from __future__ import annotations

from typing import Optional
from uuid import UUID


async def get_perfil_usuario(conn, usuario_id: UUID) -> Optional[dict]:
    row = await conn.fetchrow(
        """
        SELECT id_usuario, nombre, email, department, puesto
        FROM tb_usuarios
        WHERE id_usuario = $1
        """,
        usuario_id,
    )
    return dict(row) if row else None
