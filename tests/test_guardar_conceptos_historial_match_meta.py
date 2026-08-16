"""
Regresion B3a: `guardar_conceptos_historial` debe mapear bom_item_map y
match_meta_map a la fila correcta POR INDICE, compartiendo la misma lista
filtrada que el matcher. El bug original corria el match sobre la lista sin
filtrar y persistia id_bom_item/confianza/origen en el renglon equivocado.

Las aserciones resuelven la posicion de cada columna PARSEANDO el INSERT real
(`_column_indices`) en vez de hardcodear el indice numerico: la mayoria de las
columnas de match/sugerencia son `None` por default, asi que un futuro cambio
de orden en el INSERT (ej. doc 39, columnas de sugerencia del catalogo
interno) podria desalinear los indices sin que un assert `is None` lo note --
resolver por nombre de columna cierra ese hueco.
"""

import re
from uuid import uuid4

import pytest

from modules.compras.db_service import ComprasDBService


class FakeConn:
    """Stub minimo: fetch vacio (sin categorias previas), captura executemany."""
    def __init__(self):
        self.rows = None
        self.query = None

    async def fetch(self, *args, **kwargs):
        return []

    async def executemany(self, query, rows):
        self.query = query
        self.rows = rows

    async def execute(self, *args, **kwargs):
        return None


def _column_indices(query: str) -> dict:
    """Mapa nombre_columna -> indice, parseado del INSERT real."""
    match = re.search(r"INSERT INTO tb_materiales_historial \((.*?)\)\s*VALUES", query, re.S)
    columnas = [c.strip() for c in match.group(1).split(',')]
    return {nombre: idx for idx, nombre in enumerate(columnas)}


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
    cols = _column_indices(conn.query)

    # Fila 0: matcheada ALTA/CLAVE_SAT
    assert conn.rows[0][cols['id_bom_item']] == id_a
    assert conn.rows[0][cols['match_confianza']] == 'ALTA'
    assert conn.rows[0][cols['match_origen']] == 'CLAVE_SAT'
    # Fila 1: sin match -> todo None (no se corre la meta de otra fila)
    assert conn.rows[1][cols['id_bom_item']] is None
    assert conn.rows[1][cols['match_confianza']] is None
    assert conn.rows[1][cols['match_origen']] is None
    # Fila 2: matcheada ALTA/COTIZACION
    assert conn.rows[2][cols['id_bom_item']] == id_c
    assert conn.rows[2][cols['match_confianza']] == 'ALTA'
    assert conn.rows[2][cols['match_origen']] == 'COTIZACION'
    assert conn.rows[2][cols['id_bom_item_sugerido']] is None
    assert conn.rows[2][cols['sugerencia_confianza']] is None
    assert conn.rows[2][cols['sugerencia_origen']] is None


@pytest.mark.asyncio
async def test_sin_match_meta_columnas_quedan_none():
    conn = FakeConn()
    conceptos = [_concepto('CABLE')]

    await ComprasDBService().guardar_conceptos_historial(
        conn, 'UUID-FAC', uuid4(), uuid4(), conceptos,
        __import__('datetime').date(2026, 6, 23), uuid4(),
    )

    cols = _column_indices(conn.query)
    for nombre in (
        'id_bom_item', 'match_confianza', 'match_origen',
        'id_bom_item_sugerido', 'sugerencia_confianza', 'sugerencia_origen',
        'id_material_interno_sugerido', 'sugerencia_interno_confianza',
        'sugerencia_interno_origen',
    ):
        assert conn.rows[0][cols[nombre]] is None


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

    cols = _column_indices(conn.query)
    assert conn.rows[0][cols['id_bom_item']] is None
    assert conn.rows[0][cols['match_confianza']] is None
    assert conn.rows[0][cols['match_origen']] is None
    assert conn.rows[0][cols['id_bom_item_sugerido']] == id_sugerido
    assert conn.rows[0][cols['sugerencia_confianza']] == 'BAJA'
    assert conn.rows[0][cols['sugerencia_origen']] == 'TEXTO'


@pytest.mark.asyncio
async def test_sugerencia_interno_se_mapea_por_indice_y_no_pisa_bom():
    """doc 39: interno_suggestion_map comparte indice con conceptos/bom_item_map
    pero escribe columnas propias -- no debe interferir con las de BOM."""
    conn = FakeConn()
    id_interno_sugerido = uuid4()
    id_bom = uuid4()
    conceptos = [_concepto('CABLE'), _concepto('TUERCA')]

    await ComprasDBService().guardar_conceptos_historial(
        conn, 'UUID-FAC', uuid4(), uuid4(), conceptos,
        __import__('datetime').date(2026, 6, 23), uuid4(),
        bom_item_map={0: id_bom},
        match_meta_map={0: {'confianza': 'ALTA', 'origen': 'CLAVE_SAT'}},
        interno_suggestion_map={
            1: {
                'id_material_interno': id_interno_sugerido,
                'confianza': 'BAJA', 'origen': 'TEXTO',
            }
        },
    )

    cols = _column_indices(conn.query)
    # Fila 0: match BOM presente, sin sugerencia interno
    assert conn.rows[0][cols['id_bom_item']] == id_bom
    assert conn.rows[0][cols['id_material_interno_sugerido']] is None
    # Fila 1: sugerencia interno presente, sin match BOM
    assert conn.rows[1][cols['id_bom_item']] is None
    assert conn.rows[1][cols['id_material_interno_sugerido']] == id_interno_sugerido
    assert conn.rows[1][cols['sugerencia_interno_confianza']] == 'BAJA'
    assert conn.rows[1][cols['sugerencia_interno_origen']] == 'TEXTO'
