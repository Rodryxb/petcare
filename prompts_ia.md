# 🤖 Bitácora de Ingeniería de Prompts e Inteligencia Artificial — Proyecto PetCare

Documento técnico exigido por la rúbrica de la **Evaluación 3**, donde se registra de forma transparente y verificable el uso de Inteligencia Artificial Generativa a lo largo de las **5 etapas del ciclo de desarrollo de software** del sistema clínico veterinario **PetCare**.

---

## Resumen Ejecutivo del Flujo con IA

| Etapa | Módulo / Entregable | Rol Solicitado a la IA | Modelo Recomendado / Utilizado |
| :--- | :--- | :--- | :--- |
| **Fase 1: Modelado ORM y Configuración** | `settings.py`, `.env.example`, `requirements.txt`, `usuarios/models.py`, `clinica/models.py` | Arquitecto de Software Senior y Tech Lead en Python/Django | Claude Opus 5.5 |
| **Fase 2: Django Admin Empresarial** | `clinica/admin.py`, `usuarios/admin.py` | Desarrollador Django Senior | Gemini 4 Argon / Gemini 3.8 Flash |
| **Fase 3: API DRF, Lógica y Seguridad** | `serializers.py`, `views.py`, `services.py`, `permissions.py`, `urls.py` | Arquitecto Backend / DRF & Seguridad | Claude Opus 5.5 |
| **Fase 4: Frontend Dark Mode Clínico** | `base.html`, `dashboard.html`, `tutores_mascotas.html`, `calendario_citas.html`, `ficha_clinica.html`, `recordatorios.html`, CSS, JS | Diseñador UI/UX Senior y Frontend Engineer de Élite | Claude Sonnet 5.5 |
| **Fase 5: Despliegue EC2 y Documentación** | `deploy_ec2.sh`, `README.md`, `prompts_ia.md`, `seed_petcare.py` | Ingeniero DevOps y Docente de Arquitectura de Software | Gemini 4 Argon |

---

## Etapa 1: Modelado ORM y Configuración Inicial

### 1. Rol solicitado a la IA
> *"Actúa como un Arquitecto de Software Senior y Tech Lead en Python/Django."*

### 2. Prompt ejecutado
```text
Actúa como un Arquitecto de Software Senior y Tech Lead en Python/Django. Desarrollaremos el backend de "PetCare" (Sistema de Gestión Clínica Veterinaria de uso exclusivo para el personal: Administrador, Veterinario, Recepcionista).

Genera el código completo de la arquitectura inicial:
1. CONFIGURACIÓN (settings.py y .env.example):
   - Conexión a PostgreSQL mediante variables de entorno (python-decouple).
   - Configuración de Django REST Framework (DRF) con autenticación por sesión (SessionAuthentication).
   - Manejo de archivos estáticos (STATIC_ROOT, STATICFILES_DIRS) listo para producción en AWS EC2 con Nginx.
2. USUARIOS Y CONTROL DE ACCESO (models.py):
   - Modelo de usuario extendiendo AbstractUser con campo de selección de roles: 'ADMIN', 'VET' (Veterinario), 'RECEP' (Recepcionista).
3. MODELOS DEL DOMINIO (models.py):
   - Tutor: RUT chileno (único, indexado), nombres, apellidos, teléfono, email, dirección.
   - Mascota: ForeignKey a Tutor, nombre, especie (Canino, Felino, Exótico), raza, sexo, fecha_nacimiento, peso, observaciones/alergias.
   - Cita: ForeignKey a Mascota, ForeignKey al usuario Veterinario (limit_choices_to={'rol': 'VET'}), fecha, hora_inicio, hora_fin, motivo, estado ('PROGRAMADA', 'CONFIRMADA', 'EN_ATENCION', 'FINALIZADA', 'CANCELADA').
     * REGLA CRÍTICA ANTI-SOLAPAMIENTO: Implementa validación estricta en el método clean() y validación a nivel de ORM con Q para garantizar que un mismo veterinario no pueda tener dos citas que se superpongan en horario (hora_inicio < nueva_hora_fin y hora_fin > nueva_hora_inicio) en la misma fecha.
   - FichaClinica: ForeignKey/OneToOne a Mascota, ForeignKey a Cita (opcional), ForeignKey a Usuario Veterinario, fecha_registro, anamnesis, constantes vitales (temperatura, peso actual, FC), diagnóstico_presuntivo, diagnóstico_definitivo, tratamiento, receta_medica, exámenes_solicitados.
   - ControlVacuna: ForeignKey a Mascota, tipo ('VACUNA', 'DESPARASITACION', 'CONTROL_GENERAL'), nombre_producto, fecha_aplicacion, fecha_proximo_vencimiento, estado ('PENDIENTE', 'AL_DIA', 'VENCIDO').

Entrega el código de requirements.txt, .env.example y models.py completo con sus métodos __str__ y metadatos Meta.
```

