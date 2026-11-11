from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import AsistenciaPersonal, Usuario


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    list_display = ("username", "get_full_name", "email", "rol", "pin_seguridad", "is_active")
    list_filter = ("rol", "is_active", "is_staff")
    search_fields = ("username", "first_name", "last_name", "email")
    fieldsets = UserAdmin.fieldsets + (("PetCare", {"fields": ("rol", "telefono", "pin_seguridad")}),)
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("PetCare", {"fields": ("email", "first_name", "last_name", "rol", "telefono", "pin_seguridad")}),
    )


@admin.register(AsistenciaPersonal)
class AsistenciaPersonalAdmin(admin.ModelAdmin):
    list_display = ("fecha", "usuario", "estado", "registrado_por", "actualizado_en")
    list_filter = ("estado", "fecha", "usuario__rol")
    search_fields = ("usuario__username", "usuario__first_name", "usuario__last_name")
    date_hierarchy = "fecha"

