"""
Tests del matcher por niveles `BomService.match_conceptos_a_items`.

Cubre las 3 capas de confianza (clave SAT exacta, ancla de cotizacion por monto,
fallback de texto), el caso sin match y la desambiguacion por monto cuando varios
items comparten la misma clave SAT.

El metodo es puro (no toca BD), por eso se instancia BomService directamente.
"""

from core.bom.service import BomService


def _svc():
    return BomService()


def _item(id_item, descripcion, material_clave=None, coti_subtotal=None, id_material_ref=None):
    return {
        'id_item': id_item,
        'descripcion': descripcion,
        'material_clave': material_clave,
        'coti_subtotal': coti_subtotal,
        'id_material_ref': id_material_ref,
    }


def test_clave_sat_exacta_es_alta():
    conceptos = [{'descripcion': 'CABLE DESCONOCIDO', 'clave_prod_serv': '26111702', 'importe': 999}]
    bom_items = [
        _item('A', 'Panel solar 550W', material_clave='27112800', coti_subtotal=1000),
        _item('B', 'Cable fotovoltaico 6mm', material_clave='26111702', coti_subtotal=5000),
    ]
    r = _svc().match_conceptos_a_items(conceptos, bom_items)
    assert r[0] == {'id_item': 'B', 'confianza': 'ALTA', 'origen': 'CLAVE_SAT'}


def test_clave_sat_empate_desempata_por_monto():
    # Dos items con la MISMA clave SAT: gana el de subtotal mas cercano al importe.
    conceptos = [{'descripcion': 'X', 'clave_prod_serv': '26111702', 'importe': 4800}]
    bom_items = [
        _item('A', 'Cable rollo 1', material_clave='26111702', coti_subtotal=1000),
        _item('B', 'Cable rollo 2', material_clave='26111702', coti_subtotal=5000),
    ]
    r = _svc().match_conceptos_a_items(conceptos, bom_items)
    assert r[0]['id_item'] == 'B'
    assert r[0]['origen'] == 'CLAVE_SAT'


def test_ancla_cotizacion_por_monto_unico_es_alta():
    # Sin clave coincidente; el importe cuadra con un unico subtotal de cotizacion.
    conceptos = [{'descripcion': 'PRODUCTO PROVEEDOR RARO', 'clave_prod_serv': '99999999', 'importe': 5000}]
    bom_items = [
        _item('A', 'Algo', material_clave='11111111', coti_subtotal=1000),
        _item('B', 'Otra cosa', material_clave='22222222', coti_subtotal=5000),
    ]
    r = _svc().match_conceptos_a_items(conceptos, bom_items)
    assert r[0] == {'id_item': 'B', 'confianza': 'ALTA', 'origen': 'COTIZACION'}


def test_ancla_cotizacion_dentro_de_tolerancia():
    # 5000 vs 5040 -> 0.8% < 1% -> sigue contando como match de monto.
    conceptos = [{'descripcion': 'X', 'clave_prod_serv': '0', 'importe': 5040}]
    bom_items = [
        _item('A', 'Algo', coti_subtotal=1000),
        _item('B', 'Otra', coti_subtotal=5000),
    ]
    r = _svc().match_conceptos_a_items(conceptos, bom_items)
    assert r[0]['id_item'] == 'B'
    assert r[0]['origen'] == 'COTIZACION'


def test_fallback_texto_es_baja():
    # Ni clave ni monto: cae a similitud de texto.
    conceptos = [{'descripcion': 'PANEL SOLAR 550W MONO', 'clave_prod_serv': '', 'importe': 12345}]
    bom_items = [
        _item('A', 'Panel solar 550W', material_clave=None, coti_subtotal=1),
        _item('B', 'Tornilleria varia', material_clave=None, coti_subtotal=2),
    ]
    r = _svc().match_conceptos_a_items(conceptos, bom_items)
    assert r[0]['id_item'] == 'A'
    assert r[0] == {'id_item': 'A', 'confianza': 'BAJA', 'origen': 'TEXTO'}


def test_sin_match_devuelve_none():
    conceptos = [{'descripcion': 'ZZZZ QQQQ', 'clave_prod_serv': '', 'importe': 99}]
    bom_items = [
        _item('A', 'Panel solar 550W', material_clave='12345678', coti_subtotal=1000),
    ]
    r = _svc().match_conceptos_a_items(conceptos, bom_items)
    assert r[0] is None


def test_memoria_acierta_es_alta():
    # Ni la clave ni el monto cuadran solos; la memoria proveedor->material apunta a B.
    conceptos = [{'descripcion': 'NOMBRE RARO PROVEEDOR', 'clave_prod_serv': '50000000', 'importe': 777}]
    bom_items = [
        _item('A', 'Algo', material_clave='11111111', coti_subtotal=100, id_material_ref='MAT-A'),
        _item('B', 'Otra cosa', material_clave='22222222', coti_subtotal=999, id_material_ref='MAT-B'),
    ]
    memoria_map = {'50000000': 'MAT-B'}
    r = _svc().match_conceptos_a_items(conceptos, bom_items, memoria_map=memoria_map)
    assert r[0] == {'id_item': 'B', 'confianza': 'ALTA', 'origen': 'MEMORIA'}


