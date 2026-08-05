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
    EN_REVISION_OBRA = "EN_REVISION_OBRA"
    EN_REVISION_CONST = "EN_REVISION_CONST"
    APROBADO_CONST = "APROBADO_CONST"
    EN_REVISION_FINAL = "EN_REVISION_FINAL"
    APROBADO_FINAL = "APROBADO_FINAL"
    CANCELADO = "CANCELADO"


class TipoAlcanceBOM(str, Enum):
    COMPLETO = "COMPLETO"
    PARCIAL = "PARCIAL"
    LEGACY = "LEGACY"


class EstadoPaqueteBOM(str, Enum):
    ACTIVO = "ACTIVO"
    ARCHIVADO = "ARCHIVADO"
    CANCELADO = "CANCELADO"


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
    ENVIO_REVISION_OBRA = "ENVIO_REVISION_OBRA"
    APROBACION_OBRA = "APROBACION_OBRA"
    RECHAZO_OBRA = "RECHAZO_OBRA"
    ENVIO_REVISION_CONST = "ENVIO_REVISION_CONST"
    APROBACION_CONST = "APROBACION_CONST"
    RECHAZO_CONST = "RECHAZO_CONST"
    DEVOLUCION_BORRADOR = "DEVOLUCION_BORRADOR"
    CANCELACION = "CANCELACION"
    SOLICITUD_MODIFICACION = "SOLICITUD_MODIFICACION"
    APROBACION_MODIFICACION = "APROBACION_MODIFICACION"
    ENVIO_REVISION_FINAL = "ENVIO_REVISION_FINAL"
    APROBACION_FINAL = "APROBACION_FINAL"
    RECHAZO_FINAL = "RECHAZO_FINAL"


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


class BomPaqueteCreate(BaseModel):
    tipo_alcance: TipoAlcanceBOM
    nombre: str = Field(..., min_length=1, max_length=160)
    descripcion_alcance: Optional[str] = None


class BomPaqueteRead(BaseModel):
    id_paquete: UUID
    id_proyecto: UUID
    codigo: str
    nombre: str
    tipo_alcance: TipoAlcanceBOM
    descripcion_alcance: Optional[str] = None
    estado_paquete: EstadoPaqueteBOM
    lock_version: int = 0
    creado_por: UUID
    ingeniero_responsable_id: UUID
    responsable_ing_id: Optional[UUID] = None
    coordinador_obra_id: Optional[UUID] = None
    jefe_construccion_id: Optional[UUID] = None
    cabeza_trabajo_id: Optional[UUID] = None
    cabeza_oficial_id: Optional[UUID] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class BomRead(BaseModel):
    id_bom: UUID
    id_proyecto: UUID
    id_paquete: Optional[UUID] = None
    version: int
    estatus: EstatusBOM
    elaborado_por: UUID
    ingeniero_responsable_id: Optional[UUID] = None
    lock_version: int = 0
    elaborado_por_nombre: Optional[str] = None
    responsable_ing: Optional[UUID] = None
    responsable_ing_nombre: Optional[str] = None
    jefe_construccion: Optional[UUID] = None
    jefe_construccion_nombre: Optional[str] = None
    coordinador_obra: Optional[UUID] = None
    coordinador_obra_nombre: Optional[str] = None
    fecha_envio_ing: Optional[datetime] = None
    fecha_aprobacion_ing: Optional[datetime] = None
    fecha_envio_obra: Optional[datetime] = None
    fecha_aprobacion_obra: Optional[datetime] = None
    fecha_envio_const: Optional[datetime] = None
    fecha_aprobacion_const: Optional[datetime] = None
    fecha_envio_final: Optional[datetime] = None
    fecha_aprobacion_final: Optional[datetime] = None
    notas: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    modulos_fv_snapshot: Optional[int] = None
    potencia_pico_kwp_snapshot: Optional[Decimal] = None
    tipo_cambio_aprobacion: Optional[Decimal] = None
    fecha_tipo_cambio_aprobacion: Optional[date] = None
    total_aprobado_mxn: Optional[Decimal] = None
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
    tipo_partida: Optional[str] = Field(default="MATERIAL", pattern="^(MATERIAL|MANO_OBRA|SERVICIO|LEGALIZACION|EQUIPO)$")
    moneda: Optional[str] = Field(default="MXN", pattern="^(MXN|USD)$")


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
    precio_real: Optional[Decimal] = None
    origen_precio: Optional[str] = None
    cantidad_recibida: Optional[Decimal] = None
    tipo_partida: Optional[str] = None
    moneda: Optional[str] = Field(default=None, pattern="^(MXN|USD)$")
    moneda_real: Optional[str] = Field(default=None, pattern="^(MXN|USD)$")
    estatus_ejecucion: Optional[str] = None


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
    precio_base: Optional[Decimal] = None
    precio_real: Optional[Decimal] = None
    origen_precio: Optional[str] = "MANUAL"
    id_material_ref: Optional[UUID] = None
    importe: Optional[Decimal] = None
    importe_real: Optional[Decimal] = None
    cantidad_recibida: Decimal = Decimal("0")
    grupos: List[str] = []
    tipo_partida: str = "MATERIAL"
    estatus_compra: Optional[str] = None
    estatus_ejecucion: Optional[str] = None
    moneda: Optional[str] = "MXN"
    moneda_real: Optional[str] = "MXN"
    costo_mxn: Optional[Decimal] = None
    costo_real_mxn: Optional[Decimal] = None
    gasto_real: Optional[Decimal] = None
    comentarios_operativos: Optional[str] = None
    id_item_origen: Optional[UUID] = None
    tipo_origen_item: str = "BASE"
    id_item_reemplazado: Optional[UUID] = None
    motivo_adenda: Optional[str] = None
    creado_en_adenda: Optional[UUID] = None
    bloqueado: bool = False
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


