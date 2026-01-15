# modules/comercial/file_utils.py
"""
Utilidades para validación de archivos.
Evita duplicación de código entre handlers.
"""
from fastapi import UploadFile, HTTPException
from typing import Tuple
import logging

logger = logging.getLogger("ComercialModule")


def validate_file_size(
    file: UploadFile, 
    max_size_mb: int = 10,
    read_content: bool = False
) -> Tuple[bool, int] | Tuple[bool, int, bytes]:
    """
    Valida el tamaño de un archivo usando seek/tell pattern.
    
    Args:
        file: Archivo UploadFile de FastAPI
        max_size_mb: Tamaño máximo permitido en MB
        read_content: If True, also read and return file content
        
    Returns:
        If read_content=False: Tuple (is_valid, file_size_bytes)
        If read_content=True: Tuple (is_valid, file_size_bytes, content_bytes)
        
    Raises:
        HTTPException: Si el archivo excede el tamaño máximo (400 Bad Request)
    """
    file.file.seek(0, 2)
    file_size = file.file.tell()
    file.file.seek(0)
    
    max_size_bytes = max_size_mb * 1024 * 1024
    
    if file_size > max_size_bytes:
        logger.warning(
            f"Archivo rechazado (excede {max_size_mb}MB): {file.filename} ({file_size} bytes)"
        )
        raise HTTPException(
            status_code=400,
            detail=f"El archivo {file.filename} excede el tamaño máximo permitido de {max_size_mb}MB."
        )
    
    if read_content:
        content = file.file.read()
        file.file.seek(0)
        return (True, file_size, content)
    
    return (True, file_size)
