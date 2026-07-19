from fastapi import APIRouter, Request, Depends, HTTPException, Form, UploadFile, File, Response
from fastapi.templating import Jinja2Templates
from datetime import date, time, datetime
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from uuid import UUID
from typing import Optional, List
import io
import logging
import asyncpg
import pandas as pd
import asyncio
import urllib.parse


import jinja2

from core.database import get_db_connection
from core.microsoft import get_ms_auth
from core.security import get_current_user_context, get_valid_graph_token
from core.permissions import require_module_access, require_manager_access, require_role
from core.config import settings
from core.pdf_service.service import PDFService, get_pdf_service
from core.timezone import ensure_mx, now_mx
from .schemas import OportunidadCreateCompleta
from .service import ComercialService, get_comercial_service
from .email_handler import get_email_handler
from .file_utils import validate_file_size
from .db_service import QUERY_BUSCAR_OPORTUNIDADES_PARA_RELACIONAR
from . import reportes_service
from .reportes_excel_builder import construir_bytes_general, construir_bytes_por_cliente, generar_nombre_archivo
from modules.rrhh.excel_utils import format_date, format_datetime
from modules.shared.utils import excel_bytes_response

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
    can_filter_responsables = role in ("ADMIN", "MANAGER")
    
    # Detección inteligente: HTMX devuelve tabs.html, carga completa devuelve dashboard.html
    # HX-History-Restore-Request: HTMX lo envía cuando restaura desde historial (Back/Forward)
    # En ese caso retornar full page para que el layout (sidebar/header) esté completo
    is_htmx = request.headers.get("hx-request")
    is_history_restore = request.headers.get("hx-history-restore-request")
    if is_htmx and not is_history_restore:
        template = "comercial/tabs.html"
    else:
        template = "comercial/dashboard.html"
        
    # Cargar catálogos para filtros globales
    catalogos = await service.get_catalogos_ui(
        conn,
        include_responsables_con_oportunidades=can_filter_responsables,
    )

    # Verificar si debe mostrar el popup
    show_popup = await service.should_show_popup(conn, context.get("email"))

    # Conteo de borradores para badge del tab
    borradores_count = await service.get_borradores_count(conn, context)

    # ADMIN global (bypass, sin entrada en module_roles) o MANAGER con acceso viewer+ al módulo
    puede_generar_reporte_comercial = role == "ADMIN" or (
        role == "MANAGER" and context.get("module_roles", {}).get("comercial") in ("viewer", "editor", "admin")
    )
    reporte_fecha_inicio_default, reporte_fecha_fin_default = reportes_service.defaults_fecha_reporte()

    return templates.TemplateResponse(request, template, {"user_name": user_name,
        "role": role,
        "module_roles": context.get("module_roles", {}),
        "current_module_role": context.get("module_roles", {}).get("comercial", "viewer"),
        "can_filter_responsables": can_filter_responsables,
        "catalogos": catalogos,
        "show_custom_popup": show_popup,
        "borradores_count": borradores_count,
        "puede_generar_reporte_comercial": puede_generar_reporte_comercial,
        "reporte_fecha_inicio_default": reporte_fecha_inicio_default.isoformat(),
        "reporte_fecha_fin_default": reporte_fecha_fin_default.isoformat(),
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

    return templates.TemplateResponse(request, "shared/forms/oportunidad_form.html", {"canal_default": canal_default,
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
    return templates.TemplateResponse(request, "comercial/partials/graphs.html", {"stats": stats})

@router.get("/partials/cards", include_in_schema=False)
async def get_cards_partial(
    request: Request,
    tab: str = "activos",
    q: Optional[str] = None,
    limit: int = 20,
    page: int = 1,
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
    """Partial: List of Opportunities (Cards/Grid)"""
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
    
    result = await service.get_oportunidades_list(
        conn,
        user_context=user_context,
        tab=tab,
        q=q,
        limit=limit,
        page=page,
        subtab=subtab,
        filtro_usuario_id=f_user,
        filtro_tipo_id=f_tipo,
        filtro_estatus_id=f_estatus,
        filtro_tecnologia_id=f_tecnologia,
        filtro_fecha_inicio=f_inicio,
        filtro_fecha_fin=f_fin
    )

    ops_processed = [{**op, 'es_multisitio': ComercialService.is_originally_multisite(op)} for op in result["items"]]

    return templates.TemplateResponse(
        request, "comercial/partials/cards.html",
        {
            "oportunidades": ops_processed,
            "user_token": has_valid_token,
            "current_tab": tab,
            "subtab": subtab,
            "q": q,
            "is_global_search": bool(q and q.strip()),
            "limit": result["limit"],
            "page": result["page"],
            "total": result["total"],
            "total_pages": result["total_pages"],
            "base_url": "/comercial/partials/cards",
            "hx_target": "#tab-content",
            "hx_include": ".global-filter",
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
        request, "comercial/partials/sitios_list.html",
        {"sitios": rows}
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
        request, "shared/partials/comentarios_list.html",
        {"comentarios": comentarios}
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
        request, "shared/modals/bess_detalle_modal.html",  # New Modal Wrapper
        {"bess": bess}
    )

@router.get("/partials/progreso/{id_oportunidad}", include_in_schema=False)
async def get_progreso_partial(
    request: Request,
    id_oportunidad: UUID,
    service: ComercialService = Depends(get_comercial_service),
    conn=Depends(get_db_connection),
    _=require_module_access("comercial"),
):
    """Modal de progreso de proyecto para una oportunidad ganada."""
    progreso = await service.get_progreso_proyecto(conn, id_oportunidad)
    return templates.TemplateResponse(
        request, "comercial/partials/progreso_modal.html",
        {"progreso": progreso, "id_oportunidad": str(id_oportunidad)},
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
    hora_ideal_usuario: Optional[time] = Form(None),   # Hora ideal (solo LEVANTAMIENTO)
    legacy_search_term: Optional[str] = Form(None),  # Capturar término legacy
    sharepoint_folder_url: Optional[str] = Form(None),  # Reubicado del Paso 1
    archivos_extra: List[UploadFile] = File(default=[]),
    service: ComercialService = Depends(get_comercial_service),
    ms_auth = Depends(get_ms_auth),
    conn = Depends(get_db_connection),
    email_handler = Depends(get_email_handler),  # Inyectar EmailHandler
    context = Depends(get_current_user_context),
    _auth = require_module_access("comercial", "editor")
):
    """Envía el correo de notificación usando el token de la sesión."""
    
    # Actualizar sharepoint_folder_url si se proporcionó (reubicado del Paso 1)
    if sharepoint_folder_url and sharepoint_folder_url.strip():
        await conn.execute(
            "UPDATE tb_oportunidades SET sharepoint_folder_url = $1 WHERE id_oportunidad = $2",
            sharepoint_folder_url.strip(), id_oportunidad
        )
    
    # Actualizar fecha_ideal_usuario si se proporcionó (para seguimientos)
    if fecha_ideal_usuario:
        await conn.execute(
            "UPDATE tb_oportunidades SET fecha_ideal_usuario = $1 WHERE id_oportunidad = $2",
            fecha_ideal_usuario, id_oportunidad
        )

        # Para LEVANTAMIENTO: guardar fecha+hora en tb_levantamientos.fecha_ideal_solicitante
        tipo_codigo = await conn.fetchval("""
            SELECT ts.codigo_interno
              FROM tb_oportunidades o
              JOIN tb_cat_tipos_solicitud ts ON o.id_tipo_solicitud = ts.id
             WHERE o.id_oportunidad = $1
        """, id_oportunidad)
        if tipo_codigo == 'LEVANTAMIENTO':
            if hora_ideal_usuario:
                fecha_ideal_dt = datetime.combine(fecha_ideal_usuario, hora_ideal_usuario)
            else:
                fecha_ideal_dt = datetime.combine(fecha_ideal_usuario, time(0, 0))
            await conn.execute("""
                UPDATE tb_levantamientos
                   SET fecha_ideal_solicitante = $1 AT TIME ZONE 'America/Mexico_City',
                       updated_at              = NOW()
                 WHERE id_oportunidad = $2
            """, fecha_ideal_dt, id_oportunidad)

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

    thread_ids = await ms_auth.find_thread_candidates(token, search_term)
    
    if thread_ids:
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
        sharepoint_folder_url=None,  # Se captura en Paso 3 (email_form)
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
            request, "comercial/error_message.html", 
            {"detail": str(e)},
            status_code=200 
        )
    except asyncpg.PostgresError as e:
        logger.error(f"Error BD creando oportunidad: {e}", exc_info=True)
        return HTMLResponse("<div class='bg-red-100 border-l-4 border-red-500 text-red-700 p-4 mb-4' role='alert'><p class='font-bold'>Error de Base de Datos</p><p>Ocurrió un error al guardar. Intente nuevamente.</p></div>", status_code=500)
    except Exception as e:
        logger.error(f"Error creando oportunidad: {e}", exc_info=True)
        return HTMLResponse("<div class='bg-red-100 border-l-4 border-red-500 text-red-700 p-4 mb-4' role='alert'><p class='font-bold'>Error del Sistema</p><p>Ocurrió un error inesperado.</p></div>", status_code=500)

# ===== BÚSQUEDA DE OPORTUNIDADES PARA RELACIONAR (HTMX) =====
@router.get("/buscar-para-relacionar", response_class=HTMLResponse, include_in_schema=False)
async def buscar_oportunidades_para_relacionar(
    request: Request,
    q: str = "",
    conn = Depends(get_db_connection),
    _ = require_manager_access("comercial")
):
    if not q or len(q.strip()) < 2:
        return HTMLResponse("")

    patron = f"%{q.strip()}%"
    filas = await conn.fetch(QUERY_BUSCAR_OPORTUNIDADES_PARA_RELACIONAR, patron)
    resultados = [dict(r) for r in filas]

    return templates.TemplateResponse(
        request, "comercial/partials/buscar_oportunidad_relacionar.html",
        {"resultados": resultados}
    )


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

    # Validar token
    token = await get_valid_graph_token(request)
    if not token:
        return Response(status_code=200, headers={"HX-Redirect": "/auth/login?expired=1"})

    # Generar canal default
    canal_default = ComercialService.get_canal_from_user_name(user_context.get("user_name"))
    
    # Obtener catálogos (Solo PRE_OFERTA y SIMULACION para extraordinarias)
    catalogos = await service.get_catalogos_extraordinario(conn)

    return templates.TemplateResponse(request, "shared/forms/oportunidad_form.html", {"catalogos": catalogos,
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
    
    # --- Nuevos Campos v2 ---
    es_licitacion: bool = Form(False),
    solicitado_por_id: Optional[UUID] = Form(None),

    # --- Campo Fecha Manual (OBLIGATORIO en extraordinarias) ---
    fecha_manual: str = Form(...),
    fecha_ideal_usuario: Optional[date] = Form(None),

    # --- Relacionar con oportunidad existente (OPCIONAL) ---
    parent_id: Optional[UUID] = Form(None),
    
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

        # Validar que parent_id sea raíz del hilo (sin padre propio)
        if parent_id:
            es_raiz = await conn.fetchval(
                "SELECT parent_id IS NULL FROM tb_oportunidades WHERE id_oportunidad = $1",
                parent_id
            )
            if not es_raiz:
                raise ValueError("La oportunidad seleccionada no es un registro raiz. Solo se puede vincular al origen del hilo.")

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
            sharepoint_folder_url=None,  # Se captura en Paso 3 (email_form)
            fecha_manual_str=fecha_manual,
            detalles_bess=detalles_bess,
            es_licitacion=es_licitacion,
            solicitado_por_id=solicitado_por_id,
            fecha_ideal_usuario=fecha_ideal_usuario,
            clasificacion_solicitud="EXTRAORDINARIO",
            parent_id=parent_id
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
            request, "comercial/error_message.html",
            {"detail": str(e)},
            status_code=200
        )
    except asyncpg.PostgresError as e:
        logger.error(f"Error BD en solicitud extraordinaria: {e}", exc_info=True)
        return templates.TemplateResponse(
            request, "comercial/error_message.html",
            {"detail": "Error de base de datos. Intente nuevamente."},
            status_code=500
        )
    except Exception as e:
        logger.error(f"Error en creación de solicitud extraordinaria: {e}", exc_info=True)
        return templates.TemplateResponse(
            request, "comercial/error_message.html",
            {"detail": "Ocurrió un error inesperado."},
            status_code=500
        )

@router.get("/partials/borradores", response_class=HTMLResponse, include_in_schema=False)
async def get_borradores_partial(
    request: Request,
    service: ComercialService = Depends(get_comercial_service),
    conn = Depends(get_db_connection),
    user_context = Depends(get_current_user_context),
    _ = require_module_access("comercial"),
):
    """Retorna la vista parcial de borradores (oportunidades sin enviar <24h)."""
    borradores = await service.get_borradores(conn, user_context)
    return templates.TemplateResponse(request, "comercial/partials/borradores.html", {"borradores": borradores,
    })


@router.delete("/borrador/{id_oportunidad}", response_class=HTMLResponse)
async def eliminar_borrador(
    request: Request,
    id_oportunidad: UUID,
    service: ComercialService = Depends(get_comercial_service),
    conn = Depends(get_db_connection),
    user_context = Depends(get_current_user_context),
    _ = require_module_access("comercial", "editor"),
):
    """Elimina un borrador y devuelve la lista actualizada en el mismo tab."""
    await service.cancelar_oportunidad(conn, id_oportunidad, user_context)
    borradores = await service.get_borradores(conn, user_context)
    return templates.TemplateResponse(request, "comercial/partials/borradores.html", {"borradores": borradores,
    })


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

@router.get("/reasignar-modal/{id_oportunidad}", response_class=HTMLResponse)
async def get_reasignar_modal(
    request: Request,
    id_oportunidad: UUID,
    service: ComercialService = Depends(get_comercial_service),
    conn = Depends(get_db_connection),
    _auth = require_module_access("comercial", "editor"),
):
    usuarios = await service.get_usuarios_activos(conn)
    return templates.TemplateResponse(request, "comercial/modals/reasignar_modal.html", {
        "id_oportunidad": id_oportunidad,
        "usuarios": usuarios,
    })


@router.post("/reasignar/{id_oportunidad}")
async def reasignar_oportunidad(
    request: Request,
    id_oportunidad: UUID,
    new_owner_id: UUID = Form(...),
    motivo: Optional[str] = Form(None),
    service: ComercialService = Depends(get_comercial_service),
    ms_auth = Depends(get_ms_auth),
    conn = Depends(get_db_connection),
    user_context = Depends(get_current_user_context),
    _auth = require_module_access("comercial", "editor")
):
    # Sin sesión de Graph activa: la transferencia en BD no depende de correo,
    # así que no se bloquea por esto — solo se omite la búsqueda de hilo.
    access_token = await get_valid_graph_token(request)

    try:
        if access_token:
            preview_context = await service.preparar_transferencia_email_preview(
                conn=conn,
                ms_auth=ms_auth,
                access_token=access_token,
                user_email=user_context.get("user_email") or user_context.get("email"),
                id_oportunidad=id_oportunidad,
                new_owner_id=new_owner_id,
                motivo=motivo,
                user_context=user_context,
            )
        else:
            transfer_context = await service.validar_transferencia_comercial(
                conn, id_oportunidad, new_owner_id, motivo, user_context
            )
            preview_context = {
                "requires_preview": False,
                "transfer_context": transfer_context,
                "notice_type": "warning",
                "notice_title": "Transferencia sin correo",
                "notice_message": "No hay sesión de Microsoft activa. La transferencia se realizará sin acción de correo.",
            }
    except HTTPException as exc:
        return templates.TemplateResponse(request, "shared/toast.html", {
            "type": "error",
            "title": "No se pudo transferir",
            "message": exc.detail,
        }, headers={"HX-Reswap": "none", "X-Transfer-Error": "1"})
    except asyncpg.PostgresError as exc:
        logger.exception("[REASIGNAR] Error de base de datos preparando transferencia")
        return templates.TemplateResponse(request, "shared/toast.html", {
            "type": "error",
            "title": "No se pudo transferir",
            "message": "Error de base de datos al preparar la transferencia.",
        }, headers={"HX-Reswap": "none", "X-Transfer-Error": "1"})

    if preview_context.get("requires_preview"):
        return templates.TemplateResponse(request, "comercial/modals/reasignar_email_preview.html", {
            "id_oportunidad": id_oportunidad,
            "new_owner_id": new_owner_id,
            "motivo": motivo or "",
            "draft": preview_context["draft"],
        })

    try:
        is_manager = await service.confirmar_transferencia_con_contexto(
            conn, id_oportunidad, new_owner_id, motivo, user_context,
            transfer_context=preview_context.get("transfer_context"),
        )
    except HTTPException as exc:
        return templates.TemplateResponse(request, "shared/toast.html", {
            "type": "error",
            "title": "No se pudo transferir",
            "message": exc.detail,
        }, headers={"HX-Reswap": "none", "X-Transfer-Error": "1"})
    except asyncpg.PostgresError as exc:
        logger.exception("[REASIGNAR] Error de base de datos confirmando transferencia")
        return templates.TemplateResponse(request, "shared/toast.html", {
            "type": "error",
            "title": "No se pudo transferir",
            "message": "Error de base de datos al actualizar el responsable.",
        }, headers={"HX-Reswap": "none", "X-Transfer-Error": "1"})

    toast_context = {
        "type": preview_context.get("notice_type", "success"),
        "title": preview_context.get("notice_title", "Transferencia exitosa"),
        "message": preview_context.get("notice_message", "Responsable comercial actualizado."),
    }
    if not is_manager:
        toast_context["redirect_url"] = "/comercial/ui"
    return templates.TemplateResponse(request, "shared/toast.html", toast_context)


@router.post("/reasignar/{id_oportunidad}/confirmar-correo")
async def confirmar_reasignacion_correo(
    request: Request,
    id_oportunidad: UUID,
    draft_id: str = Form(...),
    new_owner_id: UUID = Form(...),
    motivo: Optional[str] = Form(None),
    subject: str = Form(...),
    body_text: str = Form(...),
    service: ComercialService = Depends(get_comercial_service),
    ms_auth = Depends(get_ms_auth),
    conn = Depends(get_db_connection),
    user_context = Depends(get_current_user_context),
    _auth = require_module_access("comercial", "editor"),
):
    access_token = await get_valid_graph_token(request)
    if not access_token:
        return Response(status_code=200, headers={"HX-Redirect": "/auth/login?expired=1"})

    email_sent = False
    try:
        await service.validar_transferencia_comercial(
            conn, id_oportunidad, new_owner_id, motivo, user_context
        )
        ok, msg = await ms_auth.send_draft(
            access_token=access_token,
            from_email=user_context.get("user_email") or user_context.get("email"),
            draft_id=draft_id,
            subject=subject,
            body_text=body_text,
        )
        if not ok:
            return templates.TemplateResponse(request, "shared/toast.html", {
                "type": "error",
                "title": "No se pudo enviar el correo",
                "message": msg,
            }, headers={"HX-Reswap": "none", "X-Transfer-Error": "1"})

        email_sent = True
        is_manager = await service.confirmar_transferencia_con_contexto(
            conn, id_oportunidad, new_owner_id, motivo, user_context
        )
    except HTTPException as exc:
        title = "Correo enviado, transferencia pendiente" if email_sent else "No se pudo transferir"
        if email_sent:
            logger.error(
                "[REASIGNAR] Correo de traspaso enviado (borrador %s, oportunidad %s) pero la "
                "actualización de responsable_comercial_id NO se aplicó: %s. Requiere revisión manual.",
                draft_id, id_oportunidad, exc.detail,
            )
        return templates.TemplateResponse(request, "shared/toast.html", {
            "type": "error",
            "title": title,
            "message": exc.detail,
        }, headers={"HX-Reswap": "none", "X-Transfer-Error": "1"})
    except asyncpg.PostgresError as exc:
        logger.exception("[REASIGNAR] Error de base de datos tras enviar correo de transferencia")
        title = "Correo enviado, transferencia pendiente" if email_sent else "No se pudo transferir"
        return templates.TemplateResponse(request, "shared/toast.html", {
            "type": "error",
            "title": title,
            "message": "Error de base de datos al actualizar el responsable.",
        }, headers={"HX-Reswap": "none", "X-Transfer-Error": "1"})

    toast_context = {
        "type": "success",
        "title": "Transferencia exitosa",
        "message": "Correo enviado y responsable comercial actualizado.",
    }
    if not is_manager:
        toast_context["redirect_url"] = "/comercial/ui"
    return templates.TemplateResponse(request, "shared/toast.html", toast_context)


@router.post("/reasignar/{id_oportunidad}/cancelar-correo")
async def cancelar_reasignacion_correo(
    request: Request,
    id_oportunidad: UUID,
    draft_id: str = Form(...),
    ms_auth = Depends(get_ms_auth),
    user_context = Depends(get_current_user_context),
    _auth = require_module_access("comercial", "editor"),
):
    access_token = await get_valid_graph_token(request)
    if not access_token:
        return Response(status_code=200, headers={"HX-Redirect": "/auth/login?expired=1"})

    ok, msg = await ms_auth.delete_draft(
        access_token=access_token,
        from_email=user_context.get("user_email") or user_context.get("email"),
        draft_id=draft_id,
    )
    if not ok:
        return templates.TemplateResponse(request, "shared/toast.html", {
            "type": "error",
            "title": "No se pudo cancelar",
            "message": msg,
        }, headers={"HX-Reswap": "none", "X-Transfer-Error": "1"})

    return templates.TemplateResponse(request, "shared/toast.html", {
        "type": "warning",
        "title": "Transferencia cancelada",
        "message": "Se elimino el borrador de correo y no se cambio el responsable.",
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

    try:
        # Delegar TODA la lógica de preparación de datos y reglas al Service
        data = await service.get_data_for_email_form(conn, id_oportunidad, context)
        if not data: return HTMLResponse("Oportunidad no encontrada", 404)
    except ValueError as e:
        return templates.TemplateResponse(
            request, "comercial/error_message.html",
            {"detail": str(e)},
            status_code=200
        )

    template = "comercial/email_form.html" if (request.headers.get("hx-request") and not request.headers.get("hx-history-restore-request")) else "comercial/email_full.html"

    # Buscar correos de usuarios activos en el sistema para la lista desplegable
    system_users = await conn.fetch("SELECT email, nombre FROM tb_usuarios WHERE is_active = TRUE AND email IS NOT NULL AND email != '' ORDER BY nombre")
    user_dict_list = [{"email": u["email"], "name": u["nombre"]} for u in system_users]
    
    return templates.TemplateResponse(request, template, {**data, # Desempaquetar dict del servicio
        "legacy_term": legacy_term,
        "system_users": user_dict_list,
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
    is_conversion: bool = Form(False),
    tipo_solicitud_conv: str = Form(None),
    prioridad_conv: str = Form(None),
    id_tecnologia_conv: Optional[int] = Form(None),
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

        # Delegar Lógica Compleja al Service (skip_quantity_check en modo conversión)
        result = await service.preview_site_upload(conn, contents, uuid_op, user_context, skip_quantity_check=is_conversion)

        return templates.TemplateResponse(request, "comercial/partials/upload_preview.html", {"columns": result["columns"],
            "preview_rows": result["preview_rows"],
            "total_rows": result["total_rows"],
            "json_data": result["json_data"],
            "op_id": id_oportunidad,
            "extraordinaria": extraordinaria,
            "is_conversion": is_conversion,
            "tipo_solicitud_conv": tipo_solicitud_conv,
            "prioridad_conv": prioridad_conv,
            "id_tecnologia_conv": id_tecnologia_conv,
        })
    except HTTPException as he:
        return templates.TemplateResponse(request, "comercial/partials/toasts/toast_error.html", {"title": "Error", "message": he.detail})
    except Exception as e:
        logger.error(f"Error upload: {e}", exc_info=True)
        return templates.TemplateResponse(request, "comercial/partials/toasts/toast_error.html", {"title": "Error técnico", "message": "Error procesando el archivo. Verifique el formato e intente nuevamente."})


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
            return templates.TemplateResponse(request, "comercial/partials/messages/success_redirect.html", {"message": f"Carga Exitosa ({count} sitios). Redirigiendo...",
                "redirect_url": "/comercial/ui"
            })
        else:
            return templates.TemplateResponse(request, "comercial/partials/messages/success_redirect.html", {"message": f"Carga Exitosa ({count} sitios). Cargando paso 3...",
                "hx_url": f"/comercial/paso3/{op_id}"
            })
    except HTTPException as he:
        return HTMLResponse(f"<div class='text-red-500'>Error: {he.detail}</div>", 400)

@router.get("/modal/confirmar-seguimiento/{id_oportunidad}", response_class=HTMLResponse, include_in_schema=False)
async def get_modal_confirmar_seguimiento(
    request: Request,
    id_oportunidad: UUID,
    tipo_solicitud: str,
    prioridad: str = "high",
    service: ComercialService = Depends(get_comercial_service),
    conn = Depends(get_db_connection),
    _auth = require_module_access("comercial", "editor")
):
    """Modal de confirmación de seguimiento para oportunidades unisitio."""
    row = await service.get_paso2_data(conn, id_oportunidad)
    if not row:
        return HTMLResponse("Oportunidad no encontrada", 404)
    ultimo_movimiento = await service.get_ultimo_movimiento_hilo(conn, id_oportunidad)
    tecnologias = await service.get_tecnologias(conn)
    return templates.TemplateResponse(request, "comercial/modals/confirmar_seguimiento.html", {"id_oportunidad": id_oportunidad,
        "tipo_solicitud": tipo_solicitud,
        "prioridad": prioridad,
        "nombre_cliente": row['cliente_nombre'],
        "id_interno": row['id_interno_simulacion'],
        "ultimo_movimiento": ultimo_movimiento,
        "id_tecnologia_actual": row['id_tecnologia'],
        "tecnologias": tecnologias,
    })


@router.get("/paso2-conversion/{id_oportunidad}", include_in_schema=False)
async def get_paso2_conversion(
    request: Request,
    id_oportunidad: UUID,
    tipo_solicitud: str,
    prioridad: str = "high",
    id_tecnologia: Optional[int] = None,
    service: ComercialService = Depends(get_comercial_service),
    conn = Depends(get_db_connection),
    _auth = require_module_access("comercial", "editor")
):
    """Página de carga de sitios para conversión unisitio → multisitio."""
    row = await service.get_paso2_data(conn, id_oportunidad)
    if not row:
        return HTMLResponse("Oportunidad no encontrada", 404)
    return templates.TemplateResponse(request, "comercial/paso2_conversion.html", {"oportunidad_id": id_oportunidad,
        "nombre_cliente": row['cliente_nombre'],
        "id_interno": row['id_interno_simulacion'],
        "titulo_proyecto": row['titulo_proyecto'],
        "tipo_solicitud": tipo_solicitud,
        "prioridad": prioridad,
        "id_tecnologia": id_tecnologia if id_tecnologia is not None else row['id_tecnologia'],
    })


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
        request, "comercial/paso2.html",
        {            "oportunidad_id": id_oportunidad,
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
    tipo_solicitud: str = Form(...),
    prioridad: str = Form(...),
    force_create: bool = Form(False),
    force_ganada: bool = Form(False),
    convertir_multisitio: bool = Form(False),
    sitios_json_conversion: str = Form(None),
    id_tecnologia: Optional[int] = Form(None),
    service: ComercialService = Depends(get_comercial_service),
    conn = Depends(get_db_connection),
    ms_auth = Depends(get_ms_auth),
    user_context = Depends(get_current_user_context),
    _auth = require_module_access("comercial", "editor")
):
    """Acción del Historial: Crea seguimiento y salta directo al correo."""

    # Valida Token Graph antes de procesar
    token = await get_valid_graph_token(request)
    if not token:
        return Response(status_code=200, headers={"HX-Redirect": "/auth/login?expired=1"})

    # Stopper: solo el responsable comercial puede crear seguimientos
    if not await service.is_responsable_para_seguimiento(conn, parent_id, user_context):
        return templates.TemplateResponse(request, "shared/toast.html", {
            "type": "error",
            "title": "Sin permiso",
            "message": "Esta oportunidad fue transferida. Solicita que te devuelvan la responsabilidad para continuar el seguimiento.",
        }, headers={"HX-Reswap": "none"})

    # --- VERIFICACIÓN DE GRUPO ---
    bloqueador = await service.check_grupo_bloqueador(conn, parent_id)

    context_role = user_context.get("role", "USER")
    comercial_role = user_context.get("module_roles", {}).get("comercial", "")
    can_force = (
        context_role == "ADMIN"
        or comercial_role == "admin"
        or (context_role == "MANAGER" and comercial_role in ("editor", "admin"))
    )

    if bloqueador["tipo"] == "activo":
        return templates.TemplateResponse(
            request,
            "comercial/modals/grupo_activo_warning.html",
            {
                "sim": bloqueador.get("sim"),
                "lev": bloqueador.get("lev"),
            },
            headers={"HX-Reswap": "innerHTML", "HX-Retarget": "#modal-secondary-container"},
        )

    if bloqueador["tipo"] == "ganado" and not (force_ganada and can_force):
        return templates.TemplateResponse(
            request,
            "comercial/modals/grupo_ganado_warning.html",
            {
                "parent_id": parent_id,
                "tipo_solicitud": tipo_solicitud,
                "prioridad": prioridad,
                "convertir_multisitio": convertir_multisitio,
                "sitios_json_conversion": sitios_json_conversion or "",
                "id_tecnologia": id_tecnologia,
                "ganado_op_id": bloqueador["op_id"],
                "can_force": can_force,
            },
            headers={"HX-Reswap": "innerHTML", "HX-Retarget": "#modal-secondary-container"},
        )

    # --- THREAD CHECK LOGIC ---
    if not force_create:
        # 1. Predecir título exacto
        expected_title = await service.predict_followup_title(conn, parent_id, tipo_solicitud)

        # 2. Buscar hilo
        thread_id = await ms_auth.find_thread_candidates(token, expected_title)

        # 3. Si NO existe hilo -> Advertencia (preserva datos de conversión)
        if not thread_id:
            return templates.TemplateResponse(request, "comercial/modals/thread_not_found_warning.html", {"expected_title": expected_title,
                "parent_id": parent_id,
                "tipo_solicitud": tipo_solicitud,
                "prioridad": prioridad,
                "convertir_multisitio": convertir_multisitio,
                "sitios_json_conversion": sitios_json_conversion or "",
                "id_tecnologia": id_tecnologia,
            })

    # --- CREACIÓN con conversión diferida (se ejecuta al enviar correo) ---
    try:
        new_id = await service.create_followup_oportunidad(
            parent_id, tipo_solicitud, prioridad, conn,
            user_context['user_db_id'], user_context['user_name'],
            sitios_json_pendiente=sitios_json_conversion if convertir_multisitio else None,
            id_tecnologia=id_tecnologia
        )
    except HTTPException as exc:
        return templates.TemplateResponse(request, "shared/toast.html", {
            "type": "error",
            "title": "No se pudo crear el seguimiento",
            "message": exc.detail,
        }, headers={"HX-Reswap": "none"})
    except asyncpg.PostgresError as exc:
        logger.exception("[SEGUIMIENTO] Error de base de datos creando seguimiento")
        return templates.TemplateResponse(request, "shared/toast.html", {
            "type": "error",
            "title": "No se pudo crear el seguimiento",
            "message": "Error de base de datos al crear el seguimiento.",
        }, headers={"HX-Reswap": "none"})

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
    sitios_ganados: List[UUID] = Form(default=[]),
    service: ComercialService = Depends(get_comercial_service),
    conn = Depends(get_db_connection),
    user_context = Depends(get_current_user_context),
    _ = require_module_access("comercial", "editor")
):
    """
    Marca una oportunidad como Ganada (cierre de venta).
    
    Reglas de negocio:
    - Solo se puede ejecutar si status actual = Entregado
    - Para multisitio: sitios_ganados es obligatorio y define cuáles sitios se ganaron (el resto = Perdido)
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
            request, "comercial/partials/toasts/toast_error.html",
            {"title": "Error", "message": he.detail}
        )
    except Exception as e:
        logger.error(f"Error en cierre de venta: {e}", exc_info=True)
        return templates.TemplateResponse(
            request, "comercial/partials/toasts/toast_error.html",
            {"title": "Error", "message": "Ocurrió un error al procesar el cierre de venta."}
        )


# ----------------------------------------
# Reporte de clientes/empresas (ADMIN global o MANAGER con acceso a Comercial)
# ----------------------------------------

_require_reporte_clientes_role = require_role(["ADMIN", "MANAGER"])


def _formato_fecha_pdf(value) -> str:
    if not value:
        return ""
    return format_date(ensure_mx(value))


def _preparar_reporte_clientes(
    context: dict,
    *,
    filtro_tipo_id: Optional[int],
    filtro_tecnologia_id: Optional[int],
    filtro_estatus_id: Optional[int],
    filtro_fecha_inicio: Optional[str],
    filtro_fecha_fin: Optional[str],
    filtro_cliente_id: Optional[str],
    solo_activos: bool = False,
) -> tuple["reportes_service.FiltrosReporteClientes", str]:
    """Parsea los filtros de query y resuelve el email del solicitante — compartido
    entre los endpoints de Excel y PDF del reporte de clientes."""
    filtros = reportes_service.parse_filtros_reporte_clientes(
        filtro_tipo_id=filtro_tipo_id,
        filtro_tecnologia_id=filtro_tecnologia_id,
        filtro_estatus_id=filtro_estatus_id,
        filtro_fecha_inicio=filtro_fecha_inicio,
        filtro_fecha_fin=filtro_fecha_fin,
        filtro_cliente_id=_safe_uuid(filtro_cliente_id),
        solo_activos=solo_activos,
    )
    solicitante = context.get("user_email") or context.get("email", "")
    return filtros, solicitante


@router.get("/reportes/clientes.xlsx", include_in_schema=False)
async def reporte_clientes_excel(
    filtro_tipo_id: Optional[int] = None,
    filtro_tecnologia_id: Optional[int] = None,
    filtro_estatus_id: Optional[int] = None,
    filtro_fecha_inicio: Optional[str] = None,
    filtro_fecha_fin: Optional[str] = None,
    filtro_cliente_id: Optional[str] = None,
    solo_activos: bool = False,
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context),
    _ = require_module_access("comercial"),
    _role = _require_reporte_clientes_role,
):
    """Descarga el reporte de clientes/empresas en Excel (modo general o enfocado por cliente)."""
    try:
        filtros, solicitante = _preparar_reporte_clientes(
            context,
            filtro_tipo_id=filtro_tipo_id,
            filtro_tecnologia_id=filtro_tecnologia_id,
            filtro_estatus_id=filtro_estatus_id,
            filtro_fecha_inicio=filtro_fecha_inicio,
            filtro_fecha_fin=filtro_fecha_fin,
            filtro_cliente_id=filtro_cliente_id,
            solo_activos=solo_activos,
        )
        loop = asyncio.get_running_loop()
        if filtros.filtro_cliente_id:
            dataset = await reportes_service.generar_dataset_por_cliente(
                conn, filtros, formato="excel", solicitante_email=solicitante,
            )
            cliente_nombre = dataset.get("cliente_nombre")
            content = await loop.run_in_executor(
                None, construir_bytes_por_cliente, dataset["detalle"], cliente_nombre
            )
            nombre_archivo = generar_nombre_archivo(cliente_nombre)
        else:
            dataset = await reportes_service.generar_dataset_general(
                conn, filtros, formato="excel", solicitante_email=solicitante,
            )
            content = await loop.run_in_executor(
                None, construir_bytes_general, dataset["resumen"], dataset["detalle"], dataset.get("nota_vista")
            )
            nombre_archivo = generar_nombre_archivo()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except asyncpg.PostgresError as exc:
        logger.error(f"Error BD generando reporte de clientes (excel): {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error de base de datos generando el reporte.") from exc

    return excel_bytes_response(content, nombre_archivo)


@router.get("/reportes/clientes.pdf", include_in_schema=False)
async def reporte_clientes_pdf(
    filtro_tipo_id: Optional[int] = None,
    filtro_tecnologia_id: Optional[int] = None,
    filtro_estatus_id: Optional[int] = None,
    filtro_fecha_inicio: Optional[str] = None,
    filtro_fecha_fin: Optional[str] = None,
    filtro_cliente_id: Optional[str] = None,
    solo_activos: bool = False,
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context),
    pdf_service: PDFService = Depends(get_pdf_service),
    _ = require_module_access("comercial"),
    _role = _require_reporte_clientes_role,
):
    """Descarga el reporte de clientes/empresas en PDF (modo general o enfocado por cliente)."""
    try:
        filtros, solicitante = _preparar_reporte_clientes(
            context,
            filtro_tipo_id=filtro_tipo_id,
            filtro_tecnologia_id=filtro_tecnologia_id,
            filtro_estatus_id=filtro_estatus_id,
            filtro_fecha_inicio=filtro_fecha_inicio,
            filtro_fecha_fin=filtro_fecha_fin,
            filtro_cliente_id=filtro_cliente_id,
            solo_activos=solo_activos,
        )
        filtros_resumen = await reportes_service.describir_filtros(conn, filtros)
        fecha_generacion = format_datetime(now_mx())

        cliente_nombre = None
        if filtros.filtro_cliente_id:
            dataset = await reportes_service.generar_dataset_por_cliente(
                conn, filtros, formato="pdf", solicitante_email=solicitante,
            )
            cliente_nombre = dataset.get("cliente_nombre")
            detalle_pdf = [
                {**row, "fecha_solicitud_display": _formato_fecha_pdf(row.get("fecha_solicitud"))}
                for row in dataset["detalle"]
            ]
            pdf_context = {
                "modo": "cliente",
                "detalle": detalle_pdf,
                "filtros_resumen": filtros_resumen,
                "fecha_generacion": fecha_generacion,
            }
        else:
            dataset = await reportes_service.generar_dataset_general(
                conn, filtros, formato="pdf", solicitante_email=solicitante,
            )
            pdf_context = {
                "modo": "general",
                "resumen": dataset["resumen"],
                "filtros_resumen": filtros_resumen,
                "fecha_generacion": fecha_generacion,
            }

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except asyncpg.PostgresError as exc:
        logger.error(f"Error BD generando reporte de clientes (pdf): {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error de base de datos generando el reporte.") from exc

    try:
        pdf_bytes = await pdf_service.generate("comercial/reporte_clientes.html", pdf_context)
    except (OSError, RuntimeError, ValueError, jinja2.TemplateError) as exc:
        logger.error(f"Error generando PDF de reporte de clientes: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error generando el PDF.") from exc

    filename = pdf_service.generate_filename("reporte_clientes", suffix=cliente_nombre or "")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
