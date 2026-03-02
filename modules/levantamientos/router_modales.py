# ==============================================================
# modules/levantamientos/router_modales.py
# Endpoints GET de modales para el módulo Levantamientos.
# Registrado en router_levantamientos_nuevos.py.
# ==============================================================

import logging
from typing import Optional
from uuid import UUID
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.templating import Jinja2Templates

from core.security import get_current_user_context
from core.permissions import require_module_access, require_any_module_access
from core.database import get_db_connection

from .service import get_service, LevantamientoService
from .db_service import get_db_service, LevantamientosDBService

logger = logging.getLogger("Levantamientos.Router.Modales")

templates = Jinja2Templates(directory="templates")


def register_modal_endpoints(router: APIRouter):
    """
    Registra los 6 endpoints GET de modales en el router existente.
    """

    @router.get("/modal/posponer/{id_levantamiento}", include_in_schema=False)
    async def get_modal_posponer(
        request: Request,
        id_levantamiento: UUID,
        conn=Depends(get_db_connection),
        db_svc: LevantamientosDBService = Depends(get_db_service),
        context=Depends(get_current_user_context),
        _=require_module_access("levantamientos", "editor"),
    ):
        """Renderiza el modal de posponer con datos del levantamiento."""
        lev = await db_svc.get_levantamiento_base(conn, id_levantamiento)
        if not lev:
            raise HTTPException(status_code=404, detail="Levantamiento no encontrado")

        return templates.TemplateResponse("levantamientos/modals/posponer_modal.html", {
            "request": request,
            "lev_data": lev,
            "has_active_viaticos": await db_svc.check_viaticos_sent(conn, id_levantamiento)
        })

    # ----------------------------------------------------------

    @router.get("/modals/detalle/{id_levantamiento}", include_in_schema=False)
    async def get_detalle_levantamiento_modal(
        request: Request,
        id_levantamiento: UUID,
        source: Optional[str] = None,  # comercial | simulacion
        conn=Depends(get_db_connection),
        db_svc: LevantamientosDBService = Depends(get_db_service),
        context=Depends(get_current_user_context),
        _=require_any_module_access(["levantamientos", "comercial", "simulacion"], "viewer"),
    ):
        """
        Renderiza el modal de DETALLE COMPLETO.
        Accesible desde Comercial y Simulación.
        """
        lev = await db_svc.get_detalle_completo(conn, id_levantamiento)
        if not lev:
            raise HTTPException(status_code=404, detail="Levantamiento no encontrado")

        return templates.TemplateResponse("shared/modals/detalle_levantamiento_modal.html", {
            "request": request,
            "lev": lev,
            "source": source
        })

    # ----------------------------------------------------------

    @router.get("/modal/historial/{id_levantamiento}", include_in_schema=False)
    async def get_modal_historial(
        request: Request,
        id_levantamiento: UUID,
        conn=Depends(get_db_connection),
        db_svc: LevantamientosDBService = Depends(get_db_service),
        service: LevantamientoService = Depends(get_service),
        context=Depends(get_current_user_context),
        _=require_module_access("levantamientos", "viewer"),
    ):
        """Renderiza el modal de historial con timeline de cambios."""
        lev = await db_svc.get_levantamiento_base(conn, id_levantamiento)
        if not lev:
            raise HTTPException(status_code=404, detail="Levantamiento no encontrado")

        historial = await service.get_historial_estados(conn, id_levantamiento)

        return templates.TemplateResponse("shared/modals/historial_levantamiento_modal.html", {
            "request": request,
            "lev_data": lev,
            "historial": historial,
        })

    # ----------------------------------------------------------

    @router.get("/modal/reagendar/{id_levantamiento}", include_in_schema=False)
    async def get_modal_reagendar(
        request: Request,
        id_levantamiento: UUID,
        desde: str = "pendiente",  # pendiente | pospuesto
        conn=Depends(get_db_connection),
        db_svc: LevantamientosDBService = Depends(get_db_service),
        context=Depends(get_current_user_context),
        _=require_module_access("levantamientos", "editor"),
    ):
        """
        Renderiza el modal de reagendar.
        desde=pendiente  → agendar desde estado pendiente
        desde=pospuesto  → reagendar desde estado pospuesto
        Incluye responsable_actual e is_jefe para el bloque de confirmación de auto-asignación.
        """
        lev = await db_svc.get_levantamiento_base(conn, id_levantamiento)
        if not lev:
            raise HTTPException(status_code=404, detail="Levantamiento no encontrado")

        today_str = datetime.now(ZoneInfo("America/Mexico_City")).strftime("%Y-%m-%dT%H:%M")

        responsable_actual = await db_svc.get_responsable_asignado(conn, id_levantamiento)
        user_db_id = context.get("user_db_id")
        jefe_area_id = lev.get("jefe_area_id")
        is_jefe = (jefe_area_id is not None and str(jefe_area_id) == str(user_db_id))

        return templates.TemplateResponse("levantamientos/modals/reagendar_modal.html", {
            "request": request,
            "lev_data": lev,
            "desde": desde,
            "today_str": today_str,
            "responsable_actual": responsable_actual,
            "is_jefe": is_jefe,
        })

    # ----------------------------------------------------------

    @router.get("/modal/viaticos/{id_levantamiento}", include_in_schema=False)
    async def get_modal_viaticos(
        request: Request,
        id_levantamiento: UUID,
        conn=Depends(get_db_connection),
        db_svc: LevantamientosDBService = Depends(get_db_service),
        context=Depends(get_current_user_context),
        _=require_module_access("levantamientos", "editor"),
    ):
        """
        Renderiza el modal de viaticos con:
          - datos del levantamiento
          - lista de viaticos actuales
          - usuarios disponibles (select)
          - TO y CC configurados desde tb_config_emails
          - historial de envíos previos
        """
        lev = await db_svc.get_levantamiento_base(conn, id_levantamiento)
        if not lev:
            raise HTTPException(status_code=404, detail="Levantamiento no encontrado")

        viaticos        = await db_svc.get_viaticos(conn, id_levantamiento)
        usuarios        = await db_svc.get_usuarios_viaticos(conn, id_levantamiento)
        to_configurados = await db_svc.get_to_configurados_viaticos(conn)
        cc_configurados = await db_svc.get_cc_configurados_viaticos(conn)
        historial       = await db_svc.get_historial_envios(conn, id_levantamiento)

        return templates.TemplateResponse("levantamientos/modals/viaticos_modal.html", {
            "request": request,
            "lev_data": lev,
            "viaticos": viaticos,
            "usuarios": usuarios,
            "to_configurados": to_configurados,
            "cc_configurados": cc_configurados,
            "historial_envios": historial,
            "id_levantamiento": id_levantamiento,
        })

    # ----------------------------------------------------------

    @router.get("/modal/entrega/{id_levantamiento}", include_in_schema=False)
    async def get_modal_entrega(
        request: Request,
        id_levantamiento: UUID,
        conn=Depends(get_db_connection),
        db_svc: LevantamientosDBService = Depends(get_db_service),
        context=Depends(get_current_user_context),
        _=require_module_access("levantamientos", "editor"),
    ):
        """Renderiza el modal de entrega con datos del levantamiento y adjuntos previos."""
        lev = await db_svc.get_levantamiento_base(conn, id_levantamiento)
        if not lev:
            raise HTTPException(status_code=404, detail="Levantamiento no encontrado")

        adjuntos_previos = await db_svc.get_adjuntos_levantamiento(conn, id_levantamiento)

        return templates.TemplateResponse("levantamientos/modals/entrega_modal.html", {
            "request": request,
            "lev_data": lev,
            "adjuntos_previos": adjuntos_previos,
        })
