import asyncio
import re
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.bom.db_service import BomDBService
from core.bom.router import router, _parse_bulk_valor
from core.bom.service import get_bom_service
from core.database import get_db_connection
from core.security import get_current_user_context


LOCK_STATE_RE = re.compile(
    r'<input[^>]+id="bom-lock-version-state"[^>]+>',
    re.IGNORECASE,
)
LOCK_VALUE_RE = re.compile(r'value="(?P<lock>\d+)"')


class FakeConn:
    pass


class FakeMutationService:
    def __init__(self, bom_id, project_id):
        self.bom_id = bom_id
        self.project_id = project_id
        self.lock_version = 0
        self.received_locks = []

    async def get_bom(self, conn, bom_id):
        if bom_id != self.bom_id:
            raise ValueError("BOM no encontrado")
        return {
            "id_bom": self.bom_id,
            "id_proyecto": self.project_id,
            "id_paquete": uuid4(),
            "estatus": "BORRADOR",
            "version": 1,
            "lock_version": self.lock_version,
            "es_cabeza_trabajo": True,
            "estado_paquete": "ACTIVO",
        }

    async def agregar_item(
        self, conn, id_bom, user_id, *, lock_version_esperado=None, **campos
    ):
        self.received_locks.append(lock_version_esperado)
        if id_bom != self.bom_id or lock_version_esperado != self.lock_version:
            raise ValueError(
                "El BOM cambio desde que abriste el formulario; recarga el paquete"
            )
        self.lock_version += 1
        return {
            "item": {
                "id_item": uuid4(),
                "id_bom": id_bom,
                "descripcion": campos["descripcion"],
                "precio_unitario": campos.get("precio_unitario"),
            },
            "capacidades": {"editar_base": True, "editar_ejecucion": False},
        }

    async def get_items(self, conn, id_bom):
        return []

    async def get_estadisticas(self, conn, id_bom, items=None):
        return {}

    @staticmethod
    def item_sin_costo(item):
        return False

    @staticmethod
    def mensaje_item_agregado(item):
        return "Item agregado correctamente"

    async def get_capacidades_bom(self, *args, **kwargs):
        return {"editar_base": True, "editar_ejecucion": False}

    async def puede_crear_o_retomar_bom(self, *args, **kwargs):
        return True


class FakePackageDB:
    async def get_responsable_proyecto_o_global(
        self, conn, id_proyecto, rol_proyecto
    ):
        return None


class FakePackageService:
    def __init__(self, package_id, project_id, user_id):
        self.package_id = package_id
        self.project_id = project_id
        self.user_id = user_id
        self.db = FakePackageDB()

    async def get_paquete(self, conn, package_id):
        assert package_id == self.package_id
        return {
            "id_paquete": package_id,
            "id_proyecto": self.project_id,
            "codigo": "PKG-001",
            "nombre": "Paquete principal",
            "tipo_alcance": "COMPLETO",
            "descripcion_alcance": None,
        }

    async def get_bom_cabeza_trabajo(self, conn, package_id):
        return None

    async def get_proyecto_info(self, conn, project_id):
        assert project_id == self.project_id
        return {
            "id_proyecto": project_id,
            "proyecto_id_estandar": "MX-50001-FV",
            "nombre_proyecto": "Proyecto HTMX",
        }

    async def get_ingeniero_asignado(self, conn, project_id):
        return {"id_usuario": self.user_id}

    async def puede_crear_o_retomar_bom(self, *args, **kwargs):
        return True

    async def puede_administrar_paquete(self, *args, **kwargs):
        return True

    async def get_catalogos(self, conn):
        return {}

    async def get_titulares_que_representa(self, conn, user_id):
        return {user_id}


def _build_client(service, context):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user_context] = lambda: context
    app.dependency_overrides[get_db_connection] = lambda: FakeConn()
    app.dependency_overrides[get_bom_service] = lambda: service
    return TestClient(app)


def _lock_oob(response):
    tag_match = LOCK_STATE_RE.search(response.text)
    assert tag_match, "La respuesta HTMX debe transportar el lock OOB"
    tag = tag_match.group(0)
    assert 'hx-swap-oob="true"' in tag
    value_match = LOCK_VALUE_RE.search(tag)
    assert value_match
    return int(value_match.group("lock"))


