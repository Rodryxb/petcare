"""
Modelos del dominio clínico de PetCare.

Jerarquía principal:
    Tutor 1──N Mascota 1──N Cita
                       1──N FichaClinica (0..1 Cita)
                       1──N ControlVacuna
"""
from datetime import date, timedelta

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import RangeOperators
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import IntegrityError, models, transaction
from django.db.models import ExpressionWrapper, F, Q, Value
from django.utils import timezone

from .db import TsRange
from .validators import normalizar_rut, validar_rut, validar_telefono

ROL_VETERINARIO = "VET"
LIMITE_VETERINARIO = {"rol": ROL_VETERINARIO, "is_active": True}


# ══════════════════════════════════════════════════════════════
# Base
# ══════════════════════════════════════════════════════════════
class ModeloConTimestamps(models.Model):
    """Agrega trazabilidad de creación/modificación a todos los modelos."""

    creado_en = models.DateTimeField("creado en", auto_now_add=True)
    actualizado_en = models.DateTimeField("actualizado en", auto_now=True)

    class Meta:
        abstract = True


def _validar_es_veterinario(usuario, campo: str = "veterinario") -> None:
    """
    `limit_choices_to` solo filtra formularios/admin; esta validación
    garantiza la regla también desde la API, shell o scripts.
    """
    if usuario is not None and usuario.rol != ROL_VETERINARIO:
        raise ValidationError(
            {campo: "El usuario asignado debe tener rol Veterinario."},
            code="no_es_veterinario",
        )


# ══════════════════════════════════════════════════════════════
# Tutor
# ══════════════════════════════════════════════════════════════
class Tutor(ModeloConTimestamps):
    """Responsable legal de una o más mascotas."""

    rut = models.CharField(
        "RUT",
        max_length=12,
        unique=True,  # unique=True crea automáticamente un índice B-tree
        db_index=True,
        validators=[validar_rut],
        help_text="Formato: 12345678-9 (se normaliza automáticamente).",
    )
    nombres = models.CharField("nombres", max_length=100)
    apellidos = models.CharField("apellidos", max_length=100)
    telefono = models.CharField("teléfono", max_length=20, validators=[validar_telefono])
    email = models.EmailField("correo electrónico", blank=True)
    direccion = models.CharField("dirección", max_length=255, blank=True)
    activo = models.BooleanField("activo", default=True)

    class Meta:
        verbose_name = "tutor"
        verbose_name_plural = "tutores"
        ordering = ["apellidos", "nombres"]
        indexes = [
            models.Index(fields=["apellidos", "nombres"], name="tutor_nombre_completo_idx"),
        ]

    def __str__(self):
        return f"{self.nombre_completo} ({self.rut})"

    @property
    def nombre_completo(self) -> str:
        return f"{self.nombres} {self.apellidos}".strip()

    def clean(self):
        # Se normaliza en clean() porque Django ejecuta validate_unique()
        # DESPUÉS de clean(): así la unicidad se evalúa sobre el RUT canónico.
        self.rut = normalizar_rut(self.rut)

    def save(self, *args, **kwargs):
        self.rut = normalizar_rut(self.rut)
        super().save(*args, **kwargs)


