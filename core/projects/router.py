# Archivo: core/projects/router.py
"""
Router compartido para gestión de Proyectos Gate.
Endpoints usados por múltiples módulos (Compras, Construcción, etc.)
"""

from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from typing import Optional
from uuid import UUID
import logging

from core.database import get_db_connection
from core.security import get_current_user_context
from core.permissions import user_has_module_access

from .service import ProjectsGateService, get_projects_gate_service
from .schemas import ProyectoGateCreate

logger = logging.getLogger("ProjectsGateRouter")
templates = Jinja2Templates(directory="templates")

# Registrar filtros de timezone
from core.jinja_filters import register_timezone_filters
register_timezone_filters(templates.env)

router = APIRouter(
    prefix="/projects",
    tags=["Proyectos Gate (Compartido)"],
)


def check_puede_crear_proyecto(context: dict) -> bool:
    """
    Verifica si el usuario puede crear proyectos.
    
    Permisos:
    - Admin: siempre
    - Compras: editor+
    - Construcción: editor+
    """
    role = context.get("role", "")
    module_roles = context.get("module_roles", {})
    
    # Admin siempre puede
    if role == "ADMIN":
        return True
    
    # Verificar permisos en módulos específicos
    roles_permitidos = ["editor", "assignor", "admin", "owner"]
    
    compras_role = module_roles.get("compras", "")
    construccion_role = module_roles.get("construccion", "")
    
    return (compras_role in roles_permitidos) or (construccion_role in roles_permitidos)


# ========================================
# ENDPOINTS DE DATOS
# ========================================

@router.get("/oportunidades-ganadas")
async def get_oportunidades_ganadas(
    conn = Depends(get_db_connection),
    service: ProjectsGateService = Depends(get_projects_gate_service),
    context = Depends(get_current_user_context)
):
    """
    Obtiene oportunidades GANADAS sin proyecto asignado.
    Para el dropdown del formulario de creación.
    """
    if not check_puede_crear_proyecto(context):
        raise HTTPException(status_code=403, detail="Sin permisos para esta acción")
    
    oportunidades = await service.get_oportunidades_ganadas(conn)
    return oportunidades


@router.get("/tecnologias")
async def get_tecnologias(
    conn = Depends(get_db_connection),
    service: ProjectsGateService = Depends(get_projects_gate_service),
    context = Depends(get_current_user_context)
):
    """
    Obtiene catálogo de tecnologías activas.
    """
    tecnologias = await service.get_tecnologias(conn)
    return tecnologias


@router.get("/validar-consecutivo/{consecutivo}")
async def validar_consecutivo(
    consecutivo: int,
    conn = Depends(get_db_connection),
    service: ProjectsGateService = Depends(get_projects_gate_service),
    context = Depends(get_current_user_context)
):
    """
    Valida si un consecutivo está disponible.
    Para validación en tiempo real en el formulario.
    """
    disponible = await service.validar_consecutivo_unico(conn, consecutivo)
    
    return {
        "consecutivo": consecutivo,
        "disponible": disponible,
        "mensaje": "Disponible" if disponible else f"El consecutivo {consecutivo} ya está en uso"
    }


@router.get("/siguiente-consecutivo")
async def get_siguiente_consecutivo(
    conn = Depends(get_db_connection),
    service: ProjectsGateService = Depends(get_projects_gate_service),
    context = Depends(get_current_user_context)
):
    """
    Sugiere el siguiente consecutivo disponible.
    """
    siguiente = await service.get_siguiente_consecutivo_sugerido(conn)
    return {"siguiente": siguiente}


@router.get("/lista")
async def get_proyectos_lista(
    solo_aprobados: bool = True,
    conn = Depends(get_db_connection),
    service: ProjectsGateService = Depends(get_projects_gate_service),
    context = Depends(get_current_user_context)
):
    """
    Obtiene lista de proyectos para dropdowns.
    """
    proyectos = await service.get_proyectos_list(conn, solo_aprobados)
    return proyectos


# ========================================
# MODAL DE CREACIÓN
# ========================================

