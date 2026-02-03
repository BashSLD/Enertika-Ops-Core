from fastapi import APIRouter, Depends, Request, Form, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
from uuid import UUID

# IMPORTS OBLIGATORIOS para permisos
from core.security import get_current_user_context
from core.permissions import require_module_access
from core.config import settings

# Database connection
from core.database import get_db_connection

# Service Layer
from .service import get_service, LevantamientoService

templates = Jinja2Templates(directory="templates")
templates.env.globals["DEBUG_MODE"] = settings.DEBUG_MODE

router = APIRouter(
    prefix="/levantamientos",
    tags=["Módulo Levantamientos"]
)

# ========================================
# ENDPOINT PRINCIPAL (UI)
# ========================================
@router.api_route("/ui", methods=["GET", "HEAD"], include_in_schema=False)
async def get_levantamientos_ui(
    request: Request,
    conn = Depends(get_db_connection),
    service: LevantamientoService = Depends(get_service),
    context = Depends(get_current_user_context),
    _ = require_module_access("levantamientos")
):
    """
    Dashboard principal del módulo levantamientos con tablero Kanban.
    
    HTMX Detection:
    - Si viene desde sidebar (HTMX): retorna partial del Kanban
    - Si es carga directa (F5/URL): retorna dashboard completo
    """
    # HTMX Detection
    if request.headers.get("hx-request"):
        # Carga parcial desde sidebar - CARGAR DATOS REALES
        data = await service.get_kanban_data(conn)
        
        return templates.TemplateResponse("levantamientos/partials/kanban.html", {
            "request": request,
            "pendientes": data['pendientes'],
            "agendados": data['agendados'],
            "en_proceso": data['en_proceso'],
            "completados": data['completados'],
            "entregados": data['entregados'],
            "pospuestos": data['pospuestos'],
            "can_edit": True,
            "user_context": context
        })
    else:
        # Carga completa de página
        return templates.TemplateResponse("levantamientos/dashboard.html", {
            "request": request,
            "user_name": context.get("user_name"),
            "role": context.get("role"),
            "module_roles": context.get("module_roles", {}),
            "current_module_role": context.get("module_roles", {}).get("levantamientos", "viewer")
        })

# ========================================
# ENDPOINTS PARCIALES (HTMX)
# ========================================
@router.get("/partials/kanban", include_in_schema=False)
async def get_kanban_partial(
    request: Request,
    conn = Depends(get_db_connection),
    service: LevantamientoService = Depends(get_service),
    context = Depends(get_current_user_context)
):
    """Partial: Tablero Kanban con datos reales de BD."""
    data = await service.get_kanban_data(conn)
    
    # Determinar permisos
    can_edit = (
        context.get("role") == "ADMIN" or 
        context.get("module_roles", {}).get("levantamientos") in ["editor", "assignor", "admin"]
    )
    
    
    return templates.TemplateResponse("levantamientos/partials/kanban.html", {
        "request": request,
        "pendientes": data['pendientes'],
        "agendados": data['agendados'],
        "en_proceso": data['en_proceso'],
        "completados": data['completados'],
        "entregados": data['entregados'],
        "pospuestos": data['pospuestos'],
        "can_edit": can_edit,
        "user_context": context
    })

# ========================================
# MODALES
# ========================================
@router.get("/modal/assign/{id_levantamiento}", include_in_schema=False)
async def get_assign_modal(
    request: Request,
    id_levantamiento: UUID,
    conn = Depends(get_db_connection),
    service: LevantamientoService = Depends(get_service),
    context = Depends(get_current_user_context)
):
    """Modal para asignar responsables."""
    # Obtener datos del levantamiento
    lev_data = await conn.fetchrow("""
        SELECT l.*, o.op_id_estandar, o.nombre_proyecto, o.cliente_nombre
        FROM tb_levantamientos l
        INNER JOIN tb_oportunidades o ON l.id_oportunidad = o.id_oportunidad
        WHERE l.id_levantamiento = $1
    """, id_levantamiento)
    
    if not lev_data:
        raise HTTPException(status_code=404, detail="Levantamiento no encontrado")
    
    # Obtener listas de usuarios
    usuarios = await service.get_usuarios_para_asignacion(conn)
    
    return templates.TemplateResponse("levantamientos/modals/assign_modal.html", {
        "request": request,
        "id_levantamiento": id_levantamiento,
        "lev_data": dict(lev_data),
        "tecnicos": usuarios['tecnicos'],
        "jefes": usuarios['jefes'],
        "current_tecnico_id": lev_data['tecnico_asignado_id'],
        "current_jefe_id": lev_data['jefe_area_id']
    })