class GrupoBomRead(BaseModel):
    id: int
    codigo: str
    nombre: str
    orden: int = 0
    activo: bool = True


class SuplenciaCreate(BaseModel):
    suplente_id: UUID
    fecha_fin: date


class SuplenciaRead(BaseModel):
    id: int
    titular_id: UUID
    suplente_id: UUID
    suplente_nombre: Optional[str] = None
    fecha_fin: date
    activo: bool = True
    created_at: Optional[datetime] = None
    model_config = {"from_attributes": True}


# --- Autorizaciones de Compra (Fase D) ---

class EstatusAutorizacion(str, Enum):
    PENDIENTE = "PENDIENTE"
    AUTORIZADO_OBRA = "AUTORIZADO_OBRA"
    AUTORIZADO_DIRECCION = "AUTORIZADO_DIRECCION"
    AUTORIZADO_FINANZAS = "AUTORIZADO_FINANZAS"
    RECHAZADO = "RECHAZADO"


class EstatusCotizacionAprobacion(str, Enum):
    """Estados de tb_bom_cotizacion_aprobaciones (mismo dominio que el CHECK de la migracion 137)."""
    PENDIENTE_DIRECCION = "PENDIENTE_DIRECCION"
    APROBADA = "APROBADA"
    RECHAZADA = "RECHAZADA"
    REEMPLAZADA = "REEMPLAZADA"
    CANCELADA_PROVEEDOR = "CANCELADA_PROVEEDOR"


class BomAutorizacionRead(BaseModel):
    id: UUID
    cotizacion_id: UUID
    bom_id: UUID
    proyecto_id: UUID
    monto_total: Optional[Decimal] = None
    moneda: str = "MXN"
    tipo_cambio_snapshot: Optional[Decimal] = None
    estatus: EstatusAutorizacion

    # Paso 1 — Coordinador de Obra
    aprobador_obra_id: Optional[UUID] = None
    aprobador_obra_nombre: Optional[str] = None
    fecha_aprobacion_obra: Optional[datetime] = None
    nota_obra: Optional[str] = None

    # Paso 2 — Director
    aprobador_direccion_id: Optional[UUID] = None
    aprobador_direccion_nombre: Optional[str] = None
    fecha_aprobacion_direccion: Optional[datetime] = None
    nota_direccion: Optional[str] = None

    # Paso 3 — Finanzas
    aprobador_finanzas_id: Optional[UUID] = None
    aprobador_finanzas_nombre: Optional[str] = None
    fecha_aprobacion_finanzas: Optional[datetime] = None
    nota_finanzas: Optional[str] = None

    # Rechazo
    rechazado_en_paso: Optional[str] = None
    rechazado_por: Optional[UUID] = None
    rechazado_por_nombre: Optional[str] = None
    motivo_rechazo: Optional[str] = None
    fecha_rechazo: Optional[datetime] = None

    # Auditoría
    creado_por: Optional[UUID] = None
    creado_en: Optional[datetime] = None

    # Desnormalizados (de cotización)
    nombre_proveedor: Optional[str] = None

    model_config = {"from_attributes": True}
