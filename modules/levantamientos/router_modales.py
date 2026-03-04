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

from fastapi import APIRouter, Depends, Request, HTTPException, Query
from fastapi.templating import Jinja2Templates

from core.security import get_current_user_context
from core.permissions import require_module_access, require_any_module_access
from core.database import get_db_connection

from .service import get_service, LevantamientoService
from .db_service import get_db_service, LevantamientosDBService
from .db_service_visitas import get_visitas_db_service, VisitasCampoDBService

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
        visitas_db_svc: VisitasCampoDBService = Depends(get_visitas_db_service),
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
          - visitas de campo que contienen este levantamiento (indicador)
        """
        lev = await db_svc.get_levantamiento_base(conn, id_levantamiento)
        if not lev:
            raise HTTPException(status_code=404, detail="Levantamiento no encontrado")

        viaticos        = await db_svc.get_viaticos(conn, id_levantamiento)
        usuarios        = await db_svc.get_usuarios_viaticos(conn, id_levantamiento)
        to_configurados = await db_svc.get_to_configurados_viaticos(conn)
        cc_configurados = await db_svc.get_cc_configurados_viaticos(conn)
        historial       = await db_svc.get_historial_envios(conn, id_levantamiento)
        visitas_campo   = await db_svc.get_visitas_campo_for_lev(conn, id_levantamiento)

        return templates.TemplateResponse("levantamientos/modals/viaticos_modal.html", {
            "request": request,
            "lev_data": lev,
            "viaticos": viaticos,
            "usuarios": usuarios,
            "to_configurados": to_configurados,
            "cc_configurados": cc_configurados,
            "historial_envios": historial,
            "id_levantamiento": id_levantamiento,
            "visitas_campo": visitas_campo,
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

    # ----------------------------------------------------------

    @router.get("/modal/cancelar/{id_levantamiento}", include_in_schema=False)
    async def get_modal_cancelar(
        request: Request,
        id_levantamiento: UUID,
        conn=Depends(get_db_connection),
        db_svc: LevantamientosDBService = Depends(get_db_service),
        context=Depends(get_current_user_context),
        _=require_module_access("levantamientos", "editor"),
    ):
        """Renderiza el modal de cancelación con motivo obligatorio."""
        lev = await db_svc.get_levantamiento_base(conn, id_levantamiento)
        if not lev:
            raise HTTPException(status_code=404, detail="Levantamiento no encontrado")

        return templates.TemplateResponse("levantamientos/modals/cancelar_modal.html", {
            "request": request,
            "lev_data": lev,
            "id_levantamiento": id_levantamiento,
        })

    # ----------------------------------------------------------

    @router.get("/modal/fecha-ideal/{id_levantamiento}", include_in_schema=False)
    async def get_modal_fecha_ideal(
        request: Request,
        id_levantamiento: UUID,
        conn=Depends(get_db_connection),
        db_svc: LevantamientosDBService = Depends(get_db_service),
        context=Depends(get_current_user_context),
        _=require_module_access("levantamientos", "viewer"),
    ):
        """Renderiza el modal informativo de la fecha ideal del solicitante (solo lectura)."""
        lev = await db_svc.get_levantamiento_base(conn, id_levantamiento)
        if not lev:
            raise HTTPException(status_code=404, detail="Levantamiento no encontrado")

        # Pre-formatear fecha y hora en zona México para evitar problemas de Jinja2
        fecha_str = ""
        hora_str = ""
        fecha_raw = lev.get("fecha_ideal_solicitante")
        if fecha_raw:
            from zoneinfo import ZoneInfo
            if fecha_raw.tzinfo is None:
                fecha_raw = fecha_raw.replace(tzinfo=ZoneInfo("UTC"))
            fecha_mx = fecha_raw.astimezone(ZoneInfo("America/Mexico_City"))
            fecha_str = fecha_mx.strftime("%d/%m/%Y")
            if fecha_mx.hour or fecha_mx.minute:
                hora_str = fecha_mx.strftime("%H:%M")

        return templates.TemplateResponse("levantamientos/modals/fecha_ideal_modal.html", {
            "request": request,
            "lev_data": lev,
            "fecha_str": fecha_str,
            "hora_str": hora_str,
        })

    # ----------------------------------------------------------

    @router.get("/modal/solicitar-reasignacion/{id_levantamiento}", include_in_schema=False)
    async def get_modal_solicitar_reasignacion(
        request: Request,
        id_levantamiento: UUID,
        conn=Depends(get_db_connection),
        db_svc: LevantamientosDBService = Depends(get_db_service),
        context=Depends(get_current_user_context),
        _=require_module_access("levantamientos"),
    ):
        """Renderiza el modal de solicitud de reasignación (solo para el responsable actual)."""
        lev = await db_svc.get_levantamiento_base(conn, id_levantamiento)
        if not lev:
            raise HTTPException(status_code=404, detail="Levantamiento no encontrado")

        responsable = await db_svc.get_responsable_asignado(conn, id_levantamiento)
        user_db_id = context.get("user_db_id")
        if not responsable or str(responsable['id_usuario']) != str(user_db_id):
            raise HTTPException(status_code=403, detail="Solo el ingeniero responsable puede solicitar reasignacion")

        return templates.TemplateResponse("levantamientos/modals/solicitar_reasignacion_modal.html", {
            "request": request,
            "lev_data": lev,
            "id_levantamiento": id_levantamiento,
        })

    # ----------------------------------------------------------
    # VISITAS DE CAMPO — modales
    # ----------------------------------------------------------

    @router.get("/modal/visita-campo/nueva", include_in_schema=False)
    async def get_modal_nueva_visita(
        request: Request,
        id_levantamiento: Optional[UUID] = Query(None),
        conn=Depends(get_db_connection),
        visitas_db_svc: VisitasCampoDBService = Depends(get_visitas_db_service),
        context=Depends(get_current_user_context),
        _=require_module_access("levantamientos", "editor"),
    ):
        """
        Renderiza el modal de creación de nueva Visita de Campo.
        Si se pasa id_levantamiento, ese levantamiento queda pre-seleccionado.
        """
        levantamientos = await visitas_db_svc.get_levantamientos_disponibles(conn)
        preseleccionado = str(id_levantamiento) if id_levantamiento else None

        return templates.TemplateResponse("levantamientos/modals/visita_campo_modal.html", {
            "request": request,
            "step": "crear",
            "levantamientos_disponibles": levantamientos,
            "preseleccionado": preseleccionado,
            "visita": None,
            "levantamientos_visita": [],
            "viaticos": [],
            "usuarios": [],
            "historial_envios": [],
            "to_configurados": [],
            "cc_configurados": [],
        })

    # ----------------------------------------------------------

    @router.get("/modal/visita-campo/{id_visita}", include_in_schema=False)
    async def get_modal_gestionar_visita(
        request: Request,
        id_visita: UUID,
        conn=Depends(get_db_connection),
        db_svc: LevantamientosDBService = Depends(get_db_service),
        visitas_db_svc: VisitasCampoDBService = Depends(get_visitas_db_service),
        context=Depends(get_current_user_context),
        _=require_module_access("levantamientos", "editor"),
    ):
        """
        Renderiza el modal de gestión de una Visita de Campo existente.
        Muestra viáticos, prorrateo y botón de envío.
        """
        visita = await visitas_db_svc.get_visita(conn, id_visita)
        if not visita:
            raise HTTPException(status_code=404, detail="Visita de campo no encontrada")

        levantamientos_visita = await visitas_db_svc.get_levantamientos_en_visita(conn, id_visita)
        viaticos = await visitas_db_svc.get_viaticos_visita(conn, id_visita)
        usuarios = await visitas_db_svc.get_usuarios_para_visita(conn, id_visita)
        historial_envios = await visitas_db_svc.get_envios_visita(conn, id_visita)
        to_configurados = await db_svc.get_to_configurados_viaticos(conn)
        cc_configurados = await db_svc.get_cc_configurados_viaticos(conn)

        from .db_service_visitas import calcular_prorrateo
        total_viaticos = float(sum(v["monto"] for v in viaticos))
        prorrateo = calcular_prorrateo(total_viaticos, levantamientos_visita)

        return templates.TemplateResponse("levantamientos/modals/visita_campo_modal.html", {
            "request": request,
            "step": "gestionar",
            "visita": visita,
            "levantamientos_visita": levantamientos_visita,
            "viaticos": viaticos,
            "usuarios": usuarios,
            "historial_envios": historial_envios,
            "to_configurados": to_configurados,
            "cc_configurados": cc_configurados,
            "prorrateo": prorrateo,
            "total_viaticos": total_viaticos,
            "levantamientos_disponibles": [],
            "preseleccionado": None,
        })

    # ----------------------------------------------------------

    @router.get("/modal/visita-campo/{id_visita}/agregar", include_in_schema=False)
    async def get_modal_agregar_levantamientos(
        request: Request,
        id_visita: UUID,
        conn=Depends(get_db_connection),
        visitas_db_svc: VisitasCampoDBService = Depends(get_visitas_db_service),
        context=Depends(get_current_user_context),
        _=require_module_access("levantamientos", "editor"),
    ):
        """
        Carga el selector de levantamientos disponibles para agregar a la visita.
        Excluye los ya vinculados y los de estatus final.
        Se inyecta en #vc-agregar-lev-container dentro del modal gestionar.
        """
        disponibles = await visitas_db_svc.get_levantamientos_disponibles_para_agregar(
            conn, id_visita
        )
        return templates.TemplateResponse(
            "levantamientos/partials/visita_campo_selector_agregar.html",
            {
                "request": request,
                "id_visita": id_visita,
                "levantamientos_disponibles": disponibles,
            },
        )

    # ----------------------------------------------------------

    @router.get("/modal/visita-campo-lev/{id_levantamiento}", include_in_schema=False)
    async def get_modal_visitas_de_levantamiento(
        request: Request,
        id_levantamiento: UUID,
        conn=Depends(get_db_connection),
        visitas_db_svc: VisitasCampoDBService = Depends(get_visitas_db_service),
        context=Depends(get_current_user_context),
        _=require_module_access("levantamientos", "editor"),
    ):
        """
        Desde la tarjeta de un levantamiento: muestra las visitas de campo
        que lo contienen. Si no tiene visitas, carga el modal de nueva visita
        con el levantamiento pre-seleccionado.
        """
        visitas = await visitas_db_svc.get_visitas_for_levantamiento(conn, id_levantamiento)

        if not visitas:
            # Redirige al modal de nueva visita con pre-selección
            levantamientos = await visitas_db_svc.get_levantamientos_disponibles(conn)
            return templates.TemplateResponse("levantamientos/modals/visita_campo_modal.html", {
                "request": request,
                "step": "crear",
                "levantamientos_disponibles": levantamientos,
                "preseleccionado": str(id_levantamiento),
                "visita": None,
                "levantamientos_visita": [],
                "viaticos": [],
                "usuarios": [],
                "historial_envios": [],
                "to_configurados": [],
                "cc_configurados": [],
            })

        return templates.TemplateResponse("levantamientos/modals/visitas_de_levantamiento_modal.html", {
            "request": request,
            "id_levantamiento": id_levantamiento,
            "visitas": visitas,
        })
