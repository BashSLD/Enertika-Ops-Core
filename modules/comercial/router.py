from fastapi import APIRouter, Request, Depends, HTTPException, Form, UploadFile, File, status, Response
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from uuid import UUID, uuid4
from typing import Optional, List
import io
import logging
import pandas as pd

# --- Imports de Core ---
from core.database import get_db_connection
from core.microsoft import get_ms_auth
from core.security import get_current_user_context, get_valid_graph_token
from core.permissions import require_module_access
from .schemas import OportunidadCreateCompleta, DetalleBessCreate
from .service import ComercialService, get_comercial_service
from .email_handler import EmailHandler, get_email_handler

# Import Workflow Service (Centralizado)
from core.workflow.service import get_workflow_service

# Configuración básica de logging
logger = logging.getLogger("ComercialModule")

templates = Jinja2Templates(directory="templates")

# Registrar filtros de timezone (México)
from core.jinja_filters import register_timezone_filters
register_timezone_filters(templates.env)

router = APIRouter(
    prefix="/comercial",
    tags=["Módulo Comercial"],
)


# ----------------------------------------
# ENDPOINTS
# ----------------------------------------

@router.head("/ui", include_in_schema=False)
async def check_comercial_ui(
    request: Request,
    context = Depends(get_current_user_context),
    _ = require_module_access("comercial")  # VALIDACIÓN DE ACCESO
):
    """Heartbeat endpoint to check session status without rendering."""
    return HTMLResponse("", status_code=200)

@router.get("/ui", include_in_schema=False)
async def get_comercial_ui(
    request: Request,
    context = Depends(get_current_user_context),  # Usar dependencia completa
    _ = require_module_access("comercial")  # VALIDACIÓN DE ACCESO
):
    """Main Entry: Shows the Tabbed Dashboard (Graphs + Records)."""
    user_name = context.get("user_name", "Usuario")
    role = context.get("role", "USER")
    
    # Detección inteligente de contexto:
    # 1. Si es HTMX (Navegación parcial desde Sidebar), devolvemos solo contenido interno (tabs.html)
    # 2. Si es Carga Completa (F5 o URL directa), devolvemos el wrapper completo (dashboard.html)
    if request.headers.get("hx-request"):
        template = "comercial/tabs.html"
    else:
        template = "comercial/dashboard.html"
        
    return templates.TemplateResponse(template, {
        "request": request,
        "user_name": user_name,
        "role": role,  # Pasar rol de sistema para el sidebar
        "module_roles": context.get("module_roles", {}),  # IMPORTANTE para el sidebar
        "current_module_role": context.get("module_roles", {}).get("comercial", "viewer")  # Rol específico en este módulo
    }, headers={"HX-Title": "Enertika Ops Core | Comercial"})

