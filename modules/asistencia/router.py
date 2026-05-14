from __future__ import annotations

import logging
from datetime import date
from uuid import UUID

import asyncpg
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from core.database import get_db_connection
from core.permissions import require_manager_access, require_module_access
from modules.asistencia import db_service as db
from modules.asistencia.constants import ASISTENCIA_ESTADOS
from modules.asistencia.service import sync_biotime_once

logger = logging.getLogger("asistencia.router")
router = APIRouter(prefix="/asistencia", tags=["asistencia"])


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
        usuario_id=usuario_id,
        sucursal_id=sucursal_id,
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