### 3. Modelo utilizado
- **Claude Opus 5.5**.

### 4. Cómo se validó y mejoró el resultado
- **Decisión de cardinalidad en `FichaClinica`**: El prompt planteaba `ForeignKey/OneToOne a Mascota`. Se definió `ForeignKey` hacia `Mascota` (porque un paciente acumula múltiples fichas a lo largo de su vida clínica) y `OneToOneField(null=True, blank=True)` hacia `Cita` (cada cita origina como máximo una ficha clínica).
- **Defensa en profundidad en la regla anti-solapamiento**: Además de la validación con objetos `Q` en `Cita.clean()`, se forzó `self.full_clean()` dentro de `Cita.save()` (ya que DRF no invoca `Model.clean()` automáticamente) y se añadió una restricción `ExclusionConstraint` GiST en PostgreSQL junto con `BtreeGistExtension()` en la migración inicial para evitar condiciones de carrera concurrentes.
- **Validación de RUT chileno con Módulo 11**: Se creó `clinica/validators.py` con normalización canónica (`12.345.678-k` → `12345678-K`) y cálculo real de dígito verificador.
- **Verificación ejecutada**: Se corrió `python manage.py check` (0 problemas) y se probó el validador de RUT con casos reales.

---

## Etapa 2: Diseño Empresarial de Django Admin

### 1. Rol solicitado a la IA
> *"Actúa como un Desarrollador Django Senior."*

### 2. Prompt ejecutado
```text
Actúa como un Desarrollador Django Senior. Basándote en los modelos del proyecto PetCare, diseña un archivo admin.py empresarial y altamente visual:

1. Personalización de Cabeceras:
   - admin.site.site_header = "PetCare | Panel de Control Veterinario"
   - admin.site.site_title = "PetCare Admin"
   - admin.site.index_title = "Administración Central del Sistema"
2. Configuración de ModelAdmins:
   - TutorAdmin: Búsqueda por RUT, apellido y teléfono. List display con nombre completo y método computado que cuente las mascotas asociadas.
   - MascotaAdmin: Incluye un TabularInline para visualizar y agregar ControlVacuna directamente dentro de la ficha de la mascota. Filtros por especie y sexo.
   - CitaAdmin: Filtros por veterinario, estado y fecha. Método con format_html para renderizar badges de color según el estado (Verde = Finalizada, Azul = En Atención, Amarillo = Programada, Rojo = Cancelada).
   - FichaClinicaAdmin: Agrupación de campos mediante fieldsets (Datos de Consulta, Evaluación Médica, Tratamiento y Exámenes). Búsqueda por nombre de mascota o RUT del tutor.
   - ControlVacunaAdmin: Indicador visual con format_html que resalte en rojo si la fecha de vencimiento ya expiró respecto al día de hoy.

Entrega el archivo admin.py completo y listo para producción.
```

### 3. Modelo utilizado
- **Gemini 4 Argon / Gemini 3.8 Flash**.

### 4. Cómo se validó y mejoró el resultado
- **Prevención de consultas N+1**: En `TutorAdmin.get_queryset()` se utilizó `annotate(_total_mascotas=Count("mascotas"))` en lugar de ejecutar `.count()` por fila, y se agregó `list_select_related` en `MascotaAdmin`, `CitaAdmin`, `FichaClinicaAdmin` y `ControlVacunaAdmin`.
- **Seguridad XSS en `format_html`**: Se verificó mediante una prueba en consola que entradas maliciosas como `<script>` fueran escapadas como `&lt;script&gt;`.
- **Búsqueda tolerante a puntos en RUT**: Se creó `BusquedaRutMixin` para que el personal pueda buscar `12.345.678-5` en la barra del admin y coincida con `12345678-5` almacenado en la base de datos.
- **Eliminación de mensajes duplicados**: Se sobreescribió `Cita.get_constraints()` para que los formularios del Admin muestren únicamente el mensaje detallado de `Cita.clean()` cuando ocurre un solapamiento.

---

## Etapa 3: Lógica de Negocio, Endpoints DRF y Permisos por Rol

