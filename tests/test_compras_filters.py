from unittest.mock import AsyncMock

import pytest

from modules.compras.db_service import ComprasDBService


@pytest.mark.asyncio
async def test_sin_completar_incluye_anticipos_en_listado():
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])

    await ComprasDBService().get_comprobantes_filtered(
        conn,
        {"estatus": "SIN_COMPLETAR"},
        count_only=False,
    )

    sql = conn.fetch.await_args.args[0]
    assert "PENDIENTE" in sql
    assert "PARCIALMENTE_FACTURADO" in sql
    assert "ANTICIPO" in sql


@pytest.mark.asyncio
async def test_sin_completar_incluye_anticipos_en_estadisticas():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={
        "total": 0,
        "pendientes": 0,
        "facturados": 0,
        "anticipos": 0,
        "parciales": 0,
        "cerrados": 0,
        "total_mxn": 0,
        "total_usd": 0,
    })

    await ComprasDBService().get_estadisticas(conn, {"estatus": "SIN_COMPLETAR"})

    sql = conn.fetchrow.await_args.args[0]
    params = conn.fetchrow.await_args.args[1:]
    assert "PENDIENTE" in sql
    assert "PARCIALMENTE_FACTURADO" in sql
    assert "ANTICIPO" in sql
    assert "SIN_COMPLETAR" not in params


@pytest.mark.asyncio
async def test_catalogo_compradores_solo_usuarios_con_comprobantes():
    conn = AsyncMock()
    conn.fetch = AsyncMock(side_effect=[[], [], [], []])

    await ComprasDBService().get_catalogos_data(conn)

    sql = conn.fetch.await_args_list[3].args[0]
    assert "tb_comprobantes_pago" in sql
    assert "capturado_por_id" in sql
    assert "EXISTS" in sql
