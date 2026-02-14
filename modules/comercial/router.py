from fastapi import APIRouter, Request, Depends, HTTPException, Form, UploadFile, File, status, Response
from fastapi.templating import Jinja2Templates
from datetime import date
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from uuid import UUID, uuid4
from typing import Optional, List
import io
import logging
import asyncpg
import pandas as pd
import asyncio
import urllib.parse


from core.database import get_db_connection
from core.microsoft import get_ms_auth
from core.security import get_current_user_context, get_valid_graph_token
from core.permissions import require_module_access, require_manager_access
from core.config import settings
from .schemas import OportunidadCreateCompleta, DetalleBessCreate
from .service import ComercialService, get_comercial_service
from .email_handler import EmailHandler, get_email_handler
from .file_utils import validate_file_size

from core.workflow.service import get_workflow_service

logger = logging.getLogger("ComercialModule")

templates = Jinja2Templates(directory="templates")
templates.env.globals["DEBUG_MODE"] = settings.DEBUG_MODE

from core.jinja_filters import register_timezone_filters
register_timezone_filters(templates.env)

router = APIRouter(
    prefix="/comercial",
    tags=["Módulo Comercial"],
)

def _safe_uuid(val: str) -> Optional[UUID]:
    try:
        return UUID(val) if val and val.strip() else None
    except ValueError:
        return None

def _safe_int(val: str) -> Optional[int]:
    try:
        return int(val) if val and val.strip() else None
    except (ValueError, TypeError):
        return None



@router.head("/ui", include_in_schema=False)
async def check_comercial_ui(
    request: Request,
    context = Depends(get_current_user_context),
    _ = require_module_access("comercial")
):
    """Heartbeat endpoint to check session status without rendering."""
    return HTMLResponse("", status_code=200)

@router.get("/ui", include_in_schema=False)
async def get_comercial_ui(
    request: Request,
    context = Depends(get_current_user_context),
    conn = Depends(get_db_connection),
    service: ComercialService = Depends(get_comercial_service),
    _ = require_module_access("comercial")
):
    """Main Entry: Shows the Tabbed Dashboard (Graphs + Records)."""
    user_name = context.get("user_name", "Usuario")
    role = context.get("role", "USER")
    
    # Detección inteligente: HTMX devuelve tabs.html, carga completa devuelve dashboard.html
    if request.headers.get("hx-request"):
        template = "comercial/tabs.html"
    else:
        template = "comercial/dashboard.html"
        
    # Cargar catálogos para filtros globales
    catalogos = await service.get_catalogos_ui(conn)
    
    # Verificar si debe mostrar el popup
    show_popup = await service.should_show_popup(conn, context.get("email"))
        
    return templates.TemplateResponse(template, {
        "request": request,
        "user_name": user_name,
        "role": role,
        "module_roles": context.get("module_roles", {}),
        "current_module_role": context.get("module_roles", {}).get("comercial", "viewer"),
        "catalogos": catalogos,
        "show_custom_popup": show_popup
    }, headers={"HX-Title": "Enertika Core Ops | Comercial"})


@router.get("/form", include_in_schema=False)
async def get_comercial_form(
    request: Request,
    user_context = Depends(get_current_user_context),
    conn = Depends(get_db_connection),
    service: ComercialService = Depends(get_comercial_service),
    _ = require_module_access("comercial", "editor")
):
    """Shows the creation form (Partial or Full Page)."""
    
    # Validar email
    if not user_context.get("email"):
        # Retornamos 401 SIN redirección automática. HTMX lo atrapará.
        return HTMLResponse(status_code=401)
    
    # Validar token antes de mostrar formulario para prevenir pérdida de datos
    token = await get_valid_graph_token(request)
    if not token:
        # Token expirado y no se pudo renovar - redirigir al login AHORA
        # Mejor que el usuario lo sepa de inmediato en lugar de perder 10 minutos de trabajo
        return Response(status_code=200, headers={"HX-Redirect": "/auth/login?expired=1"})

    # Generar canal default desde el servicio
    canal_default = ComercialService.get_canal_from_user_name(
        user_context.get("user_name")
    )
    # Esto permite que ACTUALIZACIÓN esté disponible en el template
    if request.query_params.get('legacy_term'):
        catalogos = await service.get_catalogos_ui(conn)  # TODOS los tipos
        
        # Delegar búsqueda de ACTUALIZACIÓN al Service Layer
        catalogos['tipo_actualizacion_id'] = await service.get_id_tipo_actualizacion(conn)
    else:
        catalogos = await service.get_catalogos_creacion(conn, include_simulacion=False)  # Filtrado (PRE_OFERTA, LICITACION)

    return templates.TemplateResponse("shared/forms/oportunidad_form.html", {
        "request": request, 
        "canal_default": canal_default,
        "catalogos": catalogos,  # Catálogos filtrados
        "user_name": user_context.get("user_name"),
        "role": user_context.get("role"),
        "module_roles": user_context.get("module_roles", {})
    }, headers={"HX-Title": "Enertika Core Ops | Nuevo Comercial"})

