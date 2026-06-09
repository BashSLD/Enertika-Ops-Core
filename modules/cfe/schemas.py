# modules/cfe/schemas.py
from __future__ import annotations
from typing import Optional
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel


class CfeServicioCreate(BaseModel):
    numero_servicio: str
    nombre: str
    alias: Optional[str] = None
    lada: str = "55"
    telefono: str
    email: str


class CfeServicioRow(BaseModel):
    id: UUID
    numero_servicio: str
    nombre: str
    alias: Optional[str]
    lada: str
    telefono: str
    email: str
    activo: bool
    creado_en: datetime

    model_config = {"from_attributes": True}


class CfeDescargaRow(BaseModel):
    id: UUID
    servicio_id: UUID
    periodo: str
    tipo: str
    estatus: str
    nombre_archivo: Optional[str]
    ruta_sharepoint: Optional[str]
    error_mensaje: Optional[str]
    descargado_en: Optional[datetime]

    model_config = {"from_attributes": True}
