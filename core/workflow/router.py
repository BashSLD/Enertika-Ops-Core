"""
Router Centralizado de Comentarios
Endpoints compartidos por todos los módulos para gestión de comentarios
"""

from fastapi import APIRouter, Request, Depends, Form, HTTPException, File, UploadFile
from fastapi.templating import Jinja2Templates
import logging
import json
from uuid import UUID
from typing import Optional, List

# Core imports
from core.security import get_current_user_context, get_valid_graph_token
from core.permissions import user_has_module_access
from core.database import get_db_connection
from core.workflow.service import get_workflow_service

logger = logging.getLogger("SharedComments")
templates = Jinja2Templates(directory="templates")

# Registrar filtros de timezone
from core.jinja_filters import register_timezone_filters
register_timezone_filters(templates.env)

router = APIRouter(
    prefix="/workflow",
    tags=["Workflow - Comentarios Centralizados"],
)

# Mapeo de módulos a departamentos
MODULE_TO_DEPT = {
    "simulacion": "SIMULACION",
    "comercial": "COMERCIAL",
    "ingenieria": "INGENIERIA",
    "levantamientos": "LEVANTAMIENTOS",
    "proyectos": "PROYECTOS",
    "compras": "COMPRAS",
    "construccion": "CONSTRUCCION",
    "oym": "OYM"
}

@router.get("/modals/comentarios")
async def get_comentarios_modal(
    request: Request,
    id_oportunidad: UUID,
    module: str,  # Slug del módulo: "simulacion", "comercial", etc.
    workflow_service = Depends(get_workflow_service),
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context)
):
    """
    Modal centralizado de comentarios para todos los módulos.
    
    Query params:
        - id_oportunidad: UUID de la oportunidad
        - module: slug del módulo (ej: "simulacion", "comercial")
    """
    logger.info(f"[COMENTARIOS MODAL] Solicitado para oportunidad {id_oportunidad} desde módulo {module}")
    
    # Validar que el módulo exista en el mapeo
    if module not in MODULE_TO_DEPT:
        raise HTTPException(status_code=400, detail=f"Módulo '{module}' no válido")
    
    # Obtener info de la oportunidad para el header
    op = await conn.fetchrow("""
        SELECT op_id_estandar, nombre_proyecto, titulo_proyecto, cliente_nombre 
        FROM tb_oportunidades 
        WHERE id_oportunidad = $1
    """, id_oportunidad)
    
    if not op:
        raise HTTPException(status_code=404, detail="Oportunidad no encontrada")
    
    # Verificar permisos - CUALQUIER usuario con acceso al módulo puede VER comentarios
    # Solo editores+ pueden CREAR comentarios
    can_comment = user_has_module_access(module, context, min_role="editor")
    
    # Obtener historial de comentarios
    comentarios = await workflow_service.get_historial(conn, id_oportunidad)
    
    logger.info(f"[COMENTARIOS MODAL] Mostrando {len(comentarios)} comentarios. Usuario puede comentar: {can_comment}")
    
    return templates.TemplateResponse("shared/modals/comentarios_modal.html", {
        "request": request,
        "id_oportunidad": id_oportunidad,
        "module_slug": module,
        "department_slug": MODULE_TO_DEPT.get(module),
        "can_comment": can_comment,
        "op_info": dict(op) if op else None,
        "comentarios": comentarios,
        "context": context
    })


@router.post("/comentarios")
async def create_comentario_workflow(
    request: Request,
    id_oportunidad: UUID = Form(...),
    nuevo_comentario: str = Form(...),
    module: str = Form(...),  # Slug del módulo
    file_uploads: List[UploadFile] = File(None), # Nuevo: Lista de archivos
    workflow_service = Depends(get_workflow_service),
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context)
):
    """
    Endpoint centralizado para crear comentarios desde cualquier módulo.
    
    Valida permisos dinámicamente según el módulo de origen.
    Retorna la lista actualizada de comentarios para reemplazar en el modal.
    """
    logger.info(f"[CREATE COMENTARIO] Módulo: {module}, Oportunidad: {id_oportunidad}, Usuario: {context.get('user_name')}")
    
    # Validar módulo
    if module not in MODULE_TO_DEPT:
        raise HTTPException(status_code=400, detail=f"Módulo '{module}' no válido")
    
    # Validar permisos dinámicamente
    if not user_has_module_access(module, context, min_role="editor"):
        logger.warning(f"[CREATE COMENTARIO] Usuario {context.get('user_name')} sin permisos de editor en {module}")
        raise HTTPException(
            status_code=403, 
            detail=f"No tienes permisos para comentar en el módulo {module}"
        )
    
    # Obtener token para SharePoint (Si hay archivos)
    sharepoint_token = None
    if file_uploads:
        sharepoint_token = await get_valid_graph_token(request)
        if not sharepoint_token:
            # Si expira, podríamos fallar o subir sin token (que fallará en service)
            logger.warning("[CREATE COMENTARIO] Token expirado al intentar subir archivo")
            # Dejamos que el servicio maneje el error o falle
    
    # Crear comentario usando WorkflowService
    if nuevo_comentario.strip() or file_uploads:
        await workflow_service.add_comentario(
            conn, 
            context, 
            id_oportunidad, 
            nuevo_comentario.strip(),
            departamento_slug=MODULE_TO_DEPT.get(module),
            modulo_origen=module,
            file_uploads=file_uploads,
            sharepoint_token=sharepoint_token
        )
        logger.info(f"[CREATE COMENTARIO] Comentario creado exitosamente")
    else:
        logger.warning(f"[CREATE COMENTARIO] Comentario vacío recibido, ignorado")
    
    # Retornar lista actualizada de comentarios
    comentarios = await workflow_service.get_historial(conn, id_oportunidad)
    
    # Retornar lista actualizada de comentarios
    comentarios = await workflow_service.get_historial(conn, id_oportunidad)
    
    response = templates.TemplateResponse("shared/partials/comentarios_list.html", {
        "request": request,
        "comentarios": comentarios,
        "mode": None,
        "has_more": False,
        "total_extra": 0,
        "id_oportunidad": id_oportunidad
    })
    
    # Trigger Toast (suponiendo que usas toast.js normalizado en tu frontend)
    response.headers["HX-Trigger"] = json.dumps({
        "showMessage": {
            "type": "success",
            "message": "Comentario enviado exitosamente"
        }
    })
    
    return response