@router.get("/partials/graphs", include_in_schema=False)
async def get_graphs_partial(
    request: Request,
    filtro_usuario_id: Optional[str] = None,
    filtro_tipo_id: Optional[str] = None,
    filtro_estatus_id: Optional[str] = None,
    filtro_tecnologia_id: Optional[str] = None,
    filtro_fecha_inicio: Optional[str] = None,
    filtro_fecha_fin: Optional[str] = None,
    service: ComercialService = Depends(get_comercial_service),
    conn = Depends(get_db_connection),
    user_context: dict = Depends(get_current_user_context),
    _ = require_module_access("comercial")
):
    """Partial: Graphs Tab Content."""
    f_user = _safe_uuid(filtro_usuario_id)
    f_tipo = _safe_int(filtro_tipo_id)
    f_estatus = _safe_int(filtro_estatus_id)
    f_tecnologia = _safe_int(filtro_tecnologia_id)
    f_inicio = filtro_fecha_inicio if filtro_fecha_inicio and filtro_fecha_inicio.strip() else None
    f_fin = filtro_fecha_fin if filtro_fecha_fin and filtro_fecha_fin.strip() else None

    stats = await service.get_dashboard_stats(
        conn, 
        user_context,
        filtro_usuario_id=f_user,
        filtro_tipo_id=f_tipo,
        filtro_estatus_id=f_estatus,
        filtro_tecnologia_id=f_tecnologia,
        filtro_fecha_inicio=f_inicio,
        filtro_fecha_fin=f_fin
    )
    return templates.TemplateResponse("comercial/partials/graphs.html", {"request": request, "stats": stats})

@router.get("/partials/cards", include_in_schema=False)
async def get_cards_partial(
    request: Request,
    tab: str = "activos",
    q: Optional[str] = None,
    limit: int = 15,
    subtab: Optional[str] = None,
    filtro_usuario_id: Optional[str] = None,
    filtro_tipo_id: Optional[str] = None,
    filtro_estatus_id: Optional[str] = None,
    filtro_tecnologia_id: Optional[str] = None,
    filtro_fecha_inicio: Optional[str] = None,
    filtro_fecha_fin: Optional[str] = None,
    service: ComercialService = Depends(get_comercial_service),
    conn = Depends(get_db_connection),
    user_context: dict = Depends(get_current_user_context),
    _ = require_module_access("comercial")
):
    """Partial: List of Opportunities (Cards/Grid)."""
    f_user = _safe_uuid(filtro_usuario_id)
    f_tipo = _safe_int(filtro_tipo_id)
    f_estatus = _safe_int(filtro_estatus_id)
    f_tecnologia = _safe_int(filtro_tecnologia_id)
    f_inicio = filtro_fecha_inicio if filtro_fecha_inicio and filtro_fecha_inicio.strip() else None
    f_fin = filtro_fecha_fin if filtro_fecha_fin and filtro_fecha_fin.strip() else None
    
    # Validar existencia de token sin exponerlo (para botón de envío)
    # Evita llamadas innecesarias a Graph API en cada carga
    has_valid_token = await service.check_user_has_access_token(
        conn, 
        user_context['user_db_id']
    )
    
    items = await service.get_oportunidades_list(
        conn, 
        user_context=user_context, 
        tab=tab, 
        q=q, 
        limit=limit, 
        subtab=subtab,
        filtro_usuario_id=f_user,
        filtro_tipo_id=f_tipo,
        filtro_estatus_id=f_estatus,
        filtro_tecnologia_id=f_tecnologia,
        filtro_fecha_inicio=f_inicio,
        filtro_fecha_fin=f_fin
    )
    
    return templates.TemplateResponse(
        "comercial/partials/cards.html", 
        {
            "request": request, 
            "oportunidades": items,
            "user_token": has_valid_token,
            "current_tab": tab,
            "subtab": subtab,
            "q": q,
            "limit": limit
        }
    )

@router.get("/partials/sitios/{id_oportunidad}", include_in_schema=False)
async def get_sitios_partial(
    request: Request,
    id_oportunidad: UUID,
    service: ComercialService = Depends(get_comercial_service),
    conn = Depends(get_db_connection),
    user_context = Depends(get_current_user_context),
    _ = require_module_access("comercial")
):
    """Retorna la sub-tabla de sitios para una oportunidad."""
    rows = await service.get_sitios_simple(conn, id_oportunidad, user_context)
    return templates.TemplateResponse(
        "comercial/partials/sitios_list.html",
        {"request": request, "sitios": rows}
    )

