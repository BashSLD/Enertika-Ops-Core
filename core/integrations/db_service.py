from typing import Dict, Iterable, Optional
from uuid import UUID


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

    async def get_sharepoint_mapeo(self, conn, id_proyecto: UUID) -> Optional[dict]:
        row = await conn.fetchrow(
            """
            SELECT sharepoint_folder_id, sharepoint_url
            FROM tb_proyectos_gate
            WHERE id_proyecto = $1
            """,
            id_proyecto,
        )
        return dict(row) if row else None

    async def get_proyecto_id_estandar(self, conn, id_proyecto: UUID) -> Optional[str]:
        return await conn.fetchval(
            "SELECT proyecto_id_estandar FROM tb_proyectos_gate WHERE id_proyecto = $1",
            id_proyecto,
        )

    async def persist_sharepoint_mapeo(
        self,
        conn,
        id_proyecto: UUID,
        folder_id: str,
        drive_id: str,
        web_url: str,
        origen: str,
    ) -> None:
        result = await conn.execute(
            """
            UPDATE tb_proyectos_gate
            SET sharepoint_folder_id = $2,
                sharepoint_drive_id = $3,
                sharepoint_url = $4,
                sharepoint_origen = $5,
                sharepoint_resuelto_en = NOW()
            WHERE id_proyecto = $1
            """,
            id_proyecto, folder_id, drive_id, web_url, origen,
        )
        # asyncpg retorna "UPDATE n" -- si n es 0, el proyecto ya no existe (borrado
        # concurrente o UUID invalido) y el caller no debe reportar exito silencioso.
        if result == "UPDATE 0":
            raise ValueError(f"Proyecto {id_proyecto} no encontrado para persistir el mapeo de SharePoint")


def get_integrations_db_service() -> IntegrationsDBService:
    return IntegrationsDBService()
