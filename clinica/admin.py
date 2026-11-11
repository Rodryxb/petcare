"""
Panel de administración de PetCare.

Convenciones:
  * Todo HTML se genera con ``format_html`` (escapa automáticamente -> sin XSS).
  * Cada ModelAdmin optimiza sus consultas (select_related / annotate) para
    evitar el problema N+1 en los listados.
  * Las búsquedas por RUT aceptan el formato con puntos (12.345.678-5).
"""
import re
from datetime import timedelta

from django.contrib import admin, messages
from django.db import models
from django.db.models import Count, Q
from django.forms import Textarea
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from .models import Cita, ControlVacuna, FichaClinica, Mascota, Tutor

# ══════════════════════════════════════════════════════════════
# Cabeceras del sitio
# ══════════════════════════════════════════════════════════════
admin.site.site_header = "PetCare | Panel de Control Veterinario"
admin.site.site_title = "PetCare Admin"
admin.site.index_title = "Administración Central del Sistema"
admin.site.empty_value_display = "—"

# ══════════════════════════════════════════════════════════════
# Utilidades visuales
# ══════════════════════════════════════════════════════════════
DIAS_ALERTA_VENCIMIENTO = 15

# (fondo, texto) por estado. Contraste AA en temas claro y oscuro.
COLORES_CITA = {
    Cita.Estado.PROGRAMADA: ("#ffc107", "#212529"),   # Amarillo
    Cita.Estado.CONFIRMADA: ("#6f42c1", "#ffffff"),   # Morado
    Cita.Estado.EN_ATENCION: ("#0d6efd", "#ffffff"),  # Azul
    Cita.Estado.FINALIZADA: ("#198754", "#ffffff"),   # Verde
    Cita.Estado.CANCELADA: ("#dc3545", "#ffffff"),    # Rojo
}

COLORES_CONTROL = {
    ControlVacuna.Estado.PENDIENTE: ("#ffc107", "#212529"),
    ControlVacuna.Estado.AL_DIA: ("#198754", "#ffffff"),
    ControlVacuna.Estado.VENCIDO: ("#dc3545", "#ffffff"),
}


def badge(texto, fondo, color="#ffffff"):
    """Píldora de color reutilizable."""
    return format_html(
        '<span style="display:inline-block;padding:3px 10px;border-radius:12px;'
        "font-size:11px;font-weight:600;letter-spacing:.3px;white-space:nowrap;"
        'background:{};color:{};">{}</span>',
        fondo,
        color,
        texto,
    )


def indicador_vencimiento(fecha):
    """
    Semáforo de vencimiento calculado contra el día de HOY (no contra el campo
    `estado`, que podría estar desactualizado si el cron diario no ha corrido).
    """
    if not fecha:
        return format_html('<span style="color:#6c757d;">{}</span>', "Sin fecha")

    hoy = timezone.localdate()
    dias = (fecha - hoy).days
    fecha_txt = f"{fecha:%d-%m-%Y}"

    if dias < 0:
        return format_html(
            '<span style="color:#dc3545;font-weight:700;">⛔ {} '
            '<small>(vencido hace {} día{})</small></span>',
            fecha_txt, abs(dias), "" if abs(dias) == 1 else "s",
        )
    if dias <= DIAS_ALERTA_VENCIMIENTO:
        return format_html(
            '<span style="color:#fd7e14;font-weight:600;">⚠ {} '
            "<small>({})</small></span>",
            fecha_txt, "vence hoy" if dias == 0 else f"vence en {dias} día{'' if dias == 1 else 's'}",
        )
    return format_html('<span style="color:#198754;">✔ {}</span>', fecha_txt)


def link_admin(obj, texto=None):
    """Enlace a la página de edición de un objeto en el admin."""
    if obj is None:
        return "—"
    url = reverse(f"admin:{obj._meta.app_label}_{obj._meta.model_name}_change", args=[obj.pk])
    return format_html('<a href="{}">{}</a>', url, texto or str(obj))


