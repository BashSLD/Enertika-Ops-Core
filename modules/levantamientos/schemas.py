# Archivo: modules/levantamientos/schemas.py

from typing import Optional, List
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field

class LevantamientoCreate(BaseModel):
    """Schema para que Comercial solicite un nuevo levantamiento."""
    id_sitio: UUID = Field(..., description="FK al sitio específico de la oportunidad.")
    solicitado_por_id: UUID = Field(..., description="Usuario Comercial que solicita.")
    # El status se inicializa en 'Solicitado'.

class LevantamientoUpdate(BaseModel):
    """Schema para que Ingeniería/Construcción gestionen la tarea."""
    tecnico_asignado_id: Optional[UUID] = Field(None, description="Ingeniero/Técnico que se asigna la tarea.")
    status_tarea: Optional[str] = Field(None, description="Status (Asignado, Ejecutado).")
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

    class Config:
        from_attributes = True