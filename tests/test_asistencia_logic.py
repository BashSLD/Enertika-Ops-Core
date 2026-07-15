from datetime import date, datetime, time

import pytest

from modules.asistencia.logic import (
    AttendanceCheck,
    LaborWindow,
    MX_TZ,
    ScheduleConfig,
    build_labor_window,
    calcular_resumen_dia,
    extender_salida_descanso_medianoche,
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
        fecha_laboral=date(2026, 5, 12),
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
        fecha_laboral=date(2026, 5, 12),
    )

    assert resumen["minutos_trabajados"] == 660
    assert resumen["minutos_programados"] == 480
    # Solo el extremo de salida excede la tolerancia: 19:00 - (17:00+15min) = 105
    assert resumen["minutos_extra"] == 105


@pytest.mark.parametrize(
    "hora_entrada_real,hora_salida_real,extra_esperado",
    [
        ((6, 30), (17, 30), 0),
        ((6, 30), (17, 40), 10),
        ((6, 29), (17, 0), 1),
        ((7, 0), (17, 31), 1),
    ],
)
def test_overtime_symmetric_tolerance_per_extremo(hora_entrada_real, hora_salida_real, extra_esperado):
    schedule = ScheduleConfig(
        hora_entrada=time(7, 0),
        hora_salida=time(17, 0),
        minutos_programados=600,
        tolerancia_extra_min=30,
    )
    checks = [
        AttendanceCheck(_dt(2026, 5, 12, *hora_entrada_real), "0"),
        AttendanceCheck(_dt(2026, 5, 12, *hora_salida_real), "1"),
    ]

    resumen = calcular_resumen_dia(
        checks=checks,
        schedule=schedule,
        tiene_vacaciones=False,
        es_feriado=False,
        fecha_laboral=date(2026, 5, 12),
    )

    assert resumen["minutos_extra"] == extra_esperado


def test_overtime_en_feriado_descuenta_comida_igual_que_minutos_trabajados():
    schedule = ScheduleConfig(
        hora_entrada=time(8, 0),
        hora_salida=time(17, 0),
        minutos_programados=480,
        descuento_comida_min=60,
    )
    checks = [
        AttendanceCheck(_dt(2026, 5, 12, 8, 0), "0"),
        AttendanceCheck(_dt(2026, 5, 12, 17, 0), "1"),
    ]

    resumen = calcular_resumen_dia(
        checks=checks,
        schedule=schedule,
        tiene_vacaciones=False,
        es_feriado=True,
        fecha_laboral=date(2026, 5, 12),
    )

    assert resumen["minutos_trabajados"] == 480
    assert resumen["minutos_extra"] == resumen["minutos_trabajados"]


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


def test_vacaciones_en_descanso_sin_checadas_marca_descanso():
    schedule = ScheduleConfig(
        hora_entrada=time(8, 0),
        hora_salida=time(17, 0),
        minutos_programados=0,
        es_laboral=False,
    )

    resumen = calcular_resumen_dia(
        checks=[],
        schedule=schedule,
        tiene_vacaciones=True,
        es_feriado=False,
    )

    assert resumen["estado"] == "descanso"
    assert resumen["minutos_extra"] == 0


def test_ausencia_en_feriado_sin_checadas_marca_feriado():
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
        ausencia_tipo_nombre="Incapacidad",
        es_feriado=True,
    )

    assert resumen["estado"] == "feriado"
    assert resumen["minutos_extra"] == 0


def test_descanso_con_entrada_y_salida_calcula_asistencia_y_extra():
    schedule = ScheduleConfig(
        hora_entrada=time(8, 0),
        hora_salida=time(17, 0),
        minutos_programados=0,
        es_laboral=False,
    )
    checks = [
        AttendanceCheck(_dt(2026, 5, 16, 9, 0), "0"),
        AttendanceCheck(_dt(2026, 5, 16, 13, 0), "1"),
    ]

    resumen = calcular_resumen_dia(
        checks=checks,
        schedule=schedule,
        tiene_vacaciones=False,
        es_feriado=False,
        fecha_laboral=date(2026, 5, 16),
    )

    assert resumen["estado"] == "asistencia"
    assert resumen["minutos_trabajados"] == 240
    assert resumen["minutos_extra"] == 240


def test_feriado_con_registro_incompleto_marca_incompleto():
    schedule = ScheduleConfig(
        hora_entrada=time(8, 0),
        hora_salida=time(17, 0),
        minutos_programados=480,
    )
    checks = [AttendanceCheck(_dt(2026, 5, 12, 9, 0), "0")]

    resumen = calcular_resumen_dia(
        checks=checks,
        schedule=schedule,
        tiene_vacaciones=False,
        es_feriado=True,
        fecha_laboral=date(2026, 5, 12),
        now=_dt(2026, 5, 12, 23, 30),
    )

    assert resumen["estado"] == "incompleto"


def test_feriado_sin_horario_con_checadas_completas_marca_asistencia_todo_extra():
    checks = [
        AttendanceCheck(_dt(2026, 5, 12, 9, 0), "0"),
        AttendanceCheck(_dt(2026, 5, 12, 14, 0), "1"),
    ]

    resumen = calcular_resumen_dia(
        checks=checks,
        schedule=None,
        tiene_vacaciones=False,
        es_feriado=True,
        fecha_laboral=date(2026, 5, 12),
    )

    assert resumen["estado"] == "asistencia"
    assert resumen["minutos_trabajados"] == 300
    assert resumen["minutos_extra"] == 300
    assert "Sin horario configurado" in resumen["observaciones"]


