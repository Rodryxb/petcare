"""
Serializadores de Django REST Framework para PetCare.

Incluye:
  - TutorSerializer y MascotaSerializer para gestión de recepción y pacientes.
  - CitaSerializer con validación estricta de rango horario y anti-solapamiento.
  - CitaCalendarioSerializer con contrato nativo de FullCalendar 6
    (id, title, start, end, color, textColor, extendedProps).
  - FichaClinicaSerializer y ControlVacunaSerializer con reglas clínicas por rol.
"""
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from rest_framework import serializers

from usuarios.models import Usuario
from usuarios.permissions import es_personal_clinico

from .constants import COLORES_CITA, DIAS_CRITICOS_VACUNA, ESTADOS_CITA_CLINICOS, TRANSICIONES_CITA
from .models import Cita, ControlVacuna, FichaClinica, Mascota, Tutor
from .validators import normalizar_rut, validar_rut


class VeterinarioResumenSerializer(serializers.ModelSerializer):
    """Representación compacta de un veterinario para selectores y agenda."""

    nombre_completo = serializers.SerializerMethodField()
    rol_display = serializers.CharField(source="get_rol_display", read_only=True)

    class Meta:
        model = Usuario
        fields = ("id", "username", "first_name", "last_name", "nombre_completo", "email", "rol", "rol_display")
        read_only_fields = fields

    def get_nombre_completo(self, obj) -> str:
        return obj.get_full_name() or obj.username


class MascotaResumenSerializer(serializers.ModelSerializer):
    """Resumen ligero de mascota embebido dentro del listado de tutores."""

    especie_display = serializers.CharField(source="get_especie_display", read_only=True)
    sexo_display = serializers.CharField(source="get_sexo_display", read_only=True)

    class Meta:
        model = Mascota
        fields = ("id", "nombre", "especie", "especie_display", "raza", "sexo", "sexo_display", "peso", "activo")
        read_only_fields = fields


class TutorSerializer(serializers.ModelSerializer):
    """Serializador completo de Tutor con normalización y validación de RUT chileno."""

    nombre_completo = serializers.CharField(read_only=True)
    total_mascotas = serializers.IntegerField(read_only=True, default=0)
    mascotas_resumen = MascotaResumenSerializer(source="mascotas", many=True, read_only=True)

    class Meta:
        model = Tutor
        fields = (
            "id",
            "rut",
            "nombres",
            "apellidos",
            "nombre_completo",
            "telefono",
            "email",
            "direccion",
            "activo",
            "total_mascotas",
            "mascotas_resumen",
            "creado_en",
            "actualizado_en",
        )
        read_only_fields = ("id", "nombre_completo", "total_mascotas", "mascotas_resumen", "creado_en", "actualizado_en")
        extra_kwargs = {
            # Desactivamos el UniqueValidator automático para evaluar unicidad
            # DESPUÉS de normalizar el RUT en validate_rut().
            "rut": {"validators": []},
        }

    def validate_rut(self, valor: str) -> str:
        rut_normalizado = normalizar_rut(valor)
        validar_rut(rut_normalizado)
        qs = Tutor.objects.filter(rut=rut_normalizado)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Ya existe un tutor registrado con este RUT.")
        return rut_normalizado


