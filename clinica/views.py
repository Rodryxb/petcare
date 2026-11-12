"""
Capa de vistas (API REST con DRF y vistas tradicionales Django) para PetCare.

Seguridad:
  - Todas las vistas exigen sesión activa (`IsAuthenticated` / `@personal_requerido`).
  - Recepción (`RECEP`) puede gestionar Tutores, Mascotas y Citas.
  - La creación/edición de `FichaClinica` y la aplicación de `ControlVacuna`
    están restringidas exclusivamente a `VET` y `ADMIN`.
"""
import logging
import re
from datetime import date, datetime, timedelta
from urllib.parse import quote

from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from usuarios.decorators import personal_requerido
from usuarios.models import Usuario
from usuarios.permissions import (
    EliminarSoloAdmin,
    EliminarSoloClinico,
    EsAdminOVeterinario,
    EsAutorFichaOAdmin,
    EsPersonalClinica,
    LecturaPersonalEscrituraClinica,
    es_personal_clinico,
)

from .catalogo_pos import asegurar_catalogo_pos
from .constants import (
    DIAS_ALERTA_VENCIMIENTO_STOCK,
    DIAS_CRITICOS_MAXIMO,
    DIAS_CRITICOS_VACUNA,
    MOTIVOS_CONSULTA_CHOICES,
    OTRO_MOTIVO_CODIGO,
    OTRO_MOTIVO_ETIQUETA,
)
from .models import (
    Cita,
    ControlVacuna,
    FichaClinica,
    Mascota,
    NotificacionVacuna,
    OrdenPago,
    ProductoServicio,
    Tutor,
)
from .serializers import (
    CitaCalendarioSerializer,
    CitaSerializer,
    ControlVacunaSerializer,
    FichaClinicaSerializer,
    MascotaSerializer,
    NotificacionVacunaSerializer,
    OrdenPagoSerializer,
    ProductoServicioSerializer,
    TutorSerializer,
    VeterinarioResumenSerializer,
)

logger = logging.getLogger(__name__)
from .services import (
    agrupar_recordatorios,
    cambiar_estado_cita,
    citas_para_calendario,
    registrar_ficha,
)
from .validators import normalizar_termino_busqueda


def _parsear_fecha_iso(valor: str | None, por_defecto: date) -> date:
    """Convierte cadenas ISO ('YYYY-MM-DD' o 'YYYY-MM-DDTHH:MM:SS...') a `date`."""
    if not valor:
        return por_defecto
    limpio = valor.strip()[:10]
    try:
        return datetime.strptime(limpio, "%Y-%m-%d").date()
    except ValueError:
        return por_defecto


# ══════════════════════════════════════════════════════════════
# ViewSets de la API REST (DRF + SessionAuthentication)
# ══════════════════════════════════════════════════════════════
class TutorViewSet(viewsets.ModelViewSet):
    """
    CRUD de Tutores.
    Accesible para todo el personal autenticado (`ADMIN`, `VET`, `RECEP`).
    Soporta búsqueda en tiempo real mediante `?q=` o `?search=`.
    """

    serializer_class = TutorSerializer
    permission_classes = [IsAuthenticated, EsPersonalClinica]

    def get_queryset(self):
        qs = (
            Tutor.objects.annotate(total_mascotas=Count("mascotas", filter=Q(mascotas__activo=True)))
            .prefetch_related("mascotas")
            .order_by("apellidos", "nombres")
        )
        termino = self.request.query_params.get("q") or self.request.query_params.get("search")
        if termino:
            termino_norm = normalizar_termino_busqueda(termino)
            qs = qs.filter(
                Q(rut__icontains=termino_norm)
                | Q(nombres__icontains=termino.strip())
                | Q(apellidos__icontains=termino.strip())
                | Q(telefono__icontains=termino.strip())
                | Q(email__icontains=termino.strip())
                | Q(mascotas__nombre__icontains=termino.strip())
            ).distinct()

        activo = self.request.query_params.get("activo")
        if activo in ("true", "1", "false", "0"):
            qs = qs.filter(activo=activo in ("true", "1"))

        return qs

    def paginate_queryset(self, queryset):
        if self.request.query_params.get("sin_paginar") in ("1", "true"):
            return None
        return super().paginate_queryset(queryset)


class MascotaViewSet(viewsets.ModelViewSet):
    """
    CRUD de Mascotas.
    Accesible para todo el personal autenticado (`ADMIN`, `VET`, `RECEP`).
    """

    serializer_class = MascotaSerializer
    permission_classes = [IsAuthenticated, EsPersonalClinica]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        qs = Mascota.objects.select_related("tutor").order_by("nombre")

        tutor_id = self.request.query_params.get("tutor_id") or self.request.query_params.get("tutor")
        if tutor_id and tutor_id.isdigit():
            qs = qs.filter(tutor_id=int(tutor_id))

        especie = self.request.query_params.get("especie")
        if especie:
            qs = qs.filter(especie=especie.upper())

        activo = self.request.query_params.get("activo")
        if activo in ("true", "1", "false", "0"):
            qs = qs.filter(activo=activo in ("true", "1"))

        termino = self.request.query_params.get("q") or self.request.query_params.get("search")
        if termino:
            termino_norm = normalizar_termino_busqueda(termino)
            qs = qs.filter(
                Q(nombre__icontains=termino.strip())
                | Q(raza__icontains=termino.strip())
                | Q(color__icontains=termino.strip())
                | Q(numero_chip__icontains=termino.strip())
                | Q(tutor__rut__icontains=termino_norm)
                | Q(tutor__nombres__icontains=termino.strip())
                | Q(tutor__apellidos__icontains=termino.strip())
            )

        return qs

    def paginate_queryset(self, queryset):
        if self.request.query_params.get("sin_paginar") in ("1", "true"):
            return None
        return super().paginate_queryset(queryset)


