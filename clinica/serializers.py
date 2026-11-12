"""
Serializadores de Django REST Framework para PetCare.

Incluye:
  - TutorSerializer y MascotaSerializer para gestión de recepción y pacientes.
  - CitaSerializer con validación estricta de rango horario y anti-solapamiento.
  - CitaCalendarioSerializer con contrato nativo de FullCalendar 6
    (id, title, start, end, color, textColor, extendedProps).
  - FichaClinicaSerializer y ControlVacunaSerializer con reglas clínicas por rol.
"""
import secrets

from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from rest_framework import serializers

from usuarios.models import Usuario
from usuarios.permissions import es_personal_clinico

from .constants import (
    COLORES_CITA,
    DIAS_ALERTA_VENCIMIENTO_STOCK,
    DIAS_CRITICOS_VACUNA,
    ESTADOS_CITA_CLINICOS,
    MOTIVOS_CONSULTA_CHOICES,
    OTRO_MOTIVO_CODIGO,
    OTRO_MOTIVO_ETIQUETA,
    TRANSICIONES_CITA,
)
from .models import (
    Cita,
    ControlVacuna,
    DetalleOrdenPago,
    FichaClinica,
    Mascota,
    NotificacionVacuna,
    OrdenPago,
    ProductoServicio,
    Tutor,
)
from .validators import autocompletar_rut, normalizar_rut, validar_rut


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
    foto_url = serializers.CharField(read_only=True)

    class Meta:
        model = Mascota
        fields = (
            "id",
            "nombre",
            "especie",
            "especie_display",
            "raza",
            "sexo",
            "sexo_display",
            "peso",
            "foto_url",
            "numero_chip",
            "activo",
        )
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
        rut_normalizado = autocompletar_rut(valor)
        validar_rut(rut_normalizado)
        qs = Tutor.objects.filter(rut=rut_normalizado)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Ya existe un tutor registrado con este RUT.")
        return rut_normalizado


