# Archivo: modules/simulacion/schemas.py

from typing import Optional, List
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict

# --- Base Schemas ---

class SimulacionBase(BaseModel):
    """Campos comunes para la creación y actualización."""
    id_oportunidad: UUID = Field(..., description="FK a la oportunidad comercial.")
    tecnico_asignado_id: Optional[UUID] = Field(None, description="Técnico de Simulación responsable.")
    status_simulacion: str = Field(..., description="Status (Pendiente, En Proceso, Entregado, etc.).")

# --- BESS Schemas ---

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
    id_estatus_global: Optional[int] = 1  # 1=Activa por defecto

    model_config = ConfigDict(from_attributes=True)

class SimulacionCreate(SimulacionBase):
    """Schema para crear una nueva entrada de simulación."""
    # Los tiempos se inician al crear
    pass

class SimulacionUpdate(BaseModel):
    """Schema para actualizar el estado, asignación o el dato crítico."""
    tecnico_asignado_id: Optional[UUID] = None
    status_simulacion: Optional[str] = None
    
    # Dato Crítico: KWp
    potencia_simulada_kwp: Optional[float] = Field(None, ge=0.0, description="Potencia Simulada (KWp). Debe ser capturada al entregar.")

class SimulacionRead(BaseModel):
    """Schema de lectura para la vista del Dashboard de Simulación."""
    id_simulacion: UUID
    id_oportunidad: UUID
    tecnico_asignado_id: Optional[UUID]
    
    # Tiempos para KPIs
    fecha_solicitud: datetime
    deadline_estimado: Optional[datetime]
    fecha_entrega_real: Optional[datetime]

    # Dato Crítico
    potencia_simulada_kwp: Optional[float]
    status_simulacion: str

    model_config = ConfigDict(from_attributes=True)