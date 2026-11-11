"""
Comando de gestión `python manage.py actualizar_vacunas_vencidas`:
Marca automáticamente como `VENCIDO` todos los controles preventivos cuya
`fecha_proximo_vencimiento` sea anterior a la fecha actual.
Pensado para ejecutarse mediante cron o systemd timer en AWS EC2.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from clinica.models import ControlVacuna


class Command(BaseCommand):
    help = "Actualiza a estado VENCIDO las vacunas y controles cuya fecha de vencimiento ya expiró."

    def handle(self, *args, **options):
        hoy = timezone.localdate()
        actualizados = ControlVacuna.objects.actualizar_vencidos()
        self.stdout.write(
            self.style.SUCCESS(
                f"[{hoy.isoformat()}] Controles actualizados a VENCIDO: {actualizados}"
            )
        )
