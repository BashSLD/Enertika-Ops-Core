# ==============================================================
# modules/levantamientos/router_vistas.py
# Endpoints de vistas (lista e histórica y gráficas) para
# el módulo Levantamientos.
# Registrado en router_levantamientos_nuevos.py.
# ==============================================================

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates

from core.security import get_current_user_context
from core.permissions import require_module_access
from core.database import get_db_connection

from .db_service import get_db_service, LevantamientosDBService
from .db_service_analytics import get_analytics_db_service, LevantamientosAnalyticsDBService

logger = logging.getLogger("Levantamientos.Router.Vistas")

templates = Jinja2Templates(directory="templates")


def register_vistas_endpoints(router: APIRouter):
    """
    Registra los endpoints de las vistas lista y gráficas.
    """

    # ==============================================================
    # GET — VISTA LISTA HISTÓRICA (con tabs activos/terminados)
    # ==============================================================

    @router.get("/partials/lista", include_in_schema=False)
    async def get_lista_levantamientos(
        request: Request,
        tab: str = "activos",
        q: Optional[str] = None,
        estado: Optional[int] = None,
        tecnico_id: Optional[str] = None,
        fecha_inicio: Optional[str] = None,
        fecha_fin: Optional[str] = None,
        conn=Depends(get_db_connection),
        db_svc: LevantamientosDBService = Depends(get_db_service),
        context=Depends(get_current_user_context),
        _=require_module_access("levantamientos"),
    ):
        """
        Vista lista histórica del módulo levantamientos.
        Tabs: activos | terminados.
        Filtros: búsqueda texto, estado, técnico, rango fechas.
        """
        estatus_map = await db_svc.get_estatus_map(conn)
        estatus_list = await db_svc.get_estatus_list(conn)

        if tab == "terminados":
            ids_terminados = [v for k, v in estatus_map.items() if k in ('completado', 'entregado')]
            levantamientos = await db_svc.get_lista_terminados(
                conn, ids_terminados=ids_terminados, q=q, estado=estado,
                tecnico_id=tecnico_id, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin
            )
            estatus_filtro = [e for e in estatus_list if e['grupo_kanban'] == 'terminado']
        else:
            tab = "activos"
            ids_activos = [v for k, v in estatus_map.items() if k not in ('completado', 'entregado')]
            levantamientos = await db_svc.get_lista_activos(
                conn, ids_activos=ids_activos, q=q, estado=estado,
                tecnico_id=tecnico_id, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin
            )
            estatus_filtro = [e for e in estatus_list if e['grupo_kanban'] == 'activo']

        tecnicos = await db_svc.get_usuarios_tecnicos(conn)

        can_edit = (
            context.get("role") == "ADMIN"
            or context.get("module_roles", {}).get("levantamientos") in ["editor", "admin"]
        )

        return templates.TemplateResponse("levantamientos/partials/lista.html", {
            "request": request,
            "tab": tab,
            "levantamientos": levantamientos,
            "tecnicos": tecnicos,
            "estatus_filtro": estatus_filtro,
            "can_edit": can_edit,
            "filtros": {
                "q": q or "",
                "estado": estado,
                "tecnico_id": tecnico_id or "",
                "fecha_inicio": fecha_inicio or "",
                "fecha_fin": fecha_fin or "",
            },
        })

    # ==============================================================
    # GET — VISTA GRÁFICAS
    # ==============================================================

    @router.get("/partials/graficas", include_in_schema=False)
    async def get_graficas_levantamientos(
        request: Request,
        conn=Depends(get_db_connection),
        analytics_svc: LevantamientosAnalyticsDBService = Depends(get_analytics_db_service),
        context=Depends(get_current_user_context),
        _=require_module_access("levantamientos"),
    ):
        """
        Vista gráficas del módulo levantamientos.
        4 charts: donut estatus, barras técnicos, línea tendencia semanal, tiempos+costos KPI.
        """
        distribucion   = await analytics_svc.get_distribucion_estatus(conn)
        carga_tecnicos = await analytics_svc.get_carga_tecnicos(conn)
        tendencia      = await analytics_svc.get_tendencia_semanal(conn)
        tiempos_costos = await analytics_svc.get_tiempos_y_costos(conn)

        return templates.TemplateResponse("levantamientos/partials/graficas.html", {
            "request": request,
            "distribucion": distribucion,
            "carga_tecnicos": carga_tecnicos,
            "tendencia": tendencia,
            "tiempos_costos": tiempos_costos,
        })
