"""
Endpoints de integración con servicios externos.
Actualmente: navegador de carpetas SharePoint para selector de destino.
"""
import logging
from typing import Optional

import asyncpg
import httpx
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from core.database import get_db_connection
from core.security import get_current_user_context
from .service import get_integrations_service

logger = logging.getLogger("Integrations.Router")

router = APIRouter(prefix="/integraciones", tags=["Integraciones"])


@router.get("/sharepoint/carpetas", include_in_schema=False)
async def listar_carpetas_sp(
    folder_id: Optional[str] = Query(None),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    service=Depends(get_integrations_service),
):
    """
    Lista subcarpetas de un folder en el SharePoint de Visitas a Obra.
    folder_id=None → raíz del drive configurado.
    Retorna JSON: {folders: [{id, name}], folder_id_actual}
    """
    if not context.get("user_name") or context.get("user_name") == "Usuario":
        return JSONResponse(status_code=401, content={"error": "Sesion requerida"})

    try:
        folders = await service.list_visitas_sharepoint_folders(conn, folder_id)
        return {"folders": folders, "folder_id_actual": folder_id}
    except ValueError as exc:
        return JSONResponse(
            status_code=422,
            content={"error": str(exc)},
        )
    except RuntimeError as exc:
        return JSONResponse(status_code=503, content={"error": str(exc)})
    except asyncpg.PostgresError as exc:
        logger.exception("Error BD listando carpetas SP visitas")
        return JSONResponse(status_code=500, content={"error": "Error al leer configuracion"})
    except httpx.HTTPError as exc:
        logger.error("Error conectando con SharePoint: %s", exc, exc_info=True)
        return JSONResponse(status_code=500, content={"error": "Error al conectar con SharePoint"})
