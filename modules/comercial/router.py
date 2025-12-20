from fastapi import APIRouter, Depends, status, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import StreamingResponse, HTMLResponse

from fastapi.templating import Jinja2Templates
from typing import List, Optional
from datetime import datetime, timedelta, time as dt_time
from uuid import UUID, uuid4
import pandas as pd
import io
import logging

# --- Imports de Core ---
from core.database import get_db_connection
from core.database import get_db_connection
from core.microsoft import get_ms_auth, MicrosoftAuth
from core.config import settings
from core.security import get_current_user_context
from .schemas import OportunidadCreate

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
        """
        Busca el cliente por nombre fiscal. 
        NOTA: Asumimos que la tabla tb_clientes tiene columna 'id' (estándar).
        Si falla aquí, es porque tb_clientes usa otro nombre de PK.
        """
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

    async def create_oportunidad(self, datos_form: dict, conn, user_id: UUID) -> UUID:
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
            
            # Query corregida: Usamos titulo_proyecto (renombrado en DB)
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
                datos_form['canal_venta'],        # 4 (Solicitado por) - Mantenemos esto como string legacy? Sí, 'solicitado_por' texto.
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
            logger.error(f"Error creando oportunidad: {e}")
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

            
    # El método process_multisitio_excel se queda igual...
    async def process_multisitio_excel(self, conn, id_oportunidad: UUID, file: UploadFile) -> int:
        # ... (código existente)
        try:
            # 1. Obtener cantidad declarada en BD
            cant_declarada = await conn.fetchval(
                "SELECT cantidad_sitios FROM tb_oportunidades WHERE id_oportunidad = $1", 
                id_oportunidad
            )
            
            contents = await file.read()
            df = pd.read_excel(io.BytesIO(contents), engine='openpyxl')
            df.columns = [str(c).strip().upper() for c in df.columns]
            
            cols_req = ["NOMBRE", "DIRECCION"]
            if not all(col in df.columns for col in cols_req):
                raise ValueError(f"Faltan columnas: {cols_req}")

            # 2. VALIDACIÓN DE CANTIDAD (NUEVO)
            cant_real = len(df)
            if cant_real != cant_declarada:
                raise ValueError(
                    f"Discrepancia de sitios: Declaraste {cant_declarada} en el paso anterior, "
                    f"pero el archivo contiene {cant_real} filas."
                )

            # OJO: Aquí también corregimos para usar id_oportunidad en el WHERE
            await conn.execute("DELETE FROM tb_sitios_oportunidad WHERE id_oportunidad = $1", id_oportunidad)
            
            records = []
            for _, row in df.iterrows():
                records.append((
                    uuid4(), # id_sitio (según tu radiografía)
                    id_oportunidad,
                    str(row.get("NOMBRE", "")).strip(),
                    str(row.get("DIRECCION", "")).strip(),
                    str(row.get("TARIFA", "")).strip() if row.get("TARIFA") else None,
                    str(row.get("LINK GOOGLE", "")).strip() if row.get("LINK GOOGLE") else None
                ))

            # Ajustamos INSERT a tb_sitios_oportunidad según radiografía
            q = """
                INSERT INTO tb_sitios_oportunidad (
                    id_sitio, id_oportunidad, nombre_sitio, direccion, tipo_tarifa, google_maps_link
                ) VALUES ($1, $2, $3, $4, $5, $6)
            """
            if records:
                await conn.executemany(q, records)
            return len(records)

        except Exception as e:
            logger.error(f"Error Excel: {e}")
            raise HTTPException(500, f"Error Excel: {e}")


    async def preview_multisitio_excel(self, file: UploadFile) -> dict:
        """Lee el archivo, lo guarda temporalmente y retorna preview + file_id."""
        
        # 1. Guardar temporalmente
        file_id = str(uuid4())
        import os
        os.makedirs("temp_uploads", exist_ok=True)
        file_path = f"temp_uploads/{file_id}.xlsx"
        
        # Guardamos el archivo
        with open(file_path, "wb") as buffer:
            import shutil
            shutil.copyfileobj(file.file, buffer)
            
        # 2. Leer partial con Pandas
        try:
            df = pd.read_excel(file_path, engine='openpyxl')
            df.columns = [str(c).strip().upper() for c in df.columns]
            
            # Validación básica de columnas
            cols_req = ["NOMBRE", "DIRECCION"]
            if not all(col in df.columns for col in cols_req):
                # Borrar si es inválido
                os.remove(file_path)
                raise ValueError(f"Faltan columnas requeridas: {cols_req}")
                
            preview_rows = df.head(5).values.tolist()
            columns = df.columns.tolist()
            total_rows = len(df)
            
            return {
                "file_id": file_id,
                "preview_rows": preview_rows,
                "columns": columns,
                "total_rows": total_rows
            }
        except Exception as e:
            if os.path.exists(file_path):
                os.remove(file_path)
            raise e

    async def confirm_multisitio_upload(self, conn, id_oportunidad: UUID, file_id: str) -> int:
        """Procesa el archivo temporal confirmado e inserta en BD."""
        import os
        file_path = f"temp_uploads/{file_id}.xlsx"
        
        if not os.path.exists(file_path):
            raise FileNotFoundError("El archivo temporal ha expirado o no existe.")
            
        try:
            # Reutilizamos lógica de lectura, esta vez completa
            df = pd.read_excel(file_path, engine='openpyxl')
            df.columns = [str(c).strip().upper() for c in df.columns]
            
            # (Aquí podríamos re-validar cantidad vs oportunidad si fuera necesario)
            
            # Borrar sitios anteriores
            await conn.execute("DELETE FROM tb_sitios_oportunidad WHERE id_oportunidad = $1", id_oportunidad)
            
            records = []
            for _, row in df.iterrows():
                records.append((
                    uuid4(),
                    id_oportunidad,
                    str(row.get("NOMBRE", "")).strip(),
                    str(row.get("DIRECCION", "")).strip(),
                    str(row.get("TARIFA", "")).strip() if row.get("TARIFA") else None,
                    str(row.get("LINK GOOGLE", "")).strip() if row.get("LINK GOOGLE") else None
                ))
                
            q = """
                INSERT INTO tb_sitios_oportunidad (
                    id_sitio, id_oportunidad, nombre_sitio, direccion, tipo_tarifa, google_maps_link
                ) VALUES ($1, $2, $3, $4, $5, $6)
            """
            if records:
                await conn.executemany(q, records)
                
            return len(records)
            
        finally:
            # Siempre intentamos borrar el temporal
            if os.path.exists(file_path):
                try: 
                    os.remove(file_path)
                except:
                    pass

