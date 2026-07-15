# modules/oym/db_service.py
from __future__ import annotations

import logging
from uuid import UUID

import asyncpg

logger = logging.getLogger("OyMDBService")


class OyMDBService:

    async def get_zona_de_usuario(
        self, conn: asyncpg.Connection, usuario_id: UUID
    ) -> str | None:
        """Zona asignada al usuario, o None si no tiene zona."""
        return await conn.fetchval(
            "SELECT zona FROM tb_oym_zonas_usuarios WHERE usuario_id = $1", usuario_id,
        )

    async def get_asignaciones_zona(self, conn: asyncpg.Connection) -> list[dict]:
        """Usuarios activos del departamento de O&M con su zona actual (NULL si sin asignar)."""
        rows = await conn.fetch(
            """
            SELECT u.id_usuario, u.nombre, u.email, u.department,
                   z.zona
            FROM tb_usuarios u
            LEFT JOIN tb_oym_zonas_usuarios z ON z.usuario_id = u.id_usuario
            WHERE u.is_active = true
              AND u.department = (SELECT nombre FROM tb_cat_departamentos WHERE slug = 'oym')
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
