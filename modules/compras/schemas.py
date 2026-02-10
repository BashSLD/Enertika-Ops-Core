# Archivo: modules/compras/schemas.py
"""
Schemas Pydantic para el módulo Compras.
Incluye modelos para comprobantes de pago y catálogos.
"""

from typing import Optional, List
from datetime import date, datetime
from uuid import UUID
from decimal import Decimal
from pydantic import BaseModel, Field, ConfigDict, field_validator
from enum import Enum


# ========================================
# ENUMS
# ========================================

class EstatusComprobante(str, Enum):
    """Estados posibles de un comprobante."""
    PENDIENTE = "PENDIENTE"
    FACTURADO = "FACTURADO"


class MonedaComprobante(str, Enum):
    """Monedas soportadas."""
    MXN = "MXN"
    USD = "USD"


# ========================================
# COMPROBANTES DE PAGO
# ========================================

class ComprobanteBase(BaseModel):
    """Campos base de un comprobante."""
    fecha_pago: date
    beneficiario_orig: str = Field(..., min_length=1, max_length=500)
    monto: Decimal = Field(..., gt=0, decimal_places=2)
    moneda: MonedaComprobante = MonedaComprobante.MXN


class ComprobanteCreate(ComprobanteBase):
    """Schema para creación manual (si se necesita en futuro)."""
    pass


class ComprobanteUpdate(BaseModel):
    """Schema para actualización de comprobante."""
    id_zona: Optional[int] = None
    id_proyecto: Optional[UUID] = None
    id_categoria: Optional[int] = None
    id_proveedor: Optional[UUID] = None
    estatus: Optional[EstatusComprobante] = None
    
    model_config = ConfigDict(use_enum_values=True)


class ComprobanteBulkUpdate(BaseModel):
    """Schema para actualización masiva."""
    ids: List[UUID] = Field(..., min_length=1)
    updates: ComprobanteUpdate


class ComprobanteRead(ComprobanteBase):
    """Schema de lectura completa de comprobante."""
    id_comprobante: UUID
    estatus: EstatusComprobante
    uuid_factura: Optional[UUID] = None
    
    # Relaciones (IDs)
    id_proveedor: Optional[UUID] = None
    id_zona: Optional[int] = None
    id_proyecto: Optional[UUID] = None
    id_categoria: Optional[int] = None
    capturado_por_id: UUID
    
    # Campos calculados/joined
    comprador_nombre: Optional[str] = None
    proveedor_nombre: Optional[str] = None
    proveedor_rfc: Optional[str] = None
    zona_nombre: Optional[str] = None
    proyecto_nombre: Optional[str] = None
    categoria_nombre: Optional[str] = None
    
    # Timestamps
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)
    
    @field_validator('monto', mode='before')
    @classmethod
    def convert_decimal(cls, v):
        """Convierte Decimal a float para serialización."""
        if isinstance(v, Decimal):
            return float(v)
        return v


class ComprobanteListResponse(BaseModel):
    """Respuesta paginada de comprobantes."""
    items: List[ComprobanteRead]
    total: int
    page: int
    per_page: int
    pages: int


# ========================================
# RESULTADO DE CARGA DE PDFs
# ========================================

class PDFUploadError(BaseModel):
    """Detalle de error en carga de PDF."""
    archivo: str
    error: str


class PDFUploadDuplicate(BaseModel):
    """Detalle de duplicado detectado."""
    archivo: str
    fecha: str
    beneficiario: str
    monto: float
    moneda: str


class PDFUploadResult(BaseModel):
    """Resultado de la carga de PDFs."""
    insertados: int
    duplicados: List[PDFUploadDuplicate]
    errores: List[PDFUploadError]
    
    @property
    def total_procesados(self) -> int:
        return self.insertados + len(self.duplicados) + len(self.errores)


# ========================================
# CATÁLOGOS
# ========================================

class ZonaCompraRead(BaseModel):
    """Schema de zona de compra."""
    id: int
    nombre: str
    
    model_config = ConfigDict(from_attributes=True)


class CategoriaCompraRead(BaseModel):
    """Schema de categoría de compra."""
    id: int
    nombre: str
    
    model_config = ConfigDict(from_attributes=True)


class ProyectoGateRead(BaseModel):
    """Schema simplificado de proyecto para dropdown."""
    id_proyecto: UUID
    nombre: str  # proyecto_id_estandar
    
    model_config = ConfigDict(from_attributes=True)


class CatalogosComprasResponse(BaseModel):
    """Respuesta con todos los catálogos."""
    zonas: List[ZonaCompraRead]
    categorias: List[CategoriaCompraRead]
    proyectos: List[ProyectoGateRead]