class MascotaSerializer(serializers.ModelSerializer):
    """Serializador de Mascota con datos enriquecidos del tutor y cálculo de edad."""

    tutor_nombre = serializers.CharField(source="tutor.nombre_completo", read_only=True)
    tutor_rut = serializers.CharField(source="tutor.rut", read_only=True)
    tutor_telefono = serializers.CharField(source="tutor.telefono", read_only=True)
    especie_display = serializers.CharField(source="get_especie_display", read_only=True)
    sexo_display = serializers.CharField(source="get_sexo_display", read_only=True)
    edad = serializers.CharField(read_only=True)

    class Meta:
        model = Mascota
        fields = (
            "id",
            "tutor",
            "tutor_nombre",
            "tutor_rut",
            "tutor_telefono",
            "nombre",
            "especie",
            "especie_display",
            "raza",
            "sexo",
            "sexo_display",
            "fecha_nacimiento",
            "edad",
            "peso",
            "alergias",
            "observaciones",
            "activo",
            "creado_en",
            "actualizado_en",
        )
        read_only_fields = (
            "id",
            "tutor_nombre",
            "tutor_rut",
            "tutor_telefono",
            "especie_display",
            "sexo_display",
            "edad",
            "creado_en",
            "actualizado_en",
        )

    def validate_fecha_nacimiento(self, valor):
        if valor and valor > timezone.localdate():
            raise serializers.ValidationError("La fecha de nacimiento no puede ser futura.")
        return valor


class CitaSerializer(serializers.ModelSerializer):
    """
    Serializador de Cita con validación explícita:
      1. ``hora_fin > hora_inicio``
      2. El usuario asignado debe tener rol ``VET`` y estar activo.
      3. Prohibición de solapamiento de horarios para el mismo veterinario y fecha.
    """

    mascota_nombre = serializers.CharField(source="mascota.nombre", read_only=True)
    mascota_especie = serializers.CharField(source="mascota.get_especie_display", read_only=True)
    tutor_nombre = serializers.CharField(source="mascota.tutor.nombre_completo", read_only=True)
    tutor_rut = serializers.CharField(source="mascota.tutor.rut", read_only=True)
    tutor_telefono = serializers.CharField(source="mascota.tutor.telefono", read_only=True)
    veterinario_nombre = serializers.SerializerMethodField()
    estado_display = serializers.CharField(source="get_estado_display", read_only=True)
    ficha_id = serializers.IntegerField(source="ficha.id", read_only=True, default=None)

    class Meta:
        model = Cita
        fields = (
            "id",
            "mascota",
            "mascota_nombre",
            "mascota_especie",
            "tutor_nombre",
            "tutor_rut",
            "tutor_telefono",
            "veterinario",
            "veterinario_nombre",
            "fecha",
            "hora_inicio",
            "hora_fin",
            "motivo",
            "estado",
            "estado_display",
            "ficha_id",
            "creado_en",
            "actualizado_en",
        )
        read_only_fields = (
            "id",
            "mascota_nombre",
            "mascota_especie",
            "tutor_nombre",
            "tutor_rut",
            "tutor_telefono",
            "veterinario_nombre",
            "estado_display",
            "ficha_id",
            "creado_en",
            "actualizado_en",
        )

    def get_veterinario_nombre(self, obj) -> str:
        return obj.veterinario.get_full_name() or obj.veterinario.username

    def validate(self, attrs):
        instancia = self.instance
        veterinario = attrs.get("veterinario", getattr(instancia, "veterinario", None))
        fecha = attrs.get("fecha", getattr(instancia, "fecha", None))
        hora_inicio = attrs.get("hora_inicio", getattr(instancia, "hora_inicio", None))
        hora_fin = attrs.get("hora_fin", getattr(instancia, "hora_fin", None))
        estado = attrs.get("estado", getattr(instancia, "estado", Cita.Estado.PROGRAMADA))

        errores = {}

        if hora_inicio and hora_fin and hora_fin <= hora_inicio:
            errores["hora_fin"] = "La hora de término debe ser posterior a la hora de inicio."

        if veterinario is not None:
            if veterinario.rol != Usuario.Rol.VET:
                errores["veterinario"] = "El usuario asignado debe tener rol Veterinario."
            elif not veterinario.is_active:
                errores["veterinario"] = "El veterinario seleccionado no se encuentra activo."

        # Validación de máquina de estados y permisos clínicos cuando se edita vía PUT/PATCH
        request = self.context.get("request")
        if instancia is not None and "estado" in attrs and attrs["estado"] != instancia.estado:
            nuevo_estado = attrs["estado"]
            destinos_validos = TRANSICIONES_CITA.get(instancia.estado, set())
            if nuevo_estado not in destinos_validos:
                etiqueta_nueva = Cita.Estado(nuevo_estado).label
                errores["estado"] = (
                    f"No se puede cambiar una cita de '{instancia.get_estado_display()}' a '{etiqueta_nueva}'."
                )
            elif nuevo_estado in ESTADOS_CITA_CLINICOS and request:
                if not es_personal_clinico(request.user):
                    errores["estado"] = (
                        "Solo veterinarios o administradores pueden marcar una cita en atención o finalizada."
                    )
                elif request.user.rol == Usuario.Rol.VET and veterinario and veterinario.pk != request.user.pk:
                    errores["estado"] = "Solo el veterinario asignado puede atender o finalizar esta cita."
                elif nuevo_estado == Cita.Estado.EN_ATENCION and fecha and fecha != timezone.localdate():
                    errores["estado"] = "La atención solo puede iniciarse el día de la cita."

        if errores:
            raise serializers.ValidationError(errores)

        # Validación anti-solapamiento a nivel de serializador
        if all([veterinario, fecha, hora_inicio, hora_fin]) and estado != Cita.Estado.CANCELADA:
            filtro_solapamiento = (
                Q(veterinario=veterinario)
                & Q(fecha=fecha)
                & Q(hora_inicio__lt=hora_fin)
                & Q(hora_fin__gt=hora_inicio)
                & ~Q(estado=Cita.Estado.CANCELADA)
            )
            qs = Cita.objects.filter(filtro_solapamiento).select_related("mascota")
            if instancia is not None:
                qs = qs.exclude(pk=instancia.pk)

            conflicto = qs.first()
            if conflicto:
                raise serializers.ValidationError(
                    {
                        "non_field_errors": [
                            f"Conflicto de horario: el veterinario ya tiene reservada la cita de "
                            f"'{conflicto.mascota.nombre}' el {conflicto.fecha:%d-%m-%Y} "
                            f"entre {conflicto.hora_inicio:%H:%M} y {conflicto.hora_fin:%H:%M}."
                        ]
                    },
                    code="cita_solapada",
                )

        return attrs


