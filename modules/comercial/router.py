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
    return templates.TemplateResponse("comercial/form.html", {"request": request})

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
@router.delete("/{id_oportunidad}", status_code=204)
async def cancelar_oportunidad(
    id_oportunidad: UUID, 
    conn = Depends(get_db_connection)
):
    """Elimina una oportunidad en borrador (Limpieza de fantasmas)."""
    # Primero borramos sitios hijos por FK
    await conn.execute("DELETE FROM tb_sitios_oportunidad WHERE id_oportunidad = $1", id_oportunidad)
    # Borramos cabecera
    await conn.execute("DELETE FROM tb_oportunidades WHERE id_oportunidad = $1", id_oportunidad)
    return 
@router.post("/multisitio/{id_oportunidad}", status_code=status.HTTP_200_OK, response_class=HTMLResponse)
async def cargar_multisitio_endpoint(
    request: Request,
    id_oportunidad: str, # Recibe UUID como string
    file: UploadFile = File(...),
    service: ComercialService = Depends(get_comercial_service),
    conn = Depends(get_db_connection)
):
    # Usar id_oportunidad convertido a UUID si la base de datos es estricta
    try:
        uuid_op = UUID(id_oportunidad)
    except:
        uuid_op = id_oportunidad # Intentamos como string si falla

    try:
        cantidad = await service.process_multisitio_excel(conn, uuid_op, file)
        return HTMLResponse(content=f"""
        <div class="bg-green-100 border-l-4 border-green-500 text-green-700 p-4 mt-4 animate-fade-in-down" role="alert">
            <p class="font-bold">Carga Masiva Exitosa</p>
            <p>Se cargaron {cantidad} sitios correctamente.</p>
        </div>
        """, status_code=200)
        
    except ValueError as e:
        return HTMLResponse(content=f"""
        <div class="bg-yellow-100 border-l-4 border-yellow-500 text-yellow-700 p-4 mt-4 animate-fade-in-down" role="alert">
            <p class="font-bold">Atención</p>
            <p>{str(e)}</p>
        </div>
        """, status_code=200)

    except Exception as e:
         logger.error(f"Error carga multisitio: {e}")
         return HTMLResponse(content=f"""
            <div class="bg-red-100 border-l-4 border-red-500 text-red-700 p-4 mt-4 animate-fade-in-down" role="alert">
                <p class="font-bold">Error procesando archivo</p>
                <p>{str(e)}</p>
            </div>
        """, status_code=200)