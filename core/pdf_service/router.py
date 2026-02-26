# core/pdf_service/router.py
"""
Endpoints compartidos de generacion PDF.
Accesibles desde cualquier modulo con sesion activa.
"""
import logging
from typing import List

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response

from core.security import get_current_user_context
from .image_processor import ImageProcessor
from .schemas import VisitaObraData
from .service import PDFService, get_pdf_service

logger = logging.getLogger("PDFRouter")

router = APIRouter(prefix="/pdf", tags=["Reportes PDF"])


@router.post("/visita-obra/generar")
async def generar_visita_obra(
    request: Request,
    data: str = Form(...),
    images: List[UploadFile] = File(default=[]),
    context=Depends(get_current_user_context),
    service: PDFService = Depends(get_pdf_service),
):
    """
    Genera PDF de Formato de Visita a Obra.

    Body (multipart/form-data):
        data: JSON string con los campos de VisitaObraData.
        images: Archivos de imagen (opcional).

    Retorna el PDF como attachment.
    """
    if not context.get("user_name") or context.get("user_name") == "Usuario":
        return JSONResponse(status_code=401, content={"error": "Sesion requerida"})

    try:
        visita = VisitaObraData.model_validate_json(data)
    except Exception as exc:
        logger.warning("Datos de visita invalidos: %s", exc)
        return JSONResponse(status_code=422, content={"error": str(exc)})

    # Leer, validar y procesar imagenes en un solo pass
    raw_images: List[bytes] = []
    for upload in images:
        raw = await upload.read()
        if not raw:
            continue
        error = ImageProcessor.validate_image_file(
            raw,
            upload.content_type or "",
            upload.filename or "",
        )
        if error:
            return JSONResponse(
                status_code=400,
                content={"error": f"{upload.filename}: {error}"},
            )
        raw_images.append(raw)

    images_b64: List[str] = []
    if raw_images:
        images_b64, _ = ImageProcessor.process_images_for_pdf(raw_images)

    try:
        pdf_bytes = await service.generate(
            "visita_obra.html",
            {
                "data": visita,
                "images": images_b64,
                "total_images": len(images_b64),
            },
        )
    except (ValueError, Exception) as exc:
        logger.error("Error generando PDF visita obra: %s", exc)
        return JSONResponse(status_code=500, content={"error": "Error generando PDF"})

    filename = service.generate_filename("visita_obra", visita.nombre_planta)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
