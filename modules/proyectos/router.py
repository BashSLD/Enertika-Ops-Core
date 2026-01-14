"""
Router del Módulo Proyectos
Maneja el flujo de Gates (1-4) y automatización de SharePoint
"""

from fastapi import APIRouter, Request, Depends, HTTPException, status
from fastapi.templating import Jinja2Templates
from typing import List
from datetime import datetime
from uuid import UUID, uuid4

# Importamos modelos y dependencias de DB
from .schemas import ProyectoRead, ProyectoFaseUpdate, TraspasoProyectoCreate
from core.database import get_db_connection
from core.microsoft import MicrosoftAuth, get_ms_auth

# IMPORTS OBLIGATORIOS para permisos
from core.security import get_current_user_context
from core.permissions import require_module_access

templates = Jinja2Templates(directory="templates")

router = APIRouter(
    prefix="/proyectos",
    tags=["Módulo Proyectos"],
)

# ========================================
# CAPA DE SERVICIO (Service Layer)
# ========================================
class ProyectosService:
    """
    Maneja el flujo de Proyectos, Gates y Automatización de SharePoint.
    
    Gates del Flujo:
    - Gate 1: Dirección aprueba traspaso de Venta a Proyecto
    - Gate 2: Ingeniería → Construcción (requiere docs técnicos)
    - Gate 3: Construcción → O&M (requiere dossier O&M)
    - Gate 4: Cierre del proyecto
    """

    @staticmethod
    def generar_proyecto_id() -> str:
        """Genera un ID de proyecto único (Diferente al OP)."""
        timestamp = datetime.now().strftime("%y%m%d%H%M") 
        return f"PRJ-{timestamp}-{uuid4().hex[:4]}".upper()

    async def approve_proyecto(self, conn, id_oportunidad: UUID, ms_auth: MicrosoftAuth) -> ProyectoRead:
        """
        Gate 1: Dirección Aprueba el traspaso de Venta a Proyecto.
        
        Acciones:
        1. Genera ID único de proyecto
        2. Crea estructura de carpetas en SharePoint
        3. Inserta registro en tb_proyectos
        4. Dispara notificaciones "Banderazo" a todas las áreas
        """
        
        # 1. Generar ID de Proyecto
        new_project_id = self.generar_proyecto_id()
        
        # 2. Automatización de SharePoint (CRÍTICO)
        sharepoint_url = await self.create_sharepoint_structure(ms_auth, new_project_id)
        
        # 3. Inserción en tb_proyectos
        # TODO: Implementar INSERT real
        # await conn.execute(INSERT_QUERY, new_project_id, sharepoint_url, ...)
        
        # 4. Notificación Banderazo
        # TODO: Implementar envío de email a todas las áreas
        print(f"🚩 BANDERA ROJA: Proyecto {new_project_id} APROBADO. Notificando a todas las áreas.")
        
        # Simulación de respuesta de DB
        return ProyectoRead(
            id_proyecto=uuid4(),
            id_oportunidad=id_oportunidad,
            proyecto_id_estandar=new_project_id,
            status_fase="Ingeniería",  # Pasa automáticamente a Gate 2
            aprobacion_direccion=True,
            fecha_aprobacion=datetime.now(),
            sharepoint_carpeta_url=sharepoint_url
        )

    async def create_sharepoint_structure(self, ms_auth: MicrosoftAuth, project_id: str) -> str:
        """
        Utiliza Graph API para crear la estructura de carpetas en SharePoint.
        
        Endpoint Graph: /sites/{site-id}/drives/{drive-id}/root:/{project_id}:/children
        """
        # TODO: Implementación real con Graph API
        print(f"📁 Creando carpeta SharePoint para: {project_id}")
        return f"https://enertika.sharepoint.com/Proyectos/{project_id}"

    async def update_fase(self, conn, project_id: UUID, data: ProyectoFaseUpdate) -> ProyectoRead:
        """
        Gates 2, 3, 4: Gestiona el paso entre fases.
        
        Validaciones:
        - Gate 2 (Ingeniería → Construcción): Requiere documentos técnicos
        - Gate 3 (Construcción → O&M): Requiere dossier O&M
        """
        
        # Validación Gate 2
        if data.status_fase == "Construcción" and data.documentos_tecnicos_url is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El Gate 2 (Ingeniería) requiere los documentos técnicos."
            )
        
        # Validación Gate 3
        if data.status_fase == "O&M" and data.documentos_o_m_url is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El Gate 3 (Construcción) requiere el dossier O&M."
            )

        # TODO: Lógica de actualización de DB
        # await conn.execute(UPDATE_QUERY, data.status_fase, project_id)
        
        pass  # Implementación de DB pendiente