def test_clave_sat_gana_a_memoria():
    # La clave SAT exacta (A) tiene prioridad sobre la memoria (que apuntaria a B).
    conceptos = [{'descripcion': 'X', 'clave_prod_serv': '26111702', 'importe': 1}]
    bom_items = [
        _item('A', 'Cable', material_clave='26111702', coti_subtotal=1, id_material_ref='MAT-A'),
        _item('B', 'Otro', material_clave='99999999', coti_subtotal=1, id_material_ref='MAT-B'),
    ]
    memoria_map = {'26111702': 'MAT-B'}
    r = _svc().match_conceptos_a_items(conceptos, bom_items, memoria_map=memoria_map)
    assert r[0]['id_item'] == 'A'
    assert r[0]['origen'] == 'CLAVE_SAT'


def test_memoria_none_no_rompe():
    # Sin memoria_map el matcher se comporta como en B1 (compat hacia atras).
    conceptos = [{'descripcion': 'PANEL SOLAR 550W MONO', 'clave_prod_serv': '', 'importe': 12345}]
    bom_items = [_item('A', 'Panel solar 550W', coti_subtotal=1)]
    r = _svc().match_conceptos_a_items(conceptos, bom_items)
    assert r[0]['id_item'] == 'A'
    assert r[0]['origen'] == 'TEXTO'


def test_prioridad_clave_sobre_monto():
    # El importe cuadra con A, pero la clave SAT exacta apunta a B -> gana la clave.
    conceptos = [{'descripcion': 'X', 'clave_prod_serv': '26111702', 'importe': 1000}]
    bom_items = [
        _item('A', 'Algo barato', material_clave='00000000', coti_subtotal=1000),
        _item('B', 'Cable', material_clave='26111702', coti_subtotal=9999),
    ]
    r = _svc().match_conceptos_a_items(conceptos, bom_items)
    assert r[0]['id_item'] == 'B'
    assert r[0]['origen'] == 'CLAVE_SAT'


def test_empate_de_montos_desempata_por_texto():
    # Dos items con subtotal dentro de tolerancia del importe: gana el de mejor texto.
    conceptos = [{'descripcion': 'PANEL SOLAR 550W MONO', 'clave_prod_serv': '', 'importe': 5000}]
    bom_items = [
        _item('A', 'Tornilleria varia', coti_subtotal=5000),
        _item('B', 'Panel solar 550W mono', coti_subtotal=5000),
    ]
    r = _svc().match_conceptos_a_items(conceptos, bom_items)
    assert r[0] == {'id_item': 'B', 'confianza': 'ALTA', 'origen': 'COTIZACION'}


def test_clave_sat_corta_se_ignora_y_cae_a_texto():
    # Clave de <6 caracteres no es señal fiable: el guard la descarta y cae a texto.
    conceptos = [{'descripcion': 'PANEL SOLAR 550W', 'clave_prod_serv': '123', 'importe': 99}]
    bom_items = [
        _item('A', 'Panel solar 550W', material_clave='123', coti_subtotal=1),
        _item('B', 'Tornilleria', material_clave='999999', coti_subtotal=2),
    ]
    r = _svc().match_conceptos_a_items(conceptos, bom_items)
    assert r[0]['id_item'] == 'A'
    assert r[0]['origen'] == 'TEXTO'


def test_memoria_apunta_a_material_ausente_cae_a_siguiente_nivel():
    # La memoria recuerda un material que ya no está en este BOM: se ignora y cae a cotización.
    conceptos = [{'descripcion': 'RARO', 'clave_prod_serv': '50000000', 'importe': 5000}]
    bom_items = [
        _item('A', 'Algo', material_clave='11111111', coti_subtotal=100, id_material_ref='MAT-A'),
        _item('B', 'Otra', material_clave='22222222', coti_subtotal=5000, id_material_ref='MAT-B'),
    ]
    memoria_map = {'50000000': 'MAT-AUSENTE'}
    r = _svc().match_conceptos_a_items(conceptos, bom_items, memoria_map=memoria_map)
    assert r[0] == {'id_item': 'B', 'confianza': 'ALTA', 'origen': 'COTIZACION'}


def test_varios_conceptos_resultado_por_indice():
    # Cada concepto resuelve por su propio nivel; los índices no se cruzan (refuerza B3a).
    conceptos = [
        {'descripcion': 'X', 'clave_prod_serv': '26111702', 'importe': 1},      # 0 -> clave
        {'descripcion': 'ZZZZ QQQQ', 'clave_prod_serv': '', 'importe': 99},     # 1 -> sin match
        {'descripcion': 'Panel solar 550W', 'clave_prod_serv': '', 'importe': 7},  # 2 -> texto
    ]
    bom_items = [
        _item('A', 'Cable', material_clave='26111702', coti_subtotal=999),
        _item('B', 'Panel solar 550W', coti_subtotal=999),
    ]
    r = _svc().match_conceptos_a_items(conceptos, bom_items)
    assert r[0] == {'id_item': 'A', 'confianza': 'ALTA', 'origen': 'CLAVE_SAT'}
    assert r[1] is None
    assert r[2]['id_item'] == 'B' and r[2]['origen'] == 'TEXTO'
