"""
Tests de la tabla cross-proyecto "Mis Autorizaciones" (paso Obra):
_Planes_Activos/2026-08-31-plan-tabla-autorizaciones-obra-cross-proyecto.md, seccion 3.

GET /bom/obra/autorizaciones y POST .../aprobar|rechazar son endpoints nuevos que
llaman los MISMOS metodos de servicio que las rutas por-BOM ya existentes
(aprobar_obra, rechazar_autorizacion -- logica de negocio y CAS sin cambios) pero
re-renderizan bom/partials/obra_autorizaciones.html (tabla completa) en vez de
autorizaciones.html (que depende de un #tab-autorizaciones inexistente aqui).

Gate: require_authenticated_session() para el modo "mis autorizaciones" (sin
id_proyecto) -- el filtro real vive en el WHERE de la query cross-BOM
(representados/rol_organizacional). Con id_proyecto (modo solo-lectura de un
proyecto especifico) se re-exige ademas BomService.tiene_acceso_indicador_pendientes_proyecto
en el router, el mismo gate que ya decide si el link "Ver todas" se muestra
(proyectos/router.py) -- sin acceso de modulo/Direccion, 403. Ya cubierto por
separado en test_bom_gates_coordinador_obra.py (gates) y
test_bom_popup_pendientes_obra.py (logica de listar_autorizaciones_obra_coordinador).
Este archivo cubre el cableado router-service-template de las 3 rutas nuevas.
"""
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.bom.router import router
from core.bom.service import BomService, get_bom_service
from core.database import get_db_connection
from core.security import get_current_user_context


class FakeDB:
    def __init__(self, autorizaciones=None, total=None):
        self.autorizaciones = autorizaciones or []
        self.total = total if total is not None else len(self.autorizaciones)
        self.limit_recibido = None
        self.offset_recibido = None
        self.id_proyecto_recibido = None

    async def get_titulares_que_representa(self, conn, user_id):
        return []

    async def get_autorizaciones_pendientes_por_coordinador(
        self, conn, representados, rol_organizacional, limit=20, offset=0, id_proyecto=None,
    ):
        self.limit_recibido = limit
        self.offset_recibido = offset
        self.id_proyecto_recibido = id_proyecto
        return self.autorizaciones

    async def contar_autorizaciones_pendientes_por_coordinador(
        self, conn, representados, rol_organizacional, id_proyecto=None,
    ):
        return self.total


def _autorizacion(**extra):
    data = {
        "id": uuid4(),
        "cotizacion_id": uuid4(),
        "bom_id": uuid4(),
        "id_paquete": uuid4(),
        "estatus": "PENDIENTE",
        "monto_total": 1000.0,
        "moneda": "MXN",
        "nombre_proveedor": "Proveedor Uno",
        "pdf_url": None,
        "paquete_codigo": "PAQ-1",
        "paquete_nombre": "Paquete de prueba",
        "bom_version": 1,
        "proyecto_nombre": "Proyecto Demo",
        "proyecto_id_estandar": "PRY-001",
        "creado_en": None,
        "lock_version": 0,
    }
    data.update(extra)
    return data


def _context(user_id=None):
    return {
        "email": "coordinador@example.com",
        "user_db_id": user_id or uuid4(),
        "user_name": "Coordinador",
        "role": "USER",
        "rol_organizacional": None,
        "module_roles": {},
    }


def _context_visitante(user_id=None):
    """Direccion u otro rol con tiene_acceso_indicador_pendientes_proyecto --
    unico contexto valido para consultar el modo solo-lectura (id_proyecto)."""
    return {**_context(user_id), "rol_organizacional": "director"}


def _build_client(service, context):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user_context] = lambda: context
    app.dependency_overrides[get_db_connection] = lambda: object()
    app.dependency_overrides[get_bom_service] = lambda: service
    return TestClient(app)


async def _fake_aprobar_obra_ok(conn, autorizacion_id, uid, nota, user_role, lock_version, rol_organizacional=None):
    return {"bom_id": uuid4()}


def test_ui_renderiza_tabla_con_pendientes_y_total():
    service = BomService()
    service.db = FakeDB(autorizaciones=[_autorizacion()], total=1)
    client = _build_client(service, _context())

    response = client.get("/bom/obra/autorizaciones")

    assert response.status_code == 200
    assert "PAQ-1" in response.text
    assert "Proveedor Uno" in response.text


def test_ui_vacio_muestra_estado_sin_pendientes():
    service = BomService()
    service.db = FakeDB(autorizaciones=[], total=0)
    client = _build_client(service, _context())

    response = client.get("/bom/obra/autorizaciones")

    assert response.status_code == 200
    assert "Sin autorizaciones pendientes" in response.text


def test_ui_propaga_limit_offset_a_la_query():
    service = BomService()
    service.db = FakeDB(autorizaciones=[], total=0)
    client = _build_client(service, _context())

    client.get("/bom/obra/autorizaciones?limit=5&offset=10")

    assert service.db.limit_recibido == 5
    assert service.db.offset_recibido == 10


