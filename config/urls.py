"""Rutas raíz de PetCare."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.shortcuts import render
from django.urls import include, path

from usuarios.views import verificar_pin_view


def custom_page_not_found_view(request, exception=None, *args, **kwargs):
    """Manejador global de 404 con redirección y aviso visual."""
    return render(
        request,
        "404.html",
        {"request_path": request.path_info},
        status=404,
    )


handler404 = "config.urls.custom_page_not_found_view"

# Las cabeceras del admin se configuran en clinica/admin.py.
urlpatterns = [
    path("admin/", admin.site.urls),
    # Autenticación por sesión del personal clínico
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="login.html",
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    # Verificación de PIN de desbloqueo por inactividad (5 min)
    path("api/seguridad/verificar-pin/", verificar_pin_view, name="verificar_pin"),
    # Login/logout para la API navegable de DRF
    path("api/auth/", include("rest_framework.urls")),
    # Módulo clínico (Vistas web + API REST)
    path("", include("clinica.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    # En desarrollo local (DEBUG=True), capturar cualquier ruta no registrada
    # para mostrar la plantilla personalizada 404 con redirección al dashboard.
    urlpatterns.append(path("<path:unmatched>", custom_page_not_found_view))