### 1. Rol solicitado a la IA
> *"Desarrollador Backend Senior en Django REST Framework y Seguridad de Aplicaciones."*

### 2. Prompt ejecutado
```text
Desarrolla la capa de lógica de negocio y endpoints (serializers.py, views.py y urls.py) para PetCare:

1. serializers.py:
   - Serializadores para Tutor, Mascota, Cita, FichaClinica y ControlVacuna.
   - Serializador de Cita con validación que rechace registros si hora_fin <= hora_inicio o si el veterinario ya tiene una cita reservada en ese lapso.
   - Serializador adaptado para FullCalendar (id, title, start, end, color, extendedProps).
2. SEGURIDAD Y PERMISOS (views.py):
   - Todas las vistas requieren sesión activa (@login_required o IsAuthenticated).
   - Crear permisos/decoradores para que 'Recepción' pueda gestionar Tutores, Mascotas y Citas, pero la creación/edición de FichaClinica y aplicación de ControlVacuna esté restringida a 'VET' y 'ADMIN'.
3. FUNCIONALIDADES CLAVE:
   - Módulo Calendario: Endpoint /api/citas/calendario/?veterinario_id=X que retorne los eventos filtrados para renderizar en FullCalendar.
   - Módulo Recordatorios: Vista y endpoint que filtre y retorne automáticamente las vacunas en 3 grupos: Vencidas (< hoy), Críticas (próximos 7 días) y Al día.
   - Vistas tradicionales de Django combinadas con llamadas a la API para los CRUDs de Tutores y Mascotas.

Entrega serializers.py, views.py y urls.py de forma modular y sin omitir lógica de negocio.
```

### 3. Modelo utilizado
- **Claude Opus 5.5**.

### 4. Cómo se validó y mejoró el resultado
- **Desacoplamiento en capa de servicios (`clinica/services.py`)**: Se extrajo la máquina de estados de citas (`cambiar_estado_cita`), el cierre transaccional de cita al emitir ficha (`registrar_ficha`) y el algoritmo de clasificación de vacunas (`agrupar_recordatorios`) para evitar vistas sobrecargadas.
- **Descarte de vacunas históricas reemplazadas**: En `controles_vigentes()` se implementó una subconsulta `~Exists(...)` que excluye dosis antiguas cuando la misma mascota ya tiene una aplicación más reciente del mismo producto, evitando falsos positivos en la columna de "Vencidas".
- **Validación en `PATCH` parciales**: En `CitaSerializer.validate()` se combinaron los atributos entrantes con `self.instance` para que una edición parcial de horario nunca pueda saltarse la regla anti-solapamiento.

---

## Etapa 4: Interfaz "Dark Mode Clínico" con Bootstrap 5.3 y FullCalendar 6

### 1. Rol solicitado a la IA
> *"Actúa como un Diseñador UI/UX Senior y Frontend Engineer de élite."*

### 2. Prompt ejecutado
```text
Actúa como un Diseñador UI/UX Senior y Frontend Engineer de élite. Crea el conjunto de templates para "PetCare" utilizando Django Templates, Bootstrap 5.3 (data-bs-theme="dark"), Bootstrap Icons y FullCalendar 6.

ESTILO VISUAL OBLIGATORIO:
- Tema: Dark Mode Clínico de alto contraste.
- Paleta: Fondo principal #0b0f19, tarjetas y sidebar #111827, bordes sutiles #1f2937, acento primario Cian Médico (#06b6d4), acento secundario Verde Esmeralda (#10b981) para confirmaciones/salud, y Púrpura suave (#8b5cf6) para badges de rol.
- Tipografía limpia, sombras sutiles, microinteracciones y tablas estilizadas.

TEMPLATES REQUERIDOS:
1. base.html: Sidebar lateral fijo y colapsable con logotipo, navegación y tarjeta de perfil del trabajador actual. Barra superior con reloj en tiempo real y cierre de sesión.
2. dashboard.html: Tarjetas KPI con bordes luminosos y tabla con la agenda inmediata del día.
3. tutores_mascotas.html: Buscador dinámico en tiempo real y modales modernos para dar de alta o editar Tutores y Mascotas mediante fetch sin recargar la página.
4. calendario_citas.html: Contenedor FullCalendar oscuro, selector de veterinario en tiempo real y modal para agendar citas con alertas dinámicas de solapamiento.
5. ficha_clinica.html: Timeline vertical de atenciones previas y formulario en pestañas (Examen Físico, Diagnóstico, Prescripción y Exámenes).
6. recordatorios.html: Panel semáforo/Kanban con 3 columnas ("Vencidas", "Próximos 7 Días", "Al Día") con opción para marcar como aplicada.
```

