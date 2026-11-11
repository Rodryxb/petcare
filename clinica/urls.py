"""
Rutas del módulo clínico de PetCare:
  - Endpoints REST bajo `/api/` (mediante DefaultRouter + vistas auxiliares).
  - Vistas web tradicionales para el personal clínico.
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from usuarios.views import (
    AsistenciaPersonalViewSet,
    UsuarioPersonalViewSet,
    personal_usuarios_view,
)

from .views import (
    CitaViewSet,
    ControlVacunaViewSet,
    FichaClinicaViewSet,
    MascotaViewSet,
    TutorViewSet,
    VeterinariosActivosAPIView,
    calendario_citas_view,
    dashboard_view,
    ficha_clinica_view,
    recordatorios_view,
    tutores_mascotas_view,
)

router = DefaultRouter()
router.register(r"tutores", TutorViewSet, basename="api-tutores")
router.register(r"mascotas", MascotaViewSet, basename="api-mascotas")
router.register(r"citas", CitaViewSet, basename="api-citas")
router.register(r"fichas-clinicas", FichaClinicaViewSet, basename="api-fichas-clinicas")
router.register(r"controles-vacunas", ControlVacunaViewSet, basename="api-controles-vacunas")
router.register(r"usuarios", UsuarioPersonalViewSet, basename="api-usuarios")
router.register(r"asistencias", AsistenciaPersonalViewSet, basename="api-asistencias")

recordatorios_api = ControlVacunaViewSet.as_view({"get": "recordatorios"})

urlpatterns = [
    # ─── Vistas Web (Django Templates + Dark Mode Clínico) ────
    path("", dashboard_view, name="dashboard"),
    path("recepcion/", tutores_mascotas_view, name="tutores_mascotas"),
    path("calendario/", calendario_citas_view, name="calendario_citas"),
    path("fichas/", ficha_clinica_view, name="ficha_clinica"),
    path("fichas/mascota/<int:mascota_id>/", ficha_clinica_view, name="ficha_clinica_mascota"),
    path("recordatorios/", recordatorios_view, name="recordatorios"),
    path("personal/", personal_usuarios_view, name="personal_usuarios"),
    # ─── Endpoints de la API REST (/api/...) ──────────────────
    path("api/veterinarios/", VeterinariosActivosAPIView.as_view(), name="api-veterinarios"),
    path("api/recordatorios/", recordatorios_api, name="api-recordatorios"),
    path("api/", include(router.urls)),
]
