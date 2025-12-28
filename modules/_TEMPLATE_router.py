"""
PLANTILLA MEJORADA PARA MÓDULOS CON PERMISOS Y HTMX
====================================================
Versión 2.0 - Incluye mejores prácticas de simulación/levantamientos

PASOS PARA USAR ESTE TEMPLATE:
1. Copia este archivo a modules/{nombre_modulo}/router.py
2. Reemplaza "TEMPLATE" con el nombre real del módulo (usar búsqueda global)
3. Ajusta el slug del módulo en require_module_access()
4. Crea el template correspondiente en templates/{nombre_modulo}/dashboard.html
5. (Opcional) Implementa lógica de negocio en la clase Service

CARACTERÍSTICAS:
- ✅ Sistema de permisos completo
- ✅ HTMX detection para cargas parciales/completas
- ✅ Estructura de servicio para lógica de negocio
- ✅ Template context completo (incluye module_roles para sidebar)
- ✅ Endpoints de ejemplo documentados
"""

from fastapi import APIRouter, Request, Depends, Response  # ← Response agregado para redirects
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

# IMPORTS OBLIGATORIOS para permisos y seguridad
from core.security import get_current_user_context, get_valid_graph_token  # ← Token inteligente agregado
from core.permissions import require_module_access

templates = Jinja2Templates(directory="templates")

router = APIRouter(
    prefix="/TEMPLATE",  # Cambiar: /proyectos, /construccion, /compras, /oym
    tags=["Módulo TEMPLATE"],  # Cambiar
)

# ========================================
# CAPA DE SERVICIO (Service Layer)
# ========================================
class TemplateService:
    """
    Separa la lógica de negocio de los endpoints.
    
    Aquí va toda la lógica que interactúa con la BD:
    - Queries complejas
    - Validaciones de negocio
    - Transformaciones de datos
    """
    
    async def get_data(self, conn):
        """
        Ejemplo: Obtiene datos de la BD.
        
        Args:
            conn: Conexión a la base de datos (de get_db_connection)
            
        Returns:
            Lista de items o datos procesados
        """
        # Query ejemplo:
        # query = "SELECT * FROM tb_tabla WHERE status = $1"
        # rows = await conn.fetch(query, "activo")
        # return [dict(row) for row in rows]
        
        return []  # Placeholder hasta implementar BD

def get_service():
    """Dependencia para inyectar la capa de servicio."""
    return TemplateService()

# ========================================
# ENDPOINT PRINCIPAL (UI)
# ========================================
@router.get("/ui", include_in_schema=False)
async def get_template_ui(
    request: Request,
    context = Depends(get_current_user_context),
    _ = require_module_access("TEMPLATE")  # Cambiar el slug aquí
):
    """
    Main Entry: Shows the module dashboard.
    
    IMPORTANTE sobre permisos:
    - El dependency require_module_access() valida que el usuario tenga acceso
    - Si no tiene acceso, retorna 403 Forbidden automáticamente
    - Puedes especificar un rol mínimo: require_module_access("TEMPLATE", "editor")
    
    IMPORTANTE sobre HTMX:
    - Detecta si es carga parcial (HTMX desde sidebar) o completa (F5/URL directo)
    - Carga parcial: solo contenido (sin base.html)
    - Carga completa: wrapper completo (con base.html)
    
    ⚠️ CRÍTICO sobre module_roles:
    - SIEMPRE pasar module_roles al template
    - Si no pasas module_roles, el sidebar en base.html NO se renderizará correctamente
    - Esto puede causar duplicación del sidebar o módulos ocultos incorrectamente
    """
    # HTMX Detection: carga parcial vs completa
    if request.headers.get("hx-request"):
        # Carga parcial desde sidebar (HTMX)
        template = "TEMPLATE/partials/content.html"  # Cambiar ruta
    else:
        # Carga completa (F5 o URL directo)
        template = "TEMPLATE/dashboard.html"  # Cambiar ruta
    
    return templates.TemplateResponse(template, {
        "request": request,
        "user_name": context.get("user_name"),
        "role": context.get("role"),
        "module_roles": context.get("module_roles", {}),  # ⚠️ CRÍTICO para sidebar
        "current_module_role": context.get("module_roles", {}).get("TEMPLATE", "viewer")
    })

# ========================================
# ENDPOINTS PARCIALES (HTMX)
# ========================================
@router.get("/partials/list", include_in_schema=False)
async def get_template_list(
    request: Request,
    context = Depends(get_current_user_context),
    _ = require_module_access("TEMPLATE"),  # Solo requiere acceso básico
    service: TemplateService = Depends(get_service)
):
    """
    Partial: Lista de elementos del módulo.
    
    Este endpoint retorna solo el HTML de la lista, sin el wrapper completo.
    Ideal para recargas dinámicas con HTMX.
    """
    # Obtener datos del servicio
    # conn = await get_db_connection()
    # items = await service.get_data(conn)
    items = []  # Placeholder
    
    return templates.TemplateResponse("TEMPLATE/partials/list.html", {
        "request": request,
        "items": items
    })

# ========================================
# ENDPOINTS ADICIONALES (Ejemplos)
# ========================================
@router.get("/form", include_in_schema=False)
async def get_template_form(
    request: Request,
    context = Depends(get_current_user_context),
    _ = require_module_access("TEMPLATE", "editor")  # Requiere rol EDITOR o superior
):
    """
    Formulario de creación - requiere permisos de edición.
    
    Nota: require_module_access("TEMPLATE", "editor") valida que el usuario
    tenga rol de "editor" o superior ("owner") en este módulo.
    """
    return templates.TemplateResponse("TEMPLATE/form.html", {
        "request": request,
        "user_name": context.get("user_name"),
        "module_roles": context.get("module_roles", {})
    })

# ========================================
# EJEMPLO DE ENDPOINT CON LÓGICA DE BD
# ========================================
# from core.database import get_db_connection
# from typing import List
# 
# @router.get("/items", response_model=List[dict])
# async def get_items(
#     service: TemplateService = Depends(get_service),
#     conn = Depends(get_db_connection)
# ):
#     """API endpoint: Retorna items en formato JSON"""
#     return await service.get_data(conn)

# ========================================
# EJEMPLO DE ACCIÓN SEGURA (Graph API)
# ========================================
@router.post("/accion-segura-ejemplo")
async def perform_secure_action(
    request: Request,
    _ = require_module_access("TEMPLATE", "editor")
):
    """
    Patrón para acciones que requieren Microsoft Graph (Email, Planner, SharePoint).
    Usa get_valid_graph_token para asegurar que el token esté vivo.
    
    ⚠️ CRÍTICO: Los tokens ahora se guardan en la BASE DE DATOS, NO en cookies.
    
    NUNCA hacer:
    ❌ token = request.session.get("access_token")  # Las cookies YA NO contienen tokens
    
    SIEMPRE hacer:
    ✅ token = await get_valid_graph_token(request)  # Lee de BD y renueva automáticamente
    """
    # 1. Obtener token seguro (lee de BD y renueva automáticamente si está próximo a expirar)
    token = await get_valid_graph_token(request)
    
    # 2. Manejo de sesión expirada (Redirect HTMX)
    if not token:
        return Response(status_code=200, headers={"HX-Redirect": "/auth/login?expired=1"})
    
    # 3. Ejecutar lógica con Graph
    # ms_auth.create_planner_task(token, ...)
    
    return HTMLResponse("Acción completada", status_code=200)
