from __future__ import annotations

import logging
from io import BytesIO
from datetime import date
from uuid import UUID

import asyncpg
import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from core.database import get_db_connection
from core.integrations.sharepoint import SharePointService
from core.microsoft import get_ms_auth
from core.permissions import require_manager_access, require_module_access, user_has_module_access
from core.security import get_current_user_context
from core.timezone import today_mx
from core.workflow.notification_service import NotificationService
from modules.asistencia import db_service as db
from modules.asistencia.constants import ASISTENCIA_ESTADOS
from modules.asistencia.service import (
    HEAutorizacionError,
    ajuste_manual_svc,
    aprobar_compensatorio_svc,
    aprobar_solicitud_manual_svc,
    aprobar_horas_extra_svc,
    cancelar_compensatorio_svc,
    confirmar_saldo_inicial_svc,
    generar_reporte_bolsa_he_svc,
    get_equipo_ids,
    get_equipo_ids_para_autorizacion_he,
    get_equipo_visible_he,
    get_he_bolsa_ctx,
    get_he_bolsa_fecha_corte,
    omitir_horas_extra_svc,
    rechazar_solicitud_manual_svc,
    rechazar_compensatorio_svc,
    recuperar_horas_extra_svc,
    revertir_dia_horas_extra_svc,
    solicitar_compensatorio_svc,
    solicitar_aprobacion_svc,
    subir_evidencias_he_y_solicitar_svc,
    sync_biotime_once,
)
from modules.shared.utils import excel_response, format_minutes, toast_error, toast_success
from modules.vacaciones import db_service as vacaciones_db

logger = logging.getLogger("asistencia.router")
router = APIRouter(prefix="/asistencia", tags=["asistencia"])
templates = Jinja2Templates(directory="templates")


@router.get("/api/reporte")
async def reporte_asistencia(
    fecha_inicio: date,
    fecha_fin: date,
    usuario_id: UUID | None = None,
    sucursal_id: UUID | None = None,
    estado: str | None = Query(None),
    conn=Depends(get_db_connection),
    _=require_module_access("rrhh", "viewer"),
):
    if fecha_fin < fecha_inicio:
        raise HTTPException(status_code=400, detail="La fecha final no puede ser menor que la inicial")
    if estado and estado not in ASISTENCIA_ESTADOS:
        raise HTTPException(status_code=400, detail="Estado de asistencia no valido")
    rows = await db.get_reporte_asistencia(
        conn,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        usuario_ids=[usuario_id] if usuario_id else None,
        sucursal_ids=[sucursal_id] if sucursal_id else None,
        estados=[estado] if estado else None,
    )
    return JSONResponse(jsonable_encoder({"items": rows, "count": len(rows)}))


