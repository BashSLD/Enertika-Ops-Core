# Archivo: modules/compras/pdf_extractor.py
"""
Extractor de datos de comprobantes de pago BBVA y BanBajío (BajioNet).
BBVA validado con 120+ archivos PDF.
"""

import pdfplumber
import re
import io
from datetime import datetime
from typing import Optional
from dataclasses import dataclass
import logging
from pdfminer.pdfexceptions import PSException

logger = logging.getLogger("ComprasPDFExtractor")

_MESES_ES_EN = {
    "ene": 1, "jan": 1,
    "feb": 2,
    "mar": 3,
    "abr": 4, "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "ago": 8, "aug": 8,
    "sep": 9, "set": 9,
    "oct": 10,
    "nov": 11,
    "dic": 12, "dec": 12,
}


@dataclass
class ComprobantePDFData:
    """Datos extraídos de un comprobante PDF."""
    archivo: str
    fecha_pago: Optional[datetime] = None
    beneficiario: Optional[str] = None
    monto: Optional[float] = None
    moneda: str = "MXN"
    error: Optional[str] = None

    def is_valid(self) -> bool:
        """Verifica si tiene todos los campos requeridos."""
        return (
            self.fecha_pago is not None and
            self.beneficiario is not None and
            self.monto is not None and
            self.error is None
        )


def clean_text(text: str) -> Optional[str]:
    """Limpia espacios múltiples y caracteres especiales."""
    if not text:
        return None
    # Eliminar espacios múltiples y caracteres problemáticos
    cleaned = re.sub(r'\s+', ' ', text).strip()
    cleaned = cleaned.replace('"', '').replace("'", "")
    return cleaned if cleaned else None


def _parse_monto(raw_text: str, pattern: str, filename: str) -> Optional[float]:
    """Extrae el monto usando el patrón de importe propio de cada banco."""
    match = re.search(pattern, raw_text)
    if not match:
        return None

    monto_str = match.group(1).replace(',', '')
    try:
        return float(monto_str)
    except ValueError:
        logger.warning(f"[{filename}] Monto inválido: {monto_str}")
        return None


def _validar_datos_minimos(result: ComprobantePDFData) -> None:
    """Marca error si falta alguno de los campos requeridos."""
    if not result.fecha_pago:
        result.error = "No se encontró fecha de pago"
    elif result.monto is None:
        result.error = "No se encontró monto"
    elif not result.beneficiario:
        result.error = "No se encontró beneficiario"


def _extract_raw_text(pdf_content: bytes, filename: str) -> tuple[Optional[str], Optional[str]]:
    """
    Abre el PDF una sola vez y extrae el texto de la primera página.

    Returns:
        Tupla (texto, error). Si error no es None, texto es None.
    """
    try:
        with pdfplumber.open(io.BytesIO(pdf_content)) as pdf:
            if not pdf.pages:
                return None, "PDF sin páginas"

            raw_text = pdf.pages[0].extract_text()
            if not raw_text:
                return None, "No se pudo extraer texto del PDF"

            return raw_text, None
    except (PSException, ValueError, TypeError, KeyError, OSError) as e:
        logger.error(f"Error procesando PDF {filename}: {e}", exc_info=True)
        return None, f"Error de procesamiento: {str(e)}"


_ENCABEZADO_MAX_LINEAS = 5


def _detect_banco(raw_text: str) -> str:
    """
    Detecta el banco emisor usando solo el encabezado del comprobante.
    Restringido a las primeras líneas para no confundir el banco emisor
    con menciones a otros bancos en el cuerpo (ej. "Banco Destino").
    """
    encabezado = "\n".join(raw_text.split('\n')[:_ENCABEZADO_MAX_LINEAS])
    if any(x in encabezado for x in ["BanBajío", "Banco del Bajío", "BajioNet"]):
        return "banbajio"
    return "bbva"


