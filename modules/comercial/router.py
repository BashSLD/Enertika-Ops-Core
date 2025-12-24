
from fastapi import APIRouter, Request, Depends, HTTPException, Form, UploadFile, File
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from uuid import UUID, uuid4
from typing import Optional, List
import pandas as pd
import io
import json
import logging
from datetime import datetime, timedelta, time as dt_time # Keep timedelta and dt_time as they are used later

# --- Imports de Core ---
from core.database import get_db_connection
from core.microsoft import get_ms_auth, MicrosoftAuth # Keep MicrosoftAuth as it's used in get_ms_auth
from core.config import settings
from core.security import get_current_user_context
from .schemas import OportunidadCreate, SitioImportacion

# Configuración básica de logging
logger = logging.getLogger("ComercialModule")

templates = Jinja2Templates(directory="templates")

router = APIRouter(
    prefix="/comercial",
    tags=["Módulo Comercial"],
)

# ----------------------------------------
# CAPA DE SERVICIO (LÓGICA DE NEGOCIO)
# ----------------------------------------
class ComercialService:
    """Implementa la lógica de negocio del módulo Comercial (Legacy Port)."""

    @staticmethod
    def calcular_deadline() -> datetime:
        ahora = datetime.now()
        fecha_base = ahora.date()
        hora_actual = ahora.time()
        corte = dt_time(17, 30, 0)
        
        if hora_actual > corte: 
            fecha_base += timedelta(days=1)
            
        dia_semana = fecha_base.weekday()
        if dia_semana == 5: fecha_base += timedelta(days=2) 
        elif dia_semana == 6: fecha_base += timedelta(days=1) 
        
        return fecha_base + timedelta(days=7)

    async def get_or_create_cliente(self, conn, nombre_cliente: str) -> UUID:
        nombre_clean = nombre_cliente.strip().upper()
        
        # Intentamos buscar
        row = await conn.fetchrow("SELECT id FROM tb_clientes WHERE nombre_fiscal = $1", nombre_clean)
        if row:
            return row['id']
            
        # Intentamos crear
        try:
            val = await conn.fetchval(
                "INSERT INTO tb_clientes (nombre_fiscal) VALUES ($1) RETURNING id",
                nombre_clean
            )
            return val
        except Exception:
             # Fallback: Generamos UUID nosotros si la DB no tiene default
             new_id = uuid4()
             await conn.execute(
                 "INSERT INTO tb_clientes (id, nombre_fiscal) VALUES ($1, $2)",
                 new_id, nombre_clean
             )
             return new_id

    async def create_oportunidad(self, datos_form: dict, conn, user_id: UUID, user_name: str) -> UUID:
        """Crea una nueva oportunidad en la BBDD y retorna su ID."""
        try:
            # 1. Preparar datos auxiliares
            cliente_id = await self.get_or_create_cliente(conn, datos_form['nombre_cliente'])
            timestamp_id = datetime.now().strftime('%y%m%d%H%M')
            
            # Generamos códigos Legacy
            titulo_proyecto = f"{datos_form['tipo_solicitud']}_{datos_form['nombre_cliente']}_{datos_form['nombre_proyecto']}_{datos_form['tipo_tecnologia']}_{datos_form['canal_venta']}".upper()
            id_interno_simulacion = f"OP - {timestamp_id}_{datos_form['nombre_proyecto']}_{datos_form['nombre_cliente']}".upper()[:50]
            op_id_estandar = f"OP-{timestamp_id}" # Requerido por tu esquema NOT NULL
            
            deadline = self.calcular_deadline()
            status_global = "Pendiente"
            
            query = """
                INSERT INTO tb_oportunidades (
                    -- Campos Legacy Nuevos
                    titulo_proyecto, nombre_proyecto, canal_venta, solicitado_por,
                    tipo_tecnologia, tipo_solicitud, cantidad_sitios, prioridad,
                    direccion_obra, coordenadas_gps, google_maps_link, sharepoint_folder_url,
                    deadline_calculado, id_interno_simulacion,
                    fecha_solicitud, email_enviado, 
                    
                    -- Campos Originales
                    id_oportunidad,
                    creado_por_id,
                    op_id_estandar,
                    cliente_nombre,
                    status_global, 
                    cliente_id
                ) 
                VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, NOW(), FALSE,
                    $15, $16, $17, $18, $19, $20
                )
                RETURNING id_oportunidad
            """
            
            # Generamos UUID para el insert manual
            new_uuid = uuid4()

            oportunidad_id = await conn.fetchval(
                query,
                titulo_proyecto,                  # 1
                datos_form['nombre_proyecto'],    # 2
                datos_form['canal_venta'],        # 3
                user_name,                        # 4 (AHORA ES EL NOMBRE REAL)
                datos_form['tipo_tecnologia'],    # 5
                datos_form['tipo_solicitud'],     # 6
                int(datos_form['cantidad_sitios']),# 7
                datos_form['prioridad'],          # 8
                datos_form['direccion_obra'],     # 9
                datos_form['coordenadas_gps'],    # 10
                datos_form['google_maps_link'],   # 11
                datos_form['sharepoint_folder_url'], # 12
                deadline,                         # 13
                id_interno_simulacion,            # 14
                
                new_uuid,                         # 15 (id_oportunidad)
                user_id,                          # 16 (creado_por_id REAL)
                op_id_estandar,                   # 17 (op_id_estandar)
                datos_form['nombre_cliente'],     # 18 (cliente_nombre)
                status_global,                    # 19 (status_global)
                cliente_id                        # 20 (cliente_id FK)
            )
            
            return oportunidad_id
            
        except Exception as e:
            logger.exception(f"Error creando oportunidad (Code 500): {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error BD: {e}"
            )

    async def get_oportunidades_list(self, conn, user_context: dict, tab: str = "activos", q: str = None, page: int = 1, subtab: str = None) -> List[dict]:
        """Recupera la lista filtrada de oportunidades, aplicando lógica de permisos y paginación."""
        
        user_id = user_context.get("user_id")
        role = user_context.get("role", "USER") 
        user_email = user_context.get("email")

        # 1. Base Query
        query = """
            SELECT 
                o.id_oportunidad, o.titulo_proyecto, o.nombre_proyecto, o.cliente_nombre,
                o.fecha_solicitud, o.status_global, o.email_enviado, o.id_interno_simulacion,
                o.tipo_solicitud, o.deadline_calculado, o.cantidad_sitios,
                -- Alias clave para el frontend (JOINs):
                u_sim.nombre as responsable_simulacion, 
                u_sim.email as responsable_email,  
                u_crea.nombre as solicitado_por    
            FROM tb_oportunidades o
            LEFT JOIN tb_usuarios u_sim ON o.responsable_simulacion_id = u_sim.id_usuario
            LEFT JOIN tb_usuarios u_crea ON o.creado_por_id = u_crea.id_usuario
            WHERE 1=1
        """
        params = []
        param_idx = 1

        # 2. Filtro Tab (Lógica de Negocio)
        if tab == "historial":
            query += f" AND o.status_global IN ('Entregado', 'Cancelado', 'Perdida', 'Ganada')"
        elif tab == "levantamientos":
            query += f" AND o.tipo_solicitud = 'SOLICITUD DE LEVANTAMIENTO'"
            # Sub-tab Logic
            if subtab == 'realizados':
                query += f" AND o.status_global = 'Realizado'" # O el status que signifique terminado en Lev.
            else: # solicitados (default)
                query += f" AND o.status_global != 'Realizado'"
        else: # activos
             query += f" AND o.status_global NOT IN ('Entregado', 'Cancelado', 'Perdida', 'Ganada')"
             query += f" AND o.tipo_solicitud != 'SOLICITUD DE LEVANTAMIENTO'"

        # 3. Filtro Búsqueda
        if q:
            query += f" AND (o.titulo_proyecto ILIKE ${param_idx} OR o.nombre_proyecto ILIKE ${param_idx} OR o.cliente_nombre ILIKE ${param_idx})"
            params.append(f"%{q}%")
            param_idx += 1

        # 4. Filtro de Seguridad
        if role != 'MANAGER' and role != 'ADMIN':
            query += f" AND o.creado_por_id = ${param_idx}"
            params.append(user_id)
            param_idx += 1

        query += " ORDER BY o.fecha_solicitud DESC"
        
        # 5. Paginación (Solo para Historial por ahora)
        if tab == "historial":
            limit = 10
            offset = (page - 1) * limit
            query += f" LIMIT {limit} OFFSET {offset}"
        
        rows = await conn.fetch(query, *params)
        return [dict(row) for row in rows]

    async def update_email_status(self, conn, id_oportunidad: UUID):
        await conn.execute("UPDATE tb_oportunidades SET email_enviado = TRUE WHERE id_oportunidad = $1", id_oportunidad)


