# core/validation.py
"""Utilidades compartidas de validacion de input."""

from fastapi import UploadFile
import logging

logger = logging.getLogger("Validation")

# 50 MB default max upload size
DEFAULT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024


async def validate_upload_size(
    file: UploadFile,
    max_bytes: int = DEFAULT_MAX_UPLOAD_BYTES
) -> bytes:
    """
    Lee y valida el tamano de un archivo subido.

    Args:
        file: UploadFile de FastAPI
        max_bytes: Tamano maximo permitido en bytes

    Returns:
        bytes: Contenido del archivo

    Raises:
        ValueError: Si el archivo excede el tamano maximo
    """
    content = await file.read()
    if len(content) > max_bytes:
        max_mb = max_bytes / (1024 * 1024)
        actual_mb = len(content) / (1024 * 1024)
        raise ValueError(
            f"Archivo excede el limite de {max_mb:.0f}MB "
            f"(tamano: {actual_mb:.1f}MB)"
        )
    await file.seek(0)
    return content
