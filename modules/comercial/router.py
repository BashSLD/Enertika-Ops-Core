# Archivo: modules/comercial/router.py

from fastapi import APIRouter, Depends, status, HTTPException, UploadFile, File
from typing import List
from datetime import datetime
from uuid import uuid4, UUID
import pandas as pd
import io # Para manejar archivos en memoria
import os
from pydantic import BaseModel
from fastapi.templating import Jinja2Templates
from fastapi import Request

# Inicializar templates (tomando la configuración de main.py)
templates = Jinja2Templates(directory="templates")

# Importamos dependencias y Auth
from core.microsoft import MicrosoftAuth, get_ms_auth

# Importamos los modelos Pydantic
from .schemas import (
    OportunidadCreate, OportunidadRead, 
    SitioOportunidadBase, SitioOportunidadRead, 
)
# Asumimos que el servicio de conexión a DB se define en core/service.py
# from core.database import get_db_connection 

router = APIRouter(
    prefix="/comercial",
    tags=["Módulo Comercial"],
    # Aquí se añadirán dependencias de Auth (e.g., Depends(validar_rol_comercial))
)

# ----------------------------------------
# ENDPOINTS DE UI (JINJA2/HTMX)
# ----------------------------------------

@router.get("/ui", include_in_schema=False)
async def get_comercial_ui(request: Request):
    """Renderiza la vista inicial del Módulo Comercial (Formulario de Solicitud)."""
    # Usaremos una vista específica: templates/comercial/form.html
    return templates.TemplateResponse(
        "comercial/form.html",
        {"request": request, "page_title": "Módulo Comercial: Solicitud de Oportunidad"}
    )

# --- Capa de Servicio Simulada (Service Layer) ---
# En un proyecto real, esta clase manejaría el CRUD con Supabase (asyncpg)

class ComercialService:
    """Implementa la lógica de negocio del módulo Comercial."""

    @staticmethod
    def generar_op_id() -> str:
        """
        Genera el ID Estándar: OP-YYMMDDhhmm... 
        (Formato estricto requerido por el Contexto)
        """
        # Formato: OP-YYMMDDhhmm... (se incluye segundos para mayor unicidad)
        timestamp = datetime.now().strftime("%y%m%d%H%M%S") 
        return f"OP-{timestamp}"

    # Simulación de la función que interactuaría con la DB
    async def create_oportunidad(self, data: OportunidadCreate) -> OportunidadRead:
        """Crea Oportunidad, genera ID y la inserta en tb_oportunidades."""
        
        op_id = self.generar_op_id()
        
        # --- LÓGICA DE INSERCIÓN EN SUPABASE IRÍA AQUÍ ---
        # data_to_insert = {..., "op_id_estandar": op_id, "status_global": "Comercial"}
        # await db.fetch_one(QUERY_INSERT)
        
        # Simulación de respuesta de la DB
        db_data = {
            "id_oportunidad": uuid4(), 
            "op_id_estandar": op_id,
            "cliente_nombre": data.cliente_nombre,
            "status_global": "Comercial",
            "fecha_creacion": datetime.now(),
            "creado_por_id": data.creado_por_id
        }
        # Usamos model_validate para convertir el dict de la DB simulada a Pydantic
        return OportunidadRead.model_validate(db_data, from_attributes=True)
    
    # ----------------------------------------------------
    # Procesamiento y Carga de Excel Multisitio
    # ----------------------------------------------------
    async def process_multisitio_excel(self, id_oportunidad: UUID, file: UploadFile) -> int:
        """
        Procesa el archivo Excel y extrae los sitios.
        """
        
        # 1. Leer el archivo cargado en memoria
        content = await file.read()
        try:
            # Usamos io.BytesIO para que Pandas pueda leer el contenido binario
            df = pd.read_excel(io.BytesIO(content), engine='openpyxl')
        except Exception as e:
            # Esto captura errores de formato o corrupción del Excel
            print(f"Error al leer Excel: {e}")
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, 
                detail="Error al procesar el Excel. Asegúrate que el formato sea correcto."
            )
        
        # 2. Mapeo y Validación de Columnas (Asumimos que el Excel tiene estas columnas)
        required_columns = ['Direccion', 'Coordenadas', 'Tipo Tarifa']
        if not all(col in df.columns for col in required_columns):
             raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail=f"El Excel debe contener las columnas: {', '.join(required_columns)}"
            )

        sitios_a_insertar: List[SitioOportunidadBase] = []
        
        for index, row in df.iterrows():
            try:
                # Se valida contra el schema Pydantic para asegurar tipos de datos
                sitios_a_insertar.append(SitioOportunidadBase(
                    direccion=str(row['Direccion']),
                    coordenadas=str(row['Coordenadas']) if pd.notna(row['Coordenadas']) else None,
                    tipo_tarifa=str(row['Tipo Tarifa']) if pd.notna(row['Tipo Tarifa']) else None
                ))
            except Exception as e:
                # Captura errores en la fila específica
                print(f"Error de validación en la fila {index}: {e}")
                # Podrías registrar el error y continuar, o detener la carga.
                continue 
            
        # 3. Lógica de inserción MÚLTIPLE en tb_sitios_oportunidad (Supabase)
        # Aquí iría el bucle o el método bulk_insert(sitios_a_insertar)
        # Ej: await db.execute("INSERT INTO tb_sitios_oportunidad (id_oportunidad, ...) VALUES (%s, %s, ...)", [id_oportunidad, ...])

        sitios_cargados_count = len(sitios_a_insertar)
        # if sitios_cargados_count == 0:
        #     raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No se encontraron sitios válidos para cargar.")

        return sitios_cargados_count

    # NUEVO MÉTODO: Envío de Correo (Acción Final del Módulo Comercial)
    async def send_simulacion_email(self, auth_service: MicrosoftAuth, email_data: dict, file_paths: List[str]) -> bool:
        """
        Llama a la capa de MicrosoftAuth para enviar el correo al departamento de Simulación.
        """
        try:
            # Reconstruimos la lista de archivos para Graph API
            attachments = [{"name": os.path.basename(p), "path": p} for p in file_paths]
            
            # Dirección de Simulación (Debe estar en settings o db)
            recipients = ["simulacion@enertika.mx", "direccion@enertika.mx"] # EJEMPLO
            
            # Usamos el método existente del legacy
            exito, mensaje = auth_service.send_email_with_attachments(
                subject=email_data['subject'],
                body=email_data['body'],
                recipients=recipients,
                attachments_files=attachments
            )
            
            if not exito:
                raise Exception(f"Fallo en Graph API: {mensaje}")
            
            # Si el envío fue exitoso, actualiza el status en la DB.
            # Aquí iría la lógica: await conn.execute("UPDATE tb_oportunidades SET email_enviado=TRUE WHERE id=$1", email_data['oportunidad_id'])

            return True
            
        except Exception as e:
            print(f"Error al enviar correo: {e}")
            # El router capturará esto y lo devolverá como un 500
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error al enviar solicitud: {e}")