# ----------------------------------------
# DEPENDENCIES
# ----------------------------------------
def get_comercial_service():
    return ComercialService()



# ----------------------------------------
# ENDPOINTS
# ----------------------------------------

@router.head("/ui", include_in_schema=False)
async def check_comercial_ui(
    request: Request,
    context = Depends(get_current_user_context)
):
    """Heartbeat endpoint to check session status without rendering."""
    return HTMLResponse("", status_code=200)

@router.get("/ui", include_in_schema=False)
async def get_comercial_ui(
    request: Request,
    context = Depends(get_current_user_context) # Usar dependencia completa
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
        "role": role # Pasar rol para el sidebar
    }, headers={"HX-Title": "Enertika Ops Core | Comercial"})

@router.get("/form", include_in_schema=False)
async def get_comercial_form(
    request: Request,
    user_context = Depends(get_current_user_context)
):
    """Shows the creation form (Partial or Full Page)."""
    
    # 1. Validación Estricta: Si no hay email, cortamos aquí.
    if not user_context.get("email"):
        # Retornamos 401 SIN redirección automática. HTMX lo atrapará.
        return HTMLResponse(status_code=401)
    
    # Lógica: Tomar primera palabra + guion bajo + segunda palabra (si existe)
    user_name = user_context.get("user_name")
    parts = (user_name or "").strip().split()
    if len(parts) >= 2:
        canal_default = f"{parts[0]}_{parts[1]}".upper()
    elif len(parts) == 1:
        canal_default = parts[0].upper()
    else:
        canal_default = "OFICINA_CENTRAL" # Fallback

    return templates.TemplateResponse("comercial/form.html", {
        "request": request, 
        "canal_default": canal_default
    }, headers={"HX-Title": "Enertika Ops Core | Nuevo Comercial"})

