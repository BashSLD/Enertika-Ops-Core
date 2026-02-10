from fastapi import APIRouter, Depends, Request, Form, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
from uuid import UUID
import logging

# IMPORTS OBLIGATORIOS para permisos
from core.security import get_current_user_context
from core.permissions import require_module_access
from core.config import settings

# Database connection
from core.database import get_db_connection

# Service Layer
from .service import get_service, LevantamientoService
from .db_service import get_db_service
from .schemas import AssignmentForm, ChangeStatusForm
from typing import Annotated

logger = logging.getLogger("Levantamientos.Router")

templates = Jinja2Templates(directory="templates")
templates.env.globals["DEBUG_MODE"] = settings.DEBUG_MODE

# Custom Filters
def clean_status_filter(value):
    if isinstance(value, str):
        return value.replace("Lev_", "")
    return value

templates.env.filters["clean_status"] = clean_status_filter

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

        # Determinar permisos reales
        can_edit = (
            context.get("role") == "ADMIN" or
            context.get("module_roles", {}).get("levantamientos") in ["editor", "admin"]
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
    context = Depends(get_current_user_context),
    _ = require_module_access("levantamientos"),
    notification: Optional[dict] = None  # Add notification support
):
    """Partial: Tablero Kanban con datos reales de BD."""
    data = await service.get_kanban_data(conn)
    
    # Determinar permisos
    can_edit = (
        context.get("role") == "ADMIN" or 
        context.get("module_roles", {}).get("levantamientos") in ["editor", "admin"]
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
        "user_context": context,
        "notification": notification
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
    context = Depends(get_current_user_context),
    _ = require_module_access("levantamientos"),
):
    """Modal para asignar responsables."""
    # Obtener datos del levantamiento
    lev_data = await service.get_modal_data(conn, id_levantamiento)
    
    # Obtener listas de usuarios
    usuarios = await service.get_usuarios_para_asignacion(conn)

    # Phase 5: Fetch assigned technicians (Multi-select support)
    db_svc = get_db_service()
    current_tecnico_ids = await db_svc.get_asignaciones_actuales(conn, id_levantamiento)
        
    # Fallback legacy: si no hay en tabla pivote, usar el de la tabla principal
    if not current_tecnico_ids and lev_data['tecnico_asignado_id']:
        current_tecnico_ids = [lev_data['tecnico_asignado_id']]

    # Phase 4: Default Boss Logic
    current_jefe_id = lev_data['jefe_area_id']
    if not current_jefe_id:
        current_jefe_id = await service.get_jefe_default(conn)
    
    # Identificar permisos de edición para el modal
    user_role = context.get("role")
    mod_role = context.get("module_roles", {}).get("levantamientos")
    can_assign = (
        user_role == "ADMIN" or
        mod_role == "admin" or
        (user_role == "MANAGER" and mod_role in ["editor", "admin"])
    )

    return templates.TemplateResponse("levantamientos/modals/assign_modal.html", {
        "request": request,
        "id_levantamiento": id_levantamiento,
        "lev_data": lev_data,
        "tecnicos": usuarios['tecnicos'],
        "jefes": usuarios['jefes'],
        "current_tecnico_ids": current_tecnico_ids,
        "current_jefe_id": current_jefe_id,
        "can_assign": can_assign
    })


@router.get("/modal/historial/{id_levantamiento}", include_in_schema=False)
async def get_historial_modal(
    request: Request,
    id_levantamiento: UUID,
    conn = Depends(get_db_connection),
    service: LevantamientoService = Depends(get_service),
    context = Depends(get_current_user_context),
    _ = require_module_access("levantamientos"),
):
    """Modal con timeline de cambios de estado."""
    # Obtener datos del levantamiento
    lev_data = await service.get_modal_data(conn, id_levantamiento)
    
    # Obtener historial
    historial = await service.get_historial_estados(conn, id_levantamiento)
    
    return templates.TemplateResponse("shared/modals/historial_levantamiento_modal.html", {
        "request": request,
        "lev_data": lev_data,
        "historial": historial
    })

