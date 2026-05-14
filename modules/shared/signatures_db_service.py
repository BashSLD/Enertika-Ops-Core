from __future__ import annotations

from typing import Optional
from uuid import UUID


async def get_firma_usuario(conn, usuario_id: UUID) -> Optional[dict]:
    row = await conn.fetchrow(
        "SELECT usuario_id, firma_data, tipo_firma, fecha_carga "
        "FROM tb_usuarios_firmas WHERE usuario_id = $1",
        usuario_id,
    )
    return dict(row) if row else None


async def upsert_firma_usuario(conn, usuario_id: UUID, firma_bytes: bytes, tipo: str) -> None:
    await conn.execute(
        """
        INSERT INTO tb_usuarios_firmas (usuario_id, firma_data, tipo_firma, fecha_carga)
        VALUES ($1, $2, $3, now())
        ON CONFLICT (usuario_id) DO UPDATE SET
            firma_data  = EXCLUDED.firma_data,
            tipo_firma  = EXCLUDED.tipo_firma,
            fecha_carga = now()
        """,
        usuario_id,
        firma_bytes,
        tipo,
    )
