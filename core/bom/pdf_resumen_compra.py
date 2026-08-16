# Archivo: core/bom/pdf_resumen_compra.py
"""
Conversion Decimal -> valor graficable para el PDF "resumen de compra" del
consolidado BOM (doc 40, puntos 6.3/6.4).

Deliberadamente AISLADO de `BomService._get_consolidado_proyecto_snapshot`:
esa funcion es el read model de mas trafico del modulo BOM (el hub principal
la llama dos veces por carga, no solo el export) y dos tests
(tests/test_bom_resumen_financiero_contratos.py) afirman igualdad exacta con
Decimal sobre `consolidado["totales"]`/`consolidado["divisor_fv"]`. Este
modulo LEE el dict del snapshot sin mutarlo -- nunca se edita el snapshot
compartido para "ayudar" a esta conversion.

Regla de conversion (mismo precedente que `export_consolidado_excel`, que
trata None como celda vacia, no como cero): un total None nunca se grafica
como barra en cero -- se omite la etiqueta/valor por completo del dataset.
"""

from typing import Optional


_ETAPAS_TOTALES = (
    ("Presupuesto", "presupuesto_total_mxn"),
    ("Cotizado", "cotizado_total_mxn"),
    ("Autorizado", "autorizado_total_mxn"),
    ("Facturado", "facturado_total_mxn"),
    ("Pagado", "pagado_total_mxn"),
)

_COLOR_ETAPAS = "#00BABB"
_COLOR_PRESUPUESTO = "#0A2463"
_COLOR_FACTURADO = "#00BABB"


def _totales_bar(totales: dict) -> Optional[dict]:
    """Barra unica: las 5 etapas del proyecto completo, ya en MXN. Etapas con
    valor None se omiten (etiqueta + dato juntos), no se muestran en cero."""
    etiquetas, valores = [], []
    for nombre, clave in _ETAPAS_TOTALES:
        valor = totales.get(clave)
        if valor is not None:
            etiquetas.append(nombre)
            valores.append(float(valor))
    if not etiquetas:
        return None
    return {
        "tipo": "bar",
        "labels": etiquetas,
        "datasets": [{"label": "MXN", "data": valores, "backgroundColor": _COLOR_ETAPAS}],
    }


def _por_paquete_bar(paquetes: list) -> Optional[dict]:
    """Barras agrupadas: 5 datasets (uno por etapa) x N paquetes.

    Las 5 etapas de un paquete deben alinearse por indice entre datasets, asi
    que -a diferencia de la barra de totales- no se puede omitir una celda
    suelta sin desalinear las demas series. Un paquete con CUALQUIER etapa en
    None se excluye del grafico completo (no se muestra parcialmente
    completo) -- mismo principio de "nunca mostrar incompleto como
    completo", aplicado a nivel de fila en vez de celda."""
    completos = [
        p for p in paquetes
        if all(p.get(clave) is not None for _, clave in _ETAPAS_TOTALES)
    ]
    if not completos:
        return None
    etiquetas = [p.get("codigo") or str(p.get("id_paquete")) for p in completos]
    datasets = [
        {
            "label": nombre,
            "data": [float(p[clave]) for p in completos],
        }
        for nombre, clave in _ETAPAS_TOTALES
    ]
    return {"tipo": "bar", "labels": etiquetas, "datasets": datasets}


def _por_grupo_bar(desglose_grupos: list) -> Optional[dict]:
    """Barras agrupadas: presupuesto vs facturado por grupo operativo, ambos
    en MXN (desglose_grupos no trae autorizado/pagado ni un total_mxn
    pre-convertido para presupuesto_usd -- se grafica solo la parte MXN, sin
    inventar una conversion de tipo de cambio nueva a nivel de grupo).

    `presupuesto_pendiente` es un flag independiente del monto (el grupo
    puede tener datos incompletos aunque su suma parcial no sea None) -- se
    anota con un asterisco en la etiqueta en vez de descartar la barra."""
    if not desglose_grupos:
        return None
    etiquetas = [
        f"{g['codigo']} *" if g.get("presupuesto_pendiente") else g["codigo"]
        for g in desglose_grupos
    ]
    return {
        "tipo": "bar",
        "labels": etiquetas,
        "datasets": [
            {
                "label": "Presupuesto",
                "data": [float(g.get("presupuesto_mxn") or 0) for g in desglose_grupos],
                "backgroundColor": _COLOR_PRESUPUESTO,
            },
            {
                "label": "Facturado",
                "data": [float(g.get("facturado_mxn") or 0) for g in desglose_grupos],
                "backgroundColor": _COLOR_FACTURADO,
            },
        ],
    }


def datos_graficas_resumen_compra(consolidado: dict) -> dict:
    """Punto de entrada: recibe el dict ya devuelto por
    `BomService.get_consolidado_proyecto` (sin mutarlo) y arma las 3
    especificaciones de grafica (formato Chart.js) para
    `core.charts.service.generar_charts_bom_consolidado`."""
    return {
        "totales_bar": _totales_bar(consolidado.get("totales") or {}),
        "por_paquete_bar": _por_paquete_bar(consolidado.get("paquetes") or []),
        "por_grupo_bar": _por_grupo_bar(consolidado.get("desglose_grupos") or []),
    }
