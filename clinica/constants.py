"""Constantes de negocio compartidas por admin, API y vistas web."""
from .models import Cita, ControlVacuna

# Ventana (días) para considerar una vacuna "crítica" en el módulo de recordatorios.
DIAS_CRITICOS_VACUNA = 7
DIAS_CRITICOS_MAXIMO = 90
DIAS_ALERTA_VENCIMIENTO_STOCK = 30

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

# Catálogo clínico de motivos seleccionables con tick/palomita al agendar citas.
# Formato: (codigo, etiqueta_visible, icono_bootstrap) — sin comas en las etiquetas.
MOTIVOS_CONSULTA_CHOICES = [
    ("CONTROL_ANUAL", "Control Anual", "bi-clipboard2-pulse"),
    ("VACUNA_ANTIRRABICA", "Vacuna Antirrábica", "bi-shield-check"),
    ("VACUNA_OCTUPLE_SEXTUPLE", "Vacuna Óctuple / Séxtuple Canina", "bi-eyedropper"),
    ("VACUNA_TRIPLE_FELINA", "Vacuna Triple / Leucemia Felina", "bi-eyedropper"),
    ("DESPARASITACION", "Desparasitación Interna / Externa", "bi-bug"),
    ("INYECCION_TRATAMIENTO", "Inyección / Tratamiento Ambulatorio", "bi-capsule"),
    ("CONSULTA_SINTOMAS", "Consulta por Síntomas / Urgencia", "bi-heart-pulse"),
    ("CURACION_HERIDA", "Curación de Herida / Retiro de Puntos", "bi-bandaid"),
    ("DERMATOLOGIA_OTITIS", "Control Dermatológico / Otitis", "bi-search-heart"),
    ("LIMPIEZA_DENTAL", "Limpieza Dental / Profilaxis", "bi-stars"),
    ("CIRUGIA_ANESTESIA", "Cirugía / Anestesia / Pre-Quirúrgico", "bi-hospital"),
    ("EXAMENES_LABORATORIO", "Exámenes de Sangre / Ecografía", "bi-activity"),
    ("MICROCHIP_CERTIFICADO", "Microchip / Certificado Veterinario", "bi-upc-scan"),
    ("CORTE_UNAS_HIGIENE", "Corte de Uñas / Higiene Clínica", "bi-scissors"),
]
OTRO_MOTIVO_CODIGO = "OTRO"
OTRO_MOTIVO_ETIQUETA = "Otro motivo"