### 3. Modelo utilizado
- **Claude Sonnet 5.5**.

### 4. Cómo se validó y mejoró el resultado
- **Cliente HTTP centralizado (`static/js/petcare.js`)**: Se encapsuló el envío automático del encabezado `X-CSRFToken` requerido por `SessionAuthentication` de DRF y el formateo de errores de validación por campo.
- **Pre-detección de choque horario en vivo**: En `calendario_citas.html`, antes incluso de enviar el formulario al backend, la función `verificarSolapamientoEnVivo()` contrasta el rango elegido con los eventos cargados en FullCalendar y despliega una alerta visual inmediata si detecta superposición.
- **Degradación elegante según rol**: En `ficha_clinica.html` y `recordatorios.html`, cuando ingresa un usuario con rol `RECEP`, los controles exclusivos de acto médico (`Emitir Ficha` y `Marcar como Aplicada`) se deshabilitan en la interfaz además de estar protegidos con HTTP 403 en la API.
- **CRUD completo en templates (Creación, Lectura, Edición y Eliminación/Baja)**: En `tutores_mascotas.html`, `calendario_citas.html`, `ficha_clinica.html` y `recordatorios.html` se habilitaron acciones de edición y eliminación directa hacia PostgreSQL mediante `PATCH` y `DELETE`, ofreciendo dar de baja lógica (`activo=False`) cuando un registro clínico está protegido por `on_delete=models.PROTECT` (HTTP 409).
- **Módulo de Personal, Asistencia (`AsistenciaPersonal`) y Bloqueo por Inactividad con PIN**: Se implementó `personal_usuarios.html` para gestión de usuarios/roles y registro diario de asistencia, junto con bloqueo automático a los 5 minutos de inactividad (`verificar_pin_view` con límite de intentos contra fuerza bruta), cierre de sesión a los 10 minutos y vista personalizada `404.html`.

---

## Etapa 5: Automatización DevOps en AWS EC2 y Documentación Docente

### 1. Rol solicitado a la IA
> *"Actúa como un Ingeniero DevOps y Docente de Arquitectura de Software."*

### 2. Prompt ejecutado
```text
Actúa como un Ingeniero DevOps y Docente de Arquitectura de Software. Genera los archivos finales de despliegue y documentación para la Evaluación 3 de PetCare:

1. SCRIPT DE DESPLIEGUE (deploy_ec2.sh):
   - Script Bash para Ubuntu Server en AWS EC2 que de forma no interactiva:
     * Instale PostgreSQL, Python3-venv, Nginx y Gunicorn.
     * Configure la base de datos PostgreSQL, usuario y permisos locales.
     * Configure el entorno virtual, dependencias, ejecute makemigrations, migrate y collectstatic.
     * Configure Gunicorn como servicio systemd (/etc/systemd/system/gunicorn.service).
     * Configure Nginx como reverse proxy en el puerto 80 apuntando a Gunicorn y a la carpeta de estáticos.
2. README.md:
   - Portada profesional del proyecto, diagrama de arquitectura de la solución.
   - Bloque destacado para ingresar la IP Pública de AWS EC2 y credenciales predeterminadas para revisión docente (Admin, Veterinario y Recepcionista).
   - Manual paso a paso de ejecución tanto en entorno local como en la nube.
3. prompts_ia.md:
   - Documento exigido por la rúbrica donde se desglosa el uso de IA durante todo el ciclo de desarrollo en las 5 etapas.
```

### 3. Modelo utilizado
- **Gemini 4 Argon**.

### 4. Cómo se validó y mejoró el resultado
- **Soporte IMDSv2 en AWS EC2**: El script `deploy_ec2.sh` solicita un token temporal IMDSv2 (`http://169.254.169.254/latest/api/token`) para descubrir automáticamente la IP pública de la instancia e inyectarla en `ALLOWED_HOSTS` y `CSRF_TRUSTED_ORIGINS`.
- **Creación automática de `btree_gist` y semilla de datos**: Se incluyó `CREATE EXTENSION IF NOT EXISTS btree_gist;` en el bloque SQL de PostgreSQL y el comando idempotente `python manage.py seed_petcare` para que el docente evaluador disponga inmediatamente de los 3 roles (`admin`, `dra.morales`, `recepcion`) y datos clínicos reales tras correr `deploy_ec2.sh`.
