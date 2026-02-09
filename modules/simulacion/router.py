"""
Router del Módulo Simulación
"""

from fastapi import APIRouter, Request, Depends, Form, HTTPException, Query
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse, StreamingResponse, RedirectResponse
import io
from datetime import date
from uuid import UUID
from typing import Optional, List
from decimal import Decimal
import logging
import asyncpg
from dataclasses import asdict

# IMPORTS OBLIGATORIOS para permisos
from core.security import get_current_user_context
from core.permissions import require_module_access, require_manager_access, require_role
from core.config import settings

from core.database import get_db_connection

# Import del Service Layer
from .service import SimulacionService, get_simulacion_service
from .db_service import SimulacionDBService, get_db_service
from ..comercial.service import ComercialService # Reusing logic from Comercial
from modules.shared.services import SiteService

from .metrics_service import MetricsService, get_metrics_service
from datetime import datetime, timedelta

# Helper para conversión segura
def _safe_int(val: Optional[str]) -> Optional[int]:
    if not val:
        return None
    try:
        return int(val)
    except ValueError:
        return None
        
def _safe_uuid(val: Optional[str]) -> Optional[UUID]:
    if not val:
        return None
    try:
        return UUID(val)
    except ValueError:
        return None

from .schemas import OportunidadCreateCompleta, DetalleBessCreate, SimulacionUpdate, SitiosBatchUpdate

# Import Workflow Service (Centralizado)
from core.workflow.service import get_workflow_service

logger = logging.getLogger("SimulacionModule")

