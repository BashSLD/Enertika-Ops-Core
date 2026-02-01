"""
Router del Módulo O&M (Operación y Mantenimiento)
"""

from fastapi import APIRouter, Request, Depends
from fastapi.templating import Jinja2Templates
from core.config import settings

# IMPORTS OBLIGATORIOS para permisos
from core.security import get_current_user_context
from core.permissions import require_module_access

templates = Jinja2Templates(directory="templates")
templates.env.globals["DEBUG_MODE"] = settings.DEBUG_MODE

# Registrar filtros de timezone (México)
from core.jinja_filters import register_timezone_filters
register_timezone_filters(templates.env)

router = APIRouter(
    prefix="/oym",
    tags=["Módulo O&M"],
)

# ========================================
# CAPA DE SERVICIO (Service Layer)
# ========================================
class OyMService:
    """
    Lógica de negocio del módulo O&M.
    
    Aquí irá la lógica relacionada con:
    - Mantenimiento preventivo y correctivo
    - Monitoreo de plantas
    - Tickets de servicio
    """
    
    async def get_data(self, conn):
        """Obtiene datos de O&M desde BD."""
        # TODO: Implementar query real
        # query = "SELECT * FROM tb_oym WHERE status = $1"
        # rows = await conn.fetch(query, "activo")
        return []

def get_service():
    """Dependencia para inyectar la capa de servicio."""
    return OyMService()

# ========================================
# ENDPOINT PRINCIPAL (UI)
# ========================================
@router.api_route("/ui", methods=["GET", "HEAD"], include_in_schema=False)
async def get_oym_ui(
    request: Request,
    context = Depends(get_current_user_context),
    _ = require_module_access("oym")
):
    """
    Dashboard principal del módulo O&M.
    
    HTMX Detection:
    - Si viene desde sidebar (HTMX): retorna solo contenido
    - Si es carga directa (F5/URL): retorna dashboard completo
    """
    # HTMX Detection
    if request.headers.get("hx-request"):
        template = "oym/partials/content.html"
    else:
        template = "oym/dashboard.html"
    
    return templates.TemplateResponse(template, {
        "request": request,
        "user_name": context.get("user_name"),
        "role": context.get("role"),
        "module_roles": context.get("module_roles", {}),
        "current_module_role": context.get("module_roles", {}).get("oym", "viewer")
    })