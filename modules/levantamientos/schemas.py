# Archivo: modules/levantamientos/schemas.py

from typing import Optional, List
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict

class LevantamientoCreate(BaseModel):
    """Schema para que Comercial solicite un nuevo levantamiento."""
    id_sitio: UUID = Field(..., description="FK al sitio específico de la oportunidad.")
    solicitado_por_id: UUID = Field(..., description="Usuario Comercial que solicita.")
    # El status se inicializa en 'Solicitado'.

class LevantamientoUpdate(BaseModel):
    """Schema para que Ingeniería/Construcción gestionen la tarea."""
    tecnico_asignado_id: Optional[UUID] = Field(None, description="Técnico asignado al levantamiento.")
    jefe_area_id: Optional[UUID] = Field(None, description="Jefe de área responsable.")
    id_estatus_global: Optional[int] = Field(None, description="Estado del levantamiento (8-13).", ge=8, le=13)
    fecha_visita_programada: Optional[datetime] = Field(None, description="Fecha programada para la visita.")
    evidencia_docs_url: Optional[str] = Field(None, description="URL de la carpeta de SharePoint con fotos/docs.")

class LevantamientoRead(BaseModel):
    """Schema de lectura para la cola de tareas."""
    id_levantamiento: UUID
    id_sitio: UUID
    solicitado_por_id: UUID
    tecnico_asignado_id: Optional[UUID]
    fecha_solicitud: datetime
    status_tarea: str
    evidencia_docs_url: Optional[str]

    model_config = ConfigDict(from_attributes=True)