# ══════════════════════════════════════════════════════════════
# Mascota
# ══════════════════════════════════════════════════════════════
class Mascota(ModeloConTimestamps):
    """Paciente de la clínica."""

    class Especie(models.TextChoices):
        CANINO = "CANINO", "Canino"
        FELINO = "FELINO", "Felino"
        EXOTICO = "EXOTICO", "Exótico"

    class Sexo(models.TextChoices):
        MACHO = "MACHO", "Macho"
        HEMBRA = "HEMBRA", "Hembra"

    tutor = models.ForeignKey(
        Tutor,
        on_delete=models.PROTECT,  # No se pierde historial clínico al borrar un tutor
        related_name="mascotas",
        verbose_name="tutor",
    )
    nombre = models.CharField("nombre", max_length=100)
    especie = models.CharField("especie", max_length=10, choices=Especie.choices, db_index=True)
    raza = models.CharField("raza", max_length=100, blank=True)
    sexo = models.CharField("sexo", max_length=10, choices=Sexo.choices)
    fecha_nacimiento = models.DateField(
        "fecha de nacimiento",
        null=True,
        blank=True,
        help_text="Puede ser aproximada si se desconoce la fecha exacta.",
    )
    peso = models.DecimalField(
        "peso (kg)",
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0.01)],
    )
    alergias = models.TextField("alergias", blank=True)
    observaciones = models.TextField("observaciones", blank=True)
    activo = models.BooleanField("activo", default=True, help_text="Desmarcar si falleció o se dio de baja.")

    class Meta:
        verbose_name = "mascota"
        verbose_name_plural = "mascotas"
        ordering = ["nombre"]
        indexes = [
            models.Index(fields=["tutor", "nombre"], name="mascota_tutor_nombre_idx"),
        ]

    def __str__(self):
        return f"{self.nombre} ({self.get_especie_display()}) - {self.tutor.nombre_completo}"

    def clean(self):
        if self.fecha_nacimiento and self.fecha_nacimiento > timezone.localdate():
            raise ValidationError(
                {"fecha_nacimiento": "La fecha de nacimiento no puede ser futura."}
            )

    @property
    def edad(self) -> str:
        """Edad legible, p. ej. '3 años, 2 meses'."""
        if not self.fecha_nacimiento:
            return "Desconocida"
        hoy = timezone.localdate()
        meses = (hoy.year - self.fecha_nacimiento.year) * 12 + (hoy.month - self.fecha_nacimiento.month)
        if hoy.day < self.fecha_nacimiento.day:
            meses -= 1
        anios, meses = divmod(max(meses, 0), 12)
        partes = []
        if anios:
            partes.append(f"{anios} año{'s' if anios != 1 else ''}")
        if meses or not anios:
            partes.append(f"{meses} mes{'es' if meses != 1 else ''}")
        return ", ".join(partes)


