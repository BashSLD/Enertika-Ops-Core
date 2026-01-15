from typing import Optional, List
from datetime import datetime
from uuid import UUID
from decimal import Decimal
from pydantic import BaseModel, Field, ConfigDict, field_validator

# --- Base Schemas ---

class SimulacionBase(BaseModel):
    """Campos base para lecturas comunes."""
    id_oportunidad: UUID
    id_estatus_global: int
    status_nombre: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)

class ResponsableOption(BaseModel):
    """Schema para el dropdown de responsables (Select)."""
    id_usuario: UUID
    nombre_completo: str
    departamento: str
    
    model_config = ConfigDict(from_attributes=True)

# --- BESS Schemas (Preservado para Creación) ---

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

# --- Oportunidades Create Completo (Preservado para Creación) ---

class OportunidadCreateCompleta(BaseModel):
    """Schema maestro para la creación transaccional (Formulario Extraordinario)."""
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
    fecha_manual_str: Optional[str] = None
    detalles_bess: Optional[DetalleBessCreate] = None
    id_estatus_global: Optional[int] = 1

    model_config = ConfigDict(from_attributes=True)

# --- Update Schemas (Lógica de Negocio V2 - NUEVO) ---

class SimulacionUpdate(BaseModel):
    """
    Schema maestro para actualizar la Oportunidad desde Simulación.
    Maneja cambio de estatus, re-asignaciones y datos de cierre.
    """
    # Gestión
    id_interno_simulacion: Optional[str] = Field(None, max_length=150)
    responsable_simulacion_id: Optional[UUID] = None
    
    # Fechas
    fecha_entrega_simulacion: Optional[datetime] = None
    deadline_negociado: Optional[datetime] = None
    
    # Estatus y Cierre
    id_estatus_global: int
    id_motivo_cierre: Optional[int] = None
    
    # Métricas de Cierre (Obligatorios condicionalmente en Service Layer)
    monto_cierre_usd: Optional[Decimal] = Field(None, ge=0)
    potencia_cierre_fv_kwp: Optional[Decimal] = Field(None, ge=0)
    capacidad_cierre_bess_kwh: Optional[Decimal] = Field(None, ge=0)

    # Flag auxiliar para validación (no persiste en BD)
    tiene_detalles_bess: Optional[bool] = False

    model_config = ConfigDict(from_attributes=True)

    @field_validator(
        'id_interno_simulacion', 
        'responsable_simulacion_id', 
        'fecha_entrega_simulacion', 
        'deadline_negociado', 
        'id_motivo_cierre', 
        'monto_cierre_usd', 
        'potencia_cierre_fv_kwp', 
        'capacidad_cierre_bess_kwh',
        mode='before'
    )
    def empty_string_to_none(cls, v, info):
        if v == "":
            return None
        # Enforce Uppercase for ID
        if info.field_name == 'id_interno_simulacion' and isinstance(v, str):
            return v.upper()
        return v

class SitiosBatchUpdate(BaseModel):
    """
    Para la actualización masiva de hijos (Multisitio).
    """
    ids_sitios: List[UUID]  # IDs de la tabla tb_sitios_oportunidad
    id_estatus_global: int
    fecha_cierre: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)

# --- Read Schemas (Legacy/UI support) ---

class SimulacionRead(BaseModel):
    """Schema de lectura para el Dashboard."""
    id_oportunidad: UUID
    status_simulacion: str
    # Se pueden agregar más campos calculados si se requiere en el futuro
    model_config = ConfigDict(from_attributes=True)