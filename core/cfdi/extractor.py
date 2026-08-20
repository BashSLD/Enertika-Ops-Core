# core/cfdi/extractor.py
"""
Extractor de datos de facturas XML CFDI (3.3 y 4.0).
Parsea estructura SAT, extrae conceptos, detecta anticipos,
y extrae CFDI relacionados para trazabilidad.

Basado en prototipos validados con 663+ XMLs reales.
"""
from __future__ import annotations

import defusedxml.ElementTree as ET
from decimal import Decimal, InvalidOperation
from typing import Optional, List
import logging
import io
import re

from core.materials.normalizer import RE_MULTI_SPACE
from .schemas import (
    CfdiData, CfdiConcepto, CfdiRelacionado,
    TipoFactura,
)

# UsoCFDI de los complementos de pago (tipo P) -- regla SAT fija, no se valida contra el receptor
USO_CFDI_COMPLEMENTO_PAGO = "CP01"

logger = logging.getLogger("CfdiExtractor")

# Claves SAT para deteccion de anticipos y notas de credito
CLAVE_ANTICIPO = "84111506"
TIPO_RELACION_ANTICIPO = "07"
TIPO_RELACION_NOTA_CREDITO = "01"
TIPO_RELACION_PARCIALIDADES = "08"

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

# Guion-vineta pegado al inicio del texto (sin espacio), artefacto de formato
# de algunos proveedores: "-CABLE MULTICONDUCTOR..." -> "CABLE MULTICONDUCTOR..."
# No afecta guiones legitimos a media palabra (Wi-Fi) ni numeros de parte (THHN-2).
_RE_BULLET_DASH = re.compile(r'^-(?=\S)')


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


def _extract_pago_info(root: ET.Element) -> tuple[Optional[Decimal], str, Optional[Decimal]]:
    """
    Para CFDI tipo P (complemento de pago), extrae monto, moneda y tipo de cambio reales.

    Estrategia: leer MonedaP, sumar Monto y tomar TipoCambioP del primer nodo pago20:Pago.
    Si todos los pagos son en la misma moneda se devuelve esa moneda; si hay
    mezcla de monedas se devuelve MontoTotalPagos en MXN como fallback.

    Returns:
        (total, moneda, tipo_cambio) — e.g. (Decimal("30760.41"), "USD", Decimal("17.9697"))
        tipo_cambio es None si moneda == MXN o si no está en el XML.
    """
    pago_nodes = _find_all_nodes(root, "Pago")

    if pago_nodes:
        monedas = {_get_attr(n, "MonedaP", "MXN") for n in pago_nodes}
        if len(monedas) == 1:
            moneda = monedas.pop()
            total = sum(
                (_safe_decimal(_get_attr(n, "Monto"), Decimal("0")) for n in pago_nodes),
                Decimal("0"),
            )
            if total > 0:
                tipo_cambio = None
                if moneda != "MXN":
                    for nodo in pago_nodes:
                        tc_raw = _get_attr(nodo, "TipoCambioP")
                        if tc_raw and tc_raw != "1":
                            tipo_cambio = _safe_decimal(tc_raw)
                            break
                return total, moneda, tipo_cambio

    # Fallback: MontoTotalPagos siempre en MXN
    totales_node = _find_node(root, "Totales")
    if totales_node is not None:
        monto = _safe_decimal(_get_attr(totales_node, "MontoTotalPagos"))
        if monto is not None:
            return monto, "MXN", None

    return None, "MXN", None