@router.post("/api/biotime/sync")
async def ejecutar_sync_biotime(
    conn=Depends(get_db_connection),
    _=require_manager_access("rrhh", "editor"),
):
    try:
        result = await sync_biotime_once(conn, force=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        logger.error("Error HTTP ejecutando sync BioTime: %s", exc)
        raise HTTPException(status_code=502, detail="No se pudo consultar BioTime") from exc
    except asyncpg.PostgresError as exc:
        logger.error("Error de BD ejecutando sync BioTime: %s", exc)
        raise HTTPException(status_code=500, detail="No se pudo guardar la asistencia") from exc
    return JSONResponse(jsonable_encoder(result))


@router.post("/api/horas-extra/{asistencia_id}/aprobar")
async def aprobar_horas_extra(
    request: Request,
    asistencia_id: UUID,
    minutos_aprobados: int = Form(...),
    comentario: str = Form(...),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    if not context.get("user_db_id"):
        raise HTTPException(status_code=401)
    aprobador_id = UUID(str(context["user_db_id"]))

    try:
        result = await aprobar_horas_extra_svc(
            conn,
            asistencia_id=asistencia_id,
            aprobador_id=aprobador_id,
            minutos_aprobados=minutos_aprobados,
            comentario=comentario,
        )
    except HEAutorizacionError as exc:
        return toast_error(request, str(exc), status_code=403)
    except ValueError as exc:
        return toast_error(request, str(exc))
    except asyncpg.PostgresError as exc:
        logger.error("Error BD aprobando horas extra: %s", exc)
        return toast_error(request, "Error al guardar la aprobacion", status_code=500)

    try:
        equipo = await get_equipo_ids_para_autorizacion_he(conn, aprobador_id, context)
        new_count = await db.count_horas_extra_pendientes(conn, equipo)
    except asyncpg.PostgresError as exc:
        logger.error("Error contando horas extra pendientes: %s", exc)
        new_count = 0

    svc = NotificationService()
    await svc.notify_horas_extra_aprobacion(
        conn,
        aprobador_nombre=context["user_name"],
        empleado_nombre=result["empleado_nombre"],
        empleado_email=result.get("empleado_email"),
        dias_aprobados=[
            {
                "fecha": result["fecha_laboral"],
                "minutos_aprobados": result["minutos_aprobados"],
            }
        ],
        comentario=result["comentario"],
    )

    return templates.TemplateResponse(
        request,
        "asistencia/partials/aprobacion_success.html",
        {
            "asistencia_id": str(asistencia_id),
            "new_count": new_count,
            "mensaje": f"Horas extra aprobadas para {result['empleado_nombre']}",
        },
        headers={"HX-Reswap": "none"},
    )


@router.post("/api/horas-extra/{asistencia_id}/omitir")
async def omitir_horas_extra(
    request: Request,
    asistencia_id: UUID,
    comentario: str = Form(...),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    if not context.get("user_db_id"):
        raise HTTPException(status_code=401)
    aprobador_id = UUID(str(context["user_db_id"]))

    try:
        result = await omitir_horas_extra_svc(
            conn, asistencia_id=asistencia_id, aprobador_id=aprobador_id, comentario=comentario
        )
    except HEAutorizacionError as exc:
        return toast_error(request, str(exc), status_code=403)
    except ValueError as exc:
        return toast_error(request, str(exc))
    except asyncpg.PostgresError as exc:
        logger.error("Error BD omitiendo horas extra: %s", exc)
        return toast_error(request, "Error al descartar el registro", status_code=500)

    try:
        equipo = await get_equipo_ids_para_autorizacion_he(conn, aprobador_id, context)
        new_count = await db.count_horas_extra_pendientes(conn, equipo)
    except asyncpg.PostgresError as exc:
        logger.error("Error contando horas extra pendientes: %s", exc)
        new_count = 0
    return templates.TemplateResponse(
        request,
        "asistencia/partials/omitir_success.html",
        {
            "asistencia_id": str(asistencia_id),
            "new_count": new_count,
            "mensaje": f"Registro descartado — {result['empleado_nombre']}",
        },
        headers={"HX-Reswap": "none"},
    )


@router.post("/api/horas-extra/{asistencia_id}/recuperar")
async def recuperar_horas_extra(
    request: Request,
    asistencia_id: UUID,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    if not context.get("user_db_id"):
        raise HTTPException(status_code=401)
    aprobador_id = UUID(str(context["user_db_id"]))

    try:
        await recuperar_horas_extra_svc(
            conn, asistencia_id=asistencia_id, aprobador_id=aprobador_id
        )
    except HEAutorizacionError as exc:
        return toast_error(request, str(exc), status_code=403)
    except ValueError as exc:
        return toast_error(request, str(exc))
    except asyncpg.PostgresError as exc:
        logger.error("Error BD recuperando horas extra: %s", exc)
        return toast_error(request, "Error al recuperar el registro", status_code=500)

    try:
        equipo = await get_equipo_ids_para_autorizacion_he(conn, aprobador_id, context)
        new_count = await db.count_horas_extra_pendientes(conn, equipo)
    except asyncpg.PostgresError as exc:
        logger.error("Error contando horas extra pendientes: %s", exc)
        new_count = 0
    return templates.TemplateResponse(
        request,
        "asistencia/partials/recuperar_success.html",
        {
            "asistencia_id": str(asistencia_id),
            "new_count": new_count,
        },
        headers={"HX-Reswap": "none"},
    )


@router.post("/api/horas-extra/{asistencia_id}/revertir-correccion")
async def revertir_correccion_horas_extra(
    asistencia_id: UUID,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_manager_access("rrhh", "editor"),
):
    """Correccion manual RH para dias 'feriado'/'aprobado' congelados por BioTime.

    Sin boton en UI todavia — invocar directamente (ver PENDIENTES_RH.md seccion 4).
    """
    if not context.get("user_db_id"):
        raise HTTPException(status_code=401)
    revertido_por = UUID(str(context["user_db_id"]))
    try:
        result = await revertir_dia_horas_extra_svc(
            conn, asistencia_id=asistencia_id, revertido_por=revertido_por
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except asyncpg.PostgresError as exc:
        logger.error("Error BD revirtiendo dia de horas extra: %s", exc)
        raise HTTPException(status_code=500, detail="Error al revertir el registro") from exc
    return JSONResponse(jsonable_encoder({
        "asistencia_id": str(asistencia_id),
        "empleado_nombre": result["empleado_nombre"],
        "fecha_laboral": result["fecha_laboral"],
        "estado_anterior": result["estado_anterior"],
    }))


@router.get("/horas-extra/{asistencia_id}/form")
async def horas_extra_form(
    request: Request,
    asistencia_id: UUID,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    if not context.get("user_db_id"):
        raise HTTPException(status_code=401)
    usuario_id = UUID(str(context["user_db_id"]))
    row = await db.get_asistencia_para_aprobar(conn, asistencia_id)
    if not row or row["usuario_id"] != usuario_id:
        raise HTTPException(status_code=404)
    if row["horas_extra_estado"] != "pendiente":
        raise HTTPException(status_code=400, detail="Este registro ya fue procesado")
    return templates.TemplateResponse(
        request,
        "asistencia/partials/horas_extra_form.html",
        {
            "asistencia_id": asistencia_id,
            "fecha_laboral": row["fecha_laboral"],
            "extra_fmt": format_minutes(row["minutos_extra"] or 0),
        },
    )


@router.post("/api/horas-extra/{asistencia_id}/solicitar")
async def solicitar_aprobacion_horas_extra(
    request: Request,
    asistencia_id: UUID,
    motivo: str = Form(...),
    evidencias: list[UploadFile] | None = File(default=None),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    if not context.get("user_db_id"):
        raise HTTPException(status_code=401)
    usuario_id = UUID(str(context["user_db_id"]))

    try:
        if evidencias:
            await subir_evidencias_he_y_solicitar_svc(
                conn,
                asistencia_id=asistencia_id,
                usuario_id=usuario_id,
                motivo=motivo,
                empleado_nombre=context["user_name"],
                evidencias=evidencias,
            )
        else:
            await solicitar_aprobacion_svc(
                conn,
                asistencia_id=asistencia_id,
                usuario_id=usuario_id,
                motivo=motivo,
                empleado_nombre=context["user_name"],
            )
    except ValueError as exc:
        return toast_error(request, str(exc))
    except (httpx.HTTPError, RuntimeError) as exc:
        logger.error("Error subiendo evidencias de horas extra a SharePoint: %s", exc)
        return toast_error(request, "No se pudo subir la evidencia a SharePoint", status_code=502)
    except asyncpg.PostgresError as exc:
        logger.error("Error BD solicitando aprobacion horas extra: %s", exc)
        return toast_error(request, "Error al enviar la solicitud", status_code=500)

    return templates.TemplateResponse(
        request,
        "asistencia/partials/solicitar_success.html",
        {
            "asistencia_id": str(asistencia_id),
            "mensaje": "Solicitud enviada al responsable.",
        },
    )


@router.get("/compensatorio/form")
async def compensatorio_form(
    request: Request,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    if not context.get("user_db_id"):
        raise HTTPException(status_code=401)
    usuario_id = UUID(str(context["user_db_id"]))
    bolsa = await get_he_bolsa_ctx(conn, usuario_id)
    return templates.TemplateResponse(
        request,
        "asistencia/partials/compensatorio_form.html",
        {"bolsa": bolsa, "context": context},
    )


@router.post("/api/compensatorio/solicitar")
async def solicitar_compensatorio(
    request: Request,
    fecha_descanso: date = Form(...),
    minutos_solicitados: int = Form(...),
    motivo: str = Form(...),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    if not context.get("user_db_id"):
        raise HTTPException(status_code=401)
    usuario_id = UUID(str(context["user_db_id"]))
    try:
        await solicitar_compensatorio_svc(
            conn,
            usuario_id=usuario_id,
            fecha_descanso=fecha_descanso,
            minutos_solicitados=minutos_solicitados,
            motivo=motivo,
        )
    except ValueError as exc:
        return toast_error(request, str(exc))
    except asyncpg.PostgresError as exc:
        logger.error("Error BD solicitando compensatorio: %s", exc)
        return toast_error(request, "Error al guardar la solicitud", status_code=500)

    bolsa = await get_he_bolsa_ctx(conn, usuario_id)
    return templates.TemplateResponse(
        request,
        "asistencia/partials/compensatorio_solicitud_response.html",
        {"bolsa": bolsa, "context": context, "mensaje": "Solicitud enviada para aprobacion."},
    )


@router.post("/api/compensatorio/{solicitud_id}/aprobar")
async def aprobar_compensatorio(
    request: Request,
    solicitud_id: UUID,
    comentario: str = Form(""),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    if not context.get("user_db_id"):
        raise HTTPException(status_code=401)
    aprobador_id = UUID(str(context["user_db_id"]))
    try:
        await aprobar_compensatorio_svc(
            conn,
            solicitud_id=solicitud_id,
            aprobador_id=aprobador_id,
            comentario=comentario,
        )
    except HEAutorizacionError as exc:
        return toast_error(request, str(exc), status_code=403)
    except ValueError as exc:
        return toast_error(request, str(exc))
    except asyncpg.PostgresError as exc:
        logger.error("Error BD aprobando compensatorio: %s", exc)
        return toast_error(request, "Error al aprobar la solicitud", status_code=500)
    return templates.TemplateResponse(
        request,
        "asistencia/partials/compensatorio_aprobacion_resultado.html",
        {"solicitud_id": solicitud_id, "mensaje": "Tiempo compensatorio aprobado."},
    )


@router.post("/api/compensatorio/{solicitud_id}/rechazar")
async def rechazar_compensatorio(
    request: Request,
    solicitud_id: UUID,
    comentario: str = Form(...),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    if not context.get("user_db_id"):
        raise HTTPException(status_code=401)
    aprobador_id = UUID(str(context["user_db_id"]))
    try:
        await rechazar_compensatorio_svc(
            conn,
            solicitud_id=solicitud_id,
            aprobador_id=aprobador_id,
            comentario=comentario,
        )
    except HEAutorizacionError as exc:
        return toast_error(request, str(exc), status_code=403)
    except ValueError as exc:
        return toast_error(request, str(exc))
    except asyncpg.PostgresError as exc:
        logger.error("Error BD rechazando compensatorio: %s", exc)
        return toast_error(request, "Error al rechazar la solicitud", status_code=500)
    return templates.TemplateResponse(
        request,
        "asistencia/partials/compensatorio_aprobacion_resultado.html",
        {"solicitud_id": solicitud_id, "mensaje": "Tiempo compensatorio rechazado."},
    )


@router.post("/api/compensatorio/{solicitud_id}/cancelar")
async def cancelar_compensatorio(
    request: Request,
    solicitud_id: UUID,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    if not context.get("user_db_id"):
        raise HTTPException(status_code=401)
    usuario_id = UUID(str(context["user_db_id"]))
    try:
        await cancelar_compensatorio_svc(conn, solicitud_id=solicitud_id, usuario_id=usuario_id)
    except ValueError as exc:
        return toast_error(request, str(exc))
    except asyncpg.PostgresError as exc:
        logger.error("Error BD cancelando compensatorio: %s", exc)
        return toast_error(request, "Error al cancelar la solicitud", status_code=500)
    bolsa = await get_he_bolsa_ctx(conn, usuario_id)
    return templates.TemplateResponse(
        request,
        "perfil/partials/_he_bolsa_widget_saldo.html",
        {"bolsa": bolsa, "context": context},
    )


@router.get("/evidencias/{documento_id}/preview")
async def preview_he_evidencia(
    documento_id: UUID,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    if not context.get("user_db_id"):
        raise HTTPException(status_code=401)
    usuario_id = UUID(str(context["user_db_id"]))
    evidencia = await db.get_he_evidencia_for_preview(conn, documento_id)
    if not evidencia:
        raise HTTPException(status_code=404, detail="Evidencia no encontrada")
    if user_has_module_access("rrhh", context, "editor"):
        equipo_visible_he, _ = await get_equipo_visible_he(conn, usuario_id, context, [])
    else:
        equipo_consulta = await get_equipo_ids(conn, usuario_id, context)
        equipo_visible_he, _ = await get_equipo_visible_he(conn, usuario_id, context, equipo_consulta)
    es_rrhh = user_has_module_access("rrhh", context, "viewer")
    if (
        evidencia["usuario_id"] != usuario_id
        and evidencia["usuario_id"] not in equipo_visible_he
        and not es_rrhh
    ):
        raise HTTPException(status_code=403, detail="No tienes permiso para ver esta evidencia")
    token = await get_ms_auth().get_application_token()
    if not token:
        raise HTTPException(status_code=502, detail="No se pudo conectar a SharePoint")
    sp_service = SharePointService(token)
    config = await sp_service._resolve_config(conn)
    sp_service.site_id = config.get("site_id")
    sp_service.drive_id = config.get("drive_id")
    content = await sp_service.download_bytes_direct_by_item_id(evidencia["drive_item_id"])
    filename = evidencia.get("nombre_archivo") or "evidencia"
    return StreamingResponse(
        BytesIO(content),
        media_type=evidencia.get("tipo_contenido") or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


_BOLSA_HE_PREFIJOS = {
    "propio": "Rep_BolsaHr",
    "equipo": "Rep_BolsaHrEquipo",
    "global": "Rep_BolsaHrFull",
}


@router.get("/api/horas-extra/reporte.xlsx")
async def reporte_bolsa_horas_extra(
    scope: str = Query("propio", pattern="^(propio|equipo|global)$"),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    if not context.get("user_db_id"):
        raise HTTPException(status_code=401)
    usuario_id = UUID(str(context["user_db_id"]))
    try:
        wb = await generar_reporte_bolsa_he_svc(conn, scope=scope, usuario_id=usuario_id, context=context)
    except PermissionError as exc:
        raise HTTPException(status_code=403) from exc
    prefijo = _BOLSA_HE_PREFIJOS[scope]
    filename = f"{prefijo}_{today_mx():%y%m%d}.xlsx"
    return excel_response(wb, filename)


@router.get("/api/saldo-inicial/pendientes")
async def saldo_inicial_pendientes(
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    if not context.get("user_db_id"):
        raise HTTPException(status_code=401)
    usuario_id = UUID(str(context["user_db_id"]))
    fecha_corte = await get_he_bolsa_fecha_corte(conn)
    if user_has_module_access("rrhh", context, "editor"):
        rows = await db.get_saldo_inicial_pendientes(conn, fecha_corte=fecha_corte)
    else:
        equipo = await vacaciones_db.get_empleados_donde_soy_jefe(conn, usuario_id)
        rows = await db.get_saldo_inicial_pendientes(conn, equipo, fecha_corte=fecha_corte)
    return JSONResponse(jsonable_encoder({"items": rows, "count": len(rows)}))


@router.post("/api/saldo-inicial/{usuario_id}/confirmar")
async def confirmar_saldo_inicial(
    request: Request,
    usuario_id: UUID,
    minutos: int = Form(...),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    if not context.get("user_db_id"):
        raise HTTPException(status_code=401)
    confirmado_por = UUID(str(context["user_db_id"]))
    try:
        await confirmar_saldo_inicial_svc(
            conn,
            usuario_id=usuario_id,
            minutos=minutos,
            confirmado_por=confirmado_por,
            context=context,
        )
    except ValueError as exc:
        return toast_error(request, str(exc))
    except asyncpg.PostgresError as exc:
        logger.error("Error BD confirmando saldo inicial HE: %s", exc)
        return toast_error(request, "Error al confirmar el saldo", status_code=500)
    return templates.TemplateResponse(
        request,
        "vacaciones/partials/saldo_inicial_confirmado.html",
        {"usuario_id": str(usuario_id)},
        headers={"HX-Reswap": "none"},
    )


@router.post("/api/bolsa/ajuste-manual")
async def ajuste_manual_bolsa(
    request: Request,
    usuario_id: UUID = Form(...),
    tipo: str = Form(...),
    minutos: int = Form(...),
    concepto: str = Form(...),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("rrhh", "admin"),
):
    if not context.get("user_db_id"):
        raise HTTPException(status_code=401)
    try:
        await ajuste_manual_svc(
            conn,
            usuario_id=usuario_id,
            tipo=tipo,
            minutos=minutos,
            concepto=concepto,
            creado_por=UUID(str(context["user_db_id"])),
        )
    except ValueError as exc:
        return toast_error(request, str(exc))
    except asyncpg.PostgresError as exc:
        logger.error("Error BD creando ajuste manual HE: %s", exc)
        return toast_error(request, "Error al guardar el ajuste", status_code=500)
    return toast_success(request, "Ajuste aplicado a la bolsa.")


@router.post("/api/saldo-inicial/notificar-arranque")
async def notificar_arranque_saldo_inicial(
    request: Request,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("rrhh", "admin"),
):
    svc = NotificationService()
    await svc.notify_he_saldo_inicial_arranque(conn)
    return toast_success(request, "Notificacion de arranque enviada.")


@router.post("/api/solicitudes-manuales/{solicitud_id}/aprobar")
async def aprobar_solicitud_manual(
    request: Request,
    solicitud_id: UUID,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("rrhh", "editor"),
):
    if not context.get("user_db_id"):
        raise HTTPException(status_code=401)
    aprobador_id = UUID(str(context["user_db_id"]))
    equipo = await get_equipo_ids(conn, aprobador_id, context)
    if not equipo:
        raise HTTPException(status_code=403)

    try:
        result = await aprobar_solicitud_manual_svc(
            conn,
            solicitud_id=solicitud_id,
            aprobador_id=aprobador_id,
            equipo_ids=equipo,
        )
    except ValueError as exc:
        return toast_error(request, str(exc))
    except asyncpg.PostgresError as exc:
        logger.error("Error BD aprobando solicitud manual: %s", exc)
        return toast_error(request, "Error al aprobar la solicitud", status_code=500)

    try:
        new_count = await db.count_solicitudes_manuales_pendientes_equipo(conn, equipo)
    except asyncpg.PostgresError as exc:
        logger.error("Error contando solicitudes manuales pendientes: %s", exc)
        new_count = 0

    return templates.TemplateResponse(
        request,
        "asistencia/partials/solicitud_manual_success.html",
        {
            "solicitud_id": str(solicitud_id),
            "new_count": new_count,
            "mensaje": f"Registro manual aprobado para {result['empleado_nombre']}",
        },
    )


@router.post("/api/solicitudes-manuales/{solicitud_id}/rechazar")
async def rechazar_solicitud_manual(
    request: Request,
    solicitud_id: UUID,
    comentario: str = Form(...),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("rrhh", "editor"),
):
    if not context.get("user_db_id"):
        raise HTTPException(status_code=401)
    aprobador_id = UUID(str(context["user_db_id"]))
    equipo = await get_equipo_ids(conn, aprobador_id, context)
    if not equipo:
        raise HTTPException(status_code=403)

    try:
        result = await rechazar_solicitud_manual_svc(
            conn,
            solicitud_id=solicitud_id,
            aprobador_id=aprobador_id,
            equipo_ids=equipo,
            comentario=comentario,
        )
    except ValueError as exc:
        return toast_error(request, str(exc))
    except asyncpg.PostgresError as exc:
        logger.error("Error BD rechazando solicitud manual: %s", exc)
        return toast_error(request, "Error al rechazar la solicitud", status_code=500)

    try:
        new_count = await db.count_solicitudes_manuales_pendientes_equipo(conn, equipo)
    except asyncpg.PostgresError as exc:
        logger.error("Error contando solicitudes manuales pendientes: %s", exc)
        new_count = 0

    return templates.TemplateResponse(
        request,
        "asistencia/partials/solicitud_manual_success.html",
        {
            "solicitud_id": str(solicitud_id),
            "new_count": new_count,
            "mensaje": f"Registro manual rechazado para {result['empleado_nombre']}",
        },
    )
