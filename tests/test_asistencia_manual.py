from __future__ import annotations

from datetime import date, datetime, time
from types import SimpleNamespace
from uuid import uuid4

import pytest

from modules.asistencia import service as asistencia_service
from modules.asistencia.logic import MX_TZ, ScheduleConfig, build_labor_window
from modules.asistencia.service import (
    _clasificar_huecos_biotime,
    _parse_manual_datetime,
    _validar_fechas_manual,
    _validar_solicitud_vs_huecos,
    _validar_tiempos_manual,
)


def _dt(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=MX_TZ)


def _schedule(entrada: time = time(8, 0), salida: time = time(17, 0)) -> ScheduleConfig:
    return ScheduleConfig(
        hora_entrada=entrada,
        hora_salida=salida,
        minutos_programados=480,
        margen_entrada_antes_min=120,
        margen_salida_despues_min=240,
        cruza_medianoche=salida < entrada,
    )


def _window(fecha_laboral: date, entrada: time = time(8, 0), salida: time = time(17, 0)):
    return build_labor_window(fecha_laboral, _schedule(entrada, salida))


def _patch_clock(monkeypatch, *, today: date, now: datetime | None = None) -> None:
    monkeypatch.setattr(asistencia_service, "today_mx", lambda: today)
    monkeypatch.setattr(asistencia_service, "now_mx", lambda: now or _dt(today.year, today.month, today.day, 12))


def test_parse_manual_datetime_uses_mx_timezone():
    parsed = _parse_manual_datetime(date(2026, 6, 30), "08:15")

    assert parsed == _dt(2026, 6, 30, 8, 15)


def test_manual_fecha_laboral_retroactiva(monkeypatch):
    _patch_clock(monkeypatch, today=date(2026, 6, 30))

    with pytest.raises(ValueError, match="7"):
        _validar_fechas_manual(
            fecha_laboral=date(2026, 6, 22),
            fecha_entrada=date(2026, 6, 22),
            fecha_salida=date(2026, 6, 22),
            solicita_entrada=True,
            solicita_salida=True,
            entrada_tiempo=_dt(2026, 6, 22, 8),
            salida_tiempo=_dt(2026, 6, 22, 17),
            dias_retroactivo=7,
            max_horas=16,
            labor_window=_window(date(2026, 6, 22)),
            huecos={"entrada_real": None, "salida_real": None},
            schedule=_schedule(),
        )


def test_manual_fecha_laboral_futura(monkeypatch):
    _patch_clock(monkeypatch, today=date(2026, 6, 30))

    with pytest.raises(ValueError, match="futura"):
        _validar_fechas_manual(
            fecha_laboral=date(2026, 7, 1),
            fecha_entrada=date(2026, 7, 1),
            fecha_salida=date(2026, 7, 1),
            solicita_entrada=True,
            solicita_salida=True,
            entrada_tiempo=_dt(2026, 7, 1, 8),
            salida_tiempo=_dt(2026, 7, 1, 17),
            dias_retroactivo=7,
            max_horas=16,
            labor_window=_window(date(2026, 7, 1)),
            huecos={"entrada_real": None, "salida_real": None},
            schedule=_schedule(),
        )


def test_manual_entrada_salida_mismo_dia(monkeypatch):
    _patch_clock(monkeypatch, today=date(2026, 6, 30), now=_dt(2026, 6, 30, 23))

    _validar_fechas_manual(
        fecha_laboral=date(2026, 6, 30),
        fecha_entrada=date(2026, 6, 30),
        fecha_salida=date(2026, 6, 30),
        solicita_entrada=True,
        solicita_salida=True,
        entrada_tiempo=_dt(2026, 6, 30, 8),
        salida_tiempo=_dt(2026, 6, 30, 17),
        dias_retroactivo=7,
        max_horas=16,
        labor_window=_window(date(2026, 6, 30)),
        huecos={"entrada_real": None, "salida_real": None},
        schedule=_schedule(),
    )