@router.get("/partials/comentarios/{id_oportunidad}", include_in_schema=False)
async def get_comentarios_partial(
    request: Request,
    id_oportunidad: UUID,
    workflow_service = Depends(get_workflow_service),
    conn = Depends(get_db_connection),
    _ = require_module_access("comercial")
):
    """Retorna los comentarios de simulación para una oportunidad."""
    comentarios = await workflow_service.get_historial(conn, id_oportunidad)
    return templates.TemplateResponse(
        "shared/partials/comentarios_list.html",
        {"request": request, "comentarios": comentarios}
    )

@router.get("/partials/bess/{id_oportunidad}", include_in_schema=False)
async def get_bess_partial(
    request: Request,
    id_oportunidad: UUID,
    service: ComercialService = Depends(get_comercial_service),
    conn = Depends(get_db_connection),
    user_context = Depends(get_current_user_context),
    _ = require_module_access("comercial")
):
    """Retorna los detalles BESS para una oportunidad."""
    bess = await service.get_detalles_bess(conn, id_oportunidad, user_context)
    return templates.TemplateResponse(
        "shared/modals/bess_detalle_modal.html",  # New Modal Wrapper
        {"request": request, "bess": bess}
    )

@router.post("/notificar/{id_oportunidad}")
async def notificar_oportunidad(
    request: Request,
    id_oportunidad: UUID,
    recipients_str: str = Form(""), # Chips de TO
    fixed_to: List[str] = Form([]), # Hidden fixed TOs
    fixed_cc: List[str] = Form([]), # Hidden fixed CCs
    extra_cc: str = Form(""),       # Input manual CC
    subject: str = Form(...),
    body: str = Form(""),           # Mensaje adicional del usuario
    auto_message: str = Form(...),  # Mensaje automático
    prioridad: str = Form("normal"),  # Prioridad del email
    fecha_ideal_usuario: Optional[date] = Form(None),  # Nueva fecha ideal (seguimientos)
    legacy_search_term: Optional[str] = Form(None),  # Capturar término legacy
    archivos_extra: List[UploadFile] = File(default=[]),
    service: ComercialService = Depends(get_comercial_service),
    ms_auth = Depends(get_ms_auth),
    conn = Depends(get_db_connection),
    email_handler = Depends(get_email_handler),  # Inyectar EmailHandler
    context = Depends(get_current_user_context),
    _auth = require_module_access("comercial", "editor")
):
    """Envía el correo de notificación usando el token de la sesión."""
    
    # Actualizar fecha_ideal_usuario si se proporcionó (para seguimientos)
    if fecha_ideal_usuario:
        await conn.execute(
            "UPDATE tb_oportunidades SET fecha_ideal_usuario = $1 WHERE id_oportunidad = $2",
            fecha_ideal_usuario, id_oportunidad
        )
    
    # Preparar datos del formulario
    form_data = {
        "recipients_str": recipients_str,
        "fixed_to": fixed_to,
        "fixed_cc": fixed_cc,
        "extra_cc": extra_cc,
        "subject": subject,
        "body": body,
        "auto_message": auto_message,
        "prioridad": prioridad,
        "legacy_search_term": legacy_search_term,  # Pasar al handler
        "archivos_extra": archivos_extra
    }
    
    # Delegar toda la lógica al EmailHandler
    success, result = await email_handler.procesar_y_enviar_notificacion(
        request=request,
        conn=conn,
        service=service,
        ms_auth=ms_auth,
        id_oportunidad=id_oportunidad,
        form_data=form_data,

        user_email=context['user_email'],
        user_context=context # Pasamos el contexto completo para validación de ownership
    )
    
    return result

