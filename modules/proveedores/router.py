"""Router compartido de proveedores."""

import logging
import zipfile
from uuid import UUID

import asyncpg
import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse, Response

from core.database import get_db_connection
from core.permissions import require_any_module_access
from modules.shared.utils import content_disposition_header as _content_disposition

from .service import (
    DocumentoArchivo,
    DocumentoProveedorNoEncontrado,
    DocumentoProveedorSinArchivo,
    ProveedoresService,
    SharePointProveedorError,
    get_proveedores_service,
)

logger = logging.getLogger("ProveedoresModule")

router = APIRouter(
    prefix="/proveedores",
    tags=["Proveedores"],
)


def _is_inline_preview(media_type: str) -> bool:
    return media_type == "application/pdf" or media_type.startswith("image/")


def _archivo_response(archivo: DocumentoArchivo, disposition: str) -> Response:
    if archivo.redirect_url:
        return RedirectResponse(url=archivo.redirect_url, status_code=303)

    return Response(
        content=archivo.contenido or b"",
        media_type=archivo.media_type,
        headers={
            "Content-Disposition": _content_disposition(
                disposition,
                archivo.nombre_archivo,
            )
        },
    )


def _handle_sharepoint_error(exc: httpx.HTTPError) -> HTTPException:
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 404:
        return HTTPException(status_code=404, detail="Archivo no encontrado en SharePoint")
    return HTTPException(status_code=502, detail="Error descargando archivo desde SharePoint")


@router.get("/{id_proveedor}/documentos/{doc_id}/metadata")
async def get_documento_metadata(
    id_proveedor: UUID,
    doc_id: UUID,
    conn=Depends(get_db_connection),
    service: ProveedoresService = Depends(get_proveedores_service),
    _=require_any_module_access(["compras", "finanzas"]),
):
    try:
        return await service.get_documento_metadata(conn, id_proveedor, doc_id)
    except DocumentoProveedorNoEncontrado as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except asyncpg.PostgresError as exc:
        logger.exception("Error obteniendo metadata de documento proveedor")
        raise HTTPException(status_code=500, detail="Error consultando metadata del documento") from exc


@router.get("/{id_proveedor}/documentos/{doc_id}/preview")
async def preview_documento(
    id_proveedor: UUID,
    doc_id: UUID,
    conn=Depends(get_db_connection),
    service: ProveedoresService = Depends(get_proveedores_service),
    _=require_any_module_access(["compras", "finanzas"]),
):
    try:
        archivo = await service.get_documento_archivo(conn, id_proveedor, doc_id)
        disposition = "inline" if _is_inline_preview(archivo.media_type) else "attachment"
        return _archivo_response(archivo, disposition)
    except DocumentoProveedorNoEncontrado as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DocumentoProveedorSinArchivo as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SharePointProveedorError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except asyncpg.PostgresError as exc:
        logger.exception("Error consultando documento proveedor para preview")
        raise HTTPException(status_code=500, detail="Error consultando documento") from exc
    except httpx.HTTPError as exc:
        logger.exception("Error descargando documento proveedor desde SharePoint")
        raise _handle_sharepoint_error(exc) from exc
    except (RuntimeError, OSError) as exc:
        logger.exception("Error descargando documento proveedor")
        raise HTTPException(status_code=502, detail="Error descargando documento") from exc


@router.get("/{id_proveedor}/documentos/{doc_id}/download")
async def download_documento(
    id_proveedor: UUID,
    doc_id: UUID,
    conn=Depends(get_db_connection),
    service: ProveedoresService = Depends(get_proveedores_service),
    _=require_any_module_access(["compras", "finanzas"]),
):
    try:
        archivo = await service.get_documento_archivo(conn, id_proveedor, doc_id)
        return _archivo_response(archivo, "attachment")
    except DocumentoProveedorNoEncontrado as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DocumentoProveedorSinArchivo as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SharePointProveedorError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except asyncpg.PostgresError as exc:
        logger.exception("Error consultando documento proveedor para descarga")
        raise HTTPException(status_code=500, detail="Error consultando documento") from exc
    except httpx.HTTPError as exc:
        logger.exception("Error descargando documento proveedor desde SharePoint")
        raise _handle_sharepoint_error(exc) from exc
    except (RuntimeError, OSError) as exc:
        logger.exception("Error descargando documento proveedor")
        raise HTTPException(status_code=502, detail="Error descargando documento") from exc


@router.get("/{id_proveedor}/documentos/zip")
async def download_zip_expediente(
    id_proveedor: UUID,
    conn=Depends(get_db_connection),
    service: ProveedoresService = Depends(get_proveedores_service),
    _=require_any_module_access(["compras", "finanzas"]),
):
    try:
        archivo = await service.generar_zip_expediente(conn, id_proveedor)
        return _archivo_response(archivo, "attachment")
    except DocumentoProveedorNoEncontrado as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DocumentoProveedorSinArchivo as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SharePointProveedorError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except asyncpg.PostgresError as exc:
        logger.exception("Error consultando expediente de proveedor")
        raise HTTPException(status_code=500, detail="Error consultando expediente") from exc
    except httpx.HTTPError as exc:
        logger.exception("Error descargando expediente desde SharePoint")
        raise _handle_sharepoint_error(exc) from exc
    except (RuntimeError, OSError, zipfile.BadZipFile) as exc:
        logger.exception("Error generando ZIP de expediente")
        raise HTTPException(status_code=502, detail="Error generando ZIP") from exc
