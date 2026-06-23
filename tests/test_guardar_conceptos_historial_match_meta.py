"""
Regresion B3a: `guardar_conceptos_historial` debe mapear bom_item_map y
match_meta_map a la fila correcta POR INDICE, compartiendo la misma lista
filtrada que el matcher. El bug original corria el match sobre la lista sin
filtrar y persistia id_bom_item/confianza/origen en el renglon equivocado.

Posiciones en la tupla de INSERT (ver db_service.guardar_conceptos_historial):
  [15] id_bom_item  [16] match_confianza  [17] match_origen
  [18] id_bom_item_sugerido  [19] sugerencia_confianza  [20] sugerencia_origen
"""

from uuid import uuid4

import pytest

from modules.compras.db_service import ComprasDBService


class FakeConn:
    """Stub minimo: fetch vacio (sin categorias previas), captura executemany."""
    def __init__(self):
        self.rows = None

    async def fetch(self, *args, **kwargs):
        return []

    async def executemany(self, query, rows):
        self.rows = rows

    async def execute(self, *args, **kwargs):
        return None


def _concepto(desc, clave='12345678'):
    return {
        'descripcion': desc, 'cantidad': 1, 'valor_unitario': 10,
        'importe': 10, 'unidad': 'PZA', 'clave_prod_serv': clave,
        'clave_unidad': 'H87',
    }


@pytest.mark.asyncio
async def test_match_meta_se_mapea_por_indice():
    conn = FakeConn()
    id_a, id_c = uuid4(), uuid4()
    conceptos = [_concepto('CABLE'), _concepto('TUERCA'), _concepto('PANEL')]
    bom_item_map = {0: id_a, 2: id_c}
    match_meta_map = {
        0: {'confianza': 'ALTA', 'origen': 'CLAVE_SAT'},
        2: {'confianza': 'ALTA', 'origen': 'COTIZACION'},
    }

    await ComprasDBService().guardar_conceptos_historial(
        conn, 'UUID-FAC', uuid4(), uuid4(), conceptos,
        __import__('datetime').date(2026, 6, 23), uuid4(),
        bom_item_map=bom_item_map, match_meta_map=match_meta_map,
    )

    assert conn.rows is not None and len(conn.rows) == 3
    # Fila 0: matcheada ALTA/CLAVE_SAT
    assert conn.rows[0][15] == id_a
    assert conn.rows[0][16] == 'ALTA'
    assert conn.rows[0][17] == 'CLAVE_SAT'
    # Fila 1: sin match -> todo None (no se corre la meta de otra fila)
    assert conn.rows[1][15] is None
    assert conn.rows[1][16] is None
    assert conn.rows[1][17] is None
    # Fila 2: matcheada ALTA/COTIZACION
    assert conn.rows[2][15] == id_c
    assert conn.rows[2][16] == 'ALTA'
    assert conn.rows[2][17] == 'COTIZACION'
    assert conn.rows[2][18] is None
    assert conn.rows[2][19] is None
    assert conn.rows[2][20] is None


@pytest.mark.asyncio
async def test_sin_match_meta_columnas_quedan_none():
    conn = FakeConn()
    conceptos = [_concepto('CABLE')]

    await ComprasDBService().guardar_conceptos_historial(
        conn, 'UUID-FAC', uuid4(), uuid4(), conceptos,
        __import__('datetime').date(2026, 6, 23), uuid4(),
    )

    assert conn.rows[0][15] is None
    assert conn.rows[0][16] is None
    assert conn.rows[0][17] is None
    assert conn.rows[0][18] is None
    assert conn.rows[0][19] is None
    assert conn.rows[0][20] is None


@pytest.mark.asyncio
async def test_sugerencia_baja_no_puebla_id_bom_item():
    conn = FakeConn()
    id_sugerido = uuid4()
    conceptos = [_concepto('PANEL')]

    await ComprasDBService().guardar_conceptos_historial(
        conn, 'UUID-FAC', uuid4(), uuid4(), conceptos,
        __import__('datetime').date(2026, 6, 23), uuid4(),
        suggestion_map={
            0: {'id_item': id_sugerido, 'confianza': 'BAJA', 'origen': 'TEXTO'}
        },
    )

    assert conn.rows[0][15] is None
    assert conn.rows[0][16] is None
    assert conn.rows[0][17] is None
    assert conn.rows[0][18] == id_sugerido
    assert conn.rows[0][19] == 'BAJA'
    assert conn.rows[0][20] == 'TEXTO'