@router.get("/plantilla", response_class=StreamingResponse)
async def descargar_plantilla_sitios(
    user_context = Depends(get_current_user_context),
    _auth = require_module_access("comercial")
):
    """Genera y descarga la plantilla Excel oficial (Async/Non-blocking)."""
    
    def _generate_excel_sync():
        cols = ["#", "NOMBRE", "# DE SERVICIO", "TARIFA", "LINK GOOGLE", "DIRECCION", "COMENTARIOS"]
        df = pd.DataFrame(columns=cols)
        df.loc[0] = [1, "SUCURSAL NORTE", "123456789012", "GDMTO", 
                     "https://maps.google.com/?q=19.4326,-99.1332", 
                     "Av. Reforma 123, Col. Centro", "Ejemplo de comentario"]
        
        buffer = io.BytesIO()
        # Changed engine to openpyxl to unify libraries
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Sitios')
        buffer.seek(0)
        return buffer

    # Run CPU-bound task in run_in_executor
    loop = asyncio.get_running_loop()
    buffer = await loop.run_in_executor(None, _generate_excel_sync)
    
    headers = {"Content-Disposition": 'attachment; filename="plantilla_sitios_enertika.xlsx"'}
    return StreamingResponse(buffer, headers=headers, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@router.post("/validate-thread-check")
async def validate_thread_check(
    request: Request,
    search_term: str = Form(...),
    ms_auth = Depends(get_ms_auth),
    _ = require_module_access("comercial")
):
    """Valida si existe un hilo de correo antes de permitir avanzar al usuario (Modo Homologación)."""
    token = await get_valid_graph_token(request)
    if not token:
        return JSONResponse({"found": False, "error": "Sesión expirada"}, status_code=401)

    thread_id = await ms_auth.find_thread_id(token, search_term)
    
    if thread_id:
        # Retorna éxito y el término para que el frontend lo pase al formulario
        return JSONResponse({"found": True, "clean_term": search_term})
    else:
        return JSONResponse({"found": False, "message": "No se encontró ningún hilo con ese texto."}, status_code=404)

@router.get("/api/clientes/search", include_in_schema=False)
async def search_clientes(
    request: Request,
    q: str,
    service: ComercialService = Depends(get_comercial_service),
    conn = Depends(get_db_connection),
    # Validar acceso básico, aunque sea read-only
    user_context: dict = Depends(get_current_user_context),
    _ = require_module_access("comercial")
):
    """API para búsqueda inteligente de clientes."""
    if not q:
        return []
    
    results = await service.buscar_clientes(conn, q)
    return JSONResponse(results)


@router.post("/form")
async def handle_oportunidad_creation(
    request: Request,
    # --- Datos del Cliente ---
    cliente_nombre: str = Form(..., min_length=3),
    cliente_id: Optional[UUID] = Form(None), # Nuevo campo
    nombre_proyecto: str = Form(...),
    canal_venta: str = Form(...),
    id_tecnologia: int = Form(...),
    id_tipo_solicitud: int = Form(...),
    cantidad_sitios: int = Form(...),
    prioridad: str = Form(...),
    direccion_obra: str = Form(...),
    coordenadas_gps: Optional[str] = Form(None),
    google_maps_link: Optional[str] = Form(None),

    sharepoint_folder_url: Optional[str] = Form(None),
    
    # --- Campo Licitación (Flag Transversal) ---
    es_licitacion: bool = Form(False),

    # --- Campo Fecha Manual (Gerentes) ---
    fecha_manual: Optional[str] = Form(None),
    fecha_ideal_usuario: Optional[date] = Form(None),
    
    # --- Campo Legacy (Modo Homologación) ---
    legacy_search_term: Optional[str] = Form(None),

    # --- Campos BESS (HTMX Conditional) ---
    bess_uso_sistema: List[str] = Form([]),
    bess_cargas_criticas: Optional[float] = Form(None),
    bess_tiene_motores: bool = Form(False),
    bess_potencia_motor: Optional[float] = Form(None),
    bess_autonomia: Optional[str] = Form(None),
    bess_voltaje: Optional[str] = Form(None),
    bess_cargas_separadas: bool = Form(False),
    bess_planta_emergencia: bool = Form(False),
    # --- Dependencies ---
    service: ComercialService = Depends(get_comercial_service),
    conn = Depends(get_db_connection),
    user_context: dict = Depends(get_current_user_context),
    _ = require_module_access("comercial", "editor")
):


    # Construir objeto BESS (Delegado al Service)
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

    oportunidad_data = OportunidadCreateCompleta(
        cliente_nombre=cliente_nombre,
        cliente_id=cliente_id,
        nombre_proyecto=nombre_proyecto,
        canal_venta=canal_venta,
        id_tecnologia=id_tecnologia,
        id_tipo_solicitud=id_tipo_solicitud,
        cantidad_sitios=cantidad_sitios,
        prioridad=prioridad,
        direccion_obra=direccion_obra,
        coordenadas_gps=coordenadas_gps,
        google_maps_link=google_maps_link,
        sharepoint_folder_url=sharepoint_folder_url,
        fecha_manual_str=fecha_manual,
        detalles_bess=detalles_bess,
        es_licitacion=es_licitacion,
        fecha_ideal_usuario=fecha_ideal_usuario,
        clasificacion_solicitud="ESPECIAL" if legacy_search_term else "NORMAL"
    )

    try:
        # Check for legacy search term (Modo Homologación)
        legacy_term = legacy_search_term
        
        new_id, op_std_id, fuera_horario = await service.crear_oportunidad_transaccional(conn, oportunidad_data, user_context, legacy_search_term=legacy_term)
        
        # Redirección Delegada (Datos Lógicos)
        redir_data = service.get_redirection_params(
            new_id=new_id,
            op_std_id=op_std_id,
            cant_sitios=cantidad_sitios,
            es_fuera_horario=fuera_horario,
            legacy_term=legacy_term,
            is_extraordinario=False
        )

        # Construcción de URL y Headers en Router (capa de transporte)
        query_string = urllib.parse.urlencode(redir_data["query_params"])
        full_redirect_url = f"{redir_data['redirect_url']}?{query_string}"
        
        return Response(status_code=200, headers={"HX-Redirect": full_redirect_url})
    
    except ValueError as e:
        # Errores de validación de negocio
        return templates.TemplateResponse(
            "comercial/error_message.html", 
            {"request": request, "detail": str(e)},
            status_code=200 
        )
    except asyncpg.PostgresError as e:
        logger.error(f"Error BD creando oportunidad: {e}", exc_info=True)
        return HTMLResponse("<div class='bg-red-100 border-l-4 border-red-500 text-red-700 p-4 mb-4' role='alert'><p class='font-bold'>Error de Base de Datos</p><p>Ocurrió un error al guardar. Intente nuevamente.</p></div>", status_code=500)
    except Exception as e:
        logger.error(f"Error creando oportunidad: {e}", exc_info=True)
        return HTMLResponse("<div class='bg-red-100 border-l-4 border-red-500 text-red-700 p-4 mb-4' role='alert'><p class='font-bold'>Error del Sistema</p><p>Ocurrió un error inesperado.</p></div>", status_code=500)

# ===== FORMULARIO EXTRAORDINARIO (ADMIN/MANAGER ONLY) =====
@router.get("/form-extraordinario", include_in_schema=False)
async def get_comercial_form_extraordinario(
    request: Request,
    user_context = Depends(get_current_user_context),
    conn = Depends(get_db_connection),
    service: ComercialService = Depends(get_comercial_service),
    _ = require_manager_access("comercial")
):
    """Shows the extraordinary creation form (ADMIN/MANAGER ONLY)."""
    
    # Validación de Rol: Delegada a require_manager_access
    role = user_context.get("role")

    
    # Validación de sesión
    if not user_context.get("email"):
        return HTMLResponse(status_code=401)
    
    # Validar token
    token = await get_valid_graph_token(request)
    if not token:
        return Response(status_code=200, headers={"HX-Redirect": "/auth/login?expired=1"})

    # Generar canal default
    canal_default = ComercialService.get_canal_from_user_name(user_context.get("user_name"))
    
    # Obtener catálogos (Solo PRE_OFERTA y SIMULACION para extraordinarias)
    catalogos = await service.get_catalogos_extraordinario(conn)

    return templates.TemplateResponse("shared/forms/oportunidad_form.html", {
        "request": request,
        "catalogos": catalogos,
        "canal_default": canal_default,
        "user_name": user_context.get("user_name"),
        "role": role,
        "module_roles": user_context.get("module_roles", {}),
        "post_url": "/comercial/form-extraordinario",
        "cancel_url": "/comercial/ui",
        "is_extraordinario": True
    }, headers={"HX-Title": "Enertika Core Ops | Solicitud Extraordinaria"})

@router.post("/form-extraordinario")
async def handle_oportunidad_extraordinaria(
    request: Request,
    # --- Datos del Cliente ---
    cliente_nombre: str = Form(..., min_length=3),
    cliente_id: Optional[UUID] = Form(None), # Nuevo campo
    nombre_proyecto: str = Form(...),
    canal_venta: str = Form(...),
    id_tecnologia: int = Form(...),
    id_tipo_solicitud: int = Form(...),
    cantidad_sitios: int = Form(...),
    prioridad: str = Form(...),
    direccion_obra: str = Form(...),
    coordenadas_gps: Optional[str] = Form(None),
    google_maps_link: Optional[str] = Form(None),
    sharepoint_folder_url: Optional[str] = Form(None),
    
    # --- Nuevos Campos v2 ---
    es_licitacion: bool = Form(False),
    solicitado_por_id: Optional[UUID] = Form(None),

    # --- Campo Fecha Manual (OBLIGATORIO en extraordinarias) ---
    fecha_manual: str = Form(...),
    fecha_ideal_usuario: Optional[date] = Form(None),
    
    # --- Campos BESS (Opcionales) ---
    bess_uso_sistema: List[str] = Form([]),
    bess_cargas_criticas: Optional[float] = Form(None),
    bess_tiene_motores: bool = Form(False),
    bess_potencia_motor: Optional[float] = Form(None),
    bess_tiempo_autonomia: Optional[str] = Form(None),
    bess_voltaje_operacion: Optional[str] = Form(None),
    bess_cargas_separadas: bool = Form(False),
    bess_tiene_planta_emergencia: bool = Form(False),

    # --- Dependencias ---
    conn = Depends(get_db_connection),
    service: ComercialService = Depends(get_comercial_service),
    context = Depends(get_current_user_context),
    ms_auth = Depends(get_ms_auth),
    _ = require_manager_access("comercial")
):
    try:

        # Validación de sesión y token
        token = await get_valid_graph_token(request)
        if not token:
             return Response(status_code=200, headers={"HX-Redirect": "/auth/login?expired=1"})

         # Construir objeto BESS (Delegado al Service)
        detalles_bess = ComercialService.build_bess_detail(
            uso_sistema=bess_uso_sistema,
            cargas_criticas=bess_cargas_criticas,
            tiene_motores=bess_tiene_motores,
            potencia_motor=bess_potencia_motor,
            tiempo_autonomia=bess_tiempo_autonomia,
            voltaje_operacion=bess_voltaje_operacion,
            cargas_separadas=bess_cargas_separadas,
            tiene_planta_emergencia=bess_tiene_planta_emergencia
        )

        oportunidad_data = OportunidadCreateCompleta(
            cliente_nombre=cliente_nombre,
            cliente_id=cliente_id,
            nombre_proyecto=nombre_proyecto,
            canal_venta=canal_venta,
            id_tecnologia=id_tecnologia,
            id_tipo_solicitud=id_tipo_solicitud,
            cantidad_sitios=cantidad_sitios,
            prioridad=prioridad,
            direccion_obra=direccion_obra,
            coordenadas_gps=coordenadas_gps,
            google_maps_link=google_maps_link,
            sharepoint_folder_url=sharepoint_folder_url,
            fecha_manual_str=fecha_manual,
            detalles_bess=detalles_bess,
            es_licitacion=es_licitacion,
            solicitado_por_id=solicitado_por_id,
            fecha_ideal_usuario=fecha_ideal_usuario,
            clasificacion_solicitud="EXTRAORDINARIO"
        )

        # Ejecutar Transacción en Servicio
        new_id, op_id_estandar, es_fuera_horario = await service.crear_oportunidad_transaccional(
            conn, oportunidad_data, context
        )
        
        # Marcar como extraordinaria: email_enviado = TRUE
        await service.marcar_extraordinaria_enviada(conn, new_id)
        
        # --- ENVÍO DE NOTIFICACIÓN AUTOMÁTICA ---
        base_url = str(request.base_url).rstrip('/')
        await service.enviar_notificacion_extraordinaria(
            conn=conn,
            ms_auth=ms_auth,
            token=token,
            id_oportunidad=new_id,
            base_url=base_url,
            user_email=context['user_email']
        )
        # -----------------------------------------------
        
        logger.info(f"Solicitud extraordinaria {op_id_estandar} creada y notificada.")

        # Redirección Delegada (Datos Lógicos)
        redir_data = service.get_redirection_params(
            new_id=new_id,
            op_std_id=op_id_estandar,
            cant_sitios=cantidad_sitios,
            es_fuera_horario=es_fuera_horario,
            is_extraordinario=True
        )
        
        # Construcción de URL y Headers
        query_string = urllib.parse.urlencode(redir_data["query_params"])
        full_redirect_url = f"{redir_data['redirect_url']}?{query_string}"
        
        return Response(status_code=200, headers={"HX-Redirect": full_redirect_url})

    except ValueError as e:
        return templates.TemplateResponse(
            "comercial/error_message.html",
            {"request": request, "detail": str(e)},
            status_code=200
        )
    except asyncpg.PostgresError as e:
        logger.error(f"Error BD en solicitud extraordinaria: {e}", exc_info=True)
        return templates.TemplateResponse(
            "comercial/error_message.html",
            {"request": request, "detail": "Error de base de datos. Intente nuevamente."},
            status_code=500
        )
    except Exception as e:
        logger.error(f"Error en creación de solicitud extraordinaria: {e}", exc_info=True)
        return templates.TemplateResponse(
            "comercial/error_message.html",
            {"request": request, "detail": "Ocurrió un error inesperado."},
            status_code=500
        )

@router.delete("/{id_oportunidad}", response_class=HTMLResponse)
async def cancelar_oportunidad(
    request: Request,
    id_oportunidad: UUID,
    service: ComercialService = Depends(get_comercial_service),
    conn = Depends(get_db_connection),
    user_context = Depends(get_current_user_context),
    _auth = require_module_access("comercial", "editor")
):
    """Elimina borrador y fuerza una recarga completa al Dashboard."""
    
    # Protección de Sesión
    access_token = await get_valid_graph_token(request)
    if not access_token:
        return Response(status_code=200, headers={"HX-Redirect": "/auth/login?expired=1"})

    # Borrar datos en BD via Service
    await service.cancelar_oportunidad(conn, id_oportunidad, user_context)

    return Response(status_code=200, headers={"HX-Redirect": "/comercial/ui"}) 

@router.post("/reasignar/{id_oportunidad}")
async def reasignar_oportunidad(
    request: Request,
    id_oportunidad: UUID,
    new_owner_id: UUID = Form(...),
    service: ComercialService = Depends(get_comercial_service),
    conn = Depends(get_db_connection),
    user_context = Depends(get_current_user_context),
    _ = require_manager_access("comercial")
):
    """Permite a un Manager/Admin transferir la oportunidad a otro usuario."""
    await service.reasignar_oportunidad(conn, id_oportunidad, new_owner_id, user_context)
    
    # Retornar toast de éxito via OOB swap
    return templates.TemplateResponse("shared/toast.html", {
        "request": request,
        "type": "success",
        "title": "Reasignación exitosa",
        "message": "Oportunidad reasignada correctamente."
    })


# ----------------------------------------
# Endpoints para Paso 3
# ----------------------------------------

@router.get("/paso3/{id_oportunidad}", include_in_schema=False)
async def get_paso3_email_form(
    request: Request,
    id_oportunidad: UUID,
    legacy_term: Optional[str] = None,
    conn = Depends(get_db_connection),
    service: ComercialService = Depends(get_comercial_service),
    context = Depends(get_current_user_context),
    _auth = require_module_access("comercial", "editor")
):
    """Formulario final de envío de correo."""
    if not await get_valid_graph_token(request):
        return Response(status_code=200, headers={"HX-Redirect": "/auth/login?expired=1"})
    
    
    # Delegar TODA la lógica de preparación de datos y reglas al Service
    data = await service.get_data_for_email_form(conn, id_oportunidad, context)
    if not data: return HTMLResponse("Oportunidad no encontrada", 404)
    
    template = "comercial/email_form.html" if request.headers.get("hx-request") else "comercial/email_full.html"
    
    return templates.TemplateResponse(template, {
        "request": request,
        **data, # Desempaquetar dict del servicio
        "legacy_term": legacy_term,
        "user_name": context.get("user_name"),
        "role": context.get("role"),
        "module_roles": context.get("module_roles", {})
    })

# ----------------------------------------
# Endpoints para Previsualización de Excel
# ----------------------------------------

@router.post("/upload-preview", response_class=HTMLResponse)
async def upload_preview_endpoint(
    request: Request,
    id_oportunidad: str = Form(...),
    file: UploadFile = File(...),
    extraordinaria: int = Form(0),
    service: ComercialService = Depends(get_comercial_service),
    conn = Depends(get_db_connection),
    user_context = Depends(get_current_user_context),
    _auth = require_module_access("comercial", "editor")
):
    """Procesa previsualización de Excel (Lógica movida al Service)."""
    try:
        # Validación de tamaño usando utilidad centralizada
        validate_file_size(file, max_size_mb=10)
        
        contents = await file.read()
        uuid_op = UUID(id_oportunidad)
        
        # Delegar Lógica Compleja al Service
        result = await service.preview_site_upload(conn, contents, uuid_op, user_context)
        
        return templates.TemplateResponse("comercial/partials/upload_preview.html", {
            "request": request,
            "columns": result["columns"],
            "preview_rows": result["preview_rows"],
            "total_rows": result["total_rows"],
            "json_data": result["json_data"],
            "op_id": id_oportunidad,
            "extraordinaria": extraordinaria
        })
    except HTTPException as he:
        return templates.TemplateResponse("comercial/partials/toasts/toast_error.html", {"request": request, "title": "Error", "message": he.detail})
    except Exception as e:
        logger.error(f"Error upload: {e}", exc_info=True)
        return templates.TemplateResponse("comercial/partials/toasts/toast_error.html", {"request": request, "title": "Error técnico", "message": "Error procesando el archivo. Verifique el formato e intente nuevamente."})


@router.post("/upload-confirm", response_class=HTMLResponse)
async def upload_confirm_endpoint(
    request: Request,
    sitios_json: str = Form(...),
    op_id: str = Form(...),
    extraordinaria: int = Form(0),
    service: ComercialService = Depends(get_comercial_service),
    conn = Depends(get_db_connection),
    user_context = Depends(get_current_user_context),
    _auth = require_module_access("comercial", "editor")
):
    try:
        uuid_op = UUID(op_id)
        
        count = await service.confirm_site_upload(conn, uuid_op, sitios_json, user_context)
        
        if extraordinaria == 1:
            return templates.TemplateResponse("comercial/partials/messages/success_redirect.html", {
                "request": request,
                "message": f"Carga Exitosa ({count} sitios). Redirigiendo...",
                "redirect_url": "/comercial/ui"
            })
        else:
            return templates.TemplateResponse("comercial/partials/messages/success_redirect.html", {
                "request": request,
                "message": f"Carga Exitosa ({count} sitios). Cargando paso 3...",
                "hx_url": f"/comercial/paso3/{op_id}"
            })
    except HTTPException as he:
        return HTMLResponse(f"<div class='text-red-500'>Error: {he.detail}</div>", 400)

@router.get("/paso2/{id_oportunidad}", include_in_schema=False)
async def get_paso_2_form(
    request: Request,
    id_oportunidad: UUID,
    extraordinaria: int = 0,
    conn = Depends(get_db_connection),
    service: ComercialService = Depends(get_comercial_service),
    user_context = Depends(get_current_user_context),
    _auth = require_module_access("comercial", "editor")
):
    """Re-renderiza el formulario de carga multisitio (Paso 2)."""
    row = await service.get_paso2_data(conn, id_oportunidad)
    if not row:
         return HTMLResponse("Oportunidad no encontrada", 404)

    return templates.TemplateResponse(
        "comercial/paso2.html",
        {
            "request": request,
            "oportunidad_id": id_oportunidad,
            "nombre_cliente": row['cliente_nombre'],
            "id_interno": row['id_interno_simulacion'],
            "titulo_proyecto": row['titulo_proyecto'],
            "cantidad_declarada": row['cantidad_sitios'],
            "extraordinaria": extraordinaria
        }
    )

@router.post("/crear-seguimiento/{parent_id}")
async def crear_seguimiento(
    request: Request,
    parent_id: UUID,
    tipo_solicitud: str = Form(...), # "OFERTA_FINAL", "ACTUALIZACION"
    prioridad: str = Form(...),
    service: ComercialService = Depends(get_comercial_service),
    conn = Depends(get_db_connection),
    user_context = Depends(get_current_user_context),
    _auth = require_module_access("comercial", "editor")
):
    """Acción del Historial: Crea seguimiento y salta directo al correo."""
    if not user_context.get("email"): 
        return HTMLResponse(status_code=401)

    new_id = await service.create_followup_oportunidad(
        parent_id, tipo_solicitud, prioridad, conn, 
        user_context['user_db_id'], user_context['user_name']
    )
    
    # Salto directo al Paso 3 (El usuario ya no carga Excel)
    return HTMLResponse(headers={"HX-Location": f"/comercial/paso3/{new_id}"})

@router.delete("/sitios/{id_sitio}", response_class=HTMLResponse)
async def delete_sitio_endpoint(
    request: Request,
    id_sitio: UUID,
    service: ComercialService = Depends(get_comercial_service),
    conn = Depends(get_db_connection),
    user_context = Depends(get_current_user_context),
    _auth = require_module_access("comercial", "editor")
):
    if not await get_valid_graph_token(request):
        return Response(status_code=200, headers={"HX-Redirect": "/auth/login?expired=1"})
    
    await service.delete_sitio(conn, id_sitio, user_context)
    return HTMLResponse("", status_code=200)


# ----------------------------------------
# Endpoint: Cierre de Venta (Marcar como Ganada)
# ----------------------------------------

@router.post("/cierre-venta/{id_oportunidad}")
async def cierre_venta(
    request: Request,
    id_oportunidad: UUID,
    sitios_ganados: List[UUID] = Form(default=[]),  # Solo para multisitio (opcional)
    service: ComercialService = Depends(get_comercial_service),
    conn = Depends(get_db_connection),
    user_context = Depends(get_current_user_context),
    _ = require_module_access("comercial", "editor")
):
    """
    Marca una oportunidad como Ganada (cierre de venta).
    
    Reglas de negocio:
    - Solo se puede ejecutar si status actual = Entregado
    - Para multisitio: sitios_ganados define cuáles sitios se ganaron (el resto = Perdido)
    - Para unisitio: todos los sitios pasan a Ganada
    - Los KPIs ya fueron calculados en el paso anterior, se heredan
    """
    try:
        result = await service.marcar_como_ganada(
            conn, id_oportunidad, sitios_ganados, user_context
        )
        
        # Redirigir a la sección de ganadas con confetti
        return HTMLResponse(
            headers={"HX-Redirect": f"/comercial/ui?tab=ganadas&confetti=1"}
        )
        
    except HTTPException as he:
        return templates.TemplateResponse(
            "comercial/partials/toasts/toast_error.html",
            {"request": request, "title": "Error", "message": he.detail}
        )
    except Exception as e:
        logger.error(f"Error en cierre de venta: {e}", exc_info=True)
        return templates.TemplateResponse(
            "comercial/partials/toasts/toast_error.html",
            {"request": request, "title": "Error", "message": "Ocurrió un error al procesar el cierre de venta."}
        )
