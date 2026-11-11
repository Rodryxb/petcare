"""Pruebas unitarias de reglas de negocio, permisos RBAC y serializadores de PetCare."""
from datetime import date, time, timedelta
from types import SimpleNamespace

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import RequestFactory, SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from usuarios.models import Usuario
from usuarios.permissions import (
    EliminarSoloAdmin,
    EliminarSoloClinico,
    EsAdminOVeterinario,
    EsAutorFichaOAdmin,
    EsPersonalClinica,
    LecturaPersonalEscrituraClinica,
    LecturaPersonalEscrituraSuperusuario,
)

from .models import Cita, ControlVacuna, FichaClinica, Mascota, Tutor
from .serializers import CitaCalendarioSerializer, CitaSerializer
from .services import cambiar_estado_cita
from .validators import calcular_dv, normalizar_rut, normalizar_termino_busqueda, validar_rut


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

    def test_normalizar_termino_busqueda_con_puntos(self):
        self.assertEqual(normalizar_termino_busqueda("12.345.678-k"), "12345678-K")
        self.assertEqual(normalizar_termino_busqueda("González"), "González")


class CitaReglasSinBDTests(SimpleTestCase):
    def setUp(self):
        self.vet = Usuario(
            id=3,
            username="dra.morales",
            first_name="Valentina",
            last_name="Morales",
            rol=Usuario.Rol.VET,
            is_active=True,
        )
        self.otro_vet = Usuario(
            id=4,
            username="dr.soto",
            first_name="Matías",
            last_name="Soto",
            rol=Usuario.Rol.VET,
            is_active=True,
        )
        self.recep = Usuario(
            id=2,
            username="recepcion",
            rol=Usuario.Rol.RECEP,
            is_active=True,
        )
        self.admin = Usuario(
            id=1,
            username="admin",
            rol=Usuario.Rol.ADMIN,
            is_active=True,
            is_superuser=True,
        )
        self.tutor = Tutor(
            id=1,
            rut="12345678-5",
            nombres="Ana",
            apellidos="Soto",
            telefono="+56911112222",
        )
        self.mascota = Mascota(
            id=7,
            tutor=self.tutor,
            nombre="Thor",
            especie="CANINO",
            sexo="MACHO",
        )

    def test_clean_rechaza_hora_fin_anterior_o_igual_a_inicio(self):
        cita = Cita(
            mascota=self.mascota,
            veterinario=self.vet,
            fecha=date(2026, 11, 10),
            hora_inicio=time(11, 0),
            hora_fin=time(10, 30),
            motivo="Consulta general",
        )
        with self.assertRaises(ValidationError) as ctx:
            cita.clean()
        self.assertIn("hora_fin", ctx.exception.message_dict)

    def test_clean_rechaza_usuario_que_no_es_veterinario(self):
        cita = Cita(
            mascota=self.mascota,
            veterinario=self.recep,
            fecha=date(2026, 11, 10),
            hora_inicio=time(10, 0),
            hora_fin=time(10, 30),
            motivo="Consulta general",
        )
        with self.assertRaises(ValidationError) as ctx:
            cita.clean()
        self.assertIn("veterinario", ctx.exception.message_dict)

    def test_serializador_fullcalendar_estructura_completa(self):
        cita = Cita(
            id=42,
            mascota=self.mascota,
            veterinario=self.vet,
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

    def test_maquina_estados_rechaza_reactivar_cita_cancelada(self):
        cita = Cita(
            id=10,
            mascota=self.mascota,
            veterinario=self.vet,
            fecha=timezone.localdate(),
            hora_inicio=time(9, 0),
            hora_fin=time(9, 30),
            motivo="Control",
            estado=Cita.Estado.CANCELADA,
        )
        with self.assertRaises(ValidationError):
            cambiar_estado_cita(cita, Cita.Estado.PROGRAMADA, self.admin)

    def test_maquina_estados_impide_a_recepcion_iniciar_atencion(self):
        cita = Cita(
            id=11,
            mascota=self.mascota,
            veterinario=self.vet,
            fecha=timezone.localdate(),
            hora_inicio=time(9, 0),
            hora_fin=time(9, 30),
            motivo="Control",
            estado=Cita.Estado.CONFIRMADA,
        )
        with self.assertRaises(PermissionDenied):
            cambiar_estado_cita(cita, Cita.Estado.EN_ATENCION, self.recep)

    def test_maquina_estados_impide_a_otro_veterinario_atender_cita_ajena(self):
        cita = Cita(
            id=12,
            mascota=self.mascota,
            veterinario=self.vet,
            fecha=timezone.localdate(),
            hora_inicio=time(9, 0),
            hora_fin=time(9, 30),
            motivo="Control",
            estado=Cita.Estado.CONFIRMADA,
        )
        with self.assertRaises(PermissionDenied):
            cambiar_estado_cita(cita, Cita.Estado.EN_ATENCION, self.otro_vet)

    def test_serializador_cita_bloquea_transicion_invalida_en_patch(self):
        cita = Cita(
            id=15,
            mascota=self.mascota,
            veterinario=self.vet,
            fecha=timezone.localdate(),
            hora_inicio=time(9, 0),
            hora_fin=time(9, 30),
            motivo="Control",
            estado=Cita.Estado.CANCELADA,
        )
        req = SimpleNamespace(user=self.admin)
        serializer = CitaSerializer(instance=cita, context={"request": req})
        with self.assertRaises( Exception ) as ctx:
            serializer.validate({"estado": Cita.Estado.PROGRAMADA})
        self.assertIn("estado", ctx.exception.detail)


class ControlVacunaEstadoTests(SimpleTestCase):
    def test_calcular_estado_vencido_al_dia_y_pendiente(self):
        hoy = date(2026, 11, 11)
        vencida = ControlVacuna(
            tipo=ControlVacuna.Tipo.VACUNA,
            nombre_producto="Óctuple",
            fecha_aplicacion=hoy - timedelta(days=400),
            fecha_proximo_vencimiento=hoy - timedelta(days=5),
        )
        self.assertEqual(vencida.calcular_estado(hoy=hoy), ControlVacuna.Estado.VENCIDO)

        al_dia = ControlVacuna(
            tipo=ControlVacuna.Tipo.VACUNA,
            nombre_producto="Antirrábica",
            fecha_aplicacion=hoy,
            fecha_proximo_vencimiento=hoy + timedelta(days=365),
        )
        self.assertEqual(al_dia.calcular_estado(hoy=hoy), ControlVacuna.Estado.AL_DIA)

        pendiente = ControlVacuna(
            tipo=ControlVacuna.Tipo.DESPARASITACION,
            nombre_producto="Bravecto",
            fecha_aplicacion=None,
            fecha_proximo_vencimiento=hoy + timedelta(days=7),
        )
        self.assertEqual(pendiente.calcular_estado(hoy=hoy), ControlVacuna.Estado.PENDIENTE)


class PermisosRBACTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.admin = Usuario(
            id=1, username="admin", rol=Usuario.Rol.ADMIN, is_active=True, is_superuser=True
        )
        self.vet = Usuario(
            id=2, username="dra.morales", rol=Usuario.Rol.VET, is_active=True, is_superuser=False
        )
        self.otro_vet = Usuario(
            id=3, username="dr.soto", rol=Usuario.Rol.VET, is_active=True, is_superuser=False
        )
        self.recep = Usuario(
            id=4, username="recepcion", rol=Usuario.Rol.RECEP, is_active=True, is_superuser=False
        )

    def _req(self, method: str, user):
        req = getattr(self.factory, method.lower())("/api/test/")
        req.user = user
        return req

    def test_lectura_personal_escritura_clinica(self):
        perm = LecturaPersonalEscrituraClinica()
        self.assertTrue(perm.has_permission(self._req("GET", self.recep), None))
        self.assertFalse(perm.has_permission(self._req("POST", self.recep), None))
        self.assertTrue(perm.has_permission(self._req("POST", self.vet), None))
        self.assertTrue(perm.has_permission(self._req("POST", self.admin), None))

    def test_autor_ficha_o_admin(self):
        perm = EsAutorFichaOAdmin()
        ficha = FichaClinica(id=1, veterinario_id=self.vet.id)
        self.assertTrue(perm.has_object_permission(self._req("PATCH", self.vet), None, ficha))
        self.assertFalse(perm.has_object_permission(self._req("PATCH", self.otro_vet), None, ficha))
        self.assertTrue(perm.has_object_permission(self._req("PATCH", self.admin), None, ficha))
        self.assertTrue(perm.has_object_permission(self._req("GET", self.recep), None, ficha))

    def test_eliminar_solo_admin_y_solo_clinico(self):
        perm_admin = EliminarSoloAdmin()
        self.assertFalse(perm_admin.has_permission(self._req("DELETE", self.recep), None))
        self.assertFalse(perm_admin.has_permission(self._req("DELETE", self.vet), None))
        self.assertTrue(perm_admin.has_permission(self._req("DELETE", self.admin), None))

        perm_clinico = EliminarSoloClinico()
        self.assertFalse(perm_clinico.has_permission(self._req("DELETE", self.recep), None))
        self.assertTrue(perm_clinico.has_permission(self._req("DELETE", self.vet), None))

    def test_lectura_personal_escritura_superusuario(self):
        perm = LecturaPersonalEscrituraSuperusuario()
        self.assertTrue(perm.has_permission(self._req("GET", self.recep), None))
        self.assertFalse(perm.has_permission(self._req("POST", self.vet), None))
        self.assertTrue(perm.has_permission(self._req("POST", self.admin), None))