@router.get("/form", include_in_schema=False)
async def get_comercial_form(
    request: Request,
    user_context = Depends(get_current_user_context),
    conn = Depends(get_db_connection),
    service: ComercialService = Depends(get_comercial_service),
    _ = require_module_access("comercial", "editor")  # REQUIERE ROL EDITOR O SUPERIOR
):
    """Shows the creation form (Partial or Full Page)."""
    
    # Validación Estricta: Si no hay email, cortamos aquí.
    if not user_context.get("email"):
        # Retornamos 401 SIN redirección automática. HTMX lo atrapará.
        return HTMLResponse(status_code=401)
    
    # PREVENCIÓN CRÍTICA: Validar token ANTES de mostrar formulario
    # Esto evita que el usuario pierda su trabajo si el token expira mientras lo llena.
    # Si el token está cerca de expirar, get_valid_graph_token lo renovará automáticamente.
    token = await get_valid_graph_token(request)
    if not token:
        # Token expirado y no se pudo renovar - redirigir al login AHORA
        # Mejor que el usuario lo sepa de inmediato en lugar de perder 10 minutos de trabajo
        from fastapi import Response
        return Response(status_code=200, headers={"HX-Redirect": "/auth/login?expired=1"})
    
    # Generar canal default desde el servicio
    canal_default = ComercialService.get_canal_from_user_name(
        user_context.get("user_name")
    )
    # Esto permite que ACTUALIZACIÓN esté disponible en el template
    if request.query_params.get('legacy_term'):
        catalogos = await service.get_catalogos_ui(conn)  # TODOS los tipos
        
        # Buscar ACTUALIZACIÓN directamente en BD por codigo_interno (más confiable que regex)
        tipo_act = await conn.fetchrow(
            "SELECT id, nombre FROM tb_cat_tipos_solicitud WHERE codigo_interno = 'ACTUALIZACION' AND activo = true"
        )
        catalogos['tipo_actualizacion_id'] = tipo_act['id'] if tipo_act else None
    else:
        catalogos = await service.get_catalogos_creacion(conn)  # Filtrado (PRE_OFERTA, LICITACION)

    return templates.TemplateResponse("comercial/form.html", {
        "request": request, 
        "canal_default": canal_default,
        "catalogos": catalogos,  # Catálogos filtrados
        "user_name": user_context.get("user_name"),
        "role": user_context.get("role"),
        "module_roles": user_context.get("module_roles", {})
    }, headers={"HX-Title": "Enertika Ops Core | Nuevo Comercial"})

@router.get("/partials/graphs", include_in_schema=False)
async def get_graphs_partial(
    request: Request,
    service: ComercialService = Depends(get_comercial_service),
    conn = Depends(get_db_connection),
    user_context: dict = Depends(get_current_user_context),
    _ = require_module_access("comercial")
):
    """Partial: Graphs Tab Content."""
    stats = await service.get_dashboard_stats(conn, user_context)
    return templates.TemplateResponse("comercial/partials/graphs.html", {"request": request, "stats": stats})

@router.get("/partials/cards", include_in_schema=False)
async def get_cards_partial(
    request: Request,
    tab: str = "activos",
    q: Optional[str] = None,
    limit: int = 15,
    subtab: Optional[str] = None,
    service: ComercialService = Depends(get_comercial_service),
    conn = Depends(get_db_connection),
    user_context: dict = Depends(get_current_user_context),
    _ = require_module_access("comercial")
):
    """Partial: List of Opportunities (Cards/Grid)."""
    
    # OPTIMIZACIÓN: Token se obtiene solo cuando el usuario hace click en "Enviar Correo"
    # Esto evita una llamada HTTP a Microsoft Graph en cada cambio de pestaña
    # El token se validará en tiempo real cuando se necesite (lazy loading)
    # Validamos existencia de token en BD sin exponer el string sensible
    has_valid_token = await conn.fetchval(
        """SELECT CASE WHEN access_token IS NOT NULL THEN true ELSE false END 
           FROM tb_usuarios WHERE id_usuario = $1""",
        user_context['user_db_id']
    )
    
    items = await service.get_oportunidades_list(conn, user_context=user_context, tab=tab, q=q, limit=limit, subtab=subtab)
    
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
    conn = Depends(get_db_connection)
):
    """Retorna la sub-tabla de sitios para una oportunidad."""
    rows = await service.get_sitios_simple(conn, id_oportunidad)
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
    _ = require_module_access("comercial")
):
    """Retorna los detalles BESS para una oportunidad."""
    bess = await service.get_detalles_bess(conn, id_oportunidad)
    return templates.TemplateResponse(
        "comercial/partials/detalles/bess_info.html",
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
    legacy_search_term: Optional[str] = Form(None),  # NUEVO: Capturar término legacy
    archivos_extra: List[UploadFile] = File(default=[]),
    service: ComercialService = Depends(get_comercial_service),
    ms_auth = Depends(get_ms_auth),
    conn = Depends(get_db_connection),
    email_handler = Depends(get_email_handler)  # NUEVO: Inyectar EmailHandler
):
    """Envía el correo de notificación usando el token de la sesión."""
    
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
        user_email=context['user_email']
    )
    
    return result