def test_manual_entrada_salida_cruza_medianoche(monkeypatch):
    fecha_laboral = date(2026, 6, 30)
    window = _window(fecha_laboral, entrada=time(20, 0), salida=time(5, 0))
    _patch_clock(monkeypatch, today=date(2026, 7, 1), now=_dt(2026, 7, 1, 12))

    _validar_fechas_manual(
        fecha_laboral=fecha_laboral,
        fecha_entrada=fecha_laboral,
        fecha_salida=date(2026, 7, 1),
        solicita_entrada=True,
        solicita_salida=True,
        entrada_tiempo=_dt(2026, 6, 30, 20),
        salida_tiempo=_dt(2026, 7, 1, 1),
        dias_retroactivo=7,
        max_horas=16,
        labor_window=window,
        huecos={"entrada_real": None, "salida_real": None},
        schedule=_schedule(time(20, 0), time(5, 0)),
    )


def test_manual_rechaza_salida_anterior_mensaje_exacto(monkeypatch):
    _patch_clock(monkeypatch, today=date(2026, 6, 30), now=_dt(2026, 6, 30, 23))

    with pytest.raises(
        ValueError,
        match="La hora de salida es anterior a la entrada. Revisa la fecha y hora correcta.",
    ):
        _validar_fechas_manual(
            fecha_laboral=date(2026, 6, 30),
            fecha_entrada=date(2026, 6, 30),
            fecha_salida=date(2026, 6, 30),
            solicita_entrada=True,
            solicita_salida=True,
            entrada_tiempo=_dt(2026, 6, 30, 17),
            salida_tiempo=_dt(2026, 6, 30, 8),
            dias_retroactivo=7,
            max_horas=16,
            labor_window=_window(date(2026, 6, 30)),
            huecos={"entrada_real": None, "salida_real": None},
            schedule=_schedule(),
        )


def test_manual_aprobacion_valida_con_entrada_real_actual(monkeypatch):
    _patch_clock(monkeypatch, today=date(2026, 6, 30), now=_dt(2026, 6, 30, 23))

    with pytest.raises(
        ValueError,
        match="La hora de salida es anterior a la entrada. Revisa la fecha y hora correcta.",
    ):
        _validar_tiempos_manual(
            solicita_entrada=False,
            solicita_salida=True,
            entrada_tiempo=None,
            salida_tiempo=_dt(2026, 6, 30, 17),
            max_horas=16,
            labor_window=_window(date(2026, 6, 30)),
            huecos={
                "entrada_real": _dt(2026, 6, 30, 18),
                "salida_real": None,
            },
            schedule=_schedule(),
        )


def test_clasificar_huecos_sin_checks_solicita_ambas():
    huecos = _clasificar_huecos_biotime([])

    assert huecos["falta_entrada"] is True
    assert huecos["falta_salida"] is True
    assert huecos["bloqueado"] is False


def test_clasificar_huecos_entrada_real_sin_salida():
    huecos = _clasificar_huecos_biotime([
        {"check_time": _dt(2026, 6, 30, 8), "punch_state": "0", "es_manual": False}
    ])

    assert huecos["falta_entrada"] is False
    assert huecos["falta_salida"] is True


def test_clasificar_huecos_salida_real_sin_entrada():
    huecos = _clasificar_huecos_biotime([
        {"check_time": _dt(2026, 6, 30, 17), "punch_state": "1", "es_manual": False}
    ])

    assert huecos["falta_entrada"] is True
    assert huecos["falta_salida"] is False


def test_clasificar_huecos_entrada_y_salida_reales_bloquea_solicitud():
    huecos = _clasificar_huecos_biotime([
        {"check_time": _dt(2026, 6, 30, 8), "punch_state": "0", "es_manual": False},
        {"check_time": _dt(2026, 6, 30, 17), "punch_state": "1", "es_manual": False},
    ])

    assert huecos["falta_entrada"] is False
    assert huecos["falta_salida"] is False
    with pytest.raises(ValueError, match="entrada y salida"):
        _validar_solicitud_vs_huecos(
            solicita_entrada=True,
            solicita_salida=True,
            huecos=huecos,
        )


