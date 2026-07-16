# core/pdf_service/router.py
"""
Endpoints compartidos de generacion PDF.
Accesibles desde cualquier modulo con sesion activa.
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.templating import Jinja2Templates

from core.security import get_current_user_context
from core.permissions import require_authenticated_session
from .service import PDFService, get_pdf_service

logger = logging.getLogger("PDFRouter")

router = APIRouter(prefix="/pdf", tags=["Reportes PDF"])
templates = Jinja2Templates(directory="templates")


@router.get("/visita-obra/modal", include_in_schema=False)
async def get_visita_obra_modal(
    request: Request,
    context=Depends(get_current_user_context),
    _=require_authenticated_session(),
):
    """Modal compartido de Visita a Obra, accesible desde proyectos y construccion."""
    return templates.TemplateResponse(
        request,
        "shared/modals/visita_obra_modal.html",
        {"user_name": context.get("user_name")},
    )


@router.post("/visita-obra/generar")
async def generar_visita_obra(
    request: Request,
    background_tasks: BackgroundTasks,
    data: str = Form(...),
    sp_folder_id: str = Form(default=""),
    images: Optional[List[UploadFile]] = File(default=None),
    context=Depends(get_current_user_context),
    service: PDFService = Depends(get_pdf_service),
    _=require_authenticated_session(),
):
    """
    Genera PDF de Formato de Visita a Obra.

    Body multipart/form-data:
        data: JSON string con campos de VisitaObraData.
        images: archivos de imagen opcionales.
    """
    try:
        visita = service.parse_visita_obra_data(data)
    except ValueError as exc:
        logger.warning("Datos de visita invalidos: %s", exc)
        return JSONResponse(status_code=422, content={"error": str(exc)})

    try:
        pdf_bytes, filename, images_optimized = await service.generate_visita_obra_report(
            visita,
            images or [],
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    except RuntimeError as exc:
        logger.error("Error generando PDF visita obra: %s", exc)
        return JSONResponse(status_code=500, content={"error": "Error generando PDF"})

    from_email = context.get("user_email") or context.get("email") or ""
    if from_email:
        background_tasks.add_task(
            service.send_visita_obra_email,
            pdf_bytes,
            filename,
            images_optimized,
            visita,
            from_email,
        )
    else:
        logger.warning(
            "[VISITA_EMAIL] Usuario sin email en contexto, correo omitido - proyecto=%s",
            visita.id_proyecto,
        )

    target_folder = sp_folder_id.strip()
    if target_folder:
        background_tasks.add_task(
            service.save_visita_obra_pdf_sharepoint,
            pdf_bytes,
            filename,
            target_folder,
            visita,
        )

    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    if target_folder:
        headers["X-SP-Guardado"] = "1"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers=headers,
    )
