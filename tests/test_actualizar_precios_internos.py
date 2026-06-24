"""
Tests del parser puro `MaterialsService._parse_actualizacion_precios`.

Match por id (UUID) contra el dict `actuales` ({id: {'precio', 'moneda'}}).
Solo se actualizan precio_referencia y moneda; las filas sin cambio real se
reportan como 'sin_cambios' y no entran a 'validas'.
"""

import io
from uuid import uuid4

import pytest
from openpyxl import Workbook

from core.materials.service import MaterialsService


def _build_xlsx(rows, headers=("id", "descripcion", "unidad", "moneda", "precio_referencia")):
    wb = Workbook()
    ws = wb.active
    ws.append(list(headers))
    for row in rows:
        ws.append(list(row))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _parse(rows, actuales):
    return MaterialsService()._parse_actualizacion_precios(_build_xlsx(rows), actuales)


def test_actualiza_precio_cambiado():
    mid = uuid4()
    out = _parse(
        [(str(mid), "ABRAZADERA", "pza", "MXN", 7.50)],
        {mid: {"precio": 5.24, "moneda": "MXN"}},
    )
    assert out["resumen"] == {"a_actualizar": 1, "errores": 0, "sin_cambios": 0}
    assert out["validas"] == [{"id": mid, "precio_referencia": 7.50, "moneda": "MXN"}]


def test_sin_cambios_no_entra_a_validas():
    mid = uuid4()
    out = _parse(
        [(str(mid), "ABRAZADERA", "pza", "MXN", 5.24)],
        {mid: {"precio": 5.24, "moneda": "MXN"}},
    )
    assert out["resumen"]["sin_cambios"] == 1
    assert out["validas"] == []


def test_cambio_de_moneda_cuenta_como_actualizacion():
    mid = uuid4()
    out = _parse(
        [(str(mid), "X", "pza", "USD", 5.0)],
        {mid: {"precio": 5.0, "moneda": "MXN"}},
    )
    assert out["resumen"]["a_actualizar"] == 1
    assert out["validas"][0]["moneda"] == "USD"


def test_precio_donde_no_habia_es_actualizacion():
    mid = uuid4()
    out = _parse(
        [(str(mid), "X", "pza", "MXN", 3.0)],
        {mid: {"precio": None, "moneda": "MXN"}},
    )
    assert out["resumen"]["a_actualizar"] == 1


def test_id_inexistente_es_error():
    mid = uuid4()
    out = _parse([(str(mid), "X", "pza", "MXN", 1.0)], {})
    assert out["resumen"]["errores"] == 1
    assert out["validas"] == []


def test_id_invalido_es_error():
    out = _parse([("no-es-uuid", "X", "pza", "MXN", 1.0)], {})
    assert out["resumen"]["errores"] == 1


def test_precio_negativo_es_error():
    mid = uuid4()
    out = _parse(
        [(str(mid), "X", "pza", "MXN", -3)],
        {mid: {"precio": 5.0, "moneda": "MXN"}},
    )
    assert out["resumen"]["errores"] == 1


def test_precio_vacio_donde_no_habia_precio_es_sin_cambios():
    mid = uuid4()
    out = _parse(
        [(str(mid), "X", "pza", "MXN", "")],
        {mid: {"precio": None, "moneda": "MXN"}},
    )
    assert out["resumen"]["sin_cambios"] == 1
    assert out["validas"] == []


def test_precio_vacio_limpia_precio_existente():
    mid = uuid4()
    out = _parse(
        [(str(mid), "X", "pza", "MXN", "")],
        {mid: {"precio": 5.0, "moneda": "MXN"}},
    )
    assert out["resumen"]["a_actualizar"] == 1
    assert out["validas"] == [{"id": mid, "precio_referencia": None, "moneda": "MXN"}]


def test_moneda_invalida_es_error():
    mid = uuid4()
    out = _parse(
        [(str(mid), "X", "pza", "EUR", 5.0)],
        {mid: {"precio": 1.0, "moneda": "MXN"}},
    )
    assert out["resumen"]["errores"] == 1


def test_id_repetido_segunda_fila_es_error():
    mid = uuid4()
    out = _parse(
        [
            (str(mid), "X", "pza", "MXN", 7.0),
            (str(mid), "X", "pza", "MXN", 9.0),
        ],
        {mid: {"precio": 5.0, "moneda": "MXN"}},
    )
    assert out["resumen"]["a_actualizar"] == 1
    assert out["resumen"]["errores"] == 1


def test_fila_sin_id_se_ignora_en_silencio():
    mid = uuid4()
    out = _parse(
        [("", "", "", "", ""), (str(mid), "X", "pza", "MXN", 8.0)],
        {mid: {"precio": 5.0, "moneda": "MXN"}},
    )
    assert out["resumen"] == {"a_actualizar": 1, "errores": 0, "sin_cambios": 0}


def test_sin_encabezados_lanza_valueerror():
    wb = Workbook()
    wb.active.append(["foo", "bar"])
    buf = io.BytesIO()
    wb.save(buf)
    with pytest.raises(ValueError):
        MaterialsService()._parse_actualizacion_precios(buf.getvalue(), {})
