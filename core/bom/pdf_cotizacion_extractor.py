# Archivo: core/bom/pdf_cotizacion_extractor.py
"""
Extractor de precios candidatos desde PDFs de cotizacion de proveedor (Compras BOM).

No hace match automatico contra los items del BOM -- las descripciones de
proveedor varian demasiado entre ellos para que un match automatico sea
confiable. Solo lista renglones candidatos (texto + precio) para que el
usuario asigne manualmente cada uno al item correspondiente en el modal de
captura. Mismo enfoque sin OCR que modules/compras/pdf_extractor.py
(pdfplumber), pero la heuristica es distinta: ahi se parsean campos fijos de
un comprobante de pago (necesita solo texto de la pagina 1); aqui se listan
renglones de una tabla de items (necesita el objeto pdf completo, multi-pagina,
para extract_tables()) -- por eso no reusa su apertura+manejo de errores.
"""

import pdfplumber
import re
import io
import logging
from pdfminer.pdfexceptions import PSException

from modules.compras.pdf_extractor import clean_text

logger = logging.getLogger("BOM.PDFCotizacionExtractor")

_MAX_CANDIDATOS = 50
_PRECIO_EN_TEXTO_RE = re.compile(r'\$?\s*([\d,]+\.\d{2})\s*$')
_PRECIO_CELDA_RE = re.compile(r'([\d,]+\.\d{2})')
# Renglones de agregado (total/IVA/subtotal) no son un costo de item -- asignarlos
# a un item del BOM seria un error de captura, no solo un candidato de baja calidad.
_LINEA_AGREGADO_RE = re.compile(r'\b(total|subtotal|i\.?v\.?a\.?|impuesto)\b', re.IGNORECASE)


def _parse_precio(texto: str):
    """Extrae el primer numero con centavos de un texto, o None si no hay."""
    match = _PRECIO_CELDA_RE.search(texto) if texto else None
    if not match:
        return None
    try:
        return float(match.group(1).replace(',', ''))
    except ValueError:
        return None


def _es_linea_agregado(texto: str) -> bool:
    return bool(_LINEA_AGREGADO_RE.search(texto))


def _agregar_candidato(candidatos: list, texto: str, precio: float) -> None:
    if texto and not _es_linea_agregado(texto):
        candidatos.append({"texto": texto[:200], "precio": precio})


def _candidatos_de_tablas(pdf) -> list:
    """Extrae (texto, precio) de tablas detectadas por pdfplumber.

    Por fila, toma como precio la ultima celda que parsea como numero con
    centavos y concatena el resto de celdas no vacias como descripcion.
    Corta en cuanto se alcanza _MAX_CANDIDATOS -- evita seguir corriendo
    extract_tables() (costoso) sobre paginas cuyo resultado se descartaria.
    """
    candidatos = []
    for page in pdf.pages:
        for tabla in page.extract_tables():
            for fila in tabla:
                celdas = [c.strip() for c in fila if c and c.strip()]
                if len(celdas) < 2:
                    continue
                precio = None
                idx_precio = None
                for i in range(len(celdas) - 1, -1, -1):
                    precio = _parse_precio(celdas[i])
                    if precio is not None:
                        idx_precio = i
                        break
                if precio is None:
                    continue
                texto = clean_text(" ".join(c for j, c in enumerate(celdas) if j != idx_precio))
                _agregar_candidato(candidatos, texto, precio)
                if len(candidatos) >= _MAX_CANDIDATOS:
                    return candidatos
    return candidatos


def _candidatos_de_texto(paginas_texto: list) -> list:
    """Fallback sin tablas: cada linea que termina en un precio es un candidato."""
    candidatos = []
    for raw_text in paginas_texto:
        for linea in raw_text.split("\n"):
            match = _PRECIO_EN_TEXTO_RE.search(linea)
            if not match:
                continue
            precio = _parse_precio(match.group(1))
            texto = linea[:match.start()].strip()
            _agregar_candidato(candidatos, texto, precio)
            if len(candidatos) >= _MAX_CANDIDATOS:
                return candidatos
    return candidatos


def _detectar_moneda(raw_text: str):
    if any(x in raw_text for x in ["USD", "Dólares", "DOLARES", "US$"]):
        return "USD"
    if any(x in raw_text for x in ["MXN", "Pesos", "M.N."]):
        return "MXN"
    return None


def extraer_costos_cotizacion(pdf_content: bytes, filename: str) -> dict:
    """
    Extrae precios candidatos de un PDF de cotizacion de proveedor.

    Returns:
        dict con:
        - candidatos: list[{"texto": str, "precio": float}] (tope 50)
        - metodo: "tabla" | "texto" | None (None si no se detecto nada)
        - moneda_detectada: "USD" | "MXN" | None
        - error: str | None
    """
    try:
        with pdfplumber.open(io.BytesIO(pdf_content)) as pdf:
            if not pdf.pages:
                return {"candidatos": [], "metodo": None, "moneda_detectada": None, "error": "PDF sin páginas"}

            primera_pagina_texto = pdf.pages[0].extract_text() or ""

            candidatos = _candidatos_de_tablas(pdf)
            metodo = "tabla" if candidatos else None
            if not candidatos:
                # Solo se re-extrae texto de paginas 2+ aqui -- la pagina 1 ya
                # se tiene arriba, evita pedirsela dos veces a pdfplumber.
                paginas_texto = [primera_pagina_texto] + [
                    p.extract_text() or "" for p in pdf.pages[1:]
                ]
                candidatos = _candidatos_de_texto(paginas_texto)
                metodo = "texto" if candidatos else None

            moneda = _detectar_moneda(primera_pagina_texto)

            return {
                "candidatos": candidatos,
                "metodo": metodo,
                "moneda_detectada": moneda,
                "error": None,
            }
    except (PSException, ValueError, TypeError, KeyError, OSError) as e:
        logger.error(f"Error procesando PDF de cotización {filename}: {e}", exc_info=True)
        return {
            "candidatos": [], "metodo": None, "moneda_detectada": None,
            "error": f"Error de procesamiento: {str(e)}",
        }