# ========================================
# ENDPOINTS DE API (Acciones del Kanban)
# ========================================
@router.post("/assign/{id_levantamiento}")
async def assign_responsables_endpoint(
    request: Request,
    id_levantamiento: UUID,
    form: Annotated[AssignmentForm, Form()],
    conn = Depends(get_db_connection),
    service: LevantamientoService = Depends(get_service),
    context = Depends(get_current_user_context),
    _ = require_module_access("levantamientos", "editor"),
):
    """
    API: Asigna responsables (múltiples técnicos) a un levantamiento.
    Envía notificaciones automáticas.
    """
    try:
        await service.assign_responsables(
            conn=conn,
            id_levantamiento=id_levantamiento,
            tecnicos_ids=form.tecnico_asignado_id or [],
            jefe_id=form.jefe_area_id,
            user_context=context,
            observaciones=form.observaciones
        )

        data = await service.get_kanban_data(conn)
        can_edit = (
            context.get("role") == "ADMIN"
            or context.get("module_roles", {}).get("levantamientos") in ["editor", "admin"]
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
            "user_context": context,
            "notification": {
                "title": "Asignación Guardada",
                "message": "Los responsables han sido actualizados correctamente.",
                "type": "success"
            }
        })

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"[ASSIGN] Error asignando responsables lev {id_levantamiento}: {e}", exc_info=True)
        data = await service.get_kanban_data(conn)
        can_edit = (
            context.get("role") == "ADMIN"
            or context.get("module_roles", {}).get("levantamientos") in ["editor", "admin"]
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
            "user_context": context,
            "notification": {
                "title": "Error",
                "message": "No se pudo completar la asignación. Intenta de nuevo.",
                "type": "error"
            }
        })

@router.post("/change-status/{id_levantamiento}")
async def change_status_endpoint(
    request: Request,
    id_levantamiento: UUID,
    form: Annotated[ChangeStatusForm, Form()],
    conn = Depends(get_db_connection),
    service: LevantamientoService = Depends(get_service),
    context = Depends(get_current_user_context),
    _ = require_module_access("levantamientos", "editor"),
):
    """
    API: Cambia el estado de un levantamiento.
    Registra en historial y notifica automáticamente.
    """
    # VALIDACION: Reglas de negocio en Service Layer
    try:
        await service.validate_status_change_prerequisites(conn, id_levantamiento, form.nuevo_estado)
    except HTTPException as e:
         data = await service.get_kanban_data(conn)
         can_edit = (
            context.get("role") == "ADMIN"
            or context.get("module_roles", {}).get("levantamientos") in ["editor", "admin"]
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
            "user_context": context,
            "notification": {
                "title": "Acción Requerida",
                "message": e.detail,
                "type": "error"
            }
        })

    try:
        await service.cambiar_estado(
            conn=conn,
            id_levantamiento=id_levantamiento,
            nuevo_estado=form.nuevo_estado,
            user_context=context,
            observaciones=form.observaciones
        )

        # Recargar datos del kanban y retornar HTML actualizado
        data = await service.get_kanban_data(conn)
        can_edit = (
            context.get("role") == "ADMIN"
            or context.get("module_roles", {}).get("levantamientos") in ["editor", "admin"]
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
            "user_context": context,
        })

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"[STATUS] Error cambiando estado lev {id_levantamiento}: {e}", exc_info=True)
        data = await service.get_kanban_data(conn)
        can_edit = (
            context.get("role") == "ADMIN"
            or context.get("module_roles", {}).get("levantamientos") in ["editor", "admin"]
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
            "user_context": context,
            "notification": {
                "title": "Error",
                "message": "No se pudo cambiar el estado. Intenta de nuevo.",
                "type": "error"
            }
        })

@router.post("/move/{id_oportunidad}")
async def mover_tarjeta_endpoint(
    request: Request,
    id_oportunidad: UUID,
    status: int = Form(...),
    conn = Depends(get_db_connection),
    service: LevantamientoService = Depends(get_service),
    context = Depends(get_current_user_context),
    _ = require_module_access("levantamientos", "editor"),
):
    """
    API: Cambia estado de un levantamiento usando id_oportunidad.
    Alias de /change-status para acceso por oportunidad.
    """
    db_svc = get_db_service()
    lev_id = await db_svc.get_id_by_oportunidad(conn, id_oportunidad)

    if not lev_id:
        raise HTTPException(status_code=404, detail="Levantamiento no encontrado")

    # Adaptar a nuevo signature con Pydantic
    form = ChangeStatusForm(nuevo_estado=status, observaciones=None)

    return await change_status_endpoint(
        request=request,
        id_levantamiento=lev_id,
        form=form,
        conn=conn,
        service=service,
        context=context
    )

# ========================================
# INTEGRAR ENDPOINTS NUEVOS (Posponer, Reagendar, Viaticos)
# ========================================
from .router_levantamientos_nuevos import register_nuevos_endpoints
register_nuevos_endpoints(router)