# ----------------------------------------
# DEPENDENCIES
# ----------------------------------------
def get_comercial_service():
    return ComercialService()



# ----------------------------------------
# ENDPOINTS
# ----------------------------------------

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
    })

@router.get("/form", include_in_schema=False)
async def get_comercial_form(request: Request):
    """Shows the creation form (Partial or Full Page)."""
    return templates.TemplateResponse("comercial/form.html", {"request": request})

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
        
    # 2. Procesar Destinatarios (TO)
    final_to = set()
    
    # a) From Chips (recipients_str)
    if recipients_str:
        raw_list = recipients_str.replace(";", ",").split(",")
        for email in raw_list:
            if email.strip(): final_to.add(email.strip())
            
    # b) From Fixed rules
    for email in fixed_to:
        if email.strip(): final_to.add(email.strip())

    # Fallback
    if not final_to:
        final_to.add("vendedores@enertika.com")

    # 3. Procesar Copias (CC)
    final_cc = set()
    
    # a) From Fixed rules
    for email in fixed_cc:
        if email.strip(): final_cc.add(email.strip())
        
    # b) From Manual Input
    if extra_cc:
        raw_cc = extra_cc.replace(";", ",").split(",")
        for email in raw_cc:
            if email.strip(): final_cc.add(email.strip())

    recipients_list = list(final_to)
    cc_list = list(final_cc)

    logger.info(f"Enviando correo OP {row['op_id_estandar']} | TO: {recipients_list} | CC: {cc_list}")

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

    # 6. Enviar
    ok, msg = ms_auth.send_email_with_attachments(
        access_token, 
        subject, 
        body, 
        recipients_list,
        cc_recipients=cc_list, # NUEVO
        attachments_files=adjuntos_procesados 
    )
    
    if ok:
        await service.update_email_status(conn, id_oportunidad)
        return HTMLResponse(f"""
            <div class="text-center">
                <p class="text-green-600 font-bold text-xl mb-2">✓ Enviado Exitosamente</p>
                <div hx-get="/comercial/ui" hx-target="#main-content" hx-trigger="load delay:1s">
                    <span class="text-gray-500 text-sm">Redirigiendo al inicio...</span>
                </div>
            </div>
        """, status_code=200)
    else:
        logger.error(f"Fallo envio correo Graph: {msg}")
        return HTMLResponse(f"""
            <span class="text-red-600">Error enviando correo: {msg}</span>
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
        user_id = UUID('00000000-0000-0000-0000-000000000000') # Fallback por si acaso

        if token:
            profile = ms_auth.get_user_profile(token)
            if profile:
                email = profile.get("mail") or profile.get("userPrincipalName")
                nombre = profile.get("displayName")
                
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
        oportunidad_id = await service.create_oportunidad(datos_form, conn, user_id)
        
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
    request: Request,  # <--- FALTABA ESTO
    id_oportunidad: UUID, 
    conn = Depends(get_db_connection)
):
    """Elimina borrador y regresa al Dashboard."""
    # 1. Borrar sitios hijos
    await conn.execute("DELETE FROM tb_sitios_oportunidad WHERE id_oportunidad = $1", id_oportunidad)
    # 2. Borrar cabecera
    await conn.execute("DELETE FROM tb_oportunidades WHERE id_oportunidad = $1", id_oportunidad)
    
    # 3. Retornamos respuesta vacía con header de redirección HTMX
    # Esto fuerza al cliente a hacer un GET completo a /comercial/ui, restaurando Sidebar y Contexto
    from fastapi import Response
    return Response(status_code=200, headers={"HX-Location": "/comercial/ui"}) 


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
    
    # --- LOGICA DE CORREOS DINÁMICA (Desde tb_config_emails) ---
    fixed_to = ["vendedores@enertika.com"] # Default hardcoded
    fixed_cc = []

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
                    <p class="font-bold">❌ Error de Cantidad</p>
                    <p>Declaraste <strong>{expected_qty}</strong> sitios.</p>
                    <p>El archivo tiene <strong>{real_qty}</strong> filas.</p>
                    <p class="text-sm mt-2 font-semibold">Corrige el Excel y vuelve a seleccionarlo.</p>
                    <button onclick="removeFile(event)" class="text-sm underline mt-2 text-red-800 hover:text-red-900 font-bold">Intentar de nuevo</button>
                </div>
            """, 200)

        # 6. SI TODO ESTÁ BIEN: Generar Preview
        # Reseteamos el archivo de nuevo para que el servicio lo pueda guardar
        await file.seek(0) 
        
        data = await service.preview_multisitio_excel(file)
        
        return templates.TemplateResponse(
            "comercial/partials/upload_preview.html",
            {
                "request": request,
                "columns": data["columns"],
                "preview_rows": data["preview_rows"],
                "total_rows": data["total_rows"],
                "file_id": data["file_id"],
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
    file_id: str = Form(...),
    op_id: str = Form(...),
    service: ComercialService = Depends(get_comercial_service),
    conn = Depends(get_db_connection)
):
    try:
        uuid_op = UUID(op_id)
        cantidad = await service.confirm_multisitio_upload(conn, uuid_op, file_id)
        
        return HTMLResponse(content=f"""
        <div class="bg-green-100 border-l-4 border-green-500 text-green-700 p-4 mt-4 animate-fade-in-down" role="alert">
            <p class="font-bold">Carga Exitosa</p>
            <p>Se confirmaron e insertaron {cantidad} sitios.</p>
        </div>
        
        <!-- CAMBIO: Transición automática al Paso 3 (Email) -->
        <div hx-trigger="load delay:1s" hx-get="/comercial/paso3/{op_id}" hx-target="#main-content"></div> 
        """, status_code=200)
        
    except FileNotFoundError:
        return HTMLResponse("<div class='text-red-500'>Error: La sesión de carga ha expirado. Sube el archivo nuevamente.</div>", 400)
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

@router.get("/paso3/{id_oportunidad}", include_in_schema=False)
async def get_paso_3_form(request: Request, id_oportunidad: UUID, conn = Depends(get_db_connection)):
    """Renderiza el formulario de envío de correo (Paso 3)."""
    row = await conn.fetchrow("SELECT * FROM tb_oportunidades WHERE id_oportunidad = $1", id_oportunidad)
    if not row:
        logger.error(f"Paso 3: Oportunidad {id_oportunidad} no encontrada.")
        return HTMLResponse("Oportunidad no encontrada", 404)

    # Preparamos datos del correo (igual que en notificar_oportunidad)
    subject = f"Nueva Oportunidad Comercial: {row['titulo_proyecto']}"
    body = f"""
    Se ha generado una nueva oportunidad comercial.
    
    ID: {row['op_id_estandar']}
    Proyecto: {row['nombre_proyecto']}
    Cliente: {row['cliente_nombre']}
    Link SharePoint: {row['sharepoint_folder_url'] or 'N/A'}
    
    Favor de revisar.
    """
    recipients = "vendedores@enertika.com"

    # Multisitio Check
    has_multisitio = (row['cantidad_sitios'] or 1) > 1

    return templates.TemplateResponse(
        "comercial/email_form.html",
        {
            "request": request, 
            "op": row, # <--- FIXED: template expects 'op'
            "has_multisitio_file": has_multisitio, # <--- FIXED
            "oportunidad_id": id_oportunidad,
            "subject": subject,
            "body": body,
            "recipients": recipients
        }
    )