"""
Router del Módulo Simulación
"""

from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse
from uuid import UUID
from typing import Optional
from decimal import Decimal
import logging

# IMPORTS OBLIGATORIOS para permisos
from core.security import get_current_user_context
from core.permissions import require_module_access
from core.database import get_db_connection

# Import del Service Layer
from .service import SimulacionService, get_simulacion_service
from .schemas import OportunidadCreateCompleta, DetalleBessCreate, SimulacionUpdate, SitiosBatchUpdate

# Import Workflow Service (Centralizado)
from core.workflow.service import get_workflow_service

logger = logging.getLogger("SimulacionModule")

templates = Jinja2Templates(directory="templates")

# Registrar filtros de timezone (México)
from core.jinja_filters import register_timezone_filters
register_timezone_filters(templates.env)

router = APIRouter(
    prefix="/simulacion",
    tags=["Módulo Simulación"],
)

# ========================================
# ENDPOINT PRINCIPAL (UI)
# ========================================
@router.api_route("/ui", methods=["GET", "HEAD"], include_in_schema=False)
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
# FORMULARIO EXTRAORDINARIO (Solo ADMIN/MANAGER)
# ========================================
@router.get("/form-extraordinario", include_in_schema=False)
async def get_form_extraordinario(
    request: Request,
    context = Depends(get_current_user_context),
    service: SimulacionService = Depends(get_simulacion_service),
    conn = Depends(get_db_connection),
    _ = require_module_access("simulacion")
):
    """
    Formulario para registro extraordinario de oportunidades.
    Solo accesible para ADMIN y MANAGER.
    """
    role = context.get("role")
    
    # Validación de permiso
    if role not in ['ADMIN', 'MANAGER']:
        raise HTTPException(status_code=403, detail="Acceso denegado. Solo ADMIN/MANAGER pueden usar registro extraordinario.")
    
    # Cargar catálogos para el formulario
    catalogos = await service.get_catalogos_ui(conn)
    canal_default = service.get_canal_from_user_name(context.get("user_name", ""))
    
    return templates.TemplateResponse("simulacion/form_extraordinario.html", {
        "request": request,
        "catalogos": catalogos,
        "canal_default": canal_default,
        "user_name": context.get("user_name"),
        "role": role
    })

@router.post("/form-extraordinario", include_in_schema=False)
async def create_oportunidad_extraordinaria(
    request: Request,
    fecha_manual: Optional[str] = Form(None),
    nombre_cliente: str = Form(...),
    nombre_proyecto: str = Form(...),
    id_tecnologia: int = Form(...),
    id_tipo_solicitud: int = Form(...),
    canal_venta: str = Form(...),
    prioridad: str = Form("normal"),
    cantidad_sitios: int = Form(1),
    direccion_obra: str = Form(...),
    google_maps_link: str = Form(...),
    coordenadas_gps: Optional[str] = Form(None),
    sharepoint_folder_url: Optional[str] = Form(None),
    # Campos BESS (opcionales)
    bess_cargas_criticas: Optional[float] = Form(None),
    bess_voltaje: Optional[str] = Form(None),
    bess_autonomia: Optional[str] = Form(None),
    bess_tiene_motores: Optional[str] = Form(None),
    bess_potencia_motor: Optional[float] = Form(None),
    bess_cargas_separadas: Optional[str] = Form(None),
    bess_planta_emergencia: Optional[str] = Form(None),
    bess_objetivos: Optional[list] = Form(None),
    # Dependencies
    context = Depends(get_current_user_context),
    service: SimulacionService = Depends(get_simulacion_service),
    conn = Depends(get_db_connection),
    _ = require_module_access("simulacion")
):
    """
    Procesa el formulario extraordinario y crea la oportunidad.
    Solo accesible para ADMIN y MANAGER.
    """
    role = context.get("role")
    
    # Validación de permiso
    if role not in ['ADMIN', 'MANAGER']:
        raise HTTPException(status_code=403, detail="Acceso denegado")
    
    try:
        # Preparar datos BESS si aplica
        detalles_bess = None
        if bess_cargas_criticas and bess_voltaje and bess_autonomia:
            detalles_bess = DetalleBessCreate(
                cargas_criticas_kw=bess_cargas_criticas,
                voltaje_operacion=bess_voltaje,
                tiempo_autonomia=bess_autonomia,
                tiene_motores=(bess_tiene_motores == "true"),
                potencia_motor_hp=bess_potencia_motor,
                cargas_separadas=(bess_cargas_separadas == "true"),
                tiene_planta_emergencia=(bess_planta_emergencia == "true"),
                objetivos_json=bess_objetivos or []
            )
        
        # Crear objeto de datos completo
        datos = OportunidadCreateCompleta(
            fecha_manual_str=fecha_manual,
            cliente_nombre=nombre_cliente,
            nombre_proyecto=nombre_proyecto,
            id_tecnologia=id_tecnologia,
            id_tipo_solicitud=id_tipo_solicitud,
            id_estatus_global=1,  # Pendiente por defecto
            canal_venta=canal_venta,
            prioridad=prioridad,
            cantidad_sitios=cantidad_sitios,
            direccion_obra=direccion_obra,
            google_maps_link=google_maps_link,
            coordenadas_gps=coordenadas_gps or "",
            sharepoint_folder_url=sharepoint_folder_url or "",
            detalles_bess=detalles_bess
        )
        
        # Crear oportunidad
        new_id, op_id_estandar, es_fuera_horario = await service.crear_oportunidad_transaccional(
            conn, datos, context
        )
        
        # Retornar mensaje de éxito
        return templates.TemplateResponse("simulacion/partials/messages/success.html", {
            "request": request,
            "title": "¡Registro Extraordinario Exitoso!",
            "message": f"Oportunidad {op_id_estandar} creada correctamente. {'ALERTA: Fuera de horario.' if es_fuera_horario else ''}"
        })
        
    except Exception as e:
        return templates.TemplateResponse("simulacion/partials/messages/error.html", {
            "request": request,
            "title": "Error al crear oportunidad",
            "message": str(e)
        })