# ══════════════════════════════════════════════════════════════
# Cita
# ══════════════════════════════════════════════════════════════
class Cita(ModeloConTimestamps):
    """
    Cita agendada para una mascota con un veterinario.

    REGLA ANTI-SOLAPAMIENTO (defensa en profundidad):
      1. ``clean()``: consulta ORM con ``Q`` -> mensaje de error claro al usuario.
      2. ``save()``: fuerza ``full_clean()`` para que la API/shell no la salte.
      3. ``ExclusionConstraint`` en PostgreSQL -> garantía absoluta incluso
         ante condiciones de carrera (dos recepcionistas agendando a la vez).
    Las citas CANCELADAS no bloquean el horario.
    """

    class Estado(models.TextChoices):
        PROGRAMADA = "PROGRAMADA", "Programada"
        CONFIRMADA = "CONFIRMADA", "Confirmada"
        EN_ATENCION = "EN_ATENCION", "En atención"
        FINALIZADA = "FINALIZADA", "Finalizada"
        CANCELADA = "CANCELADA", "Cancelada"

    CONSTRAINT_SOLAPAMIENTO = "cita_sin_solapamiento_veterinario"
    CONSTRAINT_HORARIO = "cita_hora_fin_posterior_inicio"

    mascota = models.ForeignKey(
        Mascota,
        on_delete=models.PROTECT,
        related_name="citas",
        verbose_name="mascota",
    )
    veterinario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="citas_asignadas",
        limit_choices_to=LIMITE_VETERINARIO,
        verbose_name="veterinario",
    )
    fecha = models.DateField("fecha", db_index=True)
    hora_inicio = models.TimeField("hora de inicio")
    hora_fin = models.TimeField("hora de término")
    motivo = models.CharField("motivo de consulta", max_length=255)
    estado = models.CharField(
        "estado",
        max_length=15,
        choices=Estado.choices,
        default=Estado.PROGRAMADA,
        db_index=True,
    )

    class Meta:
        verbose_name = "cita"
        verbose_name_plural = "citas"
        ordering = ["fecha", "hora_inicio"]
        indexes = [
            # Consulta típica: agenda de un veterinario en un día.
            models.Index(fields=["veterinario", "fecha", "hora_inicio"], name="cita_agenda_vet_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(hora_fin__gt=F("hora_inicio")),
                name="cita_hora_fin_posterior_inicio",
                violation_error_message="La hora de término debe ser posterior a la hora de inicio.",
            ),
            # Requiere la extensión btree_gist (se habilita en la migración 0001).
            ExclusionConstraint(
                name="cita_sin_solapamiento_veterinario",
                index_type="GIST",
                expressions=[
                    ("veterinario", RangeOperators.EQUAL),
                    (
                        TsRange(
                            ExpressionWrapper(F("fecha") + F("hora_inicio"), output_field=models.DateTimeField()),
                            ExpressionWrapper(F("fecha") + F("hora_fin"), output_field=models.DateTimeField()),
                            Value("[)"),
                        ),
                        RangeOperators.OVERLAPS,
                    ),
                ],
                condition=~Q(estado="CANCELADA"),
                violation_error_message=(
                    "El veterinario ya tiene una cita que se superpone con este horario."
                ),
            ),
        ]

    def __str__(self):
        return (
            f"{self.fecha:%d-%m-%Y} {self.hora_inicio:%H:%M}-{self.hora_fin:%H:%M} | "
            f"{self.mascota.nombre} con {self.veterinario.get_full_name() or self.veterinario.username} "
            f"[{self.get_estado_display()}]"
        )

    # ─── Reglas de negocio ────────────────────────────────────
    def get_citas_solapadas(self):
        """
        Citas activas del mismo veterinario, en la misma fecha, cuyo horario
        se superpone con el de esta cita:

            existente.hora_inicio < nueva.hora_fin
            AND existente.hora_fin > nueva.hora_inicio
        """
        filtro = (
            Q(veterinario_id=self.veterinario_id)
            & Q(fecha=self.fecha)
            & Q(hora_inicio__lt=self.hora_fin)
            & Q(hora_fin__gt=self.hora_inicio)
            & ~Q(estado=self.Estado.CANCELADA)
        )
        qs = Cita.objects.filter(filtro).select_related("mascota")
        if self.pk:
            qs = qs.exclude(pk=self.pk)  # Al editar, no compararse consigo misma
        return qs

    def clean(self):
        super().clean()
        errores = {}

        if self.hora_inicio and self.hora_fin and self.hora_fin <= self.hora_inicio:
            errores["hora_fin"] = "La hora de término debe ser posterior a la hora de inicio."

        if self.veterinario_id:
            try:
                _validar_es_veterinario(self.veterinario)
            except ValidationError as exc:
                errores.update(exc.message_dict)

        if errores:
            raise ValidationError(errores)

        # Validación anti-solapamiento (solo si la cita ocupa horario).
        campos_completos = all([self.veterinario_id, self.fecha, self.hora_inicio, self.hora_fin])
        if campos_completos and self.estado != self.Estado.CANCELADA:
            conflicto = self.get_citas_solapadas().first()
            if conflicto:
                raise ValidationError(
                    f"El veterinario ya tiene una cita el {conflicto.fecha:%d-%m-%Y} de "
                    f"{conflicto.hora_inicio:%H:%M} a {conflicto.hora_fin:%H:%M} "
                    f"({conflicto.mascota.nombre}) que se superpone con el horario solicitado.",
                    code="cita_solapada",
                )

    def get_constraints(self):
        """
        Omite la ExclusionConstraint en la validación Python (validate_constraints):
        clean() ya cubre esa regla con un mensaje más detallado, y así no se
        duplica el error en formularios. La BD la sigue haciendo cumplir siempre.
        """
        return [
            (modelo, [c for c in constraints if c.name != self.CONSTRAINT_SOLAPAMIENTO])
            for modelo, constraints in super().get_constraints()
        ]

    def save(self, *args, **kwargs):
        # DRF no invoca Model.clean(); forzarlo aquí asegura la regla en cualquier punto de entrada.
        self.full_clean()
        try:
            # Savepoint: si la BD rechaza por la ExclusionConstraint (carrera),
            # la transacción externa (ATOMIC_REQUESTS) sigue siendo utilizable.
            with transaction.atomic():
                super().save(*args, **kwargs)
        except IntegrityError as exc:
            if self.CONSTRAINT_SOLAPAMIENTO in str(exc):
                raise ValidationError(
                    "El veterinario ya tiene una cita que se superpone con este horario.",
                    code="cita_solapada",
                ) from exc
            raise