@router.get("/partials/graphs", include_in_schema=False)
async def get_graphs_partial(request: Request):
    """Partial: Graphs Tab Content."""
    # Data for charts could be passed here
    return templates.TemplateResponse("comercial/partials/graphs.html", {"request": request})

@router.get("/partials/cards", include_in_schema=False)
async def get_cards_partial(
    request: Request,
    tab: str = "activos",
    q: Optional[str] = None,
    page: int = 1,
    subtab: Optional[str] = None,
    service: ComercialService = Depends(get_comercial_service),
    conn = Depends(get_db_connection),
    user_context: dict = Depends(get_current_user_context)
):
    """Partial: List of Opportunities (Cards/Grid)."""
    
    items = await service.get_oportunidades_list(conn, user_context=user_context, tab=tab, q=q, page=page, subtab=subtab)
    
    return templates.TemplateResponse(
        "comercial/partials/cards.html", 
        {
            "request": request, 
            "oportunidades": items,
            "user_token": request.session.get("access_token"),
            "current_tab": tab,
            "subtab": subtab,
            "q": q,
            "page": page,
            "has_more": len(items) == 10 if tab == 'historial' else False # Simple check logic
        }
    )

@router.get("/partials/sitios/{id_oportunidad}", include_in_schema=False)
async def get_sitios_partial(
    request: Request,
    id_oportunidad: UUID,
    conn = Depends(get_db_connection)
):
    """Retorna la sub-tabla de sitios para una oportunidad."""
    rows = await conn.fetch(
        "SELECT * FROM tb_sitios_oportunidad WHERE id_oportunidad = $1 ORDER BY id_sitio",
        id_oportunidad
    )
    return templates.TemplateResponse(
        "comercial/partials/sitios_list.html",
        {"request": request, "sitios": rows}
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
    body: str = Form(...),
    archivos_extra: List[UploadFile] = File(default=[]),
    service: ComercialService = Depends(get_comercial_service),
    ms_auth = Depends(get_ms_auth),
    conn = Depends(get_db_connection)
):
    """Envía el correo de notificación usando el token de la sesión."""
    access_token = request.session.get("access_token")
    if not access_token:
        return HTMLResponse(
            "<div class='text-red-500'>Error: No has iniciado sesión con Microsoft. <a href='/auth/login' class='underline'>Log In</a></div>",
            status_code=401
        )

    # 1. Recuperar info de la oportunidad
    row = await conn.fetchrow("SELECT * FROM tb_oportunidades WHERE id_oportunidad = $1", id_oportunidad)
    if not row:
        return HTMLResponse("<div class='text-red-500'>Oportunidad no encontrada</div>", status_code=404)
        
    # --- 1.5 RECUPERAR DEFAULTS (Admin Config) ---
    defaults = await conn.fetchrow("SELECT * FROM tb_email_defaults WHERE id = 1")
    def_to = (defaults['default_to'] or "").upper().replace(",", ";").split(";") if defaults else []
    def_cc = (defaults['default_cc'] or "").upper().replace(",", ";").split(";") if defaults else []
    def_cco = (defaults['default_cco'] or "").upper().replace(",", ";").split(";") if defaults else []
    
    # 2. Procesar Destinatarios (TO)
    final_to = set()
    
    # a) Defaults
    for email in def_to:
        if email.strip(): final_to.add(email.strip())

    # b) From Chips (recipients_str)
    if recipients_str:
        # Aseguramos soporte de ; como separador
        raw_list = recipients_str.replace(",", ";").split(";")
        for email in raw_list:
            if email.strip(): final_to.add(email.strip())
            
    # c) From Fixed rules (Legacy Params)
    for email in fixed_to:
        if email.strip(): final_to.add(email.strip())

    # 3. Procesar Copias (CC)
    final_cc = set()
    
    # a) Defaults
    for email in def_cc:
        if email.strip(): final_cc.add(email.strip())
    
    # b) From Fixed rules
    for email in fixed_cc:
        if email.strip(): final_cc.add(email.strip())
        
    # c) From Manual Input (Chips now)
    if extra_cc:
        raw_cc = extra_cc.replace(",", ";").split(";")
        for email in raw_cc:
            if email.strip(): final_cc.add(email.strip())

    # 4. Procesar Ocultos (BCC - Solo Defaults por ahora)
    final_bcc = set()
    for email in def_cco:
        if email.strip(): final_bcc.add(email.strip())

    recipients_list = list(final_to)
    cc_list = list(final_cc)
    bcc_list = list(final_bcc)

    logger.info(f"Enviando correo OP {row['op_id_estandar']} | TO: {recipients_list} | CC: {cc_list} | BCC: {bcc_list}")

    # 4. Procesar Adjuntos
    adjuntos_procesados = []
    
    # --- LOGICA MULTISITIO: Generar Excel Automáticamente ---
    if (row['cantidad_sitios'] or 0) > 1:
        try:
            sites_rows = await conn.fetch("SELECT nombre_sitio, direccion, tipo_tarifa, google_maps_link FROM tb_sitios_oportunidad WHERE id_oportunidad = $1", id_oportunidad)
            if sites_rows:
                df_sites = pd.DataFrame([dict(r) for r in sites_rows])
                df_sites.columns = ["NOMBRE", "DIRECCION", "TARIFA", "LINK MAPS"]
                
                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
                    df_sites.to_excel(writer, index=False, sheet_name='Sitios')
                
                adjuntos_procesados.append({
                    "name": f"Listado_Sitios_{row['op_id_estandar']}.xlsx",
                    "content_bytes": buf.getvalue(),
                    "contentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                })
        except Exception as e:
            logger.error(f"Error generando excel adjunto: {e}")
            
    # 5. Procesar archivos extra del formulario
    for archivo in archivos_extra:
        if archivo.filename: 
            contenido = await archivo.read()
            await archivo.seek(0) 
            adjuntos_procesados.append({
                "name": archivo.filename,
                "content_bytes": contenido, 
                "contentType": archivo.content_type
            })

    # 5. Llamada a MicrosoftAuth (Con manejo de expiración)
    ok, msg = ms_auth.send_email_with_attachments(
        access_token=access_token, 
        subject=subject,
        body=body,
        recipients=recipients_list,
        cc_recipients=cc_list, 
        bcc_recipients=bcc_list, # Soportado ahora
        attachments_files=adjuntos_procesados 
    )
    
    # --- LOGICA DE AUTO-RECARGA / REDIRECCIÓN ---
    if not ok:
        # Detectamos palabras clave de token vencido en el mensaje de error de Graph
        if "expired" in str(msg).lower() or "InvalidAuthenticationToken" in str(msg):
            print(" Sesión expirada. Forzando redirección al login...")
            
            # Limpiamos la sesión del lado del servidor (Opcional pero recomendado)
            request.session.clear()
            
            # TRUCO HTMX: Esta cabecera obliga al navegador a cambiar de página,
            # ignorando que fue una petición AJAX parcial.
            from fastapi import Response
            return Response(
                status_code=200, 
                headers={"HX-Redirect": "/auth/login?expired=1"}
            )

        # Si es otro error (ej. archivo muy pesado, email inválido), mostramos el error normal
        logger.error(f"Fallo envio correo Graph: {msg}")
        return HTMLResponse(f"""
            <div class="bg-red-100 border-l-4 border-red-500 text-red-700 p-4 mb-4">
                <p class="font-bold">Error enviando correo</p>
                <p>{msg}</p>
            </div>
        """, status_code=200)

    # Si todo salió bien
    # Si todo salió bien
    await service.update_email_status(conn, id_oportunidad) 

    # CAMBIO: Usamos window.location.href en lugar de htmx.ajax
    # Esto fuerza al navegador a ir realmente a la URL, corrigiendo la barra lateral y la dirección
    return HTMLResponse(f"""
        <div class="text-center p-8 bg-green-50 rounded-lg border border-green-200 animate-fade-in-down">
            <div class="mb-4">
                <svg class="w-16 h-16 text-green-500 mx-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>
                </svg>
            </div>
            <p class="text-green-800 font-bold text-xl mb-2">✓ Enviado Exitosamente</p>
            <p class="text-green-600 text-sm">Regresando al tablero...</p>
            
            <script>
                // Esperar 1.5 segundos y luego MUDARNOS de página
                setTimeout(function() {{
                    window.location.href = '/comercial/ui'; 
                }}, 1500);
            </script>
        </div>
    """, status_code=200)

@router.get("/plantilla", response_class=StreamingResponse)
async def descargar_plantilla_sitios():
    """Genera y descarga la plantilla Excel oficial."""
    # Columnas actualizadas según requerimiento
    cols = ["#", "NOMBRE", "# DE SERVICIO", "TARIFA", "LINK GOOGLE", "DIRECCION", "COMENTARIOS"]
    df = pd.DataFrame(columns=cols)
    
    # Fila de ejemplo actualizada
    df.loc[0] = [1, "SUCURSAL NORTE", "123456789012", "GDMTO", "http://maps...", "Av. Reforma 123", "ejemplo de coments"]
    
    # Guardar en buffer de memoria
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Sitios')
    buffer.seek(0)
    
    headers = {"Content-Disposition": 'attachment; filename="plantilla_sitios_enertika.xlsx"'}
    return StreamingResponse(buffer, headers=headers, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@router.post("/form")
async def handle_oportunidad_creation(
    request: Request,
    nombre_proyecto: str = Form(...),
    nombre_cliente: str = Form(...),
    canal_venta: str = Form(...),
    tipo_tecnologia: str = Form(...),
    tipo_solicitud: str = Form(...),
    cantidad_sitios: int = Form(...),
    prioridad: str = Form(...),
    direccion_obra: str = Form(...),
    coordenadas_gps: str = Form(None),
    google_maps_link: str = Form(None),
    sharepoint_folder_url: str = Form(None),
    conn = Depends(get_db_connection),
    service: ComercialService = Depends(get_comercial_service),
    ms_auth = Depends(get_ms_auth)
):
    try:
        # 1. Obtener usuario de MS Graph
        token = request.session.get("access_token")
        
        # --- CAMBIO IMPORTANTE ---
        # Antes: Retornaba HTML con HX-Redirect (Esto recargaba la página y borraba datos)
        # Ahora: Solo retornamos status 401. El Javascript de base.html hará el resto.
        if not token:
             return HTMLResponse(status_code=401)
             
        # Inicializamos variables obligatorias (ya no usamos defaults inseguros)
        user_id = None
        nombre = request.session.get("user_name", "Desconocido")
        email = None

        profile = ms_auth.get_user_profile(token)
        if profile:
            email = profile.get("mail") or profile.get("userPrincipalName")
            nombre = profile.get("displayName") or nombre 
            
            # Check / Create user in DB
            row = await conn.fetchrow("SELECT id_usuario FROM tb_usuarios WHERE email = $1", email)
            if row:
                user_id = row['id_usuario']
            else:
                # Crear usuario nuevo
                user_id = uuid4()
                await conn.execute(
                    "INSERT INTO tb_usuarios (id_usuario, nombre, email) VALUES ($1, $2, $3)",
                    user_id, nombre, email
                )
        else:
             # Tenemos token pero Graph falló --> Token Inválido o Expirado
             return HTMLResponse(
                 "<div class='text-red-600 p-4 font-bold'>Error validando credenciales con Microsoft.</div>", 
                 status_code=401,
                 headers={"HX-Redirect": "/auth/login"}
             )

        # 2. Diccionario de datos
        datos_form = {
            "nombre_proyecto": nombre_proyecto,
            "nombre_cliente": nombre_cliente,
            "canal_venta": canal_venta,
            "tipo_tecnologia": tipo_tecnologia,
            "tipo_solicitud": tipo_solicitud,
            "cantidad_sitios": cantidad_sitios,
            "prioridad": prioridad,
            "direccion_obra": direccion_obra,
            "coordenadas_gps": coordenadas_gps,
            "google_maps_link": google_maps_link,
            "sharepoint_folder_url": sharepoint_folder_url
        }

        # 3. Crear Oportunidad con user_id real
        oportunidad_id = await service.create_oportunidad(datos_form, conn, user_id, nombre)
        
        # 4. Recuperar datos visuales para el Paso 2
        row = await conn.fetchrow(
            "SELECT id_interno_simulacion, titulo_proyecto FROM tb_oportunidades WHERE id_oportunidad = $1", 
            oportunidad_id
        )

        # 4. Lógica Condicional de Pasos
        if cantidad_sitios == 1:
            # CASO 1 SITIO: Auto-crear sitio y saltar al Paso 3 (Email)
            # Usamos los datos de cabecera como el "Sitio Único"
            try:
                # Insertamos el sitio único en tb_sitios_oportunidad
                await conn.execute("""
                    INSERT INTO tb_sitios_oportunidad (id_sitio, id_oportunidad, nombre_sitio, direccion, google_maps_link)
                    VALUES ($1, $2, $3, $4, $5)
                """, uuid4(), oportunidad_id, nombre_proyecto, direccion_obra, google_maps_link)
            except Exception as e:
                logger.error(f"Error auto-creando sitio único: {e}")
            
            # Redirigir al Paso 3 (Email) via HTMX
            # Usamos HX-Location para que el cliente haga el GET
            return HTMLResponse(headers={"HX-Location": f"/comercial/paso3/{oportunidad_id}"})
            
        else:
            # CASO MULTISITIOS (>1): Mostrar Paso 2 (Excel)
            return templates.TemplateResponse(
                "comercial/multisitio_form.html",
                {
                    "request": request,
                    "oportunidad_id": oportunidad_id, 
                    "nombre_cliente": nombre_cliente,
                    "id_interno": row['id_interno_simulacion'],
                    "titulo_proyecto": row['titulo_proyecto'],
                    "cantidad_declarada": cantidad_sitios
                }
            )
            
    except HTTPException as e:
        return templates.TemplateResponse(
            "comercial/error_message.html", 
            {"request": request, "detail": e.detail},
            status_code=e.status_code
        )

# (El endpoint de Excel se mantiene igual, asegúrate de que esté incluido en tu archivo)
@router.delete("/{id_oportunidad}", response_class=HTMLResponse)
async def cancelar_oportunidad(
    request: Request,
    id_oportunidad: UUID,
    conn = Depends(get_db_connection)
):
    """Elimina borrador y fuerza una recarga completa al Dashboard."""
    
    # 1. Protección de Sesión (Conserva esto, es importante)
    if not request.session.get("access_token"):
        return HTMLResponse(status_code=401)
        
    # 2. Borrar datos en BD
    await conn.execute("DELETE FROM tb_sitios_oportunidad WHERE id_oportunidad = $1", id_oportunidad)
    await conn.execute("DELETE FROM tb_oportunidades WHERE id_oportunidad = $1", id_oportunidad)
    
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
    conn = Depends(get_db_connection)
):
    """Muestra el formulario final de envío de correo (Paso 3)."""
    # Recuperar datos para pre-llenar
    row = await conn.fetchrow(
        "SELECT * FROM tb_oportunidades WHERE id_oportunidad = $1", 
        id_oportunidad
    )
    if not row:
        return HTMLResponse("Oportunidad no encontrada", 404)
        
    # Verificar si es multisitio para mostrar badge
    has_multisitio = (row['cantidad_sitios'] or 0) > 1
    
    # --- LOGICA DE CORREOS DINÁMICA (Desde tb_config_emails + Defaults) ---
    
    # 0. Defaults
    defaults_row = await conn.fetchrow("SELECT * FROM tb_email_defaults WHERE id = 1")
    # Parseamos a listas para el frontend (evitar nulos)
    def_to = (defaults_row['default_to'] or "").replace(";", ",").split(",") if defaults_row else []
    def_cc = (defaults_row['default_cc'] or "").replace(";", ",").split(",") if defaults_row else []
    # No pasamos CCO al frontend por privacidad/regla de negocio
    
    fixed_to = [d.strip() for d in def_to if d.strip()] 
    fixed_cc = [d.strip() for d in def_cc if d.strip()]

    # 1. Traer todas las reglas del módulo COMERCIAL
    rules = await conn.fetch("SELECT * FROM tb_config_emails WHERE modulo = 'COMERCIAL'")
    
    # 2. Evaluar reglas
    for rule in rules:
        field = rule['trigger_field']    # e.g., 'tecnologia'
        val_trigger = rule['trigger_value'].upper() # e.g., 'BESS'
        val_actual = str(row.get(field) or "").upper()
        
        # Lógica de coincidencia (Contains)
        if val_trigger in val_actual:
            email = rule['email_to_add']
            tipo = rule['type'] # TO o CC
            
            if tipo == 'TO':
                if email not in fixed_to: fixed_to.append(email)
            else:
                if email not in fixed_cc: fixed_cc.append(email)
    
    # 3. Determinar Template (HTMX vs Full Load)
    if request.headers.get("hx-request"):
        template = "comercial/email_form.html"
    else:
        template = "comercial/email_full.html" # Wrapper que extiende base.html

    return templates.TemplateResponse(
        template,
        {
            "request": request,
            "op": row,
            "has_multisitio_file": has_multisitio,
            "fixed_to": fixed_to,
            "fixed_cc": fixed_cc,
            # Contexto necesario para base.html en Full Load
            "user_name": request.session.get("user_name", "Usuario"),
            "role": request.session.get("role", "USER")
        }
    )

@router.get("/debug/set-dept")
async def debug_set_department(request: Request, dept: str = ""):
    """
    Endpoint de Debug para 'sistemas@enertika.mx'.
    Permite simular ser de otro departamento para probar permisos.
    Uso: /comercial/debug/set-dept?dept=Logistica
    Para resetear: /comercial/debug/set-dept?dept=
    """
    user_email = request.session.get("user_email", "")
    if user_email != "sistemas@enertika.mx":
        raise HTTPException(status_code=403, detail="Solo admin puede usar debug")
        
    if not dept:
        if "mock_department" in request.session:
            del request.session["mock_department"]
        msg = "Debug Mode OFF: Eres Admin (Manager) de nuevo."
    else:
        request.session["mock_department"] = dept
        msg = f"Debug Mode ON: Simulando departamento '{dept}'"
        
    return HTMLResponse(f"<div class='p-4 bg-yellow-100 text-yellow-800 font-bold'>{msg} <a href='/comercial/ui' class='underline ml-2'>Ir al Dashboard</a></div>")

# ----------------------------------------
# NUEVOS ENDPOINTS PARA EXCEL PREVIEW
# ----------------------------------------

@router.post("/upload-preview", response_class=HTMLResponse)
async def upload_preview_endpoint(
    request: Request,
    id_oportunidad: str = Form(...), # Llega como string
    file: UploadFile = File(...),
    service: ComercialService = Depends(get_comercial_service),
    conn = Depends(get_db_connection)
):
    try:
        # 1. Resetear puntero del archivo (CRÍTICO para reintentos)
        await file.seek(0)

        # 2. Validar extensión
        if not file.filename.endswith((".xlsx", ".xls")):
             return HTMLResponse("<div class='bg-red-100 border-l-4 border-red-500 text-red-700 p-4 mb-4'>Error: Solo archivos Excel (.xlsx)</div>", 200)

        # 3. Leer contenido en memoria
        contents = await file.read()
        
        # DEBUG: Imprimir tamaño para ver si llega algo
        print(f"DEBUG: Archivo recibido {file.filename}, tamaño: {len(contents)} bytes")

        import io
        import pandas as pd
        
        try:
            # Engine openpyxl es necesario para xlsx
            df = pd.read_excel(io.BytesIO(contents), engine='openpyxl')
            # Normalizar columnas (Upper + Strip)
            df.columns = [str(c).strip().upper() for c in df.columns]
        except Exception as e:
             logger.error(f"Error Pandas: {e}")
             return HTMLResponse(f"<div class='bg-red-100 border-l-4 border-red-500 text-red-700 p-4 mb-4'>Error: El archivo no es un Excel válido o está corrupto. ({e})</div>", 200)

        # 4. VALIDACIÓN ESTRUCTURA (Columnas)
        cols_req = ["NOMBRE", "DIRECCION"]
        if not all(col in df.columns for col in cols_req):
            return HTMLResponse(f"""
                <div class="bg-red-100 border-l-4 border-red-500 text-red-700 p-4 mb-4">
                    <p class="font-bold">Formato Incorrecto</p>
                    <p class="text-sm">Faltan columnas requeridas: {', '.join([c for c in cols_req if c not in df.columns])}</p>
                    <p class="text-xs mt-1">Usa la plantilla oficial.</p>
                    <button onclick="removeFile(event)" class="text-sm underline mt-2 text-red-800 hover:text-red-900 font-bold">Intentar de nuevo</button>
                </div>
            """, 200)

        # 5. VALIDACIÓN CANTIDAD
        # Convertimos el string id_oportunidad a UUID para la DB
        try:
            uuid_op = UUID(id_oportunidad)
        except ValueError:
             return HTMLResponse("<div class='text-red-500'>Error interno: ID de oportunidad inválido.</div>", 200)

        expected_qty = await conn.fetchval(
            "SELECT cantidad_sitios FROM tb_oportunidades WHERE id_oportunidad = $1", 
            uuid_op
        )
        
        # Si por alguna razón no existe la oportunidad
        if expected_qty is None:
             return HTMLResponse("<div class='text-red-500'>Error: Oportunidad no encontrada en BD.</div>", 200)

        real_qty = len(df)
        
        if real_qty != expected_qty:
            return HTMLResponse(f"""
                <div class="bg-red-100 border-l-4 border-red-500 text-red-700 p-4 mb-4 animate-pulse">
                    <p class="font-bold"> Error de Cantidad</p>
                    <p>Declaraste <strong>{expected_qty}</strong> sitios.</p>
                    <p>El archivo tiene <strong>{real_qty}</strong> filas.</p>
                    <p class="text-sm mt-2 font-semibold">Corrige el Excel y vuelve a seleccionarlo.</p>
                    <button onclick="removeFile(event)" class="text-sm underline mt-2 text-red-800 hover:text-red-900 font-bold">Intentar de nuevo</button>
                </div>
            """, 200)

        # 6. SI TODO ESTÁ BIEN: Generar Preview (Stateless)
        # Convertimos DataFrame a lista de diccionarios para el frontend
        
        # Formato esperado por el frontend: List[Dict]
        preview_rows = df.head(5).values.tolist()
        columns = df.columns.tolist()
        total_rows = len(df)
        
        # Serializamos todo el dataframe para pasarlo como "Hot Potato"
        # Usamos default=str para manejar fechas y UUIDs
        full_data_list = df.fillna("").to_dict(orient='records')
        json_payload = json.dumps(full_data_list, default=str)
        
        return templates.TemplateResponse(
            "comercial/partials/upload_preview.html",
            {
                "request": request,
                "columns": columns,
                "preview_rows": preview_rows,
                "total_rows": total_rows,
                "json_data": json_payload, # <--- La papa caliente
                "op_id": id_oportunidad
            }
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return HTMLResponse(f"""
            <div class='bg-red-100 p-4 text-red-700'>
                <p>Error Técnico (500): {e}</p>
                 <button onclick="removeFile(event)" class="text-sm underline mt-2 font-bold">Intentar de nuevo</button>
            </div>
        """, 200)

@router.get("/upload-preview-full/{file_id}", response_class=HTMLResponse)
async def upload_preview_full_endpoint(
    request: Request,
    file_id: str,
    op_id: Optional[str] = None,
    service: ComercialService = Depends(get_comercial_service)
):
    """Retorna la tabla COMPLETA del Excel cargado temporalmente."""
    import os
    file_path = f"temp_uploads/{file_id}.xlsx"
    
    if not os.path.exists(file_path):
        return HTMLResponse("<div class='p-4 text-red-500'>El archivo ha expirado. Súbelo de nuevo.</div>")

    try:
        import pandas as pd
        df = pd.read_excel(file_path, engine='openpyxl')
        df.columns = [str(c).strip().upper() for c in df.columns]
        
        # Convertir a lista de listas
        rows = df.values.tolist()
        columns = df.columns.tolist()
        total_rows = len(df)

        return templates.TemplateResponse(
            "comercial/partials/upload_preview.html", 
            {
                "request": request,
                "columns": columns,
                "preview_rows": rows,
                "total_rows": total_rows,
                "file_id": file_id,
                "op_id": op_id if op_id else "",
            }
        )
    except Exception as e:
        return HTMLResponse(f"<div class='p-4 text-red-500'>Error leyendo archivo: {e}</div>")


@router.post("/upload-confirm", response_class=HTMLResponse)
async def upload_confirm_endpoint(
    request: Request,
    sitios_json: str = Form(...), # <--- Recibimos el JSON
    op_id: str = Form(...),
    conn = Depends(get_db_connection)
):
    try:
        uuid_op = UUID(op_id)
        
        # 1. Deserializar
        try:
            raw_data = json.loads(sitios_json)
        except json.JSONDecodeError:
             return HTMLResponse("<div class='text-red-500'>Error: Data corrupta (JSON inválido).</div>", 400)
             
        # 2. Borrar sitios anteriores (Idempotencia)
        await conn.execute("DELETE FROM tb_sitios_oportunidad WHERE id_oportunidad = $1", uuid_op)
        
        # 3. Preparar Registros
        records = []
        
        for item in raw_data:
            # Validación con Pydantic (Opcional pero recomendada para sanear)
            # Mapeamos los alias del Excel a los campos internos
            # Como Pydantic usa alias 'NOMBRE' -> 'nombre_sitio', le pasamos el dict tal cual
            try:
                # Validamos contra el schema. 
                # NOTA: SitioImportacion espera alias (NOMBRE, DIRECCION).
                # El json tiene las claves en mayúsculas (NOMBRE, DIRECCION...)
                sitio_obj = SitioImportacion(**item)
                
                records.append((
                    uuid4(), # id_sitio
                    uuid_op,
                    sitio_obj.nombre_sitio,
                    sitio_obj.direccion,
                    sitio_obj.tipo_tarifa,
                    sitio_obj.google_maps_link
                ))
            except Exception as e:
                logger.error(f"Error parseando fila: {item} -> {e}")
                # Podríamos fallar o saltar. Aquí saltamos filas malas.
                continue

        # 4. Insertar
        q = """
            INSERT INTO tb_sitios_oportunidad (
                id_sitio, id_oportunidad, nombre_sitio, direccion, tipo_tarifa, google_maps_link
            ) VALUES ($1, $2, $3, $4, $5, $6)
        """
        if records:
            await conn.executemany(q, records)
        
        return HTMLResponse(content=f"""
        <div class="bg-green-100 border-l-4 border-green-500 text-green-700 p-4 mt-4 animate-fade-in-down" role="alert">
            <p class="font-bold">Carga Exitosa</p>
            <p>Se confirmaron e insertaron {len(records)} sitios.</p>
        </div>
        
        <!-- Transición automática al Paso 3 (Email) -->
        <div hx-trigger="load delay:1s" hx-get="/comercial/paso3/{op_id}" hx-target="#main-content"></div> 
        """, status_code=200)
        
    except Exception as e:
        logger.error(f"Error Confirm: {e}")
        return HTMLResponse(f"<div class='text-red-500'>Error confirmando carga: {e}</div>", 500)

@router.get("/paso2/{id_oportunidad}", include_in_schema=False)
async def get_paso_2_form(request: Request, id_oportunidad: UUID, conn = Depends(get_db_connection)):
    """Re-renderiza el formulario de carga multisitio (Paso 2)."""
    row = await conn.fetchrow(
        "SELECT id_interno_simulacion, titulo_proyecto, cliente_nombre, cantidad_sitios FROM tb_oportunidades WHERE id_oportunidad = $1", 
        id_oportunidad
    )
    if not row:
         return HTMLResponse("Oportunidad no encontrada", 404)
         
    return templates.TemplateResponse(
        "comercial/multisitio_form.html",
        {
            "request": request,
            "oportunidad_id": id_oportunidad, 
            "nombre_cliente": row['cliente_nombre'],
            "id_interno": row['id_interno_simulacion'],
            "titulo_proyecto": row['titulo_proyecto'],
            "cantidad_declarada": row['cantidad_sitios']
        }
    )


# En modules/comercial/router.py

@router.get("/debug/test-email")
async def test_simple_email(
    request: Request,
    ms_auth = Depends(get_ms_auth)
):
    """Prueba de fuego visual."""
    token = request.session.get("access_token")
    
    # Validar sesión
    if not token:
        return HTMLResponse(
            "<h1>❌ Error: No estás logueado</h1><p>Ve a <a href='/auth/login'>Iniciar Sesión</a> primero.</p>"
        )
        
    # Obtener tu email
    profile = ms_auth.get_user_profile(token)
    my_email = profile.get("mail") or profile.get("userPrincipalName")
    
    # Intentar enviar
    ok, msg = ms_auth.send_email_with_attachments(
        access_token=token,
        subject="PRUEBA DE FUEGO (Visual)",
        body="<h1>Sistema Operativo</h1><p>Si lees esto, el envío funciona.</p>",
        recipients=[my_email] if my_email else [] 
    )
    
    # Resultado Visual
    color = "green" if ok else "red"
    titulo = "✅ ÉXITO" if ok else "❌ FALLO"
    
    return HTMLResponse(f"""
        <div style="font-family: sans-serif; padding: 20px; border: 2px solid {color}; background: #f0fdf4;">
            <h2 style="color: {color};">{titulo}</h2>
            <p><strong>Destinatario:</strong> {my_email}</p>
            <p><strong>Resultado Backend:</strong> {msg}</p>
            <hr>
            <p><em>Revisa tu terminal de VS Code para ver los logs detallados.</em></p>
        </div>
    """)