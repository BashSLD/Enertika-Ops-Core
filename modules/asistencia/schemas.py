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


class AprobacionHorasExtraIn(BaseModel):
    minutos_aprobados: int
    comentario: str


class BulkAprobacionIn(BaseModel):
    asistencia_ids: list[UUID]
    minutos_aprobados: int
    comentario: str


class SolicitudHorasExtraIn(BaseModel):
    motivo: str


class SolicitudManualIn(BaseModel):
    fecha_laboral: date
    fecha_entrada: date | None = None
    hora_entrada: str | None = None
    fecha_salida: date | None = None
    hora_salida: str | None = None
    motivo: str


class RechazarSolicitudManualIn(BaseModel):
    comentario: str
