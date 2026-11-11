"""
Vistas de Usuarios, Control de Roles, Asistencia de Personal y Seguridad (PIN).

Reglas de acceso:
  - Cualquier rol autenticado (`ADMIN`, `VET`, `RECEP`) puede ver el directorio
    de usuarios, sus roles y el registro de asistencia ("Presente" / "Ausente").
  - ÚNICAMENTE el Superusuario (`request.user.is_superuser`) puede crear, editar
    o eliminar usuarios/roles y registrar o modificar asistencias.
"""
import json
from datetime import datetime

from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.db.models import Count, ProtectedError, Q
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_POST
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .decorators import personal_requerido
from .models import AsistenciaPersonal, Usuario
from .permissions import LecturaPersonalEscrituraSuperusuario
from .serializers import AsistenciaPersonalSerializer, UsuarioPersonalSerializer


def _parse_fecha(valor: str | None):
    if not valor:
        return timezone.localdate()
    try:
        return datetime.strptime(valor.strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return timezone.localdate()


@login_required
@require_POST
def verificar_pin_view(request):
    """
    Verifica el PIN de 4 dígitos para desbloquear la pantalla tras 5 minutos de inactividad.
    Incluye límite de intentos fallidos en sesión para prevenir fuerza bruta.
    """
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        data = request.POST

    pin_ingresado = str(data.get("pin", "")).strip()
    usuario = request.user
    pin_correcto = getattr(usuario, "pin_seguridad", "1234") or "1234"
    max_intentos = 5

    if pin_ingresado == pin_correcto:
        request.session["pin_intentos_fallidos"] = 0
        return JsonResponse({"ok": True, "mensaje": "Sesión desbloqueada correctamente."})

    intentos = int(request.session.get("pin_intentos_fallidos", 0)) + 1
    request.session["pin_intentos_fallidos"] = intentos

    if intentos >= max_intentos:
        logout(request)
        return JsonResponse(
            {
                "ok": False,
                "sesion_cerrada": True,
                "mensaje": "Demasiados intentos fallidos de PIN. Su sesión se ha cerrado por seguridad.",
            },
            status=403,
        )

    restantes = max_intentos - intentos
    return JsonResponse(
        {
            "ok": False,
            "mensaje": f"PIN incorrecto. Intentos restantes antes de cerrar sesión: {restantes}.",
        },
        status=400,
    )


class UsuarioPersonalViewSet(viewsets.ModelViewSet):
    """
    API CRUD de Usuarios y Roles.
    - Lectura (`GET`): permitida a todo el personal autenticado.
    - Escritura (`POST`, `PUT`, `PATCH`, `DELETE`): exclusiva del Superusuario.
    """

    serializer_class = UsuarioPersonalSerializer
    permission_classes = [IsAuthenticated, LecturaPersonalEscrituraSuperusuario]

    def get_queryset(self):
        qs = (
            Usuario.objects.annotate(
                dias_presente=Count(
                    "asistencias",
                    filter=Q(asistencias__estado=AsistenciaPersonal.Estado.PRESENTE),
                ),
                dias_ausente=Count(
                    "asistencias",
                    filter=Q(asistencias__estado=AsistenciaPersonal.Estado.AUSENTE),
                ),
            )
            .prefetch_related("asistencias")
            .order_by("-is_superuser", "rol", "last_name", "first_name")
        )
        rol = self.request.query_params.get("rol")
        if rol:
            qs = qs.filter(rol=rol.upper())

        q = self.request.query_params.get("q")
        if q:
            qs = qs.filter(
                Q(username__icontains=q.strip())
                | Q(first_name__icontains=q.strip())
                | Q(last_name__icontains=q.strip())
                | Q(email__icontains=q.strip())
            )
        return qs

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.pk == request.user.pk:
            return Response(
                {"detail": "No puede eliminar su propia cuenta de superusuario."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            self.perform_destroy(instance)
            return Response(status=status.HTTP_204_NO_CONTENT)
        except ProtectedError:
            instance.is_active = False
            instance.save(update_fields=["is_active"])
            return Response(
                {
                    "detail": (
                        "El usuario posee historial clínico asociado; se desactivó su cuenta para preservar la trazabilidad."
                    )
                },
                status=status.HTTP_200_OK,
            )


class AsistenciaPersonalViewSet(viewsets.ModelViewSet):
    """
    API de Registro de Asistencia ('Presente' / 'Ausente').
    - Lectura (`GET`): todo el personal puede consultar qué días asistió cada trabajador.
    - Escritura (`POST`): exclusivo del Superusuario.
    """

    serializer_class = AsistenciaPersonalSerializer
    permission_classes = [IsAuthenticated, LecturaPersonalEscrituraSuperusuario]

    def get_queryset(self):
        qs = AsistenciaPersonal.objects.select_related("usuario", "registrado_por").order_by(
            "-fecha", "usuario__last_name", "usuario__first_name"
        )
        usuario_id = self.request.query_params.get("usuario_id")
        if usuario_id and usuario_id.isdigit():
            qs = qs.filter(usuario_id=int(usuario_id))

        fecha = self.request.query_params.get("fecha")
        if fecha:
            qs = qs.filter(fecha=_parse_fecha(fecha))

        estado = self.request.query_params.get("estado")
        if estado in (AsistenciaPersonal.Estado.PRESENTE, AsistenciaPersonal.Estado.AUSENTE):
            qs = qs.filter(estado=estado)

        return qs

    @action(detail=False, methods=["post"], url_path="marcar")
    def marcar(self, request):
        """
        Registra o actualiza la asistencia de un trabajador en una fecha dada
        únicamente como 'PRESENTE' o 'AUSENTE'. Exclusivo para Superusuario.
        """
        usuario_id = request.data.get("usuario")
        estado = str(request.data.get("estado", "")).upper().strip()
        fecha = _parse_fecha(request.data.get("fecha"))

        if estado not in (AsistenciaPersonal.Estado.PRESENTE, AsistenciaPersonal.Estado.AUSENTE):
            return Response(
                {"estado": ["El estado de asistencia solo puede ser 'PRESENTE' o 'AUSENTE'."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            trabajador = Usuario.objects.get(pk=usuario_id)
        except (Usuario.DoesNotExist, ValueError, TypeError):
            return Response(
                {"usuario": ["Trabajador no encontrado."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        registro, _ = AsistenciaPersonal.objects.update_or_create(
            usuario=trabajador,
            fecha=fecha,
            defaults={
                "estado": estado,
                "registrado_por": request.user,
            },
        )
        return Response(AsistenciaPersonalSerializer(registro).data)


@personal_requerido
def personal_usuarios_view(request):
    """
    Vista web de Gestión de Usuarios, Roles y Registro de Asistencia
    (reemplaza el acceso directo al Django Admin en el menú lateral).
    - Superusuario: CRUD completo de usuarios/roles + marcado de Presente/Ausente.
    - Otros roles: visualización de roles y consulta del registro de asistencia.
    """
    fecha_sel = _parse_fecha(request.GET.get("fecha"))
    trabajadores_qs = (
        Usuario.objects.annotate(
            dias_presente=Count(
                "asistencias",
                filter=Q(asistencias__estado=AsistenciaPersonal.Estado.PRESENTE),
            ),
            dias_ausente=Count(
                "asistencias",
                filter=Q(asistencias__estado=AsistenciaPersonal.Estado.AUSENTE),
            ),
        )
        .order_by("-is_superuser", "rol", "last_name", "first_name")
    )

    asistencias_fecha = {
        a.usuario_id: a.estado
        for a in AsistenciaPersonal.objects.filter(fecha=fecha_sel)
    }

    trabajadores = []
    for u in trabajadores_qs:
        u.estado_en_fecha = asistencias_fecha.get(u.pk)
        trabajadores.append(u)

    historial_asistencia = (
        AsistenciaPersonal.objects.select_related("usuario", "registrado_por")
        .order_by("-fecha", "usuario__last_name", "usuario__first_name")[:60]
    )

    context = {
        "pagina_activa": "personal",
        "es_superusuario": bool(request.user.is_superuser),
        "fecha_seleccionada": fecha_sel,
        "fecha_seleccionada_iso": fecha_sel.isoformat(),
        "trabajadores": trabajadores,
        "historial_asistencia": historial_asistencia,
        "roles_usuario": Usuario.Rol.choices,
        "total_presentes_fecha": sum(1 for v in asistencias_fecha.values() if v == "PRESENTE"),
        "total_ausentes_fecha": sum(1 for v in asistencias_fecha.values() if v == "AUSENTE"),
    }
    return render(request, "personal_usuarios.html", context)