def _parse_bbva(raw_text: str, filename: str) -> ComprobantePDFData:
    """Parsea el texto ya extraído de un comprobante BBVA."""
    result = ComprobantePDFData(archivo=filename)

    try:
        lines = raw_text.split('\n')

        # 1. Extraer fecha (formato DD/MM/YYYY)
        match_fecha = re.search(r'(\d{2}/\d{2}/\d{4})', raw_text)
        if match_fecha:
            fecha_str = match_fecha.group(1)
            try:
                result.fecha_pago = datetime.strptime(fecha_str, "%d/%m/%Y")
            except ValueError:
                logger.warning(f"[{filename}] Fecha inválida: {fecha_str}")

        # 2. Extraer monto (buscar patrón "Importe" seguido de cantidad)
        result.monto = _parse_monto(raw_text, r'Importe.*?\$?\s*([\d,]+\.\d{2})', filename)

        # 3. Detectar moneda
        if any(x in raw_text for x in ["USD", "Dólares", "Divisa: USD", "DOLARES"]):
            result.moneda = "USD"

        # 4. Extraer beneficiario - Estrategia múltiple
        beneficiario = None

        # Estrategia A: Buscar en líneas con etiquetas conocidas
        for i, line in enumerate(lines):
            if "Nombre del tercero" in line or "Nombre de la empresa a pagar" in line:
                parts = line.split(":")
                candidate = parts[-1].strip() if len(parts) > 1 else ""

                # Si está vacío, revisar siguiente línea
                if not candidate and i + 1 < len(lines):
                    candidate = lines[i + 1].strip()

                # Corrección para nombres cortados (ej: "CV", "SA", "SA DE CV")
                if len(candidate) < 5 or candidate.upper() in ["CV", "SA", "SA DE CV", "DE CV"]:
                    if i > 0 and ":" not in lines[i - 1]:
                        candidate = f"{lines[i - 1].strip()} {candidate}"

                if candidate and len(candidate) >= 3:
                    beneficiario = clean_text(candidate)
                    break

        # Estrategia B: Buscar en bloque "Datos del beneficiario"
        if not beneficiario:
            block_pattern = r'Datos del beneficiario\s*(.*?)\s*(?:Datos del ordenante|Puedes obtener|BBVA|Cerrar|$)'
            bloque = re.search(block_pattern, raw_text, re.DOTALL | re.IGNORECASE)

            if bloque:
                bloque_lines = bloque.group(1).split('\n')
                for line in bloque_lines:
                    # Limpiar etiquetas comunes
                    clean_l = line.replace("Nombre:", "").replace("Beneficiario:", "").strip()
                    # Ignorar líneas con otras etiquetas o vacías
                    if (clean_l and
                        "Dirección" not in clean_l and
                        "RFC" not in clean_l and
                        "Cuenta" not in clean_l and
                        "CLABE" not in clean_l and
                        len(clean_l) >= 3):
                        beneficiario = clean_text(clean_l)
                        break

        result.beneficiario = beneficiario

        _validar_datos_minimos(result)

    except (ValueError, TypeError, AttributeError, IndexError) as e:
        logger.error(f"Error procesando PDF {filename}: {e}", exc_info=True)
        result.error = f"Error de procesamiento: {str(e)}"

    return result


def _parse_fecha_banbajio(fecha_str: str) -> Optional[datetime]:
    """Parsea fechas BanBajío en formato DD-Mon-YYYY (abreviatura ES o EN)."""
    match = re.match(r'(\d{1,2})-([A-Za-z]{3})-(\d{4})', fecha_str)
    if not match:
        return None

    dia, mes_str, anio = match.groups()
    mes = _MESES_ES_EN.get(mes_str.lower())
    if not mes:
        return None

    try:
        return datetime(int(anio), mes, int(dia))
    except ValueError:
        return None


