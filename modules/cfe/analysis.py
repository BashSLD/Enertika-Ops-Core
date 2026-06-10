from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Optional

from modules.shared.services.cfe.excel import construir_datos_recibo_cfe
from modules.shared.services.cfe.schemas import CfeReceipt

_ANALISIS_BASELINE_PERIODOS = 12
_ALERTA_FACTOR_POTENCIA_MIN = 90.0
_ALERTA_DESVIACION_ALTA_PCT = 15.0
_ALERTA_DEMANDA_ALTA_PCT = 10.0
_ALERTA_COSTO_KWH_ALTO_PCT = 10.0
_ALERTA_CONSUMO_PUNTA_PCT = 25.0
_MESES_CORTOS = (
    "Ene",
    "Feb",
    "Mar",
    "Abr",
    "May",
    "Jun",
    "Jul",
    "Ago",
    "Sep",
    "Oct",
    "Nov",
    "Dic",
)
_ANALISIS_METRICAS = (
    {"key": "consumo", "label": "Consumo", "unidad": "kWh", "decimales": 0},
    {"key": "total_facturado", "label": "Total facturado", "unidad": "MXN", "decimales": 0},
    {"key": "costo_kwh", "label": "Costo/kWh", "unidad": "MXN/kWh", "decimales": 2},
    {"key": "kwmax", "label": "Demanda máxima", "unidad": "kW", "decimales": 1},
    {"key": "fp", "label": "Factor de potencia", "unidad": "%", "decimales": 2},
    {"key": "consumo_punta", "label": "Consumo punta", "unidad": "kWh", "decimales": 0},
)


def construir_analisis_recibos(
    servicio: dict,
    recibos: Sequence[tuple[dict, CfeReceipt]],
) -> dict[str, Any]:
    periodos = []
    for descarga, recibo in recibos:
        periodo = _construir_periodo_analisis(descarga, recibo)
        if periodo:
            periodos.append(periodo)

    periodos.sort(key=lambda item: item["periodo_key"])
    if not periodos:
        return analisis_sin_datos(
            servicio,
            "Los XMLs descargados no contienen periodos válidos para analizar.",
        )

    ultimo = periodos[-1]
    historico = periodos[:-1]
    baseline = historico[-_ANALISIS_BASELINE_PERIODOS:]
    periodo_anterior = historico[-1] if historico else None
    mismo_mes_anio_anterior = _buscar_mismo_mes_anio_anterior(ultimo, periodos)

    return {
        "servicio": servicio,
        "hay_datos": True,
        "mensaje": "",
        "ultimo": ultimo,
        "periodos": periodos,
        "total_periodos": len(periodos),
        "baseline_periodos": len(baseline),
        "comparativos": _construir_comparativos(
            ultimo,
            periodo_anterior,
            baseline,
            mismo_mes_anio_anterior,
        ),
        "graficas": _construir_graficas(periodos),
        "alertas": _construir_alertas(ultimo, baseline),
        "ahorro_estimado": _construir_ahorro_estimado(ultimo, baseline),
        "historial_extendido": _historial_extendido(periodos),
    }


def analisis_sin_datos(servicio: dict, mensaje: str) -> dict[str, Any]:
    return {
        "servicio": servicio,
        "hay_datos": False,
        "mensaje": mensaje,
        "ultimo": None,
        "periodos": [],
        "total_periodos": 0,
        "baseline_periodos": 0,
        "comparativos": [],
        "graficas": {"labels": [], "metricas": {}},
        "alertas": [],
        "ahorro_estimado": {"disponible": False},
        "historial_extendido": {"disponible": False, "items": []},
    }


def filtrar_xmls_completados(descargas: Sequence[dict]) -> list[dict]:
    rows = [
        row for row in descargas
        if row.get("tipo") == "xml"
        and row.get("estatus") == "completado"
        and _periodo_key(row.get("periodo")) is not None
    ]
    return sorted(rows, key=lambda row: _periodo_key(row.get("periodo")) or (0, 0))


