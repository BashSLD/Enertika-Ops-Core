# Archivo: modules/compras/router.py

from fastapi import APIRouter, Depends, status, HTTPException
from typing import List
from uuid import UUID

# Importamos modelos y dependencias de DB
from .schemas import CompraTrackingCreate, CompraTrackingRead
from core.database import get_db_connection

router = APIRouter(
    prefix="/compras",
    tags=["Módulo Compras"],
    # Se asumiría una dependencia para verificar rol Compras
)

# --- Capa de Servicio (Service Layer) ---

class ComprasService:
    """Maneja el tracking de gastos y la homologación."""

    async def create_tracking(self, conn, data: CompraTrackingCreate) -> CompraTrackingRead:
        """Carga manual de una factura/gasto (espejo simplificado de Odoo)."""
        # Lógica de inserción de DB en tb_compras_tracking
        pass # Implementación de DB pendiente

    async def get_tracking_by_project(self, conn, id_proyecto: UUID) -> List[CompraTrackingRead]:
        """Obtiene todos los gastos asociados a un proyecto para control de presupuesto."""
        # Query: SELECT * FROM tb_compras_tracking WHERE id_proyecto = :id_proyecto
        return [] # Retorno vacío hasta que la DB funcione

def get_compras_service():
    return ComprasService()

# --- Endpoints ---

@router.post("/tracking", response_model=CompraTrackingRead, status_code=status.HTTP_201_CREATED)
async def create_compra_tracking(
    data: CompraTrackingCreate,
    service: ComprasService = Depends(get_compras_service),
    conn = Depends(get_db_connection)
):
    """Carga un nuevo registro de gasto/factura para un proyecto."""
    return await service.create_tracking(conn, data)


@router.get("/tracking/proyecto/{id_proyecto}", response_model=List[CompraTrackingRead])
async def get_gastos_proyecto(
    id_proyecto: UUID,
    service: ComprasService = Depends(get_compras_service),
    conn = Depends(get_db_connection)
):
    """Lista el tracking de gastos para un proyecto específico."""
    return await service.get_tracking_by_project(conn, id_proyecto)