def test_ausencia_completa_sin_horario_conserva_legacy():
    resumen = calcular_resumen_dia(
        checks=[],
        schedule=None,
        tiene_vacaciones=False,
        tiene_ausencia_justificada=True,
        ausencia_tipo_nombre="Permiso sin goce",
        es_feriado=False,
    )

    assert resumen["estado"] == "ausencia"
    assert resumen["minutos_extra"] == 0


def test_extender_salida_descanso_toma_salida_del_dia_siguiente_dentro_de_margen():
    window = LaborWindow(
        start=_dt(2026, 5, 16, 0, 0),
        end=_dt(2026, 5, 17, 0, 0),
    )
    entrada = AttendanceCheck(_dt(2026, 5, 16, 22, 0), "0")
    salida_siguiente = AttendanceCheck(_dt(2026, 5, 17, 0, 45), "1")
    checks_dia = [entrada]
    checks_todos = [entrada, salida_siguiente]

    resultado, prestada = extender_salida_descanso_medianoche(checks_dia, checks_todos, window, 180)

    assert salida_siguiente in resultado
    assert len(resultado) == 2
    assert prestada is salida_siguiente


def test_extender_salida_descanso_no_toma_salida_fuera_de_margen():
    window = LaborWindow(
        start=_dt(2026, 5, 16, 0, 0),
        end=_dt(2026, 5, 17, 0, 0),
    )
    entrada = AttendanceCheck(_dt(2026, 5, 16, 22, 0), "0")
    salida_tardia = AttendanceCheck(_dt(2026, 5, 17, 4, 0), "1")
    checks_dia = [entrada]
    checks_todos = [entrada, salida_tardia]

    resultado, prestada = extender_salida_descanso_medianoche(checks_dia, checks_todos, window, 180)

    assert resultado == checks_dia
    assert prestada is None


def test_extender_salida_descanso_no_toma_salida_despues_de_nueva_entrada():
    window = LaborWindow(
        start=_dt(2026, 5, 16, 0, 0),
        end=_dt(2026, 5, 17, 0, 0),
    )
    entrada = AttendanceCheck(_dt(2026, 5, 16, 22, 0), "0")
    nueva_entrada = AttendanceCheck(_dt(2026, 5, 17, 0, 30), "0")
    salida_nueva_jornada = AttendanceCheck(_dt(2026, 5, 17, 1, 0), "1")
    checks_dia = [entrada]
    checks_todos = [entrada, nueva_entrada, salida_nueva_jornada]

    resultado, prestada = extender_salida_descanso_medianoche(checks_dia, checks_todos, window, 180)

    assert resultado == checks_dia
    assert prestada is None


def test_extender_salida_descanso_no_hace_nada_si_ya_hay_salida_el_mismo_dia():
    window = LaborWindow(
        start=_dt(2026, 5, 16, 0, 0),
        end=_dt(2026, 5, 17, 0, 0),
    )
    entrada = AttendanceCheck(_dt(2026, 5, 16, 9, 0), "0")
    salida = AttendanceCheck(_dt(2026, 5, 16, 13, 0), "1")
    checks_dia = [entrada, salida]

    resultado, prestada = extender_salida_descanso_medianoche(checks_dia, checks_dia, window, 180)

    assert resultado == checks_dia
    assert prestada is None


def test_extender_salida_descanso_toma_segunda_entrada_pese_a_salida_previa_cerrada():
    """Regresion: un dia de descanso con una primera entrada/salida ya cerrada (ej. visita
    breve) y una SEGUNDA entrada mas tarde que cruza medianoche (ej. llamado nocturno) debe
    seguir intentando tomar prestada la salida del dia siguiente para esa segunda entrada --
    antes del fix, la sola presencia de la primera salida abortaba la extension."""
    window = LaborWindow(
        start=_dt(2026, 5, 16, 0, 0),
        end=_dt(2026, 5, 17, 0, 0),
    )
    entrada_temprana = AttendanceCheck(_dt(2026, 5, 16, 10, 0), "0")
    salida_temprana = AttendanceCheck(_dt(2026, 5, 16, 18, 0), "1")
    entrada_tardia = AttendanceCheck(_dt(2026, 5, 16, 23, 50), "0")
    salida_siguiente = AttendanceCheck(_dt(2026, 5, 17, 0, 45), "1")
    checks_dia = [entrada_temprana, salida_temprana, entrada_tardia]
    checks_todos = [*checks_dia, salida_siguiente]

    resultado, prestada = extender_salida_descanso_medianoche(checks_dia, checks_todos, window, 180)

    assert prestada is salida_siguiente
    assert salida_siguiente in resultado
    assert len(resultado) == 4


def test_descanso_con_salida_al_dia_siguiente_calcula_trabajo_y_extra():
    schedule = ScheduleConfig(
        hora_entrada=time(8, 0),
        hora_salida=time(17, 0),
        minutos_programados=0,
        es_laboral=False,
        margen_salida_despues_min=180,
    )
    window = build_labor_window(date(2026, 5, 16), schedule)
    entrada = AttendanceCheck(_dt(2026, 5, 16, 22, 0), "0")
    salida_siguiente = AttendanceCheck(_dt(2026, 5, 17, 0, 45), "1")
    checks_dia, _prestada = extender_salida_descanso_medianoche(
        [entrada], [entrada, salida_siguiente], window, schedule.margen_salida_despues_min
    )

    resumen = calcular_resumen_dia(
        checks=checks_dia,
        schedule=schedule,
        tiene_vacaciones=False,
        es_feriado=False,
        fecha_laboral=date(2026, 5, 16),
    )

    assert resumen["estado"] == "asistencia"
    assert resumen["minutos_trabajados"] == 165
    assert resumen["minutos_extra"] == 165


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