def _construir_periodo_analisis(descarga: dict, recibo: CfeReceipt) -> Optional[dict[str, Any]]:
    periodo = str(descarga.get("periodo") or "")
    periodo_key = _periodo_key(periodo)
    if periodo_key is None:
        return None

    datos = construir_datos_recibo_cfe(recibo)
    consumo = _numero_analisis(datos.get("consumo"))
    total_subtotal = _numero_analisis(datos.get("total"))
    total_facturado = _numero_analisis(recibo.get("cfdi", {}).get("total"))
    if total_facturado is None:
        total_facturado = total_subtotal

    consumo_punta = _numero_analisis(datos.get("consumo_punta"))
    observaciones = str(datos.get("observaciones") or "")
    datos_faltantes = [
        item.strip()
        for item in observaciones.split(";")
        if item.strip().startswith("Falta")
    ]

    return {
        "periodo": periodo,
        "periodo_key": periodo_key,
        "label": _periodo_label(periodo),
        "fecha_emision": recibo.get("cfdi", {}).get("fecha_emision"),
        "tarifa": recibo.get("servicio", {}).get("tarifa") or "N/D",
        "tipo_tarifa": recibo.get("servicio", {}).get("tipo_tarifa") or "N/D",
        "archivo": recibo.get("archivo"),
        "consumo": consumo,
        "consumo_base": _numero_analisis(datos.get("consumo_base")),
        "consumo_intermedio": _numero_analisis(datos.get("consumo_intermedio")),
        "consumo_punta": consumo_punta,
        "consumo_punta_pct": _porcentaje(consumo_punta, consumo),
        "total_facturado": total_facturado,
        "subtotal": total_subtotal,
        "iva": _numero_analisis(recibo.get("cfdi", {}).get("iva")),
        "costo_kwh": _dividir(total_facturado, consumo),
        "kwmax": _numero_analisis(datos.get("kwmax")),
        "kw_cap": _numero_analisis(datos.get("kw_cap")),
        "kw_dist": _numero_analisis(datos.get("kw_dist")),
        "fp": _numero_analisis(datos.get("fp")),
        "reactiva": _numero_analisis(datos.get("reactiva")),
        "penalizacion_fp": _numero_analisis(datos.get("penalizacion_fp")),
        "componentes": _componentes_principales(recibo, total_facturado),
        "perfil_horario": _perfil_horario(datos),
        "observaciones": observaciones,
        "datos_faltantes": datos_faltantes,
        "historial_embebido": recibo.get("historial") or [],
    }


def _componentes_principales(recibo: CfeReceipt, total: Optional[float]) -> list[dict[str, Any]]:
    componentes = []
    for componente in recibo.get("componentes_tarifarios") or []:
        importe = _numero_analisis(componente.get("importe"))
        if importe is None:
            continue
        componentes.append({
            "codigo": componente.get("codigo") or "",
            "nombre": componente.get("nombre") or componente.get("codigo") or "N/D",
            "importe": importe,
            "porcentaje": _porcentaje(importe, total),
        })
    return sorted(componentes, key=lambda item: abs(item["importe"]), reverse=True)[:8]


def _perfil_horario(datos: dict[str, Any]) -> list[dict[str, Any]]:
    perfil = [
        ("Base", "consumo_base", "coste_energia_base"),
        ("Intermedia", "consumo_intermedio", "coste_energia_intermedia"),
        ("Punta", "consumo_punta", "coste_energia_punta"),
    ]
    items = []
    for nombre, consumo_key, costo_key in perfil:
        consumo = _numero_analisis(datos.get(consumo_key))
        costo = _numero_analisis(datos.get(costo_key))
        if consumo is not None or costo is not None:
            items.append({
                "nombre": nombre,
                "consumo": consumo,
                "costo": costo,
            })
    return items


def _construir_comparativos(
    ultimo: dict[str, Any],
    periodo_anterior: Optional[dict[str, Any]],
    baseline: Sequence[dict[str, Any]],
    mismo_mes_anio_anterior: Optional[dict[str, Any]],
) -> list[dict[str, Any]]:
    comparativos = []
    for metrica in _ANALISIS_METRICAS:
        key = metrica["key"]
        actual = _numero_analisis(ultimo.get(key))
        promedio_12 = _promedio(baseline, key)
        comparativos.append({
            **metrica,
            "actual": actual,
            "anterior": _comparar(actual, _valor_periodo(periodo_anterior, key)),
            "promedio_12": {
                **_comparar(actual, promedio_12),
                "periodos": len(baseline),
            },
            "anio_anterior": _comparar(actual, _valor_periodo(mismo_mes_anio_anterior, key)),
        })
    return comparativos


