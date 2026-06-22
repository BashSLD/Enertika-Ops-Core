"""
Service Layer del modulo OyM.
Delega a TransferService con area='OYM'.
"""
from typing import Optional, List, Dict, Any
from uuid import UUID
import logging

from core.transfers.service import get_transfer_service
from .db_service import get_oym_db_service

logger = logging.getLogger("OyMService")


class OyMService:

    def __init__(self):
        self.transfers = get_transfer_service()
        self.db = get_oym_db_service()

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

    # ── Zonas ─────────────────────────────────────────────────────────────

    async def get_asignaciones_zona(self, conn) -> List[Dict[str, Any]]:
        return await self.db.get_asignaciones_zona(conn)

    async def asignar_zona(self, conn, usuario_id: UUID, zona: str) -> None:
        if zona not in ("Zona 1", "Zona 2"):
            raise ValueError(f"Zona inválida: {zona!r}")
        await self.db.upsert_zona_usuario(conn, usuario_id, zona)

    async def eliminar_zona(self, conn, usuario_id: UUID) -> None:
        await self.db.eliminar_zona_usuario(conn, usuario_id)


def get_service() -> OyMService:
    return OyMService()