def test_clasificar_huecos_ambiguos_bloquea():
    huecos = _clasificar_huecos_biotime([
        {"check_time": _dt(2026, 6, 30, 8), "punch_state": None, "es_manual": False}
    ])

    assert huecos["bloqueado"] is True
    with pytest.raises(ValueError, match="ambiguas"):
        _validar_solicitud_vs_huecos(
            solicita_entrada=True,
            solicita_salida=True,
            huecos=huecos,
        )


def test_clasificar_huecos_duplicado_solo_entrada_no_bloquea():
    huecos = _clasificar_huecos_biotime([
        {"check_time": _dt(2026, 6, 30, 7, 55), "punch_state": "Entrada", "es_manual": False},
        {"check_time": _dt(2026, 6, 30, 8), "punch_state": "Entrada", "es_manual": False},
        {"check_time": _dt(2026, 6, 30, 17), "punch_state": "Salida", "es_manual": False},
    ])

    assert huecos["bloqueado"] is False
    assert huecos["entrada_real"] == _dt(2026, 6, 30, 7, 55)
    assert huecos["salida_real"] == _dt(2026, 6, 30, 17)


def test_clasificar_huecos_duplicado_solo_salida_no_bloquea():
    huecos = _clasificar_huecos_biotime([
        {"check_time": _dt(2026, 6, 30, 8), "punch_state": "Entrada", "es_manual": False},
        {"check_time": _dt(2026, 6, 30, 17), "punch_state": "Salida", "es_manual": False},
        {"check_time": _dt(2026, 6, 30, 17, 5), "punch_state": "Salida", "es_manual": False},
    ])

    assert huecos["bloqueado"] is False
    assert huecos["entrada_real"] == _dt(2026, 6, 30, 8)
    assert huecos["salida_real"] == _dt(2026, 6, 30, 17, 5)


def test_clasificar_huecos_ambos_duplicados_bloquea():
    huecos = _clasificar_huecos_biotime([
        {"check_time": _dt(2026, 6, 30, 8), "punch_state": "Entrada", "es_manual": False},
        {"check_time": _dt(2026, 6, 30, 9), "punch_state": "Entrada", "es_manual": False},
        {"check_time": _dt(2026, 6, 30, 17), "punch_state": "Salida", "es_manual": False},
        {"check_time": _dt(2026, 6, 30, 18), "punch_state": "Salida", "es_manual": False},
    ])

    assert huecos["bloqueado"] is True


def test_clasificar_huecos_ignora_estado_de_descanso():
    huecos = _clasificar_huecos_biotime([
        {"check_time": _dt(2026, 6, 30, 8), "punch_state": "Entrada", "es_manual": False},
        {"check_time": _dt(2026, 6, 30, 13), "punch_state": "Inicio de Descanso", "es_manual": False},
        {"check_time": _dt(2026, 6, 30, 17), "punch_state": "Salida", "es_manual": False},
    ])

    assert huecos["bloqueado"] is False
    assert huecos["entrada_real"] == _dt(2026, 6, 30, 8)
    assert huecos["salida_real"] == _dt(2026, 6, 30, 17)


@pytest.mark.asyncio
async def test_get_equipo_ids_rrhh_viewer_sin_equipo_no_aprueba(monkeypatch):
    user_id = uuid4()

    async def fake_ids(_conn, _user_id):
        return []

    monkeypatch.setattr(asistencia_service, "user_has_module_access", lambda *_args: False)
    monkeypatch.setattr(
        asistencia_service.vacaciones_db,
        "get_empleados_donde_soy_jefe",
        fake_ids,
    )
    monkeypatch.setattr(
        asistencia_service.vacaciones_db,
        "get_empleados_donde_soy_aprobador",
        fake_ids,
    )

    ids = await asistencia_service.get_equipo_ids(SimpleNamespace(), user_id, {"module_roles": {"rrhh": "viewer"}})

    assert ids == []
