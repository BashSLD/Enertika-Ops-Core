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
_METRICAS = (
    {"key": "consumo", "label": "Consumo", "unidad": "kWh", "decimales": 0},
    {"key": "total_facturado", "label": "Total facturado", "unidad": "MXN", "decimales": 0},
    {"key": "costo_kwh", "label": "Costo/kWh", "unidad": "MXN/kWh", "decimales": 2},
    {"key": "kwmax", "label": "Demanda maxima", "unidad": "kW", "decimales": 1},
    {"key": "kw_cap", "label": "KW CAP", "unidad": "kW", "decimales": 1},
    {"key": "kw_dist", "label": "kW DIST", "unidad": "kW", "decimales": 1},
    {"key": "fp", "label": "Factor de potencia", "unidad": "%", "decimales": 2},
    {"key": "consumo_punta", "label": "Consumo punta", "unidad": "kWh", "decimales": 0},
    {"key": "consumo_punta_pct", "label": "Punta", "unidad": "% del consumo", "decimales": 1},
)
_METRICAS_BY_KEY = {metrica["key"]: metrica for metrica in _METRICAS}
# Subtexto contextual bajo ciertos KPIs (no es metrica propia: solo da contexto).
_KPI_SUBTEXTO = {
    "total_facturado": {"label": "Subtotal", "source": "subtotal", "tipo": "dinero", "decimales": 0},
}
_PERFILES_ANALISIS = {
    "GDMTH": {
        "key": "GDMTH",
        "nombre": "GDMTH",
        "descripcion": "Analisis horario con base, intermedia y punta.",
        "kpis": ("total_facturado", "consumo", "costo_kwh", "kwmax", "fp", "consumo_punta_pct"),
        "comparativos": ("consumo", "total_facturado", "costo_kwh", "kwmax", "fp", "consumo_punta"),
        "metricas_grafica": ("consumo", "total_facturado", "costo_kwh", "kwmax"),
        "alertas_desviacion": (
            ("total_facturado", "Total facturado", _ALERTA_DESVIACION_ALTA_PCT),
            ("consumo", "Consumo", _ALERTA_DESVIACION_ALTA_PCT),
            ("kwmax", "Demanda maxima", _ALERTA_DEMANDA_ALTA_PCT),
            ("costo_kwh", "Costo/kWh", _ALERTA_COSTO_KWH_ALTO_PCT),
        ),
        "alerta_fp": True,
        "alerta_punta": True,
        "limitacion": None,
        "secciones": {"perfil_horario": True, "desglose": True, "historial_extendido": True},
    },
    "GDMTO": {
        "key": "GDMTO",
        "nombre": "GDMTO",
        "descripcion": "Analisis ordinario sin inferir perfil horario.",
        "kpis": ("total_facturado", "consumo", "costo_kwh", "kwmax", "kw_cap", "kw_dist", "fp"),
        "comparativos": ("consumo", "total_facturado", "costo_kwh", "kwmax", "kw_cap", "kw_dist", "fp"),
        "metricas_grafica": ("consumo", "total_facturado", "costo_kwh", "kwmax", "kw_cap", "kw_dist"),
        "alertas_desviacion": (
            ("total_facturado", "Total facturado", _ALERTA_DESVIACION_ALTA_PCT),
            ("consumo", "Consumo", _ALERTA_DESVIACION_ALTA_PCT),
            ("kwmax", "Demanda maxima", _ALERTA_DEMANDA_ALTA_PCT),
            ("kw_cap", "KW CAP", _ALERTA_DEMANDA_ALTA_PCT),
            ("kw_dist", "kW DIST", _ALERTA_DEMANDA_ALTA_PCT),
            ("costo_kwh", "Costo/kWh", _ALERTA_COSTO_KWH_ALTO_PCT),
        ),
        "alerta_fp": True,
        "alerta_punta": False,
        "limitacion": "GDMTO no se analiza con perfil horario base/intermedia/punta.",
        "secciones": {"perfil_horario": False, "desglose": True, "historial_extendido": True},
    },
    "NO_SOPORTADA": {
        "key": "NO_SOPORTADA",
        "nombre": "Tarifa no soportada",
        "descripcion": "Analisis basico sin inferir metricas especificas de tarifa.",
        "kpis": ("total_facturado", "consumo", "costo_kwh"),
        "comparativos": ("consumo", "total_facturado", "costo_kwh"),
        "metricas_grafica": ("consumo", "total_facturado", "costo_kwh"),
        "alertas_desviacion": (
            ("total_facturado", "Total facturado", _ALERTA_DESVIACION_ALTA_PCT),
            ("consumo", "Consumo", _ALERTA_DESVIACION_ALTA_PCT),
            ("costo_kwh", "Costo/kWh", _ALERTA_COSTO_KWH_ALTO_PCT),
        ),
        "alerta_fp": False,
        "alerta_punta": False,
        "limitacion": "La tarifa {tarifa} no tiene reglas especificas; se muestra analisis basico.",
        "secciones": {"perfil_horario": False, "desglose": True, "historial_extendido": True},
    },
}
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
    perfil = _perfil_analisis(ultimo.get("tarifa"))
    periodos_misma_tarifa = [
        periodo for periodo in periodos
        if periodo.get("tarifa") == ultimo.get("tarifa")
    ]
    historico = [
        periodo for periodo in periodos_misma_tarifa
        if periodo["periodo_key"] < ultimo["periodo_key"]
    ]
    baseline = historico[-_ANALISIS_BASELINE_PERIODOS:]
    periodo_anterior = historico[-1] if historico else None
    mismo_mes_anio_anterior = _buscar_mismo_mes_anio_anterior(ultimo, periodos_misma_tarifa)
    periodos_excluidos_tarifa = len(periodos) - len(periodos_misma_tarifa)
    variacion_historico = _construir_variacion_historico(ultimo, baseline)
    metricas_grafica = _metricas_por_keys(perfil["metricas_grafica"])

    return {
        "servicio": servicio,
        "hay_datos": True,
        "mensaje": "",
        "perfil_analisis": perfil,
        "secciones": perfil["secciones"],
        "ultimo": ultimo,
        "periodos": periodos,
        "total_periodos": len(periodos),
        "periodos_comparables": len(periodos_misma_tarifa),
        "periodos_excluidos_tarifa": periodos_excluidos_tarifa,
        "baseline_periodos": len(baseline),
        "kpis": _construir_kpis(ultimo, perfil),
        "metricas_grafica": metricas_grafica,
        "comparativos": _construir_comparativos(
            ultimo,
            periodo_anterior,
            baseline,
            mismo_mes_anio_anterior,
            perfil,
        ),
        "graficas": _construir_graficas(periodos_misma_tarifa, metricas_grafica),
        "alertas": _construir_alertas_por_perfil(
            ultimo,
            baseline,
            perfil,
            periodos_excluidos_tarifa,
        ),
        "calidad_datos": _construir_calidad_datos(
            ultimo,
            perfil,
            periodos_excluidos_tarifa,
        ),
        "variacion_historico": variacion_historico,
        "historial_extendido": _historial_extendido(periodos),
    }


