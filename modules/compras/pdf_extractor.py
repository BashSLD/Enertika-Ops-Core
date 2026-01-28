# Archivo: modules/compras/pdf_extractor.py
"""
Extractor de datos de comprobantes de pago BBVA.
Validado con 120+ archivos PDF.
"""

import pdfplumber
import re
import io
from datetime import datetime
from typing import Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger("ComprasPDFExtractor")


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


def extract_from_bbva_pdf(pdf_content: bytes, filename: str) -> ComprobantePDFData:
    """
    Extrae datos de un comprobante BBVA.
    
    Args:
        pdf_content: Contenido binario del PDF
        filename: Nombre del archivo para logging
        
    Returns:
        ComprobantePDFData con los campos extraídos
    """
    result = ComprobantePDFData(archivo=filename)
    
    try:
        with pdfplumber.open(io.BytesIO(pdf_content)) as pdf:
            if not pdf.pages:
                result.error = "PDF sin páginas"
                return result
                
            raw_text = pdf.pages[0].extract_text()
            if not raw_text:
                result.error = "No se pudo extraer texto del PDF"
                return result
            
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
            match_monto = re.search(r'Importe.*?\$?\s*([\d,]+\.\d{2})', raw_text)
            if match_monto:
                monto_str = match_monto.group(1).replace(',', '')
                try:
                    result.monto = float(monto_str)
                except ValueError:
                    logger.warning(f"[{filename}] Monto inválido: {monto_str}")
            
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
            
            # Validar datos mínimos
            if not result.fecha_pago:
                result.error = "No se encontró fecha de pago"
            elif not result.monto:
                result.error = "No se encontró monto"
            elif not result.beneficiario:
                result.error = "No se encontró beneficiario"
                
    except Exception as e:
        logger.error(f"Error procesando PDF {filename}: {e}", exc_info=True)
        result.error = f"Error de procesamiento: {str(e)}"
    
    return result


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
            
        return extract_from_bbva_pdf(content, filename)
        
    except Exception as e:
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
    return extract_from_bbva_pdf(content, filename)
