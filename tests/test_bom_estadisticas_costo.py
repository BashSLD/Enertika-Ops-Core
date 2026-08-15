"""
BomService._calcular_estadisticas_costo: el total de "Costo Estimado" se calcula
en Python sobre items ya enriquecidos con costo_mxn (cadena de TC de 3 niveles:
XML->Banxico reciente->promedio 7d), no en SQL — que no convertia USD y ponia
el total en None con solo un item en esa moneda, sin importar si tenia TC
resoluble. Ver _Planes_Activos/2026-08-14-actualizacion-precios-compras-bom.md.

costo_mxn es precio UNITARIO en MXN (no el total): hay que multiplicarlo por
cantidad, igual que costo_real_mxn en la columna "Costo Real" de row_item.html.
"""
from decimal import Decimal

from core.bom.service import BomService


def _item(precio_unitario=None, moneda="MXN", importe=None, costo_mxn=None,
          activo=True, tipo_origen_item="BASE", cantidad=1):
    return {
        "precio_unitario": precio_unitario,
        "moneda": moneda,
        "importe": importe,
        "costo_mxn": costo_mxn,
        "activo": activo,
        "tipo_origen_item": tipo_origen_item,
        "cantidad": cantidad,
    }


def test_suma_mxn_y_usd_resuelto_da_total_completo():
    items = [
        _item(precio_unitario=100, moneda="MXN", importe=1000),
        _item(precio_unitario=10, moneda="USD", importe=10, costo_mxn=Decimal("180.00")),
    ]

    resultado = BomService._calcular_estadisticas_costo(items)

    assert resultado["costo_total_estimado"] == Decimal("1180.00")
    assert resultado["items_con_precio"] == 2
    assert resultado["items_sin_costo"] == 0
    assert resultado["items_sin_tc"] == 0


def test_usd_con_cantidad_mayor_a_uno_multiplica_costo_mxn_unitario():
    items = [
        _item(precio_unitario=10, moneda="USD", importe=50, costo_mxn=Decimal("180.00"), cantidad=5),
    ]

    resultado = BomService._calcular_estadisticas_costo(items)

    assert resultado["costo_total_estimado"] == Decimal("900.00")
    assert resultado["tc_promedio"] == Decimal("18")


def test_tc_promedio_ponderado_sobre_varios_items_usd():
    items = [
        _item(precio_unitario=10, moneda="USD", importe=10, costo_mxn=Decimal("180.00"), cantidad=1),
        _item(precio_unitario=100, moneda="USD", importe=100, costo_mxn=Decimal("2000.00"), cantidad=1),
    ]

    resultado = BomService._calcular_estadisticas_costo(items)

    assert resultado["costo_total_estimado"] == Decimal("2180.00")
    assert resultado["tc_promedio"] == Decimal("2180") / Decimal("110")


def test_sin_items_usd_tc_promedio_es_none():
    items = [_item(precio_unitario=100, moneda="MXN", importe=1000)]

    resultado = BomService._calcular_estadisticas_costo(items)

    assert resultado["tc_promedio"] is None


def test_usd_sin_tc_resoluble_deja_total_en_none_y_cuenta_items_sin_tc():
    items = [
        _item(precio_unitario=100, moneda="MXN", importe=1000),
        _item(precio_unitario=10000, moneda="USD", importe=10000, costo_mxn=None),
    ]

    resultado = BomService._calcular_estadisticas_costo(items)

    assert resultado["costo_total_estimado"] is None
    assert resultado["items_con_precio"] == 2
    assert resultado["items_sin_costo"] == 0
    assert resultado["items_sin_tc"] == 1


def test_item_sin_precio_deja_total_en_none_y_cuenta_items_sin_costo():
    items = [
        _item(precio_unitario=100, moneda="MXN", importe=1000),
        _item(precio_unitario=None, moneda="MXN"),
    ]

    resultado = BomService._calcular_estadisticas_costo(items)

    assert resultado["costo_total_estimado"] is None
    assert resultado["items_con_precio"] == 1
    assert resultado["items_sin_costo"] == 1
    assert resultado["items_sin_tc"] == 0


def test_ignora_items_inactivos_y_no_base():
    items = [
        _item(precio_unitario=100, moneda="MXN", importe=1000),
        _item(precio_unitario=None, moneda="MXN", activo=False),
        _item(precio_unitario=None, moneda="MXN", tipo_origen_item="REEMPLAZO"),
    ]

    resultado = BomService._calcular_estadisticas_costo(items)

    assert resultado["costo_total_estimado"] == Decimal("1000")
    assert resultado["items_con_precio"] == 1
    assert resultado["items_sin_costo"] == 0
    assert resultado["items_sin_tc"] == 0