class CitaViewSet(viewsets.ModelViewSet):
    """
    CRUD de Citas y endpoint de eventos para FullCalendar 6.
    Incluye validación anti-solapamiento en serializador, modelo y PostgreSQL.
    """

    serializer_class = CitaSerializer
    permission_classes = [IsAuthenticated, EsPersonalClinica, EliminarSoloAdmin]

    def get_queryset(self):
        qs = Cita.objects.select_related("mascota__tutor", "veterinario", "ficha").order_by(
            "fecha", "hora_inicio"
        )
        params = self.request.query_params

        veterinario_id = params.get("veterinario_id") or params.get("veterinario")
        if veterinario_id and veterinario_id.isdigit():
            qs = qs.filter(veterinario_id=int(veterinario_id))

        mascota_id = params.get("mascota_id") or params.get("mascota")
        if mascota_id and mascota_id.isdigit():
            qs = qs.filter(mascota_id=int(mascota_id))

        fecha = params.get("fecha")
        if fecha:
            qs = qs.filter(fecha=_parsear_fecha_iso(fecha, timezone.localdate()))

        estado = params.get("estado")
        if estado:
            qs = qs.filter(estado=estado.upper())

        return qs

    @action(detail=False, methods=["get"], url_path="calendario")
    def calendario(self, request):
        """
        Endpoint `/api/citas/calendario/?veterinario_id=X&start=...&end=...`
        Retorna la lista de eventos con el formato nativo de FullCalendar.
        """
        hoy = timezone.localdate()
        desde = _parsear_fecha_iso(request.query_params.get("start"), hoy - timedelta(days=60))
        hasta = _parsear_fecha_iso(request.query_params.get("end"), hoy + timedelta(days=90))

        vet_param = request.query_params.get("veterinario_id")
        veterinario_id = int(vet_param) if vet_param and vet_param.isdigit() else None
        incluir_canceladas = request.query_params.get("incluir_canceladas") in ("1", "true")

        citas = citas_para_calendario(
            desde=desde,
            hasta=hasta,
            veterinario_id=veterinario_id,
            incluir_canceladas=incluir_canceladas,
        )
        serializer = CitaCalendarioSerializer(citas, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["post"], url_path="cambiar-estado")
    def cambiar_estado(self, request, pk=None):
        """
        Cambia el estado de una cita validando la máquina de estados y el rol
        (`EN_ATENCION` y `FINALIZADA` requieren rol `VET` o `ADMIN`).
        """
        cita = self.get_object()
        nuevo_estado = str(request.data.get("estado", "")).upper().strip()
        if nuevo_estado not in dict(Cita.Estado.choices):
            return Response(
                {"estado": ["Estado de cita no válido."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        cita = cambiar_estado_cita(cita, nuevo_estado, request.user)
        return Response(CitaSerializer(cita, context={"request": request}).data)


class FichaClinicaViewSet(viewsets.ModelViewSet):
    """
    Gestión de Fichas Clínicas.
    - Lectura (`GET`): permitida a todo el personal autenticado.
    - Creación y edición (`POST`, `PUT`, `PATCH`): exclusiva para `VET` y `ADMIN`.
    """

    serializer_class = FichaClinicaSerializer
    permission_classes = [
        IsAuthenticated,
        LecturaPersonalEscrituraClinica,
        EsAutorFichaOAdmin,
    ]

    def get_queryset(self):
        qs = FichaClinica.objects.select_related(
            "mascota__tutor", "veterinario", "cita"
        ).order_by("-fecha_registro")

        mascota_id = self.request.query_params.get("mascota_id") or self.request.query_params.get("mascota")
        if mascota_id and mascota_id.isdigit():
            qs = qs.filter(mascota_id=int(mascota_id))

        veterinario_id = self.request.query_params.get("veterinario_id")
        if veterinario_id and veterinario_id.isdigit():
            qs = qs.filter(veterinario_id=int(veterinario_id))

        termino = self.request.query_params.get("q") or self.request.query_params.get("search")
        if termino:
            termino_norm = normalizar_termino_busqueda(termino)
            qs = qs.filter(
                Q(mascota__nombre__icontains=termino.strip())
                | Q(mascota__tutor__rut__icontains=termino_norm)
                | Q(diagnostico_definitivo__icontains=termino.strip())
                | Q(diagnostico_presuntivo__icontains=termino.strip())
            )

        return qs

    def perform_create(self, serializer):
        registrar_ficha(serializer)


class ControlVacunaViewSet(viewsets.ModelViewSet):
    """
    Gestión de Controles de Vacunas y Desparasitaciones.
    - Todo el personal clínico puede consultar, programar, enviar avisos al tutor
      y eliminar (botar a la basura) recordatorios de vencimiento próximo.
    - Aplicar una vacuna (`aplicar` o definir `fecha_aplicacion`) está restringido
      a `VET` y `ADMIN`.
    """

    serializer_class = ControlVacunaSerializer
    permission_classes = [IsAuthenticated, EsPersonalClinica]

    def get_queryset(self):
        qs = (
            ControlVacuna.objects.select_related("mascota__tutor", "aplicado_por")
            .prefetch_related("notificaciones__enviado_por")
            .order_by("fecha_proximo_vencimiento", "-fecha_aplicacion")
        )

        mascota_id = self.request.query_params.get("mascota_id") or self.request.query_params.get("mascota")
        if mascota_id and mascota_id.isdigit():
            qs = qs.filter(mascota_id=int(mascota_id))

        tipo = self.request.query_params.get("tipo")
        if tipo:
            qs = qs.filter(tipo=tipo.upper())

        estado = self.request.query_params.get("estado")
        if estado:
            qs = qs.filter(estado=estado.upper())

        return qs

    @action(detail=False, methods=["get"], url_path="recordatorios")
    def recordatorios(self, request):
        """
        Retorna las vacunas y controles agrupados automáticamente en 3 categorías:
          - `vencidas`: `fecha_proximo_vencimiento < hoy`
          - `criticas`: `hoy <= fecha_proximo_vencimiento <= hoy + 7 días`
          - `al_dia`:   `fecha_proximo_vencimiento > hoy + 7 días`
        Además retorna `proxima_mas_cercana` (vencimiento más cercano >= hoy)
        y `historial_notificaciones`.
        """
        dias_param = request.query_params.get("dias")
        dias = DIAS_CRITICOS_VACUNA
        if dias_param and dias_param.isdigit():
            dias = max(1, min(int(dias_param), DIAS_CRITICOS_MAXIMO))

        hoy = timezone.localdate()
        grupos = agrupar_recordatorios(dias_criticos=dias, hoy=hoy)

        vencidas_data = ControlVacunaSerializer(grupos["vencidas"], many=True).data
        criticas_data = ControlVacunaSerializer(grupos["criticas"], many=True).data
        al_dia_data = ControlVacunaSerializer(grupos["al_dia"], many=True).data
        proxima = (
            ControlVacunaSerializer(grupos["proxima_mas_cercana"]).data
            if grupos["proxima_mas_cercana"]
            else None
        )
        historial_qs = NotificacionVacuna.objects.select_related(
            "control__mascota__tutor", "enviado_por"
        ).order_by("-creado_en")[:20]

        return Response(
            {
                "fecha_corte": hoy.isoformat(),
                "dias_criticos": dias,
                "proxima_mas_cercana": proxima,
                "resumen": {
                    "vencidas": len(vencidas_data),
                    "criticas": len(criticas_data),
                    "al_dia": len(al_dia_data),
                    "total": len(vencidas_data) + len(criticas_data) + len(al_dia_data),
                },
                "vencidas": vencidas_data,
                "criticas": criticas_data,
                "al_dia": al_dia_data,
                "historial_notificaciones": NotificacionVacunaSerializer(historial_qs, many=True).data,
            }
        )

    @action(detail=True, methods=["post"], url_path="enviar-recordatorio")
    def enviar_recordatorio(self, request, pk=None):
        """
        Envía y registra un recordatorio al tutor vía Correo Electrónico o Teléfono
        (WhatsApp / SMS), informando la proximidad o vencimiento de la vacuna.
        """
        control = self.get_object()
        canal = str(request.data.get("canal") or NotificacionVacuna.Canal.EMAIL).upper().strip()
        if canal not in dict(NotificacionVacuna.Canal.choices):
            return Response(
                {"canal": ["Canal inválido. Use EMAIL, WHATSAPP o SMS."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        tutor = control.mascota.tutor
        destinatario = str(request.data.get("destinatario") or "").strip()
        if not destinatario:
            destinatario = tutor.email if canal == NotificacionVacuna.Canal.EMAIL else tutor.telefono

        if canal == NotificacionVacuna.Canal.EMAIL and ("@" not in destinatario or "." not in destinatario.split("@")[-1]):
            return Response(
                {"destinatario": ["Ingrese un correo electrónico válido para el tutor."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        digitos_tel = re.sub(r"\D", "", destinatario)
        if canal in (NotificacionVacuna.Canal.WHATSAPP, NotificacionVacuna.Canal.SMS) and len(digitos_tel) < 8:
            return Response(
                {"destinatario": ["Ingrese un número de teléfono válido (ej: +56 9 8765 4321)."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        dias = (control.fecha_proximo_vencimiento - timezone.localdate()).days if control.fecha_proximo_vencimiento else None
        fecha_fmt = control.fecha_proximo_vencimiento.strftime("%d/%m/%Y") if control.fecha_proximo_vencimiento else "por definir"
        if dias is not None and dias < 0:
            texto_plazo = f"venció hace {abs(dias)} día(s) ({fecha_fmt})"
        elif dias == 0:
            texto_plazo = f"vence HOY ({fecha_fmt})"
        elif dias is not None and dias <= 7:
            texto_plazo = f"se avecina en {dias} día(s) — en menos de una semana ({fecha_fmt})"
        else:
            texto_plazo = f"está programada para el {fecha_fmt} (en {dias} días)"

        asunto = str(request.data.get("asunto") or "").strip() or (
            f"Recordatorio PetCare: Próxima vacuna de {control.mascota.nombre} ({control.nombre_producto})"
        )
        mensaje = str(request.data.get("mensaje") or "").strip() or (
            f"Hola {tutor.nombres}, desde Clínica Veterinaria PetCare te recordamos que la próxima dosis "
            f"de '{control.nombre_producto}' para {control.mascota.nombre} ({control.mascota.get_especie_display()}) "
            f"{texto_plazo}. Contáctanos para agendar su atención."
        )

        estado_envio = "ENVIADO"
        whatsapp_url = ""
        tel_url = ""

        if canal == NotificacionVacuna.Canal.EMAIL:
            try:
                send_mail(
                    subject=asunto,
                    message=mensaje,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[destinatario],
                    fail_silently=False,
                )
                estado_envio = "ENVIADO_SMTP" if settings.EMAIL_HOST else "DESPACHADO_LOCAL"
            except Exception as exc:
                logger.warning("No se pudo enviar vía SMTP (%s); registrado en bitácora local.", exc)
                estado_envio = "REGISTRADO_LOCAL"
        else:
            if len(digitos_tel) == 9 and digitos_tel.startswith("9"):
                digitos_tel = "56" + digitos_tel
            elif len(digitos_tel) == 8:
                digitos_tel = "569" + digitos_tel
            if canal == NotificacionVacuna.Canal.WHATSAPP:
                whatsapp_url = f"https://wa.me/{digitos_tel}?text={quote(mensaje)}"
            tel_url = f"sms:+{digitos_tel}?body={quote(mensaje)}"
            estado_envio = "DESPACHADO_TELEFONO"
            logger.info("[RECORDATORIO %s] A %s (%s): %s", canal, tutor.nombre_completo, destinatario, mensaje)

        notificacion = NotificacionVacuna.objects.create(
            control=control,
            canal=canal,
            destinatario=destinatario,
            asunto=asunto if canal == NotificacionVacuna.Canal.EMAIL else f"Aviso {canal}",
            mensaje=mensaje,
            estado_envio=estado_envio,
            enviado_por=request.user,
        )

        control_refrescado = self.get_queryset().get(pk=control.pk)
        return Response(
            {
                "notificacion": NotificacionVacunaSerializer(notificacion).data,
                "control": ControlVacunaSerializer(control_refrescado).data,
                "whatsapp_url": whatsapp_url,
                "tel_url": tel_url,
                "detalle_envio": (
                    f"Recordatorio registrado y enviado vía {notificacion.get_canal_display()} a {destinatario}."
                ),
            },
            status=status.HTTP_200_OK,
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="aplicar",
        permission_classes=[IsAuthenticated, EsAdminOVeterinario],
    )
    def aplicar(self, request, pk=None):
        """
        Marca un control/vacuna como aplicado en el acto médico y recalcula
        su próximo vencimiento (por defecto +365 días en vacunas y +90 días
        en desparasitaciones/controles si no se indica otra fecha).
        Exclusivo para `VET` y `ADMIN`.
        """
        control = self.get_object()
        hoy = timezone.localdate()

        fecha_aplicacion = _parsear_fecha_iso(request.data.get("fecha_aplicacion"), hoy)
        dias_vigencia = 365 if control.tipo == ControlVacuna.Tipo.VACUNA else 90
        vencimiento_sugerido = fecha_aplicacion + timedelta(days=dias_vigencia)

        if request.data.get("fecha_proximo_vencimiento"):
            proximo_vencimiento = _parsear_fecha_iso(
                request.data.get("fecha_proximo_vencimiento"), vencimiento_sugerido
            )
        elif control.fecha_proximo_vencimiento and control.fecha_proximo_vencimiento > hoy:
            proximo_vencimiento = control.fecha_proximo_vencimiento
        else:
            proximo_vencimiento = vencimiento_sugerido

        datos = {
            "fecha_aplicacion": fecha_aplicacion,
            "fecha_proximo_vencimiento": proximo_vencimiento,
            "aplicado_por": request.user.pk,
        }
        if "observaciones" in request.data:
            datos["observaciones"] = request.data["observaciones"]

        serializer = self.get_serializer(
            control, data=datos, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class VeterinariosActivosAPIView(APIView):
    """Lista los veterinarios activos para poblar selectores de agenda."""

    permission_classes = [IsAuthenticated, EsPersonalClinica]

    def get(self, request):
        veterinarios = Usuario.objects.filter(rol=Usuario.Rol.VET, is_active=True).order_by(
            "first_name", "last_name"
        )
        return Response(VeterinarioResumenSerializer(veterinarios, many=True).data)


class ProductoServicioViewSet(viewsets.ModelViewSet):
    """
    Catálogo de Prestaciones Clínicas (Consultas, Vacunas, Inyecciones, Pabellón)
    y Productos de Tienda PetShop con lector de código de barras.
    """

    serializer_class = ProductoServicioSerializer
    permission_classes = [IsAuthenticated, EsPersonalClinica]

    def get_queryset(self):
        if not ProductoServicio.objects.exists():
            asegurar_catalogo_pos()

        qs = ProductoServicio.objects.filter(activo=True).order_by("categoria", "nombre")
        params = self.request.query_params

        categoria = params.get("categoria")
        if categoria:
            qs = qs.filter(categoria=categoria.upper())

        especie = params.get("especie")
        if especie:
            qs = qs.filter(especie_objetivo__in=[especie.upper(), ProductoServicio.EspecieObjetivo.TODOS])

        es_servicio = params.get("es_servicio")
        if es_servicio in ("1", "true", "0", "false"):
            qs = qs.filter(es_servicio=es_servicio in ("1", "true"))

        termino = params.get("q") or params.get("search")
        if termino:
            limpio = termino.strip()
            qs = qs.filter(
                Q(codigo_barras__icontains=limpio)
                | Q(sku__icontains=limpio)
                | Q(nombre__icontains=limpio)
                | Q(descripcion__icontains=limpio)
            )
        return qs

    def paginate_queryset(self, queryset):
        if self.request.query_params.get("sin_paginar") in ("1", "true", None):
            return None
        return super().paginate_queryset(queryset)

    @action(detail=False, methods=["get"], url_path="escanear")
    def escanear(self, request):
        """
        Busca un producto o servicio clínico por su código de barras EAN-13 / Code128
        o SKU (`/api/productos/escanear/?codigo=7800001000012`).
        """
        if not ProductoServicio.objects.exists():
            asegurar_catalogo_pos()

        codigo = (request.query_params.get("codigo") or "").strip()
        if not codigo:
            return Response(
                {"detail": "Debe escanear o digitar un código de barras o SKU."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        prod = (
            ProductoServicio.objects.filter(activo=True)
            .filter(Q(codigo_barras__iexact=codigo) | Q(sku__iexact=codigo))
            .first()
        )
        if not prod:
            prod = (
                ProductoServicio.objects.filter(activo=True)
                .filter(
                    Q(codigo_barras__icontains=codigo)
                    | Q(sku__icontains=codigo)
                    | Q(nombre__icontains=codigo)
                )
                .first()
            )
        if not prod:
            return Response(
                {"detail": f"No se encontró ningún producto o prestación con el código '{codigo}'."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(self.get_serializer(prod).data)

    @action(detail=False, methods=["get"], url_path="stock-vencimientos")
    def stock_vencimientos(self, request):
        """
        Devuelve alertas y listado completo de inventario clínico/PetShop:
          - Lotes vencidos (`fecha_vencimiento < hoy`)
          - Próximos a vencer (`hoy <= fecha_vencimiento <= hoy + 30d`)
          - Stock bajo o agotado (`stock <= stock_minimo`)
          - Resumen de vacunas próximas de pacientes para cruce rápido
        """
        asegurar_catalogo_pos()
        hoy = timezone.localdate()
        dias_alerta = int(request.query_params.get("dias") or DIAS_ALERTA_VENCIMIENTO_STOCK)
        dias_alerta = max(1, min(dias_alerta, 180))

        productos = list(ProductoServicio.objects.filter(activo=True).order_by("fecha_vencimiento", "stock", "nombre"))
        serializados = self.get_serializer(productos, many=True).data

        vencidos = [p for p in serializados if p["estado_vencimiento"] == "VENCIDO"]
        por_vencer = [p for p in serializados if p["estado_vencimiento"] in ("CRITICO", "POR_VENCER")]
        stock_bajo = [p for p in serializados if p["estado_stock"] in ("AGOTADO", "BAJO")]
        con_alerta = [p for p in serializados if p["tiene_alerta"]]
        vacunas_stock = [
            p for p in serializados
            if p["categoria"] in (ProductoServicio.Categoria.VACUNA, ProductoServicio.Categoria.FARMACIA, ProductoServicio.Categoria.PABELLON)
        ]

        grupos_vacunas = agrupar_recordatorios(dias_criticos=DIAS_CRITICOS_VACUNA, hoy=hoy)
        vacunas_clientes_criticas = ControlVacunaSerializer(grupos_vacunas["criticas"], many=True).data

        return Response(
            {
                "fecha_corte": hoy.isoformat(),
                "dias_alerta": dias_alerta,
                "resumen": {
                    "vencidos": len(vencidos),
                    "por_vencer": len(por_vencer),
                    "stock_bajo": len(stock_bajo),
                    "total_alertas": len(con_alerta),
                    "total_productos": len(serializados),
                    "vacunas_clientes_por_vencer": len(vacunas_clientes_criticas),
                },
                "vencidos": vencidos,
                "por_vencer": por_vencer,
                "stock_bajo": stock_bajo,
                "con_alerta": con_alerta,
                "vacunas_insumos": vacunas_stock,
                "vacunas_clientes_criticas": vacunas_clientes_criticas,
                "todos": serializados,
            }
        )

    @action(detail=True, methods=["post"], url_path="ajustar-stock")
    def ajustar_stock(self, request, pk=None):
        """
        Permite reponer stock, descontar dosis usadas (`delta`), actualizar lote
        y renovar la fecha de vencimiento desde Stock y Vencimientos.
        """
        prod = self.get_object()
        campos = []

        if "delta" in request.data and request.data["delta"] is not None:
            try:
                delta = int(request.data["delta"])
            except (TypeError, ValueError):
                return Response({"delta": ["Valor numérico inválido."]}, status=status.HTTP_400_BAD_REQUEST)
            prod.stock = max(0, prod.stock + delta)
            campos.append("stock")
        elif "stock" in request.data and request.data["stock"] is not None:
            try:
                nuevo_stock = int(request.data["stock"])
                if nuevo_stock < 0:
                    raise ValueError()
            except (TypeError, ValueError):
                return Response({"stock": ["El stock debe ser un entero mayor o igual a 0."]}, status=status.HTTP_400_BAD_REQUEST)
            prod.stock = nuevo_stock
            campos.append("stock")

        if "stock_minimo" in request.data and request.data["stock_minimo"] is not None:
            try:
                minimo = int(request.data["stock_minimo"])
                if minimo < 0:
                    raise ValueError()
            except (TypeError, ValueError):
                return Response({"stock_minimo": ["El stock mínimo debe ser mayor o igual a 0."]}, status=status.HTTP_400_BAD_REQUEST)
            prod.stock_minimo = minimo
            campos.append("stock_minimo")

        if "lote" in request.data:
            prod.lote = str(request.data["lote"] or "").strip()[:40]
            campos.append("lote")

        if "fecha_vencimiento" in request.data:
            raw_fecha = str(request.data["fecha_vencimiento"] or "").strip()
            if not raw_fecha:
                prod.fecha_vencimiento = None
            else:
                try:
                    prod.fecha_vencimiento = date.fromisoformat(raw_fecha)
                except ValueError:
                    return Response(
                        {"fecha_vencimiento": ["Formato de fecha inválido. Use YYYY-MM-DD."]},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            campos.append("fecha_vencimiento")

        if campos:
            prod.save(update_fields=[*set(campos), "actualizado_en"])

        return Response(self.get_serializer(prod).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="descartar-vencido")
    def descartar_vencido(self, request, pk=None):
        """
        Da de baja / bota a la basura un lote vencido o próximo a vencer poniendo
        el stock en 0 y dejando trazabilidad del descarte en el código de lote.
        """
        prod = self.get_object()
        lote_base = (prod.lote or prod.sku).replace(" [BOTADO]", "").strip()
        prod.stock = 0
        prod.lote = f"{lote_base[:29]} [BOTADO]"
        prod.save(update_fields=["stock", "lote", "actualizado_en"])
        return Response(
            {
                "detail": f"Lote de '{prod.nombre}' descartado (stock ajustado a 0).",
                "producto": self.get_serializer(prod).data,
            },
            status=status.HTTP_200_OK,
        )


class OrdenPagoViewSet(viewsets.ModelViewSet):
    """
    Registro de Ventas, Cobro con Tarjeta Crédito/Débito y Emisión de Boletas POS.
    """

    serializer_class = OrdenPagoSerializer
    permission_classes = [IsAuthenticated, EsPersonalClinica]

    def get_queryset(self):
        return (
            OrdenPago.objects.select_related("tutor", "mascota", "cajero", "cita")
            .prefetch_related("detalles__producto")
            .order_by("-creado_en")
        )


# ══════════════════════════════════════════════════════════════
# Vistas tradicionales de Django (Dark Mode Clínico + API Fetch)
# ══════════════════════════════════════════════════════════════
@personal_requerido
def dashboard_view(request):
    """Panel principal con KPIs en tiempo real y agenda inmediata del día."""
    hoy = timezone.localdate()
    citas_hoy_qs = (
        Cita.objects.select_related("mascota__tutor", "veterinario", "ficha")
        .filter(fecha=hoy)
        .order_by("hora_inicio")
    )

    citas_activas_hoy = citas_hoy_qs.exclude(estado=Cita.Estado.CANCELADA)
    pacientes_en_espera = citas_activas_hoy.filter(
        estado__in=[Cita.Estado.PROGRAMADA, Cita.Estado.CONFIRMADA, Cita.Estado.EN_ATENCION]
    ).count()

    grupos_vacunas = agrupar_recordatorios(dias_criticos=DIAS_CRITICOS_VACUNA, hoy=hoy)
    vacunas_alerta = grupos_vacunas["vencidas"].count() + grupos_vacunas["criticas"].count()

    context = {
        "pagina_activa": "dashboard",
        "fecha_hoy": hoy,
        "kpi_citas_hoy": citas_activas_hoy.count(),
        "kpi_pacientes_espera": pacientes_en_espera,
        "kpi_fichas_emitidas": FichaClinica.objects.count(),
        "kpi_fichas_hoy": FichaClinica.objects.filter(fecha_registro__date=hoy).count(),
        "kpi_vacunas_por_vencer": vacunas_alerta,
        "kpi_vacunas_vencidas": grupos_vacunas["vencidas"].count(),
        "kpi_vacunas_criticas": grupos_vacunas["criticas"].count(),
        "citas_hoy": citas_hoy_qs[:15],
        "puede_atender": es_personal_clinico(request.user),
        "es_admin": bool(request.user.es_admin or request.user.is_superuser),
    }
    return render(request, "dashboard.html", context)


@personal_requerido
def tutores_mascotas_view(request):
    """
    Módulo de Recepción: gestión combinada de Tutores y Mascotas
    con buscador dinámico en tiempo real y modales asíncronos (Fetch API).
    """
    tutores = (
        Tutor.objects.filter(activo=True)
        .annotate(total_mascotas=Count("mascotas", filter=Q(mascotas__activo=True)))
        .prefetch_related("mascotas")
        .order_by("apellidos", "nombres")[:200]
    )
    mascotas = Mascota.objects.filter(activo=True).select_related("tutor").order_by("nombre")[:200]
    context = {
        "pagina_activa": "tutores_mascotas",
        "tutores": tutores,
        "mascotas": mascotas,
        "total_tutores": Tutor.objects.filter(activo=True).count(),
        "total_mascotas": Mascota.objects.filter(activo=True).count(),
        "especies": Mascota.Especie.choices,
        "sexos": Mascota.Sexo.choices,
        "tipos_control": ControlVacuna.Tipo.choices,
    }
    return render(request, "tutores_mascotas.html", context)


@personal_requerido
def calendario_citas_view(request):
    """
    Módulo de Calendario Clínico con FullCalendar 6, filtro por veterinario
    y modal de agendamiento con validación anti-solapamiento.
    """
    veterinarios = Usuario.objects.filter(rol=Usuario.Rol.VET, is_active=True).order_by(
        "first_name", "last_name"
    )
    tutores = Tutor.objects.filter(activo=True).order_by("apellidos", "nombres")
    mascotas = Mascota.objects.filter(activo=True).select_related("tutor").order_by("nombre")
    context = {
        "pagina_activa": "calendario",
        "veterinarios": veterinarios,
        "tutores": tutores,
        "mascotas": mascotas,
        "especies": Mascota.Especie.choices,
        "sexos": Mascota.Sexo.choices,
        "tipos_control": ControlVacuna.Tipo.choices,
        "estados_cita": Cita.Estado.choices,
        "motivos_consulta": MOTIVOS_CONSULTA_CHOICES,
        "otro_motivo_codigo": OTRO_MOTIVO_CODIGO,
        "otro_motivo_etiqueta": OTRO_MOTIVO_ETIQUETA,
        "fecha_hoy": timezone.localdate().isoformat(),
        "puede_atender": es_personal_clinico(request.user),
        "es_admin": bool(request.user.es_admin or request.user.is_superuser),
    }
    return render(request, "calendario_citas.html", context)


@personal_requerido
def ficha_clinica_view(request, mascota_id: int | None = None):
    """
    Expediente médico digital:
      - Timeline vertical de atenciones previas de la mascota.
      - Formulario clínico en pestañas (Examen Físico, Diagnóstico, Prescripción).
        Restringido en escritura a `VET` y `ADMIN`.
    """
    mascotas = Mascota.objects.filter(activo=True).select_related("tutor").order_by("nombre")

    if mascota_id is None:
        param_mascota = request.GET.get("mascota_id")
        if param_mascota and param_mascota.isdigit():
            mascota_id = int(param_mascota)

    mascota_actual = None
    if mascota_id is not None:
        mascota_actual = get_object_or_404(
            Mascota.objects.select_related("tutor"), pk=mascota_id
        )
    elif mascotas.exists():
        mascota_actual = mascotas.first()

    fichas_previas = []
    citas_mascota = []
    controles_mascota = []
    if mascota_actual:
        fichas_previas = (
            FichaClinica.objects.filter(mascota=mascota_actual)
            .select_related("veterinario", "cita")
            .order_by("-fecha_registro")
        )
        citas_mascota = (
            Cita.objects.filter(
                mascota=mascota_actual,
                estado__in=[
                    Cita.Estado.PROGRAMADA,
                    Cita.Estado.CONFIRMADA,
                    Cita.Estado.EN_ATENCION,
                ],
                ficha__isnull=True,
            )
            .select_related("veterinario")
            .order_by("fecha", "hora_inicio")
        )
        controles_mascota = (
            ControlVacuna.objects.filter(mascota=mascota_actual)
            .select_related("aplicado_por")
            .order_by("-fecha_proximo_vencimiento")
        )

    veterinarios = Usuario.objects.filter(rol=Usuario.Rol.VET, is_active=True).order_by(
        "first_name", "last_name"
    )
    cita_seleccionada_id = request.GET.get("cita_id")

    tutores = Tutor.objects.filter(activo=True).order_by("apellidos", "nombres")
    context = {
        "pagina_activa": "ficha_clinica",
        "mascotas": mascotas,
        "tutores": tutores,
        "especies": Mascota.Especie.choices,
        "sexos": Mascota.Sexo.choices,
        "tipos_control": ControlVacuna.Tipo.choices,
        "mascota_actual": mascota_actual,
        "fichas_previas": fichas_previas,
        "citas_mascota": citas_mascota,
        "controles_mascota": controles_mascota,
        "veterinarios": veterinarios,
        "cita_seleccionada_id": int(cita_seleccionada_id) if cita_seleccionada_id and cita_seleccionada_id.isdigit() else None,
        "puede_editar_ficha": es_personal_clinico(request.user),
    }
    return render(request, "ficha_clinica.html", context)


@personal_requerido
def ficha_clinica_imprimir_view(request, mascota_id: int):
    """
    Vista limpia optimizada para impresión/PDF de la ficha clínica completa
    del paciente (datos, fotografía, tutor, complementos, vacunas y consultas),
    pensada para entregar al tutor o derivar a otra institución.
    """
    mascota = get_object_or_404(Mascota.objects.select_related("tutor"), pk=mascota_id)
    fichas_previas = (
        FichaClinica.objects.filter(mascota=mascota)
        .select_related("veterinario", "cita")
        .order_by("-fecha_registro")
    )
    controles_mascota = (
        ControlVacuna.objects.filter(mascota=mascota)
        .select_related("aplicado_por")
        .order_by("-fecha_aplicacion", "-fecha_proximo_vencimiento")
    )
    return render(
        request,
        "ficha_clinica_imprimir.html",
        {
            "mascota": mascota,
            "fichas_previas": fichas_previas,
            "controles_mascota": controles_mascota,
            "fecha_emision": timezone.localtime(),
            "auto_print": request.GET.get("auto") == "1",
        },
    )


@personal_requerido
def recordatorios_view(request):
    """
    Panel clínico de seguimiento de vacunas con cuenta regresiva, alerta a 1 semana,
    notificación por correo/teléfono, eliminación de vencimientos próximos y
    próxima fecha de vencimiento más cercana.
    """
    hoy = timezone.localdate()
    grupos = agrupar_recordatorios(dias_criticos=DIAS_CRITICOS_VACUNA, hoy=hoy)
    mascotas = Mascota.objects.filter(activo=True).select_related("tutor").order_by("nombre")
    historial_notificaciones = (
        NotificacionVacuna.objects.select_related(
            "control",
            "control__mascota",
            "control__mascota__tutor",
            "enviado_por",
        )
        .order_by("-creado_en")[:25]
    )

    vencidas_count = grupos["vencidas"].count()
    criticas_count = grupos["criticas"].count()
    al_dia_count = grupos["al_dia"].count()

    context = {
        "pagina_activa": "recordatorios",
        "fecha_hoy": hoy,
        "dias_criticos": DIAS_CRITICOS_VACUNA,
        "proxima_mas_cercana": grupos["proxima_mas_cercana"],
        "vencidas": grupos["vencidas"],
        "criticas": grupos["criticas"],
        "al_dia": grupos["al_dia"],
        "historial_notificaciones": historial_notificaciones,
        "resumen": {
            "vencidas": vencidas_count,
            "criticas": criticas_count,
            "al_dia": al_dia_count,
            "total": vencidas_count + criticas_count + al_dia_count,
        },
        "mascotas": mascotas,
        "tipos_control": ControlVacuna.Tipo.choices,
        "puede_aplicar_vacuna": es_personal_clinico(request.user),
    }
    return render(request, "recordatorios.html", context)


@personal_requerido
def avisos_clientes_view(request):
    """
    Apartado dedicado bajo 'Operación Clínica': Avisos a Clientes.
    Centraliza las ALERTAS DE PROXIMIDAD (<= 1 semana), controles vencidos,
    envío directo por Correo / Teléfono (WhatsApp / SMS) y bitácora de avisos.
    """
    hoy = timezone.localdate()
    grupos = agrupar_recordatorios(dias_criticos=DIAS_CRITICOS_VACUNA, hoy=hoy)
    criticas_count = grupos["criticas"].count()
    vencidas_count = grupos["vencidas"].count()
    enviados_count = NotificacionVacuna.objects.count()

    context = {
        "pagina_activa": "avisos_clientes",
        "fecha_hoy": hoy,
        "dias_criticos": DIAS_CRITICOS_VACUNA,
        "resumen": {
            "criticas": criticas_count,
            "vencidas": vencidas_count,
            "pendientes_aviso": criticas_count + vencidas_count,
            "enviados": enviados_count,
        },
        "puede_aplicar_vacuna": es_personal_clinico(request.user),
    }
    return render(request, "avisos_clientes.html", context)


@personal_requerido
def stock_vencimientos_view(request):
    """
    Apartado dedicado bajo 'Operación Clínica': Stock y Vencimientos.
    Alerta en la parte superior las vacunas, medicamentos e insumos próximos a
    vencer o con stock crítico, y permite reponer lotes o botar vencidos.
    """
    asegurar_catalogo_pos()
    hoy = timezone.localdate()
    context = {
        "pagina_activa": "stock_vencimientos",
        "fecha_hoy": hoy,
        "dias_alerta": DIAS_ALERTA_VENCIMIENTO_STOCK,
        "categorias": ProductoServicio.Categoria.choices,
        "especies": ProductoServicio.EspecieObjetivo.choices,
    }
    return render(request, "stock_vencimientos.html", context)


@personal_requerido
def caja_pos_view(request):
    """
    Módulo de Caja Clínica y Punto de Venta (POS tipo Supermercado):
      - Cobro de Consultas ($20.000), Vacunas ($15.000), Inyecciones ($5.000),
        Anestesia, Eutanasia y artículos de la Tienda PetShop.
      - Lector de Código de Barras funcional (Pistola USB / Teclado, Cámara en vivo y Simulador).
      - Terminal de Pago con Tarjeta de Crédito / Débito (Redcompra / Transbank),
        Efectivo (con cálculo de vuelto) y Transferencia.
    """
    asegurar_catalogo_pos()
    hoy = timezone.localdate()

    productos = ProductoServicio.objects.filter(activo=True).order_by("categoria", "nombre")
    tutores = Tutor.objects.filter(activo=True).order_by("apellidos", "nombres")
    mascotas = Mascota.objects.filter(activo=True).select_related("tutor").order_by("nombre")
    ultimas_boletas = (
        OrdenPago.objects.select_related("tutor", "mascota", "cajero")
        .prefetch_related("detalles")
        .order_by("-creado_en")[:20]
    )
    recaudacion_hoy = (
        OrdenPago.objects.filter(creado_en__date=hoy, estado=OrdenPago.Estado.PAGADO)
        .aggregate(total=Sum("total"))["total"]
        or 0
    )
    boletas_hoy = OrdenPago.objects.filter(creado_en__date=hoy, estado=OrdenPago.Estado.PAGADO).count()

    context = {
        "pagina_activa": "caja_pos",
        "productos": productos,
        "categorias_pos": ProductoServicio.Categoria.choices,
        "tutores": tutores,
        "mascotas": mascotas,
        "ultimas_boletas": ultimas_boletas,
        "recaudacion_hoy": recaudacion_hoy,
        "boletas_hoy": boletas_hoy,
    }
    return render(request, "caja_pos.html", context)


@personal_requerido
def tienda_view(request):
    """
    Módulo de Tienda PetShop & Consultor de Precios:
      - Catálogo visual con fotos, descripciones, stock y códigos de barra:
        * Comida Perro, Gato y Animales Exóticos
        * Vacunas de varios tipos, Anestesia, Eutanasia
        * Collares, Antipulgas, Calmantes, Camas y Areneros
      - Consultor de precios por código de barras y carrito conectado a Caja POS.
    """
    asegurar_catalogo_pos()
    productos = ProductoServicio.objects.filter(activo=True).order_by("categoria", "nombre")
    tutores = Tutor.objects.filter(activo=True).order_by("apellidos", "nombres")
    mascotas = Mascota.objects.filter(activo=True).select_related("tutor").order_by("nombre")

    context = {
        "pagina_activa": "tienda",
        "productos": productos,
        "categorias_tienda": ProductoServicio.Categoria.choices,
        "especies_filtro": ProductoServicio.EspecieObjetivo.choices,
        "tutores": tutores,
        "mascotas": mascotas,
    }
    return render(request, "tienda.html", context)
