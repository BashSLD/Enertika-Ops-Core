# core/pdf_service/schemas.py
"""
Schemas Pydantic para el servicio de generacion PDF.
"""
from typing import Optional
from pydantic import BaseModel, field_validator, model_validator
import re
from core.timezone import today_mx


class VisitaObraData(BaseModel):
    nombre_planta: str
    id_proyecto: str
    ubicacion: str = "NA"
    persona_responsable_interna: str
    responsable_obra: str
    numero_visita: int
    fecha: Optional[str] = None          # DD/MM/YYYY; se rellena automaticamente si None
    hora_entrada: str                    # HH:MM
    hora_salida: str                     # HH:MM
    motivo_visita: str
    avances_conforme_cronograma: bool = True
    razon_no_conforme: str = ""
    acuerdos: str = ""
    lugar_elaboracion: str = ""

    @field_validator("nombre_planta")
    @classmethod
    def validate_nombre_planta(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("nombre_planta no puede estar vacio")
        if len(v) > 200:
            raise ValueError("nombre_planta excede 200 caracteres")
        return v

    @field_validator("id_proyecto")
    @classmethod
    def validate_id_proyecto(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("id_proyecto no puede estar vacio")
        if len(v) > 50:
            raise ValueError("id_proyecto excede 50 caracteres")
        return v

    @field_validator("numero_visita")
    @classmethod
    def validate_numero_visita(cls, v: int) -> int:
        if v < 1:
            raise ValueError("numero_visita debe ser >= 1")
        return v

    @field_validator("motivo_visita")
    @classmethod
    def validate_motivo_visita(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("motivo_visita no puede estar vacio")
        if len(v) > 2000:
            raise ValueError("motivo_visita excede 2000 caracteres")
        return v

    @field_validator("hora_entrada", "hora_salida")
    @classmethod
    def validate_hora(cls, v: str) -> str:
        if not re.match(r"^\d{2}:\d{2}$", v.strip()):
            raise ValueError("Hora debe tener formato HH:MM")
        hh, mm = v.strip().split(":")
        if not (0 <= int(hh) <= 23 and 0 <= int(mm) <= 59):
            raise ValueError("Hora invalida")
        return v.strip()

    @model_validator(mode="after")
    def set_fecha_default(self) -> "VisitaObraData":
        if not self.fecha:
            self.fecha = today_mx().strftime("%d/%m/%Y")
        return self
