"""
Router del Módulo Simulación
"""

from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse
from uuid import UUID
from typing import Optional, List
from decimal import Decimal
import logging
import asyncpg

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
    

    # Logic to determine effective role for UI
    effective_role = "viewer"
    if context.get("role") == "ADMIN":
         effective_role = "admin"
    else:
        effective_role = context.get("module_roles", {}).get("simulacion", "viewer")

    return templates.TemplateResponse(template, {
        "request": request,
        "user_name": context.get("user_name"),
        "role": context.get("role"),
        "module_roles": context.get("module_roles", {}),
        "current_module_role": effective_role
    })

# ========================================
# FORMULARIO EXTRAORDINARIO (Solo ADMIN/MANAGER)
# ========================================
@router.api_route("/form-extraordinario", methods=["GET", "HEAD"], include_in_schema=False)
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
    # Validación de permiso: Admin Global, Admin de Módulo, o Manager Editor
    role = context.get("role")
    module_role = context.get("module_roles", {}).get("simulacion", "")
    
    is_module_editor_or_higher = module_role in ["editor", "assignor", "admin"]
    has_access = (role == "ADMIN") or (module_role == "admin") or (role == "MANAGER" and is_module_editor_or_higher)
    
    if not has_access:
        raise HTTPException(status_code=403, detail="Acceso denegado. Se requiere nivel Administrador o Manager (Editor) en el módulo.")
    
    # Cargar catálogos para el formulario
    catalogos = await service.get_catalogos_ui(conn)
    canal_default = service.get_canal_from_user_name(context.get("user_name", ""))
    
    return templates.TemplateResponse("shared/forms/oportunidad_form.html", {
        "request": request,
        "catalogos": catalogos,
        "canal_default": canal_default,
        "user_name": context.get("user_name"),
        "role": role,
        "module_roles": context.get("module_roles", {}),
        "post_url": "/simulacion/form-extraordinario",
        "cancel_url": "/simulacion/ui",
        "is_extraordinario": True
    })

