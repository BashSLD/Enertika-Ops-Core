"""
Router del Módulo Construcción
"""

from fastapi import APIRouter, Request, Depends
from fastapi.templating import Jinja2Templates

# IMPORTS OBLIGATORIOS para permisos
from core.security import get_current_user_context
from core.permissions import require_module_access

templates = Jinja2Templates(directory="templates")

router = APIRouter(
    prefix="/construccion",
    tags=["Módulo Construcción"],
)

# ========================================
# CAPA DE SERVICIO (Service Layer)
# ========================================
class ConstruccionService:
    """
    Lógica de negocio del módulo construcción.
    
    Aquí irá la lógica relacionada con:
    - Gestión de proyectos en construcción
    - Control de avance de obra
    - Tracking de materiales y personal
    """
    
    async def get_data(self, conn):
        """Obtiene datos de construcción desde BD."""
        # TODO: Implementar query real
        # query = "SELECT * FROM tb_construccion WHERE status = $1"
        # rows = await conn.fetch(query, "activo")
        return []

def get_service():
    """Dependencia para inyectar la capa de servicio."""
    return ConstruccionService()

# ========================================
# ENDPOINT PRINCIPAL (UI)
# ========================================
@router.get("/ui", include_in_schema=False)
async def get_construccion_ui(
    request: Request,
    context = Depends(get_current_user_context),
    _ = require_module_access("construccion")
):
    """
    Dashboard principal del módulo construcción.
    
    HTMX Detection:
    - Si viene desde sidebar (HTMX): retorna solo contenido
    - Si es carga directa (F5/URL): retorna dashboard completo
    """
    # HTMX Detection
    if request.headers.get("hx-request"):
        template = "construccion/partials/content.html"
    else:
        template = "construccion/dashboard.html"
    
    return templates.TemplateResponse(template, {
        "request": request,
        "user_name": context.get("user_name"),
        "role": context.get("role"),
        "module_roles": context.get("module_roles", {}),
        "current_module_role": context.get("module_roles", {}).get("construccion", "viewer")
    })