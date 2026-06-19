from typing import Optional


class SecurityDBService:
    """Queries SQL puras para autenticacion y contexto de usuario."""

    async def get_user_by_email(self, conn, email: str) -> Optional[dict]:
        row = await conn.fetchrow(
            """
            SELECT id_usuario, nombre, rol_sistema, department, puesto, modulo_preferido,
                   rol_organizacional, is_active
            FROM tb_usuarios
            WHERE email = $1
            """,
            email,
        )
        return dict(row) if row else None

    async def create_user(self, conn, nombre: str, email: str):
        return await conn.fetchval(
            """
            INSERT INTO tb_usuarios (nombre, email, rol_sistema)
            VALUES ($1, $2, 'USER')
            RETURNING id_usuario
            """,
            nombre,
            email,
        )

    async def get_module_permissions(self, conn, user_id) -> list[dict]:
        rows = await conn.fetch(
            """
            SELECT modulo_slug, rol_modulo
            FROM tb_permisos_modulos
            WHERE usuario_id = $1
            """,
            user_id,
        )
        return [dict(row) for row in rows]

    async def get_user_tokens(self, conn, email: str) -> Optional[dict]:
        row = await conn.fetchrow(
            """
            SELECT access_token, refresh_token, token_expires_at
            FROM tb_usuarios
            WHERE email = $1
            """,
            email,
        )
        return dict(row) if row else None

    async def update_user_tokens(
        self,
        conn,
        email: str,
        access_token: str,
        refresh_token: str,
        token_expires_at: int,
    ) -> None:
        await conn.execute(
            """
            UPDATE tb_usuarios
            SET access_token = $1, refresh_token = $2, token_expires_at = $3
            WHERE email = $4
            """,
            access_token,
            refresh_token,
            token_expires_at,
            email,
        )


def get_security_db_service() -> SecurityDBService:
    return SecurityDBService()
