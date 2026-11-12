"""
Catálogo inicial de prestaciones clínicas y productos de Tienda PetShop para PetCare.

Se inyecta de forma idempotente en la base de datos local para operar tanto en:
  1. Caja Clínica POS (tipo supermercado con lector de código de barras).
  2. Tienda PetShop (alimentos perro/gato/exóticos, vacunas, anestesia, eutanasia,
     collares, antipulgas, calmantes, camas y areneros).
"""
from datetime import timedelta
from urllib.parse import quote

from django.utils import timezone

from .models import ProductoServicio


def generar_ilustracion_producto(
    titulo: str,
    subtitulo: str,
    sku: str,
    color_primario: str,
    color_secundario: str,
    icono_svg: str,
    etiqueta_especie: str,
) -> str:
    """
    Genera una ilustración SVG de alta definición embebida como data URI
    para garantizar carga instantánea 100% local sin enlaces rotos.
    """
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 480 320" width="480" height="320">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0b1120"/>
      <stop offset="55%" stop-color="#111827"/>
      <stop offset="100%" stop-color="{color_primario}" stop-opacity="0.38"/>
    </linearGradient>
    <linearGradient id="accent" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="{color_primario}"/>
      <stop offset="100%" stop-color="{color_secundario}"/>
    </linearGradient>
    <radialGradient id="glow" cx="75%" cy="35%" r="50%">
      <stop offset="0%" stop-color="{color_primario}" stop-opacity="0.35"/>
      <stop offset="100%" stop-color="{color_primario}" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="480" height="320" rx="18" fill="url(#bg)"/>
  <circle cx="360" cy="115" r="140" fill="url(#glow)"/>
  <circle cx="70" cy="280" r="95" fill="{color_secundario}" fill-opacity="0.08"/>
  <!-- Etiqueta superior SKU + Especie -->
  <rect x="24" y="22" width="128" height="28" rx="14" fill="#0f172a" stroke="{color_primario}" stroke-opacity="0.55" stroke-width="1.2"/>
  <text x="88" y="40" fill="{color_primario}" font-family="Inter, system-ui, sans-serif" font-size="11.5" font-weight="700" text-anchor="middle" letter-spacing="0.6">{sku}</text>
  <rect x="336" y="22" width="120" height="28" rx="14" fill="{color_primario}" fill-opacity="0.18" stroke="{color_primario}" stroke-opacity="0.5" stroke-width="1"/>
  <text x="396" y="40" fill="#f8fafc" font-family="Inter, system-ui, sans-serif" font-size="11" font-weight="600" text-anchor="middle">{etiqueta_especie}</text>
  <!-- Contenedor central del producto -->
  <g transform="translate(175, 52)">
    <rect x="0" y="0" width="130" height="130" rx="30" fill="url(#accent)" fill-opacity="0.16" stroke="url(#accent)" stroke-width="2"/>
    <g transform="translate(29, 29)" stroke="{color_primario}" fill="none" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round">
      {icono_svg}
    </g>
  </g>
  <!-- Textos descriptivos -->
  <text x="240" y="222" fill="#f9fafb" font-family="Inter, system-ui, sans-serif" font-size="18" font-weight="700" text-anchor="middle">{titulo}</text>
  <text x="240" y="248" fill="#94a3b8" font-family="Inter, system-ui, sans-serif" font-size="13" font-weight="500" text-anchor="middle">{subtitulo}</text>
  <!-- Barra inferior decorativa de autenticidad clínica -->
  <rect x="24" y="276" width="432" height="22" rx="6" fill="#090d16" fill-opacity="0.75"/>
  <text x="240" y="291" fill="#64748b" font-family="monospace" font-size="10.5" font-weight="600" text-anchor="middle" letter-spacing="1.5">PETCARE CLINICAL &amp; PETSHOP CERTIFIED</text>
