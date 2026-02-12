"""
Schemas para BOM (Lista de Materiales).
Enums, modelos de entrada/salida para CRUD y workflow.
"""

from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field
from uuid import UUID
from datetime import date, datetime
from decimal import Decimal


class EstatusBOM(str, Enum):
    BORRADOR = "BORRADOR"
    EN_REVISION_ING = "EN_REVISION_ING"
    APROBADO_ING = "APROBADO_ING"
    EN_REVISION_CONST = "EN_REVISION_CONST"
    APROBADO = "APROBADO"


class AccionHistorial(str, Enum):
    CREADO = "CREADO"
    EDITADO = "EDITADO"
    ELIMINADO = "ELIMINADO"
    AGREGADO = "AGREGADO"
    RESTAURADO = "RESTAURADO"


class TipoAprobacion(str, Enum):
    ENVIO_REVISION_ING = "ENVIO_REVISION_ING"
    APROBACION_ING = "APROBACION_ING"
    RECHAZO_ING = "RECHAZO_ING"
    ENVIO_REVISION_CONST = "ENVIO_REVISION_CONST"
    APROBACION_CONST = "APROBACION_CONST"
    RECHAZO_CONST = "RECHAZO_CONST"
    SOLICITUD_MODIFICACION = "SOLICITUD_MODIFICACION"
    APROBACION_MODIFICACION = "APROBACION_MODIFICACION"


class TipoEntrega(str, Enum):
    RECOLECCION = "RECOLECCION"
    ENTREGA_SITIO = "ENTREGA_SITIO"
    ENTREGA_SEDE = "ENTREGA_SEDE"
    OTRO = "OTRO"


# --- BOM Cabecera ---

class BomCreate(BaseModel):
    id_proyecto: UUID
    responsable_ing: Optional[UUID] = None
    coordinador_obra: Optional[UUID] = None
    notas: Optional[str] = None


class BomRead(BaseModel):
    id_bom: UUID
    id_proyecto: UUID
    version: int
    estatus: EstatusBOM
    elaborado_por: UUID
    elaborado_por_nombre: Optional[str] = None
    responsable_ing: Optional[UUID] = None
    responsable_ing_nombre: Optional[str] = None
    coordinador_obra: Optional[UUID] = None
    coordinador_obra_nombre: Optional[str] = None
    fecha_envio_ing: Optional[datetime] = None
    fecha_aprobacion_ing: Optional[datetime] = None
    fecha_envio_const: Optional[datetime] = None
    fecha_aprobacion_const: Optional[datetime] = None
    notas: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # Campos calculados
    proyecto_nombre: Optional[str] = None
    proyecto_id_estandar: Optional[str] = None
    total_items: int = 0
    items_entregados: int = 0

    model_config = {"from_attributes": True}


# --- BOM Items ---

class BomItemCreate(BaseModel):
    id_categoria: Optional[int] = None
    descripcion: str = Field(..., min_length=1)
    cantidad: Decimal = Field(..., gt=0)
    unidad_medida: Optional[str] = None
    comentarios: Optional[str] = None
    precio_unitario: Optional[Decimal] = None
    origen_precio: Optional[str] = Field(default="MANUAL", pattern="^(CATALOGO|MANUAL)$")
    id_material_ref: Optional[UUID] = None


class BomItemUpdate(BaseModel):
    id_categoria: Optional[int] = None
    descripcion: Optional[str] = None
    cantidad: Optional[Decimal] = None
    unidad_medida: Optional[str] = None
    fecha_requerida: Optional[date] = None
    fecha_llegada_real: Optional[date] = None
    id_proveedor: Optional[UUID] = None
    tipo_entrega: Optional[str] = None
    fecha_estimada_entrega: Optional[date] = None
    comentarios: Optional[str] = None
    entregado: Optional[bool] = None
    precio_unitario: Optional[Decimal] = None
    origen_precio: Optional[str] = None


class BomItemRead(BaseModel):
    id_item: UUID
    id_bom: UUID
    id_categoria: Optional[int] = None
    categoria_nombre: Optional[str] = None
    descripcion: str
    cantidad: Decimal
    unidad_medida: Optional[str] = None
    fecha_requerida: Optional[date] = None
    fecha_llegada_real: Optional[date] = None
    id_proveedor: Optional[UUID] = None
    proveedor_nombre: Optional[str] = None
    tipo_entrega: Optional[str] = None
    fecha_estimada_entrega: Optional[date] = None
    comentarios: Optional[str] = None
    entregado: bool = False
    fecha_entrega_check: Optional[datetime] = None
    orden: int = 0
    activo: bool = True
    precio_unitario: Optional[Decimal] = None
    origen_precio: Optional[str] = "MANUAL"
    id_material_ref: Optional[UUID] = None
    importe: Optional[Decimal] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# --- Historial ---

class BomHistorialRead(BaseModel):
    id: int
    id_bom: UUID
    id_item: Optional[UUID] = None
    accion: AccionHistorial
    campo_modificado: Optional[str] = None
    valor_anterior: Optional[str] = None
    valor_nuevo: Optional[str] = None
    version_bom: int
    realizado_por: UUID
    realizado_por_nombre: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# --- Aprobaciones ---

class BomAprobacionRead(BaseModel):
    id: int
    id_bom: UUID
    tipo: TipoAprobacion
    version_bom: int
    usuario_id: UUID
    usuario_nombre: Optional[str] = None
    comentarios: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# --- Catalogos ---

class TipoEntregaCatalogo(BaseModel):
    id: int
    nombre: str
    activo: bool = True
    orden: int = 0