def _parse_banbajio(raw_text: str, filename: str) -> ComprobantePDFData:
    """Parsea el texto ya extraído de un comprobante BanBajío (BajioNet)."""
    result = ComprobantePDFData(archivo=filename)

    try:
        lines = raw_text.split('\n')

        # 1. Extraer fecha ("Fecha de Operación: DD-Mon-YYYY")
        match_fecha = re.search(r'Fecha de Operaci[oó]n:\s*(\d{1,2}-[A-Za-z]{3}-\d{4})', raw_text)
        if match_fecha:
            fecha_str = match_fecha.group(1)
            result.fecha_pago = _parse_fecha_banbajio(fecha_str)
            if not result.fecha_pago:
                logger.warning(f"[{filename}] Fecha inválida: {fecha_str}")

        # 2. Extraer monto ("Importe: $X,XXX.XX MN")
        result.monto = _parse_monto(raw_text, r'Importe:\s*\$?\s*([\d,]+\.\d{2})', filename)

        # 3. Detectar moneda
        if any(x in raw_text for x in ["USD", "Dólares", "DOLARES"]):
            result.moneda = "USD"

        # 4. Extraer beneficiario ("Nombre del Beneficiario: X", con posible wrap a 2da línea)
        beneficiario = None
        for i, line in enumerate(lines):
            if "Nombre del Beneficiario" in line:
                parts = line.split(":", 1)
                candidate = parts[1].strip() if len(parts) > 1 else ""

                # Nombres largos hacen wrap a la siguiente línea (igual que el ordenante)
                if i + 1 < len(lines):
                    siguiente = lines[i + 1].strip()
                    if siguiente and ":" not in siguiente:
                        candidate = f"{candidate} {siguiente}".strip()

                if candidate:
                    beneficiario = clean_text(candidate)
                    break

        result.beneficiario = beneficiario

        _validar_datos_minimos(result)

    except (ValueError, TypeError, AttributeError, IndexError) as e:
        logger.error(f"Error procesando PDF {filename}: {e}", exc_info=True)
        result.error = f"Error de procesamiento: {str(e)}"

    return result


def _extract_and_parse(pdf_content: bytes, filename: str, parser) -> ComprobantePDFData:
    """Abre el PDF una vez y delega el parseo del texto al parser indicado."""
    raw_text, error = _extract_raw_text(pdf_content, filename)
    if error:
        return ComprobantePDFData(archivo=filename, error=error)

    return parser(raw_text, filename)


def extract_from_bbva_pdf(pdf_content: bytes, filename: str) -> ComprobantePDFData:
    """
    Extrae datos de un comprobante BBVA.
    Se conserva por compatibilidad; usar extract_comprobante_pdf para
    detectar el banco automáticamente.

    Args:
        pdf_content: Contenido binario del PDF
        filename: Nombre del archivo para logging

    Returns:
        ComprobantePDFData con los campos extraídos
    """
    return _extract_and_parse(pdf_content, filename, _parse_bbva)


def extract_comprobante_pdf(pdf_content: bytes, filename: str) -> ComprobantePDFData:
    """
    Extrae datos de un comprobante de pago detectando el banco emisor.
    Soporta BBVA y BanBajío (BajioNet).

    Args:
        pdf_content: Contenido binario del PDF
        filename: Nombre del archivo para logging

    Returns:
        ComprobantePDFData con los campos extraídos
    """
    def _dispatch(raw_text: str, filename: str) -> ComprobantePDFData:
        if _detect_banco(raw_text) == "banbajio":
            return _parse_banbajio(raw_text, filename)
        return _parse_bbva(raw_text, filename)

    return _extract_and_parse(pdf_content, filename, _dispatch)


async def process_uploaded_pdf(file, filename: str) -> ComprobantePDFData:
    """
    Procesa un archivo PDF subido via FastAPI UploadFile.

    Args:
        file: Objeto UploadFile de FastAPI o similar con método read()
        filename: Nombre del archivo

    Returns:
        ComprobantePDFData con los datos extraídos
    """
    try:
        import inspect

        # Leer contenido
        if hasattr(file, 'read'):
            if inspect.iscoroutinefunction(file.read):
                content = await file.read()
            else:
                content = file.read()

            # Reset pointer si es posible
            if hasattr(file, 'seek'):
                if inspect.iscoroutinefunction(file.seek):
                    await file.seek(0)
                else:
                    file.seek(0)
        else:
            content = file

        return extract_comprobante_pdf(content, filename)

    except (OSError, ValueError, RuntimeError) as e:
        logger.error(f"Error leyendo archivo {filename}: {e}")
        return ComprobantePDFData(
            archivo=filename,
            error=f"Error leyendo archivo: {str(e)}"
        )


def process_pdf_bytes(content: bytes, filename: str) -> ComprobantePDFData:
    """
    Versión síncrona para procesar bytes directamente.

    Args:
        content: Bytes del PDF
        filename: Nombre del archivo

    Returns:
        ComprobantePDFData con los datos extraídos
    """
    return extract_comprobante_pdf(content, filename)
