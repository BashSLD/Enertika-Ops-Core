"""
Router del Modulo O&M (Operacion y Mantenimiento)
Recibe proyectos de Construccion. Destino final del flujo de traspasos.
"""
from fastapi import APIRouter, Request, Depends, Query
from fastapi.templating import Jinja2Templates
from uuid import UUID
from typing import Optional
from core.config import settings

from core.security import get_current_user_context
from core.permissions import require_module_access
from core.database import get_db_connection
from .service import OyMService, get_service

templates = Jinja2Templates(directory="templates")
templates.env.globals["DEBUG_MODE"] = settings.DEBUG_MODE

from core.jinja_filters import register_timezone_filters
register_timezone_filters(templates.env)

router = APIRouter(
    prefix="/oym",
    tags=["Modulo O&M"],
)


@router.api_route("/ui", methods=["GET", "HEAD"], include_in_schema=False)
async def get_oym_ui(
    request: Request,
    context=Depends(get_current_user_context),
    _=require_module_access("oym"),
    conn=Depends(get_db_connection),
    service: OyMService = Depends(get_service),
):
    kpis = await service.get_kpis(conn)
    proyectos = await service.get_proyectos(conn)
    pendientes = await service.get_pendientes_recepcion(conn)

    mod_role = context.get("module_roles", {}).get("oym", "viewer")
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
        "area": "OYM",
        "area_origen": "CONSTRUCCION",
        "puede_recibir": mod_role in ("editor", "admin") or is_admin,
    }

    if request.headers.get("hx-request"):
        return templates.TemplateResponse("oym/partials/content.html", template_data)
    return templates.TemplateResponse("oym/dashboard.html", template_data)


@router.get("/partials/proyectos", include_in_schema=False)
async def get_proyectos_partial(
    request: Request,
    q: Optional[str] = Query(None),
    limit: int = Query(50),
    context=Depends(get_current_user_context),
    _=require_module_access("oym"),
    conn=Depends(get_db_connection),
    service: OyMService = Depends(get_service),
):
    proyectos = await service.get_proyectos(conn, q, limit)
    pendientes = await service.get_pendientes_recepcion(conn)
    mod_role = context.get("module_roles", {}).get("oym", "viewer")

    return templates.TemplateResponse("shared/partials/lista_proyectos.html", {
        "request": request,
        "proyectos": proyectos,
        "pendientes": pendientes,
        "area": "OYM",
        "current_module_role": mod_role,
        "puede_recibir": mod_role in ("editor", "admin") or context.get("role") == "ADMIN",
    })


@router.get("/modal/recibir/{id_traspaso}", include_in_schema=False)
async def modal_recibir(
    request: Request,
    id_traspaso: UUID,
    context=Depends(get_current_user_context),
    _=require_module_access("oym", "editor"),
    conn=Depends(get_db_connection),
    service: OyMService = Depends(get_service),
):
    traspaso = await service.transfers.db.get_traspaso_by_id(conn, id_traspaso)

    return templates.TemplateResponse("shared/partials/modal_recibir_traspaso.html", {
        "request": request,
        "traspaso": traspaso,
        "id_traspaso": id_traspaso,
        "area": "OYM",
    })


@router.get("/modal/rechazar/{id_traspaso}", include_in_schema=False)
async def modal_rechazar(
    request: Request,
    id_traspaso: UUID,
    context=Depends(get_current_user_context),
    _=require_module_access("oym", "editor"),
    conn=Depends(get_db_connection),
    service: OyMService = Depends(get_service),
):
    motivos = await service.get_motivos_rechazo(conn)
    traspaso = await service.transfers.db.get_traspaso_by_id(conn, id_traspaso)

    return templates.TemplateResponse("shared/partials/modal_rechazar_traspaso.html", {
        "request": request,
        "motivos": motivos,
        "traspaso": traspaso,
        "id_traspaso": id_traspaso,
        "area": "OYM",
    })
