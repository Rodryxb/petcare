"""Context processors globales de PetCare (alertas en tiempo real para la barra lateral)."""
from datetime import timedelta

from django.db.models import F, Q
from django.utils import timezone

from .constants import DIAS_ALERTA_VENCIMIENTO_STOCK, DIAS_CRITICOS_VACUNA
from .models import ProductoServicio
from .services import controles_vigentes


def sidebar_alertas(request):
    """
    Expone contadores compactos de alertas para los ítems del menú lateral
    bajo 'Operación Clínica':
      - Avisos a clientes (vacunas de pacientes por vencer en <= 7 días o vencidas).
      - Stock y vencimientos (vacunas/productos vencidos, por vencer <= 30 días o stock bajo).
    """
    user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False):
        return {}

    try:
        hoy = timezone.localdate()
        fecha_vacunas = hoy + timedelta(days=DIAS_CRITICOS_VACUNA)
        avisos_pendientes = controles_vigentes().filter(
            fecha_proximo_vencimiento__isnull=False,
            fecha_proximo_vencimiento__lte=fecha_vacunas,
        ).count()

        fecha_stock = hoy + timedelta(days=DIAS_ALERTA_VENCIMIENTO_STOCK)
        stock_alertas = ProductoServicio.objects.filter(activo=True).filter(
            Q(fecha_vencimiento__isnull=False, fecha_vencimiento__lte=fecha_stock)
            | (
                Q(stock__lte=F("stock_minimo"))
                & (
                    Q(es_servicio=False)
                    | Q(categoria__in=[ProductoServicio.Categoria.VACUNA, ProductoServicio.Categoria.PABELLON])
                )
            )
        ).count()

        return {
            "sidebar_avisos_count": avisos_pendientes,
            "sidebar_stock_count": stock_alertas,
        }
    except Exception:
        return {
            "sidebar_avisos_count": 0,
            "sidebar_stock_count": 0,
        }
