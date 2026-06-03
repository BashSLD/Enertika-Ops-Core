from __future__ import annotations

from datetime import date
from math import floor
from typing import Any

from dateutil.relativedelta import relativedelta


def obtener_dias_por_antiguedad(anios_cumplidos: int, catalogo: list[dict]) -> int:
    for row in sorted(catalogo, key=lambda r: r["antiguedad_anios"]):
        fin = row["antiguedad_anios_fin"]
        if anios_cumplidos >= row["antiguedad_anios"] and (fin is None or anios_cumplidos <= fin):
            return row["dias_enertika"]
    # fallback: último registro con fin=NULL
    for row in catalogo:
        if row["antiguedad_anios_fin"] is None:
            return row["dias_enertika"]
    return 0


def calcular_periodos(
    fecha_contratacion: date,
    hoy: date,
    catalogo_dias: list[dict],
    ajuste_dias: int | None = 0,
    meses_expiracion: int = 18,
) -> list[dict]:
    """
    Genera todos los períodos de vacaciones completados + el próximo.
    Un período se genera en cada aniversario (fecha_contratacion + N años).
    Solo se incluyen períodos con fecha_aniversario <= hoy + 1 año.
    El ajuste manual de RH se aplica al período más reciente.
    """
    ajuste_dias = ajuste_dias or 0
    periodos: list[dict] = []
    limite = hoy + relativedelta(years=1)
    num = 1
    while True:
        fecha_aniversario = fecha_contratacion + relativedelta(years=num)
        if fecha_aniversario > limite:
            break
        anios_cumplidos = num
        dias = obtener_dias_por_antiguedad(anios_cumplidos, catalogo_dias)
        fecha_expiracion = fecha_aniversario + relativedelta(months=meses_expiracion)
        periodos.append({
            "num_periodo": num,
            "periodo": str(fecha_aniversario.year),
            "fecha_aniversario": fecha_aniversario,
            "fecha_expiracion": fecha_expiracion,
            "dias_otorgados": dias,
            "es_proximo": fecha_aniversario > hoy,
        })
        num += 1

    # Aplicar ajuste al período más reciente no-futuro
    pasados = [p for p in periodos if not p["es_proximo"]]
    if pasados and ajuste_dias != 0:
        pasados[-1]["dias_otorgados"] = max(0, pasados[-1]["dias_otorgados"] + ajuste_dias)

    return periodos


def calcular_balance(
    periodos: list[dict],
    consumos: list[dict],
    prorrogas: list[dict] | None = None,
) -> list[dict]:
    """
    Devuelve los períodos enriquecidos con saldo, alertas y bandera de expirado.
    consumos: [{num_periodo, dias_consumidos}]
    prorrogas: [{num_periodo, fecha_aniversario_periodo, fecha_expiracion_prorroga, dias_prorrogados}]
    Con prorrogas=None el comportamiento es idéntico al original.
    """
    from core.timezone import today_mx

    hoy = today_mx()
    consumo_por_periodo: dict[int, int] = {}
    for c in consumos:
        n = c["num_periodo"]
        consumo_por_periodo[n] = consumo_por_periodo.get(n, 0) + c["dias_consumidos"]

    prorroga_por_periodo: dict[tuple, dict] = {}
    if prorrogas:
        for pr in prorrogas:
            if pr["fecha_expiracion_prorroga"] >= hoy:
                key = (pr["num_periodo"], pr["fecha_aniversario_periodo"])
                prorroga_por_periodo[key] = pr

    resultado: list[dict] = []
    for p in periodos:
        n = p["num_periodo"]
        usados = consumo_por_periodo.get(n, 0)
        restantes = p["dias_otorgados"] - usados

        prorroga = prorroga_por_periodo.get((n, p["fecha_aniversario"]))
        tiene_prorroga = prorroga is not None
        fecha_exp_original = p["fecha_expiracion"]
        fecha_exp_efectiva = prorroga["fecha_expiracion_prorroga"] if prorroga else fecha_exp_original

        dias_para_exp = (fecha_exp_efectiva - hoy).days if not p["es_proximo"] else None
        expirado = (dias_para_exp is not None and dias_para_exp < 0)
        alerta = (
            not p["es_proximo"]
            and not expirado
            and dias_para_exp is not None
            and dias_para_exp <= 90
            and restantes > 0
        )
        resultado.append({
            **p,
            "dias_usados": usados,
            "dias_restantes": restantes,
            "dias_para_expiracion": dias_para_exp,
            "expirado": expirado,
            "alerta": alerta,
            "tiene_prorroga": tiene_prorroga,
            "fecha_expiracion_original": fecha_exp_original,
            "fecha_expiracion_efectiva": fecha_exp_efectiva,
            "dias_prorrogados": prorroga["dias_prorrogados"] if prorroga else None,
            "dias_restantes_prorrogados": min(restantes, prorroga["dias_prorrogados"]) if prorroga else None,
        })
    return resultado


