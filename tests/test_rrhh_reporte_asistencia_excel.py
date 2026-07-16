from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4

import pytest

from modules.rrhh.asistencia_excel_builder import (
    _duration_formula,
    _safe_sheet_title,
    build_asistencia_workbook,
)


def _row(**overrides) -> dict:
    row = {
        "usuario_id": uuid4(),
        "fecha_laboral": date(2026, 7, 1),
        "empleado_nombre": "Ana Ejemplo",
        "empleado_email": "ana@example.com",
        "sucursal_nombre": "Monterrey",
        "departamento": "Operaciones",
        "primera_entrada": datetime(2026, 7, 1, 8, 0),
        "ultima_salida": datetime(2026, 7, 1, 18, 0),
        "minutos_trabajados": 600,
        "minutos_programados": 480,
        "minutos_extra": 120,
        "minutos_aprobados": 90,
        "horas_extra_estado": "aprobado",
        "estado": "asistencia",
        "tiene_ausencia_justificada": False,
        "tipo_ausencia_nombre": None,
        "observaciones": "",
    }
    row.update(overrides)
    return row


@pytest.mark.parametrize(
    ("formato", "sheetnames"),
    [
        ("detalle", ["Asistencia", "Checadas sin mapear"]),
        ("detalle_consolidado", ["Consolidado", "Asistencia", "Checadas sin mapear"]),
        ("departamentos", ["Consolidado", "Operaciones", "Checadas sin mapear"]),
        (
            "completo",
            ["Consolidado", "Asistencia", "Por empleado", "Operaciones", "Checadas sin mapear"],
        ),
    ],
)
def test_workbook_generates_only_the_sheets_for_each_format(formato, sheetnames):
    workbook = build_asistencia_workbook(
        [_row()],
        [{"biotime_emp_code": "X-100", "deptname": "Sin asignar", "total": 1}],
        formato,
    )

    assert workbook.sheetnames == sheetnames


def test_consolidado_separa_laboral_he_autorizada_y_total_sin_duplicar():
    workbook = build_asistencia_workbook([_row()], [], "detalle_consolidado")
    worksheet = workbook["Consolidado"]

    assert worksheet["D2"].value == "8h"
    assert worksheet["E2"].value == "1h 30m"
    assert worksheet["F2"].value == "9h 30m"
    assert worksheet["D3"].value.startswith("=IF(AND(INT(SUM(")
    assert worksheet.column_dimensions["G"].hidden is True
    assert worksheet.column_dimensions["H"].hidden is True
    assert worksheet.column_dimensions["I"].hidden is True


def test_feriado_no_se_suma_como_hora_extra_autorizada():
    workbook = build_asistencia_workbook(
        [_row(horas_extra_estado="feriado", minutos_aprobados=120)],
        [],
        "detalle_consolidado",
    )

    assert workbook["Consolidado"]["E2"].value == "0m"
    assert workbook["Consolidado"]["F2"].value == "8h"


def test_detalle_agrega_formulas_y_oculta_las_columnas_auxiliares():
    workbook = build_asistencia_workbook([_row()], [], "detalle")
    worksheet = workbook["Asistencia"]

    assert worksheet["H3"].value.startswith("=IF(AND(INT(SUM(")
    assert worksheet["I3"].value.startswith("=IF(AND(INT(SUM(")
    assert worksheet["J3"].value.startswith("=IF(AND(INT(SUM(")
    assert worksheet.column_dimensions["O"].hidden is True
    assert worksheet.column_dimensions["P"].hidden is True
    assert worksheet.column_dimensions["Q"].hidden is True
    assert workbook.calculation.fullCalcOnLoad is True
    assert workbook.calculation.forceFullCalc is True


def test_departamentos_usa_nombres_validos_y_sin_colisiones():
    long_department = "Operaciones/Ingenieria: Norte con un nombre muy largo"
    workbook = build_asistencia_workbook(
        [_row(departamento=long_department), _row(departamento="OperacionesIngenieria Norte con un nombre muy largo")],
        [],
        "departamentos",
    )

    department_sheets = workbook.sheetnames[1:]
    assert all(len(title) <= 31 for title in department_sheets)
    assert all(not set(title) & set("\\/?*[]:") for title in department_sheets)
    assert len({title.casefold() for title in department_sheets}) == 2


def test_safe_sheet_title_reserves_fixed_titles_case_insensitively():
    used_titles = {"consolidado", "asistencia", "por empleado", "checadas sin mapear"}

    assert _safe_sheet_title("Asistencia", used_titles) == "Asistencia (2)"


def test_invalid_format_is_rejected():
    with pytest.raises(ValueError, match="Formato de asistencia no valido"):
        build_asistencia_workbook([], [], "otro")


def test_detalle_deja_celda_vacia_cuando_falta_departamento():
    workbook = build_asistencia_workbook([_row(departamento=None)], [], "detalle")
    worksheet = workbook["Asistencia"]

    assert worksheet["E2"].value == ""


def test_duration_formula_coincide_con_convencion_de_format_minutes():
    formula = _duration_formula("G2:G10")

    assert formula == (
        '=IF(AND(INT(SUM(G2:G10)/60)>0,MOD(SUM(G2:G10),60)>0),'
        'INT(SUM(G2:G10)/60)&"h "&TEXT(MOD(SUM(G2:G10),60),"00")&"m",'
        'IF(INT(SUM(G2:G10)/60)>0,INT(SUM(G2:G10)/60)&"h",MOD(SUM(G2:G10),60)&"m"))'
    )


def test_total_row_no_es_autoreferencial_sin_filas():
    workbook = build_asistencia_workbook([], [], "detalle")
    worksheet = workbook["Asistencia"]

    assert worksheet["A2"].value == "Total"
    assert worksheet["H2"].value == "0m"
    assert worksheet["I2"].value == "0m"
    assert worksheet["J2"].value == "0m"