templates = Jinja2Templates(directory="templates")
templates.env.globals["DEBUG_MODE"] = settings.DEBUG_MODE

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
    service: SimulacionService = Depends(get_simulacion_service),
    conn = Depends(get_db_connection),
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
        "current_module_role": effective_role,
        "catalogos": await service.get_catalogos_ui(conn)
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
    _ = require_manager_access("simulacion")
):
    """
    Formulario para registro extraordinario de oportunidades.
    Solo accesible para ADMIN y MANAGER.
    """
    # Validación de permiso: Delegada a require_manager_access
    role = context.get("role")

    
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
    _ = require_manager_access("simulacion")
):
    """
    Procesa el formulario extraordinario y crea la oportunidad.
    Solo accesible para ADMIN y MANAGER.
    """
    # Validación de permiso: Delegada a require_manager_access
    
    try:
        # Construir objeto BESS (Reusando lógica centralizada de Comercial)
        detalles_bess = ComercialService.build_bess_detail(
            uso_sistema=bess_uso_sistema,
            cargas_criticas=bess_cargas_criticas,
            tiene_motores=bess_tiene_motores,
            potencia_motor=bess_potencia_motor,
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
            await SiteService.create_single_site(
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
    filtro_fecha_inicio: Optional[str] = None,
    filtro_fecha_fin: Optional[str] = None,
    filtro_tecnologia_id: Optional[str] = None,
    filtro_responsable_id: Optional[str] = None,
    context = Depends(get_current_user_context),
    conn = Depends(get_db_connection),
    _ = require_module_access("simulacion")
):
    """Partial: Tab de gráficas y reportes interactivos."""
    from .report_service import ReportesSimulacionService, FiltrosReporte, get_reportes_service
    from datetime import date
    
    # Instanciar servicio de reportes
    report_service = ReportesSimulacionService()
    
    today = date.today()
    
    # Default: Start of current Year
    start_date = today.replace(month=1, day=1)
    end_date = today
    
    # Parse params if present
    if filtro_fecha_inicio:
        try:
            start_date = datetime.strptime(filtro_fecha_inicio, '%Y-%m-%d').date()
        except ValueError:
            pass # Keep default
            
    if filtro_fecha_fin:
        try:
            end_date = datetime.strptime(filtro_fecha_fin, '%Y-%m-%d').date()
        except ValueError:
            pass # Keep default

    id_tecnologia = _safe_int(filtro_tecnologia_id)
    responsable_id = _safe_uuid(filtro_responsable_id)
    
    filtros = FiltrosReporte(
        fecha_inicio=start_date,
        fecha_fin=end_date,
        id_tecnologia=id_tecnologia,
        responsable_id=responsable_id
    )
    
    # Obtener datos para el dashboard
    catalogos = await report_service.get_catalogos_filtros(conn)
    metricas = await report_service.get_metricas_generales(conn, filtros)
    graficas = await report_service.get_datos_graficas(conn, filtros, metricas=metricas)
    
    return templates.TemplateResponse("simulacion/reportes/tabs.html", {
        "request": request,
        "user_name": context.get("user_name"),
        "role": context.get("role"),
        "module_roles": context.get("module_roles", {}),
        "current_module_role": context.get("module_roles", {}).get("simulacion", "viewer"),
        "catalogos": catalogos,
        "metricas": metricas,
        "graficas": {k: asdict(v) for k, v in graficas.items()},
        "filtros_aplicados": {
            "fecha_inicio": filtros.fecha_inicio.isoformat(),
            "fecha_fin": filtros.fecha_fin.isoformat(),
            "id_tecnologia": filtros.id_tecnologia if filtros.id_tecnologia else "",
            "responsable_id": str(filtros.responsable_id) if filtros.responsable_id else ""
        }
    })

@router.get("/partials/cards", include_in_schema=False)
async def get_cards_partial(
    request: Request,
    tab: str = "activos",
    q: Optional[str] = None,
    limit: int = 30,  # Default 30 para simulación
    subtab: Optional[str] = None,
    filtro_tecnologia_id: Optional[str] = None,
    context = Depends(get_current_user_context),
    service: SimulacionService = Depends(get_simulacion_service),
    conn = Depends(get_db_connection),
    _ = require_module_access("simulacion")
):
    """Partial: Tabla de oportunidades con filtros."""
    f_tecnologia = _safe_int(filtro_tecnologia_id)
    
    oportunidades = await service.get_oportunidades_list(
        conn, context, tab=tab, q=q, limit=limit, subtab=subtab, filtro_tecnologia_id=f_tecnologia
    )
    
    return templates.TemplateResponse("simulacion/partials/cards.html", {
        "request": request,
        "oportunidades": oportunidades,
        "current_tab": tab,
        "subtab": subtab,
        "limit": limit,
        "context": context,
        "catalogos": await service.get_catalogos_ui(conn),
        "filtro_tecnologia_id": f_tecnologia
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
    bess = await service.get_detalles_bess(conn, id_oportunidad)
    
    
    return templates.TemplateResponse("shared/partials/bess_info.html", {
        "request": request,
        "bess": bess
    })

@router.get("/partials/sitios/{id_oportunidad}", include_in_schema=False)
async def get_sitios_partial(
    id_oportunidad: UUID,
    request: Request,
    service: SimulacionService = Depends(get_simulacion_service),
    db_service: SimulacionDBService = Depends(get_db_service),
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context),
    _ = require_module_access("simulacion")
):
    """Partial: Lista de sitios de la oportunidad."""
    sitios = await service.get_sitios(conn, id_oportunidad)
    
    # Obtener opciones para dropdown (Excluyendo "Ganada")
    status_ids = await service._get_status_ids(conn)
    # Using DB Service
    estatus_options = await db_service.get_estatus_simulacion_dropdown(conn, exclude_id=status_ids["ganada"])
    
    # Logic to determine effective role for UI (Consistent with Main UI)
    effective_role = "viewer"
    if context.get("role") == "ADMIN":
         effective_role = "admin"
    else:
        effective_role = context.get("module_roles", {}).get("simulacion", "viewer")

    # Validar si la oportunidad está en estado terminal (Bloquear edición)
    op = await db_service.get_oportunidad_by_id(conn, id_oportunidad)
    is_locked = False
    if op:
         # Estados terminales: Entregado(4), Cancelado(3), Perdido(5), Ganada(2) - IDs aproximados standard
         # Usamos el mapa de IDs para ser precisos
         if op['id_estatus_global'] in [status_ids.get('entregado'), status_ids.get('cancelado'), status_ids.get('perdido'), status_ids.get('ganada')]:
             is_locked = True

    return templates.TemplateResponse("simulacion/partials/sitios_list.html", {
        "request": request,
        "sitios": sitios,
        "context": context,
        "current_module_role": effective_role, 
        "estatus_options": [dict(r) for r in estatus_options],
        "id_oportunidad": id_oportunidad,
        "is_locked": is_locked # <--- Variable de bloqueo para UI
    })

# ========================================
# MODALES DE DETALLE
# ========================================
@router.get("/modals/detalle/{id_oportunidad}", include_in_schema=False)
async def get_detalle_modal(
    request: Request,
    id_oportunidad: UUID,
    db_service: SimulacionDBService = Depends(get_db_service),
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context),
    _ = require_module_access("simulacion", "editor")
):
    """Modal de detalle (solo lectura) usando template compartido."""
    
    # 1. Obtener datos
    op = await db_service.get_oportunidad_by_id(conn, id_oportunidad)
    if not op:
         return JSONResponse(status_code=404, content={"message": "Oportunidad no encontrada"})

    # 2. Logic flags (Simulacion usually readonly for comercial actions)
    # But we follow the template requirements
    can_edit_comercial = False 
    can_close_sale = False
    
    return templates.TemplateResponse("shared/modals/detalle_oportunidad_modal.html", {
        "request": request,
        "op": dict(op),
        "can_edit_comercial": can_edit_comercial,
        "can_close_sale": can_close_sale,
        "context": context
    })

# --- ENDPOINTS DE GESTIÓN (MODALES Y UPDATES) ---

@router.get("/modals/edit/{id_oportunidad}", include_in_schema=False)
async def get_edit_modal(
    request: Request,
    id_oportunidad: UUID,
    service: SimulacionService = Depends(get_simulacion_service),
    db_service: SimulacionDBService = Depends(get_db_service),
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context), # Necesario para checar rol
    _ = require_module_access("simulacion") # Acceso base (Viewer puede ver el modal, pero no guardar)
):
    """Renderiza el modal de edición principal."""
    # 1. Obtener datos actuales
    op = await db_service.get_oportunidad_by_id(conn, id_oportunidad)
    if not op:
        return JSONResponse(status_code=404, content={"message": "Oportunidad no encontrada"})

    # 2. Cargar catálogos dinámicos
    responsables = await service.get_responsables_dropdown(conn)
    
    # 3. Obtener mapa de IDs para lógica frontend (AlpineJS)
    status_ids = await service._get_status_ids(conn)
    
    # Excluir "Ganada" del dropdown (solo para selección manual)
    estatus_global = await db_service.get_estatus_simulacion_dropdown(conn, exclude_id=status_ids["ganada"])
    motivos_cierre = await db_service.get_motivos_cierre(conn)
    
    # NUEVO: Cargar sitios de esta oportunidad para checkbox de retrabajo
    sitios_oportunidad = await db_service.get_sitios_by_oportunidad(conn, id_oportunidad)
    
    # NUEVO: Cargar catálogo de motivos de retrabajo
    motivos_retrabajo = await db_service.get_motivos_retrabajo(conn)
    
    # Determinar si es multisitio
    es_multisitio = len(sitios_oportunidad) > 1

    # 4. Definir Permiso de Edición (Manager/Admin)
    # 4. Definir Permiso de Edición (Manager/Admin)
    # Regla: Solo si es ADMIN global o tiene rol de módulo 'editor'/'admin'
    sim_role = context.get("module_roles", {}).get("simulacion", "")
    
    # Permission 1: Can Manage (Basic Save - Estatus)
    can_manage = context["role"] == "ADMIN" or sim_role in ["editor", "admin"]
    
    # Permission 2: Can Edit Sensitive (ID, Responsable, Deadline)
    # Rules: 
    # - ADMIN (System/Module) -> YES
    # - MANAGER (System) + Editor (Module) -> YES
    # - Regular Editor -> NO
    is_manager_editor = (context["role"] == 'MANAGER' and sim_role in ['editor', 'admin'])
    is_admin_system = (context["role"] == 'ADMIN' or sim_role == 'admin')
    
    can_edit_sensitive = is_manager_editor or is_admin_system

    # Determinar si es tecnología BESS (ID 2) o FV+BESS (ID 3)
    is_bess_related = op['id_tecnologia'] in [2, 3]

    return templates.TemplateResponse("simulacion/modals/update_oportunidades.html", {
        "request": request,
        "op": dict(op),
        "responsables": responsables,
        "estatus_global": [dict(r) for r in estatus_global],
        "motivos_cierre": [dict(r) for r in motivos_cierre],
        "status_ids": status_ids, # <--- Clave para AlpineJS
        "can_manage": can_manage,  # <--- Clave para ocultar/mostrar botones
        "can_edit_sensitive": can_edit_sensitive, # <--- Clave para bloquear campos sensibles
        "context": context,  # <--- Para checks de permisos en comentarios
        # NUEVOS para retrabajo
        "sitios_oportunidad": [dict(r) for r in sitios_oportunidad],
        "motivos_retrabajo": [dict(r) for r in motivos_retrabajo],
        "es_multisitio": es_multisitio,
        "is_bess_related": is_bess_related
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
    # NUEVOS: Campos de retrabajo
    es_retrabajo: Optional[bool] = Form(False),
    id_motivo_retrabajo: Optional[int] = Form(None),
    sitios_retrabajo: Optional[str] = Form(None),  # JSON string de UUIDs
    
    service: SimulacionService = Depends(get_simulacion_service),
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context),
    _ = require_module_access("simulacion", "editor") 
):
    """Procesa el update del padre con datos de formulario HTMX."""
    # NOTA: No necesitamos notificación aquí, el service se encarga.
    import json
    
    try:
        # Parsear sitios_retrabajo si viene como JSON
        sitios_retrabajo_ids = None
        if sitios_retrabajo:
            try:
                sitios_retrabajo_ids = [UUID(s) for s in json.loads(sitios_retrabajo)]
            except (json.JSONDecodeError, ValueError):
                pass
        
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
            capacidad_cierre_bess_kwh=capacidad_cierre_bess_kwh,
            # NUEVOS
            es_retrabajo=es_retrabajo,
            id_motivo_retrabajo=id_motivo_retrabajo,
            sitios_retrabajo_ids=sitios_retrabajo_ids
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
    datos: SitiosBatchUpdate, # FastAPI Pydantic Injection (Handles JSON automatically)
    service: SimulacionService = Depends(get_simulacion_service),
    db_service: SimulacionDBService = Depends(get_db_service),
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context),
    _ = require_module_access("simulacion", "editor") 
):
    """
    Actualiza múltiples sitios en batch.
    Refactorizado para usar Pydantic + IDOR Check en Service.
    Payload esperado: JSON (hx-ext="json-enc" en frontend).
    """
    try:
        if not datos.ids_sitios:
             # Retorno vacío seguro si no hubo selección
            return templates.TemplateResponse("simulacion/partials/sitios_list.html", {
                "request": request, 
                "sitios": [], 
                "context": context
            })

        # Obtener id_oportunidad del primer sitio (Validación de consistencia)
        id_op = await db_service.get_id_oportunidad_from_sitio(conn, datos.ids_sitios[0])
        
        if not id_op:
            raise HTTPException(status_code=404, detail="Sitio no encontrado o sin oportunidad asociada")
        
        # Execute Service (Ahora con validación IDOR interna)
        await service.update_sitios_batch(conn, id_op, datos, context)
        
        # Response (Refresh Table)
        sitios = await service.get_sitios(conn, id_op)
        status_ids = await service._get_status_ids(conn)
        estatus_options = await db_service.get_estatus_simulacion_dropdown(conn, exclude_id=status_ids["ganada"])
        
        # Logic to determine effective role for UI
        effective_role = "viewer"
        if context.get("role") == "ADMIN":
             effective_role = "admin"
        else:
            effective_role = context.get("module_roles", {}).get("simulacion", "viewer")

        # Validar si la oportunidad está en estado terminal (Bloquear edición visualmente)
        op = await db_service.get_oportunidad_by_id(conn, id_op)
        is_locked = False
        if op and op['id_estatus_global'] in [status_ids.get('entregado'), status_ids.get('cancelado'), status_ids.get('perdido'), status_ids.get('ganada')]:
             is_locked = True
            
        return templates.TemplateResponse("simulacion/partials/sitios_list.html", {
            "request": request, 
            "sitios": sitios,
            "context": context,
            "current_module_role": effective_role,
            "estatus_options": [dict(r) for r in estatus_options],
            "id_oportunidad": id_op,
            "is_locked": is_locked
        })

    except HTTPException as e:
        # Return error as OOB swap or inline message?
        # For this partial, usually a toast notification is better but we don't have easy toast trigger from here without HX-Trigger header.
        # Let's return a simple error alert replacing the table for now, or just raise.
        # Better: HX-Trigger for toast.
        from fastapi import Response
        return Response(status_code=e.status_code, headers={"HX-Retarget": "#error-container-if-exists", "HX-Reswap": "none"})
    except Exception as e:
        logger.error(f"Error in batch update: {e}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")# The 'require_module_access' dependency actually returns the context if assigned, but here it is assigned to `_`.
        # Let's see if I can add context to args safely or if it's already there implicitly.
        # Looking at original code: `batch_update_sitios` did NOT have `context` in args.
        # I will inject it.
        # But actually, I can just hardcode "editor" or "admin" if I knew, but that's risky.
        # Best way: Add `context = Depends(get_current_user_context)` to the function signature in a separate edit, 
        # OR assume the user has rights since they passed the check. 
        # However, to render the checkboxes again, we need to know if they are still allowed.
        # Since they just did an update, they ARE allowed.
        # But the template checks `current_module_role in ['editor', 'admin']`.
        # So I can pass "editor" as a fallback if I can't get context, but adding context is better.
        
        # NOTE: I am editing the BODY here. I cannot easily change the signature in `replace_file_content` if it spans many lines above.
        # Let's check the signature lines in the file view... 
        # Signature is lines 616-623. I am editing lines 722-733.
        # I cannot access `context` if it's not in args.
        # Workaround: Use `request.state.user` if available, or just pass a flag.
        # Wait, the previous code had `"context": {"role": "ADMIN", "module_role": "editor"},`.
        # This was a HARDCODED fake context!
        # `context={"role": "ADMIN", "module_role": "editor"}`.
        # My new template logic uses `current_module_role`.
        # So I can just pass `current_module_role="editor"` (or "admin") into the template.
        # Since this endpoint is protected by `require_module_access("simulacion", "editor")`, the user is at least an editor.
        # So passing "editor" is safe for the purpose of showing the checkboxes again.
        
        return templates.TemplateResponse("simulacion/partials/sitios_list.html", {
            "request": request,
            "sitios": sitios,
            "context": {"role": "ADMIN"}, # Dummy context to avoid jinja errors if used elsewhere
            "current_module_role": "editor", # Force enable checkboxes after update
            "estatus_options": [dict(r) for r in estatus_options],
            "id_oportunidad": id_op
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
    db_service: SimulacionDBService = Depends(get_db_service),
    _ = require_module_access("simulacion", "editor")
):
    """Actualización rápida de responsable (Inline)."""
    try:
        # Update directo
        await db_service.update_responsable(conn, id_oportunidad, responsable_simulacion_id)
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


# ========================================
# MÉTRICAS OPERATIVAS (Solo ADMIN)
# ========================================

@router.api_route("/metricas-operativas", methods=["GET", "HEAD"], include_in_schema=False)
async def get_metricas_operativas(
    request: Request,
    context = Depends(get_current_user_context),
    conn = Depends(get_db_connection),
    db_service: SimulacionDBService = Depends(get_db_service),
    _ = require_module_access("simulacion", "editor")
):
    """
    Dashboard de métricas operativas de Simulación (Admins y Managers).
    """
    
    # Verificar permisos (Admin o Manager)
    is_admin = context.get("is_admin")
    is_manager = context.get("role") == "MANAGER"
    
    if not (is_admin or is_manager):
        raise HTTPException(status_code=403, detail="Acceso denegado")

    
    # Obtener usuarios y tipos de solicitud para filtros
    usuarios = await db_service.get_usuarios_activos(conn)
    
    tipos_solicitud = await db_service.get_tipos_solicitud(conn)
    
    if request.headers.get("hx-request"):
        template = "simulacion/metricas_operativas.html"
    else:
        template = "simulacion/dashboard.html"
    
    return templates.TemplateResponse(template, {
        "request": request,
        "usuarios": [dict(r) for r in usuarios],
        "tipos_solicitud": [dict(r) for r in tipos_solicitud],
        "inner_template": "simulacion/metricas_operativas.html",
        **context
    })


@router.get("/api/metricas-operativas/datos", include_in_schema=False)
async def get_datos_metricas(
    request: Request,
    fecha_inicio: str = Query(None),
    fecha_fin: str = Query(None),
    user_id: str = Query(None),
    tipo_solicitud: str = Query(None),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),  # Explicit DB Connection Dependency
    metrics_service: MetricsService = Depends(get_metrics_service),
    _ = require_module_access("simulacion", "editor")
):
    """API para obtener métricas de estatus con detalle"""
    
    # Verificar acceso (Admin o Manager+Editor)
    is_admin = context.get("is_admin")
    is_manager = context.get("role") == "MANAGER"
    
    if not (is_admin or is_manager):
        return templates.TemplateResponse("shared/error.html", {
            "request": request,
            "message": "Acceso denegado: Se requiere ser Admin o Manager."
        })
    
    # Parsear fechas (últimos 3 meses por defecto)
    if not fecha_inicio or not fecha_fin:
        end = datetime.now()
        # Si no hay fechas, mostrar todo el historial (desde 2020)
        start = datetime(2020, 1, 1)
    else:
        try:
            start = datetime.fromisoformat(fecha_inicio)
            end = datetime.fromisoformat(fecha_fin)
        except ValueError:
             end = datetime.now()
             start = datetime(2020, 1, 1)
    
    # Parsear filtros opcionales
    user_uuid = None
    if user_id:
        try:
             user_uuid = UUID(user_id) 
        except ValueError:
            pass

    tipo_int = None
    if tipo_solicitud and tipo_solicitud.isdigit():
        tipo_int = int(tipo_solicitud)
    
    # Obtener métricas se usa la connexion inyectada
    # 1. Tiempo por estatus
    metricas_estatus = await metrics_service.get_tiempo_por_estatus(
        conn, start.date(), end.date(),
        user_id=user_uuid,
        tipo_solicitud_id=tipo_int
    )
    
    # 2. Cuellos de botella
    cuellos = await metrics_service.get_cuellos_botella(metricas_estatus)
    
    # 3. Análisis de ciclos
    ciclos = await metrics_service.get_analisis_ciclos(
        conn, start.date(), end.date()
    )
    
    # 4. Transiciones par a par (estado actual del pipeline)
    transiciones = await metrics_service.get_transiciones_par_a_par(
        conn,
        user_id=user_uuid,
        tipo_solicitud_id=tipo_int
    )
    
    return templates.TemplateResponse("simulacion/partials/metricas_datos.html", {
        "request": request,
        "metricas_estatus": metricas_estatus,
        "cuellos_botella": cuellos,
        "ciclos": ciclos,
        "transiciones": transiciones,
        "fecha_inicio": start.date().isoformat(),
        "fecha_fin": end.date().isoformat(),
        **context
    })