@router.get("/plantilla", response_class=StreamingResponse)
async def descargar_plantilla_sitios():
    """Genera y descarga la plantilla Excel oficial."""
    # Columnas actualizadas según requerimiento
    cols = ["#", "NOMBRE", "# DE SERVICIO", "TARIFA", "LINK GOOGLE", "DIRECCION", "COMENTARIOS"]
    df = pd.DataFrame(columns=cols)
    
    # Fila de ejemplo actualizada
    df.loc[0] = [1, "SUCURSAL NORTE", "123456789012", "GDMTO", "https://maps.google.com/?q=19.4326,-99.1332", "Av. Reforma 123, Col. Centro", "Ejemplo de comentario"]
    
    # Guardar en buffer de memoria
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Sitios')
    buffer.seek(0)
    
    headers = {"Content-Disposition": 'attachment; filename="plantilla_sitios_enertika.xlsx"'}
    return StreamingResponse(buffer, headers=headers, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@router.post("/validate-thread-check")
async def validate_thread_check(
    request: Request,
    search_term: str = Form(...),
    ms_auth = Depends(get_ms_auth)
):
    """Valida si existe un hilo de correo antes de permitir avanzar al usuario (Modo Homologación)."""
    token = await get_valid_graph_token(request)
    if not token:
        return JSONResponse({"found": False, "error": "Sesión expirada"}, status_code=401)

    thread_id = ms_auth.find_thread_id(token, search_term)
    
    if thread_id:
        # Retorna éxito y el término para que el frontend lo pase al formulario
        return JSONResponse({"found": True, "clean_term": search_term})
    else:
        return JSONResponse({"found": False, "message": "No se encontró ningún hilo con ese texto."}, status_code=404)

@router.post("/form")
async def handle_oportunidad_creation(
    request: Request,
    # --- Campos Estándar ---
    nombre_proyecto: str = Form(...),
    nombre_cliente: str = Form(...),
    canal_venta: str = Form(...),
    id_tecnologia: int = Form(...),
    id_tipo_solicitud: int = Form(...),
    cantidad_sitios: int = Form(...),
    prioridad: str = Form(...),
    direccion_obra: str = Form(...),
    coordenadas_gps: Optional[str] = Form(None),
    google_maps_link: Optional[str] = Form(None),
    sharepoint_folder_url: Optional[str] = Form(None),
    
    # --- Campo Fecha Manual (Gerentes) ---
    fecha_manual: Optional[str] = Form(None),
    
    # --- Campos BESS (HTMX Conditional) ---
    bess_cargas_criticas: Optional[float] = Form(None),
    bess_tiene_motores: bool = Form(False),
    bess_potencia_motor: Optional[float] = Form(None),
    bess_autonomia: Optional[str] = Form(None),
    bess_voltaje: Optional[str] = Form(None),
    bess_planta_emergencia: bool = Form(False),
    bess_cargas_separadas: Optional[bool] = Form(False), # NUEVO CAMPO
    bess_objetivos: List[str] = Form([]),  # Recibe lista de checkboxes

    # --- Campo Legacy (Homologación) ---
    legacy_search_term: Optional[str] = Form(None),  # Asunto del correo antiguo (solo viaja, no se guarda)

    # --- Dependencias ---
    conn = Depends(get_db_connection),
    service: ComercialService = Depends(get_comercial_service),
    context = Depends(get_current_user_context)
):
    try:
        # 1. Seguridad Token
        token = await get_valid_graph_token(request)
        if not token: 
            from fastapi import Response
            return Response(status_code=200, headers={"HX-Redirect": "/auth/login?expired=1"})

        # 2. Construir Objeto BESS (Pydantic v2)
        # Solo si se enviaron datos relevantes o la tecnología implica BESS
        datos_bess = None
        if bess_cargas_criticas or bess_tiene_motores or bess_objetivos:
            # Importar schema BESS
            from .schemas import DetalleBessCreate
            datos_bess = DetalleBessCreate(
                cargas_criticas_kw=bess_cargas_criticas,
                tiene_motores=bess_tiene_motores,
                potencia_motor_hp=bess_potencia_motor,
                tiempo_autonomia=bess_autonomia,
                voltaje_operacion=bess_voltaje,
                cargas_separadas=bess_cargas_separadas,
                objetivos_json=bess_objetivos,
                tiene_planta_emergencia=bess_planta_emergencia
            )

        # 3. Validar Permiso Fecha Manual
        role = context.get("role")
        fecha_final_str = None
        if role in ['ADMIN', 'MANAGER']:
            fecha_final_str = fecha_manual
        
        # 3.5 MODO HOMOLOGACIÓN: Forzar tipo ACTUALIZACIÓN
        # Si viene legacy_search_term, sobrescribir id_tipo_solicitud
        if legacy_search_term:
            id_tipo_actualizacion = await conn.fetchval(
                "SELECT id FROM tb_cat_tipos_solicitud WHERE UPPER(codigo_interno) = 'ACTUALIZACION'"
            )
            if id_tipo_actualizacion:
                id_tipo_solicitud = id_tipo_actualizacion
                logger.info(f"MODO HOMOLOGACIÓN: Tipo de solicitud forzado a ACTUALIZACIÓN")
            else:
                logger.warning("No se encontró tipo ACTUALIZACIÓN en catálogo, usando el seleccionado por usuario")

        # 4. Construir Objeto Principal (Pydantic v2)
        from .schemas import OportunidadCreateCompleta
        oportunidad_data = OportunidadCreateCompleta(
            nombre_proyecto=nombre_proyecto,
            cliente_nombre=nombre_cliente,
            canal_venta=canal_venta,
            id_tecnologia=id_tecnologia,
            id_tipo_solicitud=id_tipo_solicitud,
            cantidad_sitios=cantidad_sitios,
            prioridad=prioridad,
            direccion_obra=direccion_obra,
            coordenadas_gps=coordenadas_gps,
            google_maps_link=google_maps_link,
            sharepoint_folder_url=sharepoint_folder_url,
            fecha_manual_str=fecha_final_str,
            detalles_bess=datos_bess
        )

        # 5. Ejecutar Transacción en Servicio
        new_id, op_id_estandar, es_fuera_horario = await service.crear_oportunidad_transaccional(
            conn, oportunidad_data, context
        )

        # 6. Redirección (Lógica Multisitos vs Unisitio)
        if cantidad_sitios == 1:
            # Auto-creación de sitio único (Legacy logic mantenida por consistencia)
            await service.auto_crear_sitio_unico(
                conn, new_id, nombre_proyecto, direccion_obra, google_maps_link
            )
            target_url = f"/comercial/paso3/{new_id}"
        else:
            target_url = f"/comercial/paso2/{new_id}"
        
        # Construir parámetros de URL
        params = f"?new_op={op_id_estandar}&fh={str(es_fuera_horario).lower()}"
        
        # PUENTE: Si existe legacy_search_term, agregarlo a la URL para que viaje hasta el Paso 3
        if legacy_search_term:
            import urllib.parse
            safe_legacy = urllib.parse.quote(legacy_search_term)
            params += f"&legacy_term={safe_legacy}"
        
        from fastapi import Response
        return Response(status_code=200, headers={"HX-Redirect": f"{target_url}{params}"})

    except Exception as e:
        logger.error(f"Error en creación de oportunidad: {e}")
        # En producción, mejorar el manejo de error para no exponer detalles técnicos
        return templates.TemplateResponse(
            "comercial/error_message.html", 
            {"request": request, "detail": str(e)},
            status_code=500
        )

# ===== FORMULARIO EXTRAORDINARIO (ADMIN/MANAGER ONLY) =====
@router.get("/form-extraordinario", include_in_schema=False)
async def get_comercial_form_extraordinario(
    request: Request,
    user_context = Depends(get_current_user_context),
    conn = Depends(get_db_connection),
    service: ComercialService = Depends(get_comercial_service)
):
    """Shows the extraordinary creation form (ADMIN/MANAGER ONLY)."""
    
    # Validación de Rol: SOLO ADMIN o MANAGER
    role = user_context.get("role")
    if role not in ['ADMIN', 'MANAGER']:
        from fastapi import Response
        return Response(status_code=403, content="Acceso denegado. Solo ADMIN y MANAGER pueden acceder.")
    
    # Validación de sesión
    if not user_context.get("email"):
        return HTMLResponse(status_code=401)
    
    # Validar token
    token = await get_valid_graph_token(request)
    if not token:
        from fastapi import Response
        return Response(status_code=200, headers={"HX-Redirect": "/auth/login?expired=1"})
    
    # Generar canal default
    canal_default = ComercialService.get_canal_from_user_name(user_context.get("user_name"))
    
    # Obtener catálogos
    catalogos = await service.get_catalogos_creacion(conn)

    return templates.TemplateResponse("comercial/form_extraordinario.html", {
        "request": request, 
        "canal_default": canal_default,
        "catalogos": catalogos,
        "user_name": user_context.get("user_name"),
        "role": user_context.get("role"),
        "module_roles": user_context.get("module_roles", {})
    }, headers={"HX-Title": "Enertika Ops Core | Solicitud Extraordinaria"})

@router.post("/form-extraordinario")
async def handle_oportunidad_extraordinaria(
    request: Request,
    # --- Campos Estándar ---
    nombre_proyecto: str = Form(...),
    nombre_cliente: str = Form(...),
    canal_venta: str = Form(...),
    id_tecnologia: int = Form(...),
    id_tipo_solicitud: int = Form(...),
    cantidad_sitios: int = Form(...),
    prioridad: str = Form(...),
    direccion_obra: str = Form(...),
    coordenadas_gps: Optional[str] = Form(None),
    google_maps_link: Optional[str] = Form(None),
    sharepoint_folder_url: Optional[str] = Form(None),
    
    # --- Campo Fecha Manual (OBLIGATORIO en extraordinarias) ---
    fecha_manual: str = Form(...),
    
    # --- Campos BESS (Opcionales) ---
    bess_cargas_criticas: Optional[float] = Form(None),
    bess_tiene_motores: bool = Form(False),
    bess_potencia_motor: Optional[float] = Form(None),
    bess_autonomia: Optional[str] = Form(None),
    bess_voltaje: Optional[str] = Form(None),
    bess_planta_emergencia: bool = Form(False),
    bess_cargas_separadas: Optional[bool] = Form(False),
    bess_objetivos: List[str] = Form([]),

    # --- Dependencias ---
    conn = Depends(get_db_connection),
    service: ComercialService = Depends(get_comercial_service),
    context = Depends(get_current_user_context),
    ms_auth = Depends(get_ms_auth)  # INYECCIÓN NUEVA
):
    """Procesa solicitud extraordinaria y envía notificación automática."""
    try:
        # 1. Seguridad: Validar rol ADMIN/MANAGER
        role = context.get("role")
        if role not in ['ADMIN', 'MANAGER']:
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Solo ADMIN y MANAGER pueden crear solicitudes extraordinarias")
        
        # Validar token
        token = await get_valid_graph_token(request)
        if not token: 
            from fastapi import Response
            return Response(status_code=200, headers={"HX-Redirect": "/auth/login?expired=1"})

        # 2. Construir Objeto BESS (si aplica)
        datos_bess = None
        if bess_cargas_criticas or bess_tiene_motores or bess_objetivos:
            from .schemas import DetalleBessCreate
            datos_bess = DetalleBessCreate(
                cargas_criticas_kw=bess_cargas_criticas,
                tiene_motores=bess_tiene_motores,
                potencia_motor_hp=bess_potencia_motor,
                tiempo_autonomia=bess_autonomia,
                voltaje_operacion=bess_voltaje,
                cargas_separadas=bess_cargas_separadas,
                objetivos_json=bess_objetivos,
                tiene_planta_emergencia=bess_planta_emergencia
            )

        # 3. Construir Objeto Principal
        from .schemas import OportunidadCreateCompleta
        oportunidad_data = OportunidadCreateCompleta(
            nombre_proyecto=nombre_proyecto,
            cliente_nombre=nombre_cliente,
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
            detalles_bess=datos_bess
        )

        # 4. Ejecutar Transacción en Servicio
        new_id, op_id_estandar, es_fuera_horario = await service.crear_oportunidad_transaccional(
            conn, oportunidad_data, context
        )
        
        # 5. MARCAR COMO EXTRAORDINARIA: email_enviado = TRUE
        await service.marcar_extraordinaria_enviada(conn, new_id)
        
        # --- NUEVO: ENVÍO DE NOTIFICACIÓN AUTOMÁTICA ---
        # Recuperamos la URL base para el link del correo
        base_url = str(request.base_url).rstrip('/')
        
        # Enviar notificación (usando el token del usuario en sesión)
        await service.enviar_notificacion_extraordinaria(
            conn=conn,
            ms_auth=ms_auth,
            token=token,
            id_oportunidad=new_id,
            base_url=base_url
        )
        # -----------------------------------------------
        
        logger.info(f"Solicitud extraordinaria {op_id_estandar} creada y notificada.")

        # 6. Redirección (Lógica Multisitos vs Unisitio)
        if cantidad_sitios == 1:
            await service.auto_crear_sitio_unico(
                conn, new_id, nombre_proyecto, direccion_obra, google_maps_link
            )
            target_url = "/comercial/ui"
            params = f"?new_op={op_id_estandar}&fh={str(es_fuera_horario).lower()}&extraordinaria=1"
        else:
            target_url = f"/comercial/paso2/{new_id}"
            params = f"?new_op={op_id_estandar}&fh={str(es_fuera_horario).lower()}&extraordinaria=1"
        
        from fastapi import Response
        return Response(status_code=200, headers={"HX-Redirect": f"{target_url}{params}"})

    except Exception as e:
        logger.error(f"Error en creación de solicitud extraordinaria: {e}")
        return templates.TemplateResponse(
            "comercial/error_message.html", 
            {"request": request, "detail": str(e)},
            status_code=500
        )

# (El endpoint de Excel se mantiene igual, asegúrate de que esté incluido en tu archivo)
@router.delete("/{id_oportunidad}", response_class=HTMLResponse)
async def cancelar_oportunidad(
    request: Request,
    id_oportunidad: UUID,
    service: ComercialService = Depends(get_comercial_service),
    conn = Depends(get_db_connection)
):
    """Elimina borrador y fuerza una recarga completa al Dashboard."""
    
    # 1. Protección de Sesión con Token Inteligente
    access_token = await get_valid_graph_token(request)
    if not access_token:
        # Token expirado y no se pudo renovar
        from fastapi import Response
        return Response(status_code=200, headers={"HX-Redirect": "/auth/login?expired=1"})
        
    # 2. Borrar datos en BD via Service
    await service.cancelar_oportunidad(conn, id_oportunidad)
    
    # 3. CAMBIO CLAVE: Usamos HX-Redirect en lugar de HX-Location
    # HX-Redirect obliga al navegador a cambiar de URL (como un F5 + ir a nueva página)
    # Esto limpia la memoria y carga los estilos/scripts correctamente.
    from fastapi import Response
    return Response(status_code=200, headers={"HX-Redirect": "/comercial/ui"}) 


# ----------------------------------------
# NEW ENDPOINTS FOR STEP 3 & DEBUG
# ----------------------------------------

@router.get("/paso3/{id_oportunidad}", include_in_schema=False)
async def get_paso3_email_form(
    request: Request,
    id_oportunidad: UUID,
    legacy_term: Optional[str] = None,
    conn = Depends(get_db_connection),
    service: ComercialService = Depends(get_comercial_service)
):
    """Formulario final de envío de correo."""
    if not await get_valid_graph_token(request):
        return Response(status_code=200, headers={"HX-Redirect": "/auth/login?expired=1"})
    
    # Delegar TODA la lógica de preparación de datos y reglas al Service
    data = await service.get_data_for_email_form(conn, id_oportunidad)
    if not data: return HTMLResponse("Oportunidad no encontrada", 404)
    
    template = "comercial/email_form.html" if request.headers.get("hx-request") else "comercial/email_full.html"
    
    return templates.TemplateResponse(template, {
        "request": request,
        **data, # Desempaquetar dict del servicio
        "legacy_term": legacy_term,
        "user_name": request.session.get("user_name"),
        "role": request.session.get("role")
    })

# ----------------------------------------
# NUEVOS ENDPOINTS PARA EXCEL PREVIEW
# ----------------------------------------

@router.post("/upload-preview", response_class=HTMLResponse)
async def upload_preview_endpoint(
    request: Request,
    id_oportunidad: str = Form(...),
    file: UploadFile = File(...),
    extraordinaria: int = Form(0),
    service: ComercialService = Depends(get_comercial_service),
    conn = Depends(get_db_connection)
):
    """Procesa previsualización de Excel (Lógica movida al Service)."""
    try:
        # Validaciones básicas HTTP
        if file.size > 10 * 1024 * 1024:
             return templates.TemplateResponse("comercial/partials/toasts/toast_error.html", {"request": request, "title": "Error", "message": "Archivo > 10MB"})
        
        contents = await file.read()
        uuid_op = UUID(id_oportunidad)
        
        # Delegar Lógica Compleja al Service
        result = await service.preview_site_upload(conn, contents, uuid_op)
        
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
        logger.error(f"Error upload: {e}")
        return templates.TemplateResponse("comercial/partials/toasts/toast_error.html", {"request": request, "title": "Error técnico", "message": str(e)})


@router.post("/upload-confirm", response_class=HTMLResponse)
async def upload_confirm_endpoint(
    request: Request,
    sitios_json: str = Form(...),
    op_id: str = Form(...),
    extraordinaria: int = Form(0),
    service: ComercialService = Depends(get_comercial_service),
    conn = Depends(get_db_connection)
):
    try:
        uuid_op = UUID(op_id)
        count = await service.confirm_site_upload(conn, uuid_op, sitios_json)
        
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
async def get_paso_2_form(request: Request, id_oportunidad: UUID, extraordinaria: int = 0, conn = Depends(get_db_connection)):
    """Re-renderiza el formulario de carga multisitio (Paso 2)."""
    row = await conn.fetchrow(
        "SELECT id_interno_simulacion, titulo_proyecto, cliente_nombre, cantidad_sitios FROM tb_oportunidades WHERE id_oportunidad = $1", 
        id_oportunidad
    )
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
    tipo_solicitud: str = Form(...), # "COTIZACION", "ACTUALIZACION"
    prioridad: str = Form(...),
    service: ComercialService = Depends(get_comercial_service),
    conn = Depends(get_db_connection),
    # CORRECCIÓN DE SEGURIDAD: Validar permisos explícitamente
    _ = require_module_access("comercial", "editor"),
    user_context = Depends(get_current_user_context)
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
    conn = Depends(get_db_connection)
):
    if not await get_valid_graph_token(request):
        return Response(status_code=200, headers={"HX-Redirect": "/auth/login?expired=1"})
    await service.delete_sitio(conn, id_sitio)
    return HTMLResponse("", status_code=200)
    