def test_dos_mutaciones_consecutivas_consumen_lock_oob_actualizado():
    bom_id = uuid4()
    project_id = uuid4()
    user_id = uuid4()
    service = FakeMutationService(bom_id, project_id)
    client = _build_client(
        service,
        {
            "email": "ingenieria@example.com",
            "user_db_id": user_id,
            "user_name": "Ingenieria",
            "role": "USER",
            "rol_organizacional": None,
            "module_roles": {"ingenieria": "editor"},
        },
    )

    form = {
        "descripcion": "Item uno",
        "cantidad": "1",
        "precio_unitario": "10",
        "grupo_ids": "1",
        "lock_version": "0",
    }
    first = client.post(
        f"/bom/{bom_id}/items", data=form, headers={"HX-Request": "true"}
    )

    assert first.status_code == 200
    first_lock = _lock_oob(first)
    assert first_lock == 1

    form.update({"descripcion": "Item dos", "lock_version": str(first_lock)})
    second = client.post(
        f"/bom/{bom_id}/items", data=form, headers={"HX-Request": "true"}
    )

    assert second.status_code == 200
    assert _lock_oob(second) == 2
    assert service.received_locks == [0, 1]


def test_history_restore_de_paquete_retorna_documento_completo():
    package_id = uuid4()
    project_id = uuid4()
    user_id = uuid4()
    service = FakePackageService(package_id, project_id, user_id)
    client = _build_client(
        service,
        {
            "email": "admin@example.com",
            "user_db_id": user_id,
            "user_name": "Administrador",
            "role": "ADMIN",
            "rol_organizacional": None,
            "module_roles": {},
        },
    )

    partial = client.get(
        f"/bom/paquetes/{package_id}/ui",
        headers={"HX-Request": "true"},
    )
    restored = client.get(
        f"/bom/paquetes/{package_id}/ui",
        headers={
            "HX-Request": "true",
            "HX-History-Restore-Request": "true",
        },
    )

    assert partial.status_code == 200
    assert '<div class="bom-page' in partial.text
    assert "<!DOCTYPE html>" not in partial.text
    assert restored.status_code == 200
    assert "<!DOCTYPE html>" in restored.text
    assert 'id="main-content"' in restored.text


def test_mutaciones_y_navegacion_no_seleccionan_bom_por_proyecto():
    paths = {route.path for route in router.routes}

    assert "/bom/paquetes/{id_paquete}/ui" in paths
    assert "/bom/{id_bom}/items" in paths
    assert "/bom/{id_bom}/items/bulk-edit" in paths
    assert "/bom/{id_bom}/refrescar-costos" in paths
    assert "/bom/{id_proyecto}/items" not in paths
    assert "/bom/{id_proyecto}/items/bulk-edit" not in paths
    assert "/bom/{id_proyecto}/refrescar-costos" not in paths

    hub_source = Path("templates/bom/partials/hub.html").read_text(
        encoding="utf-8"
    )
    canonical_link = "/bom/paquetes/{{ paquete.id_paquete }}/ui"
    assert f'href="{canonical_link}"' in hub_source
    assert f'hx-get="{canonical_link}"' in hub_source
    assert "/bom/{{ paquete.id_proyecto }}/ui" not in hub_source


def test_parse_bulk_valor_moneda_acepta_mxn_y_usd():
    assert _parse_bulk_valor("moneda", "MXN") == "MXN"
    assert _parse_bulk_valor("moneda", "usd") == "USD"


def test_parse_bulk_valor_moneda_rechaza_valor_invalido():
    with pytest.raises(ValueError):
        _parse_bulk_valor("moneda", "EUR")
    with pytest.raises(ValueError):
        _parse_bulk_valor("moneda", "")