class MascotaSerializer(serializers.ModelSerializer):
    """Serializador de Mascota con datos enriquecidos del tutor, foto y ficha descriptiva."""

    tutor_nombre = serializers.CharField(source="tutor.nombre_completo", read_only=True)
    tutor_rut = serializers.CharField(source="tutor.rut", read_only=True)
    tutor_telefono = serializers.CharField(source="tutor.telefono", read_only=True)
    tutor_email = serializers.EmailField(source="tutor.email", read_only=True)
    especie_display = serializers.CharField(source="get_especie_display", read_only=True)
    sexo_display = serializers.CharField(source="get_sexo_display", read_only=True)
    edad = serializers.CharField(read_only=True)
    foto_url = serializers.CharField(read_only=True)

    class Meta:
        model = Mascota
        fields = (
            "id",
            "tutor",
            "tutor_nombre",
            "tutor_rut",
            "tutor_telefono",
            "tutor_email",
            "nombre",
            "especie",
            "especie_display",
            "raza",
            "sexo",
            "sexo_display",
            "fecha_nacimiento",
            "edad",
            "peso",
            "foto",
            "foto_url",
            "color",
            "condicion_corporal",
            "cicatrices",
            "cirugias_esterilizacion",
            "datos_medioambientales",
            "nutricion",
            "entorno",
            "numero_chip",
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
            "tutor_email",
            "especie_display",
            "sexo_display",
            "edad",
            "foto_url",
            "creado_en",
            "actualizado_en",
        )

    def to_internal_value(self, data):
        # En envíos multipart/form-data los campos vacíos llegan como "";
        # se normalizan a None para que DateField/DecimalField/IntegerField acepten vacío opcional.
        if hasattr(data, "copy"):
            mutable = data.copy()
            for campo in ("fecha_nacimiento", "peso", "condicion_corporal"):
                if campo in mutable and mutable[campo] == "":
                    mutable[campo] = None
            data = mutable
        return super().to_internal_value(data)

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
    motivos_seleccionados = serializers.ListField(
        child=serializers.CharField(max_length=120),
        required=False,
        write_only=True,
    )
    otro_motivo = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        write_only=True,
    )

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
            "motivos_seleccionados",
            "otro_motivo",
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
        extra_kwargs = {
            "motivo": {"required": False, "allow_blank": True},
        }

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

        seleccionados = attrs.pop("motivos_seleccionados", None)
        otro_texto = (attrs.pop("otro_motivo", "") or "").strip()

        if seleccionados is not None:
            mapa_codigos = {cod: etq for cod, etq, _ in MOTIVOS_CONSULTA_CHOICES}
            mapa_etiquetas = {etq.lower(): etq for _, etq, _ in MOTIVOS_CONSULTA_CHOICES}
            partes = []
            tiene_otro = False

            for item in seleccionados:
                limpio = str(item or "").strip()
                if not limpio:
                    continue
                if limpio.upper() == OTRO_MOTIVO_CODIGO or limpio.lower() == OTRO_MOTIVO_ETIQUETA.lower():
                    tiene_otro = True
                    continue
                etiqueta = mapa_codigos.get(limpio.upper()) or mapa_etiquetas.get(limpio.lower()) or limpio
                if etiqueta not in partes:
                    partes.append(etiqueta)

            if tiene_otro:
                if not otro_texto:
                    errores["otro_motivo"] = "Debe escribir el detalle cuando selecciona 'Otro motivo'."
                else:
                    partes.append(f"{OTRO_MOTIVO_ETIQUETA}: {otro_texto}")

            if not partes and "otro_motivo" not in errores:
                errores["motivo"] = "Debe seleccionar al menos un motivo de consulta."
            elif partes:
                motivo_compuesto = ", ".join(partes)
                if len(motivo_compuesto) > 500:
                    errores["motivo"] = "La combinación de motivos supera el máximo de 500 caracteres."
                else:
                    attrs["motivo"] = motivo_compuesto
        elif instancia is None or "motivo" in attrs:
            motivo_actual = (attrs.get("motivo") if "motivo" in attrs else getattr(instancia, "motivo", "") or "").strip()
            if not motivo_actual:
                errores["motivo"] = "Debe seleccionar o escribir al menos un motivo de consulta."
            elif "motivo" in attrs:
                attrs["motivo"] = motivo_actual

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


class NotificacionVacunaSerializer(serializers.ModelSerializer):
    """Historial de recordatorios de vacuna enviados por correo o teléfono."""

    canal_display = serializers.CharField(source="get_canal_display", read_only=True)
    mascota_nombre = serializers.CharField(source="control.mascota.nombre", read_only=True)
    nombre_producto = serializers.CharField(source="control.nombre_producto", read_only=True)
    tutor_nombre = serializers.CharField(source="control.mascota.tutor.nombre_completo", read_only=True)
    enviado_por_nombre = serializers.SerializerMethodField()

    class Meta:
        model = NotificacionVacuna
        fields = (
            "id",
            "control",
            "mascota_nombre",
            "nombre_producto",
            "tutor_nombre",
            "canal",
            "canal_display",
            "destinatario",
            "asunto",
            "mensaje",
            "estado_envio",
            "enviado_por_nombre",
            "creado_en",
        )
        read_only_fields = fields

    def get_enviado_por_nombre(self, obj) -> str:
        if not obj.enviado_por:
            return "Sistema PetCare"
        return obj.enviado_por.get_full_name() or obj.enviado_por.username


