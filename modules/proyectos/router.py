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
import asyncpg
import logging

logger = logging.getLogger("Proyectos.Router")

from core.security import get_current_user_context
from core.permissions import require_module_access
from core.database import get_db_connection
from .service import ProyectosService, get_service
from core.projects.router import check_puede_crear_proyecto

templates = Jinja2Templates(directory="templates")
templates.env.globals["DEBUG_MODE"] = settings.DEBUG_MODE

from core.jinja_filters import register_timezone_filters
register_timezone_filters(templates.env)

router = APIRouter(
    prefix="/proyectos",
    tags=["Modulo Proyectos"],
)


def _separar_proyectos_globales(proyectos):
    return {
        "proyectos_activos": [
            p for p in proyectos if p.get("area_actual") != "OYM"
        ],
        "proyectos_terminados": [
            p for p in proyectos if p.get("area_actual") == "OYM"
        ],
    }


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
    proyectos_split = _separar_proyectos_globales(proyectos)
    puede_crear_proyecto = check_puede_crear_proyecto(context)

    template_data = {
        "user_name": context.get("user_name"),
        "role": context.get("role"),
        "module_roles": context.get("module_roles", {}),
        "current_module_role": context.get("module_roles", {}).get("proyectos", "viewer"),
        "kpis": kpis,
        "proyectos": proyectos,
        **proyectos_split,
        "area": None,
        "vista_global": True,
        "puede_crear_proyecto": puede_crear_proyecto,
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
    proyectos_split = _separar_proyectos_globales(proyectos)

    return templates.TemplateResponse(request, "shared/partials/lista_proyectos.html", {"proyectos": proyectos,
        **proyectos_split,
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
    return templates.TemplateResponse(request, "shared/modals/visita_obra_modal.html", {"user_name": context.get("user_name"),
    })


def _equipo_template_data(request, id_proyecto, data, permisos, guardado=False):
    return {
        "id_proyecto": str(id_proyecto),
        "asignaciones": data["asignaciones"],
        "jefe_ingenieria": data["jefe_ingenieria"],
        "jefe_construccion": data["jefe_construccion"],
        "jefes_ingenieria": data["jefes_ingenieria"],
        "jefes_construccion": data["jefes_construccion"],
        "usuarios_ingenieria": data["usuarios_ingenieria"],
        "usuarios_construccion": data["usuarios_construccion"],
        "usuarios_oym": data["usuarios_oym"],
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
    permisos = await service.permisos_equipo(conn, context, id_proyecto)

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
    permisos = await service.permisos_equipo(conn, context, id_proyecto)
    if not any([permisos["puede_asignar_ingenieria"], permisos["puede_asignar_construccion"], permisos["puede_asignar_oym"]]):
        raise HTTPException(status_code=403, detail="Sin permisos para editar el equipo")

    user_db_id = context.get("user_db_id")

    try:
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

        responsables_explicitos = {}
        for area in ("INGENIERIA", "CONSTRUCCION"):
            val = form.get(f"responsable_{area.lower()}")
            if val:
                responsables_explicitos[area] = UUID(val)

        await service.save_equipo_proyecto(
            conn, id_proyecto, asignaciones, user_db_id, permisos,
            context=context, responsables_explicitos=responsables_explicitos,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except asyncpg.PostgresError:
        logger.exception("Error de BD al guardar equipo de proyecto")
        raise HTTPException(status_code=500, detail="Error interno al guardar el equipo")

    data = await service.get_equipo_proyecto(conn, id_proyecto)
    return templates.TemplateResponse(request,
        "proyectos/partials/equipo_modal.html",
        _equipo_template_data(request, id_proyecto, data, permisos, guardado=True),
    )


@router.post("/equipo/{id_proyecto}/responsable", include_in_schema=False)
async def reasignar_responsable(
    request: Request,
    id_proyecto: UUID,
    context=Depends(get_current_user_context),
    _=require_module_access("proyectos"),
    conn=Depends(get_db_connection),
    service: ProyectosService = Depends(get_service),
):
    permisos = await service.permisos_equipo(conn, context, id_proyecto)
    if not permisos["puede_reasignar_responsable"]:
        raise HTTPException(status_code=403, detail="Solo Direccion puede reasignar al responsable")

    user_db_id = context.get("user_db_id")
    try:
        form = await request.form()
        area = form.get("area", "")
        nuevo = form.get("id_usuario", "")
        await service.reasignar_responsable(
            conn, id_proyecto, area, UUID(nuevo) if nuevo else None, user_db_id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except asyncpg.PostgresError:
        logger.exception("Error de BD al reasignar responsable")
        raise HTTPException(status_code=500, detail="Error interno al reasignar")

    data = await service.get_equipo_proyecto(conn, id_proyecto)
    return templates.TemplateResponse(
        request, "proyectos/partials/equipo_modal.html",
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
