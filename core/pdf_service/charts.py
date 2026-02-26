# core/pdf_service/charts.py
"""
Generadores de charts server-side usando Plotly + kaleido 0.2.1.
Cada funcion retorna un data URI base64 (PNG) para embeber en HTML de WeasyPrint.

Uso:
    uri = await chart_tendencia_mensual(datos_mensual)
    # uri = "data:image/png;base64,..."
"""
import asyncio
import base64
import logging
from typing import Any, Dict, List

logger = logging.getLogger("PDFCharts")

# Paleta corporativa Enertika
_COLORS_PRIMARY = ["#00BABB", "#0A2463", "#2D5A9E", "#3E92CC", "#4CAF50", "#FF9800"]
_COLOR_TEAL = "#00BABB"
_COLOR_NAVY = "#0A2463"
_COLOR_GRAY = "#9E9E9E"
_WHITE = "white"

_DEFAULT_LAYOUT = dict(
    paper_bgcolor=_WHITE,
    plot_bgcolor=_WHITE,
    font=dict(family="Arial, Helvetica, sans-serif", size=11, color="#333333"),
    margin=dict(l=50, r=30, t=40, b=50),
)


def _to_data_uri(png_bytes: bytes) -> str:
    return f"data:image/png;base64,{base64.b64encode(png_bytes).decode()}"


async def _run_sync(fn) -> str:
    """Ejecuta una funcion sincrona en executor y retorna data URI."""
    loop = asyncio.get_running_loop()
    png_bytes = await loop.run_in_executor(None, fn)
    return _to_data_uri(png_bytes)


# ---------------------------------------------------------------------------
# Chart 1: Distribucion por estatus (donut)
# ---------------------------------------------------------------------------

async def chart_distribucion_estatus(data: List[Dict[str, Any]]) -> str:
    """
    Donut chart de simulaciones por estatus.

    Args:
        data: Lista de dicts con keys 'label' y 'value'.
    """
    def _sync():
        import plotly.graph_objects as go

        labels = [d["label"] for d in data]
        values = [d["value"] for d in data]

        fig = go.Figure(go.Pie(
            labels=labels,
            values=values,
            hole=0.45,
            marker=dict(colors=_COLORS_PRIMARY),
            textinfo="label+percent",
            textfont=dict(size=10),
        ))
        fig.update_layout(
            **_DEFAULT_LAYOUT,
            width=480,
            height=340,
            showlegend=False,
            title=dict(text="Distribucion por Estatus", font=dict(size=13)),
        )
        return fig.to_image(format="png")

    return await _run_sync(_sync)


# ---------------------------------------------------------------------------
# Chart 2: Tendencia mensual (line chart)
# ---------------------------------------------------------------------------

async def chart_tendencia_mensual(datos_mensual: Dict[str, Any]) -> str:
    """
    Line chart de solicitudes vs entregas por mes.

    Args:
        datos_mensual: Dict con key 'meses' (List[str]) y 'series' (List[Dict]).
                       Alternativa: lista de dicts con 'mes', 'solicitudes', 'entregas'.
    """
    def _sync():
        import plotly.graph_objects as go

        # Soporte para dos formatos de entrada
        if isinstance(datos_mensual, dict) and "meses" in datos_mensual:
            meses = datos_mensual["meses"]
            solicitudes = datos_mensual.get("solicitudes", [])
            entregas = datos_mensual.get("entregas", [])
        elif isinstance(datos_mensual, list):
            meses = [str(d.get("mes", i)) for i, d in enumerate(datos_mensual)]
            solicitudes = [d.get("solicitudes", 0) for d in datos_mensual]
            entregas = [d.get("entregas", 0) for d in datos_mensual]
        else:
            meses, solicitudes, entregas = [], [], []

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=meses, y=solicitudes,
            name="Solicitudes",
            mode="lines+markers",
            line=dict(color=_COLOR_TEAL, width=2),
            marker=dict(size=6),
        ))
        fig.add_trace(go.Scatter(
            x=meses, y=entregas,
            name="Entregas",
            mode="lines+markers",
            line=dict(color=_COLOR_NAVY, width=2, dash="dot"),
            marker=dict(size=6),
        ))
        fig.update_layout(
            **_DEFAULT_LAYOUT,
            width=700,
            height=320,
            legend=dict(orientation="h", y=-0.25),
            xaxis=dict(title="Mes", tickangle=-30),
            yaxis=dict(title="Cantidad"),
            title=dict(text="Tendencia Mensual", font=dict(size=13)),
        )
        return fig.to_image(format="png")

    return await _run_sync(_sync)