class ControlVacunaSerializer(serializers.ModelSerializer):
    """
    Serializador de ControlVacuna.
    Recepción puede programar un control pendiente, pero solo VET y ADMIN
    pueden registrar o marcar una aplicación (`fecha_aplicacion`).
    Incluye cálculo de cuenta regresiva y alerta de proximidad a una semana.
    """

    mascota_nombre = serializers.CharField(source="mascota.nombre", read_only=True)
    mascota_especie = serializers.CharField(source="mascota.get_especie_display", read_only=True)
    mascota_especie_codigo = serializers.CharField(source="mascota.especie", read_only=True)
    tutor_nombre = serializers.CharField(source="mascota.tutor.nombre_completo", read_only=True)
    tutor_nombres = serializers.CharField(source="mascota.tutor.nombres", read_only=True)
    tutor_rut = serializers.CharField(source="mascota.tutor.rut", read_only=True)
    tutor_telefono = serializers.CharField(source="mascota.tutor.telefono", read_only=True)
    tutor_email = serializers.CharField(source="mascota.tutor.email", read_only=True)
    tipo_display = serializers.CharField(source="get_tipo_display", read_only=True)
    estado_display = serializers.CharField(source="get_estado_display", read_only=True)
    aplicado_por_nombre = serializers.SerializerMethodField()
    dias_para_vencer = serializers.SerializerMethodField()
    dias_totales_ciclo = serializers.SerializerMethodField()
    porcentaje_transcurrido = serializers.SerializerMethodField()
    semaforo = serializers.SerializerMethodField()
    alerta_una_semana = serializers.SerializerMethodField()
    mensaje_alerta = serializers.SerializerMethodField()
    ultimo_recordatorio = serializers.SerializerMethodField()
    total_recordatorios = serializers.SerializerMethodField()

    class Meta:
        model = ControlVacuna
        fields = (
            "id",
            "mascota",
            "mascota_nombre",
            "mascota_especie",
            "mascota_especie_codigo",
            "tutor_nombre",
            "tutor_nombres",
            "tutor_rut",
            "tutor_telefono",
            "tutor_email",
            "tipo",
            "tipo_display",
            "nombre_producto",
            "fecha_aplicacion",
            "fecha_proximo_vencimiento",
            "estado",
            "estado_display",
            "dias_para_vencer",
            "dias_totales_ciclo",
            "porcentaje_transcurrido",
            "semaforo",
            "alerta_una_semana",
            "mensaje_alerta",
            "aplicado_por",
            "aplicado_por_nombre",
            "es_externa",
            "lugar_aplicacion",
            "observaciones",
            "ultimo_recordatorio",
            "total_recordatorios",
            "creado_en",
            "actualizado_en",
        )
        read_only_fields = (
            "id",
            "mascota_nombre",
            "mascota_especie",
            "mascota_especie_codigo",
            "tutor_nombre",
            "tutor_nombres",
            "tutor_rut",
            "tutor_telefono",
            "tutor_email",
            "tipo_display",
            "estado",
            "estado_display",
            "dias_para_vencer",
            "dias_totales_ciclo",
            "porcentaje_transcurrido",
            "semaforo",
            "alerta_una_semana",
            "mensaje_alerta",
            "aplicado_por_nombre",
            "ultimo_recordatorio",
            "total_recordatorios",
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

    def get_dias_totales_ciclo(self, obj) -> int | None:
        if not obj.fecha_aplicacion or not obj.fecha_proximo_vencimiento:
            return None
        return max(1, (obj.fecha_proximo_vencimiento - obj.fecha_aplicacion).days)

    def get_porcentaje_transcurrido(self, obj) -> int:
        if not obj.fecha_proximo_vencimiento:
            return 0
        dias_restantes = self.get_dias_para_vencer(obj)
        if dias_restantes is None:
            return 0
        if dias_restantes <= 0:
            return 100
        total = self.get_dias_totales_ciclo(obj) or 30
        transcurrido = max(0, total - dias_restantes)
        return min(100, max(4, round((transcurrido / total) * 100)))

    def get_semaforo(self, obj) -> str:
        dias = self.get_dias_para_vencer(obj)
        if dias is None:
            return "SIN_FECHA"
        if dias < 0:
            return "VENCIDA"
        if dias <= DIAS_CRITICOS_VACUNA:
            return "CRITICA"
        return "AL_DIA"

    def get_alerta_una_semana(self, obj) -> bool:
        dias = self.get_dias_para_vencer(obj)
        return dias is not None and 0 <= dias <= DIAS_CRITICOS_VACUNA

    def get_mensaje_alerta(self, obj) -> str:
        dias = self.get_dias_para_vencer(obj)
        if dias is None:
            return ""
        if dias < 0:
            atraso = abs(dias)
            return f"Vacuna vencida hace {atraso} día{'s' if atraso != 1 else ''}. Enviar aviso urgente al tutor."
        if dias == 0:
            return "¡Su próxima vacuna vence HOY! Enviar recordatorio inmediato al tutor."
        if dias == 1:
            return "Su próxima vacuna se avecina mañana (en 1 día). Enviar recordatorio al tutor."
        if dias <= DIAS_CRITICOS_VACUNA:
            return f"Su próxima vacuna se avecina en una semana ({dias} días restantes). Enviar recordatorio al tutor."
        return f"Cuenta regresiva activa: faltan {dias} días para su próxima dosis."

    def get_ultimo_recordatorio(self, obj) -> dict | None:
        if not obj.pk:
            return None
        notifs = list(obj.notificaciones.all())
        if not notifs:
            return None
        ultima = notifs[0]
        return {
            "id": ultima.id,
            "canal": ultima.canal,
            "canal_display": ultima.get_canal_display(),
            "destinatario": ultima.destinatario,
            "estado_envio": ultima.estado_envio,
            "creado_en": timezone.localtime(ultima.creado_en).strftime("%d/%m/%Y %H:%M"),
        }

    def get_total_recordatorios(self, obj) -> int:
        if not obj.pk:
            return 0
        return len(list(obj.notificaciones.all()))

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

        es_externa = attrs.get(
            "es_externa",
            getattr(instancia, "es_externa", False),
        )

        # Verificar que solo VET o ADMIN puedan aplicar una vacuna interna
        aplicacion_nueva_o_cambiada = (
            "fecha_aplicacion" in attrs
            and attrs["fecha_aplicacion"] is not None
            and (instancia is None or attrs["fecha_aplicacion"] != instancia.fecha_aplicacion)
        )
        if (
            aplicacion_nueva_o_cambiada
            and not es_externa
            and request
            and not es_personal_clinico(request.user)
        ):
            raise serializers.ValidationError(
                {
                    "fecha_aplicacion": (
                        "Solo veterinarios o administradores pueden registrar la aplicación de una vacuna interna."
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

        if es_externa:
            if "aplicado_por" not in attrs:
                attrs["aplicado_por"] = None
        elif fecha_aplicacion and not attrs.get("aplicado_por") and (not instancia or not instancia.aplicado_por_id):
            if request and request.user and request.user.is_authenticated:
                attrs["aplicado_por"] = request.user

        return attrs


class ProductoServicioSerializer(serializers.ModelSerializer):
    """Serializador del catálogo de Servicios Clínicos, Productos y Control de Stock / Vencimientos."""

    categoria_display = serializers.CharField(source="get_categoria_display", read_only=True)
    especie_display = serializers.CharField(source="get_especie_objetivo_display", read_only=True)
    dias_para_vencer = serializers.SerializerMethodField()
    estado_vencimiento = serializers.SerializerMethodField()
    estado_stock = serializers.SerializerMethodField()
    controla_stock_fisico = serializers.BooleanField(read_only=True)
    tiene_alerta = serializers.SerializerMethodField()

    class Meta:
        model = ProductoServicio
        fields = (
            "id",
            "codigo_barras",
            "sku",
            "nombre",
            "categoria",
            "categoria_display",
            "especie_objetivo",
            "especie_display",
            "descripcion",
            "precio",
            "stock",
            "stock_minimo",
            "lote",
            "fecha_vencimiento",
            "es_servicio",
            "controla_stock_fisico",
            "dias_para_vencer",
            "estado_vencimiento",
            "estado_stock",
            "tiene_alerta",
            "imagen_url",
            "destacado",
            "activo",
            "creado_en",
            "actualizado_en",
        )
        read_only_fields = (
            "id",
            "categoria_display",
            "especie_display",
            "controla_stock_fisico",
            "dias_para_vencer",
            "estado_vencimiento",
            "estado_stock",
            "tiene_alerta",
            "creado_en",
            "actualizado_en",
        )

    def get_dias_para_vencer(self, obj) -> int | None:
        return obj.calcular_dias_vencimiento_lote()

    def get_estado_vencimiento(self, obj) -> str:
        return obj.calcular_estado_vencimiento_lote(dias_alerta=DIAS_ALERTA_VENCIMIENTO_STOCK)

    def get_estado_stock(self, obj) -> str:
        return obj.calcular_estado_stock()

    def get_tiene_alerta(self, obj) -> bool:
        est_venc = self.get_estado_vencimiento(obj)
        est_stock = self.get_estado_stock(obj)
        return est_venc in ("VENCIDO", "CRITICO", "POR_VENCER") or est_stock in ("AGOTADO", "BAJO")


class DetalleOrdenPagoSerializer(serializers.ModelSerializer):
    """Detalle de cada línea cobrada en una boleta POS."""

    categoria = serializers.CharField(source="producto.categoria", read_only=True)
    es_servicio = serializers.BooleanField(source="producto.es_servicio", read_only=True)

    class Meta:
        model = DetalleOrdenPago
        fields = (
            "id",
            "producto",
            "nombre_item",
            "codigo_barras",
            "categoria",
            "es_servicio",
            "cantidad",
            "precio_unitario",
            "subtotal",
        )
        read_only_fields = fields


class DetalleOrdenInputSerializer(serializers.Serializer):
    """Ítem recibido desde el carrito del POS o la Tienda."""

    producto_id = serializers.IntegerField()
    cantidad = serializers.IntegerField(min_value=1, max_value=999, default=1)


class OrdenPagoSerializer(serializers.ModelSerializer):
    """
    Serializador transaccional de Orden de Pago (Caja POS y Tienda):
      - Recibe `items` (`[{producto_id, cantidad}, ...]`).
      - Calcula subtotal neto, IVA (19%) y total en CLP.
      - Descuenta stock de productos físicos y emite número de boleta y código de autorización.
    """

    items = DetalleOrdenInputSerializer(many=True, write_only=True)
    detalles = DetalleOrdenPagoSerializer(many=True, read_only=True)
    tutor_nombre = serializers.SerializerMethodField()
    tutor_rut = serializers.SerializerMethodField()
    mascota_nombre = serializers.SerializerMethodField()
    cajero_nombre = serializers.SerializerMethodField()
    metodo_pago_display = serializers.CharField(source="get_metodo_pago_display", read_only=True)
    estado_display = serializers.CharField(source="get_estado_display", read_only=True)

    class Meta:
        model = OrdenPago
        fields = (
            "id",
            "numero_boleta",
            "tutor",
            "tutor_nombre",
            "tutor_rut",
            "mascota",
            "mascota_nombre",
            "cita",
            "cajero",
            "cajero_nombre",
            "metodo_pago",
            "metodo_pago_display",
            "marca_tarjeta",
            "ultimos_4_digitos",
            "cuotas",
            "codigo_autorizacion",
            "subtotal_neto",
            "iva",
            "descuento",
            "total",
            "monto_recibido",
            "vuelto",
            "estado",
            "estado_display",
            "observaciones",
            "items",
            "detalles",
            "creado_en",
        )
        read_only_fields = (
            "id",
            "numero_boleta",
            "tutor_nombre",
            "tutor_rut",
            "mascota_nombre",
            "cajero",
            "cajero_nombre",
            "metodo_pago_display",
            "codigo_autorizacion",
            "subtotal_neto",
            "iva",
            "total",
            "vuelto",
            "estado",
            "estado_display",
            "detalles",
            "creado_en",
        )

    def get_tutor_nombre(self, obj) -> str:
        return obj.tutor.nombre_completo if obj.tutor else "Cliente Presencial (Venta Directa)"

    def get_tutor_rut(self, obj) -> str:
        return obj.tutor.rut if obj.tutor else "—"

    def get_mascota_nombre(self, obj) -> str:
        return f"{obj.mascota.nombre} ({obj.mascota.get_especie_display()})" if obj.mascota else "—"

    def get_cajero_nombre(self, obj) -> str:
        return obj.cajero.get_full_name() or obj.cajero.username

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("El carrito de compra no puede estar vacío.")
        return value

    @transaction.atomic
    def create(self, validated_data):
        items_data = validated_data.pop("items", [])
        request = self.context.get("request")
        cajero = request.user if request and request.user.is_authenticated else Usuario.objects.first()

        descuento = max(0, int(validated_data.get("descuento") or 0))
        monto_recibido = int(validated_data.get("monto_recibido") or 0)
        metodo_pago = validated_data.get("metodo_pago", OrdenPago.MetodoPago.TARJETA_DEBITO)

        lineas_preparadas = []
        suma_bruta = 0

        for item in items_data:
            prod = ProductoServicio.objects.select_for_update().filter(pk=item["producto_id"], activo=True).first()
            if not prod:
                raise serializers.ValidationError(
                    {"items": f"El producto o servicio con ID {item['producto_id']} no está disponible."}
                )
            cantidad = int(item["cantidad"])
            if prod.controla_stock_fisico and prod.stock < cantidad:
                raise serializers.ValidationError(
                    {"items": f"Stock insuficiente para '{prod.nombre}' (disponible: {prod.stock})."}
                )
            subtotal_linea = prod.precio * cantidad
            suma_bruta += subtotal_linea
            lineas_preparadas.append((prod, cantidad, subtotal_linea))

        total_final = max(0, suma_bruta - descuento)
        subtotal_neto = int(round(total_final / 1.19))
        iva = max(0, total_final - subtotal_neto)

        if metodo_pago == OrdenPago.MetodoPago.EFECTIVO:
            if monto_recibido < total_final:
                monto_recibido = total_final
            vuelto = max(0, monto_recibido - total_final)
        else:
            monto_recibido = total_final
            vuelto = 0

        mascota = validated_data.get("mascota")
        tutor = validated_data.get("tutor")
        if mascota and not tutor:
            tutor = mascota.tutor
            validated_data["tutor"] = tutor

        ahora = timezone.localtime()
        correlativo = OrdenPago.objects.count() + 101
        numero_boleta = f"BOL-{ahora:%Y%m%d}-{correlativo:05d}"
        while OrdenPago.objects.filter(numero_boleta=numero_boleta).exists():
            correlativo += 1
            numero_boleta = f"BOL-{ahora:%Y%m%d}-{correlativo:05d}"

        codigo_auth = f"TBK-{secrets.randbelow(900000) + 100000}"

        orden = OrdenPago.objects.create(
            numero_boleta=numero_boleta,
            cajero=cajero,
            subtotal_neto=subtotal_neto,
            iva=iva,
            descuento=descuento,
            total=total_final,
            monto_recibido=monto_recibido,
            vuelto=vuelto,
            codigo_autorizacion=codigo_auth,
            **{
                k: v
                for k, v in validated_data.items()
                if k not in ("descuento", "monto_recibido")
            },
        )

        for prod, cantidad, subtotal_linea in lineas_preparadas:
            DetalleOrdenPago.objects.create(
                orden=orden,
                producto=prod,
                nombre_item=prod.nombre,
                codigo_barras=prod.codigo_barras,
                cantidad=cantidad,
                precio_unitario=prod.precio,
                subtotal=subtotal_linea,
            )
            if prod.controla_stock_fisico:
                prod.stock = max(0, prod.stock - cantidad)
                prod.save(update_fields=["stock", "actualizado_en"])

        return orden
