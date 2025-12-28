"""
Router del Módulo Simulación
"""

from fastapi import APIRouter, Request, Depends
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse
import random
import asyncio

# IMPORTS OBLIGATORIOS para permisos
from core.security import get_current_user_context
from core.permissions import require_module_access

templates = Jinja2Templates(directory="templates")

router = APIRouter(
    prefix="/simulacion",
    tags=["Módulo Simulación"],
)

# ========================================
# CAPA DE SERVICIO (Service Layer)
# ========================================
class SimulacionService:
    """
    Lógica de negocio del módulo simulación.
    
    Maneja:
    - Datos de gráficas en tiempo real
    - Tabla editable de simulaciones
    - Generación de datos de prueba
    """
    
    def get_dummy_simulaciones(self):
        """Retorna datos dummy para la tabla de simulaciones."""
        return [
            {"id": 1, "proyecto": "Proyecto Alpha", "potencia": 120, "ahorro": 15000, "status": "Borrador"},
            {"id": 2, "proyecto": "Sucursal Centro", "potencia": 45, "ahorro": 5400, "status": "Finalizado"},
            {"id": 3, "proyecto": "Planta Industrial", "potencia": 500, "ahorro": 89000, "status": "En Proceso"},
        ]
    
    def get_live_power_data(self):
        """Genera datos simulados para gráficas en tiempo real."""
        return {
            "timestamp": asyncio.get_event_loop().time(),
            "power": random.randint(80, 120),
            "frequency": 60 + random.uniform(-0.1, 0.1),
            "voltage": 127 + random.uniform(-2, 2)
        }

def get_service():
    """Dependencia para inyectar la capa de servicio."""
    return SimulacionService()

# ========================================
# ENDPOINT PRINCIPAL (UI)
# ========================================
@router.get("/ui", include_in_schema=False)
async def get_simulacion_ui(
    request: Request,
    context = Depends(get_current_user_context),
    _ = require_module_access("simulacion")
):
    """
    Dashboard principal del módulo simulación con sistema de tabs.
    
    HTMX Detection:
    - Si viene desde sidebar (HTMX): retorna solo tabs.html (contenido)
    - Si es carga directa (F5/URL): retorna dashboard.html (wrapper completo)
    """
    # HTMX Detection
    if request.headers.get("hx-request"):
        template = "simulacion/tabs.html"  # Solo contenido
    else:
        template = "simulacion/dashboard.html"  # Wrapper completo
    
    return templates.TemplateResponse(template, {
        "request": request,
        "user_name": context.get("user_name"),
        "role": context.get("role"),
        "module_roles": context.get("module_roles", {}),
        "current_module_role": context.get("module_roles", {}).get("simulacion", "viewer")
    })

# ========================================
# ENDPOINTS PARCIALES (HTMX)
# ========================================
@router.get("/partials/live", include_in_schema=False)
async def get_live_graphs_partial(request: Request):
    """Partial: Tab de gráficas en tiempo real."""
    return templates.TemplateResponse("simulacion/partials/live_graphs.html", {
        "request": request
    })

@router.get("/partials/table", include_in_schema=False)
async def get_editable_table_partial(
    request: Request,
    service: SimulacionService = Depends(get_service)
):
    """Partial: Tab de tabla editable de simulaciones."""
    simulaciones = service.get_dummy_simulaciones()
    return templates.TemplateResponse("simulacion/partials/editable_table.html", {
        "request": request,
        "simulaciones": simulaciones
    })

# ========================================
# ENDPOINTS DE API (JSON)
# ========================================
@router.get("/data/live")
async def get_live_data(service: SimulacionService = Depends(get_service)):
    """API: Retorna datos en tiempo real para gráficas (JSON)."""
    return JSONResponse(service.get_live_power_data())