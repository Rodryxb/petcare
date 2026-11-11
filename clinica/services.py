"""
Capa de servicios: reglas de negocio independientes de HTTP.

Las vistas (API y web) delegan aquí para que la lógica sea reutilizable
desde comandos de gestión, tareas programadas o tests.
"""
from datetime import date, timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.db.models.functions import Lower
from django.utils import timezone

from usuarios.models import Usuario
from usuarios.permissions import es_personal_clinico

from .constants import (
    DIAS_CRITICOS_VACUNA,
    ESTADOS_CITA_CLINICOS,
    ESTADOS_CITA_FINALIZABLES,
    TRANSICIONES_CITA,
)
from .models import Cita, ControlVacuna, FichaClinica


# ══════════════════════════════════════════════════════════════
# Citas
# ══════════════════════════════════════════════════════════════
def cambiar_estado_cita(cita: Cita, nuevo_estado: str, usuario: Usuario) -> Cita:
    """
    Aplica una transición de estado validando:
      1. Que la transición exista en la máquina de estados.
      2. Que los estados clínicos (EN_ATENCION, FINALIZADA) los ejecute un
         VET o ADMIN, y si es VET, que sea el veterinario asignado.
      3. Que solo se inicie la atención el mismo día de la cita.
    """
    destinos = TRANSICIONES_CITA.get(cita.estado, set())
    etiqueta_nueva = Cita.Estado(nuevo_estado).label

    if nuevo_estado not in destinos:
        raise ValidationError(
            f"No se puede cambiar una cita de '{cita.get_estado_display()}' a '{etiqueta_nueva}'.",
            code="transicion_invalida",
        )

    if nuevo_estado in ESTADOS_CITA_CLINICOS:
        if not es_personal_clinico(usuario):
            raise PermissionDenied(
                f"Solo veterinarios o administradores pueden marcar una cita como '{etiqueta_nueva}'."
            )
        if usuario.rol == Usuario.Rol.VET and cita.veterinario_id != usuario.pk:
            raise PermissionDenied("Solo el veterinario asignado puede atender esta cita.")

    if nuevo_estado == Cita.Estado.EN_ATENCION and cita.fecha != timezone.localdate():
        raise ValidationError(
            "La atención solo puede iniciarse el día de la cita.", code="fecha_atencion"
        )

    cita.estado = nuevo_estado
    cita.save(update_fields=["estado", "actualizado_en"])
    return cita


def citas_para_calendario(
    desde: date,
    hasta: date,
    veterinario_id: int | None = None,
    incluir_canceladas: bool = False,
):
    """Citas en el rango [desde, hasta) listas para serializar como eventos."""
    qs = Cita.objects.select_related("mascota__tutor", "veterinario").filter(
        fecha__gte=desde, fecha__lt=hasta
    )
    if veterinario_id:
        qs = qs.filter(veterinario_id=veterinario_id)
    if not incluir_canceladas:
        qs = qs.exclude(estado=Cita.Estado.CANCELADA)
    return qs.order_by("fecha", "hora_inicio")


# ══════════════════════════════════════════════════════════════
# Fichas clínicas
# ══════════════════════════════════════════════════════════════
@transaction.atomic
def registrar_ficha(serializer) -> FichaClinica:
    """
    Guarda la ficha y, si está asociada a una cita aún abierta, la marca
    como FINALIZADA en la misma transacción (todo o nada).
    """
    ficha = serializer.save()
    cita = ficha.cita
    if cita and cita.estado in ESTADOS_CITA_FINALIZABLES:
        cita.estado = Cita.Estado.FINALIZADA
        cita.save(update_fields=["estado", "actualizado_en"])
    return ficha


# ══════════════════════════════════════════════════════════════
# Recordatorios de vacunas
# ══════════════════════════════════════════════════════════════
def controles_vigentes():
    """
    Último control de cada (mascota, tipo, producto) con vencimiento definido,
    solo para mascotas activas.

    Si a una mascota se le vuelve a aplicar la antirrábica, el registro antiguo
    queda "reemplazado" por el nuevo (vencimiento posterior) y deja de aparecer
    como vencido. Sin esta regla, el módulo generaría falsas alarmas.
    """
    reemplazo = ControlVacuna.objects.annotate(producto=Lower("nombre_producto")).filter(
        mascota=OuterRef("mascota"),
        tipo=OuterRef("tipo"),
        producto=Lower(OuterRef("nombre_producto")),
        fecha_proximo_vencimiento__gt=OuterRef("fecha_proximo_vencimiento"),
    )
    return (
        ControlVacuna.objects.filter(
            mascota__activo=True,
            fecha_proximo_vencimiento__isnull=False,
        )
        .filter(~Exists(reemplazo))
        .select_related("mascota__tutor", "aplicado_por")
        .order_by("fecha_proximo_vencimiento", "mascota__nombre")
    )


def agrupar_recordatorios(dias_criticos: int = DIAS_CRITICOS_VACUNA, hoy: date | None = None) -> dict:
    """
    Clasifica los controles vigentes en tres grupos:
      * vencidas: fecha_proximo_vencimiento <  hoy
      * criticas: hoy <= vencimiento <= hoy + dias_criticos
      * al_dia:   vencimiento >  hoy + dias_criticos
    """
    hoy = hoy or timezone.localdate()
    limite = hoy + timedelta(days=dias_criticos)
    base = controles_vigentes()
    return {
        "vencidas": base.filter(fecha_proximo_vencimiento__lt=hoy),
        "criticas": base.filter(Q(fecha_proximo_vencimiento__gte=hoy) & Q(fecha_proximo_vencimiento__lte=limite)),
        "al_dia": base.filter(fecha_proximo_vencimiento__gt=limite),
    }
