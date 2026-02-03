# ==============================================================
# modules/levantamientos/router_levantamientos_nuevos.py
#
# Endpoints nuevos para posponer, reagendar y viaticos.
# Se agregan al router existente (modules/levantamientos/router.py).
#
# CÓMO INTEGRAR:
#   En router.py, al final del archivo, agregar:
#
#       from .router_levantamientos_nuevos import register_nuevos_endpoints
#       register_nuevos_endpoints(router)
#
#   Eso conecta todos los endpoints de este archivo al mismo
#   APIRouter que ya existe, sin duplicar prefijo ni tags.
# ==============================================================

from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
from uuid import UUID
from datetime import datetime, date
from zoneinfo import ZoneInfo
import json
import logging

from core.security import get_current_user_context
from core.permissions import require_module_access
from core.database import get_db_connection
from core.microsoft import MicrosoftAuth

from .service import get_service, LevantamientoService
from .db_service import get_db_service, LevantamientosDBService

logger = logging.getLogger("Levantamientos.Router.Nuevos")

templates = Jinja2Templates(directory="templates")


def register_nuevos_endpoints(router: APIRouter):
    """
    Registra todos los endpoints nuevos en el router existente.
    Llamar una sola vez desde router.py.
    """

    # ==============================================================
    # GET — MODALES (renderizar templates con datos)
    # ==============================================================

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
        })

    # ----------------------------------------------------------

    @router.get("/modal/reagendar/{id_levantamiento}", include_in_schema=False)
    async def get_modal_reagendar(
        request: Request,
        id_levantamiento: UUID,
        desde: str = "pendiente",   # pendiente | pospuesto
        conn=Depends(get_db_connection),
        db_svc: LevantamientosDBService = Depends(get_db_service),
        context=Depends(get_current_user_context),
        _=require_module_access("levantamientos", "editor"),
    ):
        """
        Renderiza el modal de reagendar.
        desde=pendiente  → agendar desde estado 8
        desde=pospuesto  → reagendar desde estado 13
        """
        lev = await db_svc.get_levantamiento_base(conn, id_levantamiento)
        if not lev:
            raise HTTPException(status_code=404, detail="Levantamiento no encontrado")

        today_str = datetime.now(ZoneInfo("America/Mexico_City")).strftime("%Y-%m-%d")

        return templates.TemplateResponse("levantamientos/modals/reagendar_modal.html", {
            "request": request,
            "lev_data": lev,
            "desde": desde,
            "today_str": today_str,
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
          - CC configurados desde tb_config_emails
          - historial de envíos previos
        """
        lev = await db_svc.get_levantamiento_base(conn, id_levantamiento)
        if not lev:
            raise HTTPException(status_code=404, detail="Levantamiento no encontrado")

        viaticos        = await db_svc.get_viaticos(conn, id_levantamiento)
        usuarios        = await db_svc.get_usuarios_viaticos(conn)
        cc_configurados = await db_svc.get_cc_configurados_viaticos(conn)
        historial       = await db_svc.get_historial_envios(conn, id_levantamiento)

        return templates.TemplateResponse("levantamientos/modals/viaticos_modal.html", {
            "request": request,
            "lev_data": lev,
            "viaticos": viaticos,
            "usuarios": usuarios,
            "cc_configurados": cc_configurados,
            "historial_envios": historial,
        })

    # ==============================================================
    # POST — POSPONER
    # ==============================================================

    @router.post("/posponer/{id_levantamiento}")
    async def posponer_endpoint(
        request: Request,
        id_levantamiento: UUID,
        motivo_pospone: str = Form(...),
        conn=Depends(get_db_connection),
        db_svc: LevantamientosDBService = Depends(get_db_service),
        service: LevantamientoService = Depends(get_service),
        context=Depends(get_current_user_context),
        _=require_module_access("levantamientos", "editor"),
    ):
        """
        1. Valida motivo (min 10 chars).
        2. Obtiene estado actual para el historial.
        3. Ejecuta UPDATE via db_service.
        4. Registra en historial via service.
        5. Retorna Kanban actualizado (outerHTML).
        """
        if not motivo_pospone or len(motivo_pospone.strip()) < 10:
            raise HTTPException(status_code=400, detail="El motivo debe tener al menos 10 caracteres.")

        # Estado actual antes del cambio
        lev = await db_svc.get_levantamiento_base(conn, id_levantamiento)
        if not lev:
            raise HTTPException(status_code=404, detail="Levantamiento no encontrado")

        estado_anterior = lev["id_estatus_global"]

        # UPDATE
        await db_svc.update_posponer(conn, id_levantamiento, motivo_pospone.strip(), context["user_db_id"])

        # Historial
        await service._registrar_en_historial(
            conn=conn,
            id_levantamiento=id_levantamiento,
            estatus_anterior=estado_anterior,
            estatus_nuevo=13,
            user_context=context,
            observaciones=motivo_pospone.strip(),
            metadata={"tipo_cambio": "posponer"}
        )

        # Retornar kanban completo
        return await _render_kanban(request, conn, service, context)

    # ==============================================================
    # POST — REAGENDAR
    # ==============================================================

    @router.post("/reagendar/{id_levantamiento}")
    async def reagendar_endpoint(
        request: Request,
        id_levantamiento: UUID,
        nueva_fecha_visita: str = Form(...),
        observaciones: Optional[str] = Form(None),
        conn=Depends(get_db_connection),
        db_svc: LevantamientosDBService = Depends(get_db_service),
        service: LevantamientoService = Depends(get_service),
        context=Depends(get_current_user_context),
        _=require_module_access("levantamientos", "editor"),
    ):
        """
        1. Valida formato de fecha y que no sea pasada.
        2. Obtiene estado actual.
        3. Ejecuta UPDATE via db_service.
        4. Registra en historial.
        5. Retorna Kanban actualizado.
        """
        # Validar fecha
        if not nueva_fecha_visita:
            raise HTTPException(status_code=400, detail="Se requiere fecha de visita.")

        try:
            fecha_obj = date.fromisoformat(nueva_fecha_visita)
        except ValueError:
            raise HTTPException(status_code=400, detail="Formato de fecha inválido.")

        hoy = datetime.now(ZoneInfo("America/Mexico_City")).date()
        if fecha_obj < hoy:
            raise HTTPException(status_code=400, detail="La fecha no puede ser anterior a hoy.")

        # Estado actual
        lev = await db_svc.get_levantamiento_base(conn, id_levantamiento)
        if not lev:
            raise HTTPException(status_code=404, detail="Levantamiento no encontrado")

        estado_anterior = lev["id_estatus_global"]

        # UPDATE
        await db_svc.update_reagendar(conn, id_levantamiento, nueva_fecha_visita, context["user_db_id"])

        # Historial
        await service._registrar_en_historial(
            conn=conn,
            id_levantamiento=id_levantamiento,
            estatus_anterior=estado_anterior,
            estatus_nuevo=9,
            user_context=context,
            observaciones=observaciones.strip() if observaciones else None,
            metadata={
                "tipo_cambio": "reagendar",
                "nueva_fecha": nueva_fecha_visita,
            }
        )

        return await _render_kanban(request, conn, service, context)

    # ==============================================================
    # POST / DELETE — VIATICOS CRUD
    # ==============================================================

    @router.post("/viaticos/{id_levantamiento}")
    async def crear_viatico_endpoint(
        request: Request,
        id_levantamiento: UUID,
        usuario_id: UUID = Form(...),
        concepto: str = Form(...),
        monto: float = Form(...),
        conn=Depends(get_db_connection),
        db_svc: LevantamientosDBService = Depends(get_db_service),
        context=Depends(get_current_user_context),
        _=require_module_access("levantamientos", "editor"),
    ):
        """
        Crea un viatico y retorna el innerHTML de #tabla-viaticos-container
        con la tabla actualizada + total.
        """
        if not concepto or not concepto.strip():
            raise HTTPException(status_code=400, detail="El concepto es obligatorio.")
        if monto <= 0:
            raise HTTPException(status_code=400, detail="El monto debe ser mayor a 0.")

        await db_svc.create_viatico(
            conn, id_levantamiento, usuario_id, concepto.strip(), monto, context["user_db_id"]
        )

        # Recargar lista completa para retornar partial
        viaticos = await db_svc.get_viaticos(conn, id_levantamiento)

        return templates.TemplateResponse("levantamientos/partials/tabla_viaticos.html", {
            "request": request,
            "viaticos": viaticos,
            "id_levantamiento": id_levantamiento,
        })

    # ----------------------------------------------------------

    @router.delete("/viaticos/{id_levantamiento}/{viatico_id}")
    async def eliminar_viatico_endpoint(
        request: Request,
        id_levantamiento: UUID,
        viatico_id: UUID,
        conn=Depends(get_db_connection),
        db_svc: LevantamientosDBService = Depends(get_db_service),
        context=Depends(get_current_user_context),
        _=require_module_access("levantamientos", "editor"),
    ):
        """
        Elimina un viatico y retorna el innerHTML actualizado
        de #tabla-viaticos-container.
        """
        eliminado = await db_svc.delete_viatico(conn, id_levantamiento, viatico_id)
        if not eliminado:
            raise HTTPException(status_code=404, detail="Viatico no encontrado.")

        viaticos = await db_svc.get_viaticos(conn, id_levantamiento)

        return templates.TemplateResponse("levantamientos/partials/tabla_viaticos.html", {
            "request": request,
            "viaticos": viaticos,
            "id_levantamiento": id_levantamiento,
        })

    # ==============================================================
    # POST — ENVIAR SOLICITUD DE VIATICOS
    # ==============================================================

    @router.post("/viaticos/solicitud/{id_levantamiento}")
    async def enviar_solicitud_viaticos_endpoint(
        request: Request,
        id_levantamiento: UUID,
        cc_adicionales: str = Form(""),
        conn=Depends(get_db_connection),
        db_svc: LevantamientosDBService = Depends(get_db_service),
        context=Depends(get_current_user_context),
        _=require_module_access("levantamientos", "editor"),
    ):
        """
        1. Obtiene viaticos actuales (debe haber al menos 1).
        2. Construye TO y CC (configurados + manuales).
        3. Renderiza solicitud_viaticos.html como body del correo.
        4. Envía via MicrosoftAuth.
        5. Registra en tb_levantamiento_viaticos_historico con snapshot.
        6. Retorna innerHTML de #historial-envios-container actualizado.
        """
        # 1. Viaticos
        viaticos = await db_svc.get_viaticos(conn, id_levantamiento)
        if not viaticos:
            raise HTTPException(status_code=400, detail="No hay viaticos registrados.")

        lev = await db_svc.get_levantamiento_base(conn, id_levantamiento)
        if not lev:
            raise HTTPException(status_code=404, detail="Levantamiento no encontrado")

        total_monto = sum(v["monto"] for v in viaticos)

        # 2. Destinatarios
        to_list = await db_svc.get_to_configurados_viaticos(conn)
        cc_configurados = await db_svc.get_cc_configurados_viaticos(conn)

        # CC manuales: separados por ";" desde el hidden input
        cc_manuales = [e.strip() for e in cc_adicionales.split(";") if e.strip() and "@" in e.strip()]

        # Unir CC sin duplicados, quitar TO de CC
        cc_all = list(set(cc_configurados + cc_manuales) - set(to_list))

        if not to_list:
            raise HTTPException(status_code=500, detail="No hay destinatarios TO configurados para SOLICITUD_VIATICOS.")

        # 3. Renderizar template de email
        now_mx = datetime.now(ZoneInfo("America/Mexico_City"))
        fecha_envio_str = now_mx.strftime("%d/%m/%Y %H:%M")

        email_template = templates.get_template("levantamientos/emails/solicitud_viaticos.html")
        html_body = email_template.render(
            proyecto_nombre=lev["nombre_proyecto"] or lev["titulo_proyecto"] or "Sin nombre",
            op_id=lev["op_id_estandar"],
            cliente_nombre=lev["cliente_nombre"],
            sitio_direccion=lev.get("sitio_direccion"),
            enviado_por=context.get("user_name", "Sistema"),
            fecha_envio=fecha_envio_str,
            viaticos=viaticos,
            total_monto=total_monto,
        )

        # 4. Enviar correo
        subject = f"Solicitud de Viaticos — {lev['op_id_estandar']} | {lev['cliente_nombre']}"
        sender_email = context.get("email") or context.get("user_email", "")

        estatus_envio = "enviado"
        error_detalle = None

        try:
            ms_auth = MicrosoftAuth()
            app_token = await ms_auth.get_application_token()

            if not app_token:
                raise Exception("No se pudo obtener token de aplicación de Microsoft Graph.")

            success, msg = await ms_auth.send_email_with_attachments(
                access_token=app_token,
                from_email=sender_email,
                subject=subject,
                body=html_body,
                recipients=to_list,
                cc_recipients=cc_all if cc_all else None,
                importance="normal",
            )

            if not success:
                estatus_envio = "error"
                error_detalle = msg
                logger.error(f"[VIATICOS] Error envío correo lev {id_levantamiento}: {msg}")
            else:
                logger.info(f"[VIATICOS] Correo enviado exitosamente lev {id_levantamiento}")

        except Exception as exc:
            estatus_envio = "error"
            error_detalle = str(exc)
            logger.error(f"[VIATICOS] Excepción envío correo lev {id_levantamiento}: {exc}")

        # 5. Registrar historial (siempre, incluso si falla el correo)
        snapshot = [
            {"usuario_nombre": v["usuario_nombre"], "concepto": v["concepto"], "monto": float(v["monto"])}
            for v in viaticos
        ]

        await db_svc.insert_historial_envio(
            conn=conn,
            id_levantamiento=id_levantamiento,
            enviado_por_id=context["user_db_id"],
            enviado_por_nombre=context.get("user_name", "Sistema"),
            to_destinatarios=to_list,
            cc_destinatarios=cc_all,
            viaticos_snapshot=snapshot,
            total_monto=total_monto,
            estatus=estatus_envio,
            error_detalle=error_detalle,
        )

        # 6. Retornar historial actualizado
        historial = await db_svc.get_historial_envios(conn, id_levantamiento)

        return templates.TemplateResponse("levantamientos/partials/historial_envios.html", {
            "request": request,
            "historial_envios": historial,
        })

    # ==============================================================
    # HELPER interno: renderiza el Kanban completo (outerHTML)
    # ==============================================================

    async def _render_kanban(request, conn, service, context):
        """
        Recarga datos del kanban y retorna el template completo.
        Usado por posponer y reagendar para refrescar el tablero.
        """
        data = await service.get_kanban_data(conn)

        can_edit = (
            context.get("role") == "ADMIN"
            or context.get("module_roles", {}).get("levantamientos") in ["editor", "assignor", "admin"]
        )

        return templates.TemplateResponse("levantamientos/partials/kanban.html", {
            "request": request,
            "pendientes": data["pendientes"],
            "agendados": data["agendados"],
            "en_proceso": data["en_proceso"],
            "completados": data["completados"],
            "entregados": data["entregados"],
            "pospuestos": data["pospuestos"],
            "can_edit": can_edit,
            "user_context": context,
        })
