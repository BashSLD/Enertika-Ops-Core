# Archivo: modules/compras/schemas.py

from typing import Optional
from datetime import date
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict

# --- Modelos de Tracking de Gasto ---

class CompraTrackingCreate(BaseModel):
    """Carga manual de Excel para tracking de facturas/pagos por proyecto."""
    id_proyecto: UUID = Field(..., description="Proyecto al que se vincula el gasto.")
    descripcion_proveedor: str
    descripcion_interna: str = Field(..., description="Homologación: Mapear a la descripción interna.")
    categoria_gasto: Optional[str] = Field(None, description="Control de categorías de gasto.")
    monto: float = Field(..., gt=0.0)
    fecha_factura: date = Field(..., description="Fecha de la factura.")
    status_pago: str = Field(..., description="Status del pago (Pendiente, Pagado, Cancelado).")
    creado_por_id: UUID = Field(..., description="Usuario que cargó la factura/gasto.")

class CompraTrackingRead(CompraTrackingCreate):
    """Schema de lectura."""
    id_tracking: UUID

    model_config = ConfigDict(from_attributes=True)

# --- Modelos de Homologación (Catálogos) ---

# Nota: Si la homologación es dinámica, se necesita otra tabla (tb_homologacion)
# Por ahora, se asume que la descripción interna es texto libre o de un catálogo.