class CitaCalendarioSerializer(serializers.ModelSerializer):
    """
    Serializador adaptado al contrato de eventos de FullCalendar 6:
        { id, title, start, end, color, textColor, extendedProps }
    """

    title = serializers.SerializerMethodField()
    start = serializers.SerializerMethodField()
    end = serializers.SerializerMethodField()
    color = serializers.SerializerMethodField()
    textColor = serializers.SerializerMethodField()
    extendedProps = serializers.SerializerMethodField()

    class Meta:
        model = Cita
        fields = ("id", "title", "start", "end", "color", "textColor", "extendedProps")
        read_only_fields = fields

    def get_title(self, obj) -> str:
        return f"{obj.mascota.nombre} ({obj.mascota.get_especie_display()}) · {obj.motivo}"

    def get_start(self, obj) -> str:
        return f"{obj.fecha.isoformat()}T{obj.hora_inicio.strftime('%H:%M:%S')}"

    def get_end(self, obj) -> str:
        return f"{obj.fecha.isoformat()}T{obj.hora_fin.strftime('%H:%M:%S')}"

    def get_color(self, obj) -> str:
        fondo, _ = COLORES_CITA.get(obj.estado, ("#06b6d4", "#ffffff"))
        return fondo

    def get_textColor(self, obj) -> str:
        _, texto = COLORES_CITA.get(obj.estado, ("#06b6d4", "#ffffff"))
        return texto

    def get_extendedProps(self, obj) -> dict:
        vet_nombre = obj.veterinario.get_full_name() or obj.veterinario.username
        return {
            "mascota_id": obj.mascota_id,
            "mascota_nombre": obj.mascota.nombre,
            "especie": obj.mascota.get_especie_display(),
            "tutor_id": obj.mascota.tutor_id,
            "tutor_nombre": obj.mascota.tutor.nombre_completo,
            "tutor_rut": obj.mascota.tutor.rut,
            "tutor_telefono": obj.mascota.tutor.telefono,
            "veterinario_id": obj.veterinario_id,
            "veterinario_nombre": vet_nombre,
            "fecha": obj.fecha.isoformat(),
            "hora_inicio": obj.hora_inicio.strftime("%H:%M"),
            "hora_fin": obj.hora_fin.strftime("%H:%M"),
            "motivo": obj.motivo,
            "estado": obj.estado,
            "estado_display": obj.get_estado_display(),
            "ficha_url": reverse("ficha_clinica_mascota", kwargs={"mascota_id": obj.mascota_id}),
        }


