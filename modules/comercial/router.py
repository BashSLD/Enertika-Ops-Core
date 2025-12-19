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
from core.microsoft import MicrosoftAuth, get_ms_auth

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

    async def create_oportunidad(self, conn, datos_form: dict) -> UUID:
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
            
            # ID Dummy para creado_por_id (Requerido NOT NULL en tu esquema)
            # Cuando tengas Auth real, esto vendrá del token.
            dummy_user_id = UUID('00000000-0000-0000-0000-000000000000')

            # Query corregida: Mapeo exacto a columnas
            query = """
                INSERT INTO tb_oportunidades (
                    -- Campos Legacy Nuevos
                    titulo_proyecto, nombre_proyecto, canal_venta, solicitado_por,
                    tipo_tecnologia, tipo_solicitud, cantidad_sitios, prioridad,
                    direccion_obra, coordenadas_gps, google_maps_link, sharepoint_folder_url,
                    deadline_calculado, codigo_generado, id_interno_simulacion,
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
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, NOW(), FALSE,
                    $16, $17, $18, $19, $20, $21
                )
                RETURNING id_oportunidad
            """
            
            # Generamos UUID para el insert manual (para evitar problemas con gen_random_uuid si no está activo)
            new_uuid = uuid4()

            oportunidad_id = await conn.fetchval(
                query,
                titulo_proyecto,                  # 1
                datos_form['nombre_proyecto'],    # 2
                datos_form['canal_venta'],        # 3
                datos_form['canal_venta'],        # 4 (Solicitado por)
                datos_form['tipo_tecnologia'],    # 5
                datos_form['tipo_solicitud'],     # 6
                int(datos_form['cantidad_sitios']),# 7
                datos_form['prioridad'],          # 8
                datos_form['direccion_obra'],     # 9
                datos_form['coordenadas_gps'],    # 10
                datos_form['google_maps_link'],   # 11
                datos_form['sharepoint_folder_url'], # 12
                deadline,                         # 13
                titulo_proyecto,                  # 14 (Codigo generado)
                id_interno_simulacion,            # 15
                
                new_uuid,                         # 16 (id_oportunidad)
                dummy_user_id,                    # 17 (creado_por_id)
                op_id_estandar,                   # 18 (op_id_estandar)
                datos_form['nombre_cliente'],     # 19 (cliente_nombre)
                status_global,                    # 20 (status_global)
                cliente_id                        # 21 (cliente_id FK)
            )
            
            return oportunidad_id
            
        except Exception as e:
            logger.error(f"Error creando oportunidad: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error BD: {e}"
            )

    async def get_oportunidades_list(self, conn, tab: str = "activos", q: str = None, user_email: str = None) -> List[dict]:
        """Recupera la lista filtrada de oportunidades."""
        
        # 1. Base Query
        query = """
            SELECT 
                o.id_oportunidad,
                o.titulo_proyecto,
                o.nombre_proyecto,
                o.cliente_nombre,
                o.fecha_solicitud,
                o.status_global,
                o.email_enviado,
                o.id_interno_simulacion,
                o.solicitado_por,
                o.tipo_solicitud  -- AGREGADO: Necesario para visualización en cards
            FROM tb_oportunidades o
            WHERE 1=1
        """
        params = []
        param_idx = 1

        # 2. Filtro Tab (Lógica de Negocio)
        if tab == "historial":
            # Muestra todo lo finalizado (Ganadas, Perdidas, Canceladas, Entregadas)
            query += f" AND o.status_global IN ('Entregado', 'Cancelado', 'Perdida', 'Ganada')"
            
        elif tab == "levantamientos":
            # NUEVO: Vista exclusiva de seguimiento a Levantamientos
            # Muestra todo lo que sea levantamiento, sin importar si está pendiente o realizado
            query += f" AND o.tipo_solicitud = 'SOLICITUD DE LEVANTAMIENTO'"

        else: # activos (default)
            # Muestra Licitaciones, Pre-ofertas, Cotizaciones en curso.
            # EXCLUYE lo finalizado Y los Levantamientos (porque tienen su propio tab)
            query += f" AND o.status_global NOT IN ('Entregado', 'Cancelado', 'Perdida', 'Ganada')"
            query += f" AND o.tipo_solicitud != 'SOLICITUD DE LEVANTAMIENTO'"

        # 3. Filtro Búsqueda (Texto)
        if q:
            # Buscamos en titulo, nombre, cliente
            query += f" AND (o.titulo_proyecto ILIKE ${param_idx} OR o.nombre_proyecto ILIKE ${param_idx} OR o.cliente_nombre ILIKE ${param_idx})"
            params.append(f"%{q}%")
            param_idx += 1

        # 4. Filtro Contexto Usuario (Solo sus propias solicitudes, salvo Gerentes)
        # Nota: Asumimos que 'solicitado_por' guarda el email.
        # Definir dominios de gerencia o lista blanca si aplica, por ahora simple:
        # Si NO es user admin/gerente (hardcodeado o lógica futura), filtramos.
        # Para cumplir requerimiento estricto: "Agrega WHERE solicitado_por = $1"
        if user_email:
             # Excepción simple para demo: si email empieza con 'admin', no filtra
             if not user_email.startswith("admin"): 
                query += f" AND o.solicitado_por = ${param_idx}"
                params.append(user_email)
                param_idx += 1

        query += " ORDER BY o.fecha_solicitud DESC"
        
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
async def get_comercial_ui(request: Request):
    """Main Entry: Shows the Tabbed Dashboard (Graphs + Records)."""
    return templates.TemplateResponse("comercial/tabs.html", {"request": request})

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
    service: ComercialService = Depends(get_comercial_service),
    conn = Depends(get_db_connection)
):
    """Partial: List of Opportunities (Cards/Grid)."""
    # Intentamos obtener el email del usuario de la sesión
    # Ajustar según como guardes el user en el login real.
    user_email = request.session.get("user_email")
    
    items = await service.get_oportunidades_list(conn, tab=tab, q=q, user_email=user_email)
    
    return templates.TemplateResponse(
        "comercial/partials/cards.html", 
        {
            "request": request, 
            "oportunidades": items,
            "user_token": request.session.get("access_token"),
            "current_tab": tab,
            "q": q
        }
    )

