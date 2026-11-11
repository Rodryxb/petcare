"""Expresiones de base de datos específicas de PostgreSQL."""
from django.contrib.postgres.fields import DateTimeRangeField
from django.db.models import Func


class TsRange(Func):
    """
    ``TSRANGE(inicio, fin, '[)')`` de PostgreSQL.

    Se usa para construir el rango horario de una cita dentro de la
    ``ExclusionConstraint`` anti-solapamiento. El límite semiabierto ``[)``
    permite citas consecutivas (10:00-10:30 y 10:30-11:00) sin conflicto.
    """

    function = "TSRANGE"
    output_field = DateTimeRangeField()
