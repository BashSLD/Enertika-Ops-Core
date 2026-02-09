from typing import Optional, List
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field


class TraspasoEnviar(BaseModel):
    id_proyecto: UUID
    area_origen: str
    area_destino: str
    comentario: Optional[str] = None
    documentos_verificados: List[int] = Field(default_factory=list)


class TraspasoRecibir(BaseModel):
    comentario: Optional[str] = None


class TraspasoRechazar(BaseModel):
    motivos: List[int] = Field(default_factory=list)
    comentario: Optional[str] = None


class DocumentoChecklist(BaseModel):
    id: int
    nombre_documento: str
    descripcion: Optional[str] = None
    es_obligatorio: bool = True
    orden: int = 0


class MotivoRechazo(BaseModel):
    id: int
    motivo: str


class TraspasoResponse(BaseModel):
    id_traspaso: UUID
    id_proyecto: UUID
    area_origen: str
    area_destino: str
    status: str
    enviado_por_nombre: Optional[str] = None
    fecha_envio: Optional[datetime] = None
    recibido_por_nombre: Optional[str] = None
    fecha_recepcion: Optional[datetime] = None
    rechazado_por_nombre: Optional[str] = None
    fecha_rechazo: Optional[datetime] = None
    comentario_envio: Optional[str] = None
    comentario_rechazo: Optional[str] = None


class ProyectoAreaView(BaseModel):
    id_proyecto: UUID
    proyecto_id_estandar: Optional[str] = None
    nombre_proyecto: Optional[str] = None
    cliente_nombre: Optional[str] = None
    area_actual: str = "INGENIERIA"
    fecha_inicio_area: Optional[datetime] = None
    dias_en_area: int = 0
    traspaso_pendiente: bool = False
    ultimo_traspaso_status: Optional[str] = None
