# core/pdf_service/router.py
"""
Endpoints compartidos de generacion PDF.
Accesibles desde cualquier modulo con sesion activa.
"""
import asyncio
import logging
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response

from core.security import get_current_user_context
from .image_processor import ImageProcessor
from .schemas import VisitaObraData
from .service import PDFService, get_pdf_service

logger = logging.getLogger("PDFRouter")

router = APIRouter(prefix="/pdf", tags=["Reportes PDF"])


async def _subir_fotos_sharepoint(
    images_optimized: List[bytes],
    folder_path: str,
    app_token: str,
    pool,
) -> str:
    """
    Sube imagenes a SharePoint en batches de 5 concurrentes.
    Retorna el webUrl de la carpeta, o cadena vacia si falla.
    Config SP se resuelve una sola vez (regla asyncpg: no concurrent en mismo conn).
    """
    from core.integrations.sharepoint import SharePointService

    sp = SharePointService(access_token=app_token)

    async with pool.acquire() as conn:
        config = await sp._resolve_config(conn)
    sp.drive_id = config.get("drive_id") or sp.drive_id
    sp.site_id = config.get("site_id") or sp.site_id

    BATCH = 5
    for batch_start in range(0, len(images_optimized), BATCH):
        batch = images_optimized[batch_start:batch_start + BATCH]
        tasks = [
            sp.upload_bytes_direct(img, f"foto_{batch_start + j + 1:02d}.jpg", folder_path)
            for j, img in enumerate(batch)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for j, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning(
                    "[VISITA_SP] Error subiendo foto_%02d: %s",
                    batch_start + j + 1,
                    result,
                )

    return await sp.get_folder_web_url(folder_path)


async def _enviar_email_visita_obra(
    pdf_bytes: bytes,
    filename: str,
    images_optimized: List[bytes],
    visita: VisitaObraData,
    from_email: str,
) -> None:
    """
    Envía email con PDF e imágenes adjuntas al generar un reporte de Visita a Obra.
    Si el envío completo falla, sube las fotos a SharePoint y envía email ligero con link.
    Se ejecuta como background task — los errores se loguean sin afectar la respuesta.
    """
    from core.database import get_db_pool
    from core.microsoft import MicrosoftAuth

    try:
        pool = await get_db_pool()
    except Exception:
        logger.warning("[VISITA_EMAIL] Pool de BD no disponible, correo omitido")
        return

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT valor FROM tb_configuracion_global WHERE clave = 'visita_obra_destinatarios'"
        )
        destinatarios_raw = (row["valor"] if row else "") or ""
        destinatarios = [
            e.strip()
            for e in destinatarios_raw.replace(";", ",").split(",")
            if e.strip()
        ]

    if not destinatarios:
        logger.info("[VISITA_EMAIL] Sin destinatarios configurados, correo omitido")
        return

    fecha_display = visita.fecha or "—"
    ubicacion_display = visita.ubicacion or "—"
    fotos_count = len(images_optimized)
    subject = f"Visita a Obra: {visita.id_proyecto} — {visita.nombre_planta} (Visita No. {visita.numero_visita})"

    def _build_html(sp_link: str = None) -> str:
        if sp_link:
            fila_fotos = f"""
                <tr>
                    <td style="padding: 8px 12px; font-weight: bold; background: #fef3c7; border: 1px solid #e5e7eb;">Fotografias</td>
                    <td style="padding: 8px 12px; border: 1px solid #e5e7eb; background: #fef3c7;">
                        <a href="{sp_link}" style="color: #0A2463; font-weight: bold;">
                            Ver {fotos_count} fotografia{"s" if fotos_count != 1 else ""} en SharePoint
                        </a>
                    </td>
                </tr>"""
            nota_fotos = f"""
            <div style="background: #fef3c7; border-left: 4px solid #f59e0b; padding: 10px 14px; margin-top: 16px; border-radius: 4px; font-size: 12px; color: #92400e;">
                Las {fotos_count} fotografias no pudieron enviarse como adjuntos por el volumen de archivos.
                Se encuentran disponibles en la carpeta de SharePoint indicada arriba.
            </div>"""
            pie = "El reporte PDF completo se encuentra adjunto. Las fotografias estan disponibles en SharePoint."
        else:
            fila_fotos = f"""
                <tr>
                    <td style="padding: 8px 12px; font-weight: bold; background: #f3f4f6; border: 1px solid #e5e7eb;">Fotografias adjuntas</td>
                    <td style="padding: 8px 12px; border: 1px solid #e5e7eb;">{fotos_count} imagen{"es" if fotos_count != 1 else ""}</td>
                </tr>"""
            nota_fotos = ""
            pie = "El reporte PDF completo y las fotografias se encuentran adjuntos."

        return f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background: #00BABB; padding: 20px 24px; border-radius: 8px 8px 0 0;">
            <h2 style="color: #ffffff; margin: 0; font-size: 18px;">Formato de Visita a Obra</h2>
            <p style="color: #e0fafa; margin: 4px 0 0; font-size: 13px;">Reporte No. {visita.numero_visita}</p>
        </div>
        <div style="background: #f9fafb; padding: 24px; border: 1px solid #e5e7eb; border-top: none; border-radius: 0 0 8px 8px;">
            <table style="width: 100%; border-collapse: collapse; font-size: 14px; color: #374151;">
                <tr>
                    <td style="padding: 8px 12px; font-weight: bold; width: 40%; background: #f3f4f6; border: 1px solid #e5e7eb;">Nombre del lugar</td>
                    <td style="padding: 8px 12px; border: 1px solid #e5e7eb;">{visita.nombre_planta}</td>
                </tr>
                <tr>
                    <td style="padding: 8px 12px; font-weight: bold; background: #f3f4f6; border: 1px solid #e5e7eb;">ID de Proyecto</td>
                    <td style="padding: 8px 12px; border: 1px solid #e5e7eb;">{visita.id_proyecto}</td>
                </tr>
                <tr>
                    <td style="padding: 8px 12px; font-weight: bold; background: #f3f4f6; border: 1px solid #e5e7eb;">Direccion / Ubicacion</td>
                    <td style="padding: 8px 12px; border: 1px solid #e5e7eb;">{ubicacion_display}</td>
                </tr>
                <tr>
                    <td style="padding: 8px 12px; font-weight: bold; background: #f3f4f6; border: 1px solid #e5e7eb;">Fecha de visita</td>
                    <td style="padding: 8px 12px; border: 1px solid #e5e7eb;">{fecha_display}</td>
                </tr>
                <tr>
                    <td style="padding: 8px 12px; font-weight: bold; background: #f3f4f6; border: 1px solid #e5e7eb;">Responsable interno</td>
                    <td style="padding: 8px 12px; border: 1px solid #e5e7eb;">{visita.persona_responsable_interna}</td>
                </tr>
                <tr>
                    <td style="padding: 8px 12px; font-weight: bold; background: #f3f4f6; border: 1px solid #e5e7eb;">Responsable de obra</td>
                    <td style="padding: 8px 12px; border: 1px solid #e5e7eb;">{visita.responsable_obra}</td>
                </tr>
                {fila_fotos}
            </table>
            {nota_fotos}
            <p style="font-size: 12px; color: #9ca3af; margin-top: 20px;">
                Este correo fue enviado desde ECO.
                {pie}
            </p>
        </div>
    </div>
    """

    # Adjuntos completos: PDF + todas las fotos
    attachments_full: List[dict] = [
        {"name": filename, "content_bytes": pdf_bytes, "contentType": "application/pdf"}
    ]
    for i, img_bytes in enumerate(images_optimized, 1):
        attachments_full.append(
            {"name": f"foto_{i:02d}.jpg", "content_bytes": img_bytes, "contentType": "image/jpeg"}
        )

    try:
        ms_auth = MicrosoftAuth()
        app_token = await ms_auth.get_application_token()
        if not app_token:
            logger.error("[VISITA_EMAIL] No se pudo obtener token de aplicacion")
            return

        # Intento 1: email completo con fotos adjuntas
        success, msg = await ms_auth.send_email_with_attachments(
            access_token=app_token,
            from_email=from_email,
            subject=subject,
            body=_build_html(),
            recipients=destinatarios,
            attachments_files=attachments_full,
        )
        if success:
            logger.info(
                "[VISITA_EMAIL] Correo enviado - proyecto=%s destinatarios=%d fotos=%d",
                visita.id_proyecto, len(destinatarios), fotos_count,
            )
            return

        # Intento 2 (fallback): subir fotos a SharePoint + email ligero con link
        logger.warning(
            "[VISITA_EMAIL] Envio con adjuntos fallo (%s) — activando fallback SharePoint",
            msg,
        )
        sp_folder = f"Visitas a Obra/{visita.id_proyecto}/Visita_{visita.numero_visita}"
        sp_link = ""
        try:
            sp_link = await _subir_fotos_sharepoint(images_optimized, sp_folder, app_token, pool)
            logger.info(
                "[VISITA_EMAIL] %d fotos subidas a SharePoint: %s",
                fotos_count, sp_link or "(sin url)",
            )
        except Exception as sp_exc:
            logger.error("[VISITA_EMAIL] Error subiendo fotos a SharePoint: %s", sp_exc, exc_info=True)

        success2, msg2 = await ms_auth.send_email_with_attachments(
            access_token=app_token,
            from_email=from_email,
            subject=subject,
            body=_build_html(sp_link=sp_link or None),
            recipients=destinatarios,
            attachments_files=[
                {"name": filename, "content_bytes": pdf_bytes, "contentType": "application/pdf"}
            ],
        )
        if success2:
            logger.info(
                "[VISITA_EMAIL] Fallback enviado - proyecto=%s fotos_sharepoint=%s",
                visita.id_proyecto, sp_link or "no disponible",
            )
        else:
            logger.error("[VISITA_EMAIL] Fallback tambien fallo: %s", msg2)

    except Exception as exc:
        logger.error("[VISITA_EMAIL] Error inesperado al enviar correo: %s", exc, exc_info=True)


@router.post("/visita-obra/generar")
async def generar_visita_obra(
    request: Request,
    background_tasks: BackgroundTasks,
    data: str = Form(...),
    images: List[UploadFile] = File(default=[]),
    context=Depends(get_current_user_context),
    service: PDFService = Depends(get_pdf_service),
):
    """
    Genera PDF de Formato de Visita a Obra y envía correo con adjuntos en background.

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

    # Leer, validar y optimizar imágenes en un solo pass
    # Guardamos los bytes optimizados para adjuntar al correo
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
    images_optimized: List[bytes] = []
    if raw_images:
        for img_bytes in raw_images:
            optimized_bytes, _ = ImageProcessor.optimize_image(img_bytes)
            images_b64.append(ImageProcessor.image_to_base64(optimized_bytes))
            images_optimized.append(optimized_bytes)

    try:
        pdf_bytes = await service.generate(
            "visita_obra.html",
            {
                "data": visita,
                "images": images_b64,
                "total_images": len(images_b64),
            },
        )
    except Exception as exc:
        logger.error("Error generando PDF visita obra: %s", exc)
        return JSONResponse(status_code=500, content={"error": "Error generando PDF"})

    filename = service.generate_filename("visita_obra", visita.nombre_planta)

    # Enviar correo en background — no bloquea la descarga del PDF
    from_email = context.get("user_email") or context.get("email") or ""
    if from_email:
        background_tasks.add_task(
            _enviar_email_visita_obra,
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

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
