"""
Tests unitarios del reporte Excel de bolsa HE (Fase 7 del plan
_Planes_Activos/Planes_Anteriores_Ejecutados/2026-06-29-bolsa-horas-extra.md): armado del workbook
_build_he_bolsa_workbook. No requieren BD.

Las aserciones usan _visible_rows (filtra filas 100% vacias) para no
depender de si una fila esta materializada o no en openpyxl - eso aisla
estos tests del bug de estilo conocido en start_row (ver hallazgo
reportado aparte): el contenido de cada bloque es correcto aunque el
resaltado de la fila de titulo caiga en la fila equivocada.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from modules.asistencia.service import _build_he_bolsa_workbook


def _visible_rows(ws) -> list[tuple]:
    return [
        tuple(cell.value for cell in row)
        for row in ws.iter_rows()
        if any(cell.value is not None for cell in row)
    ]


def test_workbook_una_sola_hoja_bolsa_he():
    wb = _build_he_bolsa_workbook(usuarios=[], saldos={}, movimientos=[], feriados=[])
    assert wb.sheetnames == ["Bolsa HE"]


def test_workbook_sin_usuarios_no_genera_filas():
    wb = _build_he_bolsa_workbook(usuarios=[], saldos={}, movimientos=[], feriados=[])
    assert _visible_rows(wb.active) == []


def test_workbook_empleado_sin_movimientos_bloque_en_ceros():
    uid = uuid4()
    usuarios = [{"id_usuario": uid, "nombre": "Empleado Test", "email": "test@test.com", "jefes_nombres": "Jefe Uno"}]

    wb = _build_he_bolsa_workbook(usuarios=usuarios, saldos={}, movimientos=[], feriados=[])
    rows = _visible_rows(wb.active)

    assert rows == [
        ("Empleado Test", "test@test.com", "Jefe Uno", None),
        ("Horas acumuladas", "Horas tomadas", "Horas disponibles", None),
        (0.0, 0.0, 0.0, None),
        ("Fecha", "Concepto", "Horas", "Saldo despues"),
    ]


def test_workbook_incluye_creditos_debitos_y_saldo_despues():
    uid = uuid4()
    usuarios = [{"id_usuario": uid, "nombre": "Empleado Test", "email": "test@test.com", "jefes_nombres": None}]
    saldos = {uid: {"minutos_acumulados": 120, "minutos_tomados": 60, "minutos_disponibles": 60}}
    movimientos = [
        {
            "usuario_id": uid, "tipo": "CREDITO", "minutos": 120,
            "concepto": "HE aprobada", "fecha_referencia": date(2026, 7, 1),
            "saldo_despues": 120,
        },
        {
            "usuario_id": uid, "tipo": "DEBITO", "minutos": 60,
            "concepto": "Compensatorio aprobado", "fecha_referencia": date(2026, 7, 5),
            "saldo_despues": 60,
        },
    ]

    wb = _build_he_bolsa_workbook(usuarios=usuarios, saldos=saldos, movimientos=movimientos, feriados=[])
    rows = _visible_rows(wb.active)

    assert rows[2] == (2.0, 1.0, 1.0, None)
    assert rows[4] == (date(2026, 7, 1), "HE aprobada", 2.0, 2.0)
    assert rows[5] == (date(2026, 7, 5), "Compensatorio aprobado", -1.0, 1.0)


def test_workbook_incluye_feriados_sin_afectar_saldo():
    uid = uuid4()
    usuarios = [{"id_usuario": uid, "nombre": "Empleado Test", "email": "test@test.com", "jefes_nombres": None}]
    feriados = [
        {
            "usuario_id": uid, "fecha_referencia": date(2026, 12, 25),
            "minutos_extra": 120, "concepto": "FERIADO PAGO ECONOMICO",
        }
    ]

    wb = _build_he_bolsa_workbook(usuarios=usuarios, saldos={}, movimientos=[], feriados=feriados)
    rows = _visible_rows(wb.active)

    assert rows[4] == (date(2026, 12, 25), "FERIADO PAGO ECONOMICO", 2.0, "")


def test_workbook_multiples_empleados_un_bloque_cada_uno():
    uid1, uid2 = uuid4(), uuid4()
    usuarios = [
        {"id_usuario": uid1, "nombre": "Empleado Uno", "email": "uno@test.com", "jefes_nombres": None},
        {"id_usuario": uid2, "nombre": "Empleado Dos", "email": "dos@test.com", "jefes_nombres": None},
    ]

    wb = _build_he_bolsa_workbook(usuarios=usuarios, saldos={}, movimientos=[], feriados=[])
    rows = _visible_rows(wb.active)

    nombres = [row[0] for row in rows if row[0] in ("Empleado Uno", "Empleado Dos")]
    assert nombres == ["Empleado Uno", "Empleado Dos"]
    assert rows.count(("Fecha", "Concepto", "Horas", "Saldo despues")) == 2
