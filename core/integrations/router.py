"""
Endpoints de integración con servicios externos.
Actualmente: navegador de carpetas SharePoint para selector de destino.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from core.database import get_db_connection
from core.microsoft import get_ms_auth
from core.security import get_current_user_context
from .sharepoint import SharePointService

logger = logging.getLogger("Integrations.Router")

router = APIRouter(prefix="/integraciones", tags=["Integraciones"])


@router.get("/sharepoint/carpetas", include_in_schema=False)
async def listar_carpetas_sp(
    folder_id: Optional[str] = Query(None),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    """
    Lista subcarpetas de un folder en el SharePoint de Visitas a Obra.
    folder_id=None → raíz del drive configurado.
    Retorna JSON: {folders: [{id, name}], folder_id_actual}
    """
    if not context.get("user_name") or context.get("user_name") == "Usuario":
        return JSONResponse(status_code=401, content={"error": "Sesion requerida"})

    rows = await conn.fetch(
        "SELECT clave, valor FROM tb_configuracion_global WHERE clave IN ('SP_VISITAS_SITE_ID', 'SP_VISITAS_DRIVE_ID')"
    )
    config = {r["clave"]: (r["valor"] or "").strip() for r in rows}
    site_id = config.get("SP_VISITAS_SITE_ID", "")
    drive_id = config.get("SP_VISITAS_DRIVE_ID", "")

    if not site_id and not drive_id:
        return JSONResponse(
            status_code=422,
            content={"error": "SharePoint de Visitas no configurado. Configura SP_VISITAS_SITE_ID y SP_VISITAS_DRIVE_ID en Admin."},
        )

    try:
        ms_auth = get_ms_auth()
        app_token = await ms_auth.get_application_token()
        if not app_token:
            return JSONResponse(status_code=503, content={"error": "No se pudo obtener token de Microsoft"})

        sp = SharePointService(access_token=app_token)
        folders = await sp.list_folder_children(
            drive_id=drive_id,
            site_id=site_id,
            folder_id=folder_id or None,
        )
        return {"folders": folders, "folder_id_actual": folder_id}

    except Exception as exc:
        logger.error("Error listando carpetas SP visitas: %s", exc)
        return JSONResponse(status_code=500, content={"error": "Error al conectar con SharePoint"})
