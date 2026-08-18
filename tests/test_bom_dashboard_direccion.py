"""
Test del dashboard de Direccion (Fase 3 del plan
_Planes_Activos/2026-06-29-aprobaciones-cotizaciones-post-bom.md, seccion ## 16): el service delega
los filtros de estatus/proyecto/proveedor tal cual al metodo de BD, sin logica adicional (la fuente
de verdad de la query vive en core/bom/db_compras.py, ya cubierta por /auditar-sql diff).
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
    def __init__(self):
        self.calls = []

    async def get_cotizacion_aprobaciones_direccion(self, conn, estatus=None, id_proyecto=None,
                                                      nombre_proveedor=None):
        self.calls.append({
            "estatus": estatus, "id_proyecto": id_proyecto, "nombre_proveedor": nombre_proveedor,
        })
        return [{"aprobacion_id": uuid4(), "aprobacion_estatus": estatus or "PENDIENTE_DIRECCION"}]

    async def get_aprobador_final_id(self, conn):
        return None


@pytest.mark.asyncio
async def test_delega_filtros_tal_cual_al_db_service():
    svc = BomService()
    svc.db = FakeDB()

    resultado = await svc.get_cotizacion_aprobaciones_direccion(
        object(), estatus="APROBADA", id_proyecto=uuid4(), nombre_proveedor="Acme",
    )

    assert len(resultado) == 1
    assert svc.db.calls[0]["estatus"] == "APROBADA"
    assert svc.db.calls[0]["nombre_proveedor"] == "Acme"


@pytest.mark.asyncio
async def test_estatus_vacio_no_filtra():
    svc = BomService()
    svc.db = FakeDB()

    await svc.get_cotizacion_aprobaciones_direccion(object())

    assert svc.db.calls[0] == {"estatus": None, "id_proyecto": None, "nombre_proveedor": None}


def _build_client(service, context):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user_context] = lambda: context
    app.dependency_overrides[get_db_connection] = lambda: object()
    app.dependency_overrides[get_bom_service] = lambda: service
    return TestClient(app)


def _director_service():
    """BomService real con FakeDB y aprobar/rechazar_cotizacion_direccion mockeados:
    a esta prueba solo le importa que el router reenvie los filtros del dashboard, no
    la logica de negocio de aprobar/rechazar (ya cubierta en otros tests)."""
    svc = BomService()
    svc.db = FakeDB()

    async def _fake_aprobar(conn, cotizacion_id, user_id, user_role, rol_org, comentarios,
                             aprobacion_lock_version, autorizacion_lock_version):
        return {"id": cotizacion_id}

    async def _fake_rechazar(conn, cotizacion_id, user_id, motivo, user_role, rol_org,
                              aprobacion_lock_version, autorizacion_lock_version):
        return {"id": cotizacion_id}

    svc.aprobar_cotizacion_direccion = _fake_aprobar
    svc.rechazar_cotizacion_direccion = _fake_rechazar
    return svc


def _director_context():
    return {
        "email": "director@example.com",
        "user_db_id": uuid4(),
        "user_name": "Director",
        "role": "ADMIN",
        "rol_organizacional": "director",
        "module_roles": {},
    }


def test_aprobar_cotizacion_conserva_los_filtros_del_dashboard():
    """Bug encontrado por code-review: aprobar/rechazar desde el dashboard resetaba
    el filtro a PENDIENTE_DIRECCION/todos-los-proyectos/sin-proveedor, perdiendo lo
    que el usuario tenia aplicado. El form ahora reenvia estatus/id_proyecto/proveedor
    como hidden inputs y el router los usa para reconstruir la tabla."""
    service = _director_service()
    client = _build_client(service, _director_context())
    cotizacion_id = uuid4()
    proyecto_id = uuid4()

    response = client.post(
        f"/bom/direccion/cotizaciones/{cotizacion_id}/aprobar",
        data={
            "aprobacion_lock_version": "0",
            "autorizacion_lock_version": "0",
            "estatus": "",
            "id_proyecto": str(proyecto_id),
            "proveedor": "ACME",
        },
    )

    assert response.status_code == 200
    ultima = service.db.calls[-1]
    assert ultima["estatus"] is None  # "" se normaliza a None (sin filtro de estatus)
    assert ultima["id_proyecto"] == proyecto_id
    assert ultima["nombre_proveedor"] == "ACME"


def test_aprobar_cotizacion_conserva_filtro_pendientes_explicito():
    service = _director_service()
    client = _build_client(service, _director_context())
    cotizacion_id = uuid4()

    response = client.post(
        f"/bom/direccion/cotizaciones/{cotizacion_id}/aprobar",
        data={
            "aprobacion_lock_version": "0",
            "autorizacion_lock_version": "0",
            "estatus": "PENDIENTE_DIRECCION",
            "id_proyecto": "",
            "proveedor": "",
        },
    )

    assert response.status_code == 200
    ultima = service.db.calls[-1]
    assert ultima["estatus"] == "PENDIENTE_DIRECCION"
    assert ultima["id_proyecto"] is None
    assert ultima["nombre_proveedor"] is None


def test_rechazar_cotizacion_conserva_los_filtros_del_dashboard():
    service = _director_service()
    client = _build_client(service, _director_context())
    cotizacion_id = uuid4()
    proyecto_id = uuid4()

    response = client.post(
        f"/bom/direccion/cotizaciones/{cotizacion_id}/rechazar",
        data={
            "motivo": "Precio fuera de mercado",
            "aprobacion_lock_version": "0",
            "autorizacion_lock_version": "0",
            "estatus": "RECHAZADA",
            "id_proyecto": str(proyecto_id),
            "proveedor": "ACME",
        },
    )

    assert response.status_code == 200
    ultima = service.db.calls[-1]
    assert ultima["estatus"] == "RECHAZADA"
    assert ultima["id_proyecto"] == proyecto_id
    assert ultima["nombre_proveedor"] == "ACME"


def test_aprobar_cotizacion_sin_filtros_no_filtra():
    """Si el cliente no manda los campos de filtro (ej. llamada directa a la API sin
    pasar por el form), no se aplica ningun filtro (equivalente a "Todas"): FastAPI
    normaliza estatus="" y estatus ausente al mismo valor (None), asi que ambos casos
    deben comportarse igual que elegir "Todas" en el dashboard."""
    service = _director_service()
    client = _build_client(service, _director_context())
    cotizacion_id = uuid4()

    response = client.post(
        f"/bom/direccion/cotizaciones/{cotizacion_id}/aprobar",
        data={"aprobacion_lock_version": "0", "autorizacion_lock_version": "0"},
    )

    assert response.status_code == 200
    ultima = service.db.calls[-1]
    assert ultima["estatus"] is None
    assert ultima["id_proyecto"] is None
    assert ultima["nombre_proveedor"] is None
