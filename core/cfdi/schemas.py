# core/cfdi/schemas.py
"""Schemas Pydantic del parser CFDI compartido (Compras/Finanzas/futuro Construccion)."""

from typing import Optional, List
from decimal import Decimal
from pydantic import BaseModel, field_validator
from enum import Enum


class TipoFactura(str, Enum):
    """Tipo de factura detectado del XML CFDI."""
    NORMAL = "NORMAL"
    ANTICIPO = "ANTICIPO"
    CIERRE_ANTICIPO = "CIERRE_ANTICIPO"
    NOTA_CREDITO = "NOTA_CREDITO"
    PAGO = "PAGO"  # CFDI complemento de pago (TipoDeComprobante="P")


class TipoComprobanteSAT(str, Enum):
    """Tipos de comprobante segun catalogo SAT."""
    INGRESO = "I"
    EGRESO = "E"
    TRASLADO = "T"
    PAGO = "P"


class CfdiConcepto(BaseModel):
    """Concepto/item extraido de un CFDI."""
    descripcion: str
    cantidad: Decimal
    valor_unitario: Decimal
    importe: Decimal
    unidad: Optional[str] = None
    clave_prod_serv: Optional[str] = None
    clave_unidad: Optional[str] = None


class CfdiRelacionado(BaseModel):
    """CFDI relacionado extraido del XML."""
    uuid: str
    tipo_relacion: str
    tipo_relacion_desc: Optional[str] = None


class CfdiData(BaseModel):
    """Datos completos extraidos de un XML CFDI."""
    archivo: str
    uuid: str
    fecha: str
    total: Decimal
    subtotal: Optional[Decimal] = None
    moneda: str = "MXN"
    metodo_pago: Optional[str] = None
    forma_pago: Optional[str] = None
    tipo_comprobante: Optional[str] = None

    # Emisor (proveedor)
    emisor_rfc: str
    emisor_nombre: str

    # Receptor
    receptor_rfc: Optional[str] = None
    receptor_nombre: Optional[str] = None
    receptor_cp: Optional[str] = None
    receptor_regimen_fiscal: Optional[str] = None
    uso_cfdi: Optional[str] = None

    # Conceptos
    conceptos: List[CfdiConcepto] = []

    # CFDI relacionados
    relacionados: List[CfdiRelacionado] = []

    # Tipo detectado
    tipo_factura: TipoFactura = TipoFactura.NORMAL

    # Tipo de cambio SAT-certificado al momento de timbrar (None si moneda=MXN)
    tipo_cambio_xml: Optional[Decimal] = None

    @field_validator('total', 'subtotal', mode='before')
    @classmethod
    def convert_decimal(cls, v):
        if v is None:
            return v
        if isinstance(v, (int, float, str)):
            return Decimal(str(v))
        return v