def analisis_sin_datos(servicio: dict, mensaje: str) -> dict[str, Any]:
    return {
        "servicio": servicio,
        "hay_datos": False,
        "mensaje": mensaje,
        "perfil_analisis": _PERFILES_ANALISIS["NO_SOPORTADA"],
        "secciones": _PERFILES_ANALISIS["NO_SOPORTADA"]["secciones"],
        "ultimo": None,
        "periodos": [],
        "total_periodos": 0,
        "periodos_comparables": 0,
        "periodos_excluidos_tarifa": 0,
        "baseline_periodos": 0,
        "kpis": [],
        "metricas_grafica": [],
        "comparativos": [],
        "graficas": {"labels": [], "metricas": {}},
        "alertas": [],
        "calidad_datos": {"disponibles": [], "faltantes": [], "limitaciones": []},
        "variacion_historico": {"disponible": False},
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


def _perfil_analisis(tarifa: Any) -> dict[str, Any]:
    tarifa_key = str(tarifa or "").strip().upper()
    return _PERFILES_ANALISIS.get(tarifa_key, _PERFILES_ANALISIS["NO_SOPORTADA"])


def _metricas_por_keys(keys: Sequence[str]) -> list[dict[str, Any]]:
    return [
        _METRICAS_BY_KEY[key]
        for key in keys
        if key in _METRICAS_BY_KEY
    ]


def _construir_kpis(ultimo: dict[str, Any], perfil: dict[str, Any]) -> list[dict[str, Any]]:
    kpis = []
    for key in perfil["kpis"]:
        metrica = _METRICAS_BY_KEY.get(key)
        if not metrica:
            continue

        valor = _numero_analisis(ultimo.get(key))
        tipo = "dinero" if key in {"total_facturado", "costo_kwh"} else "numero"
        sub = _KPI_SUBTEXTO.get(key)
        subtexto = None
        if sub:
            subtexto = {
                "label": sub["label"],
                "valor": _numero_analisis(ultimo.get(sub["source"])),
                "tipo": sub["tipo"],
                "decimales": sub["decimales"],
            }
        kpis.append({
            **metrica,
            "valor": valor,
            "tipo": tipo,
            "subtexto": subtexto,
        })
    return kpis


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

    tarifa = recibo.get("servicio", {}).get("tarifa") or "N/D"
    perfil = _perfil_analisis(tarifa)
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
        "tarifa": tarifa,
        "tipo_tarifa": recibo.get("servicio", {}).get("tipo_tarifa") or "N/D",
        "perfil_analisis": perfil["key"],
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
        "componentes": _componentes_agrupados(recibo, total_facturado),
        "perfil_horario": _perfil_horario(datos) if perfil["secciones"]["perfil_horario"] else [],
        "observaciones": observaciones,
        "datos_faltantes": datos_faltantes,
        "historial_embebido": recibo.get("historial") or [],
    }


