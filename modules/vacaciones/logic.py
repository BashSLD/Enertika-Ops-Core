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
    ajuste_dias: int = 0,
    meses_expiracion: int = 18,
) -> list[dict]:
    """
    Genera todos los períodos de vacaciones completados + el próximo.
    Un período se genera en cada aniversario (fecha_contratacion + N años).
    Solo se incluyen períodos con fecha_aniversario <= hoy + 1 año.
    El ajuste manual de RH se aplica al período más reciente.
    """
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
) -> list[dict]:
    """
    Devuelve los períodos enriquecidos con saldo, alertas y bandera de expirado.
    consumos: [{num_periodo, dias_consumidos}]
    """
    from core.timezone import today_mx

    hoy = today_mx()
    consumo_por_periodo: dict[int, int] = {}
    for c in consumos:
        n = c["num_periodo"]
        consumo_por_periodo[n] = consumo_por_periodo.get(n, 0) + c["dias_consumidos"]

    resultado: list[dict] = []
    for p in periodos:
        n = p["num_periodo"]
        usados = consumo_por_periodo.get(n, 0)
        restantes = p["dias_otorgados"] - usados
        fecha_exp = p["fecha_expiracion"]
        dias_para_exp = (fecha_exp - hoy).days if not p["es_proximo"] else None
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
    # Solo períodos disponibles (no futuros, no expirados, con saldo > 0), ordenados por expiración
    disponibles = sorted(
        [p for p in periodos_con_saldo if not p.get("es_proximo") and not p.get("expirado") and p["dias_restantes"] > 0],
        key=lambda p: p["fecha_expiracion"],
    )
    resultado: list[dict] = []
    pendiente = dias_solicitados

    for p in disponibles:
        if pendiente <= 0:
            break
        tomar = min(pendiente, p["dias_restantes"])
        resultado.append({
            "num_periodo": p["num_periodo"],
            "dias_consumir": tomar,
            "fecha_aniversario_periodo": p["fecha_aniversario"],
        })
        pendiente -= tomar

    if pendiente > 0:
        # Adelanto: usar el período más reciente (incluye futuros próximos)
        candidatos = sorted(
            [p for p in periodos_con_saldo if not p.get("expirado")],
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
    dias_liberados = floor(dias_proximo_periodo * porcentaje_liberacion / 100) if semestre_activo else 0
    dias_hasta_semestre = min(dias_totales, max(0, (fecha_semestre - ultimo_aniversario).days))
    semestre_pct = round((dias_hasta_semestre / dias_totales) * 100, 1)

    return {
        "fecha_semestre": fecha_semestre,
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
