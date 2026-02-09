"""
Router compartido de traspasos de proyectos.
Endpoints usados por todos los modulos (Ingenieria, Construccion, OyM, Proyectos).
"""
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.templating import Jinja2Templates
from uuid import UUID
import asyncpg
import logging

from core.database import get_db_connection
from core.security import get_current_user_context
from core.config import settings
from .service import TransferService, get_transfer_service
from .schemas import TraspasoEnviar, TraspasoRechazar

logger = logging.getLogger("TransfersRouter")

templates = Jinja2Templates(directory="templates")
templates.env.globals["DEBUG_MODE"] = settings.DEBUG_MODE

from core.jinja_filters import register_timezone_filters
register_timezone_filters(templates.env)

router = APIRouter(
    prefix="/transfers",
    tags=["Traspasos de Proyectos"],
)


@router.get("/checklist/{area_origen}/{area_destino}", include_in_schema=False)
async def get_checklist(
    request: Request,
    area_origen: str,
    area_destino: str,
    id_proyecto: UUID = None,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: TransferService = Depends(get_transfer_service),
):
    docs = await service.get_documentos_checklist(conn, area_origen.upper(), area_destino.upper())
    proyecto = None
    if id_proyecto:
        proyecto = await service.get_proyecto_detalle(conn, id_proyecto)

    return templates.TemplateResponse("shared/partials/modal_enviar_traspaso.html", {
        "request": request,
        "documentos": docs,
        "area_origen": area_origen.upper(),
        "area_destino": area_destino.upper(),
        "proyecto": proyecto,
        "id_proyecto": id_proyecto,
    })


@router.get("/motivos-rechazo/{area}", include_in_schema=False)
async def get_motivos_rechazo(
    request: Request,
    area: str,
    id_traspaso: UUID = None,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: TransferService = Depends(get_transfer_service),
):
    motivos = await service.get_motivos_rechazo(conn, area.upper())
    traspaso = None
    if id_traspaso:
        traspaso = await service.db.get_traspaso_by_id(conn, id_traspaso)

    return templates.TemplateResponse("shared/partials/modal_rechazar_traspaso.html", {
        "request": request,
        "motivos": motivos,
        "area": area.upper(),
        "traspaso": traspaso,
        "id_traspaso": id_traspaso,
    })


@router.get("/timeline/{id_proyecto}", include_in_schema=False)
async def get_timeline(
    request: Request,
    id_proyecto: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: TransferService = Depends(get_transfer_service),
):
    historial = await service.get_historial_traspasos(conn, id_proyecto)
    proyecto = await service.get_proyecto_detalle(conn, id_proyecto)

    return templates.TemplateResponse("shared/partials/timeline_proyecto.html", {
        "request": request,
        "historial": historial,
        "proyecto": proyecto,
    })


@router.post("/enviar", include_in_schema=False)
async def enviar_traspaso(
    request: Request,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: TransferService = Depends(get_transfer_service),
):
    form = await request.form()
    id_proyecto = UUID(form.get("id_proyecto"))
    area_origen = form.get("area_origen", "").upper()
    area_destino = form.get("area_destino", "").upper()
    comentario = form.get("comentario", "").strip() or None

    docs_ids = [int(v) for k, v in form.multi_items() if k == "documentos_verificados"]

    user_id = context.get("user_id")
    user_name = context.get("user_name", "Sistema")

    try:
        await service.enviar_traspaso(
            conn, id_proyecto, area_origen, area_destino,
            user_id, user_name, comentario, docs_ids
        )

        module_slug = {
            "INGENIERIA": "ingenieria",
            "CONSTRUCCION": "construccion",
        }.get(area_origen, "proyectos")

        return templates.TemplateResponse("shared/toast.html", {
            "request": request,
            "message": f"Traspaso enviado exitosamente a {area_destino}",
            "type": "success",
            "redirect_url": f"/{module_slug}/ui",
        })

    except ValueError as e:
        return templates.TemplateResponse("shared/toast.html", {
            "request": request,
            "message": str(e),
            "type": "error",
        })
    except asyncpg.PostgresError:
        logger.exception("Error de BD al enviar traspaso")
        return templates.TemplateResponse("shared/toast.html", {
            "request": request,
            "message": "Error interno al procesar el traspaso",
            "type": "error",
        })


@router.post("/recibir/{id_traspaso}", include_in_schema=False)
async def recibir_traspaso(
    request: Request,
    id_traspaso: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: TransferService = Depends(get_transfer_service),
):
    user_id = context.get("user_id")
    user_name = context.get("user_name", "Sistema")

    try:
        traspaso = await service.recibir_traspaso(
            conn, id_traspaso, user_id, user_name
        )

        module_slug = {
            "CONSTRUCCION": "construccion",
            "OYM": "oym",
        }.get(traspaso.get('area_destino', ''), "proyectos")

        return templates.TemplateResponse("shared/toast.html", {
            "request": request,
            "message": "Traspaso aceptado exitosamente",
            "type": "success",
            "redirect_url": f"/{module_slug}/ui",
        })

    except ValueError as e:
        return templates.TemplateResponse("shared/toast.html", {
            "request": request,
            "message": str(e),
            "type": "error",
        })
    except asyncpg.PostgresError:
        logger.exception("Error de BD al aceptar traspaso")
        return templates.TemplateResponse("shared/toast.html", {
            "request": request,
            "message": "Error interno al procesar la recepcion",
            "type": "error",
        })


@router.post("/rechazar/{id_traspaso}", include_in_schema=False)
async def rechazar_traspaso(
    request: Request,
    id_traspaso: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: TransferService = Depends(get_transfer_service),
):
    form = await request.form()
    comentario = form.get("comentario", "").strip() or None
    motivos_ids = [int(v) for k, v in form.multi_items() if k == "motivos"]

    user_id = context.get("user_id")
    user_name = context.get("user_name", "Sistema")

    try:
        traspaso = await service.rechazar_traspaso(
            conn, id_traspaso, user_id, user_name, motivos_ids, comentario
        )

        module_slug = {
            "CONSTRUCCION": "construccion",
            "OYM": "oym",
        }.get(traspaso.get('area_destino', ''), "proyectos")

        return templates.TemplateResponse("shared/toast.html", {
            "request": request,
            "message": "Traspaso rechazado. Se notificara al area de origen.",
            "type": "warning",
            "redirect_url": f"/{module_slug}/ui",
        })

    except ValueError as e:
        return templates.TemplateResponse("shared/toast.html", {
            "request": request,
            "message": str(e),
            "type": "error",
        })
    except asyncpg.PostgresError:
        logger.exception("Error de BD al rechazar traspaso")
        return templates.TemplateResponse("shared/toast.html", {
            "request": request,
            "message": "Error interno al procesar el rechazo",
            "type": "error",
        })
