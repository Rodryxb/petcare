"""Pruebas unitarias de reglas de negocio, permisos RBAC y serializadores de PetCare."""
from datetime import date, time, timedelta
from types import SimpleNamespace

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import QueryDict
from django.test import RequestFactory, SimpleTestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import ValidationError as DRFValidationError

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

from .context_processors import sidebar_alertas
from .models import Cita, ControlVacuna, FichaClinica, Mascota, ProductoServicio, Tutor
from .serializers import (
    CitaCalendarioSerializer,
    CitaSerializer,
    ControlVacunaSerializer,
    MascotaSerializer,
    ProductoServicioSerializer,
)
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
            username="dr.munoz",
            first_name="Egon",
            last_name="Muñoz",
            rol=Usuario.Rol.VET,
            is_active=True,
        )
        self.otro_vet = Usuario(
            id=4,
            username="dr.suazo",
            first_name="Renato",
            last_name="Suazo",
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
            first_name="Rodrigo",
            last_name="Castro",
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

    def test_serializador_cita_compone_motivos_choices_y_otro_motivo(self):
        serializer = CitaSerializer()
        attrs = serializer.validate(
            {
                "motivos_seleccionados": [
                    "CONTROL_ANUAL",
                    "VACUNA_ANTIRRABICA",
                    "DESPARASITACION",
                    "OTRO",
                ],
                "otro_motivo": "Revisión de patita delantera",
            }
        )
        self.assertEqual(
            attrs["motivo"],
            "Control Anual, Vacuna Antirrábica, Desparasitación Interna / Externa, Otro motivo: Revisión de patita delantera",
        )

        with self.assertRaises(Exception) as ctx_otro:
            serializer.validate({"motivos_seleccionados": ["CONTROL_ANUAL", "OTRO"], "otro_motivo": "   "})
        self.assertIn("otro_motivo", ctx_otro.exception.detail)

        with self.assertRaises(Exception) as ctx_vacio:
            serializer.validate({"motivos_seleccionados": []})
        self.assertIn("motivo", ctx_vacio.exception.detail)


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

    def test_serializador_cuenta_regresiva_y_alerta_una_semana(self):
        hoy = timezone.localdate()
        tutor = Tutor(nombres="Sebastián", apellidos="González", rut="12345678-5", telefono="+56912345678", email="s@test.cl")
        mascota = Mascota(nombre="Thor", especie=Mascota.Especie.CANINO, tutor=tutor)

        critica = ControlVacuna(
            mascota=mascota,
            tipo=ControlVacuna.Tipo.VACUNA,
            nombre_producto="Vacuna Óctuple Canina",
            fecha_aplicacion=hoy - timedelta(days=15),
            fecha_proximo_vencimiento=hoy + timedelta(days=6),
        )
        serializer = ControlVacunaSerializer()
        self.assertEqual(serializer.get_dias_para_vencer(critica), 6)
        self.assertEqual(serializer.get_dias_totales_ciclo(critica), 21)
        self.assertTrue(serializer.get_alerta_una_semana(critica))
        self.assertEqual(serializer.get_semaforo(critica), "CRITICA")
        self.assertIn("una semana", serializer.get_mensaje_alerta(critica))
        self.assertGreater(serializer.get_porcentaje_transcurrido(critica), 0)

        lejana = ControlVacuna(
            mascota=mascota,
            tipo=ControlVacuna.Tipo.VACUNA,
            nombre_producto="Antirrábica Canina",
            fecha_aplicacion=hoy - timedelta(days=5),
            fecha_proximo_vencimiento=hoy + timedelta(days=30),
        )
        self.assertFalse(serializer.get_alerta_una_semana(lejana))
        self.assertEqual(serializer.get_semaforo(lejana), "AL_DIA")
        self.assertIn("Cuenta regresiva activa", serializer.get_mensaje_alerta(lejana))

    def test_serializador_vacuna_externa_y_lugar(self):
        hoy = timezone.localdate()
        tutor = Tutor(nombres="Rosa", apellidos="Lara", rut="12345678-5", telefono="+56912345678", email="r@test.cl")
        mascota = Mascota(id=2, nombre="Toby", especie=Mascota.Especie.CANINO, tutor=tutor)
        externa = ControlVacuna(
            mascota=mascota,
            tipo=ControlVacuna.Tipo.VACUNA,
            nombre_producto="Vacuna Sextuple Externa",
            fecha_aplicacion=hoy - timedelta(days=10),
            fecha_proximo_vencimiento=hoy + timedelta(days=355),
            es_externa=True,
            lugar_aplicacion="Clínica Veterinaria Sur",
        )
        data = ControlVacunaSerializer(externa).data
        self.assertTrue(data["es_externa"])
        self.assertEqual(data["lugar_aplicacion"], "Clínica Veterinaria Sur")
        self.assertIsNone(data["aplicado_por_nombre"])

        recep = Usuario(id=99, username="recep_vac", rol=Usuario.Rol.RECEP)
        req = RequestFactory().post("/api/controles-vacunas/")
        req.user = recep
        ser = ControlVacunaSerializer(context={"request": req})
        validado = ser.validate(
            {
                "es_externa": True,
                "lugar_aplicacion": "Municipalidad",
                "fecha_aplicacion": hoy - timedelta(days=2),
                "fecha_proximo_vencimiento": hoy + timedelta(days=363),
            }
        )
        self.assertIsNone(validado["aplicado_por"])

        # Mientras que una vacuna interna aplicada sigue exigiendo VET o ADMIN
        with self.assertRaises(DRFValidationError):
            ser.validate(
                {
                    "es_externa": False,
                    "fecha_aplicacion": hoy,
                    "fecha_proximo_vencimiento": hoy + timedelta(days=365),
                }
            )


class StockYVencimientosTests(SimpleTestCase):
    def test_estado_vencimiento_stock_y_serializador(self):
        hoy = timezone.localdate()
        vacuna_critica = ProductoServicio(
            codigo_barras="780999000001",
            sku="VAC-TEST-1",
            nombre="Vacuna Óctuple Prueba",
            categoria=ProductoServicio.Categoria.VACUNA,
            precio=15000,
            stock=3,
            stock_minimo=5,
            lote="LOT-TEST-01",
            fecha_vencimiento=hoy + timedelta(days=5),
            es_servicio=True,
        )
        self.assertEqual(vacuna_critica.calcular_dias_vencimiento_lote(hoy=hoy), 5)
        self.assertEqual(vacuna_critica.calcular_estado_vencimiento_lote(hoy=hoy), "CRITICO")
        self.assertEqual(vacuna_critica.calcular_estado_stock(), "BAJO")

        ser = ProductoServicioSerializer()
        self.assertEqual(ser.get_estado_vencimiento(vacuna_critica), "CRITICO")
        self.assertEqual(ser.get_estado_stock(vacuna_critica), "BAJO")
        self.assertTrue(ser.get_tiene_alerta(vacuna_critica))

        consulta = ProductoServicio(
            codigo_barras="780999000002",
            sku="SRV-TEST-2",
            nombre="Consulta General",
            categoria=ProductoServicio.Categoria.CONSULTA,
            precio=20000,
            stock=999,
            stock_minimo=5,
            es_servicio=True,
        )
        self.assertEqual(ser.get_estado_vencimiento(consulta), "SIN_VENCIMIENTO")
        self.assertEqual(ser.get_estado_stock(consulta), "SERVICIO")
        self.assertFalse(ser.get_tiene_alerta(consulta))

    def test_context_processor_anonimo_sin_consulta_bd(self):
        req = RequestFactory().get("/")
        req.user = SimpleNamespace(is_authenticated=False)
        self.assertEqual(sidebar_alertas(req), {})


class PermisosRBACTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.admin = Usuario(
            id=1, username="admin", rol=Usuario.Rol.ADMIN, is_active=True, is_superuser=True
        )
        self.vet = Usuario(
            id=2, username="dr.munoz", rol=Usuario.Rol.VET, is_active=True, is_superuser=False
        )
        self.otro_vet = Usuario(
            id=3, username="dr.suazo", rol=Usuario.Rol.VET, is_active=True, is_superuser=False
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


class MascotaFichaDetalladaTests(SimpleTestCase):
    def test_serializador_mascota_ficha_detallada_y_multipart(self):
        tutor = Tutor(
            id=10,
            nombres="Camila",
            apellidos="Rodríguez",
            rut="12345678-5",
            telefono="+56912345678",
            email="camila@test.cl",
        )
        mascota = Mascota(
            id=5,
            tutor=tutor,
            nombre="Max",
            especie=Mascota.Especie.CANINO,
            raza="Golden Retriever",
            sexo=Mascota.Sexo.MACHO,
            color="Dorado",
            condicion_corporal=3,
            cicatrices=False,
            cirugias_esterilizacion=True,
            datos_medioambientales="Casa con patio cerrado",
            nutricion="Pellet adulto 2 veces al día",
            entorno="Convive con 1 gato adulto",
            numero_chip="982000123456789",
            alergias="Ninguna",
            observaciones="Paciente tranquilo",
        )
        data = MascotaSerializer(mascota).data
        self.assertEqual(data["tutor_email"], "camila@test.cl")
        self.assertEqual(data["color"], "Dorado")
        self.assertEqual(data["condicion_corporal"], 3)
        self.assertFalse(data["cicatrices"])
        self.assertTrue(data["cirugias_esterilizacion"])
        self.assertEqual(data["numero_chip"], "982000123456789")
        self.assertEqual(data["nutricion"], "Pellet adulto 2 veces al día")
        self.assertEqual(data["entorno"], "Convive con 1 gato adulto")
        self.assertEqual(data["datos_medioambientales"], "Casa con patio cerrado")

        qd = QueryDict(mutable=True)
        qd.update(
            {
                "nombre": "Max",
                "especie": "CANINO",
                "sexo": "MACHO",
                "fecha_nacimiento": "",
                "peso": "",
                "condicion_corporal": "",
            }
        )
        ser = MascotaSerializer(instance=mascota, data=qd, partial=True)
        # Normaliza cadenas vacías de FormData sin lanzar error de formato en fecha/peso/condición corporal
        ser.fields["tutor"].required = False
        interna = ser.to_internal_value(qd)
        self.assertIsNone(interna["fecha_nacimiento"])
        self.assertIsNone(interna["peso"])
        self.assertIsNone(interna["condicion_corporal"])

        # Simula alta multipart/form-data (con foto y sin "activo"): debe quedar activo=True
        qd_alta = QueryDict(mutable=True)
        qd_alta.update({"nombre": "Myke", "especie": "CANINO", "sexo": "MACHO"})
        ser_alta = MascotaSerializer(data=qd_alta)
        ser_alta.fields["tutor"].required = False
        interna_alta = ser_alta.to_internal_value(qd_alta)
        self.assertTrue(interna_alta["activo"])

    def test_condicion_corporal_rango_valido(self):
        mascota = Mascota(nombre="Luna", especie=Mascota.Especie.FELINO, sexo=Mascota.Sexo.HEMBRA, condicion_corporal=6)
        with self.assertRaises(ValidationError) as ctx:
            mascota.full_clean(exclude=["tutor"])
        self.assertIn("condicion_corporal", ctx.exception.message_dict)
