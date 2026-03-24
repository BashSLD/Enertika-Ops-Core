"""
Router del Modulo Proyectos
Vista global de todos los proyectos con filtros por area y estatus.
"""
from fastapi import APIRouter, Request, Depends, Query, HTTPException, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from uuid import UUID
from typing import Optional, List
from core.config import settings
import logging

logger = logging.getLogger("Proyectos.Router")

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
        "user_name": context.get("user_name"),
        "role": context.get("role"),
        "module_roles": context.get("module_roles", {}),
        "current_module_role": context.get("module_roles", {}).get("proyectos", "viewer"),
        "kpis": kpis,
        "proyectos": proyectos,
        "area": None,
        "vista_global": True,
    }

    # HX-History-Restore-Request: HTMX lo envía al restaurar historial (Back/Forward) — retornar full page
    if request.headers.get("hx-request") and not request.headers.get("hx-history-restore-request"):
        return templates.TemplateResponse(request, "proyectos/partials/content.html", template_data)
    return templates.TemplateResponse(request, "proyectos/dashboard.html", template_data)


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

    return templates.TemplateResponse(request, "shared/partials/lista_proyectos.html", {"proyectos": proyectos,
        "area": area,
        "current_module_role": context.get("module_roles", {}).get("proyectos", "viewer"),
        "vista_global": True,
    })


@router.get("/partials/visita-obra-modal", include_in_schema=False)
async def get_visita_obra_modal(
    request: Request,
    context=Depends(get_current_user_context),
    _=require_module_access("proyectos"),
):
    return templates.TemplateResponse(request, "proyectos/partials/visita_obra_modal.html", {"user_name": context.get("user_name"),
    })


def _equipo_template_data(request, id_proyecto, data, permisos, guardado=False):
    return {
        "id_proyecto": str(id_proyecto),
        "asignaciones": data["asignaciones"],
        "jefe_ingenieria": data["jefe_ingenieria"],
        "jefe_construccion": data["jefe_construccion"],
        "usuarios_ingenieria": data["usuarios_ingenieria"],
        "usuarios_construccion": data["usuarios_construccion"],
        "usuarios_oym": data["usuarios_oym"],
        "roles_equipo": [r for r in [
            {"rol": "ingeniero_asignado", "area": "INGENIERIA"},
            {"rol": "coordinador_obra",   "area": "CONSTRUCCION"},
            {"rol": "encargado",          "area": "OYM"},
        ]],
        **permisos,
        "guardado": guardado,
    }


@router.get("/partials/equipo/{id_proyecto}", include_in_schema=False)
async def get_equipo_partial(
    request: Request,
    id_proyecto: UUID,
    context=Depends(get_current_user_context),
    _=require_module_access("proyectos"),
    conn=Depends(get_db_connection),
    service: ProyectosService = Depends(get_service),
):
    data = await service.get_equipo_proyecto(conn, id_proyecto)
    permisos = service.permisos_equipo(context)

    return templates.TemplateResponse(request, 
        "proyectos/partials/equipo_modal.html",
        _equipo_template_data(request, id_proyecto, data, permisos),
    )


@router.post("/equipo/{id_proyecto}", include_in_schema=False)
async def save_equipo(
    request: Request,
    id_proyecto: UUID,
    context=Depends(get_current_user_context),
    _=require_module_access("proyectos"),
    conn=Depends(get_db_connection),
    service: ProyectosService = Depends(get_service),
):
    permisos = service.permisos_equipo(context)
    if not any([permisos["puede_asignar_ingenieria"], permisos["puede_asignar_construccion"], permisos["puede_asignar_oym"]]):
        raise HTTPException(status_code=403, detail="Sin permisos para editar el equipo")

    form = await request.form()
    asignaciones = []
    n = 0
    while True:
        rol = form.get(f"rol_{n}_rol")
        if rol is None:
            break
        area = form.get(f"rol_{n}_area", "")
        usuario_str = form.get(f"rol_{n}_usuario", "")
        asignaciones.append({
            "rol_proyecto": rol,
            "area": area,
            "id_usuario": UUID(usuario_str) if usuario_str else None,
        })
        n += 1

    user_db_id = context.get("user_db_id")
    if not user_db_id:
        raise HTTPException(status_code=401, detail="Usuario no autenticado")

    try:
        await service.save_equipo_proyecto(conn, id_proyecto, asignaciones, user_db_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    data = await service.get_equipo_proyecto(conn, id_proyecto)
    return templates.TemplateResponse(request, 
        "proyectos/partials/equipo_modal.html",
        _equipo_template_data(request, id_proyecto, data, permisos, guardado=True),
    )


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

    return templates.TemplateResponse(request, "shared/partials/timeline_proyecto.html", {"historial": historial,
        "proyecto": proyecto,
    })