def get_service():
    """Dependencia para inyectar la capa de servicio."""
    return ProyectosService()

# ========================================
# ENDPOINT PRINCIPAL (UI)
# ========================================
@router.api_route("/ui", methods=["GET", "HEAD"], include_in_schema=False)
async def get_proyectos_ui(
    request: Request,
    context = Depends(get_current_user_context),
    _ = require_module_access("proyectos")
):
    """
    Dashboard principal del módulo proyectos.
    
    Muestra:
    - Lista de proyectos activos
    - Estados de Gates
    - Timeline de fases
    
    HTMX Detection:
    - Si viene desde sidebar (HTMX): retorna solo contenido
    - Si es carga directa (F5/URL): retorna dashboard completo
    """
    # HTMX Detection
    if request.headers.get("hx-request"):
        template = "proyectos/partials/content.html"
    else:
        template = "proyectos/dashboard.html"
    
    return templates.TemplateResponse(template, {
        "request": request,
        "user_name": context.get("user_name"),
        "role": context.get("role"),
        "module_roles": context.get("module_roles", {}),
        "current_module_role": context.get("module_roles", {}).get("proyectos", "viewer")
    })

# ========================================
# ENDPOINTS DE API (Gates)
# ========================================
@router.post("/traspaso/{id_oportunidad}", response_model=ProyectoRead, status_code=status.HTTP_201_CREATED)
async def aprobar_traspaso_a_proyecto(
    id_oportunidad: UUID,
    context = Depends(get_current_user_context),
    _ = require_module_access("proyectos", "owner"),  # ✅ SOLO OWNER (Director/Manager)
    service: ProyectosService = Depends(get_service),
    ms_auth: MicrosoftAuth = Depends(get_ms_auth),
    conn = Depends(get_db_connection)
):
    """
    Gate 1: Dirección aprueba el cierre y crea la estructura del proyecto.
    
    ⚠️ REQUIERE ROL OWNER: Solo Director/Manager puede aprobar proyectos.
    
    Acciones:
    - Genera ID de proyecto
    - Crea estructura SharePoint
    - Notifica a todas las áreas
    """
    # Validación adicional por rol de sistema
    role = context.get("role", "USER")
    if role not in ["ADMIN", "MANAGER", "DIRECTOR"]:
        raise HTTPException(
            status_code=403,
            detail="Solo Director o Manager pueden aprobar proyectos"
        )
    
    return await service.approve_proyecto(conn, id_oportunidad, ms_auth)

@router.patch("/{project_id}", response_model=ProyectoRead)
async def actualizar_fase_proyecto(
    project_id: UUID,
    data: ProyectoFaseUpdate,
    context = Depends(get_current_user_context),
    _ = require_module_access("proyectos", "editor"),  # ✅ REQUIERE EDITOR
    service: ProyectosService = Depends(get_service),
    conn = Depends(get_db_connection)
):
    """
    Gates 2, 3, 4: Actualiza el status y documentos.
    
    ⚠️ REQUIERE ROL EDITOR o superior.
    
    Validaciones:
    - Gate 2: Requiere documentos técnicos
    - Gate 3: Requiere dossier O&M
    """
    return await service.update_fase(conn, project_id, data)