def _componentes_agrupados(recibo: CfeReceipt, total: Optional[float]) -> list[dict[str, Any]]:
    grupos: dict[str, float] = {}

    for componente in recibo.get("componentes_tarifarios") or []:
        importe = _numero_analisis(componente.get("importe"))
        if importe is None:
            continue
        grupo = _grupo_componente(
            componente.get("codigo") or "",
            componente.get("nombre") or "",
        )
        grupos[grupo] = grupos.get(grupo, 0.0) + importe

    for concepto in recibo.get("conceptos_requeridos") or []:
        nombre_concepto = concepto.get("concepto") or ""
        if nombre_concepto.upper() == "SUBTOTAL":
            continue
        importe = _numero_analisis(concepto.get("importe"))
        if importe is None:
            continue
        grupo = _grupo_componente("", nombre_concepto)
        grupos[grupo] = grupos.get(grupo, 0.0) + importe

    componentes = [
        {
            "codigo": nombre.upper().replace(" ", "_"),
            "nombre": nombre,
            "importe": importe,
            "porcentaje": _porcentaje(importe, total),
        }
        for nombre, importe in grupos.items()
    ]
    return sorted(componentes, key=lambda item: abs(item["importe"]), reverse=True)


def _grupo_componente(codigo: str, nombre: str) -> str:
    codigo = codigo.upper()
    nombre_mayus = nombre.upper()

    if codigo in {"EGB", "EGI", "EGP", "EG1"} or "GENERACI" in nombre_mayus:
        return "Energia"
    if codigo in {"ED1"} or "DISTRIBU" in nombre_mayus:
        return "Distribucion"
    if codigo in {"ETB", "ET1"} or "TRANSMISI" in nombre_mayus:
        return "Transmision"
    if codigo in {"EID", "CAP"} or "CAPACIDAD" in nombre_mayus:
        return "Capacidad"
    if codigo in {"ES1"} or "SUMINISTRO" in nombre_mayus:
        return "Suministro"
    if codigo in {"ECB", "EC1", "ECS"} or "CENACE" in nombre_mayus:
        return "CENACE"
    if (
        "FACTOR DE POTENCIA" in nombre_mayus
        or "SUBTOTAL" in nombre_mayus
        or "BAJA TENSION" in nombre_mayus
    ):
        return "Ajustes"
    return "Otros"


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
    perfil: dict[str, Any],
) -> list[dict[str, Any]]:
    comparativos = []
    for metrica in _metricas_por_keys(perfil["comparativos"]):
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