class BusquedaRutMixin:
    """
    Normaliza términos con forma de RUT antes de buscar:
    '12.345.678-k' -> '12345678-K' (formato almacenado en BD).
    """

    _patron_rut = re.compile(r"^[\d.]+-?[\dkK]?$")

    def get_search_results(self, request, queryset, search_term):
        termino = search_term.strip()
        if "." in termino and self._patron_rut.match(termino):
            search_term = termino.replace(".", "").upper()
        return super().get_search_results(request, queryset, search_term)


class AuditoriaMixin:
    """Campos de trazabilidad en solo lectura, en un fieldset colapsado."""

    fieldset_auditoria = (
        "Auditoría",
        {"fields": ("creado_en", "actualizado_en"), "classes": ("collapse",)},
    )

    def get_readonly_fields(self, request, obj=None):
        return (*super().get_readonly_fields(request, obj), "creado_en", "actualizado_en")


# ══════════════════════════════════════════════════════════════
# Filtros personalizados
# ══════════════════════════════════════════════════════════════
class VencimientoFilter(admin.SimpleListFilter):
    title = "vencimiento"
    parameter_name = "vencimiento"

    def lookups(self, request, model_admin):
        return [
            ("vencidos", "⛔ Vencidos"),
            ("proximos", f"⚠ Vencen en ≤ {DIAS_ALERTA_VENCIMIENTO} días"),
            ("vigentes", "✔ Vigentes"),
            ("sin_fecha", "Sin fecha de vencimiento"),
        ]

    def queryset(self, request, queryset):
        hoy = timezone.localdate()
        limite = hoy + timedelta(days=DIAS_ALERTA_VENCIMIENTO)
        match self.value():
            case "vencidos":
                return queryset.filter(fecha_proximo_vencimiento__lt=hoy)
            case "proximos":
                return queryset.filter(fecha_proximo_vencimiento__range=(hoy, limite))
            case "vigentes":
                return queryset.filter(fecha_proximo_vencimiento__gt=limite)
            case "sin_fecha":
                return queryset.filter(fecha_proximo_vencimiento__isnull=True)
        return queryset


# ══════════════════════════════════════════════════════════════
# Inlines
# ══════════════════════════════════════════════════════════════
class MascotaInline(admin.TabularInline):
    model = Mascota
    extra = 0
    fields = ("nombre", "especie", "raza", "sexo", "fecha_nacimiento", "activo")
    show_change_link = True


class ControlVacunaInline(admin.TabularInline):
    """Vacunas / desparasitaciones editables dentro de la ficha de la mascota."""

    model = ControlVacuna
    extra = 1
    fields = (
        "tipo",
        "nombre_producto",
        "fecha_aplicacion",
        "fecha_proximo_vencimiento",
        "vencimiento_visual",
        "estado_badge",
        "aplicado_por",
    )
    readonly_fields = ("vencimiento_visual", "estado_badge")
    autocomplete_fields = ("aplicado_por",)
    ordering = ("-fecha_aplicacion",)
    show_change_link = True
    verbose_name = "control preventivo"
    verbose_name_plural = "🩹 Vacunas, desparasitaciones y controles"

    @admin.display(description="Vencimiento")
    def vencimiento_visual(self, obj):
        return indicador_vencimiento(obj.fecha_proximo_vencimiento) if obj.pk else "—"

    @admin.display(description="Estado")
    def estado_badge(self, obj):
        if not obj.pk:
            return "—"
        return badge(obj.get_estado_display(), *COLORES_CONTROL[obj.estado])


# ══════════════════════════════════════════════════════════════
# Tutor
# ══════════════════════════════════════════════════════════════
@admin.register(Tutor)
class TutorAdmin(BusquedaRutMixin, AuditoriaMixin, admin.ModelAdmin):
    list_display = ("rut", "nombre_completo_display", "telefono", "email", "total_mascotas", "activo")
    list_display_links = ("rut", "nombre_completo_display")
    list_filter = ("activo",)
    search_fields = ("rut", "apellidos", "telefono", "nombres", "email")
    list_per_page = 50
    inlines = (MascotaInline,)
    fieldsets = (
        ("Identificación", {"fields": ("rut", ("nombres", "apellidos"))}),
        ("Contacto", {"fields": (("telefono", "email"), "direccion")}),
        ("Estado", {"fields": ("activo",)}),
        AuditoriaMixin.fieldset_auditoria,
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_total_mascotas=Count("mascotas"))

    @admin.display(description="Nombre completo", ordering="apellidos")
    def nombre_completo_display(self, obj):
        return obj.nombre_completo

    @admin.display(description="Mascotas", ordering="_total_mascotas")
    def total_mascotas(self, obj):
        total = obj._total_mascotas
        if not total:
            return badge("0", "#e9ecef", "#6c757d")
        url = reverse("admin:clinica_mascota_changelist") + f"?tutor__id__exact={obj.pk}"
        return format_html(
            '<a href="{}" title="Ver mascotas del tutor">{}</a>',
            url,
            badge(f"🐾 {total}", "#0dcaf0", "#052c65"),
        )


