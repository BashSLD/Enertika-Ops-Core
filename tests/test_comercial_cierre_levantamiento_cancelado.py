"""
Tests de la subpestaña "Cancelados" (tab=levantamientos) y su acción de cierre
manual en Comercial (_Planes_Activos/2026-07-23-propagacion-estatus-levantamientos-PLAN.md,
Paso 7).
"""

from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from modules.comercial import service as comercial_service_module
from modules.comercial.service import ComercialService

pytestmark = pytest.mark.asyncio


# ───────────────────────── filtro subtab=cancelados (BD real) ─────────────────────────


async def _crear_usuario(conn) -> UUID:
    return await conn.fetchval(
        """
        INSERT INTO tb_usuarios (email, nombre, rol_sistema, is_active)
        VALUES ($1, $2, 'USER', true)
        RETURNING id_usuario
        """,
        f"test-{uuid4().hex}@test.local",
        f"Test {uuid4().hex[:8]}",
    )


async def _crear_oportunidad_levantamiento(conn, *, creado_por_id: UUID) -> UUID:
    id_estatus = await conn.fetchval("SELECT id FROM tb_cat_estatus_oportunidades WHERE nombre = 'Pendiente'")
    id_tipo = await conn.fetchval("SELECT id FROM tb_cat_tipos_solicitud WHERE codigo_interno = 'LEVANTAMIENTO'")
    return await conn.fetchval(
        """
        INSERT INTO tb_oportunidades (
            id_oportunidad, op_id_estandar, cliente_nombre, creado_por_id,
            fecha_creacion, id_estatus_global, email_enviado, id_tipo_solicitud
        ) VALUES (gen_random_uuid(), $1, 'CLIENTE TEST', $2, now(), $3, true, $4)
        RETURNING id_oportunidad
        """,
        f"OP - TEST{uuid4().hex[:10]}",
        creado_por_id,
        id_estatus,
        id_tipo,
    )


async def _crear_sitio(conn, id_oportunidad: UUID) -> UUID:
    return await conn.fetchval(
        """
        INSERT INTO tb_sitios_oportunidad (id_sitio, id_oportunidad, direccion, nombre_sitio)
        VALUES (gen_random_uuid(), $1, 'Direccion Test', 'Sitio Test')
        RETURNING id_sitio
        """,
        id_oportunidad,
    )


async def _crear_levantamiento(conn, *, id_oportunidad: UUID, id_sitio: UUID, solicitado_por_id: UUID, codigo: str) -> UUID:
    id_estatus = await conn.fetchval("SELECT id FROM tb_cat_estatus_levantamiento WHERE codigo = $1", codigo)
    return await conn.fetchval(
        """
        INSERT INTO tb_levantamientos (
            id_levantamiento, id_sitio, id_oportunidad, solicitado_por_id,
            id_estatus_global, fecha_solicitud, created_at, updated_at, updated_by_id
        ) VALUES (gen_random_uuid(), $1, $2, $3, $4, now(), now(), now(), $3)
        RETURNING id_levantamiento
        """,
        id_sitio, id_oportunidad, solicitado_por_id, id_estatus,
    )


def _admin_context(user_id: UUID) -> dict:
    return {
        "user_db_id": user_id, "user_name": "Test Admin", "email": "admin@test.local",
        "role": "ADMIN", "module_roles": {},
    }


async def test_subtab_cancelados_excluye_multisitio_parcialmente_cancelado(real_conn):
    """La subquery `lev` en QUERY_GET_OPORTUNIDADES_LIST es DISTINCT ON(id_oportunidad)
    ordenada por id_estatus_global ASC (representante = hermano MENOS avanzado).
    Como 'cancelado' es el id mas alto del catalogo, filtrar lev.id_estatus_global =
    cancelado solo hace match cuando TODOS los hermanos estan cancelados."""
    creador = await _crear_usuario(real_conn)
    id_op = await _crear_oportunidad_levantamiento(real_conn, creado_por_id=creador)
    sitio_1 = await _crear_sitio(real_conn, id_op)
    sitio_2 = await _crear_sitio(real_conn, id_op)
    await _crear_levantamiento(real_conn, id_oportunidad=id_op, id_sitio=sitio_1, solicitado_por_id=creador, codigo="cancelado")
    lev_2 = await _crear_levantamiento(real_conn, id_oportunidad=id_op, id_sitio=sitio_2, solicitado_por_id=creador, codigo="pendiente")

    service = ComercialService()
    admin = _admin_context(creador)

    result = await service.get_oportunidades_list(real_conn, user_context=admin, tab="levantamientos", subtab="cancelados")
    assert id_op not in {op["id_oportunidad"] for op in result["items"]}

    # Al cancelar tambien el segundo sitio, la OP si aparece.
    await real_conn.execute(
        "UPDATE tb_levantamientos SET id_estatus_global = (SELECT id FROM tb_cat_estatus_levantamiento WHERE codigo = 'cancelado') WHERE id_levantamiento = $1",
        lev_2,
    )
    result = await service.get_oportunidades_list(real_conn, user_context=admin, tab="levantamientos", subtab="cancelados")
    assert id_op in {op["id_oportunidad"] for op in result["items"]}


