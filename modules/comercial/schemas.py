from typing import List, Optional, Any
from datetime import datetime, date
from uuid import UUID
from pydantic import BaseModel, Field, field_validator, ConfigDict


class DetalleBessCreate(BaseModel):
    """Datos técnicos específicos para proyectos BESS."""
    # Pregunta raíz: ¿Cómo usarás tu Sistema de almacenamiento?
    uso_sistema_json: List[str] = []
    
    cargas_criticas_kw: Optional[float] = None
    tiene_motores: bool = False
    potencia_motor_hp: Optional[float] = None
    tiempo_autonomia: Optional[str] = None
    voltaje_operacion: Optional[str] = None
    cargas_separadas: bool = False
    tiene_planta_emergencia: bool = False

    model_config = ConfigDict(from_attributes=True)


class OportunidadCreateCompleta(BaseModel):
    """Schema maestro para la creación transaccional."""
    cliente_nombre: str = Field(..., min_length=3)
    nombre_proyecto: str = Field(..., min_length=2)
    canal_venta: str
    id_tecnologia: int
    id_tipo_solicitud: int
    cantidad_sitios: int = Field(..., ge=1, le=500)
    prioridad: str
    direccion_obra: str

    @field_validator('prioridad')
    @classmethod
    def validate_prioridad(cls, v: str) -> str:
        allowed = {'baja', 'normal', 'alta', 'urgente'}
        if v.lower() not in allowed:
            raise ValueError(f"Prioridad debe ser una de: {', '.join(allowed)}")
        return v.lower()

    @field_validator('nombre_proyecto')
    @classmethod
    def validate_nombre_proyecto(cls, v: str) -> str:
        return v.strip()
    coordenadas_gps: Optional[str] = None
    google_maps_link: Optional[str] = None
    sharepoint_folder_url: Optional[str] = None
    fecha_manual_str: Optional[str] = None
    detalles_bess: Optional[DetalleBessCreate] = None
    id_estatus_global: Optional[int] = None
    
    # Campo para búsqueda inteligente de clientes
    cliente_id: Optional[UUID] = None
    
    # Nuevos Campos v2 (Clasificación)
    solicitado_por_id: Optional[UUID] = None
    clasificacion_solicitud: str = "NORMAL"
    es_licitacion: bool = False
    fecha_ideal_usuario: Optional[date] = None

    model_config = ConfigDict(from_attributes=True)





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