def _construir_graficas(periodos: Sequence[dict[str, Any]]) -> dict[str, Any]:
    ultimos_12 = periodos[-_ANALISIS_BASELINE_PERIODOS:]
    ultimo = periodos[-1]
    return {
        "labels": [item["label"] for item in periodos],
        "metricas": {
            metrica["key"]: {
                "label": metrica["label"],
                "unidad": metrica["unidad"],
                "decimales": metrica["decimales"],
                "data": [_numero_analisis(item.get(metrica["key"])) for item in periodos],
                "promedio": _promedio(ultimos_12, metrica["key"]),
            }
            for metrica in _ANALISIS_METRICAS
        },
        "perfil_horario": {
            "labels": [item["nombre"] for item in ultimo["perfil_horario"]],
            "consumo": [item["consumo"] for item in ultimo["perfil_horario"]],
            "costo": [item["costo"] for item in ultimo["perfil_horario"]],
        },
        "desglose": {
            "labels": [item["nombre"] for item in ultimo["componentes"]],
            "data": [item["importe"] for item in ultimo["componentes"]],
        },
    }


def _construir_alertas(ultimo: dict[str, Any], baseline: Sequence[dict[str, Any]]) -> list[dict[str, str]]:
    alertas: list[dict[str, str]] = []
    fp = _numero_analisis(ultimo.get("fp"))
    if fp is not None and fp < _ALERTA_FACTOR_POTENCIA_MIN:
        alertas.append({
            "tipo": "danger",
            "titulo": "Factor de potencia bajo",
            "detalle": f"El último recibo está en {fp:.2f}%, por debajo del umbral de {_ALERTA_FACTOR_POTENCIA_MIN:.0f}%.",
        })

    _agregar_alerta_desviacion(
        alertas, ultimo, baseline, "total_facturado", "Total facturado",
        _ALERTA_DESVIACION_ALTA_PCT,
    )
    _agregar_alerta_desviacion(
        alertas, ultimo, baseline, "consumo", "Consumo",
        _ALERTA_DESVIACION_ALTA_PCT,
    )
    _agregar_alerta_desviacion(
        alertas, ultimo, baseline, "kwmax", "Demanda máxima",
        _ALERTA_DEMANDA_ALTA_PCT,
    )
    _agregar_alerta_desviacion(
        alertas, ultimo, baseline, "costo_kwh", "Costo/kWh",
        _ALERTA_COSTO_KWH_ALTO_PCT,
    )

    punta_pct = _numero_analisis(ultimo.get("consumo_punta_pct"))
    if punta_pct is not None and punta_pct >= _ALERTA_CONSUMO_PUNTA_PCT:
        alertas.append({
            "tipo": "warning",
            "titulo": "Consumo punta elevado",
            "detalle": f"La punta representa {punta_pct:.1f}% del consumo del último periodo.",
        })

    if ultimo.get("datos_faltantes"):
        faltantes = ", ".join(ultimo["datos_faltantes"][:4])
        alertas.append({
            "tipo": "info",
            "titulo": "Datos incompletos en XML",
            "detalle": f"Faltan datos para algunos cálculos: {faltantes}.",
        })

    if not alertas:
        alertas.append({
            "tipo": "success",
            "titulo": "Sin alertas relevantes",
            "detalle": "El último periodo no rebasa los umbrales principales contra el baseline.",
        })
    return alertas


def _agregar_alerta_desviacion(
    alertas: list[dict[str, str]],
    ultimo: dict[str, Any],
    baseline: Sequence[dict[str, Any]],
    key: str,
    titulo: str,
    umbral_pct: float,
) -> None:
    actual = _numero_analisis(ultimo.get(key))
    referencia = _promedio(baseline, key)
    if actual is None or referencia is None or referencia == 0:
        return

    delta_pct = ((actual - referencia) / abs(referencia)) * 100
    if delta_pct < umbral_pct:
        return

    alertas.append({
        "tipo": "warning",
        "titulo": f"{titulo} arriba del promedio",
        "detalle": f"{delta_pct:.1f}% contra el promedio de {len(baseline)} periodos anteriores.",
    })


