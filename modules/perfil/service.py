from __future__ import annotations

import base64
import struct
from typing import Optional
from uuid import UUID

from modules.perfil.constants import FIRMA_MAX_BYTES
from modules.shared import signatures_db_service as signatures_db


async def guardar_firma(
    conn,
    usuario_id: UUID,
    firma_bytes: bytes,
    tipo: str,
    solicitud_pendiente_id: Optional[UUID] = None,
) -> None:
    if len(firma_bytes) > FIRMA_MAX_BYTES:
        raise ValueError(f"La firma excede el tamano maximo ({FIRMA_MAX_BYTES // 1024} KB)")
    validar_firma_png(firma_bytes)
    await signatures_db.upsert_firma_usuario(conn, usuario_id, firma_bytes, tipo)
    if solicitud_pendiente_id:
        from modules.vacaciones.db_service import insert_firma_solicitud
        from modules.vacaciones.service import activar_solicitud_tras_firma

        await insert_firma_solicitud(conn, solicitud_pendiente_id, usuario_id, "solicitante")
        await activar_solicitud_tras_firma(conn, solicitud_pendiente_id, usuario_id)


def firma_bytes_to_base64(firma_bytes: bytes) -> str:
    return base64.b64encode(firma_bytes).decode()


def validar_firma_png(firma_bytes: bytes) -> None:
    if not firma_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("La firma debe ser una imagen PNG valida")
    if len(firma_bytes) < 24:
        raise ValueError("La firma PNG esta incompleta")
    width, height = struct.unpack(">II", firma_bytes[16:24])
    if width > 500 or height > 200:
        raise ValueError("La firma debe medir maximo 500 x 200 px")
