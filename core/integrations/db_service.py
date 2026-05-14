from typing import Dict, Iterable


class IntegrationsDBService:
    """Queries SQL puras para integraciones externas."""

    async def get_config_values(self, conn, keys: Iterable[str]) -> Dict[str, str]:
        rows = await conn.fetch(
            """
            SELECT clave, valor
            FROM tb_configuracion_global
            WHERE clave = ANY($1::text[])
            """,
            list(keys),
        )
        return {row["clave"]: (row["valor"] or "").strip() for row in rows}


def get_integrations_db_service() -> IntegrationsDBService:
    return IntegrationsDBService()