class FichaClinicaSerializer(serializers.ModelSerializer):
    """Serializador de FichaClinica (restringido en escritura a VET y ADMIN)."""

    mascota_nombre = serializers.CharField(source="mascota.nombre", read_only=True)
    mascota_especie = serializers.CharField(source="mascota.get_especie_display", read_only=True)
    tutor_nombre = serializers.CharField(source="mascota.tutor.nombre_completo", read_only=True)
    tutor_rut = serializers.CharField(source="mascota.tutor.rut", read_only=True)
    veterinario_nombre = serializers.SerializerMethodField()

    class Meta:
        model = FichaClinica
        fields = (
            "id",
            "mascota",
            "mascota_nombre",
            "mascota_especie",
            "tutor_nombre",
            "tutor_rut",
            "cita",
            "veterinario",
            "veterinario_nombre",
            "fecha_registro",
            "anamnesis",
            "temperatura",
            "peso_actual",
            "frecuencia_cardiaca",
            "diagnostico_presuntivo",
            "diagnostico_definitivo",
            "tratamiento",
            "receta_medica",
            "examenes_solicitados",
            "creado_en",
            "actualizado_en",
        )
        read_only_fields = (
            "id",
            "mascota_nombre",
            "mascota_especie",
            "tutor_nombre",
            "tutor_rut",
            "veterinario_nombre",
            "creado_en",
            "actualizado_en",
        )
        extra_kwargs = {
            "veterinario": {"required": False},
        }

    def get_veterinario_nombre(self, obj) -> str:
        return obj.veterinario.get_full_name() or obj.veterinario.username

    def validate(self, attrs):
        instancia = self.instance
        request = self.context.get("request")

        veterinario = attrs.get("veterinario", getattr(instancia, "veterinario", None))
        if veterinario is None and request and getattr(request.user, "es_veterinario", False):
            veterinario = request.user
            attrs["veterinario"] = veterinario

        if veterinario is None:
            raise serializers.ValidationError(
                {"veterinario": "Debe indicar el veterinario responsable de la atención."}
            )
        if veterinario.rol != Usuario.Rol.VET:
            raise serializers.ValidationError(
                {"veterinario": "El usuario asignado debe tener rol Veterinario."}
            )

        mascota = attrs.get("mascota", getattr(instancia, "mascota", None))
        cita = attrs.get("cita", getattr(instancia, "cita", None))
        if cita is not None and mascota is not None and cita.mascota_id != mascota.pk:
            raise serializers.ValidationError(
                {"cita": "La cita seleccionada pertenece a otra mascota."}
            )

        return attrs


