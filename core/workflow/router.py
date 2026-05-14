"""
Router centralizado de comentarios y detalle de oportunidades.

El router solo recibe HTTP, valida errores esperados y renderiza templates.
La logica de negocio vive en WorkflowService y el SQL en WorkflowDBService.
"""

import json
import logging
from typing import List, Optional
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.templating import Jinja2Templates

from core.database import get_db_connection
from core.jinja_filters import register_timezone_filters
from core.security import get_current_user_context, get_valid_graph_token
from core.workflow.service import get_workflow_service

logger = logging.getLogger("SharedComments")
templates = Jinja2Templates(directory="templates")
register_timezone_filters(templates.env)

router = APIRouter(
    prefix="/workflow",
    tags=["Workflow - Comentarios Centralizados"],
)


@router.get("/modals/comentarios")
async def get_comentarios_modal(
    request: Request,
    id_oportunidad: UUID,
    module: str,
    workflow_service=Depends(get_workflow_service),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    """Renderiza el modal centralizado de comentarios."""
    logger.info(
        "[COMENTARIOS MODAL] Solicitado para oportunidad %s desde modulo %s",
        id_oportunidad,
        module,
    )

    try:
        template_context = await workflow_service.build_comentarios_modal_context(
            conn,
            id_oportunidad,
            module,
            context,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except asyncpg.PostgresError as exc:
        logger.exception("[COMENTARIOS MODAL] Error de base de datos")
        raise HTTPException(status_code=500, detail="Error al cargar comentarios") from exc

    return templates.TemplateResponse(
        request,
        "shared/modals/comentarios_modal.html",
        template_context,
    )


@router.post("/comentarios")
async def create_comentario_workflow(
    request: Request,
    id_oportunidad: UUID = Form(...),
    nuevo_comentario: str = Form(...),
    module: str = Form(...),
    file_uploads: Optional[List[UploadFile]] = File(None),
    workflow_service=Depends(get_workflow_service),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    """Crea un comentario desde cualquier modulo y devuelve el historial actualizado."""
    logger.info(
        "[CREATE COMENTARIO] Modulo: %s, Oportunidad: %s, Usuario: %s",
        module,
        id_oportunidad,
        context.get("user_name"),
    )

    sharepoint_token = None
    if file_uploads:
        sharepoint_token = await get_valid_graph_token(request)
        if not sharepoint_token:
            logger.warning("[CREATE COMENTARIO] Token expirado al intentar subir archivo")

    try:
        comentarios = await workflow_service.create_comentario_and_get_historial(
            conn,
            context,
            id_oportunidad,
            nuevo_comentario,
            module,
            file_uploads=file_uploads,
            sharepoint_token=sharepoint_token,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except asyncpg.PostgresError as exc:
        logger.exception("[CREATE COMENTARIO] Error de base de datos")
        raise HTTPException(status_code=500, detail="Error al guardar comentario") from exc

    response = templates.TemplateResponse(
        request,
        "shared/partials/comentarios_list.html",
        {
            "comentarios": comentarios,
            "mode": None,
            "has_more": False,
            "total_extra": 0,
            "id_oportunidad": id_oportunidad,
        },
    )

    response.headers["HX-Trigger"] = json.dumps({
        "showMessage": {
            "type": "success",
            "message": "Comentario enviado exitosamente",
        }
    })
    return response


@router.get("/modals/detalle/{id_oportunidad}")
async def get_detalle_oportunidad_modal(
    request: Request,
    id_oportunidad: UUID,
    source_module: str = Query(default="comercial"),
    workflow_service=Depends(get_workflow_service),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    """Renderiza el modal de detalle de oportunidad."""
    try:
        template_context = await workflow_service.build_detalle_oportunidad_context(
            conn,
            id_oportunidad,
            source_module,
            context,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except asyncpg.PostgresError as exc:
        logger.exception("[DETALLE OPORTUNIDAD] Error de base de datos")
        raise HTTPException(status_code=500, detail="Error al cargar detalle") from exc

    return templates.TemplateResponse(
        request,
        "shared/modals/detalle_oportunidad_modal.html",
        template_context,
    )
