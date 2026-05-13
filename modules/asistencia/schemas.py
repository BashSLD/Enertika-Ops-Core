from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel


class AsistenciaReporteRow(BaseModel):
    id: UUID
    fecha_laboral: date
    primera_entrada: datetime | None
    ultima_salida: datetime | None
    minutos_trabajados: int
    minutos_programados: int
    minutos_extra: int
    estado: str
    tiene_vacaciones: bool
    observaciones: str | None
    id_usuario: UUID
    empleado_nombre: str
    empleado_email: str | None
    sucursal_nombre: str | None
