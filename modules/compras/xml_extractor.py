# Archivo: modules/compras/xml_extractor.py
"""
Extractor de datos de facturas XML CFDI (3.3 y 4.0).
Parsea estructura SAT, extrae conceptos, detecta anticipos,
y extrae CFDI relacionados para trazabilidad.

Basado en prototipos validados con 663+ XMLs reales.
"""

import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from typing import Optional, List
import logging
import io

from .schemas import (
    CfdiData, CfdiConcepto, CfdiRelacionado,
    TipoFactura, XmlUploadError,
)

logger = logging.getLogger("ComprasXMLExtractor")

# Claves SAT para deteccion de anticipos
CLAVE_ANTICIPO = "84111506"
TIPO_RELACION_ANTICIPO = "07"

# Descripciones de tipos de relacion SAT
TIPOS_RELACION_SAT = {
    "01": "Nota de credito",
    "02": "Nota de debito",
    "03": "Devolucion de mercancia",
    "04": "Sustitucion de CFDI previo",
    "05": "Traslados de mercancia",
    "06": "Factura por traslado previo",
    "07": "CFDI por aplicacion de anticipo",
    "08": "Factura por pagos en parcialidades",
    "09": "Factura por pagos diferidos",
}

# Tamano maximo de XML (10 MB)
MAX_XML_SIZE_BYTES = 10 * 1024 * 1024


def _find_node(root: ET.Element, tag_name: str) -> Optional[ET.Element]:
    """Busca un nodo por nombre ignorando namespaces CFDI."""
    return root.find(f".//{{*}}{tag_name}")


def _find_all_nodes(root: ET.Element, tag_name: str) -> List[ET.Element]:
    """Busca todos los nodos por nombre ignorando namespaces."""
    return root.findall(f".//{{*}}{tag_name}")


def _get_attr(node: Optional[ET.Element], attr: str, default=None):
    """Extrae atributo de un nodo de forma segura."""
    if node is not None:
        return node.attrib.get(attr, default)
    return default


def _safe_decimal(value, default=None) -> Optional[Decimal]:
    """Convierte un valor a Decimal de forma segura."""
    if value is None:
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return default


def _detect_tipo_factura(
    conceptos: List[CfdiConcepto],
    relacionados: List[CfdiRelacionado],
) -> TipoFactura:
    """
    Detecta el tipo de factura segun reglas SAT:
    - ANTICIPO: ClaveProdServ=84111506 + descripcion contiene 'anticipo'
    - CIERRE_ANTICIPO: tiene CFDI relacionado con tipo_relacion=07
    - NORMAL: cualquier otro caso
    """
    # Verificar si es cierre de anticipo (tiene relacion tipo 07)
    for rel in relacionados:
        if rel.tipo_relacion == TIPO_RELACION_ANTICIPO:
            return TipoFactura.CIERRE_ANTICIPO

    # Verificar si es anticipo (clave SAT + descripcion)
    for concepto in conceptos:
        if concepto.clave_prod_serv == CLAVE_ANTICIPO:
            desc_lower = (concepto.descripcion or "").lower()
            if "anticipo" in desc_lower:
                return TipoFactura.ANTICIPO

    return TipoFactura.NORMAL


def _extract_conceptos(root: ET.Element) -> List[CfdiConcepto]:
    """Extrae la lista de conceptos/items del CFDI."""
    conceptos = []
    for node in _find_all_nodes(root, "Concepto"):
        descripcion = _get_attr(node, "Descripcion")
        if not descripcion:
            continue

        concepto = CfdiConcepto(
            descripcion=descripcion,
            cantidad=_safe_decimal(_get_attr(node, "Cantidad"), Decimal("0")),
            valor_unitario=_safe_decimal(_get_attr(node, "ValorUnitario"), Decimal("0")),
            importe=_safe_decimal(_get_attr(node, "Importe"), Decimal("0")),
            unidad=_get_attr(node, "Unidad"),
            clave_prod_serv=_get_attr(node, "ClaveProdServ"),
            clave_unidad=_get_attr(node, "ClaveUnidad"),
        )
        conceptos.append(concepto)

    return conceptos


def _extract_relacionados(root: ET.Element) -> List[CfdiRelacionado]:
    """Extrae los CFDI relacionados del comprobante."""
    relacionados = []
    rel_nodes = _find_all_nodes(root, "CfdiRelacionados")

    for rel_parent in rel_nodes:
        tipo_relacion = _get_attr(rel_parent, "TipoRelacion", "")

        for rel_child in rel_parent.findall(".//{*}CfdiRelacionado"):
            uuid_rel = _get_attr(rel_child, "UUID")
            if uuid_rel:
                relacionados.append(CfdiRelacionado(
                    uuid=uuid_rel.upper(),
                    tipo_relacion=tipo_relacion,
                    tipo_relacion_desc=TIPOS_RELACION_SAT.get(tipo_relacion),
                ))

    return relacionados