def get_comercial_service():
    """Dependencia para inyectar la capa de servicio."""
    return ComercialService()


# --- Endpoints ---

@router.post("/", response_model=OportunidadRead, status_code=status.HTTP_201_CREATED)
async def crear_oportunidad_endpoint(
    oportunidad: OportunidadCreate,
    service: ComercialService = Depends(get_comercial_service)
):
    """
    Crea una nueva oportunidad y genera automáticamente el ID Estándar (OP-YYMMDDhhmm...).
    """
    return await service.create_oportunidad(oportunidad)

@router.post("/multisitio/{id_oportunidad}", status_code=status.HTTP_200_OK)
async def cargar_multisitio_endpoint(
    id_oportunidad: UUID,
    # UploadFile maneja el archivo binario
    file: UploadFile = File(..., description="Archivo Excel con la lista de sitios."),
    service: ComercialService = Depends(get_comercial_service)
):
    """
    Procesa un archivo Excel, valida el tipo de archivo y carga múltiples sitios 
    vinculados a una oportunidad usando Pandas.
    """
    # Validar tipo de archivo antes de leer
    if file.content_type not in [
        "application/vnd.ms-excel", 
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tipo de archivo no soportado. Debe ser un archivo Excel (.xls o .xlsx)."
        )

    try:
        sitios_cargados = await service.process_multisitio_excel(id_oportunidad, file)
        return {
            "mensaje": f"Carga de multisitio completada. {sitios_cargados} sitios listos para inserción.",
            "sitios_cargados": sitios_cargados
        }
    except HTTPException as e:
        # Re-lanza la HTTPException con el código de error específico
        raise e
    except Exception:
        # Captura cualquier otro error no esperado
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno del servidor durante la carga del archivo."
        )

# --- NUEVO ENDPOINT PARA EL ENVÍO FINAL ---

class EmailSendRequest(BaseModel):
    oportunidad_id: UUID
    subject: str
    body: str
    # Lista de rutas temporales o URLs de almacenamiento (depende del modo web/desktop)
    attached_files: List[str] 

@router.post("/send_request", status_code=status.HTTP_200_OK)
async def enviar_solicitud_simulacion(
    data: EmailSendRequest,
    service: ComercialService = Depends(get_comercial_service),
    ms_auth: MicrosoftAuth = Depends(get_ms_auth) # <--- INYECTAMOS MS AUTH
):
    """
    Finaliza el proceso Comercial: Guarda la Oportunidad en BD y envía el correo a Simulación.
    """
    email_data = {
        "subject": data.subject,
        "body": data.body,
        "oportunidad_id": data.oportunidad_id
    }
    
    await service.send_simulacion_email(ms_auth, email_data, data.attached_files)
    
    return {"mensaje": "Solicitud enviada a Simulación exitosamente y registrada."}

# Agregamos la ruta de lectura de oportunidad básica para verificación
@router.get("/{op_id}", response_model=OportunidadRead)
def get_oportunidad_by_op_id(op_id: str):
    """Obtiene una Oportunidad por su ID Estándar."""
    # En la implementación real, esta función llama a service.get_oportunidad(op_id)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Endpoint de lectura aún no implementado en la capa de servicio.")