def _construir_ahorro_estimado(
    ultimo: dict[str, Any],
    baseline: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    consumo = _numero_analisis(ultimo.get("consumo"))
    total = _numero_analisis(ultimo.get("total_facturado"))
    costo_kwh_baseline = _promedio(baseline, "costo_kwh")
    consumo_baseline = _promedio(baseline, "consumo")

    if consumo is None or total is None or costo_kwh_baseline is None:
        return {
            "disponible": False,
            "periodos_baseline": len(baseline),
        }

    costo_esperado = consumo * costo_kwh_baseline
    ahorro = costo_esperado - total
    variacion_consumo = (
        consumo - consumo_baseline
        if consumo_baseline is not None
        else None
    )
    return {
        "disponible": True,
        "periodos_baseline": len(baseline),
        "costo_kwh_baseline": costo_kwh_baseline,
        "consumo_baseline": consumo_baseline,
        "costo_esperado": costo_esperado,
        "ahorro_estimado": ahorro,
        "ahorro_pct": _porcentaje(ahorro, costo_esperado),
        "variacion_consumo": variacion_consumo,
        "variacion_consumo_pct": _porcentaje(variacion_consumo, consumo_baseline),
    }


def _historial_extendido(periodos: Sequence[dict[str, Any]]) -> dict[str, Any]:
    for periodo in reversed(periodos):
        historial = periodo.get("historial_embebido") or []
        if historial:
            return {
                "disponible": True,
                "origen_periodo": periodo["periodo"],
                "origen_label": periodo["label"],
                "items": historial,
            }
    return {"disponible": False, "items": []}


def _buscar_mismo_mes_anio_anterior(
    ultimo: dict[str, Any],
    periodos: Sequence[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    anio, mes = ultimo["periodo_key"]
    objetivo = (anio - 1, mes)
    for periodo in reversed(periodos):
        if periodo["periodo_key"] == objetivo:
            return periodo
    return None


def _valor_periodo(periodo: Optional[dict[str, Any]], key: str) -> Optional[float]:
    if not periodo:
        return None
    return _numero_analisis(periodo.get(key))


def _comparar(actual: Optional[float], referencia: Optional[float]) -> dict[str, Any]:
    if actual is None or referencia is None:
        return {
            "disponible": False,
            "valor": referencia,
            "delta": None,
            "delta_pct": None,
        }
    delta = actual - referencia
    return {
        "disponible": True,
        "valor": referencia,
        "delta": delta,
        "delta_pct": _porcentaje(delta, abs(referencia)),
    }


def _promedio(periodos: Sequence[dict[str, Any]], key: str) -> Optional[float]:
    valores = [
        valor for valor in (_numero_analisis(periodo.get(key)) for periodo in periodos)
        if valor is not None
    ]
    if not valores:
        return None
    return sum(valores) / len(valores)


def _periodo_key(periodo: Any) -> Optional[tuple[int, int]]:
    if not isinstance(periodo, str):
        return None
    partes = periodo.split("-")
    if len(partes) != 2:
        return None
    try:
        anio = int(partes[0])
        mes = int(partes[1])
    except ValueError:
        return None
    if anio < 2000 or mes < 1 or mes > 12:
        return None
    return anio, mes


def _periodo_label(periodo: str) -> str:
    key = _periodo_key(periodo)
    if key is None:
        return periodo
    anio, mes = key
    return f"{_MESES_CORTOS[mes - 1]}-{str(anio)[-2:]}"


def _numero_analisis(valor: Any) -> Optional[float]:
    if valor is None or valor == "" or valor == "N/A" or isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    try:
        return float(str(valor).replace(",", ""))
    except ValueError:
        return None


def _dividir(numerador: Optional[float], denominador: Optional[float]) -> Optional[float]:
    if numerador is None or denominador in (None, 0):
        return None
    return numerador / denominador


def _porcentaje(valor: Optional[float], total: Optional[float]) -> Optional[float]:
    if valor is None or total in (None, 0):
        return None
    return (valor / total) * 100