# ========================================
# ENDPOINTS PARCIALES (HTMX)
# ========================================
@router.get("/partials/graphs", include_in_schema=False)
async def get_graphs_partial(
    request: Request,
    context = Depends(get_current_user_context),
    service: SimulacionService = Depends(get_simulacion_service),
    conn = Depends(get_db_connection),
    _ = require_module_access("simulacion")
):
    """Partial: Tab de gráficas y estadísticas."""
    stats = await service.get_dashboard_stats(conn, context)
    
    return templates.TemplateResponse("simulacion/partials/graphs.html", {
        "request": request,
        "stats": stats
    })

@router.get("/partials/cards", include_in_schema=False)
async def get_cards_partial(
    request: Request,
    tab: str = "activos",
    q: Optional[str] = None,
    limit: int = 30,  # Default 30 para simulación
    subtab: Optional[str] = None,
    context = Depends(get_current_user_context),
    service: SimulacionService = Depends(get_simulacion_service),
    conn = Depends(get_db_connection),
    _ = require_module_access("simulacion")
):
    """Partial: Tabla de oportunidades con filtros."""
    oportunidades = await service.get_oportunidades_list(
        conn, context, tab=tab, q=q, limit=limit, subtab=subtab
    )
    
    return templates.TemplateResponse("simulacion/partials/cards.html", {
        "request": request,
        "oportunidades": oportunidades,
        "current_tab": tab,
        "subtab": subtab,
        "limit": limit,
        "context": context
    })

@router.get("/partials/comentarios/{id_oportunidad}", include_in_schema=False)
async def get_comentarios_partial(
    id_oportunidad: UUID,
    request: Request,
    mode: Optional[str] = None,
    workflow_service = Depends(get_workflow_service),
    conn = Depends(get_db_connection),
    _ = require_module_access("simulacion")
):
    """Partial: Lista de comentarios de simulación."""
    comentarios = await workflow_service.get_historial(conn, id_oportunidad)
    
    total_comentarios = len(comentarios)
    has_more = False
    
    if mode == 'latest' and comentarios:
        comentarios = [comentarios[0]]
        if total_comentarios > 1:
            has_more = True
            
    return templates.TemplateResponse("shared/partials/comentarios_list.html", {
        "request": request,
        "comentarios": comentarios,
        "mode": mode,
        "has_more": has_more,
        "total_extra": total_comentarios - 1,
        "id_oportunidad": id_oportunidad
    })

@router.post("/comentarios/{id_oportunidad}")
async def create_comentario(
    id_oportunidad: UUID,
    request: Request,
    nuevo_comentario: str = Form(...),
    workflow_service = Depends(get_workflow_service),
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context),
    _ = require_module_access("simulacion", "editor") 
):
    """Crea un nuevo comentario y devuelve la lista actualizada."""
    logger.info(f"[ROUTER] Recibido POST comentario para {id_oportunidad}: '{nuevo_comentario[:50]}...'")
    if nuevo_comentario.strip():
        await workflow_service.add_comentario(
            conn, context, id_oportunidad, nuevo_comentario,
            departamento_slug="SIMULACION",
            modulo_origen="simulacion"
        )
    
    # Retornar la lista actualizada con todas las variables necesarias
    comentarios = await workflow_service.get_historial(conn, id_oportunidad)
    return templates.TemplateResponse("shared/partials/comentarios_list.html", {
        "request": request,
        "comentarios": comentarios,
        "mode": None,  # Mostrar todos los comentarios después de crear uno nuevo
        "has_more": False,
        "total_extra": 0,
        "id_oportunidad": id_oportunidad
    })


