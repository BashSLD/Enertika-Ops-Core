# Archivo: modules/simulacion/schemas.py

from typing import Optional
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict

# --- Base Schemas ---

class SimulacionBase(BaseModel):
    """Campos comunes para la creación y actualización."""
    id_oportunidad: UUID = Field(..., description="FK a la oportunidad comercial.")
    tecnico_asignado_id: Optional[UUID] = Field(None, description="Técnico de Simulación responsable.")
    status_simulacion: str = Field(..., description="Status (Pendiente, En Proceso, Entregado, etc.).")

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