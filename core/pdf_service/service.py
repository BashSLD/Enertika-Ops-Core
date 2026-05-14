# core/pdf_service/service.py
"""
Motor compartido de generacion PDF usando WeasyPrint.
Renderiza templates Jinja2 a HTML y convierte a PDF en un executor (async-safe).
"""
import asyncio
import logging
import re
from pathlib import Path
from typing import Any, List, Optional

import asyncpg
import httpx
import jinja2

from core.database import get_db_pool
from core.integrations.sharepoint import SharePointService
from core.microsoft import MicrosoftAuth
from core.timezone import now_mx

from .db_service import PDFDBService, get_pdf_db_service
from .image_processor import ImageProcessor
from .schemas import VisitaObraData

logger = logging.getLogger("PDFService")

# Directorio base de templates PDF — relativo al workspace
TEMPLATES_PDF_PATH = Path(__file__).parent.parent.parent / "templates" / "pdf"
EMAIL_TEMPLATES_PATH = Path(__file__).parent.parent.parent / "templates"


class PDFService:
    """Singleton para generacion de PDFs con WeasyPrint."""

    def __init__(self, db: PDFDBService | None = None) -> None:
        self.db = db or get_pdf_db_service()
        self.ms_auth = MicrosoftAuth()
        self._env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(TEMPLATES_PDF_PATH)),
            autoescape=True,
        )
        self._email_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(EMAIL_TEMPLATES_PATH)),
            autoescape=True,
        )

    async def generate(
        self,
        template_name: str,
        context: dict,
        base_url: str = None,
    ) -> bytes:
        """
        Renderiza un template PDF y retorna los bytes del PDF generado.

        Args:
            template_name: Ruta relativa dentro de templates/pdf/
                           Ej: "visita_obra.html" o "simulacion/reporte_analitica.html"
            context: Variables de contexto para el template Jinja2.
            base_url: URL base para resolver recursos relativos (CSS, imagenes).
                      Por defecto usa el directorio de templates PDF.

        Returns:
            bytes del PDF generado.
        """
        try:
            html_string = self._env.get_template(template_name).render(**context)
        except jinja2.TemplateNotFound as exc:
            raise ValueError(f"Template PDF no encontrado: {template_name}") from exc

        effective_base_url = base_url or TEMPLATES_PDF_PATH.as_uri() + "/"

        def _render_sync() -> bytes:
            from weasyprint import HTML  # lazy import — falla solo al generar PDF, no al arrancar
            return HTML(
                string=html_string,
                base_url=effective_base_url,
            ).write_pdf()

        loop = asyncio.get_running_loop()
        pdf_bytes = await loop.run_in_executor(None, _render_sync)
        logger.info("PDF generado: template=%s bytes=%d", template_name, len(pdf_bytes))
        return pdf_bytes

    def generate_filename(self, prefix: str, suffix: str = "") -> str:
        """
        Genera un nombre de archivo PDF con timestamp Mexico_City.

        Ejemplo: visita_obra_20260225_1430_Planta_Norte.pdf
        """
        ts = now_mx().strftime("%Y%m%d_%H%M")
        clean_suffix = re.sub(r"[^\w\-]", "_", suffix)[:40].strip("_")
        parts = [p for p in [prefix, ts, clean_suffix] if p]
        return "_".join(parts) + ".pdf"

    def parse_visita_obra_data(self, data: str) -> VisitaObraData:
        try:
            return VisitaObraData.model_validate_json(data)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

    async def generate_visita_obra_report(
        self,
        visita: VisitaObraData,
        images: List[Any],
    ) -> tuple[bytes, str, List[bytes]]:
        images_b64, images_optimized = await self._process_visita_images(images)
        try:
            pdf_bytes = await self.generate(
                "visita_obra.html",
                {
                    "data": visita,
                    "images": images_b64,
                    "total_images": len(images_b64),
                },
            )
        except (OSError, RuntimeError, ValueError, jinja2.TemplateError) as exc:
            raise RuntimeError("Error generando PDF") from exc

        filename = self.generate_filename("visita_obra", visita.nombre_planta)
        return pdf_bytes, filename, images_optimized

    async def send_visita_obra_email(
        self,
        pdf_bytes: bytes,
        filename: str,
        images_optimized: List[bytes],
        visita: VisitaObraData,
        from_email: str,
    ) -> None:
        try:
            pool = await get_db_pool()
        except (asyncpg.PostgresError, RuntimeError, OSError) as exc:
            logger.warning("[VISITA_EMAIL] Pool de BD no disponible, correo omitido: %s", exc)
            return

        try:
            async with pool.acquire() as conn:
                destinatarios_raw = await self.db.get_config_value(
                    conn,
                    "visita_obra_destinatarios",
                )
            destinatarios = self._parse_email_list(destinatarios_raw or "")
            if not destinatarios:
                logger.info("[VISITA_EMAIL] Sin destinatarios configurados, correo omitido")
                return

            fotos_count = len(images_optimized)
            subject = (
                f"Visita a Obra: {visita.id_proyecto} - {visita.nombre_planta} "
                f"(Visita No. {visita.numero_visita})"
            )
            attachments_full: List[dict] = [
                {"name": filename, "content_bytes": pdf_bytes, "contentType": "application/pdf"}
            ]
            for index, img_bytes in enumerate(images_optimized, 1):
                attachments_full.append({
                    "name": f"foto_{index:02d}.jpg",
                    "content_bytes": img_bytes,
                    "contentType": "image/jpeg",
                })

            app_token = await self.ms_auth.get_application_token()
            if not app_token:
                logger.error("[VISITA_EMAIL] No se pudo obtener token de aplicacion")
                return

            success, msg = await self.ms_auth.send_email_with_attachments(
                access_token=app_token,
                from_email=from_email,
                subject=subject,
                body=self._render_visita_obra_email(visita, fotos_count),
                recipients=destinatarios,
                attachments_files=attachments_full,
            )
            if success:
                logger.info(
                    "[VISITA_EMAIL] Correo enviado - proyecto=%s destinatarios=%d fotos=%d",
                    visita.id_proyecto,
                    len(destinatarios),
                    fotos_count,
                )
                return

            logger.warning(
                "[VISITA_EMAIL] Envio con adjuntos fallo (%s) - activando fallback SharePoint",
                msg,
            )
            sp_folder = f"Visitas a Obra/{visita.id_proyecto}/Visita_{visita.numero_visita}"
            sp_link = ""
            try:
                sp_link = await self._upload_visita_photos_to_sharepoint(
                    images_optimized,
                    sp_folder,
                    app_token,
                    pool,
                )
            except (asyncpg.PostgresError, httpx.HTTPError, OSError, RuntimeError, ValueError) as exc:
                logger.error("[VISITA_EMAIL] Error subiendo fotos a SharePoint: %s", exc, exc_info=True)

            success2, msg2 = await self.ms_auth.send_email_with_attachments(
                access_token=app_token,
                from_email=from_email,
                subject=subject,
                body=self._render_visita_obra_email(visita, fotos_count, sp_link=sp_link or None),
                recipients=destinatarios,
                attachments_files=[
                    {"name": filename, "content_bytes": pdf_bytes, "contentType": "application/pdf"}
                ],
            )
            if success2:
                logger.info(
                    "[VISITA_EMAIL] Fallback enviado - proyecto=%s fotos_sharepoint=%s",
                    visita.id_proyecto,
                    sp_link or "no disponible",
                )
            else:
                logger.error("[VISITA_EMAIL] Fallback tambien fallo: %s", msg2)

        except (
            asyncpg.PostgresError,
            httpx.HTTPError,
            jinja2.TemplateError,
            KeyError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as exc:
            logger.error("[VISITA_EMAIL] Error al enviar correo: %s", exc, exc_info=True)

    async def save_visita_obra_pdf_sharepoint(
        self,
        pdf_bytes: bytes,
        filename: str,
        sp_folder_id: str,
        visita: VisitaObraData,
    ) -> None:
        try:
            pool = await get_db_pool()
        except (asyncpg.PostgresError, RuntimeError, OSError) as exc:
            logger.warning("[VISITA_SP_PDF] Pool de BD no disponible, subida omitida: %s", exc)
            return

        try:
            async with pool.acquire() as conn:
                config = await self.db.get_config_values(
                    conn,
                    ("SP_VISITAS_SITE_ID", "SP_VISITAS_DRIVE_ID"),
                )
            site_id = config.get("SP_VISITAS_SITE_ID", "")
            drive_id = config.get("SP_VISITAS_DRIVE_ID", "")

            if not site_id and not drive_id:
                logger.warning("[VISITA_SP_PDF] SP_VISITAS no configurado, subida omitida")
                return

            app_token = await self.ms_auth.get_application_token()
            if not app_token:
                logger.error("[VISITA_SP_PDF] No se pudo obtener token de aplicacion")
                return

            sp = SharePointService(access_token=app_token)
            result = await sp.upload_bytes_to_folder_id(
                content=pdf_bytes,
                filename=filename,
                folder_id=sp_folder_id,
                drive_id=drive_id,
                site_id=site_id,
            )
            logger.info(
                "[VISITA_SP_PDF] PDF subido a SharePoint - proyecto=%s url=%s",
                visita.id_proyecto,
                result.get("webUrl", "(sin url)"),
            )
        except (asyncpg.PostgresError, httpx.HTTPError, KeyError, RuntimeError, TypeError, ValueError) as exc:
            logger.error("[VISITA_SP_PDF] Error subiendo PDF a SharePoint: %s", exc, exc_info=True)

    async def _process_visita_images(self, images: List[Any]) -> tuple[List[str], List[bytes]]:
        images_b64: List[str] = []
        images_optimized: List[bytes] = []

        for upload in images or []:
            raw = await upload.read()
            if not raw:
                continue

            error = ImageProcessor.validate_image_file(
                raw,
                upload.content_type or "",
                upload.filename or "",
            )
            if error:
                raise ValueError(f"{upload.filename}: {error}")

            try:
                optimized_bytes, _ = ImageProcessor.optimize_image(raw)
            except (OSError, ValueError) as exc:
                raise ValueError(f"{upload.filename}: Imagen invalida") from exc

            images_b64.append(ImageProcessor.image_to_base64(optimized_bytes))
            images_optimized.append(optimized_bytes)

        return images_b64, images_optimized

    async def _upload_visita_photos_to_sharepoint(
        self,
        images_optimized: List[bytes],
        folder_path: str,
        app_token: str,
        pool,
    ) -> str:
        sp = SharePointService(access_token=app_token)

        async with pool.acquire() as conn:
            config = await sp._resolve_config(conn)
        sp.drive_id = config.get("drive_id") or sp.drive_id
        sp.site_id = config.get("site_id") or sp.site_id

        batch_size = 5
        for batch_start in range(0, len(images_optimized), batch_size):
            batch = images_optimized[batch_start:batch_start + batch_size]
            tasks = [
                sp.upload_bytes_direct(img, f"foto_{batch_start + index + 1:02d}.jpg", folder_path)
                for index, img in enumerate(batch)
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for index, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.warning(
                        "[VISITA_SP] Error subiendo foto_%02d: %s",
                        batch_start + index + 1,
                        result,
                    )

        return await sp.get_folder_web_url(folder_path)

    def _render_visita_obra_email(
        self,
        visita: VisitaObraData,
        fotos_count: int,
        sp_link: str | None = None,
    ) -> str:
        template = self._email_env.get_template("shared/emails/visita_obra.html")
        return template.render(
            visita=visita,
            fecha_display=visita.fecha or "-",
            ubicacion_display=visita.ubicacion or "-",
            fotos_count=fotos_count,
            sp_link=sp_link,
        )

    @staticmethod
    def _parse_email_list(value: str) -> List[str]:
        return [
            email.strip()
            for email in value.replace(";", ",").split(",")
            if email.strip()
        ]


# ---------------------------------------------------------------------------
# Singleton / Dependency
# ---------------------------------------------------------------------------

_pdf_service_instance: Optional[PDFService] = None


def get_pdf_service() -> PDFService:
    """Dependencia FastAPI — retorna el singleton de PDFService."""
    global _pdf_service_instance
    if _pdf_service_instance is None:
        _pdf_service_instance = PDFService()
    return _pdf_service_instance
