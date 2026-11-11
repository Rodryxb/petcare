"""
Capa de vistas (API REST con DRF y vistas tradicionales Django) para PetCare.

Seguridad:
  - Todas las vistas exigen sesión activa (`IsAuthenticated` / `@personal_requerido`).
  - Recepción (`RECEP`) puede gestionar Tutores, Mascotas y Citas.
  - La creación/edición de `FichaClinica` y la aplicación de `ControlVacuna`
    están restringidas exclusivamente a `VET` y `ADMIN`.
"""
from datetime import date, datetime, timedelta

from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
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

from .constants import DIAS_CRITICOS_MAXIMO, DIAS_CRITICOS_VACUNA
from .models import Cita, ControlVacuna, FichaClinica, Mascota, Tutor
from .serializers import (
    CitaCalendarioSerializer,
    CitaSerializer,
    ControlVacunaSerializer,
    FichaClinicaSerializer,
    MascotaSerializer,
    TutorSerializer,
    VeterinarioResumenSerializer,
)
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
            Tutor.objects.annotate(total_mascotas=Count("mascotas"))
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


class MascotaViewSet(viewsets.ModelViewSet):
    """
    CRUD de Mascotas.
    Accesible para todo el personal autenticado (`ADMIN`, `VET`, `RECEP`).
    """

    serializer_class = MascotaSerializer
    permission_classes = [IsAuthenticated, EsPersonalClinica]

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
                | Q(tutor__rut__icontains=termino_norm)
                | Q(tutor__nombres__icontains=termino.strip())
                | Q(tutor__apellidos__icontains=termino.strip())
            )

        return qs


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
    - Recepción puede consultar y programar recordatorios pendientes.
    - Aplicar una vacuna (`aplicar` o definir `fecha_aplicacion`) está restringido
      a `VET` y `ADMIN`.
    """

    serializer_class = ControlVacunaSerializer
    permission_classes = [IsAuthenticated, EsPersonalClinica, EliminarSoloClinico]

    def get_queryset(self):
        qs = ControlVacuna.objects.select_related(
            "mascota__tutor", "aplicado_por"
        ).order_by("fecha_proximo_vencimiento", "-fecha_aplicacion")

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

        return Response(
            {
                "fecha_corte": hoy.isoformat(),
                "dias_criticos": dias,
                "resumen": {
                    "vencidas": len(vencidas_data),
                    "criticas": len(criticas_data),
                    "al_dia": len(al_dia_data),
                    "total": len(vencidas_data) + len(criticas_data) + len(al_dia_data),
                },
                "vencidas": vencidas_data,
                "criticas": criticas_data,
                "al_dia": al_dia_data,
            }
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
    }
    return render(request, "dashboard.html", context)


@personal_requerido
def tutores_mascotas_view(request):
    """
    Módulo de Recepción: gestión combinada de Tutores y Mascotas
    con buscador dinámico en tiempo real y modales asíncronos (Fetch API).
    """
    tutores = (
        Tutor.objects.annotate(total_mascotas=Count("mascotas"))
        .prefetch_related("mascotas")
        .order_by("apellidos", "nombres")[:50]
    )
    mascotas = Mascota.objects.select_related("tutor").order_by("nombre")[:50]
    context = {
        "pagina_activa": "tutores_mascotas",
        "tutores": tutores,
        "mascotas": mascotas,
        "total_tutores": Tutor.objects.count(),
        "total_mascotas": Mascota.objects.count(),
        "especies": Mascota.Especie.choices,
        "sexos": Mascota.Sexo.choices,
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
    mascotas = Mascota.objects.filter(activo=True).select_related("tutor").order_by("nombre")
    context = {
        "pagina_activa": "calendario",
        "veterinarios": veterinarios,
        "mascotas": mascotas,
        "estados_cita": Cita.Estado.choices,
        "fecha_hoy": timezone.localdate().isoformat(),
        "puede_atender": es_personal_clinico(request.user),
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

    context = {
        "pagina_activa": "ficha_clinica",
        "mascotas": mascotas,
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
def recordatorios_view(request):
    """
    Tablero visual estilo semáforo / Kanban con 3 columnas:
      - Vencidas (`< hoy`)
      - Próximos 7 Días (`hoy` a `hoy + 7`)
      - Al Día (`> hoy + 7`)
    """
    hoy = timezone.localdate()
    grupos = agrupar_recordatorios(dias_criticos=DIAS_CRITICOS_VACUNA, hoy=hoy)
    mascotas = Mascota.objects.filter(activo=True).select_related("tutor").order_by("nombre")

    context = {
        "pagina_activa": "recordatorios",
        "fecha_hoy": hoy,
        "dias_criticos": DIAS_CRITICOS_VACUNA,
        "vencidas": grupos["vencidas"],
        "criticas": grupos["criticas"],
        "al_dia": grupos["al_dia"],
        "resumen": {
            "vencidas": grupos["vencidas"].count(),
            "criticas": grupos["criticas"].count(),
            "al_dia": grupos["al_dia"].count(),
        },
        "mascotas": mascotas,
        "tipos_control": ControlVacuna.Tipo.choices,
        "puede_aplicar_vacuna": es_personal_clinico(request.user),
    }
    return render(request, "recordatorios.html", context)
