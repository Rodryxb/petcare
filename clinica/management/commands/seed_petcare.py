"""
Comando de gestión `python manage.py seed_petcare`:
Crea de forma idempotente las cuentas predeterminadas de revisión docente
(ADMIN, VET, RECEP) y datos clínicos de demostración (tutores con RUT válido,
mascotas, citas del día, fichas clínicas y controles de vacunas en los 3 estados).
"""
from datetime import date, time, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from clinica.models import Cita, ControlVacuna, FichaClinica, Mascota, Tutor
from usuarios.models import AsistenciaPersonal, Usuario


class Command(BaseCommand):
    help = "Crea usuarios de revisión docente (ADMIN, VET, RECEP) y datos clínicos iniciales."

    @transaction.atomic
    def handle(self, *args, **options):
        clave_demo = "PetCare2026!"

        # Renombrar cuentas demo anteriores si ya existían en BD para mantener trazabilidad
        for anterior, nuevo in (("dra.morales", "dr.munoz"), ("dr.soto", "dr.suazo")):
            if (
                Usuario.objects.filter(username=anterior).exists()
                and not Usuario.objects.filter(username=nuevo).exists()
            ):
                Usuario.objects.filter(username=anterior).update(username=nuevo)
            elif Usuario.objects.filter(username=anterior).exists():
                Usuario.objects.filter(username=anterior).update(is_active=False)

        # 1. Usuarios del personal con sus 3 roles
        usuarios_cfg = [
            {
                "username": "admin",
                "first_name": "Rodrigo",
                "last_name": "Castro",
                "email": "admin@petcare.cl",
                "rol": Usuario.Rol.ADMIN,
                "is_staff": True,
                "is_superuser": True,
                "telefono": "+56 9 9100 1000",
            },
            {
                "username": "dr.munoz",
                "first_name": "Egon",
                "last_name": "Muñoz",
                "email": "emunoz@petcare.cl",
                "rol": Usuario.Rol.VET,
                "is_staff": True,
                "is_superuser": False,
                "telefono": "+56 9 9200 2000",
            },
            {
                "username": "dr.suazo",
                "first_name": "Renato",
                "last_name": "Suazo",
                "email": "rsuazo@petcare.cl",
                "rol": Usuario.Rol.VET,
                "is_staff": False,
                "is_superuser": False,
                "telefono": "+56 9 9300 3000",
            },
            {
                "username": "recepcion",
                "first_name": "Camila",
                "last_name": "Fuentes",
                "email": "recepcion@petcare.cl",
                "rol": Usuario.Rol.RECEP,
                "is_staff": False,
                "is_superuser": False,
                "telefono": "+56 9 9400 4000",
            },
        ]

        usuarios = {}
        for cfg in usuarios_cfg:
            username = cfg["username"]
            user, creado = Usuario.objects.update_or_create(
                username=username,
                defaults={k: v for k, v in cfg.items() if k != "username"},
            )
            if creado or not user.check_password(clave_demo):
                user.set_password(clave_demo)
                user.save()
            usuarios[username] = user

        vet_principal = usuarios["dr.munoz"]
        vet_secundario = usuarios["dr.suazo"]

        # 2. Tutores (RUTs chilenos con dígito verificador módulo 11 válido)
        tutores_cfg = [
            {
                "rut": "12345678-5",
                "nombres": "Sebastián Andrés",
                "apellidos": "González Muñoz",
                "telefono": "+56 9 8765 4321",
                "email": "sgonzalez@correo.cl",
                "direccion": "Av. Providencia 2140, Providencia",
            },
            {
                "rut": "11111111-1",
                "nombres": "Francisca Javiera",
                "apellidos": "Silva Contreras",
                "telefono": "+56 9 7654 3210",
                "email": "fsilva@correo.cl",
                "direccion": "Los Militares 5890, Las Condes",
            },
            {
                "rut": "18000002-K",
                "nombres": "Rodrigo Ignacio",
                "apellidos": "Valdés Herrera",
                "telefono": "+56 9 6543 2109",
                "email": "rvaldes@correo.cl",
                "direccion": "Av. Irarrázaval 3400, Ñuñoa",
            },
        ]

        tutores = {}
        for t_cfg in tutores_cfg:
            tutor, _ = Tutor.objects.update_or_create(rut=t_cfg["rut"], defaults=t_cfg)
            tutores[tutor.rut] = tutor

        # 3. Mascotas
        mascotas_cfg = [
            {
                "tutor": tutores["12345678-5"],
                "nombre": "Thor",
                "especie": Mascota.Especie.CANINO,
                "raza": "Golden Retriever",
                "sexo": Mascota.Sexo.MACHO,
                "fecha_nacimiento": date(2022, 4, 15),
                "peso": Decimal("29.40"),
                "alergias": "Alergia cutánea a sulfonamidas",
                "observaciones": "Paciente dócil, microchip #9810981000231.",
            },
            {
                "tutor": tutores["11111111-1"],
                "nombre": "Mishi",
                "especie": Mascota.Especie.FELINO,
                "raza": "Europeo de Pelo Corto",
                "sexo": Mascota.Sexo.HEMBRA,
                "fecha_nacimiento": date(2023, 8, 10),
                "peso": Decimal("4.15"),
                "alergias": "",
                "observaciones": "Indoor estricto, esterilizada.",
            },
            {
                "tutor": tutores["18000002-K"],
                "nombre": "Kiwi",
                "especie": Mascota.Especie.EXOTICO,
                "raza": "Conejo Belier",
                "sexo": Mascota.Sexo.MACHO,
                "fecha_nacimiento": date(2024, 2, 1),
                "peso": Decimal("1.85"),
                "alergias": "Sensibilidad digestiva a betalactámicos orales",
                "observaciones": "Dieta basada en heno de alfalfa y pellets.",
            },
        ]

        mascotas = {}
        for m_cfg in mascotas_cfg:
            mascota, _ = Mascota.objects.update_or_create(
                tutor=m_cfg["tutor"],
                nombre=m_cfg["nombre"],
                defaults=m_cfg,
            )
            mascotas[mascota.nombre] = mascota

        # 4. Citas para hoy (sin solapamiento)
        hoy = timezone.localdate()
        citas_cfg = [
            {
                "mascota": mascotas["Thor"],
                "veterinario": vet_principal,
                "fecha": hoy,
                "hora_inicio": time(10, 0),
                "hora_fin": time(10, 30),
                "motivo": "Control dermatológico y refuerzo vacuna óctuple",
                "estado": Cita.Estado.CONFIRMADA,
            },
            {
                "mascota": mascotas["Mishi"],
                "veterinario": vet_principal,
                "fecha": hoy,
                "hora_inicio": time(10, 30),
                "hora_fin": time(11, 0),
                "motivo": "Chequeo preventivo anual y control de peso",
                "estado": Cita.Estado.PROGRAMADA,
            },
            {
                "mascota": mascotas["Kiwi"],
                "veterinario": vet_secundario,
                "fecha": hoy,
                "hora_inicio": time(11, 0),
                "hora_fin": time(11, 30),
                "motivo": "Revisión dental de incisivos y control exóticos",
                "estado": Cita.Estado.EN_ATENCION,
            },
        ]

        for c_cfg in citas_cfg:
            Cita.objects.get_or_create(
                veterinario=c_cfg["veterinario"],
                fecha=c_cfg["fecha"],
                hora_inicio=c_cfg["hora_inicio"],
                defaults=c_cfg,
            )

        # 5. Ficha clínica histórica de ejemplo
        if not FichaClinica.objects.filter(mascota=mascotas["Thor"]).exists():
            FichaClinica.objects.create(
                mascota=mascotas["Thor"],
                veterinario=vet_principal,
                anamnesis="Tutor reporta prurito moderado en pabellón auricular derecho de 3 días de evolución.",
                temperatura=Decimal("38.6"),
                peso_actual=Decimal("29.40"),
                frecuencia_cardiaca=96,
                diagnostico_presuntivo="Otitis externa eritematosa ceruminosa",
                diagnostico_definitivo="Otitis externa por Malassezia spp.",
                tratamiento="Limpieza ótica en consulta con solución ceruminolítica.",
                receta_medica="Gotas óticas antifúngicas: 5 gotas cada 12 horas por 10 días.",
                examenes_solicitados="Citología de secreción ótica bilateral.",
            )

        # 6. Controles de vacunas en los 3 estados del semáforo (Vencida, Crítica <= 7d, Al día)
        controles_cfg = [
            {
                "mascota": mascotas["Thor"],
                "tipo": ControlVacuna.Tipo.VACUNA,
                "nombre_producto": "Vacuna Antirrábica Canina",
                "fecha_aplicacion": hoy - timedelta(days=372),
                "fecha_proximo_vencimiento": hoy - timedelta(days=7),  # VENCIDA
                "aplicado_por": vet_principal,
                "observaciones": "Requiere refuerzo anual inmediato.",
            },
            {
                "mascota": mascotas["Mishi"],
                "tipo": ControlVacuna.Tipo.VACUNA,
                "nombre_producto": "Vacuna Triple Felina",
                "fecha_aplicacion": hoy - timedelta(days=361),
                "fecha_proximo_vencimiento": hoy + timedelta(days=4),  # CRÍTICA (próximos 7 días)
                "aplicado_por": vet_principal,
                "observaciones": "Contactar a tutora para agendar refuerzo esta semana.",
            },
            {
                "mascota": mascotas["Kiwi"],
                "tipo": ControlVacuna.Tipo.DESPARASITACION,
                "nombre_producto": "Desparasitación Interna Fenbendazol",
                "fecha_aplicacion": hoy - timedelta(days=15),
                "fecha_proximo_vencimiento": hoy + timedelta(days=75),  # AL DÍA
                "aplicado_por": vet_secundario,
                "observaciones": "Tolerancia óptima.",
            },
        ]

        for ctrl in controles_cfg:
            ControlVacuna.objects.update_or_create(
                mascota=ctrl["mascota"],
                tipo=ctrl["tipo"],
                nombre_producto=ctrl["nombre_producto"],
                defaults=ctrl,
            )

        # 7. Registro histórico de asistencia del personal (Presente / Ausente)
        admin_user = usuarios["admin"]
        dias_asistencia = [
            (hoy, {"admin": "PRESENTE", "dr.munoz": "PRESENTE", "dr.suazo": "PRESENTE", "recepcion": "PRESENTE"}),
            (hoy - timedelta(days=1), {"admin": "PRESENTE", "dr.munoz": "PRESENTE", "dr.suazo": "AUSENTE", "recepcion": "PRESENTE"}),
            (hoy - timedelta(days=2), {"admin": "PRESENTE", "dr.munoz": "AUSENTE", "dr.suazo": "PRESENTE", "recepcion": "PRESENTE"}),
            (hoy - timedelta(days=3), {"admin": "PRESENTE", "dr.munoz": "PRESENTE", "dr.suazo": "PRESENTE", "recepcion": "PRESENTE"}),
        ]
        for fecha_dia, mapa in dias_asistencia:
            for uname, est in mapa.items():
                AsistenciaPersonal.objects.update_or_create(
                    usuario=usuarios[uname],
                    fecha=fecha_dia,
                    defaults={"estado": est, "registrado_por": admin_user},
                )

        self.stdout.write(
            self.style.SUCCESS(
                "[OK] Datos iniciales de PetCare cargados correctamente (admin / dr.munoz / dr.suazo / recepcion -> PetCare2026!)."
            )
        )
