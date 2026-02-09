"""
Router del Modulo Construccion
Recibe proyectos de Ingenieria, gestiona obra y envia a OyM.
"""
from fastapi import APIRouter, Request, Depends, Query
from fastapi.templating import Jinja2Templates
from uuid import UUID
from typing import Optional
from core.config import settings

from core.security import get_current_user_context
from core.permissions import require_module_access
from core.database import get_db_connection
from .service import ConstruccionService, get_service

templates = Jinja2Templates(directory="templates")
templates.env.globals["DEBUG_MODE"] = settings.DEBUG_MODE

from core.jinja_filters import register_timezone_filters
register_timezone_filters(templates.env)

router = APIRouter(
    prefix="/construccion",
    tags=["Modulo Construccion"],
)


@router.api_route("/ui", methods=["GET", "HEAD"], include_in_schema=False)
async def get_construccion_ui(
    request: Request,
    context=Depends(get_current_user_context),
    _=require_module_access("construccion"),
    conn=Depends(get_db_connection),
    service: ConstruccionService = Depends(get_service),
):
    kpis = await service.get_kpis(conn)
    proyectos = await service.get_proyectos(conn)
    pendientes = await service.get_pendientes_recepcion(conn)

    mod_role = context.get("module_roles", {}).get("construccion", "viewer")
    is_admin = context.get("role") == "ADMIN"

    template_data = {
        "request": request,
        "user_name": context.get("user_name"),
        "role": context.get("role"),
        "module_roles": context.get("module_roles", {}),
        "current_module_role": mod_role,
        "kpis": kpis,
        "proyectos": proyectos,
        "pendientes": pendientes,
        "area": "CONSTRUCCION",
        "area_origen": "INGENIERIA",
        "area_destino": "OYM",
        "puede_enviar": mod_role in ("editor", "admin") or is_admin,
        "puede_recibir": mod_role in ("editor", "admin") or is_admin,
    }

    if request.headers.get("hx-request"):
        return templates.TemplateResponse("construccion/partials/content.html", template_data)
    return templates.TemplateResponse("construccion/dashboard.html", template_data)


@router.get("/partials/proyectos", include_in_schema=False)
async def get_proyectos_partial(
    request: Request,
    q: Optional[str] = Query(None),
    limit: int = Query(50),
    context=Depends(get_current_user_context),
    _=require_module_access("construccion"),
    conn=Depends(get_db_connection),
    service: ConstruccionService = Depends(get_service),
):
    proyectos = await service.get_proyectos(conn, q, limit)
    pendientes = await service.get_pendientes_recepcion(conn)
    mod_role = context.get("module_roles", {}).get("construccion", "viewer")

    return templates.TemplateResponse("shared/partials/lista_proyectos.html", {
        "request": request,
        "proyectos": proyectos,
        "pendientes": pendientes,
        "area": "CONSTRUCCION",
        "area_destino": "OYM",
        "current_module_role": mod_role,
        "puede_enviar": mod_role in ("editor", "admin") or context.get("role") == "ADMIN",
        "puede_recibir": mod_role in ("editor", "admin") or context.get("role") == "ADMIN",
    })


@router.get("/modal/recibir/{id_traspaso}", include_in_schema=False)
async def modal_recibir(
    request: Request,
    id_traspaso: UUID,
    context=Depends(get_current_user_context),
    _=require_module_access("construccion", "editor"),
    conn=Depends(get_db_connection),
    service: ConstruccionService = Depends(get_service),
):
    traspaso = await service.transfers.db.get_traspaso_by_id(conn, id_traspaso)

    return templates.TemplateResponse("shared/partials/modal_recibir_traspaso.html", {
        "request": request,
        "traspaso": traspaso,
        "id_traspaso": id_traspaso,
        "area": "CONSTRUCCION",
    })


@router.get("/modal/rechazar/{id_traspaso}", include_in_schema=False)
async def modal_rechazar(
    request: Request,
    id_traspaso: UUID,
    context=Depends(get_current_user_context),
    _=require_module_access("construccion", "editor"),
    conn=Depends(get_db_connection),
    service: ConstruccionService = Depends(get_service),
):
    motivos = await service.get_motivos_rechazo(conn)
    traspaso = await service.transfers.db.get_traspaso_by_id(conn, id_traspaso)

    return templates.TemplateResponse("shared/partials/modal_rechazar_traspaso.html", {
        "request": request,
        "motivos": motivos,
        "traspaso": traspaso,
        "id_traspaso": id_traspaso,
        "area": "CONSTRUCCION",
    })


@router.get("/modal/enviar/{id_proyecto}", include_in_schema=False)
async def modal_enviar(
    request: Request,
    id_proyecto: UUID,
    context=Depends(get_current_user_context),
    _=require_module_access("construccion", "editor"),
    conn=Depends(get_db_connection),
    service: ConstruccionService = Depends(get_service),
):
    proyecto = await service.get_proyecto_detalle(conn, id_proyecto)
    docs = await service.get_checklist_envio(conn)

    return templates.TemplateResponse("shared/partials/modal_enviar_traspaso.html", {
        "request": request,
        "proyecto": proyecto,
        "documentos": docs,
        "area_origen": "CONSTRUCCION",
        "area_destino": "OYM",
        "id_proyecto": id_proyecto,
    })
