from typing import Optional


class SatDBService:
    """Queries SQL puras para integraciones SAT."""

    async def get_active_fiel_config(self, conn, empresa: str) -> Optional[dict]:
        row = await conn.fetchrow(
            """
            SELECT empresa, sp_path_cer, sp_path_key, password_fiel
            FROM tb_sat_fiel_config
            WHERE activo = TRUE AND empresa = $1
            LIMIT 1
            """,
            empresa,
        )
        return dict(row) if row else None


def get_sat_db_service() -> SatDBService:
    return SatDBService()