# ══════════════════════════════════════════════════════════════
# Ficha clínica
# ══════════════════════════════════════════════════════════════
class FichaClinica(ModeloConTimestamps):
    """
    Registro de una atención médica. Una mascota tiene MUCHAS fichas
    (historial clínico), por eso se usa ForeignKey y no OneToOne.
    """

    mascota = models.ForeignKey(
        Mascota,
        on_delete=models.PROTECT,  # Registro médico: nunca se elimina en cascada
        related_name="fichas",
        verbose_name="mascota",
    )
    cita = models.OneToOneField(
        Cita,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ficha",
        verbose_name="cita asociada",
        help_text="Opcional: atenciones de urgencia pueden no tener cita previa.",
    )
    veterinario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="fichas_registradas",
        limit_choices_to=LIMITE_VETERINARIO,
        verbose_name="veterinario",
    )
    fecha_registro = models.DateTimeField("fecha de registro", default=timezone.now, db_index=True)

    # ─── Anamnesis y constantes vitales ───────────────────────
    anamnesis = models.TextField("anamnesis")
    temperatura = models.DecimalField(
        "temperatura (°C)",
        max_digits=4,
        decimal_places=1,
        null=True,
        blank=True,
        validators=[MinValueValidator(30), MaxValueValidator(45)],
    )
    peso_actual = models.DecimalField(
        "peso actual (kg)",
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0.01)],
    )
    frecuencia_cardiaca = models.PositiveSmallIntegerField(
        "frecuencia cardíaca (lpm)",
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(400)],
    )

    # ─── Diagnóstico y plan ───────────────────────────────────
    diagnostico_presuntivo = models.TextField("diagnóstico presuntivo", blank=True)
    diagnostico_definitivo = models.TextField("diagnóstico definitivo", blank=True)
    tratamiento = models.TextField("tratamiento", blank=True)
    receta_medica = models.TextField("receta médica", blank=True)
    examenes_solicitados = models.TextField("exámenes solicitados", blank=True)

    class Meta:
        verbose_name = "ficha clínica"
        verbose_name_plural = "fichas clínicas"
        ordering = ["-fecha_registro"]
        indexes = [
            models.Index(fields=["mascota", "-fecha_registro"], name="ficha_historial_idx"),
        ]

    def __str__(self):
        return f"Ficha #{self.pk} - {self.mascota.nombre} ({self.fecha_registro:%d-%m-%Y %H:%M})"

    def clean(self):
        super().clean()
        if self.veterinario_id:
            _validar_es_veterinario(self.veterinario)
        if self.cita_id and self.mascota_id and self.cita.mascota_id != self.mascota_id:
            raise ValidationError({"cita": "La cita seleccionada pertenece a otra mascota."})

    def save(self, *args, **kwargs):
        es_nueva = self._state.adding
        super().save(*args, **kwargs)
        # Mantiene el peso de la mascota sincronizado con la última medición.
        if es_nueva and self.peso_actual:
            Mascota.objects.filter(pk=self.mascota_id).update(peso=self.peso_actual)