def asignar_consumo_fifo(
    periodos_con_saldo: list[dict],
    dias_solicitados: int,
) -> list[dict]:
    """
    Distribuye los días solicitados usando FIFO (expira antes = consume primero).
    Permite saldo negativo en el período más reciente (adelanto).
    Retorna [{num_periodo, dias_consumir, fecha_aniversario_periodo}].
    """
    from core.timezone import today_mx

    hoy = today_mx()
    # Solo períodos disponibles (no futuros, no expirados, con saldo > 0), ordenados por expiración efectiva
    def _limite_fifo(p: dict) -> int:
        return p["dias_restantes_prorrogados"] if p.get("tiene_prorroga") else p["dias_restantes"]

    disponibles = sorted(
        [
            p for p in periodos_con_saldo
            if not p.get("es_proximo") and not p.get("expirado") and _limite_fifo(p) > 0
        ],
        key=lambda p: p.get("fecha_expiracion_efectiva", p["fecha_expiracion"]),
    )
    resultado: list[dict] = []
    pendiente = dias_solicitados

    for p in disponibles:
        if pendiente <= 0:
            break
        tomar = min(pendiente, _limite_fifo(p))
        resultado.append({
            "num_periodo": p["num_periodo"],
            "dias_consumir": tomar,
            "fecha_aniversario_periodo": p["fecha_aniversario"],
        })
        pendiente -= tomar

    if pendiente > 0:
        # Adelanto: usar el período más reciente (incluye futuros próximos).
        # Los períodos prorrogados no admiten adelanto — ya tienen un tope fijo.
        candidatos = sorted(
            [p for p in periodos_con_saldo if not p.get("expirado") and not p.get("tiene_prorroga")],
            key=lambda p: p["num_periodo"],
            reverse=True,
        )
        if candidatos:
            ultimo = candidatos[0]
            # Verificar si ya hay entrada para ese período
            existing = next((r for r in resultado if r["num_periodo"] == ultimo["num_periodo"]), None)
            if existing:
                existing["dias_consumir"] += pendiente
            else:
                resultado.append({
                    "num_periodo": ultimo["num_periodo"],
                    "dias_consumir": pendiente,
                    "fecha_aniversario_periodo": ultimo["fecha_aniversario"],
                })

    return resultado


def _ancla_periodo(
    fecha_contratacion: date, hoy: date
) -> tuple[int, date, date, int]:
    anios_cumplidos = relativedelta(hoy, fecha_contratacion).years
    ultimo = fecha_contratacion + relativedelta(years=anios_cumplidos)
    proximo = fecha_contratacion + relativedelta(years=anios_cumplidos + 1)
    dias_totales = (proximo - ultimo).days or 365
    return anios_cumplidos, ultimo, proximo, dias_totales


