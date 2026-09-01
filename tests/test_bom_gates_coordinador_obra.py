"""
Tests de los 5 gates de Compras/BOM corregidos para agregar el OR de coordinador
de obra (_Planes_Activos/2026-08-31-plan-tabla-autorizaciones-obra-cross-proyecto.md,
seccion 5): antes de este fix, un coordinador de obra sin ningun modulo asignado
(rol de equipo de proyecto, independiente de tb_permisos_modulos) recibia 403 al
intentar ver o accionar sobre su propio BOM, porque el gate declarativo
(Depends(require_any_module_access(...))) no conocia ese rol -- solo el chequeo
imperativo (BomService.tiene_acceso_paquete_compras) lo resuelve.

Cada test usa un usuario "coordinador puro": module_roles={} y rol_organizacional
distinto de jefe_construccion/director, coordinador_obra del BOM apuntando a su
user_id -- exactamente el caso que el bug bloqueaba. `paquete_ui` (gate 5) no se
verifica con un 200 real: el dashboard completo (catalogos, capacidades, items,
estadisticas...) es una superficie enorme ajena a este fix. En su lugar se prueba
que la ejecucion pasa el gate y llega al siguiente chequeo real del handler
("Proyecto no encontrado", 404) en vez de quedarse en el 403 que el bug causaba.
"""
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.bom.router import router
from core.bom.service import BomService, get_bom_service
from core.database import get_db_connection
from core.security import get_current_user_context


def _coordinador_context(user_id):
    return {
        "email": "coordinador@example.com",
        "user_db_id": user_id,
        "user_name": "Coordinador",
        "role": "USER",
        "rol_organizacional": None,
        "module_roles": {},
    }


def _extrano_context():
    """Usuario autenticado sin ningun modulo ni relacion con el BOM -- control
    negativo: debe seguir bloqueado tras el fix."""
    return _coordinador_context(uuid4())


def _bom(coordinador_obra, **extra):
    data = {
        "id_bom": uuid4(),
        "estatus": "EN_REVISION_CONST",
        "coordinador_obra": coordinador_obra,
    }
    data.update(extra)
    return data


def _build_client(service, context):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user_context] = lambda: context
    app.dependency_overrides[get_db_connection] = lambda: object()
    app.dependency_overrides[get_bom_service] = lambda: service
    return TestClient(app)


class FakeDB:
    """Stub minimo compartido por los 5 gates: cada metodo devuelve lo justo
    para que el handler llegue al render/respuesta sin depender de datos reales."""

    def __init__(self, bom=None, paquete=None, autorizacion=None):
        self.bom = bom
        self.paquete = paquete
        self.autorizacion = autorizacion

    async def get_bom_by_id(self, conn, id_bom):
        return self.bom if self.bom and self.bom["id_bom"] == id_bom else None

    async def get_titulares_que_representa(self, conn, user_id):
        return []

    async def get_aprobador_final_id(self, conn):
        return None

    async def get_autorizaciones_by_bom(self, conn, id_bom):
        return []

    async def get_cotizaciones_by_bom(self, conn, id_bom):
        return []

    async def get_items_by_bom(self, conn, id_bom):
        return []

    async def get_rfqs_by_bom(self, conn, id_bom):
        return []

    async def get_autorizacion_by_id(self, conn, autorizacion_id):
        return self.autorizacion

    async def get_paquete_by_id(self, conn, id_paquete):
        return self.paquete if self.paquete and self.paquete["id"] == id_paquete else None

    async def get_bom_cabeza_trabajo(self, conn, id_paquete):
        return self.bom

    async def get_proyecto_info(self, conn, id_proyecto):
        return None  # marca que la ejecucion paso el gate -- ver docstring del modulo


# ─── Gate 1: GET /{id_bom}/autorizaciones ────────────────────────────────

def test_tab_autorizaciones_permite_coordinador_sin_modulo():
    user_id = uuid4()
    bom = _bom(user_id)
    service = BomService()
    service.db = FakeDB(bom=bom)
    client = _build_client(service, _coordinador_context(user_id))

    response = client.get(f"/bom/{bom['id_bom']}/autorizaciones")

    assert response.status_code == 200


