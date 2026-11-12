"""Validadores de dominio para PetCare (Chile)."""
import re

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator

_RUT_FORMATO = re.compile(r"^\d{7,8}-[\dK]$")


def normalizar_rut(valor: str) -> str:
    """
    Normaliza un RUT a formato canónico ``12345678-K`` (sin puntos, DV en mayúscula).

    >>> normalizar_rut("12.345.678-5")
    '12345678-5'
    """
    if not valor:
        return valor
    limpio = re.sub(r"[^0-9kK]", "", str(valor)).upper()
    if len(limpio) < 2:
        return limpio
    return f"{limpio[:-1]}-{limpio[-1]}"


def calcular_dv(cuerpo: str) -> str:
    """Calcula el dígito verificador de un RUT mediante el algoritmo módulo 11."""
    suma, factor = 0, 2
    for digito in reversed(cuerpo):
        suma += int(digito) * factor
        factor = 2 if factor == 7 else factor + 1
    resto = 11 - (suma % 11)
    return {11: "0", 10: "K"}.get(resto, str(resto))


def autocompletar_rut(valor: str) -> str:
    """
    Normaliza un RUT y corrige o calcula automáticamente su dígito verificador
    (módulo 11) cuando el usuario ingresa solo el cuerpo numérico o un DV
    referencial en pruebas locales.
    """
    if not valor:
        return valor
    texto = str(valor).strip().upper()
    if "-" in texto:
        partes = texto.split("-", 1)
        cuerpo = re.sub(r"\D", "", partes[0])
        if 7 <= len(cuerpo) <= 8:
            return f"{cuerpo}-{calcular_dv(cuerpo)}"
    limpio = re.sub(r"[^0-9K]", "", texto)
    if len(limpio) >= 2 and limpio[:-1].isdigit() and 7 <= len(limpio[:-1]) <= 8:
        if calcular_dv(limpio[:-1]) == limpio[-1]:
            return f"{limpio[:-1]}-{limpio[-1]}"
    solo_digitos = re.sub(r"\D", "", texto)
    if 7 <= len(solo_digitos) <= 8:
        return f"{solo_digitos}-{calcular_dv(solo_digitos)}"
    if len(solo_digitos) == 9:
        cuerpo = solo_digitos[:-1]
        return f"{cuerpo}-{calcular_dv(cuerpo)}"
    return normalizar_rut(valor)


def validar_rut(valor: str) -> None:
    """Valida formato y dígito verificador de un RUT chileno."""
    rut = normalizar_rut(valor)
    if not rut or not _RUT_FORMATO.match(rut):
        raise ValidationError(
            "Formato de RUT inválido. Use 12345678-9 o 12.345.678-9.",
            code="rut_formato",
        )
    cuerpo, dv = rut.split("-")
    if calcular_dv(cuerpo) != dv:
        raise ValidationError(
            "El dígito verificador del RUT no es válido.", code="rut_dv"
        )


validar_telefono = RegexValidator(
    regex=r"^\+?[\d\s-]{8,20}$",
    message="Teléfono inválido. Ejemplo: +56 9 1234 5678.",
    code="telefono_invalido",
)

_TERMINO_RUT = re.compile(r"^[\d.]+-?[\dkK]?$")


def normalizar_termino_busqueda(termino: str) -> str:
    """
    Adapta un término de búsqueda con forma de RUT al formato almacenado:
    '12.345.678-k' -> '12345678-K'. Cualquier otro término se devuelve intacto.
    Se usa para búsquedas parciales, por eso no exige dígito verificador.
    """
    termino = termino.strip()
    if "." in termino and _TERMINO_RUT.match(termino):
        return termino.replace(".", "").upper()
    return termino
