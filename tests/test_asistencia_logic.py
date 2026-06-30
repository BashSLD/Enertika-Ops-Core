from datetime import date, datetime, time

from modules.asistencia.logic import (
    AttendanceCheck,
    MX_TZ,
    ScheduleConfig,
    build_labor_window,
    calcular_resumen_dia,
)


def _dt(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=MX_TZ)


def test_labor_window_crosses_midnight():
    schedule = ScheduleConfig(
        hora_entrada=time(20, 0),
        hora_salida=time(5, 0),
        minutos_programados=540,
        cruza_medianoche=True,
        margen_entrada_antes_min=120,
        margen_salida_despues_min=180,
    )

    window = build_labor_window(date(2026, 5, 12), schedule)

    assert window.start == _dt(2026, 5, 12, 18, 0)
    assert window.end == _dt(2026, 5, 13, 8, 0)


def test_after_midnight_checkout_belongs_to_labor_day_summary():
    schedule = ScheduleConfig(
        hora_entrada=time(20, 0),
        hora_salida=time(5, 0),
        minutos_programados=540,
        cruza_medianoche=True,
    )
    checks = [
        AttendanceCheck(_dt(2026, 5, 12, 20, 0), "0"),
        AttendanceCheck(_dt(2026, 5, 13, 0, 30), "1"),
    ]

    resumen = calcular_resumen_dia(
        checks=checks,
        schedule=schedule,
        tiene_vacaciones=False,
        es_feriado=False,
    )

    assert resumen["estado"] == "asistencia"
    assert resumen["primera_entrada"] == _dt(2026, 5, 12, 20, 0)
    assert resumen["ultima_salida"] == _dt(2026, 5, 13, 0, 30)
    assert resumen["minutos_trabajados"] == 270
    assert resumen["minutos_extra"] == 0


def test_overtime_is_calculated_locally_from_schedule():
    schedule = ScheduleConfig(
        hora_entrada=time(8, 0),
        hora_salida=time(17, 0),
        minutos_programados=480,
        tolerancia_extra_min=15,
    )
    checks = [
        AttendanceCheck(_dt(2026, 5, 12, 8, 0), "0"),
        AttendanceCheck(_dt(2026, 5, 12, 19, 0), "1"),
    ]

    resumen = calcular_resumen_dia(
        checks=checks,
        schedule=schedule,
        tiene_vacaciones=False,
        es_feriado=False,
    )

    assert resumen["minutos_trabajados"] == 660
    assert resumen["minutos_programados"] == 480
    assert resumen["minutos_extra"] == 165


def test_vacation_without_checks_marks_vacaciones():
    schedule = ScheduleConfig(
        hora_entrada=time(8, 0),
        hora_salida=time(17, 0),
        minutos_programados=480,
    )

    resumen = calcular_resumen_dia(
        checks=[],
        schedule=schedule,
        tiene_vacaciones=True,
        es_feriado=False,
    )

    assert resumen["estado"] == "vacaciones"
    assert resumen["minutos_trabajados"] == 0
    assert resumen["minutos_extra"] == 0


def test_paid_leave_without_checks_marks_ausencia():
    schedule = ScheduleConfig(
        hora_entrada=time(8, 0),
        hora_salida=time(17, 0),
        minutos_programados=480,
    )

    resumen = calcular_resumen_dia(
        checks=[],
        schedule=schedule,
        tiene_vacaciones=False,
        tiene_ausencia_justificada=True,
        ausencia_tipo_nombre="Permiso con goce de sueldo",
        es_feriado=False,
    )

    assert resumen["estado"] == "ausencia"
    assert resumen["minutos_trabajados"] == 0
    assert resumen["minutos_extra"] == 0
    assert resumen["observaciones"] == "Permiso con goce de sueldo"


def test_checks_during_paid_leave_mark_checada_en_ausencia_without_overtime():
    schedule = ScheduleConfig(
        hora_entrada=time(8, 0),
        hora_salida=time(17, 0),
        minutos_programados=480,
    )
    checks = [
        AttendanceCheck(_dt(2026, 5, 12, 8, 0), "0"),
        AttendanceCheck(_dt(2026, 5, 12, 19, 0), "1"),
    ]

    resumen = calcular_resumen_dia(
        checks=checks,
        schedule=schedule,
        tiene_vacaciones=False,
        tiene_ausencia_justificada=True,
        ausencia_tipo_nombre="Permiso con goce de sueldo",
        es_feriado=False,
    )

    assert resumen["estado"] == "checada_en_ausencia"
    assert resumen["minutos_trabajados"] == 660
    assert resumen["minutos_extra"] == 0
    assert "Permiso con goce de sueldo" in resumen["observaciones"]


def test_entry_without_exit_inside_window_marks_en_curso():
    schedule = ScheduleConfig(
        hora_entrada=time(8, 0),
        hora_salida=time(17, 0),
        minutos_programados=480,
        margen_salida_despues_min=360,
    )

    resumen = calcular_resumen_dia(
        checks=[AttendanceCheck(_dt(2026, 5, 12, 8, 5), "0")],
        schedule=schedule,
        tiene_vacaciones=False,
        es_feriado=False,
        fecha_laboral=date(2026, 5, 12),
        now=_dt(2026, 5, 12, 12, 0),
    )

    assert resumen["estado"] == "en_curso"
    assert resumen["primera_entrada"] == _dt(2026, 5, 12, 8, 5)
    assert resumen["ultima_salida"] is None
    assert resumen["observaciones"] == "Sin salida registrada"


def test_entry_without_exit_after_window_marks_incompleto():
    schedule = ScheduleConfig(
        hora_entrada=time(8, 0),
        hora_salida=time(17, 0),
        minutos_programados=480,
        margen_salida_despues_min=360,
    )

    resumen = calcular_resumen_dia(
        checks=[AttendanceCheck(_dt(2026, 5, 12, 8, 5), "0")],
        schedule=schedule,
        tiene_vacaciones=False,
        es_feriado=False,
        fecha_laboral=date(2026, 5, 12),
        now=_dt(2026, 5, 12, 23, 30),
    )

    assert resumen["estado"] == "incompleto"
    assert resumen["ultima_salida"] is None
    assert resumen["observaciones"] == "Sin salida registrada"


def test_missing_exit_never_marks_asistencia():
    schedule = ScheduleConfig(
        hora_entrada=time(8, 0),
        hora_salida=time(17, 0),
        minutos_programados=480,
        margen_salida_despues_min=360,
    )

    resumen = calcular_resumen_dia(
        checks=[
            AttendanceCheck(_dt(2026, 5, 12, 8, 5), "0"),
            AttendanceCheck(_dt(2026, 5, 12, 10, 0), "0"),
        ],
        schedule=schedule,
        tiene_vacaciones=False,
        es_feriado=False,
        fecha_laboral=date(2026, 5, 12),
        now=_dt(2026, 5, 12, 23, 30),
    )

    assert resumen["estado"] == "incompleto"
    assert resumen["ultima_salida"] is None