def calcular_progreso(
    fecha_contratacion: date,
    hoy: date,
    catalogo_dias: list[dict],
) -> dict[str, Any]:
    anios_cumplidos, ultimo_aniversario, proximo_aniversario, dias_totales = _ancla_periodo(fecha_contratacion, hoy)
    dias_transcurridos = (hoy - ultimo_aniversario).days
    dias_proximo = obtener_dias_por_antiguedad(anios_cumplidos + 1, catalogo_dias)
    dias_proporcionales = round((dias_transcurridos / dias_totales) * dias_proximo, 1)
    porcentaje = round((dias_transcurridos / dias_totales) * 100, 1)

    return {
        "dias_transcurridos": dias_transcurridos,
        "dias_totales_anio": dias_totales,
        "dias_proximo_periodo": dias_proximo,
        "dias_proporcionales": dias_proporcionales,
        "porcentaje": min(porcentaje, 100.0),
        "fecha_ultimo_aniversario": ultimo_aniversario,
        "fecha_proximo_aniversario": proximo_aniversario,
        "numero_periodo_actual": anios_cumplidos + 1,
    }


def calcular_semestre_liberado(
    fecha_contratacion: date,
    hoy: date,
    catalogo: list[dict],
    meses_semestre: int = 6,
    porcentaje_liberacion: int = 50,
) -> dict[str, Any]:
    """
    Dias liberados en el hito semestral del periodo actual.
    A los meses_semestre desde el ultimo aniversario se libera porcentaje_liberacion%
    de los dias del siguiente periodo. Aplica a todos los años: año 1→6m, año 2→18m, etc.
    """
    anios_cumplidos, ultimo_aniversario, _, dias_totales = _ancla_periodo(fecha_contratacion, hoy)
    fecha_semestre = ultimo_aniversario + relativedelta(months=meses_semestre)
    semestre_activo = hoy >= fecha_semestre
    dias_proximo_periodo = obtener_dias_por_antiguedad(anios_cumplidos + 1, catalogo)
    dias_a_liberar = floor(dias_proximo_periodo * porcentaje_liberacion / 100)
    dias_liberados = dias_a_liberar if semestre_activo else 0
    dias_hasta_semestre = min(dias_totales, max(0, (fecha_semestre - ultimo_aniversario).days))
    semestre_pct = round((dias_hasta_semestre / dias_totales) * 100, 1)

    return {
        "fecha_semestre": fecha_semestre,
        "dias_a_liberar": dias_a_liberar,
        "dias_liberados": dias_liberados,
        "semestre_activo": semestre_activo,
        "dias_proximo_periodo": dias_proximo_periodo,
        "meses_semestre": meses_semestre,
        "semestre_pct": semestre_pct,
    }


def contar_dias_habiles(inicio: date, fin: date, festivos: set[date]) -> int:
    """Cuenta días hábiles (L-V) en el rango [inicio, fin] excluyendo festivos."""
    count = 0
    current = inicio
    while current <= fin:
        if current.weekday() < 5 and current not in festivos:
            count += 1
        current += relativedelta(days=1)
    return count


def es_dia_habil(fecha: date, festivos: set[date]) -> bool:
    return fecha.weekday() < 5 and fecha not in festivos


def restar_dias_habiles(desde: date, dias: int, festivos: set[date]) -> date:
    current = desde
    restantes = dias
    while restantes > 0:
        current -= relativedelta(days=1)
        if es_dia_habil(current, festivos):
            restantes -= 1
    return current


def hito_recordatorio_aprobacion(fecha_inicio: date, hoy: date, festivos: set[date]) -> str | None:
    """t2 = dos dias habiles antes del inicio, t1 = un dia habil antes. None si no aplica."""
    if hoy >= fecha_inicio or not es_dia_habil(hoy, festivos):
        return None

    t2 = restar_dias_habiles(fecha_inicio, 2, festivos)
    t1 = restar_dias_habiles(fecha_inicio, 1, festivos)
    if hoy >= t1:
        return "t1"
    if hoy >= t2:
        return "t2"
    return None


def siguiente_dia_habil(desde: date, festivos: set[date]) -> date:
    """Primer día hábil (L-V) posterior a `desde`, excluyendo festivos."""
    current = desde + relativedelta(days=1)
    while current.weekday() >= 5 or current in festivos:
        current += relativedelta(days=1)
    return current
