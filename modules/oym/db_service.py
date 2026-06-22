# modules/oym/db_service.py
from __future__ import annotations

import logging
from uuid import UUID

import asyncpg

logger = logging.getLogger("OyMDBService")


class OyMDBService:

    async def get_usuario_ids_en_misma_zona(
        self, conn: asyncpg.Connection, usuario_id: UUID
    ) -> list[UUID]:
        """Todos los usuario_id de la misma zona. Lista vacía si el usuario no tiene zona."""
        rows = await conn.fetch(
            """
            SELECT usuario_id FROM tb_oym_zonas_usuarios
            WHERE zona = (SELECT zona FROM tb_oym_zonas_usuarios WHERE usuario_id = $1)
            """,
            usuario_id,
        )
        return [r["usuario_id"] for r in rows]

    async def get_asignaciones_zona(self, conn: asyncpg.Connection) -> list[dict]:
        """Todos los usuarios activos con su zona actual (NULL si sin asignar)."""
        rows = await conn.fetch(
            """
            SELECT u.id_usuario, u.nombre, u.email, u.department,
                   z.zona
            FROM tb_usuarios u
            LEFT JOIN tb_oym_zonas_usuarios z ON z.usuario_id = u.id_usuario
            WHERE u.is_active = true
            ORDER BY u.nombre
            """
        )
        return [dict(r) for r in rows]

    async def upsert_zona_usuario(
        self, conn: asyncpg.Connection, usuario_id: UUID, zona: str
    ) -> None:
        await conn.execute(
            """
            INSERT INTO tb_oym_zonas_usuarios (usuario_id, zona)
            VALUES ($1, $2)
            ON CONFLICT (usuario_id)
            DO UPDATE SET zona = EXCLUDED.zona, asignado_en = now()
            """,
            usuario_id, zona,
        )

    async def eliminar_zona_usuario(
        self, conn: asyncpg.Connection, usuario_id: UUID
    ) -> None:
        await conn.execute(
            "DELETE FROM tb_oym_zonas_usuarios WHERE usuario_id = $1",
            usuario_id,
        )


def get_oym_db_service() -> OyMDBService:
    return OyMDBService()
