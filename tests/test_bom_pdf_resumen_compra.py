"""
Tests de `core.bom.pdf_resumen_compra` (doc 40, puntos 6.3/6.4): conversion
Decimal->valor graficable para el PDF "resumen de compra" del consolidado BOM.

Funcion pura (no toca BD) -- deliberadamente aislada de
BomService._get_consolidado_proyecto_snapshot (ver docstring del modulo).
Cubre la regla central: un total None nunca se grafica como cero, se omite.
"""

from decimal import Decimal

from core.bom.pdf_resumen_compra import (
    datos_graficas_resumen_compra,
    _totales_bar,
    _por_paquete_bar,
    _por_grupo_bar,
)


def test_totales_bar_todos_presentes():
    totales = {
        "presupuesto_total_mxn": Decimal("1000"),
        "cotizado_total_mxn": Decimal("900"),
        "autorizado_total_mxn": Decimal("800"),
        "facturado_total_mxn": Decimal("500"),
        "pagado_total_mxn": Decimal("400"),
    }
    r = _totales_bar(totales)
    assert r["labels"] == ["Presupuesto", "Cotizado", "Autorizado", "Facturado", "Pagado"]
    assert r["datasets"][0]["data"] == [1000.0, 900.0, 800.0, 500.0, 400.0]


def test_totales_bar_omite_none_no_lo_muestra_en_cero():
    totales = {
        "presupuesto_total_mxn": Decimal("1000"),
        "cotizado_total_mxn": None,
        "autorizado_total_mxn": Decimal("800"),
        "facturado_total_mxn": None,
        "pagado_total_mxn": None,
    }
    r = _totales_bar(totales)
    assert r["labels"] == ["Presupuesto", "Autorizado"]
    assert r["datasets"][0]["data"] == [1000.0, 800.0]


def test_totales_bar_todo_none_devuelve_none():
    totales = {k: None for k in (
        "presupuesto_total_mxn", "cotizado_total_mxn", "autorizado_total_mxn",
        "facturado_total_mxn", "pagado_total_mxn",
    )}
    assert _totales_bar(totales) is None


def _paquete(codigo, presupuesto=1, cotizado=1, autorizado=1, facturado=1, pagado=1):
    return {
        "codigo": codigo,
        "presupuesto_total_mxn": presupuesto,
        "cotizado_total_mxn": cotizado,
        "autorizado_total_mxn": autorizado,
        "facturado_total_mxn": facturado,
        "pagado_total_mxn": pagado,
    }


def test_por_paquete_bar_incluye_solo_paquetes_completos():
    paquetes = [
        _paquete("PKG-A", presupuesto=Decimal("100"), cotizado=Decimal("90"),
                 autorizado=Decimal("80"), facturado=Decimal("50"), pagado=Decimal("40")),
        _paquete("PKG-B", presupuesto=None),  # conversion pendiente -> se excluye
    ]
    r = _por_paquete_bar(paquetes)
    assert r["labels"] == ["PKG-A"]
    assert len(r["datasets"]) == 5
    assert r["datasets"][0]["label"] == "Presupuesto"
    assert r["datasets"][0]["data"] == [100.0]


def test_por_paquete_bar_datasets_alineados_por_indice():
    paquetes = [
        _paquete("PKG-A", presupuesto=Decimal("100"), cotizado=Decimal("90"),
                 autorizado=Decimal("80"), facturado=Decimal("50"), pagado=Decimal("40")),
        _paquete("PKG-B", presupuesto=Decimal("200"), cotizado=Decimal("190"),
                 autorizado=Decimal("180"), facturado=Decimal("150"), pagado=Decimal("140")),
    ]
    r = _por_paquete_bar(paquetes)
    assert r["labels"] == ["PKG-A", "PKG-B"]
    presupuestos = next(d for d in r["datasets"] if d["label"] == "Presupuesto")
    pagados = next(d for d in r["datasets"] if d["label"] == "Pagado")
    assert presupuestos["data"] == [100.0, 200.0]
    assert pagados["data"] == [40.0, 140.0]


def test_por_paquete_bar_sin_paquetes_completos_devuelve_none():
    paquetes = [_paquete("PKG-A", presupuesto=None), _paquete("PKG-B", cotizado=None)]
    assert _por_paquete_bar(paquetes) is None


def test_por_paquete_bar_lista_vacia_devuelve_none():
    assert _por_paquete_bar([]) is None


def _grupo(codigo, presupuesto_mxn=0, presupuesto_usd=0, facturado_mxn=0, pendiente=False):
    return {
        "codigo": codigo,
        "presupuesto_mxn": Decimal(str(presupuesto_mxn)),
        "presupuesto_usd": Decimal(str(presupuesto_usd)),
        "facturado_mxn": Decimal(str(facturado_mxn)),
        "presupuesto_pendiente": pendiente,
    }


def test_por_grupo_bar_solo_mxn_sin_convertir_usd():
    grupos = [_grupo("AC", presupuesto_mxn=1000, presupuesto_usd=50, facturado_mxn=600)]
    r = _por_grupo_bar(grupos)
    presupuesto_ds = next(d for d in r["datasets"] if d["label"] == "Presupuesto")
    assert presupuesto_ds["data"] == [1000.0]  # no incluye presupuesto_usd


def test_por_grupo_bar_anota_pendiente_con_asterisco():
    grupos = [
        _grupo("AC", pendiente=False),
        _grupo("DC", pendiente=True),
    ]
    r = _por_grupo_bar(grupos)
    assert r["labels"] == ["AC", "DC *"]


def test_por_grupo_bar_vacio_devuelve_none():
    assert _por_grupo_bar([]) is None


def test_datos_graficas_resumen_compra_integra_las_tres():
    consolidado = {
        "totales": {
            "presupuesto_total_mxn": Decimal("1000"), "cotizado_total_mxn": Decimal("900"),
            "autorizado_total_mxn": Decimal("800"), "facturado_total_mxn": Decimal("500"),
            "pagado_total_mxn": Decimal("400"),
        },
        "paquetes": [_paquete("PKG-A", presupuesto=Decimal("100"), cotizado=Decimal("90"),
                               autorizado=Decimal("80"), facturado=Decimal("50"), pagado=Decimal("40"))],
        "desglose_grupos": [_grupo("AC", presupuesto_mxn=100, facturado_mxn=50)],
    }
    r = datos_graficas_resumen_compra(consolidado)
    assert set(r.keys()) == {"totales_bar", "por_paquete_bar", "por_grupo_bar"}
    assert r["totales_bar"] is not None
    assert r["por_paquete_bar"] is not None
    assert r["por_grupo_bar"] is not None


def test_datos_graficas_resumen_compra_no_muta_el_dict_original():
    """El snapshot compartido (_get_consolidado_proyecto_snapshot) es el path de
    mas trafico del modulo BOM -- esta funcion nunca debe mutarlo."""
    consolidado = {
        "totales": {"presupuesto_total_mxn": Decimal("1000")},
        "paquetes": [],
        "desglose_grupos": [],
    }
    import copy
    original = copy.deepcopy(consolidado)
    datos_graficas_resumen_compra(consolidado)
    assert consolidado == original
