"""
Endpoints de integración con servicios externos.
Actualmente: navegador de carpetas SharePoint para selector de destino.
"""
import logging
from typing import Optional
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from core.database import DB_REPORT_ERRORS, get_db_connection
from core.security import get_current_user_context
from core.permissions import require_any_module_access
from .schemas import SharePointMapeoManual
from .service import get_integrations_service

logger = logging.getLogger("Integrations.Router")

templates = Jinja2Templates(directory="templates")

router = APIRouter(prefix="/integraciones", tags=["Integraciones"])

_MODULOS_PROYECTO = ["proyectos", "ingenieria", "construccion", "oym"]


@router.get("/sharepoint/proyecto/{id_proyecto}/modal-picker", include_in_schema=False)
async def modal_picker_carpeta_proyecto(
    request: Request,
    id_proyecto: UUID,
    proyecto_id_estandar: Optional[str] = Query(None),
    context=Depends(get_current_user_context),
    _=require_any_module_access(_MODULOS_PROYECTO, "viewer", allow_org_roles={"director"}),
):
    """Renderiza el modal de selección manual de carpeta SharePoint para un proyecto."""
    return templates.TemplateResponse(
        request,
        "shared/modals/sharepoint_folder_picker_modal.html",
        {"id_proyecto": id_proyecto, "proyecto_id_estandar": proyecto_id_estandar or ""},
    )


@router.get("/sharepoint/carpetas", include_in_schema=False)
async def listar_carpetas_sp(
    folder_id: Optional[str] = Query(None),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    service=Depends(get_integrations_service),
    _=require_any_module_access(_MODULOS_PROYECTO, "viewer", allow_org_roles={"director"}),
):
    """
    Lista subcarpetas de un folder en el SharePoint de Visitas a Obra.
    folder_id=None → raíz del drive configurado.
    Retorna JSON: {folders: [{id, name}], folder_id_actual}
    """
    try:
        folders = await service.list_visitas_sharepoint_folders(conn, folder_id)
        return {"folders": folders, "folder_id_actual": folder_id}
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"error": str(exc)},
        )
    except RuntimeError as exc:
        return JSONResponse(status_code=503, content={"error": str(exc)})
    except DB_REPORT_ERRORS as exc:
        logger.exception("Error BD listando carpetas SP visitas")
        return JSONResponse(status_code=500, content={"error": "Error al leer configuracion"})
    except httpx.HTTPError as exc:
        logger.error("Error conectando con SharePoint: %s", exc, exc_info=True)
        return JSONResponse(status_code=500, content={"error": "Error al conectar con SharePoint"})


@router.get("/sharepoint/proyecto/{id_proyecto}/resolver", include_in_schema=False)
async def resolver_carpeta_proyecto(
    id_proyecto: UUID,
    proyecto_id_estandar: str = Query(...),
    nombre_proyecto: Optional[str] = Query(None),
    nombre_corto: Optional[str] = Query(None),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    service=Depends(get_integrations_service),
    _=require_any_module_access(_MODULOS_PROYECTO, "viewer", allow_org_roles={"director"}),
):
    """
    Resuelve la carpeta de SharePoint de un proyecto: mapeo ya persistido,
    o búsqueda en la raíz del drive por proyecto_id_estandar y luego por nombre.
    Retorna JSON: {status: MAPEADO|SIN_MATCH|AMBIGUO, web_url?, fallback_web_url?, fallback_label?}
    """
    try:
        resultado = await service.resolver_carpeta_proyecto(
            conn, id_proyecto, proyecto_id_estandar, nombre_proyecto, nombre_corto
        )
        return resultado
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    except RuntimeError as exc:
        return JSONResponse(status_code=503, content={"error": str(exc)})
    except DB_REPORT_ERRORS as exc:
        logger.exception("Error BD resolviendo carpeta SP proyecto=%s", id_proyecto)
        return JSONResponse(status_code=500, content={"error": "Error al leer configuracion"})
    except httpx.HTTPError as exc:
        logger.error("Error conectando con SharePoint: %s", exc, exc_info=True)
        return JSONResponse(status_code=500, content={"error": "Error al conectar con SharePoint"})


@router.post("/sharepoint/proyecto/{id_proyecto}/mapeo", include_in_schema=False)
async def guardar_mapeo_carpeta_proyecto(
    id_proyecto: UUID,
    body: SharePointMapeoManual,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    service=Depends(get_integrations_service),
    _=require_any_module_access(_MODULOS_PROYECTO, "editor", allow_org_roles={"director"}),
):
    """
    Persiste una selección manual de carpeta SharePoint para el proyecto.
    Si body.corregir_nombre viene en True, además renombra la carpeta en
    SharePoint al estándar del proyecto (siempre opt-in explícito del usuario,
    nunca automático).
    """
    try:
        resultado = await service.set_mapeo_manual(
            conn, id_proyecto, body.folder_id, body.corregir_nombre
        )
        return resultado
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    except RuntimeError as exc:
        return JSONResponse(status_code=503, content={"error": str(exc)})
    except DB_REPORT_ERRORS as exc:
        logger.exception("Error BD guardando mapeo SP proyecto=%s", id_proyecto)
        return JSONResponse(status_code=500, content={"error": "Error al guardar el mapeo"})
    except httpx.HTTPError as exc:
        logger.error("Error conectando con SharePoint: %s", exc, exc_info=True)
        return JSONResponse(status_code=500, content={"error": "Error al conectar con SharePoint"})
