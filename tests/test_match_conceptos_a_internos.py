"""
Tests del matcher automatico catalogo interno<->XML (doc 39, punto 6.2),
`core.materials.matcher.match_conceptos_a_internos`. Adaptado de
tests/test_match_conceptos_a_items.py (matcher factura<->BOM), 3 niveles en
vez de 4 (sin nivel COTIZACION -- el catalogo interno no tiene subtotal de
cotizacion contra el cual anclar monto).

El matcher es puro (no toca BD), se llama directo con listas en memoria.
"""

from core.materials.matcher import match_conceptos_a_internos


def _interno(id, descripcion_norm, clave_prod_serv=None):
    return {'id': id, 'descripcion_norm': descripcion_norm, 'clave_prod_serv': clave_prod_serv}


def test_clave_sat_exacta_unica_es_alta():
    conceptos = [{'descripcion': 'CABLE DESCONOCIDO', 'clave_prod_serv': '26111702'}]
    catalogo = [
        _interno('A', 'PANEL SOLAR 550W', clave_prod_serv='27112800'),
        _interno('B', 'CABLE FOTOVOLTAICO 6MM', clave_prod_serv='26111702'),
    ]
    r = match_conceptos_a_internos(conceptos, catalogo)
    assert r[0] == {
        'id_material_interno': 'B', 'confianza': 'ALTA', 'origen': 'CLAVE_SAT',
        'clave_prod_serv': '26111702',
    }


def test_clave_sat_ambigua_no_se_auto_aplica_cae_a_texto():
    # Dos items del catalogo comparten la misma clave SAT: ambiguo, no se
    # auto-aplica -- cae al siguiente nivel (aqui, texto).
    conceptos = [{'descripcion': 'CABLE FOTOVOLTAICO 6MM', 'clave_prod_serv': '26111702'}]
    catalogo = [
        _interno('A', 'CABLE FOTOVOLTAICO 6MM', clave_prod_serv='26111702'),
        _interno('B', 'CABLE FOTOVOLTAICO 10MM', clave_prod_serv='26111702'),
    ]
    r = match_conceptos_a_internos(conceptos, catalogo)
    assert r[0]['origen'] == 'TEXTO'
    assert r[0]['confianza'] == 'BAJA'


def test_clave_sat_corta_se_ignora_y_cae_a_texto():
    conceptos = [{'descripcion': 'PANEL SOLAR 550W', 'clave_prod_serv': '123'}]
    catalogo = [
        _interno('A', 'PANEL SOLAR 550W', clave_prod_serv='123'),
        _interno('B', 'TORNILLERIA', clave_prod_serv='999999'),
    ]
    r = match_conceptos_a_internos(conceptos, catalogo)
    assert r[0]['id_material_interno'] == 'A'
    assert r[0]['origen'] == 'TEXTO'


def test_memoria_acierta_es_alta():
    conceptos = [{'descripcion': 'NOMBRE RARO PROVEEDOR', 'clave_prod_serv': '50000000'}]
    catalogo = [
        _interno('A', 'ALGO', clave_prod_serv='11111111'),
        _interno('B', 'OTRA COSA', clave_prod_serv='22222222'),
    ]
    memoria_map = {'50000000': 'B'}
    r = match_conceptos_a_internos(conceptos, catalogo, memoria_map=memoria_map)
    assert r[0] == {
        'id_material_interno': 'B', 'confianza': 'ALTA', 'origen': 'MEMORIA',
        'clave_prod_serv': '50000000',
    }


def test_clave_sat_gana_a_memoria():
    conceptos = [{'descripcion': 'X', 'clave_prod_serv': '26111702'}]
    catalogo = [
        _interno('A', 'CABLE', clave_prod_serv='26111702'),
        _interno('B', 'OTRO', clave_prod_serv='99999999'),
    ]
    memoria_map = {'26111702': 'B'}
    r = match_conceptos_a_internos(conceptos, catalogo, memoria_map=memoria_map)
    assert r[0]['id_material_interno'] == 'A'
    assert r[0]['origen'] == 'CLAVE_SAT'


def test_fallback_texto_es_baja():
    conceptos = [{'descripcion': 'PANEL SOLAR 550W MONO', 'clave_prod_serv': ''}]
    catalogo = [
        _interno('A', 'PANEL SOLAR 550W'),
        _interno('B', 'TORNILLERIA VARIA'),
    ]
    r = match_conceptos_a_internos(conceptos, catalogo)
    assert r[0] == {
        'id_material_interno': 'A', 'confianza': 'BAJA', 'origen': 'TEXTO',
        'clave_prod_serv': None,
    }


def test_sin_match_devuelve_none():
    conceptos = [{'descripcion': 'ZZZZ QQQQ', 'clave_prod_serv': ''}]
    catalogo = [_interno('A', 'PANEL SOLAR 550W', clave_prod_serv='12345678')]
    r = match_conceptos_a_internos(conceptos, catalogo)
    assert r[0] is None


def test_memoria_none_no_rompe():
    conceptos = [{'descripcion': 'PANEL SOLAR 550W MONO', 'clave_prod_serv': ''}]
    catalogo = [_interno('A', 'PANEL SOLAR 550W')]
    r = match_conceptos_a_internos(conceptos, catalogo)
    assert r[0]['id_material_interno'] == 'A'
    assert r[0]['origen'] == 'TEXTO'


def test_catalogo_vacio_no_rompe():
    conceptos = [{'descripcion': 'CABLE', 'clave_prod_serv': '26111702'}]
    r = match_conceptos_a_internos(conceptos, [])
    assert r[0] is None


def test_varios_conceptos_resultado_por_indice():
    conceptos = [
        {'descripcion': 'X', 'clave_prod_serv': '26111702'},        # 0 -> clave
        {'descripcion': 'ZZZZ QQQQ', 'clave_prod_serv': ''},        # 1 -> sin match
        {'descripcion': 'Panel solar 550W', 'clave_prod_serv': ''},  # 2 -> texto
    ]
    catalogo = [
        _interno('A', 'CABLE', clave_prod_serv='26111702'),
        _interno('B', 'PANEL SOLAR 550W'),
    ]
    r = match_conceptos_a_internos(conceptos, catalogo)
    assert r[0] == {
        'id_material_interno': 'A', 'confianza': 'ALTA', 'origen': 'CLAVE_SAT',
        'clave_prod_serv': '26111702',
    }
    assert r[1] is None
    assert r[2]['id_material_interno'] == 'B' and r[2]['origen'] == 'TEXTO'