# ══════════════════════════════════════════════════════════════
# Mascota
# ══════════════════════════════════════════════════════════════
@admin.register(Mascota)
class MascotaAdmin(BusquedaRutMixin, AuditoriaMixin, admin.ModelAdmin):
    list_display = (
        "nombre",
        "especie",
        "raza",
        "sexo",
        "edad_display",
        "tutor_link",
        "alerta_alergias",
        "controles_vencidos",
        "activo",
    )
    list_filter = ("especie", "sexo", "activo")
    search_fields = ("nombre", "tutor__rut", "tutor__apellidos", "tutor__nombres")
    autocomplete_fields = ("tutor",)
    list_select_related = ("tutor",)
    list_per_page = 50
    inlines = (ControlVacunaInline,)
    fieldsets = (
        ("Identificación", {"fields": ("tutor", "nombre", ("especie", "raza", "sexo"))}),
        ("Datos físicos", {"fields": (("fecha_nacimiento", "peso"),)}),
        ("Información clínica", {"fields": ("alergias", "observaciones")}),
        ("Estado", {"fields": ("activo",)}),
        AuditoriaMixin.fieldset_auditoria,
    )
    formfield_overrides = {models.TextField: {"widget": Textarea(attrs={"rows": 3, "cols": 80})}}

    def get_queryset(self, request):
        hoy = timezone.localdate()
        return (
            super()
            .get_queryset(request)
            .annotate(
                _vencidos=Count("controles", filter=Q(controles__fecha_proximo_vencimiento__lt=hoy))
            )
        )

    @admin.display(description="Edad", ordering="-fecha_nacimiento")
    def edad_display(self, obj):
        return obj.edad

    @admin.display(description="Tutor", ordering="tutor__apellidos")
    def tutor_link(self, obj):
        return link_admin(obj.tutor, obj.tutor.nombre_completo)

    @admin.display(description="Alergias")
    def alerta_alergias(self, obj):
        if obj.alergias:
            return format_html(
                '<span title="{}">{}</span>',
                obj.alergias,
                badge("⚠ Alérgico", "#dc3545"),
            )
        return "—"

    @admin.display(description="Controles vencidos", ordering="_vencidos")
    def controles_vencidos(self, obj):
        if obj._vencidos:
            return badge(f"⛔ {obj._vencidos}", "#dc3545")
        return badge("✔ Al día", "#198754")

    def save_formset(self, request, form, formset, change):
        """Asigna automáticamente quién aplicó el control si no se indicó."""
        instancias = formset.save(commit=False)
        for obj in formset.deleted_objects:
            obj.delete()
        for obj in instancias:
            if isinstance(obj, ControlVacuna) and obj.fecha_aplicacion and not obj.aplicado_por_id:
                obj.aplicado_por = request.user
            obj.save()
        formset.save_m2m()


