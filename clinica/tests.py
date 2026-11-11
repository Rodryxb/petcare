"""Pruebas unitarias de reglas de negocio y serializadores de PetCare."""
from datetime import date, time

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from django.urls import reverse

from usuarios.models import Usuario

from .models import Cita, Mascota, Tutor
from .serializers import CitaCalendarioSerializer
from .validators import calcular_dv, normalizar_rut, validar_rut


class ValidadorRutTests(SimpleTestCase):
    def test_normaliza_y_valida_rut_correcto(self):
        self.assertEqual(normalizar_rut("12.345.678-5"), "12345678-5")
        self.assertEqual(calcular_dv("12345678"), "5")
        validar_rut("12.345.678-5")
        validar_rut("11.111.111-1")
        validar_rut("18.000.002-k")

    def test_rechaza_rut_con_digito_verificador_invalido(self):
        with self.assertRaises(ValidationError):
            validar_rut("12.345.678-9")


class CitaReglasSinBDTests(SimpleTestCase):
    def test_clean_rechaza_hora_fin_anterior_o_igual_a_inicio(self):
        vet = Usuario(id=1, username="vet", rol=Usuario.Rol.VET)
        tutor = Tutor(id=1, rut="12345678-5", nombres="Ana", apellidos="Soto", telefono="+56911112222")
        mascota = Mascota(id=1, tutor=tutor, nombre="Luna", especie="FELINO", sexo="HEMBRA")
        cita = Cita(
            mascota=mascota,
            veterinario=vet,
            fecha=date(2026, 11, 10),
            hora_inicio=time(11, 0),
            hora_fin=time(10, 30),
            motivo="Consulta general",
        )
        with self.assertRaises(ValidationError) as ctx:
            cita.clean()
        self.assertIn("hora_fin", ctx.exception.message_dict)

    def test_clean_rechaza_usuario_que_no_es_veterinario(self):
        recep = Usuario(id=2, username="recep", rol=Usuario.Rol.RECEP)
        tutor = Tutor(id=1, rut="12345678-5", nombres="Ana", apellidos="Soto", telefono="+56911112222")
        mascota = Mascota(id=1, tutor=tutor, nombre="Luna", especie="FELINO", sexo="HEMBRA")
        cita = Cita(
            mascota=mascota,
            veterinario=recep,
            fecha=date(2026, 11, 10),
            hora_inicio=time(10, 0),
            hora_fin=time(10, 30),
            motivo="Consulta general",
        )
        with self.assertRaises(ValidationError) as ctx:
            cita.clean()
        self.assertIn("veterinario", ctx.exception.message_dict)

    def test_serializador_fullcalendar_estructura_completa(self):
        vet = Usuario(id=3, username="dra.morales", first_name="Valentina", last_name="Morales", rol=Usuario.Rol.VET)
        tutor = Tutor(id=1, rut="12345678-5", nombres="Ana", apellidos="Soto", telefono="+56911112222")
        mascota = Mascota(id=7, tutor=tutor, nombre="Thor", especie="CANINO", sexo="MACHO")
        cita = Cita(
            id=42,
            mascota=mascota,
            veterinario=vet,
            fecha=date(2026, 11, 10),
            hora_inicio=time(9, 0),
            hora_fin=time(9, 30),
            motivo="Vacunación",
            estado=Cita.Estado.PROGRAMADA,
        )
        data = CitaCalendarioSerializer(cita).data
        self.assertEqual(data["id"], 42)
        self.assertEqual(data["start"], "2026-11-10T09:00:00")
        self.assertEqual(data["end"], "2026-11-10T09:30:00")
        self.assertEqual(data["extendedProps"]["veterinario_id"], 3)
        self.assertEqual(
            data["extendedProps"]["ficha_url"],
            reverse("ficha_clinica_mascota", kwargs={"mascota_id": 7}),
        )