@router.post("/form-extraordinario", include_in_schema=False)
async def create_oportunidad_extraordinaria(
    request: Request,
    fecha_manual: str = Form(...),
    cliente_nombre: str = Form(..., min_length=3),
    cliente_id: Optional[UUID] = Form(None),
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
    solicitado_por_id: Optional[UUID] = Form(None),
    es_licitacion: bool = Form(False),
    
    # Campos BESS
    bess_uso_sistema: List[str] = Form([]),
    bess_cargas_criticas: Optional[float] = Form(None),
    bess_voltaje: Optional[str] = Form(None),
    bess_autonomia: Optional[str] = Form(None),
    bess_tiene_motores: bool = Form(False),
    bess_potencia_motor: Optional[float] = Form(None),
    bess_cargas_separadas: bool = Form(False),
    bess_planta_emergencia: bool = Form(False),
    
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
    # Validación de permiso: Admin Global, Admin de Módulo, o Manager Editor
    role = context.get("role")
    module_role = context.get("module_roles", {}).get("simulacion", "")
    
    is_module_editor_or_higher = module_role in ["editor", "assignor", "admin"]
    has_access = (role == "ADMIN") or (module_role == "admin") or (role == "MANAGER" and is_module_editor_or_higher)
    
    if not has_access:
        raise HTTPException(status_code=403, detail="Acceso denegado. Se requiere nivel Administrador o Manager (Editor) en el módulo")
    
    try:
        # Construir objeto BESS
        detalles_bess = None
        if bess_uso_sistema or bess_cargas_criticas:
            detalles_bess = DetalleBessCreate(
                uso_sistema_json=bess_uso_sistema,
                cargas_criticas_kw=bess_cargas_criticas,
                tiene_motores=bess_tiene_motores,
                potencia_motor_hp=bess_potencia_motor,
                tiempo_autonomia=bess_autonomia,
                voltaje_operacion=bess_voltaje,
                cargas_separadas=bess_cargas_separadas,
                tiene_planta_emergencia=bess_planta_emergencia
            )
        
        # Crear objeto de datos completo
        datos = OportunidadCreateCompleta(
            fecha_manual_str=fecha_manual,
            cliente_nombre=cliente_nombre,
            cliente_id=cliente_id,
            nombre_proyecto=nombre_proyecto,
            id_tecnologia=id_tecnologia,
            id_tipo_solicitud=id_tipo_solicitud,
            id_estatus_global=1,
            canal_venta=canal_venta,
            prioridad=prioridad,
            cantidad_sitios=cantidad_sitios,
            direccion_obra=direccion_obra,
            google_maps_link=google_maps_link,
            coordenadas_gps=coordenadas_gps or "",
            sharepoint_folder_url=sharepoint_folder_url or "",
            detalles_bess=detalles_bess,
            clasificacion_solicitud="EXTRAORDINARIO",
            solicitado_por_id=solicitado_por_id,
            es_licitacion=es_licitacion
        )
        
        # Crear oportunidad
        new_id, op_id_estandar, es_fuera_horario = await service.crear_oportunidad_transaccional(
            conn, datos, context
        )
        
        # Auto-crear sitio si es unisitio (Para evitar proyectos huérfanos de sitio)
        if cantidad_sitios == 1:
            await service.auto_crear_sitio_unico(
                conn, new_id, nombre_proyecto, direccion_obra, google_maps_link, id_tipo_solicitud
            )
        
        target_url = "/simulacion/ui"
        # Params para mostrar alerta en dashboard
        params = f"?new_op={op_id_estandar}&fh={str(es_fuera_horario).lower()}&extraordinaria=1"
        
        from fastapi import Response
        return Response(status_code=200, headers={"HX-Redirect": f"{target_url}{params}"})
        
    except asyncpg.PostgresError as db_err:
        logger.error(f"DB Error creating simulacion op: {db_err}")
        return templates.TemplateResponse("simulacion/partials/messages/error.html", {
            "request": request,
            "title": "Error de Base de Datos",
            "message": "No se pudo crear la oportunidad. Verifique los datos o contacte a soporte."
        })
    except ValueError as val_err:
        return templates.TemplateResponse("simulacion/partials/messages/error.html", {
            "request": request,
            "title": "Datos Inválidos",
            "message": str(val_err)
        })
    except Exception as e:
        logger.error(f"Unexpected error creating simulacion op: {e}")
        return templates.TemplateResponse("simulacion/partials/messages/error.html", {
            "request": request,
            "title": "Error del Sistema",
            "message": "Ocurrió un error inesperado."
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
    
    # Modo compacto: muestra últimos 3 con opción de expandir
    if mode == 'compact':
        if total_comentarios > 3:
            comentarios = comentarios[:3]  # Primeros 3 (más recientes)
            has_more = True
        # Si hay 3 o menos, mostrar todos sin botón expandir
    
    # Modo latest: solo el más reciente
    elif mode == 'latest' and comentarios:
        comentarios = [comentarios[0]]
        if total_comentarios > 1:
            has_more = True
    
    # Modo para mostrar solo el último comentario (Historial)
    elif mode == 'last_one' and comentarios:
        comentarios = [comentarios[0]]
        has_more = False  # No mostrar botón "ver más" en historial
            
    return templates.TemplateResponse("shared/partials/comentarios_list.html", {
        "request": request,
        "comentarios": comentarios,
        "mode": mode,
        "has_more": has_more,
        "total_extra": total_comentarios - len(comentarios) if mode == 'compact' else total_comentarios - 1,
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
    request: Request, 
    id_oportunidad: UUID,
    conn = Depends(get_db_connection), 
    service: SimulacionService = Depends(get_simulacion_service)
):
    """Partial: Detalles técnicos BESS."""
    bess = await service.get_bess_info(conn, id_oportunidad)
    
    
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
    
    # Obtener opciones para dropdown (Excluyendo "Ganada")
    status_ids = await service._get_status_ids(conn)
    estatus_options = await conn.fetch(
        "SELECT id, nombre FROM tb_cat_estatus_global WHERE activo = true AND id != $1 ORDER BY id",
        status_ids["ganada"]
    )
    
    return templates.TemplateResponse("simulacion/partials/sitios_list.html", {
        "request": request,
        "sitios": sitios,
        "context": context,
        "estatus_options": [dict(r) for r in estatus_options],
        "id_oportunidad": id_oportunidad
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
    
    # Excluir "Ganada" del dropdown (solo para selección manual) -> CORRECCIÓN: Se debe mostrar TODO
    estatus_global = await conn.fetch(
        "SELECT id, nombre FROM tb_cat_estatus_global WHERE activo = true ORDER BY id"
    )
    motivos_cierre = await conn.fetch("SELECT id, motivo FROM tb_cat_motivos_cierre WHERE activo = true ORDER BY motivo")

    # 4. Definir Permiso de Edición (Manager/Admin)
    # 4. Definir Permiso de Edición (Manager/Admin)
    # Regla: Solo si es ADMIN global o tiene rol de módulo 'editor'/'admin'
    # FIX: Check module_roles correctly
    sim_role = context.get("module_roles", {}).get("simulacion", "")
    can_manage = context["role"] == "ADMIN" or sim_role in ["editor", "admin"]

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
    # NOTA: No necesitamos notificación aquí, el service se encarga.
    
    try:
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
        
        # Las notificaciones ahora se manejan internamente en el servicio (Service Layer Pattern)
        
        return templates.TemplateResponse("simulacion/partials/messages/success_redirect.html", {
            "request": request,
            "title": "Actualización Exitosa",
            "message": "La oportunidad se ha actualizado correctamente.",
            "redirect_url": "/simulacion/ui" 
        })
    except HTTPException as e:
        # UX IMPROVEMENT: Mostrar errores de validación dentro del modal como mensajes inline
        # para que el usuario los vea en contexto y pueda corregirlos fácilmente
        if e.status_code == 400:
             return templates.TemplateResponse("simulacion/partials/messages/error_inline.html", {
                "request": request,
                "message": e.detail
            }, status_code=200) # Forzamos 200 para que HTMX renderice el contenido
            
        return templates.TemplateResponse("simulacion/partials/messages/error_inline.html", {
            "request": request, 
            "message": e.detail
        }, status_code=e.status_code)

@router.put("/sitios/batch-update")
async def batch_update_sitios(
    request: Request,
    # Removed schemas.SitiosBatchUpdate strict dependency to avoid 422 before handler
    service: SimulacionService = Depends(get_simulacion_service),
    conn = Depends(get_db_connection),
    _ = require_module_access("simulacion", "editor") # <--- SEGURIDAD
):
    """
    Actualización masiva de sitios.
    Refactorizado para ser robusto ante fallos de codificación de HTMX/json-enc.
    Acepta tanto application/json como application/x-www-form-urlencoded.
    """
    import json
    from urllib.parse import parse_qs
    
    # 1. Raw Body Inspection
    body_bytes = await request.body()
    body_str = body_bytes.decode('utf-8')
    content_type = request.headers.get('content-type', '')
    
    logger.info(f"[BATCH UPDATE] Header CT: {content_type}")
    logger.info(f"[BATCH UPDATE] Body len: {len(body_str)}")
    
    ids_sitios_raw = []
    id_estatus_global = None
    fecha_cierre = None
    
    # 2. Parsing Logic
    parsed_mode = "UNKNOWN"
    
    try:
        # ATTEMPT A: Try JSON (Preferred)
        data = json.loads(body_str)
        ids_sitios_raw = data.get("ids_sitios", [])
        id_estatus_global = data.get("id_estatus_global")
        fecha_cierre = data.get("fecha_cierre")
        parsed_mode = "JSON"
    except json.JSONDecodeError:
        # ATTEMPT B: Fallback to Query String (Form Data)
        # This handles the case where Header is JSON but Body is FormUrlEncoded
        q_data = parse_qs(body_str)
        ids_sitios_raw = q_data.get("ids_sitios", []) # Returns list
        # parse_qs returns lists for everything
        stat_list = q_data.get("id_estatus_global", [])
        if stat_list:
            id_estatus_global = stat_list[0]
            
        date_list = q_data.get("fecha_cierre", [])
        if date_list:
            fecha_cierre = date_list[0]
            
        parsed_mode = "FORM_QS"

    logger.info(f"[BATCH UPDATE] Parsed Mode: {parsed_mode}")
    logger.info(f"[BATCH UPDATE] IDs count: {len(ids_sitios_raw)}, Status: {id_estatus_global}")

    try:
        # 3. Validation & Conversion
        if not ids_sitios_raw:
             # Retorno vacío seguro si no hubo selección
            return templates.TemplateResponse("simulacion/partials/sitios_list.html", {
                "request": request, 
                "sitios": [], 
                "context": {"role": "viewer"} 
            })

        # Convert UUIDs
        ids_sitios = [UUID(str(id_)) for id_ in ids_sitios_raw]
        
        # Convert Status
        if id_estatus_global is None:
            raise ValueError("Falta id_estatus_global")
        id_estatus_global = int(id_estatus_global)

        # 4. Execute Service
        await service.update_sitios_batch(conn, ids_sitios, id_estatus_global, fecha_cierre)
        
        # 5. Response (Refresh Table)
        id_op = await conn.fetchval(
            "SELECT id_oportunidad FROM tb_sitios_oportunidad WHERE id_sitio = $1", 
            ids_sitios[0]
        )
        
        sitios = await service.get_sitios(conn, id_op)
        status_ids = await service._get_status_ids(conn)
        estatus_options = await conn.fetch(
            "SELECT id, nombre FROM tb_cat_estatus_global WHERE activo = true AND id != $1 ORDER BY id",
            status_ids["ganada"]
        )
        
        return templates.TemplateResponse("simulacion/partials/sitios_list.html", {
            "request": request,
            "sitios": sitios,
            "context": {"role": "ADMIN", "module_role": "editor"}, 
            "estatus_options": [dict(r) for r in estatus_options]
        })

    except Exception as e:
        logger.error(f"[BATCH UPDATE ERROR] {str(e)}")
        return templates.TemplateResponse("shared/partials/toasts/toast_error.html", {
            "request": request,
            "title": "Error Batch",
            "message": f"Error procesando solicitud: {str(e)}"
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
        return templates.TemplateResponse("shared/partials/toasts/toast_success.html", {
            "request": request,
            "title": "Asignación Actualizada",
            "message": "El responsable ha sido actualizado correctamente."
        })
    except Exception as e:
        return templates.TemplateResponse("shared/partials/toasts/toast_error.html", {
            "request": request,
            "title": "Error Asignación",
            "message": str(e)
        })