def _construir_graficas(
    periodos: Sequence[dict[str, Any]],
    metricas_grafica: Sequence[dict[str, Any]],
) -> dict[str, Any]:
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
            for metrica in metricas_grafica
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


def _construir_alertas_por_perfil(
    ultimo: dict[str, Any],
    baseline: Sequence[dict[str, Any]],
    perfil: dict[str, Any],
    periodos_excluidos_tarifa: int,
) -> list[dict[str, str]]:
    alertas: list[dict[str, str]] = []
    if periodos_excluidos_tarifa:
        alertas.append({
            "tipo": "info",
            "titulo": "Baseline filtrado por tarifa",
            "detalle": (
                f"Se omitieron {periodos_excluidos_tarifa} periodos con tarifa distinta "
                "para evitar comparaciones incorrectas."
            ),
        })

    fp = _numero_analisis(ultimo.get("fp"))
    if perfil["alerta_fp"] and fp is not None and fp < _ALERTA_FACTOR_POTENCIA_MIN:
        alertas.append({
            "tipo": "danger",
            "titulo": "Factor de potencia bajo",
            "detalle": f"El ultimo recibo esta en {fp:.2f}%, por debajo del umbral de {_ALERTA_FACTOR_POTENCIA_MIN:.0f}%.",
        })

    for key, titulo, umbral_pct in perfil["alertas_desviacion"]:
        _agregar_alerta_desviacion(alertas, ultimo, baseline, key, titulo, umbral_pct)

    punta_pct = _numero_analisis(ultimo.get("consumo_punta_pct"))
    if perfil["alerta_punta"] and punta_pct is not None and punta_pct >= _ALERTA_CONSUMO_PUNTA_PCT:
        alertas.append({
            "tipo": "warning",
            "titulo": "Consumo punta elevado",
            "detalle": f"La punta representa {punta_pct:.1f}% del consumo del ultimo periodo.",
        })

    if ultimo.get("datos_faltantes"):
        faltantes = ", ".join(ultimo["datos_faltantes"][:4])
        alertas.append({
            "tipo": "info",
            "titulo": "Datos incompletos en XML",
            "detalle": f"Faltan datos para algunos calculos: {faltantes}.",
        })

    if not alertas:
        alertas.append({
            "tipo": "success",
            "titulo": "Sin alertas relevantes",
            "detalle": "El ultimo periodo no rebasa los umbrales principales contra el baseline.",
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


def _construir_calidad_datos(
    ultimo: dict[str, Any],
    perfil: dict[str, Any],
    periodos_excluidos_tarifa: int,
) -> dict[str, list[str]]:
    disponibles = []
    faltantes = []
    limitaciones = []

    for metrica in _metricas_por_keys(perfil["comparativos"]):
        label = metrica["label"]
        if _numero_analisis(ultimo.get(metrica["key"])) is None:
            faltantes.append(label)
        else:
            disponibles.append(label)

    if ultimo.get("componentes"):
        disponibles.append("Desglose de componentes")
    else:
        faltantes.append("Desglose de componentes")

    limitacion = perfil.get("limitacion")
    if limitacion:
        tarifa = ultimo.get("tarifa") or "N/D"
        limitaciones.append(limitacion.replace("{tarifa}", tarifa))

    if periodos_excluidos_tarifa:
        limitaciones.append(
            f"{periodos_excluidos_tarifa} periodos se excluyeron del baseline por tarifa distinta."
        )

    for faltante in ultimo.get("datos_faltantes") or []:
        if faltante not in faltantes:
            faltantes.append(faltante)

    return {
        "disponibles": disponibles,
        "faltantes": faltantes,
        "limitaciones": limitaciones,
    }


def _construir_variacion_historico(
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
    diferencia = costo_esperado - total
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
        "diferencia_estimada": diferencia,
        "diferencia_pct": _porcentaje(diferencia, costo_esperado),
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