@router.get("/modal-crear", response_class=HTMLResponse)
async def get_modal_crear_proyecto(
    request: Request,
    conn = Depends(get_db_connection),
    service: ProjectsGateService = Depends(get_projects_gate_service),
    context = Depends(get_current_user_context)
):
    """
    Retorna el modal HTML para crear un proyecto.
    """
    if not check_puede_crear_proyecto(context):
        raise HTTPException(status_code=403, detail="Sin permisos para crear proyectos")
    
    # Obtener datos para el formulario
    oportunidades = await service.get_oportunidades_ganadas(conn)
    tecnologias = await service.get_tecnologias(conn)
    siguiente_consecutivo = await service.get_siguiente_consecutivo_sugerido(conn)
    
    return templates.TemplateResponse(
        "shared/partials/modal_crear_proyecto.html",
        {
            "request": request,
            "oportunidades": oportunidades,
            "tecnologias": tecnologias,
            "siguiente_consecutivo": siguiente_consecutivo
        }
    )


# ========================================
# CREACIÓN DE PROYECTO
# ========================================

@router.post("/crear", response_class=HTMLResponse)
async def crear_proyecto(
    request: Request,
    id_oportunidad: UUID = Form(...),
    prefijo: str = Form(default="MX"),
    consecutivo: int = Form(...),
    id_tecnologia: int = Form(...),
    nombre_corto: str = Form(...),
    conn = Depends(get_db_connection),
    service: ProjectsGateService = Depends(get_projects_gate_service),
    context = Depends(get_current_user_context)
):
    """
    Crea un nuevo proyecto Gate.
    Retorna HTML con resultado (para HTMX).
    """
    if not check_puede_crear_proyecto(context):
        raise HTTPException(status_code=403, detail="Sin permisos para crear proyectos")
    
    user_id = context.get("user_db_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Usuario no identificado")
    
    try:
        proyecto = await service.crear_proyecto(
            conn=conn,
            id_oportunidad=id_oportunidad,
            prefijo=prefijo.upper().strip(),
            consecutivo=consecutivo,
            id_tecnologia=id_tecnologia,
            nombre_corto=nombre_corto.strip(),
            user_id=user_id
        )
        
        return templates.TemplateResponse(
            "shared/partials/proyecto_creado_result.html",
            {
                "request": request,
                "success": True,
                "proyecto": proyecto,
                "mensaje": f"Proyecto {proyecto['proyecto_id_estandar']} creado exitosamente"
            }
        )
        
    except HTTPException as e:
        return templates.TemplateResponse(
            "shared/partials/proyecto_creado_result.html",
            {
                "request": request,
                "success": False,
                "proyecto": None,
                "mensaje": e.detail
            }
        )
    except Exception as e:
        logger.error(f"Error creando proyecto: {e}", exc_info=True)
        return templates.TemplateResponse(
            "shared/partials/proyecto_creado_result.html",
            {
                "request": request,
                "success": False,
                "proyecto": None,
                "mensaje": f"Error inesperado: {str(e)}"
            }
        )


# ========================================
# ENDPOINT JSON (alternativo para APIs)
# ========================================

@router.post("/crear-json")
async def crear_proyecto_json(
    data: ProyectoGateCreate,
    conn = Depends(get_db_connection),
    service: ProjectsGateService = Depends(get_projects_gate_service),
    context = Depends(get_current_user_context)
):
    """
    Crea un proyecto y retorna JSON.
    Útil para integraciones o llamadas desde JS.
    """
    if not check_puede_crear_proyecto(context):
        raise HTTPException(status_code=403, detail="Sin permisos para crear proyectos")
    
    user_id = context.get("user_db_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Usuario no identificado")
    
    proyecto = await service.crear_proyecto(
        conn=conn,
        id_oportunidad=data.id_oportunidad,
        prefijo=data.prefijo,
        consecutivo=data.consecutivo,
        id_tecnologia=data.id_tecnologia,
        nombre_corto=data.nombre_corto,
        user_id=user_id
    )
    
    return {
        "success": True,
        "proyecto": proyecto,
        "mensaje": f"Proyecto {proyecto['proyecto_id_estandar']} creado exitosamente"
    }
