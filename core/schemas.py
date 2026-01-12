from pydantic import BaseModel, Field, UUID4
from typing import Optional
from datetime import datetime

class ComentarioCreate(BaseModel):
    """Schema para recibir un nuevo comentario desde cualquier módulo."""
    id_oportunidad: UUID4
    comentario: str = Field(..., min_length=1, max_length=2000, description="Contenido del mensaje")
    departamento_origen: str = Field(..., description="Slug del departamento (ej. 'INGENIERIA', 'VENTAS')")
    modulo_origen: str = Field(..., description="Módulo desde donde se envía (ej. 'simulacion', 'comercial')")

class ComentarioRead(BaseModel):
    """Schema para devolver comentarios al UI."""
    id: UUID4
    id_oportunidad: UUID4
    usuario_nombre: str
    usuario_email: Optional[str] = None
    comentario: str
    departamento_origen: Optional[str]
    modulo_origen: Optional[str]
    fecha_comentario: datetime
    es_propio: bool = False  # Flag para UI (alineación derecha/izquierda)

    class Config:
        from_attributes = True