# ─────────────────────────────────────────────────────────────────────────────
# CAS real con dos conexiones (core/bom/db_service.py::incrementar_lock_bom_cas)
#
# Las pruebas de arriba usan FakeMutationService/FakeConn a proposito: verifican el
# contrato HTTP/HTMX (headers, OOB, 404 vs 500), que es responsabilidad del router y no
# necesita Postgres real. Lo que SI necesita Postgres real es la garantia de carrera del
# CAS mismo -- que dos conexiones compitiendo por el mismo lock_version_esperado solo
# dejen ganar a una. Eso no se puede demostrar simulando el lock en memoria de Python.
# ─────────────────────────────────────────────────────────────────────────────


async def _bom_cabeza_trabajo_activo(conn):
    """Usa un BOM legacy real ya existente en DEV (cabeza de trabajo de un paquete
    ACTIVO) en vez de crear uno nuevo: tb_proyectos_gate exige id_oportunidad NOT NULL,
    que encadena a un fixture de oportunidad+cliente que no existe todavia en el repo."""
    row = await conn.fetchrow(
        """
        SELECT b.id_bom, b.lock_version, b.estatus
        FROM tb_bom b
        JOIN tb_bom_paquetes p ON p.id_paquete = b.id_paquete
        WHERE p.cabeza_trabajo_id = b.id_bom AND p.estado_paquete = 'ACTIVO'
        LIMIT 1
        """
    )
    if row is None:
        pytest.skip("No hay una cabeza de trabajo ACTIVA real en DEV para probar el CAS")
    return row


@pytest.mark.asyncio
async def test_cas_concurrente_solo_deja_ganar_a_una_conexion(two_real_conns):
    """Dos conexiones llaman incrementar_lock_bom_cas con el mismo lock_version_esperado
    al mismo tiempo: Postgres serializa las dos UPDATE por el FOR UPDATE OF p interno, y
    la que se ejecuta segunda ve el lock_version ya incrementado -- 0 filas, None. Ninguna
    debe quedar bloqueada indefinidamente (deadlock) ni las dos deben poder ganar.
    """
    conn_a, conn_b = two_real_conns
    fila = await _bom_cabeza_trabajo_activo(conn_a)
    id_bom = fila["id_bom"]
    lock_original = fila["lock_version"]
    estatus = fila["estatus"]

    db = BomDBService()
    try:
        resultado_a, resultado_b = await asyncio.gather(
            db.incrementar_lock_bom_cas(conn_a, id_bom, lock_original, estatus),
            db.incrementar_lock_bom_cas(conn_b, id_bom, lock_original, estatus),
        )

        ganadores = [r for r in (resultado_a, resultado_b) if r is not None]
        perdedores = [r for r in (resultado_a, resultado_b) if r is None]
        assert len(ganadores) == 1, "exactamente una conexion debe ganar la carrera del CAS"
        assert len(perdedores) == 1
        assert ganadores[0]["lock_version"] == lock_original + 1
    finally:
        await conn_a.execute(
            "UPDATE tb_bom SET lock_version = $1 WHERE id_bom = $2",
            lock_original, id_bom,
        )


@pytest.mark.asyncio
async def test_cas_rechaza_lock_version_obsoleto_tras_commit_ajeno(two_real_conns):
    """Si una conexion ya avanzo el lock_version y comiteo, un segundo formulario abierto
    con el lock_version viejo debe ser rechazado (None) en vez de pisar el cambio -- el
    escenario real de "dos pestanas editando el mismo BOM"."""
    conn_a, conn_b = two_real_conns
    fila = await _bom_cabeza_trabajo_activo(conn_a)
    id_bom = fila["id_bom"]
    lock_original = fila["lock_version"]
    estatus = fila["estatus"]

    db = BomDBService()
    try:
        primero = await db.incrementar_lock_bom_cas(conn_a, id_bom, lock_original, estatus)
        assert primero is not None
        assert primero["lock_version"] == lock_original + 1

        segundo = await db.incrementar_lock_bom_cas(conn_b, id_bom, lock_original, estatus)
        assert segundo is None, "el lock_version obsoleto debe ser rechazado, no aplicado"
    finally:
        await conn_a.execute(
            "UPDATE tb_bom SET lock_version = $1 WHERE id_bom = $2",
            lock_original, id_bom,
        )
