# core/tipo_cambio/db_service.py
"""Capa de acceso a datos para tb_tipo_cambio. Recibe conn como parámetro."""
from datetime import date
from decimal import Decimal
from typing import Optional
import logging

logger = logging.getLogger("TipoCambio.DBService")


class TipoCambioDBService:

    async def get_tasa_mas_reciente(self, conn) -> Optional[dict]:
        """Retorna la tasa más reciente registrada."""
        row = await conn.fetchrow(
            "SELECT id, fecha, tasa_mxn, fuente, creado_en FROM tb_tipo_cambio ORDER BY fecha DESC LIMIT 1"
        )
        return dict(row) if row else None

    async def get_tasa_by_fecha(self, conn, fecha: date) -> Optional[dict]:
        """Retorna la tasa para una fecha específica."""
        row = await conn.fetchrow(
            "SELECT id, fecha, tasa_mxn, fuente, creado_en FROM tb_tipo_cambio WHERE fecha = $1",
            fecha
        )
        return dict(row) if row else None

    async def upsert_tasa(self, conn, fecha: date, tasa_mxn: Decimal, fuente: str = "BANXICO") -> None:
        """Inserta o actualiza la tasa para una fecha."""
        await conn.execute(
            """
            INSERT INTO tb_tipo_cambio (fecha, tasa_mxn, fuente)
            VALUES ($1, $2, $3)
            ON CONFLICT (fecha) DO UPDATE
                SET tasa_mxn = EXCLUDED.tasa_mxn,
                    fuente   = EXCLUDED.fuente
            """,
            fecha, tasa_mxn, fuente
        )

    async def get_historial(self, conn, limit: int = 30) -> list:
        """Retorna las últimas N tasas registradas."""
        rows = await conn.fetch(
            "SELECT fecha, tasa_mxn, fuente FROM tb_tipo_cambio ORDER BY fecha DESC LIMIT $1",
            limit
        )
        return [dict(r) for r in rows]
