# Archivo: core/materials/pdf_captura.py
"""
Captura asistida por PDF de precios del catalogo interno de materiales.

Reusa el extractor puro de core/bom/pdf_cotizacion_extractor.py (bytes -> dict
de candidatos texto/precio, sin match automatico) pero con persistencia propia:
el destino de la asignacion es una fila de tb_cat_materiales buscada entre el
catalogo completo, no un item de una cotizacion de BOM ya cargada. No hay
"cotizacion" que agrupe la sesion de trabajo -- el PDF se descarta tras
extraer candidatos, no se sube a SharePoint ni se archiva en ninguna tabla.

Actualiza precio_referencia/moneda directamente via actualizar_precios_bulk
(mismo helper que usa el importador Excel y la adjudicacion de cotizaciones de
BOM), sin escribir en tb_materiales_historial: esa tabla exige id_proveedor
(uuid NOT NULL con FK a tb_proveedores) y otros campos (cantidad, unidad_medida,
id_categoria, bom_item_id) que un candidato {texto, precio} de un PDF suelto no
tiene.
"""

import asyncio
import logging
from typing import List

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile

from core.bom.pdf_cotizacion_extractor import extraer_costos_cotizacion, validar_pdf_cotizacion
from core.config import settings
from core.database import get_db_connection
from core.permissions import require_module_access
from core.security import get_current_user_context
from .schemas import MaterialPdfAsignacion
from .service import MaterialsService, get_materials_service

logger = logging.getLogger("MaterialsPdfCaptura")

pdf_captura_router = APIRouter()


@pdf_captura_router.post("/internos/pdf-captura/extraer", include_in_schema=False)
async def extraer_pdf_captura_precios(
    archivo: UploadFile = File(...),
    _=require_module_access("compras", "editor"),
):
    """Extrae precios candidatos de un PDF de cotizacion de proveedor para
    asistir la captura manual. No persiste nada -- solo lectura, para mostrar
    candidatos en el modal (consumido por fetch() manual, no htmx swap)."""
    contenido = await archivo.read()
    try:
        validar_pdf_cotizacion(archivo.content_type, len(contenido), settings.PDF_MAX_UPLOAD_SIZE_MB)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return await asyncio.to_thread(
        extraer_costos_cotizacion, contenido, archivo.filename or "cotizacion.pdf"
    )


@pdf_captura_router.post("/internos/pdf-captura/guardar", include_in_schema=False)
async def guardar_pdf_captura_precios(
    asignaciones: List[MaterialPdfAsignacion] = Body(...),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: MaterialsService = Depends(get_materials_service),
    _=require_module_access("compras", "editor"),
):
    """Guarda en lote los candidatos que el usuario asigno a materiales del
    catalogo. Un material desactivado a medio proceso no lanza excepcion
    (mismo comportamiento que el importador Excel) -- se reporta el conteo
    real de filas afectadas para que no se pierda en silencio."""
    if not asignaciones:
        raise HTTPException(status_code=400, detail="No hay asignaciones para guardar")

    actualizado_por = context.get("user_db_id")
    registros = [
        {
            "id": a.id_material,
            "precio_referencia": a.precio,
            "moneda": a.moneda,
            "actualizado_por": actualizado_por,
        }
        for a in asignaciones
    ]
    async with conn.transaction():
        actualizados = await service.actualizar_precios_referencia_bulk(conn, registros)

    return {"enviados": len(asignaciones), "actualizados": actualizados}
