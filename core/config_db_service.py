from typing import Any, List, Optional


class ConfigDBService:
    """Queries SQL puras para configuracion global y catalogos."""

    async def get_catalog_rows(
        self,
        conn,
        table: str,
        key_col: str,
        val_col: str,
    ) -> List[dict]:
        rows = await conn.fetch(f"SELECT {key_col}, {val_col} FROM {table}")
        return [dict(row) for row in rows]

    async def get_umbrales_kpi(
        self,
        conn,
        tipo_kpi: str,
        departamento: str,
    ) -> Optional[dict]:
        row = await conn.fetchrow(
            """
            SELECT
                tipo_kpi,
                umbral_excelente,
                umbral_bueno,
                color_excelente,
                color_bueno,
                color_critico
            FROM tb_config_umbrales_kpi
            WHERE tipo_kpi = $1
              AND activo = TRUE
              AND departamento = $2
            ORDER BY id DESC
            LIMIT 1
            """,
            tipo_kpi,
            departamento,
        )
        return dict(row) if row else None

    async def get_global_config(self, conn, clave: str) -> Optional[dict[str, Any]]:
        row = await conn.fetchrow(
            """
            SELECT valor, tipo_dato
            FROM tb_configuracion_global
            WHERE clave = $1
            """,
            clave,
        )
        return dict(row) if row else None


def get_config_db_service() -> ConfigDBService:
    return ConfigDBService()
