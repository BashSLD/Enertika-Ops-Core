# Archivo: modules/proyectos/router.py

from fastapi import APIRouter, Depends, status, HTTPException
from typing import List
from datetime import datetime
from uuid import UUID, uuid4

# Importamos modelos y dependencias de DB
from .schemas import ProyectoRead, ProyectoFaseUpdate, TraspasoProyectoCreate
from core.database import get_db_connection
from core.microsoft import MicrosoftAuth, get_ms_auth 

router = APIRouter(
    prefix="/proyectos",
    tags=["Módulo Proyectos (Extensión)"],
    # Se asumiría una dependencia para verificar roles Dirección/Ing/Const
)

# --- Capa de Servicio (Service Layer) ---

class ProyectosService:
    """Maneja el flujo de Proyectos, Gates y Automatización de SharePoint."""

    @staticmethod
    def generar_proyecto_id() -> str:
        """Genera un ID de proyecto único (Diferente al OP)."""
        timestamp = datetime.now().strftime("%y%m%d%H%M") 
        return f"PRJ-{timestamp}-{uuid4().hex[:4]}".upper()

    # --- Lógica del Gate 1: Aprobación ---
    async def approve_proyecto(self, conn, id_oportunidad: UUID, ms_auth: MicrosoftAuth) -> ProyectoRead:
        """
        Dirección Aprueba el traspaso de Venta a Proyecto (Gate 1).
        Genera ID de Proyecto, crea carpeta en SharePoint y dispara notificaciones.
        """
        
        # 1. Generar ID de Proyecto
        new_project_id = self.generar_proyecto_id()
        
        # 2. Automatización de SharePoint (CRÍTICO)
        sharepoint_url = await self.create_sharepoint_structure(ms_auth, new_project_id)
        
        # 3. Inserción en tb_proyectos (simulado)
        # Lógica: INSERT INTO tb_proyectos (...) 
        # await conn.execute(INSERT_QUERY, new_project_id, sharepoint_url, ...)
        
        # 4. Notificación Banderazo
        # Correo a Admin, Compras, Simulación, Ingeniería y Construcción.
        print(f"BANDERA ROJA: Proyecto {new_project_id} APROBADO. Notificando a todas las áreas.")
        # Lógica: ms_auth.send_email(...)
        
        # Simulación de respuesta de DB
        return ProyectoRead(
            id_proyecto=uuid4(),
            id_oportunidad=id_oportunidad,
            proyecto_id_estandar=new_project_id,
            status_fase="Ingeniería", # Pasa automáticamente a Gate 2
            aprobacion_direccion=True,
            fecha_aprobacion=datetime.now(),
            sharepoint_carpeta_url=sharepoint_url
        )

    async def create_sharepoint_structure(self, ms_auth: MicrosoftAuth, project_id: str) -> str:
        """
        Utiliza Graph API para crear la estructura de carpetas en SharePoint.
       
        """
        # Aquí iría la lógica de Graph API usando el token de ms_auth
        # Endpoint: /sites/{site-id}/drives/{drive-id}/root:/{project_id}:/children
        
        # Simulación
        print(f"Creando carpeta SharePoint para: {project_id}")
        return f"https://enertika.sharepoint.com/Proyectos/{project_id}"

    # --- Lógica de Gates 2, 3, 4 (Actualizaciones) ---

    async def update_fase(self, conn, project_id: UUID, data: ProyectoFaseUpdate) -> ProyectoRead:
        """Gestiona el paso entre Ingeniería, Construcción y O&M."""
        
        if data.status_fase == "Construcción" and data.documentos_tecnicos_url is None:
            # Gate 2 (Ingeniería) requiere documentos para pasar a Construcción
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El Gate 2 (Ingeniería) requiere los documentos técnicos.")
        
        if data.status_fase == "O&M" and data.documentos_o_m_url is None:
            # Gate 3 (Construcción) requiere docs O&M para pasar a O&M
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El Gate 3 (Construcción) requiere el dossier O&M.")

        # Lógica de actualización de DB
        pass # Implementación de DB pendiente


def get_proyectos_service():
    return ProyectosService()

# --- Endpoints ---

@router.post("/traspaso/{id_oportunidad}", response_model=ProyectoRead, status_code=status.HTTP_201_CREATED)
async def aprobar_traspaso_a_proyecto(
    id_oportunidad: UUID,
    service: ProyectosService = Depends(get_proyectos_service),
    ms_auth: MicrosoftAuth = Depends(get_ms_auth),
    conn = Depends(get_db_connection)
):
    """Endpoint de Dirección: Gate 1. Aprueba el cierre y crea la estructura del proyecto."""
    return await service.approve_proyecto(conn, id_oportunidad, ms_auth)

@router.patch("/{project_id}", response_model=ProyectoRead)
async def actualizar_fase_proyecto(
    project_id: UUID,
    data: ProyectoFaseUpdate,
    service: ProyectosService = Depends(get_proyectos_service),
    conn = Depends(get_db_connection)
):
    """Actualiza el status y documentos en los Gates 2, 3 y 4."""
    return await service.update_fase(conn, project_id, data)