"""
Router del Modulo Proyectos
Vista global de todos los proyectos con filtros por area y estatus.
"""
from fastapi import APIRouter, Request, Depends, Query
from fastapi.templating import Jinja2Templates
from uuid import UUID
from typing import Optional
from core.config import settings

from core.security import get_current_user_context
from core.permissions import require_module_access
from core.database import get_db_connection
from .service import ProyectosService, get_service

templates = Jinja2Templates(directory="templates")
templates.env.globals["DEBUG_MODE"] = settings.DEBUG_MODE

from core.jinja_filters import register_timezone_filters
register_timezone_filters(templates.env)

router = APIRouter(
    prefix="/proyectos",
    tags=["Modulo Proyectos"],
)


@router.api_route("/ui", methods=["GET", "HEAD"], include_in_schema=False)
async def get_proyectos_ui(
    request: Request,
    context=Depends(get_current_user_context),
    _=require_module_access("proyectos"),
    conn=Depends(get_db_connection),
    service: ProyectosService = Depends(get_service),
):
    kpis = await service.get_kpis(conn)
    proyectos = await service.get_proyectos(conn)

    template_data = {
        "request": request,
        "user_name": context.get("user_name"),
        "role": context.get("role"),
        "module_roles": context.get("module_roles", {}),
        "current_module_role": context.get("module_roles", {}).get("proyectos", "viewer"),
        "kpis": kpis,
        "proyectos": proyectos,
        "area": None,
        "vista_global": True,
    }

    if request.headers.get("hx-request"):
        return templates.TemplateResponse("proyectos/partials/content.html", template_data)
    return templates.TemplateResponse("proyectos/dashboard.html", template_data)


@router.get("/partials/proyectos", include_in_schema=False)
async def get_proyectos_partial(
    request: Request,
    area: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(50),
    context=Depends(get_current_user_context),
    _=require_module_access("proyectos"),
    conn=Depends(get_db_connection),
    service: ProyectosService = Depends(get_service),
):
    proyectos = await service.get_proyectos(conn, area, status, q, limit)

    return templates.TemplateResponse("shared/partials/lista_proyectos.html", {
        "request": request,
        "proyectos": proyectos,
        "area": area,
        "current_module_role": context.get("module_roles", {}).get("proyectos", "viewer"),
        "vista_global": True,
    })


@router.get("/partials/timeline/{id_proyecto}", include_in_schema=False)
async def get_timeline_partial(
    request: Request,
    id_proyecto: UUID,
    context=Depends(get_current_user_context),
    _=require_module_access("proyectos"),
    conn=Depends(get_db_connection),
    service: ProyectosService = Depends(get_service),
):
    historial = await service.get_historial(conn, id_proyecto)
    proyecto = await service.get_proyecto_detalle(conn, id_proyecto)

    return templates.TemplateResponse("shared/partials/timeline_proyecto.html", {
        "request": request,
        "historial": historial,
        "proyecto": proyecto,
    })