def test_tab_autorizaciones_sigue_bloqueando_a_un_extrano():
    bom = _bom(uuid4())
    service = BomService()
    service.db = FakeDB(bom=bom)
    client = _build_client(service, _extrano_context())

    response = client.get(f"/bom/{bom['id_bom']}/autorizaciones")

    assert response.status_code == 403


# ─── Gate 2: GET /{id_bom}/cotizaciones ──────────────────────────────────

def test_tab_cotizaciones_permite_coordinador_sin_modulo():
    user_id = uuid4()
    bom = _bom(user_id)
    service = BomService()
    service.db = FakeDB(bom=bom)
    client = _build_client(service, _coordinador_context(user_id))

    response = client.get(f"/bom/{bom['id_bom']}/cotizaciones")

    assert response.status_code == 200


# ─── Gate 3: POST /autorizaciones/{id}/aprobar-obra ──────────────────────

def test_aprobar_obra_permite_coordinador_sin_modulo():
    user_id = uuid4()
    bom = _bom(user_id)
    autorizacion = {"bom_id": bom["id_bom"]}
    service = BomService()
    service.db = FakeDB(bom=bom, autorizacion=autorizacion)

    async def _fake_aprobar_obra(conn, autorizacion_id, uid, nota, user_role, lock_version, rol_organizacional=None):
        return {"bom_id": bom["id_bom"]}

    service.aprobar_obra = _fake_aprobar_obra
    client = _build_client(service, _coordinador_context(user_id))

    response = client.post(
        f"/bom/autorizaciones/{uuid4()}/aprobar-obra",
        data={"lock_version": "0"},
    )

    assert response.status_code == 200


# ─── Gate 4: POST /autorizaciones/{id}/rechazar (compartido 3 pasos) ─────

def test_rechazar_permite_coordinador_sin_modulo():
    user_id = uuid4()
    bom = _bom(user_id)
    autorizacion = {"bom_id": bom["id_bom"]}
    service = BomService()
    service.db = FakeDB(bom=bom, autorizacion=autorizacion)

    async def _fake_rechazar(conn, autorizacion_id, uid, motivo, user_role, rol_org, finanzas_role, lock_version):
        return {"bom_id": bom["id_bom"]}

    service.rechazar_autorizacion = _fake_rechazar
    client = _build_client(service, _coordinador_context(user_id))

    response = client.post(
        f"/bom/autorizaciones/{uuid4()}/rechazar",
        data={"motivo": "Precio fuera de mercado", "lock_version": "0"},
    )

    assert response.status_code == 200


# ─── Gate 5: GET /paquetes/{id_paquete}/ui ───────────────────────────────

def test_paquete_ui_permite_coordinador_sin_modulo():
    user_id = uuid4()
    id_paquete = uuid4()
    paquete = {"id": id_paquete, "id_proyecto": uuid4()}
    bom = _bom(user_id, id_bom=uuid4())
    service = BomService()
    service.db = FakeDB(bom=bom, paquete=paquete)
    client = _build_client(service, _coordinador_context(user_id))

    response = client.get(f"/bom/paquetes/{id_paquete}/ui")

    # Ver docstring del modulo: no se renderiza el dashboard completo, solo se
    # confirma que la ejecucion paso el gate (antes del fix, este mismo caso
    # devolvia 403 sin llegar aqui).
    assert response.status_code == 404
    assert "Proyecto no encontrado" in response.text


def test_paquete_ui_sigue_bloqueando_a_un_extrano():
    id_paquete = uuid4()
    paquete = {"id": id_paquete, "id_proyecto": uuid4()}
    bom = _bom(uuid4(), id_bom=uuid4())
    service = BomService()
    service.db = FakeDB(bom=bom, paquete=paquete)
    client = _build_client(service, _extrano_context())

    response = client.get(f"/bom/paquetes/{id_paquete}/ui")

    assert response.status_code == 200
    assert "coordinador de obra" in response.text
