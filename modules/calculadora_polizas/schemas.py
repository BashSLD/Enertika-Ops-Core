# modules/calculadora/schemas.py
from typing import Optional, List
from datetime import datetime, date
from uuid import UUID
from decimal import Decimal
from pydantic import BaseModel, Field, ConfigDict, field_validator
from enum import Enum
import json as _json


class TipoPoliza(str, Enum):
    PREMIUM = "premium"
    ESTANDAR = "estandar"


class EstatusCotizacion(str, Enum):
    CREADA = "CREADA"
    ENVIADA = "ENVIADA"
    EN_NEGOCIACION = "EN_NEGOCIACION"
    ACEPTADA = "ACEPTADA"
    RECHAZADA = "RECHAZADA"
    VENCIDA = "VENCIDA"
    TERMINADA = "TERMINADA"   # ciclo completo: fue renovada, sigue cubriendo hasta fecha_fin
    CANCELADA = "CANCELADA"   # cancelación anticipada por cliente (requiere admin)


# ----------------------------------------
# PLANTAS
# ----------------------------------------

class PlantaBase(BaseModel):
    id: str = Field(..., min_length=1, max_length=20)
    nombre: str = Field(..., min_length=1, max_length=200)
    zona: str = Field(..., min_length=1, max_length=100)
    potencia_kw: Optional[Decimal] = None
    num_paneles: Optional[int] = None
    cliente: Optional[str] = Field(None, max_length=200)
    direccion: Optional[str] = Field(None, max_length=400)
    activa: bool = True
    es_externa: bool = False


class PlantaCreate(PlantaBase):
    pass


class PlantaUpdate(BaseModel):
    nombre: Optional[str] = Field(None, min_length=1, max_length=200)
    zona: Optional[str] = Field(None, min_length=1, max_length=100)
    potencia_kw: Optional[Decimal] = None
    num_paneles: Optional[int] = None
    cliente: Optional[str] = Field(None, max_length=200)
    direccion: Optional[str] = Field(None, max_length=400)
    activa: Optional[bool] = None
    es_externa: Optional[bool] = None


class PlantaRead(PlantaBase):
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class PlantaDropdown(BaseModel):
    id: str
    nombre: str
    zona: str
    potencia_kw: Optional[float] = None
    num_paneles: Optional[int] = None
    cliente: Optional[str] = None
    direccion: Optional[str] = None
    es_externa: bool = False

    model_config = ConfigDict(from_attributes=True)


# ----------------------------------------
# CATÁLOGOS EDITABLES
# ----------------------------------------

class PrecioZonaRead(BaseModel):
    zona: str
    precio_por_panel_mxp: float

    model_config = ConfigDict(from_attributes=True)


class PrecioZonaUpdate(BaseModel):
    precio_por_panel_mxp: Decimal = Field(..., gt=0)


class WattabitRead(BaseModel):
    id: int
    nombre: str
    rango_min_kwp: float
    rango_max_kwp: float
    precio_anual_mxp: float

    model_config = ConfigDict(from_attributes=True)


class WattabitUpdate(BaseModel):
    precio_anual_mxp: Decimal = Field(..., gt=0)


class CostoFijoRead(BaseModel):
    concepto: str
    valor: float
    notas: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class CostoFijoUpdate(BaseModel):
    valor: Decimal = Field(..., gt=0)


# ----------------------------------------
# CÁLCULO
# ----------------------------------------

class CalcularRequest(BaseModel):
    planta_id: str
    tipo_poliza: TipoPoliza
    utilidad: float = Field(default=0.30, ge=0.0, lt=1.0)
    descuento_pct_1: Optional[float] = Field(default=None, ge=0.0, le=0.9999)
    descuento_pct_3: Optional[float] = Field(default=None, ge=0.0, le=0.9999)
    descuento_pct_5: Optional[float] = Field(default=None, ge=0.0, le=0.9999)

    @field_validator("utilidad", mode="before")
    @classmethod
    def parse_utilidad(cls, v):
        if v is None or v == "":
            return 0.30
        return float(v)

    @field_validator("descuento_pct_1", "descuento_pct_3", "descuento_pct_5", mode="before")
    @classmethod
    def parse_descuento_pct(cls, v):
        if v is None or v == "":
            return None
        val = float(v)
        return val if val > 0 else None

    model_config = ConfigDict(use_enum_values=True)


class ProyeccionAnual(BaseModel):
    anio: int
    valor: float
    acumulado: float


class CalcularResponse(BaseModel):
    planta_id: str
    nombre_planta: str
    zona: str
    potencia_kw: float
    num_paneles: int
    tipo_poliza: str
    utilidad: float

    # Desglose de costos
    mtto_principal: float
    mtto_fijo: float
    wattabit: float
    internet: float
    gestion: float

    # Totales
    sub_total: float
    sub_total_utilidad: float
    total_final: float
    peso_kwp: float
    peso_panel: float

    # Proyección
    anio_1: float
    anio_3: float
    anio_5: float
    acumulado_1_3: float
    acumulado_1_5: float

    # Etiqueta wattabit
    nombre_wattabit: str

    # Descuento por duración de contrato (porcentaje independiente por opción)
    descuento_pct_1: Optional[float] = None   # % para contrato 1 año
    descuento_pct_3: Optional[float] = None   # % para contrato 3 años
    descuento_pct_5: Optional[float] = None   # % para contrato 5 años
    anio_1_desc: float = 0.0                  # valor año 1 con descuento (si aplica)
    anio_3_desc: float = 0.0                  # valor año 3 con descuento (si aplica)
    anio_5_desc: float = 0.0                  # valor año 5 con descuento (si aplica)
    acumulado_1_3_desc: float = 0.0           # acumulado 3 años con descuento (si aplica)
    acumulado_1_5_desc: float = 0.0           # acumulado 5 años con descuento (si aplica)


# ----------------------------------------
# COTIZACIONES
# ----------------------------------------

class CotizacionRead(BaseModel):
    id: UUID
    planta_id: Optional[str] = None
    nombre_planta: str
    tipo_poliza: str
    utilidad: float
    sub_total: float
    sub_total_utilidad: float
    total_final: float
    resultado_json: dict
    creado_por: Optional[UUID] = None
    creado_por_nombre: Optional[str] = None
    created_at: datetime
    estatus: EstatusCotizacion = EstatusCotizacion.CREADA
    estatus_updated_at: Optional[datetime] = None
    solicitante_id: Optional[UUID] = None
    solicitante_nombre: Optional[str] = None
    fecha_inicio_poliza: Optional[date] = None
    fecha_fin_poliza: Optional[date] = None
    poliza_anterior_id: Optional[UUID] = None
    fecha_fin_poliza_anterior: Optional[date] = None

    model_config = ConfigDict(from_attributes=True)


class ImportExcelResult(BaseModel):
    insertadas: int
    actualizadas: int
    errores: List[str]
    polizas_legacy: int = 0