@router.get("/api/metricas-operativas/detalle-estatus", include_in_schema=False)
async def get_detalle_estatus(
    request: Request,
    estatus: str = Query(...),
    fecha_inicio: str = Query(...),
    fecha_fin: str = Query(...),
    user_id: str = Query(None),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    metrics_service: MetricsService = Depends(get_metrics_service),
    _ = require_module_access("simulacion", "editor")
):
    """Obtiene detalle de oportunidades en un estatus específico"""
    
    # Verificar acceso (Admin o Manager+Editor)
    is_admin = context.get("is_admin")
    is_manager = context.get("role") == "MANAGER"
    
    if not (is_admin or is_manager):
        return templates.TemplateResponse("shared/error.html", {
            "request": request,
            "message": "Acceso denegado"
        })
    
    try:
        start = datetime.fromisoformat(fecha_inicio).date()
        end = datetime.fromisoformat(fecha_fin).date()
    except ValueError:
        return templates.TemplateResponse("shared/error.html", {"request": request, "message": "Fechas inválidas"})

    user_uuid = None
    if user_id:
        try:
            user_uuid = UUID(user_id)
        except ValueError:
            pass
    
    oportunidades = await metrics_service.get_oportunidades_por_estatus(
        conn, estatus, start, end, user_id=user_uuid
    )
    
    # Calcular estadísticas
    if oportunidades:
        dias_list = [op['dias_en_estatus'] for op in oportunidades]
        promedio_dias = round(sum(dias_list) / len(dias_list), 1)
        max_dias = round(max(dias_list), 1)
        min_dias = round(min(dias_list), 1)
    else:
        promedio_dias = max_dias = min_dias = 0
    
    return templates.TemplateResponse("simulacion/partials/detalle_oportunidades_estatus.html", {
        "request": request,
        "oportunidades": oportunidades,
        "promedio_dias": promedio_dias,
        "max_dias": max_dias,
        "min_dias": min_dias,
        **context
    })


