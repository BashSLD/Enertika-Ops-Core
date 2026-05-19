from __future__ import annotations

import logging
from datetime import date
from uuid import UUID

import asyncpg
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from core.database import get_db_connection
from core.permissions import require_manager_access, require_module_access
from core.security import get_current_user_context
from core.workflow.notification_service import NotificationService
from modules.asistencia import db_service as db
from modules.asistencia.constants import ASISTENCIA_ESTADOS
from modules.asistencia.schemas import AprobacionHorasExtraIn, BulkAprobacionIn
from modules.asistencia.service import (
    aprobar_horas_extra_svc,
    bulk_aprobar_horas_extra_svc,
    get_equipo_ids,
    sync_biotime_once,
)
from modules.shared.utils import toast_error

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
        estado=estado,
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
    payload: BulkAprobacionIn,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("vacaciones", "editor"),
):
    aprobador_id = UUID(str(context["user_db_id"]))
    equipo = await get_equipo_ids(conn, aprobador_id, context)

    try:
        result = await bulk_aprobar_horas_extra_svc(
            conn,
            asistencia_ids=payload.asistencia_ids,
            aprobador_id=aprobador_id,
            minutos_aprobados=payload.minutos_aprobados,
            comentario=payload.comentario,
            equipo_ids=equipo,
        )
    except ValueError as exc:
        return toast_error(request, str(exc))
    except asyncpg.PostgresError as exc:
        logger.error("Error BD aprobando horas extra bulk: %s", exc)
        return toast_error(request, "Error al guardar las aprobaciones", status_code=500)

    new_count = await db.count_horas_extra_pendientes(conn, equipo)

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
            "asistencia_ids": [str(aid) for aid in payload.asistencia_ids],
            "new_count": new_count,
            "mensaje": (
                f"{len(payload.asistencia_ids)} registros aprobados "
                f"para {result['empleado_nombre']}"
            ),
        },
        headers={"HX-Reswap": "none"},
    )


@router.post("/api/horas-extra/{asistencia_id}/aprobar")
async def aprobar_horas_extra(
    request: Request,
    asistencia_id: UUID,
    payload: AprobacionHorasExtraIn,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("vacaciones", "editor"),
):
    aprobador_id = UUID(str(context["user_db_id"]))
    equipo = await get_equipo_ids(conn, aprobador_id, context)

    try:
        result = await aprobar_horas_extra_svc(
            conn,
            asistencia_id=asistencia_id,
            aprobador_id=aprobador_id,
            minutos_aprobados=payload.minutos_aprobados,
            comentario=payload.comentario,
            equipo_ids=equipo,
        )
    except ValueError as exc:
        return toast_error(request, str(exc))
    except asyncpg.PostgresError as exc:
        logger.error("Error BD aprobando horas extra: %s", exc)
        return toast_error(request, "Error al guardar la aprobacion", status_code=500)

    new_count = await db.count_horas_extra_pendientes(conn, equipo)

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
