from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

MX_TZ = ZoneInfo("America/Mexico_City")

IN_STATES = {"0", "i", "in", "entrada", "check in"}
OUT_STATES = {"1", "o", "out", "salida", "check out"}
BREAK_STATES = {"inicio de descanso", "fin de descanso", "descanso", "break in", "break out"}


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


def _programmed_bounds(fecha_laboral: date, schedule: ScheduleConfig) -> tuple[datetime, datetime]:
    """Entrada/salida programadas del turno, ajustando la salida si cruza medianoche."""
    entrada = datetime.combine(fecha_laboral, schedule.hora_entrada, tzinfo=MX_TZ)
    salida = datetime.combine(fecha_laboral, schedule.hora_salida, tzinfo=MX_TZ)
    if schedule.cruza_medianoche or schedule.hora_salida < schedule.hora_entrada:
        salida += timedelta(days=1)
    return entrada, salida


def build_labor_window(fecha_laboral: date, schedule: ScheduleConfig | None) -> LaborWindow:
    if not schedule or not schedule.es_laboral or not schedule.hora_entrada or not schedule.hora_salida:
        start = datetime.combine(fecha_laboral, time.min, tzinfo=MX_TZ)
        return LaborWindow(start=start, end=start + timedelta(days=1))

    entrada, salida = _programmed_bounds(fecha_laboral, schedule)

    return LaborWindow(
        start=entrada - timedelta(minutes=schedule.margen_entrada_antes_min),
        end=salida + timedelta(minutes=schedule.margen_salida_despues_min),
    )


def extender_salida_descanso_medianoche(
    checks_dia: list[AttendanceCheck],
    checks_todos: list[AttendanceCheck],
    window: LaborWindow,
    margen_salida_despues_min: int,
) -> tuple[list[AttendanceCheck], AttendanceCheck | None]:
    """Si en un dia de descanso (ventana [medianoche, medianoche+1dia)) hay una entrada sin
    salida posterior dentro de esa ventana, busca la primera checada del dia siguiente dentro
    de `margen_salida_despues_min` contado desde medianoche. Solo la usa como salida si ocurre
    antes de cualquier entrada nueva en ese margen -- nunca se apropia de una jornada nueva ni
    asocia una salida aislada. El resultado (y las horas extra) siguen perteneciendo a la fecha
    de la entrada, ya que solo se extiende `checks_dia` de ese dia.

    Retorna `(checks_dia, prestada)`: `prestada` es la checada tomada del dia siguiente
    (o `None` si no se tomo ninguna) -- el llamador debe excluirla de `checks_todos` al
    procesar ese dia siguiente para no contarla dos veces."""
    if margen_salida_despues_min <= 0:
        return checks_dia, None
    ordenados = sorted(checks_dia, key=lambda c: ensure_mx(c.check_time))
    entradas = [c for c in ordenados if is_in_state(c.punch_state)]
    if not entradas:
        return checks_dia, None

    ultima_entrada = ensure_mx(entradas[-1].check_time)
    if any(
        is_out_state(c.punch_state) and ensure_mx(c.check_time) > ultima_entrada
        for c in ordenados
    ):
        # La ultima entrada ya tiene su propia salida el mismo dia -- no hay nada que extender.
        return checks_dia, None
    margen_fin = window.end + timedelta(minutes=margen_salida_despues_min)
    candidatos = sorted(
        (c for c in checks_todos if window.end <= ensure_mx(c.check_time) < margen_fin),
        key=lambda c: ensure_mx(c.check_time),
    )
    for candidato in candidatos:
        if is_in_state(candidato.punch_state):
            return checks_dia, None
        if is_out_state(candidato.punch_state) and ensure_mx(candidato.check_time) > ultima_entrada:
            return [*checks_dia, candidato], candidato
    return checks_dia, None


def is_in_state(punch_state: str | None) -> bool:
    return (punch_state or "").strip().lower() in IN_STATES


def is_out_state(punch_state: str | None) -> bool:
    return (punch_state or "").strip().lower() in OUT_STATES


def is_break_state(punch_state: str | None) -> bool:
    return (punch_state or "").strip().lower() in BREAK_STATES