@router.get("/partials/bess/{id_oportunidad}", include_in_schema=False)
async def get_bess_partial(
    id_oportunidad: UUID,
    request: Request,
    service: SimulacionService = Depends(get_simulacion_service),
    conn = Depends(get_db_connection),
    _ = require_module_access("simulacion")
):
    """Partial: Detalles técnicos BESS."""
    bess = await service.get_detalles_bess(conn, id_oportunidad)
    
    # Parsear objetivos_json de string a lista Python
    if bess and bess.get('objetivos_json'):
        import json
        try:
            bess['objetivos_json'] = json.loads(bess['objetivos_json'])
        except (json.JSONDecodeError, TypeError):
            bess['objetivos_json'] = []
    
    return templates.TemplateResponse("simulacion/partials/detalles/bess_info.html", {
        "request": request,
        "bess": bess
    })

@router.get("/partials/sitios/{id_oportunidad}", include_in_schema=False)
async def get_sitios_partial(
    id_oportunidad: UUID,
    request: Request,
    service: SimulacionService = Depends(get_simulacion_service),
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context),
    _ = require_module_access("simulacion")
):
    """Partial: Lista de sitios de la oportunidad."""
    sitios = await service.get_sitios(conn, id_oportunidad)
    
    return templates.TemplateResponse("simulacion/partials/sitios_list.html", {
        "request": request,
        "sitios": sitios,
        "context": context
    })

# --- ENDPOINTS DE GESTIÓN (MODALES Y UPDATES) ---

@router.get("/modals/edit/{id_oportunidad}", include_in_schema=False)
async def get_edit_modal(
    request: Request,
    id_oportunidad: UUID,
    service: SimulacionService = Depends(get_simulacion_service),
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context), # Necesario para checar rol
    _ = require_module_access("simulacion") # Acceso base (Viewer puede ver el modal, pero no guardar)
):
    """Renderiza el modal de edición principal."""
    # 1. Obtener datos actuales
    op = await conn.fetchrow("SELECT * FROM tb_oportunidades WHERE id_oportunidad = $1", id_oportunidad)
    if not op:
        return JSONResponse(status_code=404, content={"message": "Oportunidad no encontrada"})

    # 2. Cargar catálogos dinámicos
    responsables = await service.get_responsables_dropdown(conn)
    
    # 3. Obtener mapa de IDs para lógica frontend (AlpineJS)
    status_ids = await service._get_status_ids(conn)
    
    # Excluir "Ganada" del dropdown (solo para selección manual)
    estatus_global = await conn.fetch(
        "SELECT id, nombre FROM tb_cat_estatus_global WHERE activo = true AND id != $1 ORDER BY id",
        status_ids["ganada"]
    )
    motivos_cierre = await conn.fetch("SELECT id, motivo FROM tb_cat_motivos_cierre WHERE activo = true ORDER BY motivo")

    # 4. Definir Permiso de Edición (Manager/Admin)
    # Regla: Solo si es ADMIN global o tiene rol de módulo 'editor'/'admin'
    can_manage = context["role"] == "ADMIN" or context.get("module_role") in ["editor", "admin"]

    return templates.TemplateResponse("simulacion/modals/update_oportunidades.html", {
        "request": request,
        "op": dict(op),
        "responsables": responsables,
        "estatus_global": [dict(r) for r in estatus_global],
        "motivos_cierre": [dict(r) for r in motivos_cierre],
        "status_ids": status_ids, # <--- Clave para AlpineJS
        "can_manage": can_manage,  # <--- Clave para ocultar/mostrar botones
        "context": context  # <--- Para checks de permisos en comentarios
    })

