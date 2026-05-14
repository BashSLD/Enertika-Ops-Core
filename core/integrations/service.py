from typing import Optional

from core.microsoft import get_ms_auth

from .db_service import IntegrationsDBService, get_integrations_db_service
from .sharepoint import SharePointService


class IntegrationsService:
    """Orquesta integraciones externas usadas por endpoints compartidos."""

    def __init__(self, db: IntegrationsDBService | None = None):
        self.db = db or get_integrations_db_service()
        self.ms_auth = get_ms_auth()

    async def list_visitas_sharepoint_folders(self, conn, folder_id: Optional[str]) -> list[dict]:
        config = await self.db.get_config_values(
            conn,
            ("SP_VISITAS_SITE_ID", "SP_VISITAS_DRIVE_ID"),
        )
        site_id = config.get("SP_VISITAS_SITE_ID", "")
        drive_id = config.get("SP_VISITAS_DRIVE_ID", "")

        if not site_id and not drive_id:
            raise ValueError(
                "SharePoint de Visitas no configurado. "
                "Configura SP_VISITAS_SITE_ID y SP_VISITAS_DRIVE_ID en Admin."
            )

        app_token = await self.ms_auth.get_application_token()
        if not app_token:
            raise RuntimeError("No se pudo obtener token de Microsoft")

        sp = SharePointService(access_token=app_token)
        return await sp.list_folder_children(
            drive_id=drive_id,
            site_id=site_id,
            folder_id=folder_id or None,
        )


def get_integrations_service() -> IntegrationsService:
    return IntegrationsService()