</svg>"""
    return f"data:image/svg+xml;utf8,{quote(svg)}"


# Iconos vectoriales SVG temáticos por tipo de producto/servicio
ICONOS = {
    "consulta": '<path d="M22 12h-4l-3 9L9 3l-3 9H2" transform="scale(3)"/>',
    "inyeccion": '<path d="m18 2 4 4-4 4-4-4 4-4Z" transform="scale(3)"/><path d="m14.5 5.5-8.5 8.5v4h4l8.5-8.5" transform="scale(3)"/><path d="m6 18-4 4" transform="scale(3)"/>',
    "vacuna": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" transform="scale(3)"/><path d="M9 12h6M12 9v6" transform="scale(3)"/>',
    "anestesia": '<circle cx="36" cy="36" r="27"/><path d="M36 18v18l12 8"/><circle cx="36" cy="36" r="5" fill="currentColor"/>',
    "eutanasia": '<path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z" transform="scale(3)"/>',
    "alimento_perro": '<rect x="12" y="8" width="48" height="56" rx="8"/><path d="M12 22h48M26 38h20M36 28v20"/>',
    "alimento_gato": '<path d="M12 58V18a6 6 0 0 1 6-6h36a6 6 0 0 1 6 6v40a6 6 0 0 1-6 6H18a6 6 0 0 1-6-6Z"/><circle cx="36" cy="38" r="12"/><path d="M28 24l4 6M44 24l-4 6"/>',
    "alimento_exotico": '<path d="M36 8c14 0 24 12 24 28S50 64 36 64 12 52 12 36 22 8 36 8Z"/><path d="M36 8v56M20 24l16 12 16-12M18 42l18 12 18-12"/>',
    "antipulgas": '<path d="M36 6 12 18v18c0 16.5 10.2 31.8 24 36 13.8-4.2 24-19.5 24-36V18L36 6Z"/><path d="m26 36 7 7 15-15"/>',
    "calmante": '<path d="M36 10c-10 12-18 22-18 32a18 18 0 0 0 36 0c0-10-8-20-18-32Z"/><path d="M30 44a8 8 0 0 0 12 0"/>',
    "collar": '<circle cx="36" cy="34" r="22"/><circle cx="36" cy="34" r="13"/><circle cx="36" cy="60" r="6"/>',
    "cama": '<path d="M8 44v-8a12 12 0 0 1 12-12h28a12 12 0 0 1 12 12v8"/><rect x="4" y="40" width="64" height="16" rx="8"/><path d="M12 56v6M60 56v6"/>',
    "arenero": '<path d="M10 34h52l-6 26H16L10 34Z"/><path d="M16 34V22a10 10 0 0 1 10-10h20a10 10 0 0 1 10 10v12"/><path d="M26 46h20"/>',
}


CATALOGO_INICIAL = [
    # ─── 1. CONSULTAS E INYECCIONES ──────────────────────────────
    {
        "codigo_barras": "7800001000012",
        "sku": "SRV-CONS-001",
        "nombre": "Consulta Veterinaria General",
        "categoria": ProductoServicio.Categoria.CONSULTA,
        "especie_objetivo": ProductoServicio.EspecieObjetivo.TODOS,
        "descripcion": (
            "Evaluación médica integral en box clínico: control de peso, temperatura, "
            "frecuencia cardíaca/respiratoria, auscultación cardiopulmonar, palpación abdominal "
            "y registro en Ficha Clínica Digital."
        ),
        "precio": 20000,
        "stock": 999,
        "es_servicio": True,
        "destacado": True,
        "imagen_url": generar_ilustracion_producto(
            "Consulta General", "Atención Médica en Box Clínico", "SRV-CONS-001",
            "#06b6d4", "#3b82f6", ICONOS["consulta"], "Todas las Especies"
        ),
    },
    {
        "codigo_barras": "7800001000043",
        "sku": "SRV-INY-001",
        "nombre": "Inyección / Administración Parenteral (SC / IM / EV)",
        "categoria": ProductoServicio.Categoria.CONSULTA,
        "especie_objetivo": ProductoServicio.EspecieObjetivo.TODOS,
        "descripcion": (
            "Aplicación clínica de medicamento inyectable subcutáneo, intramuscular o endovenoso "
            "por personal médico veterinario. Incluye jeringa, aguja e insumos estériles."
        ),
        "precio": 5000,
        "stock": 999,
        "es_servicio": True,
        "destacado": True,
        "imagen_url": generar_ilustracion_producto(
            "Inyección Clínica", "Administración SC / IM / EV", "SRV-INY-001",
            "#22d3ee", "#0284c7", ICONOS["inyeccion"], "Insumos Incluidos"
        ),
    },
    {
        "codigo_barras": "7800001000029",
        "sku": "SRV-CONS-002",
        "nombre": "Consulta de Urgencia / Triaje Prioritario",
        "categoria": ProductoServicio.Categoria.CONSULTA,
        "especie_objetivo": ProductoServicio.EspecieObjetivo.TODOS,
        "descripcion": (
            "Atención médica inmediata para pacientes críticos: estabilización inicial, "
            "evaluación FAST, control de dolor agudo y monitoreo de signos vitales."
        ),
        "precio": 35000,
        "stock": 999,
        "es_servicio": True,
        "destacado": False,
        "imagen_url": generar_ilustracion_producto(
            "Consulta Urgencia", "Atención Prioritaria Inmediata", "SRV-CONS-002",
            "#ef4444", "#f97316", ICONOS["consulta"], "Urgencia 24/7"
        ),
    },
    {
        "codigo_barras": "7800001000036",
        "sku": "SRV-CONS-003",
        "nombre": "Consulta Especialidad Animales Exóticos",
        "categoria": ProductoServicio.Categoria.CONSULTA,
        "especie_objetivo": ProductoServicio.EspecieObjetivo.EXOTICO,
        "descripcion": (
            "Consulta especializada para conejos, cobayos, erizos de tierra, hurones, aves y reptiles. "
            "Incluye revisión de oclusión dental y pauta nutricional específica."
        ),
        "precio": 25000,
        "stock": 999,
        "es_servicio": True,
        "destacado": False,
        "imagen_url": generar_ilustracion_producto(
            "Consulta Exóticos", "Lagomorfos, Aves y Reptiles", "SRV-CONS-003",
            "#10b981", "#06b6d4", ICONOS["consulta"], "Especialidad Exóticos"
        ),
    },
    {
        "codigo_barras": "7800001000050",
        "sku": "SRV-CONS-004",
        "nombre": "Curación Clínica y Control Post-Quirúrgico",
        "categoria": ProductoServicio.Categoria.CONSULTA,
        "especie_objetivo": ProductoServicio.EspecieObjetivo.TODOS,
        "descripcion": (
            "Limpieza antiséptica de heridas con clorhexidina/suero fisiológico, cambio de vendaje "
            "estéril o retiro de puntos quirúrgicos."
        ),
        "precio": 12000,
        "stock": 999,
        "es_servicio": True,
        "destacado": False,
        "imagen_url": generar_ilustracion_producto(
            "Curación / Control", "Manejo de Heridas y Suturas", "SRV-CONS-004",
            "#06b6d4", "#10b981", ICONOS["consulta"], "Procedimiento"
        ),
    },
    # ─── 2. VACUNAS DE VARIOS TIPOS ──────────────────────────────
    {
        "codigo_barras": "7800002000011",
        "sku": "VAC-CAN-001",
        "nombre": "Vacuna Óctuple Canina (Nobivac DHPPi+L)",
        "categoria": ProductoServicio.Categoria.VACUNA,
        "especie_objetivo": ProductoServicio.EspecieObjetivo.CANINO,
        "descripcion": (
            "Inmunización completa contra Distemper (Moquillo), Adenovirus, Parvovirus, "
            "Parainfluenza y Leptospirosis canina. Incluye registro en Semáforo de Vacunas."
        ),
        "precio": 15000,
        "stock": 999,
        "es_servicio": True,
        "destacado": True,
        "imagen_url": generar_ilustracion_producto(
            "Vacuna Óctuple", "Nobivac DHPPi+L · Caninos", "VAC-CAN-001",
            "#10b981", "#059669", ICONOS["vacuna"], "Canino"
        ),
    },
    {
        "codigo_barras": "7800002000028",
        "sku": "VAC-GEN-002",
        "nombre": "Vacuna Antirrábica Oficial (Nobivac Rabia)",
        "categoria": ProductoServicio.Categoria.VACUNA,
        "especie_objetivo": ProductoServicio.EspecieObjetivo.TODOS,
        "descripcion": (
            "Vacuna inactivada obligatoria contra el virus de la Rabia para perros, gatos y hurones. "
            "Incluye certificado oficial válido ante el MINSAL y SAG."
        ),
        "precio": 15000,
        "stock": 999,
        "es_servicio": True,
        "destacado": True,
        "imagen_url": generar_ilustracion_producto(
            "Vacuna Antirrábica", "Certificación Oficial MINSAL", "VAC-GEN-002",
            "#10b981", "#06b6d4", ICONOS["vacuna"], "Perro / Gato / Hurón"
        ),
    },
    {
        "codigo_barras": "7800002000035",
        "sku": "VAC-FEL-003",
        "nombre": "Vacuna Triple Felina (Feligen CRP)",
        "categoria": ProductoServicio.Categoria.VACUNA,
        "especie_objetivo": ProductoServicio.EspecieObjetivo.FELINO,
        "descripcion": (
            "Inmunización esencial para gatos contra Rinotraqueítis viral felina, "
            "Calicivirus felino y Panleucopenia infecciosa."
        ),
        "precio": 15000,
        "stock": 999,
        "es_servicio": True,
        "destacado": True,
        "imagen_url": generar_ilustracion_producto(
            "Vacuna Triple Felina", "Feligen CRP · Inmunización Anual", "VAC-FEL-003",
            "#8b5cf6", "#06b6d4", ICONOS["vacuna"], "Felino"
        ),
    },
    {
        "codigo_barras": "7800002000042",
        "sku": "VAC-FEL-004",
        "nombre": "Vacuna Leucemia Felina (Purevax FeLV)",
        "categoria": ProductoServicio.Categoria.VACUNA,
        "especie_objetivo": ProductoServicio.EspecieObjetivo.FELINO,
        "descripcion": (
            "Vacuna recombinante sin adyuvante contra el Virus de la Leucemia Felina (FeLV). "
            "Máxima bioseguridad para gatos indoor/outdoor."
        ),
        "precio": 18000,
        "stock": 999,
        "es_servicio": True,
        "destacado": False,
        "imagen_url": generar_ilustracion_producto(
            "Vacuna Leucemia FeLV", "Purevax Recombinante Felina", "VAC-FEL-004",
            "#a855f7", "#ec4899", ICONOS["vacuna"], "Felino"
        ),
    },
    {
        "codigo_barras": "7800002000059",
        "sku": "VAC-CAN-005",
        "nombre": "Vacuna KC Intranasal (Tos de las Perreras)",
        "categoria": ProductoServicio.Categoria.VACUNA,
        "especie_objetivo": ProductoServicio.EspecieObjetivo.CANINO,
        "descripcion": (
            "Vacuna intranasal de rápida acción local contra Bordetella bronchiseptica y "
            "Parainfluenza canina (Traqueobronquitis infecciosa)."
        ),
        "precio": 16000,
        "stock": 999,
        "es_servicio": True,
        "destacado": False,
        "imagen_url": generar_ilustracion_producto(
            "Vacuna KC Intranasal", "Prevención Traqueobronquitis", "VAC-CAN-005",
            "#14b8a6", "#0ea5e9", ICONOS["vacuna"], "Canino"
        ),
    },
    {
        "codigo_barras": "7800002000066",
        "sku": "VAC-EXO-006",
        "nombre": "Vacuna Mixomatosis y RHD (Conejos y Exóticos)",
        "categoria": ProductoServicio.Categoria.VACUNA,
        "especie_objetivo": ProductoServicio.EspecieObjetivo.EXOTICO,
        "descripcion": (
            "Vacuna bivalente anual para conejos contra Mixomatosis y Enfermedad Hemorrágica "
            "Vírica (RHDV1 / RHDV2)."
        ),
        "precio": 19000,
        "stock": 999,
        "es_servicio": True,
        "destacado": False,
        "imagen_url": generar_ilustracion_producto(
            "Vacuna Mixomatosis", "Protección Anual Lagomorfos", "VAC-EXO-006",
            "#10b981", "#84cc16", ICONOS["vacuna"], "Exótico (Conejos)"
        ),
    },
    # ─── 3. ANESTESIA, CIRUGÍA Y EUTANASIA ───────────────────────
    {
        "codigo_barras": "7800003000010",
        "sku": "PAB-ANES-001",
        "nombre": "Anestesia Inhalatoria Isoflurano + Monitoreo Multiparámetro",
        "categoria": ProductoServicio.Categoria.PABELLON,
        "especie_objetivo": ProductoServicio.EspecieObjetivo.TODOS,
        "descripcion": (
            "Protocolo anestésico general seguro con premedicación, inducción endovenosa, "
            "intubación endotraqueal, mantención con Isoflurano y monitoreo multiparámetro continuo."
        ),
        "precio": 35000,
        "stock": 999,
        "es_servicio": True,
        "destacado": True,
        "imagen_url": generar_ilustracion_producto(
            "Anestesia Inhalatoria", "Isoflurano + Monitoreo Multiparámetro", "PAB-ANES-001",
            "#8b5cf6", "#6366f1", ICONOS["anestesia"], "Pabellón Clínico"
        ),
    },
    {
        "codigo_barras": "7800003000027",
        "sku": "PAB-ANES-002",
        "nombre": "Sedación Profunda / Anestesia Endovenosa (TIVA)",
        "categoria": ProductoServicio.Categoria.PABELLON,
        "especie_objetivo": ProductoServicio.EspecieObjetivo.TODOS,
        "descripcion": (
            "Sedación y analgesia endovenosa controlada para procedimientos menores, "
            "radiografías, ecografías en pacientes inquietos, suturas o limpiezas óticas."
        ),
        "precio": 22000,
        "stock": 999,
        "es_servicio": True,
        "destacado": False,
        "imagen_url": generar_ilustracion_producto(
            "Sedación Endovenosa", "Protocolo TIVA + Analgesia", "PAB-ANES-002",
            "#6366f1", "#06b6d4", ICONOS["anestesia"], "Procedimientos"
        ),
    },
    {
        "codigo_barras": "7800003000034",
        "sku": "PAB-EUT-001",
        "nombre": "Eutanasia Humanitaria Asistida (Protocolo Compasivo 2 Etapas)",
        "categoria": ProductoServicio.Categoria.PABELLON,
        "especie_objetivo": ProductoServicio.EspecieObjetivo.TODOS,
        "descripcion": (
            "Procedimiento médico ético e indoloro en sala privada: 1° etapa de sedación y analgesia "
            "profunda para que el paciente duerma en paz junto a su familia, seguida de 2° etapa asistida."
        ),
        "precio": 45000,
        "stock": 999,
        "es_servicio": True,
        "destacado": False,
        "imagen_url": generar_ilustracion_producto(
            "Eutanasia Humanitaria", "Protocolo Ético Indoloro en 2 Etapas", "PAB-EUT-001",
            "#64748b", "#8b5cf6", ICONOS["eutanasia"], "Acompañamiento Clínico"
        ),
    },
    {
        "codigo_barras": "7800003000058",
        "sku": "PAB-CIR-001",
        "nombre": "Destartraje / Limpieza Dental por Ultrasonido",
        "categoria": ProductoServicio.Categoria.PABELLON,
        "especie_objetivo": ProductoServicio.EspecieObjetivo.TODOS,
        "descripcion": (
            "Eliminación completa de sarro supragingival y subgingival mediante cavitron ultrasónico "
            "y pulido dental profiláctico."
        ),
        "precio": 48000,
        "stock": 999,
        "es_servicio": True,
        "destacado": False,
        "imagen_url": generar_ilustracion_producto(
            "Limpieza Dental", "Ultrasonido + Pulido Profiláctico", "PAB-CIR-001",
            "#0ea5e9", "#8b5cf6", ICONOS["anestesia"], "Odontología"
        ),
    },
    # ─── 4. COMIDA PERRO ─────────────────────────────────────────
    {
        "codigo_barras": "7800004000019",
        "sku": "ALI-PER-001",
        "nombre": "Alimento Perro Royal Canin Medium Adult 15 kg",
        "categoria": ProductoServicio.Categoria.ALIMENTO_PERRO,
        "especie_objetivo": ProductoServicio.EspecieObjetivo.CANINO,
        "descripcion": (
            "Alimento super premium para perros adultos de razas medianas (11 a 25 kg). "
            "Fórmula con complejo antioxidante, prebióticos MOS y ácidos grasos Omega 3 (EPA y DHA) "
            "para una piel sana y alta digestibilidad."
        ),
        "precio": 58900,
        "stock": 24,
        "es_servicio": False,
        "destacado": True,
        "imagen_url": generar_ilustracion_producto(
            "Royal Canin Medium 15kg", "Nutrición Super Premium Adulto", "ALI-PER-001",
            "#f59e0b", "#ef4444", ICONOS["alimento_perro"], "Canino · 15 kg"
        ),
    },
    {
        "codigo_barras": "7800004000026",
        "sku": "ALI-PER-002",
        "nombre": "Purina Pro Plan Puppy Cordero y Arroz 12 kg",
        "categoria": ProductoServicio.Categoria.ALIMENTO_PERRO,
        "especie_objetivo": ProductoServicio.EspecieObjetivo.CANINO,
        "descripcion": (
            "Alimento de alta gama con tecnología OptiStart y calostro natural para cachorros. "
            "Elaborado con carne fresca de cordero, ideal para sistemas digestivos y pieles sensibles."
        ),
        "precio": 54500,
        "stock": 18,
        "es_servicio": False,
        "destacado": False,
        "imagen_url": generar_ilustracion_producto(
            "Pro Plan Puppy Cordero", "Fórmula OptiStart con Calostro · 12kg", "ALI-PER-002",
            "#f97316", "#eab308", ICONOS["alimento_perro"], "Canino Cachorro"
        ),
    },
    {
        "codigo_barras": "7800004000040",
        "sku": "ALI-PER-004",
        "nombre": "Bravery Salmón Adulto Grain Free Perro 7 kg",
        "categoria": ProductoServicio.Categoria.ALIMENTO_PERRO,
        "especie_objetivo": ProductoServicio.EspecieObjetivo.CANINO,
        "descripcion": (
            "Alimento holístico 100% libre de cereales (Grain Free) y monoproteico de salmón Atlántico. "
            "Hipoalergénico, enriquecido con antioxidantes naturales y condroprotectores articulares."
        ),
        "precio": 42900,
        "stock": 15,
        "es_servicio": False,
        "destacado": False,
        "imagen_url": generar_ilustracion_producto(
            "Bravery Salmón 7kg", "100% Grain Free · Monoproteico", "ALI-PER-004",
            "#06b6d4", "#f59e0b", ICONOS["alimento_perro"], "Canino Hipoalergénico"
        ),
    },
    {
        "codigo_barras": "7800004000033",
        "sku": "ALI-PER-003",
        "nombre": "Lata Clínica Húmeda Gastrointestinal Canino 400 g",
        "categoria": ProductoServicio.Categoria.ALIMENTO_PERRO,
        "especie_objetivo": ProductoServicio.EspecieObjetivo.CANINO,
        "descripcion": (
            "Dieta veterinaria húmeda de prescripción para perros con trastornos digestivos agudos, "
            "gastroenteritis o en recuperación post-operatoria. Alta palatabilidad y energía concentrada."
        ),
        "precio": 4500,
        "stock": 45,
        "es_servicio": False,
        "destacado": False,
        "imagen_url": generar_ilustracion_producto(
            "Lata Gastrointestinal", "Dieta Húmeda de Recuperación · 400g", "ALI-PER-003",
            "#eab308", "#10b981", ICONOS["alimento_perro"], "Canino Clínico"
        ),
    },
    # ─── 5. COMIDA GATO ──────────────────────────────────────────
    {
        "codigo_barras": "7800005000018",
        "sku": "ALI-GAT-001",
        "nombre": "Alimento Gato Royal Canin Sterilised 37 — 7.5 kg",
        "categoria": ProductoServicio.Categoria.ALIMENTO_GATO,
        "especie_objetivo": ProductoServicio.EspecieObjetivo.FELINO,
        "descripcion": (
            "Nutrición clínica para gatos esterilizados de 1 a 7 años. Ayuda a mantener el peso ideal "
            "gracias a un contenido moderado de grasas (12%), L-carnitina y equilibrio mineral urinario."
        ),
        "precio": 49900,
        "stock": 20,
        "es_servicio": False,
        "destacado": True,
        "imagen_url": generar_ilustracion_producto(
            "Royal Canin Sterilised", "Control de Peso y Salud Urinaria · 7.5kg", "ALI-GAT-001",
            "#ec4899", "#8b5cf6", ICONOS["alimento_gato"], "Felino · 7.5 kg"
        ),
    },
    {
        "codigo_barras": "7800005000032",
        "sku": "ALI-GAT-003",
        "nombre": "Purina Pro Plan Urinary Care Gato Adulto 3 kg",
        "categoria": ProductoServicio.Categoria.ALIMENTO_GATO,
        "especie_objetivo": ProductoServicio.EspecieObjetivo.FELINO,
        "descripcion": (
            "Fórmula especializada con tecnología OptiTract que regula el pH de la orina y "
            "reduce el riesgo de formación de cálculos urinarios de estruvita y oxalato."
        ),
        "precio": 26900,
        "stock": 22,
        "es_servicio": False,
        "destacado": False,
        "imagen_url": generar_ilustracion_producto(
            "Pro Plan Urinary 3kg", "Protección del Tracto Urinario Felino", "ALI-GAT-003",
            "#a855f7", "#06b6d4", ICONOS["alimento_gato"], "Felino Urinary"
        ),
    },
    {
        "codigo_barras": "7800005000025",
        "sku": "ALI-GAT-002",
        "nombre": "Snack Cremoso Inaba Churu Atún y Salmón (Pack 20 Tubos)",
        "categoria": ProductoServicio.Categoria.ALIMENTO_GATO,
        "especie_objetivo": ProductoServicio.EspecieObjetivo.FELINO,
        "descripcion": (
            "Puré cremoso e hidratante elaborado con atún salvaje y salmón del Pacífico. "
            "Libre de granos y conservantes; ideal como premio en consulta y para dar medicación oral."
        ),
        "precio": 12900,
        "stock": 35,
        "es_servicio": False,
        "destacado": True,
        "imagen_url": generar_ilustracion_producto(
            "Inaba Churu Pack 20u", "Snack Cremoso Hidratante Atún y Salmón", "ALI-GAT-002",
            "#f43f5e", "#f59e0b", ICONOS["alimento_gato"], "Felino Snack"
        ),
    },
    # ─── 6. COMIDA ANIMALES EXÓTICOS ─────────────────────────────
    {
        "codigo_barras": "7800006000017",
        "sku": "ALI-EXO-001",
        "nombre": "Heno Timothy Oxbow Seleccionado Conejos y Cobayos 1.13 kg",
        "categoria": ProductoServicio.Categoria.ALIMENTO_EXOTICO,
        "especie_objetivo": ProductoServicio.EspecieObjetivo.EXOTICO,
        "descripcion": (
            "Heno de fleo (Timothy Grass) 100% natural cosechado en EE.UU. Aporta la fibra larga "
            "indispensable para el desgaste dental continuo de molares e incisivos en conejos, cobayos y chinchillas."
        ),
        "precio": 14500,
        "stock": 28,
        "es_servicio": False,
        "destacado": True,
        "imagen_url": generar_ilustracion_producto(
            "Heno Timothy Oxbow", "Fibra Larga Dental · Conejos y Cobayos", "ALI-EXO-001",
            "#10b981", "#84cc16", ICONOS["alimento_exotico"], "Exótico Herbívoro"
        ),
    },
    {
        "codigo_barras": "7800006000024",
        "sku": "ALI-EXO-002",
        "nombre": "Pellets Mazuri Conejo, Cobayo y Chinchilla 2.26 kg",
        "categoria": ProductoServicio.Categoria.ALIMENTO_EXOTICO,
        "especie_objetivo": ProductoServicio.EspecieObjetivo.EXOTICO,
        "descripcion": (
            "Alimento extruido homogéneo que evita la alimentación selectiva. Contiene probióticos "
            "estabilizados, vitamina C y E, linaza y alto nivel de fibra saludable sin azúcares."
        ),
        "precio": 16900,
        "stock": 20,
        "es_servicio": False,
        "destacado": False,
        "imagen_url": generar_ilustracion_producto(
            "Pellets Mazuri Exóticos", "Nutrición Extruida con Probióticos · 2.26kg", "ALI-EXO-002",
            "#22c55e", "#06b6d4", ICONOS["alimento_exotico"], "Conejo / Cobayo"
        ),
    },
    {
        "codigo_barras": "7800006000031",
        "sku": "ALI-EXO-003",
        "nombre": "Mazuri Insectivore Erizo de Tierra y Reptiles 1 kg",
        "categoria": ProductoServicio.Categoria.ALIMENTO_EXOTICO,
        "especie_objetivo": ProductoServicio.EspecieObjetivo.EXOTICO,
        "descripcion": (
            "Dieta especializada rica en proteína e insectos con quitina natural, taurina, "
            "ácidos grasos Omega y balance calcio/fósforo para erizos africanos, geckos y pogonas."
        ),
        "precio": 15500,
        "stock": 16,
        "es_servicio": False,
        "destacado": False,
        "imagen_url": generar_ilustracion_producto(
            "Mazuri Erizo y Reptiles", "Dieta Insectívora Balanceada · 1kg", "ALI-EXO-003",
            "#84cc16", "#f59e0b", ICONOS["alimento_exotico"], "Erizo / Reptil"
        ),
    },
    {
        "codigo_barras": "7800006000048",
        "sku": "ALI-EXO-004",
        "nombre": "Versele-Laga Prestige Ninfas, Agapornis y Aves Exóticas 1 kg",
        "categoria": ProductoServicio.Categoria.ALIMENTO_EXOTICO,
        "especie_objetivo": ProductoServicio.EspecieObjetivo.EXOTICO,
        "descripcion": (
            "Mezcla nutritiva enriquecida con gránulos extruidos VAM (Vitaminas, Aminoácidos y Minerales), "
            "semillas seleccionadas y conchas de ostra para plumaje brillante y huesos fuertes."
        ),
        "precio": 11900,
        "stock": 25,
        "es_servicio": False,
        "destacado": False,
        "imagen_url": generar_ilustracion_producto(
            "Versele-Laga Aves 1kg", "Mezcla Enriquecida VAM · Aves Exóticas", "ALI-EXO-004",
            "#eab308", "#10b981", ICONOS["alimento_exotico"], "Aves Exóticas"
        ),
    },
    # ─── 7. ANTIPULGAS, CALMANTES Y FARMACIA ─────────────────────
    {
        "codigo_barras": "7800007000016",
        "sku": "FAR-ANT-001",
        "nombre": "Antipulgas y Garrapatas Bravecto Masticable (12 Semanas)",
        "categoria": ProductoServicio.Categoria.FARMACIA,
        "especie_objetivo": ProductoServicio.EspecieObjetivo.CANINO,
        "descripcion": (
            "Comprimido masticable de Fluralaner que brinda 12 semanas (3 meses) continuas de protección "
            "sistémica contra pulgas, garrapatas y sarna demodécica u otodéctica."
        ),
        "precio": 34900,
        "stock": 30,
        "es_servicio": False,
        "destacado": True,
        "imagen_url": generar_ilustracion_producto(
            "Bravecto 12 Semanas", "Comprimido Masticable Antipulgas y Garrapatas", "FAR-ANT-001",
            "#06b6d4", "#8b5cf6", ICONOS["antipulgas"], "Canino · 3 Meses"
        ),
    },
    {
        "codigo_barras": "7800007000023",
        "sku": "FAR-ANT-002",
        "nombre": "Pipeta Antipulgas Frontline Plus Spot-On (Gato / Perro)",
        "categoria": ProductoServicio.Categoria.FARMACIA,
        "especie_objetivo": ProductoServicio.EspecieObjetivo.TODOS,
        "descripcion": (
            "Pipeta tópica mensual con Fipronil y (S)-Metopreno que elimina pulgas adultas, "
            "huevos y larvas en el ambiente, además de piojos y garrapatas."
        ),
        "precio": 16500,
        "stock": 40,
        "es_servicio": False,
        "destacado": False,
        "imagen_url": generar_ilustracion_producto(
            "Pipeta Frontline Plus", "Doble Acción: Adulticida + Larvicida", "FAR-ANT-002",
            "#10b981", "#06b6d4", ICONOS["antipulgas"], "Uso Tópico Mensual"
        ),
    },
    {
        "codigo_barras": "7800007000030",
        "sku": "FAR-CAL-003",
        "nombre": "Difusor Calmante de Feromonas Feliway Classic / Adaptil 48 ml",
        "categoria": ProductoServicio.Categoria.FARMACIA,
        "especie_objetivo": ProductoServicio.EspecieObjetivo.TODOS,
        "descripcion": (
            "Difusor eléctrico con análogo de feromona facial apaciguadora. Reduce el estrés, "
            "marcaje con orina, arañazos verticales, miedo a ruidos y conflictos entre mascotas."
        ),
        "precio": 28900,
        "stock": 18,
        "es_servicio": False,
        "destacado": True,
        "imagen_url": generar_ilustracion_producto(
            "Difusor Calmante Feliway", "Feromonas Clínicas Antiestrés · 48 ml", "FAR-CAL-003",
            "#8b5cf6", "#ec4899", ICONOS["calmante"], "Bienestar Etológico"
        ),
    },
    {
        "codigo_barras": "7800007000047",
        "sku": "FAR-CAL-004",
        "nombre": "Gotas Calmantes Naturales RelaxPet (Valeriana + L-Triptófano 60 ml)",
        "categoria": ProductoServicio.Categoria.FARMACIA,
        "especie_objetivo": ProductoServicio.EspecieObjetivo.TODOS,
        "descripcion": (
            "Fórmula fitoterapéutica oral con extracto de Valeriana, Passiflora, Manzanilla y L-Triptófano "
            "para calmar ansiedad en viajes, tormentas, fuegos artificiales y visitas clínicas."
        ),
        "precio": 13500,
        "stock": 32,
        "es_servicio": False,
        "destacado": False,
        "imagen_url": generar_ilustracion_producto(
            "Gotas Calmantes RelaxPet", "Valeriana + L-Triptófano · 60 ml", "FAR-CAL-004",
            "#a855f7", "#14b8a6", ICONOS["calmante"], "Calmante Natural"
        ),
    },
    # ─── 8. COLLARES, CAMAS Y ARENEROS ───────────────────────────
    {
        "codigo_barras": "7800008000015",
        "sku": "ACC-COL-001",
        "nombre": "Collar Antipulgas Seresto Bayer/Elanco (8 Meses Protección)",
        "categoria": ProductoServicio.Categoria.ACCESORIOS,
        "especie_objetivo": ProductoServicio.EspecieObjetivo.TODOS,
        "descripcion": (
            "Collar de liberación controlada continua e inodoro resistente al agua. Protege hasta "
            "por 8 meses contra pulgas y garrapatas por contacto, sin necesidad de picadura."
        ),
        "precio": 39900,
        "stock": 20,
        "es_servicio": False,
        "destacado": True,
        "imagen_url": generar_ilustracion_producto(
            "Collar Seresto 8 Meses", "Liberación Continua Antipulgas y Garrapatas", "ACC-COL-001",
            "#06b6d4", "#10b981", ICONOS["collar"], "Perro / Gato"
        ),
    },
    {
        "codigo_barras": "7800008000022",
        "sku": "ACC-COL-002",
        "nombre": "Collar Paseo Ergonómico Neopreno Reflectante + Placa QR",
        "categoria": ProductoServicio.Categoria.ACCESORIOS,
        "especie_objetivo": ProductoServicio.EspecieObjetivo.TODOS,
        "descripcion": (
            "Collar ajustable de nylon de alta resistencia con acolchado interior de neopreno "
            "hipoalergénico, bandas reflectantes 360° y placa identificadora QR grabable."
        ),
        "precio": 11900,
        "stock": 35,
        "es_servicio": False,
        "destacado": False,
        "imagen_url": generar_ilustracion_producto(
            "Collar Paseo Reflectante", "Neopreno Acolchado + Identificación QR", "ACC-COL-002",
            "#3b82f6", "#06b6d4", ICONOS["collar"], "Accesorio Paseo"
        ),
    },
    {
        "codigo_barras": "7800008000039",
        "sku": "ACC-COL-003",
        "nombre": "Collar Isabelino Clínico Acolchado Soft (Post-Operatorio)",
        "categoria": ProductoServicio.Categoria.ACCESORIOS,
        "especie_objetivo": ProductoServicio.EspecieObjetivo.TODOS,
        "descripcion": (
            "Cono protector blando impermeable que impide que la mascota lama o muerda suturas y heridas, "
            "permitiendo dormir y alimentarse cómodamente sin chocar con muebles."
        ),
        "precio": 12500,
        "stock": 28,
        "es_servicio": False,
        "destacado": False,
        "imagen_url": generar_ilustracion_producto(
            "Collar Isabelino Soft", "Protección Post-Quirúrgica Confortable", "ACC-COL-003",
            "#22d3ee", "#8b5cf6", ICONOS["collar"], "Recuperación"
        ),
    },
    {
        "codigo_barras": "7800008000046",
        "sku": "ACC-CAM-004",
        "nombre": "Cama Ortopédica Antiestrés Memory Foam 'CloudPet' Lavable",
        "categoria": ProductoServicio.Categoria.ACCESORIOS,
        "especie_objetivo": ProductoServicio.EspecieObjetivo.TODOS,
        "descripcion": (
            "Cama clínica con núcleo de espuma viscoelástica Memory Foam que alivia la presión articular "
            "y bordes elevados tipo dona para soporte cervical. Funda con cierre lavable y base impermeable."
        ),
        "precio": 32900,
        "stock": 14,
        "es_servicio": False,
        "destacado": True,
        "imagen_url": generar_ilustracion_producto(
            "Cama Ortopédica CloudPet", "Memory Foam Antiestrés + Funda Lavable", "ACC-CAM-004",
            "#8b5cf6", "#06b6d4", ICONOS["cama"], "Descanso Clínico"
        ),
    },
    {
        "codigo_barras": "7800008000053",
        "sku": "ACC-ARE-005",
        "nombre": "Arenero Sanitario Cerrado XXL con Filtro de Carbón y Pala",
        "categoria": ProductoServicio.Categoria.ACCESORIOS,
        "especie_objetivo": ProductoServicio.EspecieObjetivo.FELINO,
        "descripcion": (
            "Bandeja sanitaria cubierta de gran capacidad para gatos con puerta abatible translúcida, "
            "filtro superior de carbón activado antiolores, bordes antiderrame y pala dosificadora."
        ),
        "precio": 27900,
        "stock": 16,
        "es_servicio": False,
        "destacado": True,
        "imagen_url": generar_ilustracion_producto(
            "Arenero Cerrado XXL", "Filtro de Carbón Activo + Pala Incluida", "ACC-ARE-005",
            "#06b6d4", "#10b981", ICONOS["arenero"], "Higiene Felina"
        ),
    },
    {
        "codigo_barras": "7800008000060",
        "sku": "ACC-ARE-006",
        "nombre": "Arena Sanitaria Aglomerante Premium Bentonita Lavanda 10 kg",
        "categoria": ProductoServicio.Categoria.ACCESORIOS,
        "especie_objetivo": ProductoServicio.EspecieObjetivo.FELINO,
        "descripcion": (
            "Arena 100% bentonita sódica natural con esferas de carbón activo y suave aroma a lavanda. "
            "Aglomeración instantánea ultra firme y 99% libre de polvo para cuidar vías respiratorias."
        ),
        "precio": 13900,
        "stock": 40,
        "es_servicio": False,
        "destacado": False,
        "imagen_url": generar_ilustracion_producto(
            "Arena Aglomerante 10kg", "Bentonita + Carbón Activo · Cero Polvo", "ACC-ARE-006",
            "#14b8a6", "#a855f7", ICONOS["arenero"], "Felino · 10 kg"
        ),
    },
]


_FOTOS_POR_SKU = {
    # Consultas e inyecciones
    "SRV-CONS-001": "/static/img/productos/consulta_general.jpg",
    "SRV-INY-001": "/static/img/productos/inyeccion.jpg",
    "SRV-CONS-002": "/static/img/productos/urgencia.jpg",
    "SRV-CONS-003": "/static/img/productos/consulta_exoticos.jpg",
    "SRV-CONS-004": "/static/img/productos/curacion_herida.jpg",
    # Vacunas
    "VAC-CAN-001": "/static/img/productos/vacuna_perro.jpg",
    "VAC-GEN-002": "/static/img/productos/vacuna_perro.jpg",
    "VAC-FEL-003": "/static/img/productos/vacuna_gato.jpg",
    "VAC-FEL-004": "/static/img/productos/vacuna_gato.jpg",
    "VAC-CAN-005": "/static/img/productos/vacuna_perro.jpg",
    "VAC-EXO-006": "/static/img/productos/vacuna_conejo.jpg",
    # Pabellón, anestesia y eutanasia
    "PAB-ANES-001": "/static/img/productos/anestesia.jpg",
    "PAB-ANES-002": "/static/img/productos/anestesia.jpg",
    "PAB-EUT-001": "/static/img/productos/eutanasia.jpg",
    "PAB-CIR-001": "/static/img/productos/limpieza_dental.jpg",
    # Comida perro
    "ALI-PER-001": "/static/img/productos/comida_perro_saco.jpg",
    "ALI-PER-002": "/static/img/productos/comida_perro_saco.jpg",
    "ALI-PER-004": "/static/img/productos/comida_perro_saco.jpg",
    "ALI-PER-003": "/static/img/productos/comida_perro_lata.jpg",
    # Comida gato
    "ALI-GAT-001": "/static/img/productos/comida_gato.jpg",
    "ALI-GAT-003": "/static/img/productos/comida_gato.jpg",
    "ALI-GAT-002": "/static/img/productos/snack_gato_churu.jpg",
    # Comida exóticos
    "ALI-EXO-001": "/static/img/productos/heno_conejo.jpg",
    "ALI-EXO-002": "/static/img/productos/heno_conejo.jpg",
    "ALI-EXO-003": "/static/img/productos/comida_erizo_aves.jpg",
    "ALI-EXO-004": "/static/img/productos/comida_erizo_aves.jpg",
    # Antipulgas y calmantes
    "FAR-ANT-001": "/static/img/productos/antipulgas_tableta.jpg",
    "FAR-ANT-002": "/static/img/productos/pipeta_antipulgas.jpg",
    "FAR-CAL-003": "/static/img/productos/calmante_feromonas.jpg",
    "FAR-CAL-004": "/static/img/productos/calmante_feromonas.jpg",
    # Accesorios
    "ACC-COL-001": "/static/img/productos/collar_perro.jpg",
    "ACC-COL-002": "/static/img/productos/collar_perro.jpg",
    "ACC-COL-003": "/static/img/productos/collar_isabelino.jpg",
    "ACC-CAM-004": "/static/img/productos/cama_mascota.jpg",
    "ACC-ARE-005": "/static/img/productos/arenero_gato.jpg",
    "ACC-ARE-006": "/static/img/productos/arenero_gato.jpg",
}


_LOTES_INICIALES_SKU = {
    # Vacunas clínicas (vence en días relativos a hoy + dosis en refrigeración)
    "VAC-CAN-001": {"stock": 14, "stock_minimo": 6, "dias": 5, "lote": "LOT-OCT-2601"},
    "VAC-GEN-002": {"stock": 18, "stock_minimo": 6, "dias": 22, "lote": "LOT-RAB-2604"},
    "VAC-FEL-003": {"stock": 10, "stock_minimo": 5, "dias": 120, "lote": "LOT-TRP-2610"},
    "VAC-FEL-004": {"stock": 4, "stock_minimo": 5, "dias": 85, "lote": "LOT-FELV-2607"},
    "VAC-CAN-005": {"stock": 3, "stock_minimo": 5, "dias": -2, "lote": "LOT-KC-2511"},
    "VAC-EXO-006": {"stock": 6, "stock_minimo": 4, "dias": 14, "lote": "LOT-EXO-2602"},
    # Pabellón y anestesia
    "PAB-ANES-001": {"stock": 8, "stock_minimo": 3, "dias": 25, "lote": "LOT-ISO-2605"},
    "PAB-ANES-002": {"stock": 5, "stock_minimo": 3, "dias": 65, "lote": "LOT-TIVA-2608"},
    "PAB-EUT-001": {"stock": 6, "stock_minimo": 2, "dias": 180, "lote": "LOT-EUT-2609"},
    # Farmacia (antipulgas y calmantes)
    "FAR-ANT-001": {"stock_minimo": 6, "dias": 18, "lote": "LOT-BRV-2611"},
    "FAR-ANT-002": {"stock_minimo": 8, "dias": 6, "lote": "LOT-FRT-2603"},
    # Alimentos destacados con fecha de caducidad próxima o vigente
    "ALI-EXO-001": {"stock_minimo": 6, "dias": 28, "lote": "LOT-TIM-2612"},
}


def _defaults_con_lote_inicial(item: dict, hoy) -> dict:
    datos = dict(item)
    sku = datos.get("sku", "")
    if sku in _FOTOS_POR_SKU:
        datos["imagen_url"] = _FOTOS_POR_SKU[sku]
    cfg = _LOTES_INICIALES_SKU.get(sku)
    if cfg:
        if "stock" in cfg:
            datos["stock"] = cfg["stock"]
        datos["stock_minimo"] = cfg.get("stock_minimo", 5)
        datos["lote"] = cfg["lote"]
        datos["fecha_vencimiento"] = hoy + timedelta(days=cfg["dias"])
    elif sku.startswith("FAR-"):
        datos["stock_minimo"] = 5
        datos["lote"] = f"LOT-{sku}"
        datos["fecha_vencimiento"] = hoy + timedelta(days=145)
    elif sku.startswith("ALI-"):
        datos["stock_minimo"] = 5
        datos["lote"] = f"LOT-{sku}"
        datos["fecha_vencimiento"] = hoy + timedelta(days=210)
    elif sku.startswith("ACC-"):
        datos["stock_minimo"] = 4
        datos["lote"] = f"SER-{sku}"
        datos["fecha_vencimiento"] = None
    else:
        datos.setdefault("stock_minimo", 5)
        datos.setdefault("lote", "")
        datos.setdefault("fecha_vencimiento", None)
    return datos


def asegurar_catalogo_pos() -> int:
    """
    Garantiza que todos los productos y prestaciones iniciales existan en la BD
    sin sobrescribir ajustes manuales de stock, lote, vencimiento o fotos propias.
    Retorna el total de ítems activos en el catálogo.
    """
    hoy = timezone.localdate()
    for item in CATALOGO_INICIAL:
        defaults = _defaults_con_lote_inicial(item, hoy)
        obj, creado = ProductoServicio.objects.get_or_create(
            codigo_barras=item["codigo_barras"],
            defaults=defaults,
        )
        if not creado:
            campos_update = []
            # Reemplaza ilustraciones SVG heredadas por fotografías reales locales sin pisar fotos personalizadas
            if (
                defaults.get("imagen_url")
                and (not obj.imagen_url or obj.imagen_url.startswith("data:image/svg+xml"))
                and obj.imagen_url != defaults["imagen_url"]
            ):
                obj.imagen_url = defaults["imagen_url"]
                campos_update.append("imagen_url")

            # Inicializa lote/vencimiento una única vez para registros existentes previos a la migración
            if not obj.lote and obj.fecha_vencimiento is None and (
                defaults.get("lote") or defaults.get("fecha_vencimiento") is not None
            ):
                if defaults.get("lote"):
                    obj.lote = defaults["lote"]
                    campos_update.append("lote")
                if defaults.get("fecha_vencimiento") is not None:
                    obj.fecha_vencimiento = defaults["fecha_vencimiento"]
                    campos_update.append("fecha_vencimiento")
                if obj.stock == 999 and item["sku"] in _LOTES_INICIALES_SKU and "stock" in _LOTES_INICIALES_SKU[item["sku"]]:
                    obj.stock = _LOTES_INICIALES_SKU[item["sku"]]["stock"]
                    campos_update.append("stock")
                obj.stock_minimo = defaults.get("stock_minimo", obj.stock_minimo)
                campos_update.append("stock_minimo")

            if campos_update:
                obj.save(update_fields=[*campos_update, "actualizado_en"])
    return ProductoServicio.objects.filter(activo=True).count()
