"""
Fase 1 del plan de moneda del presupuesto BOM: `sincronizar_costos_catalogo`
debe propagar la moneda resuelta del catalogo junto con el precio, no solo el
precio. Sin este test, un item vinculado a un material USD podia quedar con
precio correcto pero moneda='MXN' (subestimando el costo real ~18-20x).

Usa real_conn (rollback automatico) y reutiliza una cabeza de trabajo real de
DEV en vez de crear un BOM desde cero: tb_bom_items exige id_linea_bom/id_paquete
via FK compuesta a tb_bom_lineas, que no tiene fixture propio en el repo todavia
(ver PENDIENTES en el plan 2026-08-14-actualizacion-precios-compras-bom.md).
Por eso el test muta un item ya existente en vez de insertar uno nuevo.
"""
from decimal import Decimal

import pytest

from core.bom.db_service import BomDBService


async def _cabeza_trabajo_con_item_activo(conn):
    """Cabeza de trabajo real (paquete ACTIVO) que tenga al menos un item BASE activo."""
    row = await conn.fetchrow(
        """
        SELECT b.id_bom, i.id_item
        FROM tb_bom b
        JOIN tb_bom_paquetes p ON p.id_paquete = b.id_paquete
        JOIN tb_bom_items i ON i.id_bom = b.id_bom
        WHERE p.cabeza_trabajo_id = b.id_bom
          AND p.estado_paquete = 'ACTIVO'
          AND i.activo = TRUE
          AND COALESCE(i.tipo_origen_item, 'BASE') = 'BASE'
        LIMIT 1
        """
    )
    if row is None:
        pytest.skip("No hay una cabeza de trabajo ACTIVA con items BASE reales en DEV")
    return row


@pytest.mark.asyncio
async def test_sincronizar_costos_catalogo_propaga_moneda_usd(real_conn):
    """Un item sin costo vinculado a un material USD debe quedar con
    precio_unitario Y moneda='USD' tras el sync, no solo el precio."""
    conn = real_conn
    fila = await _cabeza_trabajo_con_item_activo(conn)
    id_bom = fila["id_bom"]
    id_item = fila["id_item"]

    material = await conn.fetchrow(
        """
        INSERT INTO tb_cat_materiales (descripcion_canonica, precio_referencia, moneda, activo)
        VALUES ('TEST SYNC COSTOS USD', 123.45, 'USD', TRUE)
        RETURNING id
        """
    )
    id_material_interno = material["id"]

    await conn.execute(
        """
        UPDATE tb_bom_items
        SET id_material_interno = $2,
            precio_unitario = NULL,
            moneda = 'MXN',
            origen_precio = 'MANUAL'
        WHERE id_item = $1
        """,
        id_item, id_material_interno,
    )

    db = BomDBService()
    actualizados = await db.sincronizar_costos_catalogo(conn, id_bom)

    ids_actualizados = {r["id_item"] for r in actualizados}
    assert id_item in ids_actualizados

    item_final = await conn.fetchrow(
        "SELECT precio_unitario, moneda, origen_precio FROM tb_bom_items WHERE id_item = $1",
        id_item,
    )
    assert item_final["precio_unitario"] == Decimal("123.45")
    assert item_final["moneda"].strip() == "USD"
    assert item_final["origen_precio"] == "CATALOGO"
