"""Schemas del módulo Finanzas."""

from pydantic import BaseModel
from typing import Optional
from uuid import UUID
from datetime import date, datetime
from decimal import Decimal


class BomPagoCreate(BaseModel):
    autorizacion_id: UUID
    monto_pagado: Decimal
    moneda: str = "MXN"
    tipo_cambio_usado: Optional[Decimal] = None
    fecha_pago: date
    referencia_bancaria: Optional[str] = None
    comprobante_url: Optional[str] = None


class BomPagoRead(BaseModel):
    id: UUID
    autorizacion_id: UUID
    monto_pagado: Decimal
    moneda: str
    tipo_cambio_usado: Optional[Decimal]
    fecha_pago: date
    referencia_bancaria: Optional[str]
    comprobante_url: Optional[str]
    registrado_por: UUID
    registrado_en: datetime
    # Campos enriquecidos via JOIN
    nombre_proveedor: Optional[str] = None
    proyecto_id_estandar: Optional[str] = None
    nombre_proyecto: Optional[str] = None
    id_comprobante: Optional[UUID] = None
    registrado_por_nombre: Optional[str] = None
