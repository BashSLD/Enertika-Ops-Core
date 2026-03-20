"""
Service Layer del módulo Finanzas.
Gestión de pagos BOM y comprobantes asociados.
"""

import logging
from uuid import UUID
from typing import Optional, List, Dict, Any
from datetime import date
from decimal import Decimal

from .db_service import FinanzasDBService, get_finanzas_db_service

logger = logging.getLogger("FinanzasService")


class FinanzasService:

    def __init__(self, db: FinanzasDBService):
        self.db = db

    async def get_dashboard_data(self, conn) -> Dict[str, Any]:
        pendientes = await self.db.get_autorizaciones_pendientes_pago(conn)
        historial = await self.db.get_historial_pagos(conn)
        kpis = await self.db.get_kpis(conn)
        return {
            "pendientes": pendientes,
            "historial": historial,
            "kpis": kpis,
        }

    async def get_modal_registrar_pago(
        self, conn, autorizacion_id: UUID
    ) -> Dict[str, Any]:
        aut = await self.db.get_autorizacion_para_pago(conn, autorizacion_id)
        if not aut:
            raise ValueError("Autorización no encontrada.")
        return aut

    async def get_pendientes(self, conn) -> list:
        return await self.db.get_autorizaciones_pendientes_pago(conn)

    async def get_historial(self, conn, limit: int = 100) -> list:
        return await self.db.get_historial_pagos(conn, limit)

    async def registrar_pago(
        self,
        conn,
        autorizacion_id: UUID,
        monto_pagado: Decimal,
        moneda: str,
        tipo_cambio_usado: Optional[Decimal],
        fecha_pago: date,
        referencia_bancaria: Optional[str],
        comprobante_url: Optional[str],
        registrado_por: UUID,
    ) -> Dict[str, Any]:
        """
        Registra el pago de una autorización BOM:
        1. Valida que la autorización esté en AUTORIZADO_FINANZAS y sin pago previo.
        2. Inserta en tb_bom_pagos.
        3. Crea el comprobante en tb_comprobantes_pago (origen='BOM', estatus='PENDIENTE').
        """
        aut = await self.db.get_autorizacion_para_pago(conn, autorizacion_id)
        if not aut:
            raise ValueError("Autorización no encontrada.")
        if aut["estatus"] != "AUTORIZADO_FINANZAS":
            raise ValueError(
                f"La autorización está en estatus {aut['estatus']}."
            )

        pago = await self.db.crear_pago_db(
            conn,
            autorizacion_id=autorizacion_id,
            monto_pagado=monto_pagado,
            moneda=moneda,
            tipo_cambio_usado=tipo_cambio_usado,
            fecha_pago=fecha_pago,
            referencia_bancaria=referencia_bancaria,
            comprobante_url=comprobante_url,
            registrado_por=registrado_por,
        )

        await self.db.crear_comprobante_bom(
            conn,
            id_bom_pago=pago["id"],
            fecha_pago=fecha_pago,
            beneficiario_orig=aut.get("nombre_proveedor") or "Sin proveedor",
            monto=monto_pagado,
            moneda=moneda,
            id_proveedor=aut.get("proveedor_id"),
            id_proyecto=aut.get("proyecto_id"),
            capturado_por=registrado_por,
            comprobante_url=comprobante_url,
        )

        logger.info(
            "Pago BOM registrado: autorizacion=%s pago=%s monto=%s %s",
            autorizacion_id, pago["id"], monto_pagado, moneda,
        )
        return pago


def get_finanzas_service() -> FinanzasService:
    return FinanzasService(db=get_finanzas_db_service())