# ========================================
# PROVEEDORES
# ========================================

class ProveedorBase(BaseModel):
    """Campos base de proveedor."""
    rfc: str = Field(..., min_length=12, max_length=13)
    razon_social: str = Field(..., min_length=1, max_length=500)
    nombre_comercial: Optional[str] = Field(None, max_length=500)


class ProveedorCreate(ProveedorBase):
    """Schema para creación de proveedor."""
    pass


class ProveedorRead(ProveedorBase):
    """Schema de lectura de proveedor."""
    id_proveedor: UUID
    activo: bool
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class ProveedorSearchResult(BaseModel):
    """Resultado de búsqueda de proveedor."""
    id_proveedor: UUID
    rfc: str
    razon_social: str
    nombre_comercial: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)


# ========================================
# FILTROS DE BÚSQUEDA
# ========================================

class ComprobanteFilter(BaseModel):
    """Filtros para búsqueda de comprobantes."""
    fecha_inicio: Optional[date] = None
    fecha_fin: Optional[date] = None
    estatus: Optional[str] = None
    id_zona: Optional[int] = None
    id_proyecto: Optional[UUID] = None
    id_categoria: Optional[int] = None
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=50, ge=1, le=500)

    @field_validator('fecha_inicio', 'fecha_fin', mode='before')
    @classmethod
    def validate_empty_date(cls, v):
        if not v or v == "":
            return None
        return v

    @field_validator('estatus', mode='before')
    @classmethod
    def validate_estatus(cls, v):
        if v == "TODOS" or not v:
            return None
        return v

    @field_validator('id_zona', 'id_categoria', mode='before')
    @classmethod
    def validate_empty_int(cls, v):
        if v is None or v == "" or v == "0":
            return None
        return v

    @field_validator('id_proyecto', mode='before')
    @classmethod
    def validate_uuid_empty(cls, v):
        if not v or v == "":
            return None
        if isinstance(v, str):
            try:
                return UUID(v)
            except ValueError:
                return None
        return v

class ComprobanteUpdateForm(BaseModel):
    """Formulario para actualizar un comprobante."""
    id_zona: Optional[int] = None
    id_proyecto: Optional[UUID] = None
    id_categoria: Optional[int] = None
    estatus: Optional[EstatusComprobante] = None
    
    @field_validator('id_proyecto', mode='before')
    @classmethod
    def validate_uuid_empty(cls, v):
        if not v or v == "":
            return None
        if isinstance(v, str):
            try:
                return UUID(v)
            except ValueError:
                return None
        return v



# ========================================
# ESTADÍSTICAS
# ========================================

class EstadisticasMes(BaseModel):
    """Estadísticas del mes actual."""
    total: int
    pendientes: int
    facturados: int
    total_mxn: float
    total_usd: float


# ========================================
# XML CFDI
# ========================================

class TipoFactura(str, Enum):
    """Tipo de factura detectado del XML CFDI."""
    NORMAL = "NORMAL"
    ANTICIPO = "ANTICIPO"
    CIERRE_ANTICIPO = "CIERRE_ANTICIPO"


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

    # Conceptos
    conceptos: List[CfdiConcepto] = []

    # CFDI relacionados
    relacionados: List[CfdiRelacionado] = []

    # Tipo detectado
    tipo_factura: TipoFactura = TipoFactura.NORMAL

    @field_validator('total', 'subtotal', mode='before')
    @classmethod
    def convert_decimal(cls, v):
        if v is None:
            return v
        if isinstance(v, (int, float, str)):
            return Decimal(str(v))
        return v


class XmlUploadError(BaseModel):
    """Detalle de error en carga de XML."""
    archivo: str
    error: str


class XmlMatchResult(BaseModel):
    """Resultado de matching de un XML con comprobantes."""
    cfdi: CfdiData
    match_type: str  # AUTO_MATCH, MONTO_MATCH, MULTIPLE_MATCH, NO_MATCH
    candidatos: List[dict] = []
    comprobante_id: Optional[UUID] = None


class XmlUploadResult(BaseModel):
    """Resultado de la carga de XMLs."""
    procesados: List[XmlMatchResult] = []
    duplicados: List[XmlUploadError] = []
    errores: List[XmlUploadError] = []

    @property
    def total(self) -> int:
        return len(self.procesados) + len(self.duplicados) + len(self.errores)

    @property
    def auto_matched(self) -> int:
        return sum(1 for r in self.procesados if r.match_type == "AUTO_MATCH")

    @property
    def pendientes_match(self) -> int:
        return sum(1 for r in self.procesados if r.match_type != "AUTO_MATCH")