"""
Serializadores para la gestión de Personal (Usuarios/Roles) y Registro de Asistencia.
"""
from django.utils import timezone
from rest_framework import serializers

from .models import AsistenciaPersonal, Usuario


class AsistenciaPersonalSerializer(serializers.ModelSerializer):
    """Serializador del registro diario de asistencia ('Presente' o 'Ausente')."""

    usuario_nombre = serializers.SerializerMethodField()
    usuario_username = serializers.CharField(source="usuario.username", read_only=True)
    usuario_rol = serializers.CharField(source="usuario.rol", read_only=True)
    usuario_rol_display = serializers.CharField(source="usuario.get_rol_display", read_only=True)
    estado_display = serializers.CharField(source="get_estado_display", read_only=True)
    registrado_por_nombre = serializers.SerializerMethodField()

    class Meta:
        model = AsistenciaPersonal
        fields = (
            "id",
            "usuario",
            "usuario_nombre",
            "usuario_username",
            "usuario_rol",
            "usuario_rol_display",
            "fecha",
            "estado",
            "estado_display",
            "registrado_por",
            "registrado_por_nombre",
            "actualizado_en",
        )
        read_only_fields = (
            "id",
            "usuario_nombre",
            "usuario_username",
            "usuario_rol",
            "usuario_rol_display",
            "estado_display",
            "registrado_por",
            "registrado_por_nombre",
            "actualizado_en",
        )

    def get_usuario_nombre(self, obj) -> str:
        return obj.usuario.get_full_name() or obj.usuario.username

    def get_registrado_por_nombre(self, obj) -> str | None:
        if not obj.registrado_por:
            return None
        return obj.registrado_por.get_full_name() or obj.registrado_por.username


class UsuarioPersonalSerializer(serializers.ModelSerializer):
    """
    Serializador de Usuario para el módulo interno de Administración de Personal.
    Solo el Superusuario puede invocar create/update.
    """

    nombre_completo = serializers.SerializerMethodField()
    rol_display = serializers.CharField(source="get_rol_display", read_only=True)
    password = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        min_length=6,
        style={"input_type": "password"},
    )
    asistencia_hoy = serializers.SerializerMethodField()
    dias_presente = serializers.IntegerField(read_only=True, default=0)
    dias_ausente = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Usuario
        fields = (
            "id",
            "username",
            "first_name",
            "last_name",
            "nombre_completo",
            "email",
            "telefono",
            "rol",
            "rol_display",
            "pin_seguridad",
            "is_active",
            "is_superuser",
            "password",
            "asistencia_hoy",
            "dias_presente",
            "dias_ausente",
            "date_joined",
        )
        read_only_fields = (
            "id",
            "nombre_completo",
            "rol_display",
            "is_superuser",
            "asistencia_hoy",
            "dias_presente",
            "dias_ausente",
            "date_joined",
        )

    def get_nombre_completo(self, obj) -> str:
        return obj.get_full_name() or obj.username

    def get_asistencia_hoy(self, obj) -> str | None:
        hoy = timezone.localdate()
        for a in obj.asistencias.all():
            if a.fecha == hoy:
                return a.estado
        return None

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        # Ocultar el PIN de seguridad a usuarios que no sean superusuarios
        if not (request and request.user and request.user.is_superuser):
            data.pop("pin_seguridad", None)
        return data

    def validate_pin_seguridad(self, valor: str) -> str:
        valor = valor.strip()
        if not (len(valor) == 4 and valor.isdigit()):
            raise serializers.ValidationError("El PIN de seguridad debe contener exactamente 4 dígitos numéricos.")
        return valor

    def validate(self, attrs):
        if self.instance is None and not attrs.get("password"):
            raise serializers.ValidationError(
                {"password": "Debe asignar una contraseña inicial para el nuevo usuario."}
            )
        return attrs

    def create(self, validated_data):
        password = validated_data.pop("password")
        rol = validated_data.get("rol", Usuario.Rol.RECEP)
        usuario = Usuario(**validated_data)
        usuario.is_staff = rol == Usuario.Rol.ADMIN
        usuario.is_superuser = False
        usuario.set_password(password)
        usuario.save()
        return usuario

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        nuevo_rol = validated_data.get("rol", instance.rol)

        # Evitar que el superusuario actual se desactive a sí mismo por error
        request = self.context.get("request")
        if request and request.user.pk == instance.pk:
            if validated_data.get("is_active") is False:
                raise serializers.ValidationError(
                    {"is_active": "No puede desactivar su propia cuenta de superusuario."}
                )

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        # Si el usuario editado no es el propio superusuario, ajustar permisos según rol
        if not (request and request.user.pk == instance.pk):
            instance.is_superuser = False
            instance.is_staff = nuevo_rol == Usuario.Rol.ADMIN

        if password:
            instance.set_password(password)

        instance.save()
        return instance