@router.get("/modal/historial/{id_levantamiento}", include_in_schema=False)
async def get_historial_modal(
    request: Request,
    id_levantamiento: UUID,
    conn = Depends(get_db_connection),
    service: LevantamientoService = Depends(get_service)
):
    """Modal con timeline de cambios de estado."""
    # Obtener datos del levantamiento
    lev_data = await conn.fetchrow("""
        SELECT l.*, o.op_id_estandar, o.nombre_proyecto
        FROM tb_levantamientos l
        INNER JOIN tb_oportunidades o ON l.id_oportunidad = o.id_oportunidad
        WHERE l.id_levantamiento = $1
    """, id_levantamiento)
    
    if not lev_data:
        raise HTTPException(status_code=404, detail="Levantamiento no encontrado")
    
    # Obtener historial
    historial = await service.get_historial_estados(conn, id_levantamiento)
    
    return templates.TemplateResponse("levantamientos/modals/historial_modal.html", {
        "request": request,
        "lev_data": dict(lev_data),
        "historial": historial
    })

# ========================================
# ENDPOINTS DE API (Acciones del Kanban)
# ========================================
@router.post("/assign/{id_levantamiento}")
async def assign_responsables_endpoint(
    id_levantamiento: UUID,
    tecnico_asignado_id: Optional[UUID] = Form(None),
    jefe_area_id: Optional[UUID] = Form(None),
    observaciones: Optional[str] = Form(None),
    conn = Depends(get_db_connection),
    service: LevantamientoService = Depends(get_service),
    context = Depends(get_current_user_context)
):
    """
    API: Asigna responsables a un levantamiento.
    Envía notificaciones automáticas.
    """
    try:
        await service.assign_responsables(
            conn=conn,
            id_levantamiento=id_levantamiento,
            tecnico_id=tecnico_asignado_id,
            jefe_id=jefe_area_id,
            user_context=context,
            observaciones=observaciones
        )
        
        return HTMLResponse(
            status_code=200,
            headers={"HX-Trigger": "reloadKanban"}
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        return HTMLResponse(
            f"<div class='text-red-500'>Error: {str(e)}</div>",
            status_code=500
        )

@router.post("/change-status/{id_levantamiento}")
async def change_status_endpoint(
    request: Request,
    id_levantamiento: UUID,
    nuevo_estado: int = Form(...),
    observaciones: Optional[str] = Form(None),
    conn = Depends(get_db_connection),
    service: LevantamientoService = Depends(get_service),
    context = Depends(get_current_user_context)
):
    """
    API: Cambia el estado de un levantamiento.
    Registra en historial y notifica automáticamente.
    """
    try:
        await service.cambiar_estado(
            conn=conn,
            id_levantamiento=id_levantamiento,
            nuevo_estado=nuevo_estado,
            user_context=context,
            observaciones=observaciones
        )
        
        # Recargar datos del kanban y retornar HTML actualizado
        data = await service.get_kanban_data(conn)
        
        can_edit = (
            context.get("role") == "ADMIN" or 
            context.get("module_roles", {}).get("levantamientos") in ["editor", "assignor", "admin"]
        )
        
        return templates.TemplateResponse("levantamientos/partials/kanban.html", {
            "request": request,
            "pendientes": data['pendientes'],
            "agendados": data['agendados'],
            "en_proceso": data['en_proceso'],
            "completados": data['completados'],
            "entregados": data['entregados'],
            "pospuestos": data['pospuestos'],
            "can_edit": can_edit,
            "user_context": context
        })
    except HTTPException as e:
        raise e
    except Exception as e:
        return HTMLResponse(
            f"<div class='text-red-500'>Error: {str(e)}</div>",
            status_code=500
        )

# DEPRECATED: Mantener por compatibilidad pero marcar como obsoleto
@router.post("/move/{id_oportunidad}")
async def mover_tarjeta_endpoint_legacy(
    id_oportunidad: UUID,
    status: int = Form(...),
    conn = Depends(get_db_connection),
    service: LevantamientoService = Depends(get_service),
    context = Depends(get_current_user_context)
):
    """
    API LEGACY: Mantener por compatibilidad.
    Usar /change-status en su lugar.
    """
    # Obtener id_levantamiento desde id_oportunidad
    lev_id = await conn.fetchval(
        "SELECT id_levantamiento FROM tb_levantamientos WHERE id_oportunidad = $1 LIMIT 1",
        id_oportunidad
    )
    
    if not lev_id:
        raise HTTPException(status_code=404, detail="Levantamiento no encontrado")
    
    return await change_status_endpoint(
        id_levantamiento=lev_id,
        nuevo_estado=status,
        observaciones=None,
        conn=conn,
        service=service,
        context=context
    )

# ========================================
# INTEGRAR ENDPOINTS NUEVOS (Posponer, Reagendar, Viaticos)
# ========================================
from .router_levantamientos_nuevos import register_nuevos_endpoints
register_nuevos_endpoints(router)