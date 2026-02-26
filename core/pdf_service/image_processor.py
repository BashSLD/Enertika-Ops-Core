# core/pdf_service/image_processor.py
"""
Servicio para procesamiento y optimizacion de imagenes para PDFs.
Portado de ._UPDATE/Generador_Reportes/image_processor.py
"""
import io
import base64
import logging
from typing import List, Tuple

from PIL import Image

from core.config import settings

logger = logging.getLogger("PDFImageProcessor")


class ImageProcessor:
    """Procesador de imagenes para PDFs."""

    @staticmethod
    def optimize_image(
        image_bytes: bytes,
        max_width: int = None,
        quality: int = None,
    ) -> Tuple[bytes, dict]:
        """
        Optimiza una imagen para insercion en PDF.

        Args:
            image_bytes: Bytes de la imagen original.
            max_width: Ancho maximo en pixeles (default: settings.PDF_MAX_IMAGE_WIDTH).
            quality: Calidad JPEG 0-100 (default: settings.PDF_IMAGE_QUALITY).

        Returns:
            Tuple de (imagen_optimizada_bytes, metadata).
        """
        if max_width is None:
            max_width = settings.PDF_MAX_IMAGE_WIDTH
        if quality is None:
            quality = settings.PDF_IMAGE_QUALITY

        img = Image.open(io.BytesIO(image_bytes))

        original_size = len(image_bytes)
        original_width, original_height = img.size

        # Convertir RGBA/LA/P a RGB (PDFs no manejan bien alpha channel)
        if img.mode in ("RGBA", "LA", "P"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            if img.mode == "RGBA":
                background.paste(img, mask=img.split()[-1])
            else:
                background.paste(img)
            img = background

        if img.mode != "RGB":
            img = img.convert("RGB")

        new_width, new_height = original_width, original_height
        if img.width > max_width:
            ratio = max_width / img.width
            new_height = int(img.height * ratio)
            new_width = max_width
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

        output = io.BytesIO()
        img.save(output, format="JPEG", quality=quality, optimize=True)
        optimized_bytes = output.getvalue()

        metadata = {
            "original_size_bytes": original_size,
            "optimized_size_bytes": len(optimized_bytes),
            "original_dimensions": (original_width, original_height),
            "final_dimensions": (new_width, new_height),
            "compression_ratio": round(original_size / len(optimized_bytes), 2),
            "size_reduction_percent": round(
                (1 - len(optimized_bytes) / original_size) * 100, 1
            ),
        }

        return optimized_bytes, metadata

    @staticmethod
    def image_to_base64(image_bytes: bytes) -> str:
        """Convierte bytes de imagen a data URI base64 para embeber en HTML."""
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        return f"data:image/jpeg;base64,{b64}"

    @staticmethod
    def process_images_for_pdf(
        images_bytes: List[bytes],
    ) -> Tuple[List[str], List[dict]]:
        """
        Procesa multiples imagenes para PDF.

        Returns:
            Tuple de (lista_base64_strings, lista_metadata).
        """
        processed_images = []
        metadata_list = []

        for img_bytes in images_bytes:
            optimized_bytes, metadata = ImageProcessor.optimize_image(img_bytes)
            base64_str = ImageProcessor.image_to_base64(optimized_bytes)
            processed_images.append(base64_str)
            metadata_list.append(metadata)

        return processed_images, metadata_list

    @staticmethod
    def validate_image_file(
        image_bytes: bytes,
        content_type: str,
        filename: str,
        max_size_mb: int = None,
    ) -> str | None:
        """
        Valida tipo de archivo, extension y tamano.

        Returns:
            None si es valida, mensaje de error si no.
        """
        if max_size_mb is None:
            max_size_mb = settings.PDF_MAX_UPLOAD_SIZE_MB

        allowed_types = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
        allowed_extensions = {".jpg", ".jpeg", ".png", ".webp"}

        if content_type not in allowed_types:
            return f"Tipo de archivo no permitido: {content_type}"

        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in allowed_extensions:
            return f"Extension no permitida: {ext}"

        size_mb = len(image_bytes) / (1024 * 1024)
        if size_mb > max_size_mb:
            return f"Imagen excede el limite de {max_size_mb}MB"

        return None
