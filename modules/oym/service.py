"""
Service Layer del modulo OyM.
Delega a TransferService con area='OYM'.
"""
from typing import Optional, List, Dict, Any
from uuid import UUID
import logging

from core.transfers.service import TransferService, get_transfer_service

logger = logging.getLogger("OyMService")


class OyMService:

    def __init__(self):
        self.transfers = get_transfer_service()

    async def get_proyectos(
        self, conn, q: Optional[str] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        return await self.transfers.get_proyectos_by_area(
            conn, "OYM", q, limit
        )

    async def get_pendientes_recepcion(self, conn) -> List[Dict[str, Any]]:
        return await self.transfers.get_proyectos_pendientes_recepcion(
            conn, "OYM"
        )

    async def get_kpis(self, conn) -> Dict[str, int]:
        return await self.transfers.get_kpis_area(conn, "OYM")

    async def get_proyecto_detalle(
        self, conn, id_proyecto: UUID
    ) -> Dict[str, Any]:
        return await self.transfers.get_proyecto_detalle(conn, id_proyecto)

    async def get_motivos_rechazo(self, conn) -> List[Dict[str, Any]]:
        return await self.transfers.get_motivos_rechazo(conn, "OYM")


def get_service() -> OyMService:
    return OyMService()