# ---------------------------------------------------------------------------
# Chart 3: Carga de tecnicos (bar horizontal)
# ---------------------------------------------------------------------------

async def chart_carga_tecnicos(data: List[Dict[str, Any]]) -> str:
    """
    Bar horizontal de simulaciones por tecnico.

    Args:
        data: Lista de dicts con 'nombre' y 'total'.
    """
    def _sync():
        import plotly.graph_objects as go

        nombres = [d.get("nombre", "") for d in data]
        totales = [d.get("total", 0) for d in data]

        fig = go.Figure(go.Bar(
            x=totales,
            y=nombres,
            orientation="h",
            marker=dict(color=_COLOR_TEAL),
            text=totales,
            textposition="outside",
        ))
        fig.update_layout(
            **_DEFAULT_LAYOUT,
            width=600,
            height=max(280, 40 * len(nombres) + 80),
            xaxis=dict(title="Simulaciones"),
            yaxis=dict(autorange="reversed"),
            title=dict(text="Carga por Tecnico", font=dict(size=13)),
        )
        return fig.to_image(format="png")

    return await _run_sync(_sync)


# ---------------------------------------------------------------------------
# Chart 4: Distribucion por tecnologia (bar vertical)
# ---------------------------------------------------------------------------

async def chart_por_tecnologia(data: List[Dict[str, Any]]) -> str:
    """
    Bar chart de conteo por tecnologia.

    Args:
        data: Lista de dicts con 'nombre' y 'total_solicitudes'.
    """
    def _sync():
        import plotly.graph_objects as go

        nombres = [d.get("nombre", "") for d in data]
        totales = [d.get("total_solicitudes", 0) for d in data]

        fig = go.Figure(go.Bar(
            x=nombres,
            y=totales,
            marker=dict(color=_COLORS_PRIMARY[: len(nombres)]),
            text=totales,
            textposition="outside",
        ))
        fig.update_layout(
            **_DEFAULT_LAYOUT,
            width=620,
            height=320,
            xaxis=dict(title="Tecnologia", tickangle=-20),
            yaxis=dict(title="Solicitudes"),
            title=dict(text="Solicitudes por Tecnologia", font=dict(size=13)),
        )
        return fig.to_image(format="png")

    return await _run_sync(_sync)


# ---------------------------------------------------------------------------
# Chart 5: Motivos de cierre (bar horizontal)
# ---------------------------------------------------------------------------

async def chart_motivos_cierre(data: List[Dict[str, Any]]) -> str:
    """
    Bar horizontal de top motivos de cierre.

    Args:
        data: Lista de dicts con 'motivo' y 'total'.
    """
    def _sync():
        import plotly.graph_objects as go

        motivos = [d.get("motivo", "") for d in data]
        totales = [d.get("total", 0) for d in data]

        fig = go.Figure(go.Bar(
            x=totales,
            y=motivos,
            orientation="h",
            marker=dict(color=_COLOR_NAVY),
            text=totales,
            textposition="outside",
        ))
        fig.update_layout(
            **_DEFAULT_LAYOUT,
            width=600,
            height=max(260, 36 * len(motivos) + 80),
            xaxis=dict(title="Cantidad"),
            yaxis=dict(autorange="reversed"),
            title=dict(text="Motivos de Cierre", font=dict(size=13)),
        )
        return fig.to_image(format="png")

    return await _run_sync(_sync)
