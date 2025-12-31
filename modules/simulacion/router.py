"""
Router del Módulo Simulación
"""

from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse
from uuid import UUID
from typing import Optional

# IMPORTS OBLIGATORIOS para permisos
from core.security import get_current_user_context
from core.permissions import require_module_access
from core.database import get_db_connection

# Import del Service Layer
from .service import SimulacionService, get_simulacion_service
from .schemas import OportunidadCreateCompleta, DetalleBessCreate

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
        "limit": limit
    })

@router.get("/partials/comentarios/{id_oportunidad}", include_in_schema=False)
async def get_comentarios_partial(
    id_oportunidad: UUID,
    request: Request,
    service: SimulacionService = Depends(get_simulacion_service),
    conn = Depends(get_db_connection),
    _ = require_module_access("simulacion")
):
    """Partial: Lista de comentarios de simulación."""
    comentarios = await service.get_comentarios_simulacion(conn, id_oportunidad)
    
    return templates.TemplateResponse("simulacion/partials/detalles/comentarios_list.html", {
        "request": request,
        "comentarios": comentarios
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
    _ = require_module_access("simulacion")
):
    """Partial: Lista de sitios de la oportunidad."""
    sitios = await service.get_sitios(conn, id_oportunidad)
    
    return templates.TemplateResponse("simulacion/partials/sitios_list.html", {
        "request": request,
        "sitios": sitios
    })