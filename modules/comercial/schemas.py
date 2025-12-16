# Archivo: modules/comercial/schemas.py

from typing import List, Optional
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field

# --- Base Schemas (Common Attributes) ---

class BaseSchema(BaseModel):
    """Base para campos comunes en lectura."""
    id: UUID = Field(..., alias='id_oportunidad')
    
    class Config:
        # Permite mapear alias (e.g., 'id_oportunidad' en la DB a 'id' en Python)
        populate_by_name = True
        # Permite la conversión de objetos de DB a Pydantic
        from_attributes = True


# --- 1. Oportunidades (tb_oportunidades) ---

class OportunidadCreate(BaseModel):
    """Schema para la creación inicial de una Oportunidad."""
    cliente_nombre: str = Field(..., min_length=3, description="Nombre del cliente.")
    # Asumimos que el ID del usuario autenticado proviene del contexto de la sesión
    creado_por_id: UUID = Field(..., description="UUID del usuario Comercial.")
    
    # Nota: op_id_estandar y status_global se generan en la lógica del router/service.

class OportunidadRead(BaseSchema):
    """Schema para la lectura de una Oportunidad."""
    op_id_estandar: str
    cliente_nombre: str
    status_global: str
    fecha_creacion: datetime
    creado_por_id: UUID


# --- 2. Sitios (tb_sitios_oportunidad) ---

class SitioOportunidadBase(BaseModel):
    """Campos base para un sitio, usados en la carga Multisitio (Excel)."""
    direccion: str = Field(..., description="Dirección física del sitio.")
    coordenadas: Optional[str] = Field(None, description="Latitud y Longitud.")
    tipo_tarifa: Optional[str] = Field(None, description="Tipo de tarifa eléctrica.")

class SitioOportunidadCreate(SitioOportunidadBase):
    """Schema de Creación para un sitio, si se inserta individualmente."""
    id_oportunidad: UUID

class SitioOportunidadRead(SitioOportunidadBase):
    """Schema de Lectura para un sitio."""
    id: UUID = Field(..., alias='id_sitio')
    id_oportunidad: UUID
    fecha_carga: datetime