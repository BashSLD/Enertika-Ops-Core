# Archivo: modules/comercial/schemas.py

from typing import List, Optional, Any
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field, field_validator, ConfigDict

# --- Base Schemas (Common Attributes) ---

class BaseSchema(BaseModel):
    """Base para campos comunes en lectura."""
    id: UUID = Field(..., alias='id_oportunidad')
    
    model_config = ConfigDict(
        populate_by_name=True,  # v2: permite usar alias o nombre del campo
        from_attributes=True    # v2: reemplaza a orm_mode
    )


# --- BESS Schemas (NUEVO) ---

class DetalleBessCreate(BaseModel):
    """Datos técnicos específicos para proyectos BESS."""
    cargas_criticas_kw: Optional[float] = None
    tiene_motores: bool = False
    potencia_motor_hp: Optional[float] = None
    tiempo_autonomia: Optional[str] = None
    voltaje_operacion: Optional[str] = None
    cargas_separadas: bool = False
    objetivos_json: List[str] = []
    tiene_planta_emergencia: bool = False

    model_config = ConfigDict(from_attributes=True)


# --- Oportunidades Create Completo (Transaccional) ---

class OportunidadCreateCompleta(BaseModel):
    """Schema maestro para la creación transaccional."""
    # Campos Base
    cliente_nombre: str = Field(..., min_length=3)
    nombre_proyecto: str
    canal_venta: str
    id_tecnologia: int
    id_tipo_solicitud: int
    cantidad_sitios: int
    prioridad: str
    direccion_obra: str
    coordenadas_gps: Optional[str] = None
    google_maps_link: Optional[str] = None
    sharepoint_folder_url: Optional[str] = None
    
    # Campos Lógicos Fase 2
    fecha_manual_str: Optional[str] = None  # Input raw del datetime-local
    detalles_bess: Optional[DetalleBessCreate] = None  # Nested Schema opcional

    model_config = ConfigDict(from_attributes=True)


# --- Oportunidad Cierre/Status (NUEVO) ---

class OportunidadCierreUpdate(BaseModel):
    """Schema para cerrar, perder o cancelar."""
    id_motivo_cierre: int
    comentarios_cierre: str
    monto_cierre_usd: Optional[float] = 0.0
    potencia_final_fv_kwp: Optional[float] = 0.0
    potencia_final_bess_kw: Optional[float] = 0.0  # Nuevo campo BESS
    capacidad_final_bess_kwh: Optional[float] = 0.0  # Nuevo campo BESS


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
    
    model_config = ConfigDict(populate_by_name=True)
    
    @field_validator('numero_servicio', mode='before')
    @classmethod
    def convert_to_string(cls, v: Any) -> Optional[str]:
        """Convierte ints/floats del Excel a string."""
        if v is None:
            return None
        return str(v) if not isinstance(v, str) else v


# --- 3. Listado de Oportunidades (para get_oportunidades_list) ---

class OportunidadListOut(BaseModel):
    """Schema para el listado de oportunidades con información resumida y JOINs."""
    id_oportunidad: UUID
    titulo_proyecto: str
    nombre_proyecto: str
    cliente_nombre: str
    fecha_solicitud: datetime
    status_global: str
    email_enviado: bool
    id_interno_simulacion: str
    tipo_solicitud: str
    deadline_calculado: Optional[datetime] = None
    cantidad_sitios: Optional[int] = None
    responsable_simulacion: Optional[str] = None
    solicitado_por: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)
