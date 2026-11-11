"""Manejo centralizado de excepciones para la API."""
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import ProtectedError
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import exception_handler, set_rollback


def manejador_excepciones(exc, context):
    """
    Extiende el handler de DRF:
      * ``django.core.exceptions.ValidationError`` (lanzada por Model.clean/save
        o por la capa de servicios) -> 400 con el mismo formato que DRF.
      * ``ProtectedError`` (borrar algo con historial clínico) -> 409 Conflict.
    """
    if isinstance(exc, DjangoValidationError):
        exc = serializers.ValidationError(serializers.as_serializer_error(exc))

    if isinstance(exc, ProtectedError):
        set_rollback()
        return Response(
            {"detail": "No se puede eliminar: existen registros clínicos asociados."},
            status=status.HTTP_409_CONFLICT,
        )

    return exception_handler(exc, context)
