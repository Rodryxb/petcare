"""
Usuarios del sistema PetCare.

El sistema es de uso exclusivo del personal de la clínica, por lo que cada
usuario tiene un único rol que determina sus permisos.
"""
from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models
from django.utils import timezone


class Usuario(AbstractUser):
    """Usuario del personal clínico con control de acceso basado en roles."""

    class Rol(models.TextChoices):
        ADMIN = "ADMIN", "Administrador"
        VET = "VET", "Veterinario"
        RECEP = "RECEP", "Recepcionista"

    rol = models.CharField(
        "rol",
        max_length=10,
        choices=Rol.choices,
        default=Rol.RECEP,  # Principio de mínimo privilegio
        db_index=True,
    )
    email = models.EmailField("correo electrónico", unique=True)
    telefono = models.CharField("teléfono", max_length=20, blank=True)
    pin_seguridad = models.CharField(
        "PIN de desbloqueo (4 dígitos)",
        max_length=4,
        default="1234",
        help_text="PIN numérico de 4 dígitos para desbloquear la sesión tras inactividad.",
    )

    objects = UserManager()

    REQUIRED_FIELDS = ["email", "first_name", "last_name"]

    class Meta:
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"
        ordering = ["last_name", "first_name"]

    def __str__(self):
        nombre = self.get_full_name() or self.username
        return f"{nombre} ({self.get_rol_display()})"

    def save(self, *args, **kwargs):
        # Un superusuario siempre es Administrador (p. ej. creado con createsuperuser).
        if self.is_superuser:
            self.rol = self.Rol.ADMIN
        super().save(*args, **kwargs)

    # ─── Helpers de rol ───────────────────────────────────────
    @property
    def es_admin(self) -> bool:
        return self.rol == self.Rol.ADMIN

    @property
    def es_veterinario(self) -> bool:
        return self.rol == self.Rol.VET

    @property
    def es_recepcionista(self) -> bool:
        return self.rol == self.Rol.RECEP


class AsistenciaPersonal(models.Model):
    """
    Registro diario de asistencia del personal de la clínica.
    Cada trabajador tiene un estado ('PRESENTE' o 'AUSENTE') por fecha.
    """

    class Estado(models.TextChoices):
        PRESENTE = "PRESENTE", "Presente"
        AUSENTE = "AUSENTE", "Ausente"

    usuario = models.ForeignKey(
        Usuario,
        on_delete=models.CASCADE,
        related_name="asistencias",
        verbose_name="trabajador",
    )
    fecha = models.DateField("fecha", default=timezone.localdate, db_index=True)
    estado = models.CharField(
        "estado",
        max_length=10,
        choices=Estado.choices,
        default=Estado.PRESENTE,
        db_index=True,
    )
    registrado_por = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="asistencias_marcadas",
        verbose_name="registrado por",
    )
    actualizado_en = models.DateTimeField("actualizado en", auto_now=True)

    class Meta:
        verbose_name = "asistencia de personal"
        verbose_name_plural = "asistencias del personal"
        ordering = ["-fecha", "usuario__last_name", "usuario__first_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["usuario", "fecha"],
                name="asistencia_unica_usuario_fecha",
            )
        ]

    def __str__(self):
        nombre = self.usuario.get_full_name() or self.usuario.username
        return f"{self.fecha:%d-%m-%Y} | {nombre} -> {self.get_estado_display()}"

