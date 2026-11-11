"""Decoradores y mixins de control de acceso por rol para vistas Django tradicionales."""
from functools import wraps

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied

from .permissions import ROLES_CLINICOS, ROLES_PERSONAL


def rol_requerido(*roles):
    """
    Decorador para vistas basadas en función.

        @rol_requerido("VET", "ADMIN")
        def mi_vista(request): ...

    - Usuario anónimo        -> redirige al login (con ?next=).
    - Autenticado sin el rol -> 403 Forbidden.
    """
    roles_permitidos = roles or ROLES_PERSONAL

    def decorador(vista):
        @wraps(vista)
        def _vista(request, *args, **kwargs):
            user = request.user
            if not user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not user.is_active or user.rol not in roles_permitidos:
                raise PermissionDenied("Su rol no tiene acceso a esta sección.")
            return vista(request, *args, **kwargs)

        return _vista

    return decorador


personal_requerido = rol_requerido(*ROLES_PERSONAL)
clinico_requerido = rol_requerido(*ROLES_CLINICOS)


class RolRequeridoMixin(LoginRequiredMixin, UserPassesTestMixin):
    """
    Mixin para vistas basadas en clase. Anónimo -> login; sin rol -> 403.

        class MiVista(RolRequeridoMixin, TemplateView):
            roles = ("VET", "ADMIN")
    """

    roles: tuple[str, ...] = ROLES_PERSONAL

    def test_func(self):
        user = self.request.user
        return user.is_active and user.rol in self.roles