def _detect_tipo_factura(
    conceptos: List[CfdiConcepto],
    relacionados: List[CfdiRelacionado],
    tipo_comprobante: Optional[str] = None,
) -> TipoFactura:
    """
    Detecta el tipo de factura segun reglas SAT:
    - NOTA_CREDITO: TipoDeComprobante=E + relacion tipo 01
    - CIERRE_ANTICIPO: tiene CFDI relacionado con tipo_relacion=07
      o la descripcion indica cierre de anticipo sin relacion SAT
    - ANTICIPO: ClaveProdServ=84111506 + descripcion contiene 'anticipo'
    - NORMAL: cualquier otro caso
    """
    # Verificar si es complemento de pago (tipo P)
    if tipo_comprobante == "P":
        return TipoFactura.PAGO

    # Verificar si es nota de credito (tipo E + relacion tipo 01)
    if tipo_comprobante == "E":
        for rel in relacionados:
            if rel.tipo_relacion == TIPO_RELACION_NOTA_CREDITO:
                return TipoFactura.NOTA_CREDITO

    # Verificar si es cierre de anticipo (tiene relacion tipo 07)
    for rel in relacionados:
        if rel.tipo_relacion == TIPO_RELACION_ANTICIPO:
            return TipoFactura.CIERRE_ANTICIPO

    # Fallback operativo: algunos XML de prueba/proveedor no declaran TipoRelacion=07.
    for concepto in conceptos:
        desc_lower = (concepto.descripcion or "").lower()
        if "cierre" in desc_lower and "anticipo" in desc_lower:
            return TipoFactura.CIERRE_ANTICIPO

    # Verificar si es anticipo (clave SAT + descripcion)
    for concepto in conceptos:
        if concepto.clave_prod_serv == CLAVE_ANTICIPO:
            desc_lower = (concepto.descripcion or "").lower()
            if "anticipo" in desc_lower:
                return TipoFactura.ANTICIPO

    return TipoFactura.NORMAL


def _sanitize_descripcion(texto: str) -> str:
    """Limpieza minima de formato del texto crudo del proveedor.

    Solo quita ruido de formato (espacios, guion-vineta inicial) — nunca
    normaliza contenido (mayusculas, acentos, etc.), eso es responsabilidad
    de core/materials/normalizer.py para el campo de busqueda difusa.
    """
    t = _RE_BULLET_DASH.sub("", texto.strip())
    t = RE_MULTI_SPACE.sub(" ", t)
    return t.strip()


def _extract_conceptos(root: ET.Element) -> List[CfdiConcepto]:
    """Extrae la lista de conceptos/items del CFDI."""
    conceptos = []
    for node in _find_all_nodes(root, "Concepto"):
        descripcion = _sanitize_descripcion(_get_attr(node, "Descripcion") or "")
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

    # Extraer tipo de comprobante (necesario para logica de total)
    tipo_comprobante = _get_attr(root, "TipoDeComprobante")

    # Extraer total, moneda y TC — para tipo P el nodo raiz siempre tiene Total="0" y Moneda="XXX"
    tipo_cambio_xml: Optional[Decimal] = None
    if tipo_comprobante == "P":
        total, moneda_pago, tipo_cambio_xml = _extract_pago_info(root)
        if total is None:
            raise ValueError("CFDI tipo Pago sin monto en complemento pago20")
    else:
        total_str = _get_attr(root, "Total")
        total = _safe_decimal(total_str)
        if total is None:
            raise ValueError("XML sin monto total")
        moneda_pago = None  # se lee del nodo raiz abajo
        moneda_raiz = _get_attr(root, "Moneda", "MXN")
        if moneda_raiz != "MXN":
            tc_raw = _get_attr(root, "TipoCambio")
            if tc_raw and tc_raw != "1":
                tipo_cambio_xml = _safe_decimal(tc_raw)

    # Extraer conceptos
    conceptos = _extract_conceptos(root)

    # Extraer CFDI relacionados
    relacionados = _extract_relacionados(root)

    # Detectar tipo de factura
    tipo_factura = _detect_tipo_factura(conceptos, relacionados, tipo_comprobante)

    cfdi = CfdiData(
        archivo=filename,
        uuid=uuid.upper(),
        fecha=_get_attr(root, "Fecha", ""),
        total=total,
        subtotal=_safe_decimal(_get_attr(root, "SubTotal")),
        moneda=moneda_pago or _get_attr(root, "Moneda", "MXN"),
        metodo_pago=_get_attr(root, "MetodoPago"),
        forma_pago=_get_attr(root, "FormaPago"),
        tipo_comprobante=_get_attr(root, "TipoDeComprobante"),
        emisor_rfc=emisor_rfc,
        emisor_nombre=emisor_nombre,
        receptor_rfc=_get_attr(receptor, "Rfc"),
        receptor_nombre=_get_attr(receptor, "Nombre"),
        receptor_cp=_get_attr(receptor, "DomicilioFiscalReceptor"),
        receptor_regimen_fiscal=_get_attr(receptor, "RegimenFiscalReceptor"),
        uso_cfdi=_get_attr(receptor, "UsoCFDI") or _get_attr(root, "UsoCFDI"),
        conceptos=conceptos,
        relacionados=relacionados,
        tipo_factura=tipo_factura,
        tipo_cambio_xml=tipo_cambio_xml,
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