@router.put("/update/{id_oportunidad}")
async def update_simulacion(
    request: Request,
    id_oportunidad: UUID,
    # Form Data explícito para HTMX
    id_estatus_global: int = Form(...),
    id_interno_simulacion: Optional[str] = Form(None),
    responsable_simulacion_id: Optional[UUID] = Form(None),
    fecha_entrega_simulacion: Optional[str] = Form(None), # Recibe string ISO
    deadline_negociado: Optional[str] = Form(None),       # Recibe string ISO
    id_motivo_cierre: Optional[int] = Form(None),
    monto_cierre_usd: Optional[Decimal] = Form(None),
    potencia_cierre_fv_kwp: Optional[Decimal] = Form(None),
    capacidad_cierre_bess_kwh: Optional[Decimal] = Form(None),
    
    service: SimulacionService = Depends(get_simulacion_service),
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context),
    _ = require_module_access("simulacion", "editor") 
):
    """Procesa el update del padre con datos de formulario HTMX."""
    from core.workflow.notification_service import get_notification_service
    
    try:
        # Obtener valores ANTES del UPDATE para detectar cambios
        current = await conn.fetchrow(
            "SELECT responsable_simulacion_id, id_estatus_global FROM tb_oportunidades WHERE id_oportunidad = $1",
            id_oportunidad
        )
        
        old_responsable = current['responsable_simulacion_id'] if current else None
        old_status = current['id_estatus_global'] if current else None
        
        # Reconstruir modelo Pydantic manually
        datos = SimulacionUpdate(
            id_estatus_global=id_estatus_global,
            id_interno_simulacion=id_interno_simulacion,
            responsable_simulacion_id=responsable_simulacion_id,
            fecha_entrega_simulacion=fecha_entrega_simulacion,
            deadline_negociado=deadline_negociado,
            id_motivo_cierre=id_motivo_cierre,
            monto_cierre_usd=monto_cierre_usd,
            potencia_cierre_fv_kwp=potencia_cierre_fv_kwp,
            capacidad_cierre_bess_kwh=capacidad_cierre_bess_kwh
        )

        await service.update_simulacion_padre(conn, id_oportunidad, datos, context)
        
        # Notificaciones asíncronas (no bloquean flujo)
        notification_service = get_notification_service()
        
        try:
            # Notificar asignación si cambió
            if responsable_simulacion_id and old_responsable != responsable_simulacion_id:
                await notification_service.notify_assignment(
                    conn=conn,
                    id_oportunidad=id_oportunidad,
                    old_responsable_id=old_responsable,
                    new_responsable_id=responsable_simulacion_id,
                    assigned_by_ctx=context
                )
            
            # Notificar cambio de estatus si cambió
            if id_estatus_global and old_status != id_estatus_global:
                await notification_service.notify_status_change(
                    conn=conn,
                    id_oportunidad=id_oportunidad,
                    old_status_id=old_status,
                    new_status_id=id_estatus_global,
                    changed_by_ctx=context
                )
        except Exception as notif_error:
            logger.error(f"Error en notificaciones (no critico): {notif_error}")
        
        return templates.TemplateResponse("simulacion/partials/messages/success_redirect.html", {
            "request": request,
            "title": "Actualización Exitosa",
            "message": "La oportunidad se ha actualizado correctamente.",
            "redirect_url": "/simulacion/ui" 
        })
    except HTTPException as e:
        return templates.TemplateResponse("simulacion/partials/messages/error_inline.html", {
            "request": request, 
            "message": e.detail
        }, status_code=e.status_code)

@router.put("/sitios/batch-update")
async def batch_update_sitios(
    request: Request,
    datos: SitiosBatchUpdate,
    service: SimulacionService = Depends(get_simulacion_service),
    conn = Depends(get_db_connection),
    _ = require_module_access("simulacion", "editor") # <--- SEGURIDAD
):
    """Actualización masiva de sitios."""
    try:
        await service.update_sitios_batch(conn, datos.ids_sitios, datos.id_estatus_global, datos.fecha_cierre)
        
        return templates.TemplateResponse("simulacion/partials/toasts/toast_success.html", {
            "request": request,
            "title": "Sitios Actualizados",
            "message": f"{len(datos.ids_sitios)} sitios procesados correctamente."
        })
    except Exception as e:
        return templates.TemplateResponse("simulacion/partials/toasts/toast_error.html", {
            "request": request,
            "title": "Error Batch",
            "message": str(e)
        })

@router.patch("/update-responsable/{id_oportunidad}")
async def update_responsable(
    request: Request,
    id_oportunidad: UUID,
    responsable_simulacion_id: UUID = Form(...),
    conn = Depends(get_db_connection),
    _ = require_module_access("simulacion", "editor")
):
    """Actualización rápida de responsable (Inline)."""
    try:
        # Update directo
        await conn.execute(
            "UPDATE tb_oportunidades SET responsable_simulacion_id = $1 WHERE id_oportunidad = $2",
            responsable_simulacion_id, id_oportunidad
        )
        return templates.TemplateResponse("simulacion/partials/toasts/toast_success.html", {
            "request": request,
            "title": "Asignación Actualizada",
            "message": "El responsable ha sido actualizado correctamente."
        })
    except Exception as e:
        return templates.TemplateResponse("simulacion/partials/toasts/toast_error.html", {
            "request": request,
            "title": "Error Asignación",
            "message": str(e)
        })