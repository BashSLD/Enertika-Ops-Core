import asyncio
import base64
import logging
from dataclasses import asdict

import httpx

from core.config import settings

logger = logging.getLogger("charts.service")


async def _grafica_a_base64(
    client: httpx.AsyncClient, datos_grafica: dict, width: int, height: int
) -> str | None:
    if not datos_grafica or not datos_grafica.get("labels"):
        return None

    payload = {
        "chart": {
            "type": datos_grafica["tipo"],
            "data": {
                "labels": datos_grafica["labels"],
                "datasets": datos_grafica["datasets"],
            },
            "options": {
                "plugins": {"legend": {"display": True}},
                "animation": {"duration": 0},
            },
        },
        "width": width,
        "height": height,
        "backgroundColor": "white",
    }

    try:
        response = await client.post(f"{settings.QUICKCHART_URL}/chart", json=payload)
        response.raise_for_status()
        b64 = base64.b64encode(response.content).decode()
        return f"data:image/png;base64,{b64}"
    except httpx.HTTPError as e:
        logger.error("QuickChart error: %s", e)
        return None


def _to_chart_dict(g) -> dict:
    if g is None:
        return {}
    if hasattr(g, "__dataclass_fields__"):
        return asdict(g)
    return g


async def generar_charts_simulacion(graficas: dict) -> dict:
    """
    Recibe el dict de graficas de report_service y retorna
    {estatus, mensual, tecnologia} listo para el template PDF.
    Cualquier gráfica que falle queda ausente (el template maneja {% if %}).
    """
    specs = [
        ("estatus", _to_chart_dict(graficas.get("estatus_pie")), 450, 300),
        ("mensual", _to_chart_dict(graficas.get("mensual_bar")), 500, 280),
        ("tecnologia", _to_chart_dict(graficas.get("tecnologia_pie")), 450, 300),
    ]

    async with httpx.AsyncClient(timeout=15.0) as client:
        resultados = await asyncio.gather(
            *[_grafica_a_base64(client, datos, w, h) for _, datos, w, h in specs],
            return_exceptions=True,
        )

    charts = {}
    for (key, _, _, _), resultado in zip(specs, resultados):
        if isinstance(resultado, str):
            charts[key] = resultado
        elif isinstance(resultado, Exception):
            logger.warning("Error generando chart %s: %s", key, resultado)

    return charts


async def generar_charts_bom_consolidado(graficas: dict) -> dict:
    """
    Recibe el dict de graficas de core.bom.pdf_resumen_compra y retorna
    {totales, por_paquete, por_grupo} listo para el template PDF del
    consolidado BOM (doc 40, puntos 6.3/6.4). Cualquier grafica que falle
    queda ausente (el template maneja {% if %}), mismo criterio que
    generar_charts_simulacion.
    """
    specs = [
        ("totales", _to_chart_dict(graficas.get("totales_bar")), 500, 300),
        ("por_paquete", _to_chart_dict(graficas.get("por_paquete_bar")), 550, 320),
        ("por_grupo", _to_chart_dict(graficas.get("por_grupo_bar")), 550, 320),
    ]

    async with httpx.AsyncClient(timeout=15.0) as client:
        resultados = await asyncio.gather(
            *[_grafica_a_base64(client, datos, w, h) for _, datos, w, h in specs],
            return_exceptions=True,
        )

    charts = {}
    for (key, _, _, _), resultado in zip(specs, resultados):
        if isinstance(resultado, str):
            charts[key] = resultado
        elif isinstance(resultado, Exception):
            logger.warning("Error generando chart BOM %s: %s", key, resultado)

    return charts
