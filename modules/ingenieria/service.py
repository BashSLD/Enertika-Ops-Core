"""
Service Layer del modulo Ingenieria.
Delega a TransferService con area='INGENIERIA'.
"""
from typing import Optional, List, Dict, Any
from uuid import UUID
import logging

from core.transfers.service import TransferService, get_transfer_service

logger = logging.getLogger("IngenieriaService")


class IngenieriaService:

    def __init__(self):
        self.transfers = get_transfer_service()

    async def get_proyectos(
        self, conn, q: Optional[str] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        return await self.transfers.get_proyectos_by_area(
            conn, "INGENIERIA", q, limit
        )

    async def get_kpis(self, conn) -> Dict[str, int]:
        return await self.transfers.get_kpis_area(conn, "INGENIERIA")

    async def get_proyecto_detalle(
        self, conn, id_proyecto: UUID
    ) -> Dict[str, Any]:
        return await self.transfers.get_proyecto_detalle(conn, id_proyecto)

    async def get_checklist_envio(self, conn) -> List[Dict[str, Any]]:
        return await self.transfers.get_documentos_checklist(
            conn, "INGENIERIA", "CONSTRUCCION"
        )


def get_service() -> IngenieriaService:
    return IngenieriaService()
