# Archivo: modules/proyectos/schemas.py

from typing import Optional
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field

# --- Ficha de Traspaso (Gate 1) ---

class TraspasoProyectoCreate(BaseModel):
    """
    Se activa cuando Comercial marca "Cierre de Venta" y se usa como payload
    para el Gate 1 de Dirección.
    """
    id_oportunidad: UUID = Field(..., description="Oportunidad cerrada que se convertirá en proyecto.")
    # El status_fase inicial es 'Ingeniería'
    
class ProyectoRead(BaseModel):
    """Schema de lectura principal del proyecto."""
    id_proyecto: UUID
    id_oportunidad: UUID
    proyecto_id_estandar: str = Field(..., description="ID de Proyecto (Diferente al OP).")
    status_fase: str = Field(..., description="Fase actual (Ingeniería, Construcción, O&M).")
    aprobacion_direccion: bool = Field(..., description="Gate 1 (Aprobado/Rechazado).")
    fecha_aprobacion: Optional[datetime]
    sharepoint_carpeta_url: Optional[str] = Field(None, description="URL de la carpeta creada automáticamente.")

    class Config:
        from_attributes = True

# --- Actualizaciones de Fase (Gates 2, 3, 4) ---

class ProyectoFaseUpdate(BaseModel):
    """Actualización del status o la adición de documentos (Docs Técnicos, Docs O&M)."""
    status_fase: Optional[str] = None
    documentos_tecnicos_url: Optional[str] = None # Ingeniería (Gate 2)
    documentos_o_m_url: Optional[str] = None      # Construcción (Gate 3)