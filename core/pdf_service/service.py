# core/pdf_service/service.py
"""
Motor compartido de generacion PDF usando WeasyPrint.
Renderiza templates Jinja2 a HTML y convierte a PDF en un executor (async-safe).
"""
import asyncio
import logging
import re
from pathlib import Path
from typing import Optional

import jinja2
from weasyprint import HTML

logger = logging.getLogger("PDFService")

# Directorio base de templates PDF — relativo al workspace
TEMPLATES_PDF_PATH = Path(__file__).parent.parent.parent / "templates" / "pdf"


class PDFService:
    """Singleton para generacion de PDFs con WeasyPrint."""

    def __init__(self) -> None:
        self._env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(TEMPLATES_PDF_PATH)),
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
        from datetime import datetime
        import pytz

        tz = pytz.timezone("America/Mexico_City")
        ts = datetime.now(tz).strftime("%Y%m%d_%H%M")
        clean_suffix = re.sub(r"[^\w\-]", "_", suffix)[:40].strip("_")
        parts = [p for p in [prefix, ts, clean_suffix] if p]
        return "_".join(parts) + ".pdf"


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
