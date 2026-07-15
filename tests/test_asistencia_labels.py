"""
Tests del formateador unico de label de estado de asistencia
(_Planes_Activos/PLAN_ASISTENCIA_AUSENCIAS_DESCANSO.md, seccion 5): reemplaza el chip
secundario duplicado de tipo de ausencia -- generaliza el patron que antes solo cubria
vacaciones (commit 9f4bba5) a todos los estados de ausencia.
"""

from __future__ import annotations

from datetime import date

from modules.asistencia.constants import formatear_estado_asistencia_label
from modules.perfil.router import _preparar_asistencia_rows


def test_formatear_ausencia_usa_tipo_real():
    assert formatear_estado_asistencia_label("ausencia", "Incapacidad") == "Incapacidad"


def test_formatear_ausencia_sin_tipo_usa_generico():
    assert formatear_estado_asistencia_label("ausencia", None) == "Ausencia"


def test_formatear_vacaciones_conserva_label_fijo():
    assert formatear_estado_asistencia_label("vacaciones", "Vacaciones") == "Vacaciones"


def test_formatear_checada_en_ausencia_no_se_sustituye():
    assert formatear_estado_asistencia_label("checada_en_ausencia", "Incapacidad") == "Checada en ausencia"


def test_formatear_estado_vacio():
    assert formatear_estado_asistencia_label("", "Incapacidad") == ""


def test_formatear_estado_desconocido_usa_replace_underscore():
    assert formatear_estado_asistencia_label("un_estado_nuevo", None) == "un estado nuevo"


def test_preparar_rows_ausencia_usa_tipo_como_label_unico():
    rows = [{
        "fecha_laboral": date(2026, 7, 20),
        "estado": "ausencia",
        "tipo_ausencia_nombre": "Incapacidad",
        "tiene_ausencia_justificada": True,
    }]

    resultado = _preparar_asistencia_rows(rows, hoy=date(2026, 7, 21), fecha_minima=date(2026, 7, 1))

    assert resultado[0]["estado_label"] == "Incapacidad"
    assert "mostrar_tipo_ausencia" not in resultado[0]


def test_preparar_rows_vacaciones_no_duplica_chip():
    rows = [{
        "fecha_laboral": date(2026, 7, 20),
        "estado": "vacaciones",
        "tipo_ausencia_nombre": "Vacaciones",
        "tiene_ausencia_justificada": True,
    }]

    resultado = _preparar_asistencia_rows(rows, hoy=date(2026, 7, 21), fecha_minima=date(2026, 7, 1))

    assert resultado[0]["estado_label"] == "Vacaciones"
    assert "mostrar_tipo_ausencia" not in resultado[0]
