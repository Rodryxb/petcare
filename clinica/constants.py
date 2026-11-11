"""Constantes de negocio compartidas por admin, API y vistas web."""
from .models import Cita, ControlVacuna

# Ventana (días) para considerar una vacuna "crítica" en el módulo de recordatorios.
DIAS_CRITICOS_VACUNA = 7
DIAS_CRITICOS_MAXIMO = 90

# Paleta por estado de cita: (fondo, texto). Usada por el admin y por FullCalendar.
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

# Máquina de estados de la cita: estado actual -> estados destino permitidos.
# Una cita CANCELADA no se reactiva (reactivarla podría solapar): se agenda otra.
TRANSICIONES_CITA = {
    Cita.Estado.PROGRAMADA: {Cita.Estado.CONFIRMADA, Cita.Estado.EN_ATENCION, Cita.Estado.CANCELADA},
    Cita.Estado.CONFIRMADA: {Cita.Estado.EN_ATENCION, Cita.Estado.CANCELADA},
    Cita.Estado.EN_ATENCION: {Cita.Estado.FINALIZADA, Cita.Estado.CANCELADA},
    Cita.Estado.FINALIZADA: set(),
    Cita.Estado.CANCELADA: set(),
}

# Transiciones que implican acto médico: solo VET (asignado) o ADMIN.
ESTADOS_CITA_CLINICOS = {Cita.Estado.EN_ATENCION, Cita.Estado.FINALIZADA}

# Una ficha clínica asociada a una cita en estos estados la finaliza automáticamente.
ESTADOS_CITA_FINALIZABLES = {Cita.Estado.PROGRAMADA, Cita.Estado.CONFIRMADA, Cita.Estado.EN_ATENCION}
