from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

MX_TZ = ZoneInfo("America/Mexico_City")

IN_STATES = {"0", "i", "in", "entrada", "check in"}
OUT_STATES = {"1", "o", "out", "salida", "check out"}


@dataclass(frozen=True)
class AttendanceCheck:
    check_time: datetime
    punch_state: str | None = None


@dataclass(frozen=True)
class ScheduleConfig:
    hora_entrada: time | None
    hora_salida: time | None
    minutos_programados: int
    es_laboral: bool = True
    cruza_medianoche: bool = False
    margen_entrada_antes_min: int = 0
    margen_salida_despues_min: int = 0
    tolerancia_extra_min: int = 0
    descuento_comida_min: int = 0


@dataclass(frozen=True)
class LaborWindow:
    start: datetime
    end: datetime


def ensure_mx(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=MX_TZ)
    return dt.astimezone(MX_TZ)


def build_labor_window(fecha_laboral: date, schedule: ScheduleConfig | None) -> LaborWindow:
    if not schedule or not schedule.es_laboral or not schedule.hora_entrada or not schedule.hora_salida:
        start = datetime.combine(fecha_laboral, time.min, tzinfo=MX_TZ)
        return LaborWindow(start=start, end=start + timedelta(days=1))

    entrada = datetime.combine(fecha_laboral, schedule.hora_entrada, tzinfo=MX_TZ)
    salida = datetime.combine(fecha_laboral, schedule.hora_salida, tzinfo=MX_TZ)
    if schedule.cruza_medianoche or schedule.hora_salida <= schedule.hora_entrada:
        salida += timedelta(days=1)

    return LaborWindow(
        start=entrada - timedelta(minutes=schedule.margen_entrada_antes_min),
        end=salida + timedelta(minutes=schedule.margen_salida_despues_min),
    )


def is_in_state(punch_state: str | None) -> bool:
    return (punch_state or "").strip().lower() in IN_STATES


def is_out_state(punch_state: str | None) -> bool:
    return (punch_state or "").strip().lower() in OUT_STATES


def calcular_resumen_dia(
    *,
    checks: list[AttendanceCheck],
    schedule: ScheduleConfig | None,
    tiene_vacaciones: bool,
    es_feriado: bool,
) -> dict:
    checks_ordenados = sorted(checks, key=lambda c: ensure_mx(c.check_time))
    observaciones: list[str] = []

    if not checks_ordenados:
        if tiene_vacaciones:
            estado = "vacaciones"
        elif es_feriado:
            estado = "feriado"
        elif schedule and not schedule.es_laboral:
            estado = "descanso"
        elif schedule is None:
            estado = "sin_horario"
        else:
            estado = "sin_registro"

        return {
            "estado": estado,
            "primera_entrada": None,
            "ultima_salida": None,
            "minutos_trabajados": 0,
            "minutos_programados": _minutos_programados(schedule, es_feriado),
            "minutos_extra": 0,
            "observaciones": None,
        }

    entradas = [c for c in checks_ordenados if is_in_state(c.punch_state)]
    salidas = [c for c in checks_ordenados if is_out_state(c.punch_state)]

    primera = ensure_mx(entradas[0].check_time if entradas else checks_ordenados[0].check_time)
    ultima = ensure_mx(salidas[-1].check_time if salidas else checks_ordenados[-1].check_time)

    if not entradas:
        observaciones.append("Sin estado de entrada confiable")
    if not salidas:
        observaciones.append("Sin estado de salida confiable")
    if schedule is None:
        observaciones.append("Sin horario configurado")
    if tiene_vacaciones:
        observaciones.append("Tiene vacaciones aprobadas y tambien registro checadas")

    minutos_trabajados = 0
    if ultima > primera:
        minutos_trabajados = int((ultima - primera).total_seconds() // 60)
        descuento = schedule.descuento_comida_min if schedule else 0
        minutos_trabajados = max(0, minutos_trabajados - descuento)

    minutos_programados = _minutos_programados(schedule, es_feriado)

    if tiene_vacaciones:
        estado = "checada_en_vacaciones"
    elif len(checks_ordenados) < 2 or ultima <= primera:
        estado = "incompleto"
    elif schedule is None:
        estado = "sin_horario"
    else:
        estado = "asistencia"

    minutos_extra = _calcular_extra(
        minutos_trabajados=minutos_trabajados,
        minutos_programados=minutos_programados,
        schedule=schedule,
        es_feriado=es_feriado,
        tiene_vacaciones=tiene_vacaciones,
    )

    return {
        "estado": estado,
        "primera_entrada": primera,
        "ultima_salida": ultima,
        "minutos_trabajados": minutos_trabajados,
        "minutos_programados": minutos_programados,
        "minutos_extra": minutos_extra,
        "observaciones": "; ".join(observaciones) if observaciones else None,
    }


def _minutos_programados(schedule: ScheduleConfig | None, es_feriado: bool) -> int:
    if not schedule or not schedule.es_laboral or es_feriado:
        return 0
    return max(0, schedule.minutos_programados)


def _calcular_extra(
    *,
    minutos_trabajados: int,
    minutos_programados: int,
    schedule: ScheduleConfig | None,
    es_feriado: bool,
    tiene_vacaciones: bool,
) -> int:
    if minutos_trabajados <= 0 or tiene_vacaciones:
        return 0
    if es_feriado or (schedule and not schedule.es_laboral):
        return minutos_trabajados
    if not schedule:
        return 0
    return max(0, minutos_trabajados - minutos_programados - schedule.tolerancia_extra_min)
