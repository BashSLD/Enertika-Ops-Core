# Archivo: core/materials/schemas.py
"""
Schemas Pydantic para el modulo de Materiales compartido.
"""

from typing import Optional, List
from datetime import date
from uuid import UUID
from decimal import Decimal
from pydantic import BaseModel, Field, field_validator


class MaterialFilter(BaseModel):
    """Filtros para busqueda de materiales."""
    id_proveedor: Optional[UUID] = None
    id_categoria: Optional[int] = None
    id_proyecto: Optional[UUID] = None
    fecha_inicio: Optional[date] = None
    fecha_fin: Optional[date] = None
    origen: Optional[str] = None
    q: Optional[str] = None
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=50, ge=1, le=500)

    @field_validator('fecha_inicio', 'fecha_fin', mode='before')
    @classmethod
    def validate_empty_date(cls, v):
        if not v or v == "":
            return None
        return v

    @field_validator('id_categoria', mode='before')
    @classmethod
    def validate_empty_int(cls, v):
        if v is None or v == "" or v == "0":
            return None
        return v

    @field_validator('id_proveedor', mode='before')
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

    @field_validator('id_proyecto', mode='before')
    @classmethod
    def validate_uuid_proyecto(cls, v):
        if not v or v == "":
            return None
        if isinstance(v, str):
            try:
                return UUID(v)
            except ValueError:
                return None
        return v

    @field_validator('origen', 'q', mode='before')
    @classmethod
    def validate_empty_str(cls, v):
        if not v or v == "TODOS":
            return None
        return v


class MaterialRead(BaseModel):
    """Schema de lectura de un material."""
    id: UUID
    uuid_factura: UUID
    id_comprobante: Optional[UUID] = None
    id_proveedor: UUID
    descripcion_proveedor: str
    descripcion_interna: Optional[str] = None
    cantidad: Decimal
    precio_unitario: Decimal
    importe: Decimal
    unidad: Optional[str] = None
    clave_prod_serv: Optional[str] = None
    clave_unidad: Optional[str] = None
    id_categoria: Optional[int] = None
    origen: Optional[str] = None
    fecha_factura: date

    # Joined fields
    proveedor_nombre: Optional[str] = None
    proveedor_rfc: Optional[str] = None
    categoria_nombre: Optional[str] = None
    proyecto_nombre: Optional[str] = None


class MaterialUpdate(BaseModel):
    """Schema para edicion de un material (solo clasificacion interna)."""
    descripcion_interna: Optional[str] = None
    id_categoria: Optional[int] = None


class MaterialPrecioAnalisis(BaseModel):
    """Analisis de precios de un material por proveedor."""
    proveedor_nombre: str
    proveedor_rfc: str
    min_precio: Decimal
    max_precio: Decimal
    avg_precio: Decimal
    total_compras: int
    ultima_compra: Optional[date] = None