def parse_cfdi_xml(content: bytes, filename: str) -> CfdiData:
    """
    Parsea un XML CFDI y extrae todos los datos relevantes.

    Args:
        content: Bytes del archivo XML
        filename: Nombre del archivo para logging

    Returns:
        CfdiData con los datos extraidos

    Raises:
        ValueError: Si el XML no tiene la estructura minima requerida
    """
    # Validar tamano
    if len(content) > MAX_XML_SIZE_BYTES:
        raise ValueError(
            f"Archivo excede el limite de {MAX_XML_SIZE_BYTES // (1024*1024)}MB"
        )

    # Parsear XML
    try:
        tree = ET.parse(io.BytesIO(content))
        root = tree.getroot()
    except ET.ParseError as e:
        raise ValueError(f"XML mal formado: {e}")

    # Nodos principales
    emisor = _find_node(root, "Emisor")
    receptor = _find_node(root, "Receptor")
    timbre = _find_node(root, "TimbreFiscalDigital")

    # Extraer UUID (obligatorio)
    uuid = _get_attr(timbre, "UUID")
    if not uuid:
        raise ValueError("XML sin UUID (TimbreFiscalDigital no encontrado)")

    # Extraer RFC emisor (obligatorio)
    emisor_rfc = _get_attr(emisor, "Rfc")
    if not emisor_rfc:
        raise ValueError("XML sin RFC del emisor")

    # Extraer nombre emisor (obligatorio)
    emisor_nombre = _get_attr(emisor, "Nombre")
    if not emisor_nombre:
        raise ValueError("XML sin nombre del emisor")

    # Extraer total (obligatorio)
    total_str = _get_attr(root, "Total")
    total = _safe_decimal(total_str)
    if total is None:
        raise ValueError("XML sin monto total")

    # Extraer conceptos
    conceptos = _extract_conceptos(root)

    # Extraer CFDI relacionados
    relacionados = _extract_relacionados(root)

    # Detectar tipo de factura
    tipo_factura = _detect_tipo_factura(conceptos, relacionados)

    cfdi = CfdiData(
        archivo=filename,
        uuid=uuid.upper(),
        fecha=_get_attr(root, "Fecha", ""),
        total=total,
        subtotal=_safe_decimal(_get_attr(root, "SubTotal")),
        moneda=_get_attr(root, "Moneda", "MXN"),
        metodo_pago=_get_attr(root, "MetodoPago"),
        forma_pago=_get_attr(root, "FormaPago"),
        tipo_comprobante=_get_attr(root, "TipoDeComprobante"),
        emisor_rfc=emisor_rfc,
        emisor_nombre=emisor_nombre,
        receptor_rfc=_get_attr(receptor, "Rfc"),
        receptor_nombre=_get_attr(receptor, "Nombre"),
        conceptos=conceptos,
        relacionados=relacionados,
        tipo_factura=tipo_factura,
    )

    logger.info(
        "XML parseado: %s | UUID=%s | RFC=%s | Total=%s %s | Tipo=%s | Conceptos=%d | Relacionados=%d",
        filename, cfdi.uuid[:8], emisor_rfc, total, cfdi.moneda,
        tipo_factura.value, len(conceptos), len(relacionados),
    )

    return cfdi


def validate_xml_content(content: bytes, filename: str) -> Optional[str]:
    """
    Validacion rapida de un XML sin parseo completo.
    Retorna None si es valido, o un mensaje de error.
    """
    if len(content) > MAX_XML_SIZE_BYTES:
        return f"Archivo excede el limite de {MAX_XML_SIZE_BYTES // (1024*1024)}MB"

    if len(content) < 100:
        return "Archivo XML demasiado pequeno"

    # Verificar que parece un XML CFDI
    header = content[:500].decode("utf-8", errors="ignore").lower()
    if "comprobante" not in header and "cfdi" not in header:
        return "No parece ser un XML CFDI valido"

    return None


async def process_uploaded_xml(file, filename: str) -> CfdiData:
    """
    Procesa un XML subido via FastAPI UploadFile.

    Args:
        file: Objeto UploadFile de FastAPI
        filename: Nombre del archivo

    Returns:
        CfdiData con los datos extraidos

    Raises:
        ValueError: Si el XML no es valido o no tiene estructura CFDI
    """
    import inspect

    if hasattr(file, 'read'):
        if inspect.iscoroutinefunction(file.read):
            content = await file.read()
        else:
            content = file.read()

        if hasattr(file, 'seek'):
            if inspect.iscoroutinefunction(file.seek):
                await file.seek(0)
            else:
                file.seek(0)
    else:
        content = file

    # Validacion rapida
    error = validate_xml_content(content, filename)
    if error:
        raise ValueError(error)

    return parse_cfdi_xml(content, filename)