@router.post("/notificar/{id_oportunidad}")
async def notificar_oportunidad(
    request: Request,
    id_oportunidad: UUID,
    subject: str = Form(...),
    body: str = Form(...),
    archivos_extra: List[UploadFile] = File(default=[]),
    service: ComercialService = Depends(get_comercial_service),
    ms_auth: MicrosoftAuth = Depends(get_ms_auth),
    conn = Depends(get_db_connection)
):
    """Envía el correo de notificación usando el token de la sesión."""
    access_token = request.session.get("access_token")
    if not access_token:
        # Si es HTMX, podríamos retornar un div con error o redirect
        return HTMLResponse(
            "<div class='text-red-500'>Error: No has iniciado sesión con Microsoft. <a href='/auth/login' class='underline'>Log In</a></div>",
            status_code=401
        )

    # 1. Recuperar info de la oportunidad para el cuerpo del correo
    row = await conn.fetchrow("SELECT * FROM tb_oportunidades WHERE id_oportunidad = $1", id_oportunidad)
    if not row:
        return HTMLResponse("<div class='text-red-500'>Oportunidad no encontrada</div>", status_code=404)
        
    subject = f"Nueva Oportunidad Comercial: {row['titulo_proyecto']}"
    body = f"""
    Se ha generado una nueva oportunidad comercial.
    
    ID: {row['op_id_estandar']}
    Proyecto: {row['nombre_proyecto']}
    Cliente: {row['cliente_nombre']}
    Link SharePoint: {row['sharepoint_folder_url'] or 'N/A'}
    
    Favor de revisar.
    """
    
    # Destinatarios hardcodeados por ahora o config
    recipients = ["vendedores@enertika.com"] # Ajustar a real
    # Si quieres enviártelo a ti mismo para probar:
    # recipients = [payload_del_token.get("email")] # Si decodificaras el token
    
    # 2. Enviar Correo
    adjuntos_procesados = []
    
    # 1. Procesar archivos extra del formulario
    for archivo in archivos_extra:
        if archivo.filename: # Ignorar inputs vacíos
            contenido = await archivo.read()
            # Reset para seguridad
            await archivo.seek(0) 
            adjuntos_procesados.append({
                "name": archivo.filename,
                "content_bytes": contenido, # Tu wrapper debe manejar bytes
                "contentType": archivo.content_type
            })

    ok, msg = ms_auth.send_email_with_attachments(
        access_token, 
        subject, 
        body, 
        recipients, 
        attachments_files=adjuntos_procesados # <-- Pasamos la lista
    )
    
    if ok:
        await service.update_email_status(conn, id_oportunidad)
        return HTMLResponse(f"""
            <span class="text-green-600 font-bold">✓ Enviado</span>
        """, status_code=200)
    else:
        return HTMLResponse(f"""
            <span class="text-red-600">Error: {msg}</span>
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

@router.post("/", status_code=status.HTTP_201_CREATED)
async def handle_oportunidad_creation(
    request: Request,
    # --- Coincidencia exacta con los 'name'  ---
    nombre_cliente: str = Form(...),
    nombre_proyecto: str = Form(...),
    canal_venta: str = Form(...),
    tipo_tecnologia: str = Form(...),
    tipo_solicitud: str = Form(...),
    cantidad_sitios: int = Form(...), # Asegura que el input HTML tenga value por defecto o type="number"
    prioridad: str = Form(...),
    direccion_obra: str = Form(...),
    google_maps_link: str = Form(...),
    # Campos Opcionales (Deben tener default=None)
    coordenadas_gps: Optional[str] = Form(None),
    sharepoint_folder_url: Optional[str] = Form(None),
    # Inyecciones de Dependencia
    service: ComercialService = Depends(get_comercial_service),
    conn = Depends(get_db_connection) 
):
    # 1. Empaquetamos datos
    datos_form = {
        "nombre_cliente": nombre_cliente,
        "nombre_proyecto": nombre_proyecto,
        "canal_venta": canal_venta,
        "tipo_tecnologia": tipo_tecnologia,
        "tipo_solicitud": tipo_solicitud,
        "cantidad_sitios": cantidad_sitios,
        "prioridad": prioridad,
        "direccion_obra": direccion_obra,
        "google_maps_link": google_maps_link,
        "coordenadas_gps": coordenadas_gps,
        "sharepoint_folder_url": sharepoint_folder_url
    }

    try:
        # 2. Llamada al servicio
        oportunidad_id = await service.create_oportunidad(conn, datos_form)
        
        # 3. Recuperar datos visuales para el Paso 2
        row = await conn.fetchrow(
            "SELECT id_interno_simulacion, codigo_generado FROM tb_oportunidades WHERE id_oportunidad = $1", 
            oportunidad_id
        )

        # 4. Renderizar respuesta (Paso 2: Multisitio)
        if cantidad_sitios >= 1: # Nota: Ajustado a >= 1 para mostrar siempre el paso 2 y confirmar/cargar
            return templates.TemplateResponse(
                "comercial/multisitio_form.html",
                {
                    "request": request,
                    "oportunidad_id": oportunidad_id, 
                    "nombre_cliente": nombre_cliente,
                    "id_interno": row['id_interno_simulacion'],
                    "codigo_generado": row['codigo_generado'],
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
    
    # 3. Retornamos el dashboard completo para "resetear" la vista y volver al inicio
    # Como estamos borrando, lo lógico es volver a cargar la vista por defecto (Activos)
    return templates.TemplateResponse("comercial/tabs.html", {"request": request}) 

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
        "SELECT id_interno_simulacion, codigo_generado, cliente_nombre, cantidad_sitios FROM tb_oportunidades WHERE id_oportunidad = $1", 
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
            "codigo_generado": row['codigo_generado'],
            "cantidad_declarada": row['cantidad_sitios']
        }
    )

@router.get("/paso3/{id_oportunidad}", include_in_schema=False)
async def get_paso_3_form(request: Request, id_oportunidad: UUID, conn = Depends(get_db_connection)):
    """Renderiza el formulario de envío de correo (Paso 3)."""
    row = await conn.fetchrow("SELECT * FROM tb_oportunidades WHERE id_oportunidad = $1", id_oportunidad)
    if not row:
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

    return templates.TemplateResponse(
        "comercial/email_form.html",
        {
            "request": request, 
            "oportunidad_id": id_oportunidad,
            "subject": subject,
            "body": body,
            "recipients": recipients
        }
    )