class ControlVacunaSerializer(serializers.ModelSerializer):
    """
    Serializador de ControlVacuna.
    Recepción puede programar un control pendiente, pero solo VET y ADMIN
    pueden registrar o marcar una aplicación (`fecha_aplicacion`).
    """

    mascota_nombre = serializers.CharField(source="mascota.nombre", read_only=True)
    mascota_especie = serializers.CharField(source="mascota.get_especie_display", read_only=True)
    tutor_nombre = serializers.CharField(source="mascota.tutor.nombre_completo", read_only=True)
    tutor_rut = serializers.CharField(source="mascota.tutor.rut", read_only=True)
    tutor_telefono = serializers.CharField(source="mascota.tutor.telefono", read_only=True)
    tipo_display = serializers.CharField(source="get_tipo_display", read_only=True)
    estado_display = serializers.CharField(source="get_estado_display", read_only=True)
    aplicado_por_nombre = serializers.SerializerMethodField()
    dias_para_vencer = serializers.SerializerMethodField()
    semaforo = serializers.SerializerMethodField()

    class Meta:
        model = ControlVacuna
        fields = (
            "id",
            "mascota",
            "mascota_nombre",
            "mascota_especie",
            "tutor_nombre",
            "tutor_rut",
            "tutor_telefono",
            "tipo",
            "tipo_display",
            "nombre_producto",
            "fecha_aplicacion",
            "fecha_proximo_vencimiento",
            "estado",
            "estado_display",
            "dias_para_vencer",
            "semaforo",
            "aplicado_por",
            "aplicado_por_nombre",
            "observaciones",
            "creado_en",
            "actualizado_en",
        )
        read_only_fields = (
            "id",
            "mascota_nombre",
            "mascota_especie",
            "tutor_nombre",
            "tutor_rut",
            "tutor_telefono",
            "tipo_display",
            "estado",
            "estado_display",
            "dias_para_vencer",
            "semaforo",
            "aplicado_por_nombre",
            "creado_en",
            "actualizado_en",
        )

    def get_aplicado_por_nombre(self, obj) -> str | None:
        if not obj.aplicado_por:
            return None
        return obj.aplicado_por.get_full_name() or obj.aplicado_por.username

    def get_dias_para_vencer(self, obj) -> int | None:
        if not obj.fecha_proximo_vencimiento:
            return None
        return (obj.fecha_proximo_vencimiento - timezone.localdate()).days

    def get_semaforo(self, obj) -> str:
        dias = self.get_dias_para_vencer(obj)
        if dias is None:
            return "SIN_FECHA"
        if dias < 0:
            return "VENCIDA"
        if dias <= DIAS_CRITICOS_VACUNA:
            return "CRITICA"
        return "AL_DIA"

    def validate(self, attrs):
        instancia = self.instance
        request = self.context.get("request")

        fecha_aplicacion = attrs.get(
            "fecha_aplicacion", getattr(instancia, "fecha_aplicacion", None)
        )
        fecha_vencimiento = attrs.get(
            "fecha_proximo_vencimiento",
            getattr(instancia, "fecha_proximo_vencimiento", None),
        )

        # Verificar que solo VET o ADMIN puedan aplicar una vacuna
        aplicacion_nueva_o_cambiada = (
            "fecha_aplicacion" in attrs
            and attrs["fecha_aplicacion"] is not None
            and (instancia is None or attrs["fecha_aplicacion"] != instancia.fecha_aplicacion)
        )
        if aplicacion_nueva_o_cambiada and request and not es_personal_clinico(request.user):
            raise serializers.ValidationError(
                {
                    "fecha_aplicacion": (
                        "Solo veterinarios o administradores pueden registrar la aplicación de una vacuna o control."
                    )
                }
            )

        if fecha_aplicacion and fecha_aplicacion > timezone.localdate():
            raise serializers.ValidationError(
                {"fecha_aplicacion": "La fecha de aplicación no puede ser futura."}
            )

        if fecha_aplicacion and fecha_vencimiento and fecha_vencimiento < fecha_aplicacion:
            raise serializers.ValidationError(
                {"fecha_proximo_vencimiento": "El próximo vencimiento no puede ser anterior a la fecha de aplicación."}
            )

        if fecha_aplicacion and not attrs.get("aplicado_por") and (not instancia or not instancia.aplicado_por_id):
            if request and request.user and request.user.is_authenticated:
                attrs["aplicado_por"] = request.user

        return attrs