# ══════════════════════════════════════════════════════════════
# Control de vacunas / desparasitaciones
# ══════════════════════════════════════════════════════════════
class ControlVacunaQuerySet(models.QuerySet):
    def vencidos(self):
        return self.filter(estado=ControlVacuna.Estado.VENCIDO)

    def por_vencer(self, dias: int = 15):
        """Controles que vencen en los próximos `dias` (para recordatorios)."""
        hoy = timezone.localdate()
        return self.filter(
            fecha_proximo_vencimiento__gte=hoy,
            fecha_proximo_vencimiento__lte=hoy + timedelta(days=dias),
        )

    def actualizar_vencidos(self) -> int:
        """
        Marca como VENCIDO lo que ya pasó su fecha. Pensado para ejecutarse
        diariamente (cron / systemd timer en EC2). Retorna filas actualizadas.
        """
        return (
            self.filter(fecha_proximo_vencimiento__lt=timezone.localdate())
            .exclude(estado=ControlVacuna.Estado.VENCIDO)
            .update(estado=ControlVacuna.Estado.VENCIDO, actualizado_en=timezone.now())
        )


class ControlVacuna(ModeloConTimestamps):
    """Registro de vacunas, desparasitaciones y controles preventivos."""

    class Tipo(models.TextChoices):
        VACUNA = "VACUNA", "Vacuna"
        DESPARASITACION = "DESPARASITACION", "Desparasitación"
        CONTROL_GENERAL = "CONTROL_GENERAL", "Control general"

    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        AL_DIA = "AL_DIA", "Al día"
        VENCIDO = "VENCIDO", "Vencido"

    mascota = models.ForeignKey(
        Mascota,
        on_delete=models.PROTECT,
        related_name="controles",
        verbose_name="mascota",
    )
    tipo = models.CharField("tipo", max_length=20, choices=Tipo.choices, db_index=True)
    nombre_producto = models.CharField("nombre del producto", max_length=150)
    fecha_aplicacion = models.DateField(
        "fecha de aplicación",
        null=True,
        blank=True,
        help_text="Vacío si el control está agendado pero aún no se aplica.",
    )
    fecha_proximo_vencimiento = models.DateField(
        "próximo vencimiento",
        null=True,
        blank=True,
        db_index=True,
    )
    estado = models.CharField(
        "estado",
        max_length=10,
        choices=Estado.choices,
        default=Estado.PENDIENTE,
        db_index=True,
        editable=False,  # Se calcula automáticamente a partir de las fechas
    )
    aplicado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="controles_aplicados",
        verbose_name="aplicado por",
    )
    observaciones = models.TextField("observaciones", blank=True)

    objects = ControlVacunaQuerySet.as_manager()

    class Meta:
        verbose_name = "control de vacuna / desparasitación"
        verbose_name_plural = "controles de vacunas / desparasitaciones"
        ordering = ["mascota", "-fecha_aplicacion"]
        indexes = [
            models.Index(fields=["estado", "fecha_proximo_vencimiento"], name="control_vencimiento_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(fecha_aplicacion__isnull=True)
                    | Q(fecha_proximo_vencimiento__isnull=True)
                    | Q(fecha_proximo_vencimiento__gte=F("fecha_aplicacion"))
                ),
                name="control_vencimiento_posterior_aplicacion",
                violation_error_message="El vencimiento no puede ser anterior a la fecha de aplicación.",
            ),
        ]

    def __str__(self):
        return f"{self.get_tipo_display()}: {self.nombre_producto} - {self.mascota.nombre} [{self.get_estado_display()}]"

    def calcular_estado(self, hoy: date | None = None) -> str:
        """
        - VENCIDO:   la fecha de próximo vencimiento ya pasó.
        - AL_DIA:    fue aplicado y no está vencido.
        - PENDIENTE: agendado, aún no aplicado.
        """
        hoy = hoy or timezone.localdate()
        if self.fecha_proximo_vencimiento and self.fecha_proximo_vencimiento < hoy:
            return self.Estado.VENCIDO
        if self.fecha_aplicacion:
            return self.Estado.AL_DIA
        return self.Estado.PENDIENTE

    def clean(self):
        super().clean()
        if self.fecha_aplicacion and self.fecha_aplicacion > timezone.localdate():
            raise ValidationError({"fecha_aplicacion": "La fecha de aplicación no puede ser futura."})

    def save(self, *args, **kwargs):
        self.estado = self.calcular_estado()
        super().save(*args, **kwargs)
