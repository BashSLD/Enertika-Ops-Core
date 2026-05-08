"""
Integración: flujo CIERRE_ANTICIPO en ComprasDBService contra BD real.
Cada test opera dentro de una transacción que se revierte al terminar.
"""
from decimal import Decimal
from uuid import uuid4
from datetime import date

import pytest
import pytest_asyncio

from modules.compras.db_service import ComprasDBService

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest_asyncio.fixture
async def comprobante_anticipo(real_conn):
    """Inserta un comprobante ANTICIPO de 10,000 MXN y retorna su UUID."""
    user_id = await real_conn.fetchval(
        "SELECT id_usuario FROM tb_usuarios WHERE is_active = true LIMIT 1"
    )
    if not user_id:
        pytest.skip("No hay usuarios activos en la BD")

    id_comp = uuid4()
    await real_conn.execute(
        """
        INSERT INTO tb_comprobantes_pago (
            id_comprobante, fecha_pago, beneficiario_orig, monto, moneda,
            estatus, capturado_por_id, es_anticipo, tipo_factura,
            monto_facturado, created_at, updated_at
        ) VALUES ($1, $2, 'TEST CIERRE ANTICIPO INTEGRACION', $3, 'MXN',
            'ANTICIPO', $4, TRUE, 'ANTICIPO', 0, NOW(), NOW())
        """,
        id_comp,
        date(2026, 5, 1),
        Decimal("10000.00"),
        user_id,
    )
    return id_comp


async def test_cierre_anticipo_completo_estatus_facturado(real_conn, comprobante_anticipo):
    await ComprasDBService().confirmar_match(
        real_conn,
        comprobante_anticipo,
        str(uuid4()).upper(),
        None,
        "CIERRE_ANTICIPO",
        "ANTICIPO",
        Decimal("10000.00"),
        id_comprobante_anticipo=comprobante_anticipo,
    )

    row = await real_conn.fetchrow(
        """SELECT estatus, monto_facturado, es_anticipo, id_comprobante_anticipo
           FROM tb_comprobantes_pago WHERE id_comprobante = $1""",
        comprobante_anticipo,
    )
    assert row["estatus"] == "FACTURADO"
    assert row["monto_facturado"] == Decimal("10000.00")
    assert row["es_anticipo"] is False
    assert row["id_comprobante_anticipo"] == comprobante_anticipo


async def test_cierre_anticipo_parcial_estatus_parcialmente_facturado(real_conn, comprobante_anticipo):
    await ComprasDBService().confirmar_match(
        real_conn,
        comprobante_anticipo,
        str(uuid4()).upper(),
        None,
        "CIERRE_ANTICIPO",
        "ANTICIPO",
        Decimal("4000.00"),
        id_comprobante_anticipo=comprobante_anticipo,
    )

    row = await real_conn.fetchrow(
        "SELECT estatus, monto_facturado FROM tb_comprobantes_pago WHERE id_comprobante = $1",
        comprobante_anticipo,
    )
    assert row["estatus"] == "PARCIALMENTE_FACTURADO"
    assert row["monto_facturado"] == Decimal("4000.00")


async def test_cierre_anticipo_dentro_de_tolerancia_se_cierra_facturado(real_conn, comprobante_anticipo):
    """Un cierre con $0.30 menos del total entra en tolerancia ($0.50) y cierra como FACTURADO."""
    await ComprasDBService().confirmar_match(
        real_conn,
        comprobante_anticipo,
        str(uuid4()).upper(),
        None,
        "CIERRE_ANTICIPO",
        "ANTICIPO",
        Decimal("9999.70"),
        id_comprobante_anticipo=comprobante_anticipo,
    )

    row = await real_conn.fetchrow(
        "SELECT estatus FROM tb_comprobantes_pago WHERE id_comprobante = $1",
        comprobante_anticipo,
    )
    assert row["estatus"] == "FACTURADO"