# ══════════════════════════════════════════════════════════════
# Cita
# ══════════════════════════════════════════════════════════════
@admin.register(Cita)
class CitaAdmin(BusquedaRutMixin, AuditoriaMixin, admin.ModelAdmin):
    list_display = (
        "fecha",
        "horario",
        "mascota_link",
        "tutor_rut",
        "veterinario",
        "motivo_corto",
        "estado_badge",
    )
    list_display_links = ("fecha", "horario")
    list_filter = (
        ("veterinario", admin.RelatedOnlyFieldListFilter),
        "estado",
        "fecha",
    )
    search_fields = ("mascota__nombre", "mascota__tutor__rut", "mascota__tutor__apellidos", "motivo")
    date_hierarchy = "fecha"
    autocomplete_fields = ("mascota", "veterinario")
    list_select_related = ("mascota__tutor", "veterinario")
    ordering = ("-fecha", "hora_inicio")
    list_per_page = 50
    actions = ("marcar_confirmada", "marcar_cancelada")
    fieldsets = (
        ("Paciente", {"fields": ("mascota", "motivo")}),
        ("Agenda", {"fields": ("veterinario", "fecha", ("hora_inicio", "hora_fin"), "estado")}),
        AuditoriaMixin.fieldset_auditoria,
    )

    @admin.display(description="Horario", ordering="hora_inicio")
    def horario(self, obj):
        return f"{obj.hora_inicio:%H:%M} – {obj.hora_fin:%H:%M}"

    @admin.display(description="Mascota", ordering="mascota__nombre")
    def mascota_link(self, obj):
        return link_admin(obj.mascota, obj.mascota.nombre)

    @admin.display(description="RUT tutor", ordering="mascota__tutor__rut")
    def tutor_rut(self, obj):
        return obj.mascota.tutor.rut

    @admin.display(description="Motivo")
    def motivo_corto(self, obj):
        return obj.motivo if len(obj.motivo) <= 40 else f"{obj.motivo[:40]}…"

    @admin.display(description="Estado", ordering="estado")
    def estado_badge(self, obj):
        return badge(obj.get_estado_display(), *COLORES_CITA[obj.estado])

    # ─── Acciones masivas ─────────────────────────────────────
    # Seguras con .update(): no cambian horarios ni reactivan citas canceladas,
    # por lo que nunca pueden provocar un solapamiento.
    @admin.action(description="✔ Confirmar citas programadas seleccionadas")
    def marcar_confirmada(self, request, queryset):
        n = queryset.filter(estado=Cita.Estado.PROGRAMADA).update(
            estado=Cita.Estado.CONFIRMADA, actualizado_en=timezone.now()
        )
        self.message_user(request, f"{n} cita(s) confirmada(s).", messages.SUCCESS)

    @admin.action(description="✖ Cancelar citas seleccionadas")
    def marcar_cancelada(self, request, queryset):
        n = queryset.exclude(estado__in=[Cita.Estado.FINALIZADA, Cita.Estado.CANCELADA]).update(
            estado=Cita.Estado.CANCELADA, actualizado_en=timezone.now()
        )
        self.message_user(
            request,
            f"{n} cita(s) cancelada(s). Las finalizadas no se modifican.",
            messages.WARNING,
        )


# ══════════════════════════════════════════════════════════════
# Ficha clínica
# ══════════════════════════════════════════════════════════════
@admin.register(FichaClinica)
class FichaClinicaAdmin(BusquedaRutMixin, AuditoriaMixin, admin.ModelAdmin):
    list_display = (
        "fecha_registro",
        "mascota_link",
        "tutor_rut",
        "veterinario",
        "constantes",
        "diagnostico_resumen",
    )
    list_display_links = ("fecha_registro",)
    list_filter = (
        ("veterinario", admin.RelatedOnlyFieldListFilter),
        "fecha_registro",
        "mascota__especie",
    )
    search_fields = ("mascota__nombre", "mascota__tutor__rut")
    date_hierarchy = "fecha_registro"
    autocomplete_fields = ("mascota", "cita", "veterinario")
    list_select_related = ("mascota__tutor", "veterinario")
    list_per_page = 50
    formfield_overrides = {models.TextField: {"widget": Textarea(attrs={"rows": 4, "cols": 90})}}
    fieldsets = (
        (
            "📋 Datos de Consulta",
            {"fields": ("mascota", "cita", "veterinario", "fecha_registro")},
        ),
        (
            "🩺 Evaluación Médica",
            {
                "fields": (
                    "anamnesis",
                    ("temperatura", "peso_actual", "frecuencia_cardiaca"),
                    "diagnostico_presuntivo",
                    "diagnostico_definitivo",
                )
            },
        ),
        (
            "💊 Tratamiento y Exámenes",
            {"fields": ("tratamiento", "receta_medica", "examenes_solicitados")},
        ),
        AuditoriaMixin.fieldset_auditoria,
    )

    def get_changeform_initial_data(self, request):
        """Si quien crea la ficha es veterinario, se asigna por defecto."""
        inicial = super().get_changeform_initial_data(request)
        if getattr(request.user, "es_veterinario", False):
            inicial.setdefault("veterinario", request.user.pk)
        return inicial

    @admin.display(description="Mascota", ordering="mascota__nombre")
    def mascota_link(self, obj):
        return link_admin(obj.mascota, obj.mascota.nombre)

    @admin.display(description="RUT tutor", ordering="mascota__tutor__rut")
    def tutor_rut(self, obj):
        return obj.mascota.tutor.rut

    @admin.display(description="T° / Peso / FC")
    def constantes(self, obj):
        temp = f"{obj.temperatura} °C" if obj.temperatura is not None else "—"
        peso = f"{obj.peso_actual} kg" if obj.peso_actual is not None else "—"
        fc = f"{obj.frecuencia_cardiaca} lpm" if obj.frecuencia_cardiaca is not None else "—"
        return format_html('<span style="white-space:nowrap;">{} · {} · {}</span>', temp, peso, fc)

    @admin.display(description="Diagnóstico")
    def diagnostico_resumen(self, obj):
        if obj.diagnostico_definitivo:
            return format_html(
                "{} {}", badge("Definitivo", "#198754"), obj.diagnostico_definitivo[:50]
            )
        if obj.diagnostico_presuntivo:
            return format_html(
                "{} {}", badge("Presuntivo", "#ffc107", "#212529"), obj.diagnostico_presuntivo[:50]
            )
        return "—"


