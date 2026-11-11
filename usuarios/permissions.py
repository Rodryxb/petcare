"""
Permisos DRF basados en el rol del usuario.

Matriz de acceso de PetCare:

| Recurso          | ADMIN | VET                     | RECEP                         |
|------------------|-------|-------------------------|-------------------------------|
| Tutores/Mascotas | CRUD  | CRUD                    | CRUD                          |
| Citas            | CRUD  | CRU + atender/finalizar | CRU + confirmar/cancelar      |
| Fichas clínicas  | CRU   | CRU (solo las propias)  | Solo lectura                  |
| Vacunas          | CRUD  | CRUD + aplicar          | Leer y agendar (sin aplicar)  |
"""
from rest_framework.permissions import SAFE_METHODS, BasePermission

from .models import Usuario

ROLES_PERSONAL = (Usuario.Rol.ADMIN, Usuario.Rol.VET, Usuario.Rol.RECEP)
ROLES_CLINICOS = (Usuario.Rol.ADMIN, Usuario.Rol.VET)


def es_personal_clinico(user) -> bool:
    """True si el usuario puede ejecutar actos médicos (VET o ADMIN)."""
    return bool(user and user.is_authenticated and user.is_active and user.rol in ROLES_CLINICOS)


class TieneRol(BasePermission):
    """Clase base: permite el acceso solo a los roles listados en `roles`."""

    roles: tuple[str, ...] = ()
    message = "Su rol no tiene permiso para realizar esta acción."

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user and user.is_authenticated and user.is_active and user.rol in self.roles
        )


class EsAdmin(TieneRol):
    roles = (Usuario.Rol.ADMIN,)


class EsVeterinario(TieneRol):
    roles = (Usuario.Rol.VET,)


class EsAdminOVeterinario(TieneRol):
    """Acceso a actos clínicos (fichas, aplicación de vacunas, atención)."""

    roles = ROLES_CLINICOS
    message = "Solo veterinarios o administradores pueden realizar esta acción."


class EsPersonalClinica(TieneRol):
    """Cualquier rol del personal (agenda, tutores, mascotas)."""

    roles = ROLES_PERSONAL


class LecturaPersonalEscrituraClinica(BasePermission):
    """Lectura para todo el personal; creación/edición solo VET y ADMIN."""

    message = "Solo veterinarios o administradores pueden crear o modificar este registro."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated and user.is_active and user.rol in ROLES_PERSONAL):
            return False
        return request.method in SAFE_METHODS or user.rol in ROLES_CLINICOS


class EsAutorFichaOAdmin(BasePermission):
    """
    A nivel de objeto: un VET solo modifica las fichas que él registró.
    El ADMIN puede corregir cualquiera. La lectura no se restringe aquí.
    """

    message = "Solo el veterinario que registró la ficha (o un administrador) puede modificarla."

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS or request.user.rol == Usuario.Rol.ADMIN:
            return True
        return obj.veterinario_id == request.user.pk


class EliminarSoloAdmin(BasePermission):
    """DELETE reservado al Administrador; el resto de métodos pasa."""

    message = "Solo un administrador puede eliminar este registro."

    def has_permission(self, request, view):
        return request.method != "DELETE" or request.user.rol == Usuario.Rol.ADMIN


class EliminarSoloClinico(BasePermission):
    """DELETE reservado a VET y ADMIN."""

    message = "Solo veterinarios o administradores pueden eliminar este registro."

    def has_permission(self, request, view):
        return request.method != "DELETE" or request.user.rol in ROLES_CLINICOS


class LecturaPersonalEscrituraSuperusuario(BasePermission):
    """
    Todo el personal autenticado puede visualizar el directorio de usuarios,
    roles y registro de asistencia; pero SOLO el Superusuario puede crear,
    editar o eliminar usuarios y modificar el registro de asistencia.
    """

    message = "Solo el Superusuario puede crear, modificar o eliminar usuarios y registros de personal."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated and user.is_active):
            return False
        if request.method in SAFE_METHODS:
            return True
        return bool(user.is_superuser)

