from __future__ import annotations

from datetime import date, datetime, time
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, field_validator


class TipoAusencia(BaseModel):
    id: UUID
    nombre: str
    slug: str
    abreviatura: str
    afecta_saldo: bool
    requiere_aprobacion: bool
    orden: int


class Festivo(BaseModel):
    id: UUID
    fecha: date
    descripcion: str
    es_oficial: bool


class FestivoCreate(BaseModel):
    fecha: date
    descripcion: str
    es_oficial: bool = True


class EmpleadoDatos(BaseModel):
    id: UUID
    usuario_id: UUID
    numero_empleado: Optional[str] = None
    fecha_contratacion: Optional[date] = None
    puesto: Optional[str] = None
    departamento: Optional[str] = None
    id_aprobador_vacaciones: Optional[UUID] = None
    dias_vacaciones_ajuste: int = 0


class EmpleadoDatosUpdate(BaseModel):
    numero_empleado: Optional[str] = None
    fecha_contratacion: Optional[date] = None
    puesto: Optional[str] = None
    departamento: Optional[str] = None
    id_aprobador_vacaciones: Optional[UUID] = None
    dias_vacaciones_ajuste: int = 0
    jefes_ids: list[UUID] = []


class SolicitudCreate(BaseModel):
    tipo_ausencia_id: UUID
    fecha_inicio: date
    fecha_fin: date
    fecha_presentarse: date
    observaciones: Optional[str] = None

    @field_validator("fecha_fin")
    @classmethod
    def fin_no_antes_inicio(cls, v: date, info) -> date:
        inicio = info.data.get("fecha_inicio")
        if inicio and v < inicio:
            raise ValueError("fecha_fin debe ser >= fecha_inicio")
        return v


class SolicitudOut(BaseModel):
    id: UUID
    usuario_id: UUID
    tipo_ausencia_id: UUID
    tipo_nombre: str
    tipo_abreviatura: str
    fecha_inicio: date
    fecha_fin: date
    dias_solicitados: int
    fecha_presentarse: date
    hora_llegada: Optional[time] = None
    hora_salida: Optional[time] = None
    observaciones: Optional[str]
    estado: str
    aprobado_por: Optional[UUID]
    aprobado_por_nombre: Optional[str]
    motivo_rechazo: Optional[str]
    fecha_solicitud: datetime
    fecha_resolucion: Optional[datetime]


class SolicitudRechazo(BaseModel):
    motivo: str


class FirmaUpload(BaseModel):
    firma_b64: str  # base64 del PNG enviado desde canvas


class UsuarioSimple(BaseModel):
    id_usuario: UUID
    nombre: str
    email: str
    departamento: Optional[str] = None
    puesto: Optional[str] = None
