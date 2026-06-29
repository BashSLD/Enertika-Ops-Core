from __future__ import annotations

import json
import logging
from datetime import date
from uuid import UUID

import asyncpg
import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from core.database import get_db_connection
from core.permissions import require_manager_access, require_module_access
from core.security import get_current_user_context
from core.workflow.notification_service import NotificationService
from modules.asistencia import db_service as db
from modules.asistencia.constants import ASISTENCIA_ESTADOS
from modules.asistencia.schemas import SolicitudHorasExtraIn
from modules.asistencia.service import (
    aprobar_horas_extra_svc,
    bulk_aprobar_horas_extra_svc,
    get_equipo_ids,
    omitir_horas_extra_svc,
    recuperar_horas_extra_svc,
    solicitar_aprobacion_svc,
    sync_biotime_once,
)
from modules.shared.utils import format_minutes, toast_error

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


@router.post("/api/horas-extra/aprobar-bulk")
async def aprobar_horas_extra_bulk(
    request: Request,
    asistencia_ids: str = Form(...),
    minutos_aprobados: int = Form(...),
    comentario: str = Form(...),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("rrhh", "editor"),
):
    if not context.get("user_db_id"):
        raise HTTPException(status_code=401)
    try:
        ids = [UUID(x) for x in json.loads(asistencia_ids)]
    except (json.JSONDecodeError, ValueError):
        return toast_error(request, "Lista de registros inválida", status_code=400)
    aprobador_id = UUID(str(context["user_db_id"]))
    equipo = await get_equipo_ids(conn, aprobador_id, context)
    if not equipo:
        raise HTTPException(status_code=403)

    try:
        result = await bulk_aprobar_horas_extra_svc(
            conn,
            asistencia_ids=ids,
            aprobador_id=aprobador_id,
            minutos_aprobados=minutos_aprobados,
            comentario=comentario,
            equipo_ids=equipo,
        )
    except ValueError as exc:
        return toast_error(request, str(exc))
    except asyncpg.PostgresError as exc:
        logger.error("Error BD aprobando horas extra bulk: %s", exc)
        return toast_error(request, "Error al guardar las aprobaciones", status_code=500)

    try:
        new_count = await db.count_horas_extra_pendientes(conn, equipo)
    except asyncpg.PostgresError as exc:
        logger.error("Error contando horas extra pendientes: %s", exc)
        new_count = 0

    svc = NotificationService()
    await svc.notify_horas_extra_aprobacion(
        conn,
        aprobador_nombre=context["user_name"],
        empleado_nombre=result["empleado_nombre"],
        dias_aprobados=result["dias_aprobados"],
        comentario=result["comentario"],
    )

    return templates.TemplateResponse(
        request,
        "asistencia/partials/aprobacion_bulk_success.html",
        {
            "asistencia_ids": [str(aid) for aid in ids],
            "new_count": new_count,
            "mensaje": (
                f"{len(ids)} registros aprobados "
                f"para {result['empleado_nombre']}"
            ),
        },
        headers={"HX-Reswap": "none"},
    )


@router.post("/api/horas-extra/{asistencia_id}/aprobar")
async def aprobar_horas_extra(
    request: Request,
    asistencia_id: UUID,
    minutos_aprobados: int = Form(...),
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
        result = await aprobar_horas_extra_svc(
            conn,
            asistencia_id=asistencia_id,
            aprobador_id=aprobador_id,
            minutos_aprobados=minutos_aprobados,
            comentario=comentario,
            equipo_ids=equipo,
        )
    except ValueError as exc:
        return toast_error(request, str(exc))
    except asyncpg.PostgresError as exc:
        logger.error("Error BD aprobando horas extra: %s", exc)
        return toast_error(request, "Error al guardar la aprobacion", status_code=500)

    try:
        new_count = await db.count_horas_extra_pendientes(conn, equipo)
    except asyncpg.PostgresError as exc:
        logger.error("Error contando horas extra pendientes: %s", exc)
        new_count = 0

    svc = NotificationService()
    await svc.notify_horas_extra_aprobacion(
        conn,
        aprobador_nombre=context["user_name"],
        empleado_nombre=result["empleado_nombre"],
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
        result = await omitir_horas_extra_svc(
            conn, asistencia_id=asistencia_id, equipo_ids=equipo
        )
    except ValueError as exc:
        return toast_error(request, str(exc))
    except asyncpg.PostgresError as exc:
        logger.error("Error BD omitiendo horas extra: %s", exc)
        return toast_error(request, "Error al descartar el registro", status_code=500)

    try:
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
    _=require_module_access("rrhh", "editor"),
):
    if not context.get("user_db_id"):
        raise HTTPException(status_code=401)
    aprobador_id = UUID(str(context["user_db_id"]))
    equipo = await get_equipo_ids(conn, aprobador_id, context)
    if not equipo:
        raise HTTPException(status_code=403)

    try:
        await recuperar_horas_extra_svc(
            conn, asistencia_id=asistencia_id, equipo_ids=equipo
        )
    except ValueError as exc:
        return toast_error(request, str(exc))
    except asyncpg.PostgresError as exc:
        logger.error("Error BD recuperando horas extra: %s", exc)
        return toast_error(request, "Error al recuperar el registro", status_code=500)

    try:
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


@router.post("/api/horas-extra/{asistencia_id}/solicitar")
async def solicitar_aprobacion_horas_extra(
    request: Request,
    asistencia_id: UUID,
    payload: SolicitudHorasExtraIn,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    if not context.get("user_db_id"):
        raise HTTPException(status_code=401)
    usuario_id = UUID(str(context["user_db_id"]))

    try:
        result = await solicitar_aprobacion_svc(
            conn,
            asistencia_id=asistencia_id,
            usuario_id=usuario_id,
            motivo=payload.motivo,
        )
    except ValueError as exc:
        return toast_error(request, str(exc))
    except asyncpg.PostgresError as exc:
        logger.error("Error BD solicitando aprobacion horas extra: %s", exc)
        return toast_error(request, "Error al enviar la solicitud", status_code=500)

    jefes = await db.get_jefes_del_empleado(conn, usuario_id)
    tiene_director = any(j["rol_organizacional"] == "director" for j in jefes)
    svc_notif = NotificationService()
    if tiene_director:
        destinatarios = await svc_notif._get_rh_emails_cc(conn)
    else:
        destinatarios = {j["email"] for j in jefes if j.get("email")}
    await svc_notif.notify_horas_extra_solicitud(
        conn,
        empleado_nombre=context["user_name"],
        fecha_laboral=result["fecha_laboral"],
        extra_fmt=format_minutes(result["minutos_extra"]),
        motivo=payload.motivo,
        destinatarios=destinatarios,
        via_rh=tiene_director,
    )

    return templates.TemplateResponse(
        request,
        "asistencia/partials/solicitar_success.html",
        {
            "asistencia_id": str(asistencia_id),
            "mensaje": "Solicitud enviada al responsable.",
        },
        headers={"HX-Reswap": "none"},
    )