def calcular_resumen_dia(
    *,
    checks: list[AttendanceCheck],
    schedule: ScheduleConfig | None,
    tiene_vacaciones: bool,
    tiene_ausencia_justificada: bool | None = None,
    ausencia_tipo_nombre: str | None = None,
    es_feriado: bool = False,
    fecha_laboral: date | None = None,
    now: datetime | None = None,
    min_minutos_he: int = 0,
) -> dict:
    checks_ordenados = sorted(checks, key=lambda c: ensure_mx(c.check_time))
    observaciones: list[str] = []
    if tiene_ausencia_justificada is None:
        tiene_ausencia_justificada = tiene_vacaciones
    ausencia_label = ausencia_tipo_nombre or "Ausencia aprobada"

    if not checks_ordenados:
        if es_feriado:
            estado = "feriado"
        elif schedule and not schedule.es_laboral:
            estado = "descanso"
        elif tiene_vacaciones:
            estado = "vacaciones"
        elif tiene_ausencia_justificada:
            estado = "ausencia"
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
            "observaciones": ausencia_label if tiene_ausencia_justificada and not tiene_vacaciones else None,
        }

    entradas = [c for c in checks_ordenados if is_in_state(c.punch_state)]
    salidas = [c for c in checks_ordenados if is_out_state(c.punch_state)]

    primera = ensure_mx(entradas[0].check_time if entradas else checks_ordenados[0].check_time)
    ultima_salida = ensure_mx(salidas[-1].check_time) if salidas else None

    if not entradas:
        observaciones.append("Sin entrada registrada")
    if not salidas:
        observaciones.append("Sin salida registrada")
    if schedule is None:
        observaciones.append("Sin horario configurado")
    if tiene_vacaciones:
        observaciones.append("Tiene vacaciones aprobadas y tambien registro checadas")
    elif tiene_ausencia_justificada:
        observaciones.append(f"Tiene ausencia aprobada ({ausencia_label}) y tambien registro checadas")

    minutos_trabajados = 0
    if entradas and ultima_salida and ultima_salida > primera:
        minutos_trabajados = int((ultima_salida - primera).total_seconds() // 60)
        descuento = schedule.descuento_comida_min if schedule else 0
        minutos_trabajados = max(0, minutos_trabajados - descuento)

    minutos_programados = _minutos_programados(schedule, es_feriado)

    if tiene_vacaciones:
        estado = "checada_en_vacaciones"
    elif tiene_ausencia_justificada:
        estado = "checada_en_ausencia"
    elif schedule is None and not es_feriado:
        estado = "sin_horario"
    elif not entradas:
        estado = "incompleto"
    elif not salidas:
        estado = "en_curso" if _es_jornada_en_curso(
            fecha_laboral=fecha_laboral,
            schedule=schedule,
            now=now,
        ) else "incompleto"
    elif ultima_salida <= primera:
        estado = "incompleto"
    else:
        estado = "asistencia"

    minutos_extra = _calcular_extra(
        primera_entrada=primera,
        ultima_salida=ultima_salida,
        fecha_laboral=fecha_laboral,
        schedule=schedule,
        minutos_trabajados=minutos_trabajados,
        es_feriado=es_feriado,
        tiene_vacaciones=tiene_vacaciones,
        tiene_ausencia_justificada=tiene_ausencia_justificada,
        min_minutos_he=min_minutos_he,
    )

    return {
        "estado": estado,
        "primera_entrada": primera,
        "ultima_salida": ultima_salida,
        "minutos_trabajados": minutos_trabajados,
        "minutos_programados": minutos_programados,
        "minutos_extra": minutos_extra,
        "observaciones": "; ".join(observaciones) if observaciones else None,
    }


def _es_jornada_en_curso(
    *,
    fecha_laboral: date | None,
    schedule: ScheduleConfig | None,
    now: datetime | None,
) -> bool:
    if not fecha_laboral or not now:
        return False
    if not schedule or not schedule.es_laboral or not schedule.hora_entrada or not schedule.hora_salida:
        return False
    window = build_labor_window(fecha_laboral, schedule)
    current = ensure_mx(now)
    return window.start <= current < window.end


def _minutos_programados(schedule: ScheduleConfig | None, es_feriado: bool) -> int:
    if not schedule or not schedule.es_laboral or es_feriado:
        return 0
    return max(0, schedule.minutos_programados)


def _calcular_extra(
    *,
    primera_entrada: datetime | None,
    ultima_salida: datetime | None,
    fecha_laboral: date | None,
    schedule: ScheduleConfig | None,
    minutos_trabajados: int,
    es_feriado: bool,
    tiene_vacaciones: bool,
    tiene_ausencia_justificada: bool | None = None,
    min_minutos_he: int = 0,
) -> int:
    if tiene_ausencia_justificada is None:
        tiene_ausencia_justificada = tiene_vacaciones
    if (
        tiene_ausencia_justificada
        or not primera_entrada
        or not ultima_salida
        or ultima_salida <= primera_entrada
    ):
        return 0

    if es_feriado or (schedule and not schedule.es_laboral):
        total = minutos_trabajados
    elif not schedule or not schedule.hora_entrada or not schedule.hora_salida or not fecha_laboral:
        return 0
    else:
        entrada_prog, salida_prog = _programmed_bounds(fecha_laboral, schedule)
        tolerancia = timedelta(minutes=schedule.tolerancia_extra_min)
        exceso_entrada = max(0, int(((entrada_prog - tolerancia) - primera_entrada).total_seconds() // 60))
        exceso_salida = max(0, int((ultima_salida - (salida_prog + tolerancia)).total_seconds() // 60))
        total = exceso_entrada + exceso_salida

    return total if total >= min_minutos_he else 0
