"""
Camino de escritura unico `MaterialsDBService.vincular_interno_a_xml` (doc 39,
punto 6.2): un UPDATE condicional en una sola sentencia
(`WHERE origen <> 'HUMANO' OR EXCLUDED.origen = 'HUMANO'`) garantiza que un
vinculo AUTO_* (matcher automatico) nunca sobreescribe uno HUMANO ya
confirmado, mientras que HUMANO siempre puede sobreescribir cualquier vinculo.

Se prueba contra BD real (no un fake) porque es la unica forma de verificar
que Postgres resuelve el WHERE del ON CONFLICT como se espera. Al ser una
sola sentencia atomica (no read-then-write), no hay ventana de carrera que una
segunda conexion pudiera explotar de forma distinta a la secuencia probada
aqui -- cubre las 4 combinaciones de origen existente/nuevo.
"""
from uuid import uuid4

import pytest

from core.materials.db_service import MaterialsDBService


async def _seed_concepto(conn, id_interno_inicial):
    id_proveedor = uuid4()
    await conn.execute(
        "INSERT INTO tb_proveedores (id_proveedor, rfc, razon_social) VALUES ($1, $2, $3)",
        id_proveedor, "XAXX010101000", "Proveedor de Prueba",
    )
    await conn.execute(
        "INSERT INTO tb_cat_materiales (id, descripcion_canonica, descripcion_norm, activo) "
        "VALUES ($1, 'Item A', 'ITEM A', TRUE)",
        id_interno_inicial,
    )
    id_xml = uuid4()
    await conn.execute(
        """
        INSERT INTO tb_materiales_historial
            (id, uuid_factura, id_proveedor, descripcion_proveedor, cantidad,
             precio_unitario, importe, fecha_factura, numero_linea_cfdi)
        VALUES ($1, $2, $3, 'Concepto de prueba', 1, 10, 10, CURRENT_DATE, 1)
        """,
        id_xml, uuid4(), id_proveedor,
    )
    return id_xml


async def _vinculo_actual(conn, id_xml):
    return await conn.fetchrow(
        "SELECT id_material_interno, origen FROM tb_materiales_interno_xml WHERE id_material_xml = $1",
        id_xml,
    )


@pytest.mark.asyncio
async def test_auto_no_sobreescribe_humano(real_conn):
    db = MaterialsDBService()
    id_a, id_b = uuid4(), uuid4()
    id_xml = await _seed_concepto(real_conn, id_a)
    await real_conn.execute(
        "INSERT INTO tb_cat_materiales (id, descripcion_canonica, descripcion_norm, activo) "
        "VALUES ($1, 'Item B', 'ITEM B', TRUE)",
        id_b,
    )

    await db.vincular_interno_a_xml(real_conn, id_xml, id_a, origen='HUMANO', confianza='ALTA')
    await db.vincular_interno_a_xml(real_conn, id_xml, id_b, origen='AUTO_CLAVE_SAT', confianza='ALTA')

    row = await _vinculo_actual(real_conn, id_xml)
    assert row['id_material_interno'] == id_a
    assert row['origen'] == 'HUMANO'


@pytest.mark.asyncio
async def test_humano_sobreescribe_auto(real_conn):
    db = MaterialsDBService()
    id_a, id_b = uuid4(), uuid4()
    id_xml = await _seed_concepto(real_conn, id_a)
    await real_conn.execute(
        "INSERT INTO tb_cat_materiales (id, descripcion_canonica, descripcion_norm, activo) "
        "VALUES ($1, 'Item B', 'ITEM B', TRUE)",
        id_b,
    )

    await db.vincular_interno_a_xml(real_conn, id_xml, id_a, origen='AUTO_TEXTO', confianza='BAJA')
    await db.vincular_interno_a_xml(real_conn, id_xml, id_b, origen='HUMANO', confianza='ALTA')

    row = await _vinculo_actual(real_conn, id_xml)
    assert row['id_material_interno'] == id_b
    assert row['origen'] == 'HUMANO'


@pytest.mark.asyncio
async def test_auto_puede_refinar_otro_auto(real_conn):
    db = MaterialsDBService()
    id_a, id_b = uuid4(), uuid4()
    id_xml = await _seed_concepto(real_conn, id_a)
    await real_conn.execute(
        "INSERT INTO tb_cat_materiales (id, descripcion_canonica, descripcion_norm, activo) "
        "VALUES ($1, 'Item B', 'ITEM B', TRUE)",
        id_b,
    )

    await db.vincular_interno_a_xml(real_conn, id_xml, id_a, origen='AUTO_TEXTO', confianza='BAJA')
    await db.vincular_interno_a_xml(real_conn, id_xml, id_b, origen='AUTO_CLAVE_SAT', confianza='ALTA')

    row = await _vinculo_actual(real_conn, id_xml)
    assert row['id_material_interno'] == id_b
    assert row['origen'] == 'AUTO_CLAVE_SAT'


@pytest.mark.asyncio
async def test_humano_puede_corregir_otro_humano(real_conn):
    db = MaterialsDBService()
    id_a, id_b = uuid4(), uuid4()
    id_xml = await _seed_concepto(real_conn, id_a)
    await real_conn.execute(
        "INSERT INTO tb_cat_materiales (id, descripcion_canonica, descripcion_norm, activo) "
        "VALUES ($1, 'Item B', 'ITEM B', TRUE)",
        id_b,
    )

    await db.vincular_interno_a_xml(real_conn, id_xml, id_a, origen='HUMANO', confianza='ALTA')
    await db.vincular_interno_a_xml(real_conn, id_xml, id_b, origen='HUMANO', confianza='ALTA')

    row = await _vinculo_actual(real_conn, id_xml)
    assert row['id_material_interno'] == id_b
    assert row['origen'] == 'HUMANO'
