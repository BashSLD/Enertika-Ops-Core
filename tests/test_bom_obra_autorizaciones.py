"""
Tests de la tabla cross-proyecto "Mis Autorizaciones" (paso Obra):
_Planes_Activos/2026-08-31-plan-tabla-autorizaciones-obra-cross-proyecto.md, seccion 3.

GET /bom/obra/autorizaciones y POST .../aprobar|rechazar son endpoints nuevos que
llaman los MISMOS metodos de servicio que las rutas por-BOM ya existentes
(aprobar_obra, rechazar_autorizacion -- logica de negocio y CAS sin cambios) pero
re-renderizan bom/partials/obra_autorizaciones.html (tabla completa) en vez de
autorizaciones.html (que depende de un #tab-autorizaciones inexistente aqui).

Gate: solo require_authenticated_session() -- el filtro real vive en el WHERE de
la query cross-BOM (representados/rol_organizacional), no en el gate de ruta. Ya
cubierto por separado en test_bom_gates_coordinador_obra.py (gates) y
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

    async def get_titulares_que_representa(self, conn, user_id):
        return []

    async def get_autorizaciones_pendientes_por_coordinador(
        self, conn, representados, rol_organizacional, limit=20, offset=0,
    ):
        self.limit_recibido = limit
        self.offset_recibido = offset
        return self.autorizaciones

    async def contar_autorizaciones_pendientes_por_coordinador(self, conn, representados, rol_organizacional):
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
