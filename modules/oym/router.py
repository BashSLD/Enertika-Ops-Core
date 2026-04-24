"""
Router del Modulo O&M (Operacion y Mantenimiento)
Recibe proyectos de Construccion. Destino final del flujo de traspasos.
"""
from fastapi import APIRouter, Request, Depends, Query
from fastapi.templating import Jinja2Templates
from uuid import UUID
from typing import Optional
from core.config import settings
from core.timezone import today_mx

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
    tab: Optional[str] = Query(None),
    context=Depends(get_current_user_context),
    _=require_module_access("oym"),
    conn=Depends(get_db_connection),
    service: OyMService = Depends(get_service),
):
    from modules.calculadora_polizas.db_service import CalculadoraDBService
    _cal_db = CalculadoraDBService()

    kpis = await service.get_kpis(conn)
    proyectos = await service.get_proyectos(conn)
    pendientes = await service.get_pendientes_recepcion(conn)

    # Badge del tab Plantas: contar pólizas que vencen en ≤30 días
    _plantas = await _cal_db.get_plantas_list(conn)
    _vence_pron = sum(
        1 for p in _plantas
        if p.get("poliza_vigente_id")
        and p.get("poliza_vigente_dias") is not None
        and 0 < p["poliza_vigente_dias"] <= 30
    )
    resumen_plantas = {"vence_pron": _vence_pron}

    mod_role = context.get("module_roles", {}).get("oym", "viewer")
    is_admin = context.get("role") == "ADMIN"
    active_tab = tab if tab in ("proyectos", "polizas", "incidencias", "plantas") else "proyectos"

    template_data = {
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
        "puede_editar": mod_role in ("editor", "admin") or is_admin,
        "active_tab": active_tab,
        "resumen_plantas": resumen_plantas,
    }

    # HX-History-Restore-Request: HTMX lo envía al restaurar historial (Back/Forward) — retornar full page
    if request.headers.get("hx-request") and not request.headers.get("hx-history-restore-request"):
        return templates.TemplateResponse(request, "oym/partials/content.html", template_data)
    return templates.TemplateResponse(request, "oym/dashboard.html", template_data)


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

    return templates.TemplateResponse(request, "shared/partials/lista_proyectos.html", {"proyectos": proyectos,
        "pendientes": pendientes,
        "area": "OYM",
        "current_module_role": mod_role,
        "puede_recibir": mod_role in ("editor", "admin") or context.get("role") == "ADMIN",
    })


@router.get("/partials/incidencias-kanban", include_in_schema=False)
async def get_incidencias_kanban(
    request: Request,
    context=Depends(get_current_user_context),
    _=require_module_access("oym"),
    conn=Depends(get_db_connection),
):
    """Esqueleto del Kanban de Incidencias O&M."""
    from modules.calculadora_polizas.db_service import CalculadoraDBService

    mod_role = context.get("module_roles", {}).get("oym", "viewer")
    is_admin = context.get("role") == "ADMIN"
    db = CalculadoraDBService()
    plantas = await db.get_plantas_list(conn)

    resumen_zonas = {
        "zona_1": sum(1 for p in plantas if p.get("zona_incidencia") == "Zona 1"),
        "zona_2": sum(1 for p in plantas if p.get("zona_incidencia") == "Zona 2"),
        "sin_asignar": sum(1 for p in plantas if p.get("zona_incidencia") not in ("Zona 1", "Zona 2")),
    }

    return templates.TemplateResponse(
        request, "oym/partials/incidencias_kanban.html",
        {
            "puede_editar": mod_role in ("editor", "admin") or is_admin,
            "resumen_zonas": resumen_zonas,
        },
    )


@router.get("/partials/plantas-portfolio", include_in_schema=False)
async def get_plantas_portfolio(
    request: Request,
    filtro: str = Query("todas"),
    context=Depends(get_current_user_context),
    _=require_module_access("oym"),
    conn=Depends(get_db_connection),
):
    from modules.calculadora_polizas.db_service import CalculadoraDBService
    db = CalculadoraDBService()
    todas = await db.get_plantas_list(conn)

    mod_role = context.get("module_roles", {}).get("oym", "viewer")
    is_admin = context.get("role") == "ADMIN"
    puede_editar = mod_role in ("editor", "admin") or is_admin

    def _dias(p):
        return p.get("poliza_vigente_dias")

    activas    = [p for p in todas if p.get("poliza_vigente_id") and (_dias(p) is None or _dias(p) > 30)]
    vence_pron = [p for p in todas if p.get("poliza_vigente_id") and _dias(p) is not None and 0 < _dias(p) <= 30]
    vencidas   = [p for p in todas if p.get("poliza_vigente_id") and _dias(p) is not None and _dias(p) <= 0]
    sin_poliza = [p for p in todas if not p.get("poliza_vigente_id") and not p.get("poliza_proxima_id")]

    resumen = {
        "activas":    len(activas),
        "vence_pron": len(vence_pron),
        "vencidas":   len(vencidas),
        "sin_poliza": len(sin_poliza),
    }

    filtro_map = {
        "activas":    activas,
        "vence_pron": vence_pron,
        "vencidas":   vencidas,
        "sin_poliza": sin_poliza,
    }
    plantas = filtro_map.get(filtro, todas)

    # Ordenar por urgencia: vencidas → vence pronto (días asc) → activas → sin póliza
    def _sort_key(p):
        d = _dias(p)
        if d is not None and d <= 0:        return (0, d)
        if d is not None and d <= 30:       return (1, d)
        if p.get("poliza_vigente_id"):      return (2, d or 999999)
        if p.get("poliza_proxima_id"):      return (3, 0)
        return (4, 0)

    plantas = sorted(plantas, key=_sort_key)

    return templates.TemplateResponse(
        request, "oym/partials/plantas_portfolio.html",
        {
            "plantas": plantas,
            "resumen": resumen,
            "filtro": filtro,
            "today": today_mx(),
            "puede_editar": puede_editar,
        },
    )


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

    return templates.TemplateResponse(request, "shared/partials/modal_recibir_traspaso.html", {"traspaso": traspaso,
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

    return templates.TemplateResponse(request, "shared/partials/modal_rechazar_traspaso.html", {"motivos": motivos,
        "traspaso": traspaso,
        "id_traspaso": id_traspaso,
        "area": "OYM",
    })
