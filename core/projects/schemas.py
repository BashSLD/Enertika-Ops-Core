# Archivo: core/projects/schemas.py
"""
Schemas Pydantic para gestión de Proyectos Gate.
"""

from typing import Optional, List
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict, field_validator


class ProyectoGateCreate(BaseModel):
    """Schema para creación de proyecto Gate."""
    id_oportunidad: UUID = Field(..., description="Oportunidad ganada a vincular")
    prefijo: str = Field(default="MX", max_length=10, description="Prefijo del proyecto")
    consecutivo: int = Field(..., gt=0, description="Número consecutivo único")
    id_tecnologia: int = Field(..., gt=0, description="ID de tecnología")
    nombre_corto: str = Field(..., min_length=1, max_length=100, description="Nombre descriptivo")
    
    @field_validator('prefijo')
    @classmethod
    def prefijo_uppercase(cls, v: str) -> str:
        return v.upper().strip()
    
    @field_validator('nombre_corto')
    @classmethod
    def nombre_corto_clean(cls, v: str) -> str:
        return v.strip()


class ProyectoGateRead(BaseModel):
    """Schema de lectura de proyecto Gate."""
    id_proyecto: UUID
    id_oportunidad: UUID
    proyecto_id_estandar: str
    status_fase: str
    aprobacion_direccion: bool
    fecha_aprobacion: Optional[datetime] = None
    prefijo: Optional[str] = None
    consecutivo: Optional[int] = None
    id_tecnologia: Optional[int] = None
    nombre_corto: Optional[str] = None
    sharepoint_url: Optional[str] = None
    created_at: Optional[datetime] = None
    created_by_id: Optional[UUID] = None
    
    # Campos joined
    tecnologia_nombre: Optional[str] = None
    oportunidad_nombre: Optional[str] = None
    cliente_nombre: Optional[str] = None
    op_id_estandar: Optional[str] = None
    creado_por_nombre: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)


class ProyectoGateListItem(BaseModel):
    """Schema simplificado para listas/dropdowns."""
    id_proyecto: UUID
    nombre: str  # proyecto_id_estandar
    consecutivo: Optional[int] = None
    tecnologia: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)


class OportunidadGanadaItem(BaseModel):
    """Schema para oportunidades ganadas disponibles."""
    id_oportunidad: UUID
    op_id_estandar: str
    nombre_proyecto: str
    cliente_nombre: str
    id_tecnologia: Optional[int] = None
    tecnologia_nombre: Optional[str] = None
    fecha_solicitud: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)


class TecnologiaItem(BaseModel):
    """Schema para catálogo de tecnologías."""
    id: int
    nombre: str
    
    model_config = ConfigDict(from_attributes=True)


class ValidarConsecutivoResponse(BaseModel):
    """Respuesta de validación de consecutivo."""
    consecutivo: int
    disponible: bool
    mensaje: str


class CrearProyectoResponse(BaseModel):
    """Respuesta de creación de proyecto."""
    success: bool
    proyecto: Optional[ProyectoGateRead] = None
    mensaje: str
