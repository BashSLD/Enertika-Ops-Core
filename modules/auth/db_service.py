QUERY_UPSERT_AUTHENTICATED_USER = """
    INSERT INTO tb_usuarios (
        nombre,
        email,
        access_token,
        refresh_token,
        token_expires_at,
        rol_sistema,
        ultimo_login,
        is_active,
        department,
        puesto
    )
    VALUES ($1, $2, $3, $4, $5, 'USER', NOW(), TRUE, $6, $7)
    ON CONFLICT (email) DO UPDATE
    SET access_token = EXCLUDED.access_token,
        refresh_token = EXCLUDED.refresh_token,
        token_expires_at = EXCLUDED.token_expires_at,
        ultimo_login = NOW(),
        nombre = COALESCE(tb_usuarios.nombre, EXCLUDED.nombre),
        department = COALESCE(EXCLUDED.department, tb_usuarios.department),
        puesto = COALESCE(EXCLUDED.puesto, tb_usuarios.puesto)
"""


async def upsert_authenticated_user(
    conn,
    *,
    name: str,
    email: str,
    access_token: str,
    refresh_token: str | None,
    expires_at: int,
    department: str | None,
    puesto: str | None,
) -> None:
    await conn.execute(
        QUERY_UPSERT_AUTHENTICATED_USER,
        name,
        email,
        access_token,
        refresh_token,
        expires_at,
        department,
        puesto,
    )
