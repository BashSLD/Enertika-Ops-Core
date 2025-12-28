# Archivo: modules/compras/router.py

from fastapi import APIRouter, Depends, status, HTTPException, Request
from fastapi.templating import Jinja2Templates
from typing import List
from uuid import UUID

# Importamos modelos y dependencias de DB
from .schemas import CompraTrackingCreate, CompraTrackingRead
from core.database import get_db_connection

# IMPORTS OBLIGATORIOS para permisos
from core.security import get_current_user_context
from core.permissions import require_module_access

templates = Jinja2Templates(directory="templates")

router = APIRouter(
    prefix="/compras",
    tags=["Módulo Compras"],
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

# ========================================
# ENDPOINT PRINCIPAL (UI)
# ========================================
@router.get("/ui", include_in_schema=False)
async def get_compras_ui(
    request: Request,
    context = Depends(get_current_user_context),
    _ = require_module_access("compras")
):
    """
    Dashboard principal del módulo compras.
    
    HTMX Detection:
    - Si viene desde sidebar (HTMX): retorna solo contenido
    - Si es carga directa (F5/URL): retorna dashboard completo
    """
    # HTMX Detection
    if request.headers.get("hx-request"):
        template = "compras/partials/content.html"
    else:
        template = "compras/dashboard.html"
    
    return templates.TemplateResponse(template, {
        "request": request,
        "user_name": context.get("user_name"),
        "role": context.get("role"),
        "module_roles": context.get("module_roles", {}),
        "current_module_role": context.get("module_roles", {}).get("compras", "viewer")
    })

# ========================================
# ENDPOINTS DE API (Tracking de Gastos)
# ========================================

@router.post("/tracking", response_model=CompraTrackingRead, status_code=status.HTTP_201_CREATED)
async def create_compra_tracking(
    data: CompraTrackingCreate,
    context = Depends(get_current_user_context),
    _ = require_module_access("compras", "editor"),  # ✅ REQUIERE EDITOR
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