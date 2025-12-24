# Archivo: modules/comercial/schemas.py

from typing import List, Optional
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field, field_validator

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
    tipo_tarifa: Optional[str] = Field(None, description="Tipo de tarifa eléctrica.")
    numero_servicio: Optional[str] = Field(None, description="Número de servicio.")
    comentarios: Optional[str] = Field(None, description="Comentarios adicionales.")

class SitioOportunidadCreate(SitioOportunidadBase):
    """Schema de Creación para un sitio, si se inserta individualmente."""
    id_oportunidad: UUID

class SitioOportunidadRead(SitioOportunidadBase):
    """Schema de Lectura para un sitio."""
    id: UUID = Field(..., alias='id_sitio')
    id_oportunidad: UUID
    fecha_carga: datetime

class SitioImportacion(BaseModel):
    """Schema para validar la data JSON de la carga masiva en memoria."""
    nombre_sitio: str = Field(..., alias='NOMBRE')
    direccion: str = Field(..., alias='DIRECCION')
    tipo_tarifa: Optional[str] = Field(None, alias='TARIFA')
    google_maps_link: Optional[str] = Field(None, alias='LINK GOOGLE')
    numero_servicio: Optional[str] = Field(None, alias='# DE SERVICIO')
    comentarios: Optional[str] = Field(None, alias='COMENTARIOS')
    
    class Config:
        populate_by_name = True  # Permite usar tanto alias como nombres de campo
    
    @staticmethod
    def convert_to_string(v):
        """Convierte ints/floats del Excel a string."""
        if v is None:
            return None
        return str(v) if not isinstance(v, str) else v
    
    # Validators para convertir números a string
    _numero_servicio_validator = field_validator('numero_servicio', mode='before')(convert_to_string.__func__)