# ══════════════════════════════════════════════════════════════
# Control de vacunas
# ══════════════════════════════════════════════════════════════
@admin.register(ControlVacuna)
class ControlVacunaAdmin(BusquedaRutMixin, AuditoriaMixin, admin.ModelAdmin):
    list_display = (
        "mascota_link",
        "tipo",
        "nombre_producto",
        "fecha_aplicacion",
        "vencimiento_visual",
        "estado_badge",
        "aplicado_por",
    )
    list_filter = (VencimientoFilter, "tipo", "estado")
    search_fields = ("mascota__nombre", "mascota__tutor__rut", "nombre_producto")
    date_hierarchy = "fecha_proximo_vencimiento"
    autocomplete_fields = ("mascota", "aplicado_por")
    list_select_related = ("mascota", "aplicado_por")
    ordering = ("fecha_proximo_vencimiento",)
    list_per_page = 50
    actions = ("actualizar_estados",)
    fieldsets = (
        ("Paciente", {"fields": ("mascota",)}),
        (
            "Control",
            {
                "fields": (
                    ("tipo", "nombre_producto"),
                    ("fecha_aplicacion", "fecha_proximo_vencimiento"),
                    "estado_badge",
                    "aplicado_por",
                    "observaciones",
                )
            },
        ),
        AuditoriaMixin.fieldset_auditoria,
    )

    def get_readonly_fields(self, request, obj=None):
        return (*super().get_readonly_fields(request, obj), "estado_badge")

    @admin.display(description="Mascota", ordering="mascota__nombre")
    def mascota_link(self, obj):
        return link_admin(obj.mascota, obj.mascota.nombre)

    @admin.display(description="Próximo vencimiento", ordering="fecha_proximo_vencimiento")
    def vencimiento_visual(self, obj):
        return indicador_vencimiento(obj.fecha_proximo_vencimiento)

    @admin.display(description="Estado", ordering="estado")
    def estado_badge(self, obj):
        if not obj.pk:
            return "Se calcula al guardar"
        return badge(obj.get_estado_display(), *COLORES_CONTROL[obj.estado])

    def save_model(self, request, obj, form, change):
        if obj.fecha_aplicacion and not obj.aplicado_por_id:
            obj.aplicado_por = request.user
        super().save_model(request, obj, form, change)

    @admin.action(description="🔄 Actualizar estado de controles vencidos")
    def actualizar_estados(self, request, queryset):
        n = queryset.actualizar_vencidos()
        self.message_user(request, f"{n} control(es) marcado(s) como VENCIDO.", messages.INFO)