# ───────────────────────── cerrar_oportunidad_levantamiento_cancelado (mock) ─────────────────────────


def _mock_conn(*, estatus_actual_id: int, codigos_lev=("cancelado",)):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"id_oportunidad": uuid4(), "id_estatus_global": estatus_actual_id})
    conn.fetch = AsyncMock(return_value=[{"codigo": c} for c in codigos_lev])
    conn.execute = AsyncMock()
    return conn


async def test_cerrar_levantamiento_cancelado_actualiza_op_y_notifica(monkeypatch):
    estatus_map = {"pendiente": 1, "cancelado": 5, "perdido": 6, "ganada": 7}
    monkeypatch.setattr(
        comercial_service_module.ConfigService, "get_catalog_map",
        AsyncMock(return_value=estatus_map)
    )
    conn = _mock_conn(estatus_actual_id=1)  # Pendiente
    service = ComercialService()
    service.workflow_notif_service = AsyncMock()
    id_op = uuid4()
    admin = _admin_context(uuid4())

    await service.cerrar_oportunidad_levantamiento_cancelado(conn, id_op, id_motivo_cierre=15, user_context=admin)

    conn.execute.assert_awaited_once()
    args = conn.execute.await_args.args
    assert args[1] == 5  # id_cancelado_op
    assert args[2] == 15  # id_motivo_cierre
    service.workflow_notif_service.notify_status_change.assert_awaited_once()


async def test_cerrar_levantamiento_cancelado_bloquea_op_ganada(monkeypatch):
    estatus_map = {"pendiente": 1, "cancelado": 5, "perdido": 6, "ganada": 7}
    monkeypatch.setattr(
        comercial_service_module.ConfigService, "get_catalog_map",
        AsyncMock(return_value=estatus_map)
    )
    conn = _mock_conn(estatus_actual_id=7)  # Ganada
    service = ComercialService()
    service.workflow_notif_service = AsyncMock()
    admin = _admin_context(uuid4())

    with pytest.raises(HTTPException) as exc:
        await service.cerrar_oportunidad_levantamiento_cancelado(conn, uuid4(), id_motivo_cierre=15, user_context=admin)

    assert exc.value.status_code == 400
    conn.execute.assert_not_awaited()
    service.workflow_notif_service.notify_status_change.assert_not_awaited()


async def test_cerrar_levantamiento_cancelado_bloquea_op_ya_entregada(monkeypatch):
    """Guarda POSITIVA (solo Pendiente), no exclude-list: si un exclude-list de
    solo {ganada, perdido} se usara, esta OP ya Entregada (por _propagar_estatus_op
    caso 2) se sobrescribiria silenciosamente a Cancelada."""
    estatus_map = {"pendiente": 1, "entregado": 4, "cancelado": 5, "perdido": 6, "ganada": 7}
    monkeypatch.setattr(
        comercial_service_module.ConfigService, "get_catalog_map",
        AsyncMock(return_value=estatus_map)
    )
    conn = _mock_conn(estatus_actual_id=4)  # Entregado
    service = ComercialService()
    service.workflow_notif_service = AsyncMock()
    admin = _admin_context(uuid4())

    with pytest.raises(HTTPException) as exc:
        await service.cerrar_oportunidad_levantamiento_cancelado(conn, uuid4(), id_motivo_cierre=15, user_context=admin)

    assert exc.value.status_code == 400
    conn.execute.assert_not_awaited()


async def test_cerrar_levantamiento_cancelado_revalida_todos_cancelado_toctou(monkeypatch):
    """Entre el GET que mostro el boton (subpestana Cancelados) y este POST, un
    levantamiento pudo reactivarse -- el cierre debe revalidar, no confiar en que
    la lista seguia vigente."""
    estatus_map = {"pendiente": 1, "cancelado": 5, "perdido": 6, "ganada": 7}
    monkeypatch.setattr(
        comercial_service_module.ConfigService, "get_catalog_map",
        AsyncMock(return_value=estatus_map)
    )
    conn = _mock_conn(estatus_actual_id=1, codigos_lev=("cancelado", "pendiente"))  # un hermano reactivado
    service = ComercialService()
    service.workflow_notif_service = AsyncMock()
    admin = _admin_context(uuid4())

    with pytest.raises(HTTPException) as exc:
        await service.cerrar_oportunidad_levantamiento_cancelado(conn, uuid4(), id_motivo_cierre=15, user_context=admin)

    assert exc.value.status_code == 400
    conn.execute.assert_not_awaited()
