from __future__ import annotations

import asyncio
import base64
import io
from datetime import date
from typing import Optional
from uuid import UUID

from PIL import Image

from modules.perfil import db_service as db
from modules.perfil.constants import FIRMA_MAX_BYTES
from modules.shared import signatures_db_service as signatures_db

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def redimensionar_firma(firma_bytes: bytes) -> bytes:
    with Image.open(io.BytesIO(firma_bytes)) as img:
        if img.width <= 500 and img.height <= 200:
            return firma_bytes
        img.thumbnail((500, 200), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()


async def guardar_firma(
    conn,
    usuario_id: UUID,
    firma_bytes: bytes,
    tipo: str,
    solicitud_pendiente_id: Optional[UUID] = None,
) -> tuple[bytes, Optional[str]]:
    """Devuelve (firma_bytes, tipo_nombre_enviado). tipo_nombre_enviado no es
    None solo si esta firma completo y envio una solicitud pendiente."""
    if not firma_bytes.startswith(PNG_MAGIC):
        raise ValueError("La firma debe ser una imagen PNG valida")
    firma_bytes = await asyncio.to_thread(redimensionar_firma, firma_bytes)
    if len(firma_bytes) > FIRMA_MAX_BYTES:
        raise ValueError(f"La firma excede el tamano maximo ({FIRMA_MAX_BYTES // 1024} KB)")
    await signatures_db.upsert_firma_usuario(conn, usuario_id, firma_bytes, tipo)
    tipo_nombre_enviado = None
    if solicitud_pendiente_id:
        from modules.vacaciones.db_service import insert_firma_solicitud
        from modules.vacaciones.service import activar_solicitud_tras_firma

        await insert_firma_solicitud(conn, solicitud_pendiente_id, usuario_id, "solicitante")
        tipo_nombre_enviado = await activar_solicitud_tras_firma(conn, solicitud_pendiente_id, usuario_id)
    return firma_bytes, tipo_nombre_enviado


def firma_bytes_to_base64(firma_bytes: bytes) -> str:
    return base64.b64encode(firma_bytes).decode()


async def get_equipo_fuera_oficina_ctx(conn, fecha_inicio: date, fecha_fin: date) -> dict:
    """Contexto del widget colaborativo 'Equipo fuera de oficina'. El rango ya debe
    llegar saneado (fecha_fin >= fecha_inicio) — la normalizacion vive en el router,
    que es quien recibe los parametros crudos de la URL."""
    eventos = await db.get_equipo_fuera_oficina(conn, fecha_inicio, fecha_fin)
    return {
        "eventos": eventos,
        "fecha_inicio": fecha_inicio,
        "fecha_fin": fecha_fin,
    }