@router.get("/api/metricas-operativas/detalle-transicion", include_in_schema=False)
async def get_detalle_transicion(
    request: Request,
    estatus_origen: str = Query(...),
    estatus_destino: str = Query(...),
    user_id: str = Query(None),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    metrics_service: MetricsService = Depends(get_metrics_service),
    _ = require_module_access("simulacion", "editor")
):
    """Obtiene detalle de oportunidades para una transición específica (origen → destino)"""
    
    # Verificar acceso (Admin o Manager+Editor)
    is_admin = context.get("is_admin")
    is_manager = context.get("role") == "MANAGER"
    
    if not (is_admin or is_manager):
        return templates.TemplateResponse("shared/error.html", {
            "request": request,
            "message": "Acceso denegado"
        })
    
    user_uuid = None
    if user_id:
        try:
            user_uuid = UUID(user_id)
        except ValueError:
            pass
    
    oportunidades = await metrics_service.get_oportunidades_por_transicion(
        conn, estatus_origen, estatus_destino, user_id=user_uuid
    )
    
    # Calcular estadísticas
    if oportunidades:
        dias_list = [op['dias_en_estatus'] for op in oportunidades]
        promedio_dias = round(sum(dias_list) / len(dias_list), 1)
        max_dias = round(max(dias_list), 1)
        min_dias = round(min(dias_list), 1)
    else:
        promedio_dias = max_dias = min_dias = 0
    
    return templates.TemplateResponse("simulacion/partials/detalle_oportunidades_transicion.html", {
        "request": request,
        "oportunidades": oportunidades,
        "estatus_origen": estatus_origen,
        "estatus_destino": estatus_destino,
        "promedio_dias": promedio_dias,
        "max_dias": max_dias,
        "min_dias": min_dias,
        **context
    })