def test_ui_propaga_id_proyecto_a_la_query():
    """`id_proyecto` (entrada desde el indicador de pendientes de un proyecto
    especifico) debe llegar intacto a la query -- desactiva el filtro por
    representados dentro del servicio/SQL (ver db_compras.py)."""
    service = BomService()
    service.db = FakeDB(autorizaciones=[], total=0)
    client = _build_client(service, _context_visitante())
    id_proyecto = uuid4()

    client.get(f"/bom/obra/autorizaciones?id_proyecto={id_proyecto}")

    assert service.db.id_proyecto_recibido == id_proyecto


def test_ui_modo_solo_lectura_muestra_coordinador_en_vez_de_botones():
    """Con id_proyecto y una fila donde el usuario no puede actuar
    (coordinador_obra distinto y no jefe_construccion), la tabla debe mostrar el
    nombre del coordinador en vez de Aprobar/Rechazar."""
    service = BomService()
    service.db = FakeDB(autorizaciones=[
        _autorizacion(coordinador_obra=uuid4(), coordinador_nombre="Juan Perez"),
    ], total=1)
    client = _build_client(service, _context_visitante())

    response = client.get(f"/bom/obra/autorizaciones?id_proyecto={uuid4()}")

    assert response.status_code == 200
    assert "Coordinador:" in response.text
    assert "Juan Perez" in response.text
    assert 'name="lock_version"' not in response.text


def test_ui_id_proyecto_sin_acceso_de_indicador_devuelve_403():
    """Un autenticado sin acceso de modulo/Direccion (ej. RH) que navega
    directo a la URL con un id_proyecto ajeno no debe ver proveedor/monto/
    moneda de ese proyecto -- ver core/bom/compras_router.py::obra_autorizaciones_ui."""
    service = BomService()
    service.db = FakeDB(autorizaciones=[_autorizacion()], total=1)
    client = _build_client(service, _context())

    response = client.get(f"/bom/obra/autorizaciones?id_proyecto={uuid4()}")

    assert response.status_code == 403


def test_aprobar_re_renderiza_tabla_completa_no_autorizaciones_tab():
    service = BomService()
    service.db = FakeDB(autorizaciones=[_autorizacion()], total=1)
    service.aprobar_obra = _fake_aprobar_obra_ok
    client = _build_client(service, _context())

    response = client.post(
        f"/bom/obra/autorizaciones/{uuid4()}/aprobar",
        data={"lock_version": "0", "limit": "20", "offset": "0"},
    )

    assert response.status_code == 200
    assert 'id="obra-autorizaciones-content"' in response.text


def test_aprobar_preserva_paginacion_vigente():
    service = BomService()
    service.db = FakeDB(autorizaciones=[], total=0)
    service.aprobar_obra = _fake_aprobar_obra_ok
    client = _build_client(service, _context())

    client.post(
        f"/bom/obra/autorizaciones/{uuid4()}/aprobar",
        data={"lock_version": "0", "limit": "5", "offset": "10"},
    )

    assert service.db.limit_recibido == 5
    assert service.db.offset_recibido == 10


def test_aprobar_error_de_negocio_devuelve_toast_sin_tumbar_la_tabla():
    service = BomService()
    service.db = FakeDB(autorizaciones=[], total=0)

    async def _fake_aprobar_obra(conn, autorizacion_id, uid, nota, user_role, lock_version, rol_organizacional=None):
        raise ValueError("No eres el coordinador de obra de este BOM.")

    service.aprobar_obra = _fake_aprobar_obra
    client = _build_client(service, _context())

    response = client.post(
        f"/bom/obra/autorizaciones/{uuid4()}/aprobar",
        data={"lock_version": "0"},
    )

    assert response.status_code == 400
    assert "No eres el coordinador de obra" in response.text


def test_rechazar_re_renderiza_tabla_completa():
    service = BomService()
    service.db = FakeDB(autorizaciones=[], total=0)

    async def _fake_rechazar(conn, autorizacion_id, uid, motivo, user_role, rol_org, finanzas_role, lock_version):
        return {"bom_id": uuid4()}

    service.rechazar_autorizacion = _fake_rechazar
    client = _build_client(service, _context())

    response = client.post(
        f"/bom/obra/autorizaciones/{uuid4()}/rechazar",
        data={"motivo": "Precio fuera de mercado", "lock_version": "0"},
    )

    assert response.status_code == 200
    assert 'id="obra-autorizaciones-content"' in response.text


def test_rechazar_error_de_negocio_devuelve_toast():
    service = BomService()
    service.db = FakeDB(autorizaciones=[], total=0)

    async def _fake_rechazar(conn, autorizacion_id, uid, motivo, user_role, rol_org, finanzas_role, lock_version):
        raise ValueError("lock_version desactualizado.")

    service.rechazar_autorizacion = _fake_rechazar
    client = _build_client(service, _context())

    response = client.post(
        f"/bom/obra/autorizaciones/{uuid4()}/rechazar",
        data={"motivo": "x", "lock_version": "0"},
    )

    assert response.status_code == 400
    assert "lock_version desactualizado" in response.text
