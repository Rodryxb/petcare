"""
Comando de gestión `python manage.py cargar_datos_defensa`:
Carga de forma idempotente en cualquier entorno (p. ej. AWS EC2) los tutores,
mascotas con sus fotografías reales (`media/mascotas/*`), citas, fichas clínicas,
vacunas y catálogo POS exportados desde el entorno local para la defensa oral.
"""
import json
import shutil
from datetime import date, time
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from clinica.catalogo_pos import asegurar_catalogo_pos
from clinica.models import Cita, ControlVacuna, FichaClinica, Mascota, Tutor
from usuarios.models import Usuario


class Command(BaseCommand):
    help = "Importa datos clínicos y fotos reales de mascotas para sincronizar AWS EC2 con local."

    def _copiar_fotos_media(self):
        origen = Path(settings.BASE_DIR) / "media" / "mascotas"
        destino = Path(settings.MEDIA_ROOT) / "mascotas"
        if not origen.exists():
            return 0
        destino.mkdir(parents=True, exist_ok=True)
        copiadas = 0
        if origen.resolve() != destino.resolve():
            for archivo in origen.iterdir():
                if archivo.is_file():
                    shutil.copy2(archivo, destino / archivo.name)
                    copiadas += 1
        return copiadas

    @transaction.atomic
    def handle(self, *args, **options):
        fixture_path = Path(settings.BASE_DIR) / "clinica" / "fixtures" / "datos_defensa.json"
        if not fixture_path.exists():
            self.stderr.write(self.style.ERROR(f"No se encontró {fixture_path}"))
            return

        with fixture_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)

        fotos_copiadas = self._copiar_fotos_media()

        # 1. Usuarios por username o email (evita colisiones de PK entre entornos)
        usuarios_map = {}
        for u_cfg in data.get("usuarios", []):
            uname = u_cfg["username"]
            user = (
                Usuario.objects.filter(username=uname).first()
                or Usuario.objects.filter(email__iexact=u_cfg["email"]).first()
            )
            if user is None:
                user = Usuario(**u_cfg)
                user.set_password("PetCare2026!")
                user.save()
            usuarios_map[uname] = user

        # 2. Tutores por RUT
        tutores_map = {}
        for t_cfg in data.get("tutores", []):
            tutor, _ = Tutor.objects.update_or_create(
                rut=t_cfg["rut"],
                defaults={k: v for k, v in t_cfg.items() if k != "rut"},
            )
            tutores_map[tutor.rut] = tutor

        # 3. Mascotas + fotografías + ficha descriptiva
        mascotas_map = {}
        for m_cfg in data.get("mascotas", []):
            tutor = tutores_map[m_cfg["tutor_rut"]]
            defaults = {
                "especie": m_cfg["especie"],
                "raza": m_cfg["raza"],
                "sexo": m_cfg["sexo"],
                "fecha_nacimiento": (
                    date.fromisoformat(m_cfg["fecha_nacimiento"]) if m_cfg.get("fecha_nacimiento") else None
                ),
                "peso": Decimal(m_cfg["peso"]) if m_cfg.get("peso") else None,
                "alergias": m_cfg["alergias"],
                "observaciones": m_cfg["observaciones"],
                "foto": m_cfg["foto"],
                "color": m_cfg["color"],
                "condicion_corporal": m_cfg["condicion_corporal"],
                "cicatrices": m_cfg["cicatrices"],
                "cirugias_esterilizacion": m_cfg["cirugias_esterilizacion"],
                "datos_medioambientales": m_cfg["datos_medioambientales"],
                "nutricion": m_cfg["nutricion"],
                "entorno": m_cfg["entorno"],
                "numero_chip": m_cfg["numero_chip"],
                "activo": m_cfg["activo"],
            }
            mascota, _ = Mascota.objects.update_or_create(
                tutor=tutor,
                nombre=m_cfg["nombre"],
                defaults=defaults,
            )
            mascotas_map[(tutor.rut, mascota.nombre)] = mascota

        # 4. Citas (respetando restricción de no solapamiento)
        for c_cfg in data.get("citas", []):
            mascota = mascotas_map.get((c_cfg["tutor_rut"], c_cfg["mascota_nombre"]))
            vet = usuarios_map.get(c_cfg["veterinario_username"])
            if not mascota or not vet:
                continue
            fecha_c = date.fromisoformat(c_cfg["fecha"])
            hi = time.fromisoformat(c_cfg["hora_inicio"])
            hf = time.fromisoformat(c_cfg["hora_fin"])

            existente = Cita.objects.filter(
                mascota=mascota, veterinario=vet, fecha=fecha_c, hora_inicio=hi
            ).first()
            if existente:
                existente.hora_fin = hf
                existente.motivo = c_cfg["motivo"]
                existente.estado = c_cfg["estado"]
                existente.save()
                continue

            solape = (
                Cita.objects.filter(veterinario=vet, fecha=fecha_c, hora_inicio__lt=hf, hora_fin__gt=hi)
                .exclude(estado=Cita.Estado.CANCELADA)
                .exists()
            )
            if not solape:
                Cita.objects.create(
                    mascota=mascota,
                    veterinario=vet,
                    fecha=fecha_c,
                    hora_inicio=hi,
                    hora_fin=hf,
                    motivo=c_cfg["motivo"],
                    estado=c_cfg["estado"],
                )

        # 5. Fichas clínicas
        for f_cfg in data.get("fichas", []):
            mascota = mascotas_map.get((f_cfg["tutor_rut"], f_cfg["mascota_nombre"]))
            vet = usuarios_map.get(f_cfg["veterinario_username"])
            if not mascota or not vet:
                continue
            ya_existe = FichaClinica.objects.filter(
                mascota=mascota, veterinario=vet, anamnesis=f_cfg["anamnesis"]
            ).exists()
            if not ya_existe:
                FichaClinica.objects.create(
                    mascota=mascota,
                    veterinario=vet,
                    anamnesis=f_cfg["anamnesis"],
                    temperatura=Decimal(f_cfg["temperatura"]) if f_cfg.get("temperatura") else None,
                    peso_actual=Decimal(f_cfg["peso_actual"]) if f_cfg.get("peso_actual") else None,
                    frecuencia_cardiaca=f_cfg.get("frecuencia_cardiaca"),
                    diagnostico_presuntivo=f_cfg["diagnostico_presuntivo"],
                    diagnostico_definitivo=f_cfg["diagnostico_definitivo"],
                    tratamiento=f_cfg["tratamiento"],
                    receta_medica=f_cfg["receta_medica"],
                    examenes_solicitados=f_cfg["examenes_solicitados"],
                )

        # 6. Controles de vacunas
        for v_cfg in data.get("vacunas", []):
            mascota = mascotas_map.get((v_cfg["tutor_rut"], v_cfg["mascota_nombre"]))
            if not mascota:
                continue
            vet_ap = usuarios_map.get(v_cfg["aplicado_por_username"]) if v_cfg.get("aplicado_por_username") else None
            ControlVacuna.objects.update_or_create(
                mascota=mascota,
                tipo=v_cfg["tipo"],
                nombre_producto=v_cfg["nombre_producto"],
                defaults={
                    "fecha_aplicacion": (
                        date.fromisoformat(v_cfg["fecha_aplicacion"]) if v_cfg.get("fecha_aplicacion") else None
                    ),
                    "fecha_proximo_vencimiento": (
                        date.fromisoformat(v_cfg["fecha_proximo_vencimiento"])
                        if v_cfg.get("fecha_proximo_vencimiento")
                        else None
                    ),
                    "aplicado_por": vet_ap,
                    "es_externa": v_cfg["es_externa"],
                    "lugar_aplicacion": v_cfg["lugar_aplicacion"],
                    "observaciones": v_cfg["observaciones"],
                },
            )

        total_catalogo = asegurar_catalogo_pos()
        self.stdout.write(
            self.style.SUCCESS(
                f"[OK] Datos de defensa cargados: {len(tutores_map)} tutores, "
                f"{len(mascotas_map)} mascotas, {fotos_copiadas} fotos copiadas a MEDIA_ROOT, "
                f"{total_catalogo} ítems POS/Tienda activos."
            )
        )
