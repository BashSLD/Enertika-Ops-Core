"""
Router del Modulo Ingenieria
Muestra proyectos en fase INGENIERIA y permite enviar a Construccion.
"""
from fastapi import APIRouter, Request, Depends, Query
from fastapi.templating import Jinja2Templates
from uuid import UUID
from typing import Optional
from core.config import settings

from core.security import get_current_user_context
from core.permissions import require_module_access
from core.database import get_db_connection
from .service import IngenieriaService, get_service

templates = Jinja2Templates(directory="templates")
templates.env.globals["DEBUG_MODE"] = settings.DEBUG_MODE

from core.jinja_filters import register_timezone_filters
register_timezone_filters(templates.env)

router = APIRouter(
    prefix="/ingenieria",
    tags=["Modulo Ingenieria"],
)


@router.api_route("/ui", methods=["GET", "HEAD"], include_in_schema=False)
async def get_ingenieria_ui(
    request: Request,
    context=Depends(get_current_user_context),
    _=require_module_access("ingenieria"),
    conn=Depends(get_db_connection),
    service: IngenieriaService = Depends(get_service),
):
    kpis = await service.get_kpis(conn)
    proyectos = await service.get_proyectos(conn)

    mod_role = context.get("module_roles", {}).get("ingenieria", "viewer")
    is_admin = context.get("role") == "ADMIN"

    template_data = {
        "request": request,
        "user_name": context.get("user_name"),
        "role": context.get("role"),
        "module_roles": context.get("module_roles", {}),
        "current_module_role": mod_role,
        "kpis": kpis,
        "proyectos": proyectos,
        "area": "INGENIERIA",
        "area_destino": "CONSTRUCCION",
        "puede_enviar": mod_role in ("editor", "admin") or is_admin,
    }

    if request.headers.get("hx-request"):
        return templates.TemplateResponse("ingenieria/partials/content.html", template_data)
    return templates.TemplateResponse("ingenieria/dashboard.html", template_data)


@router.get("/partials/proyectos", include_in_schema=False)
async def get_proyectos_partial(
    request: Request,
    q: Optional[str] = Query(None),
    limit: int = Query(50),
    context=Depends(get_current_user_context),
    _=require_module_access("ingenieria"),
    conn=Depends(get_db_connection),
    service: IngenieriaService = Depends(get_service),
):
    proyectos = await service.get_proyectos(conn, q, limit)
    return templates.TemplateResponse("shared/partials/lista_proyectos.html", {
        "request": request,
        "proyectos": proyectos,
        "area": "INGENIERIA",
        "area_destino": "CONSTRUCCION",
        "current_module_role": context.get("module_roles", {}).get("ingenieria", "viewer"),
        "puede_enviar": context.get("module_roles", {}).get("ingenieria", "viewer") in ("editor", "admin") or context.get("role") == "ADMIN",
    })


@router.get("/modal/enviar/{id_proyecto}", include_in_schema=False)
async def modal_enviar(
    request: Request,
    id_proyecto: UUID,
    context=Depends(get_current_user_context),
    _=require_module_access("ingenieria", "editor"),
    conn=Depends(get_db_connection),
    service: IngenieriaService = Depends(get_service),
):
    proyecto = await service.get_proyecto_detalle(conn, id_proyecto)
    docs = await service.get_checklist_envio(conn)

    return templates.TemplateResponse("shared/partials/modal_enviar_traspaso.html", {
        "request": request,
        "proyecto": proyecto,
        "documentos": docs,
        "area_origen": "INGENIERIA",
        "area_destino": "CONSTRUCCION",
        "id_proyecto": id_proyecto,
    })
