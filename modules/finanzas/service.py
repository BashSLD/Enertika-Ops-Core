"""
Service Layer del módulo Finanzas.
Gestión de pagos BOM y comprobantes asociados.
"""

import logging
from uuid import UUID
from typing import Optional, Dict, Any
from datetime import date
from decimal import Decimal

from .db_service import FinanzasDBService, get_finanzas_db_service
from core.bom.db_service import BomDBService

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
        lock_version_esperado: int,
        clave_idempotencia: str,
    ) -> Dict[str, Any]:
        """
        Registra el pago de una autorización BOM:
        1. Valida autorización, saldo, moneda, idempotencia y revisión esperada.
        2. Inserta en tb_bom_pagos.
        3. Crea el comprobante en tb_comprobantes_pago (origen='BOM', estatus='PENDIENTE').
        """
        clave_limpia = (clave_idempotencia or "").strip()
        if not clave_limpia or len(clave_limpia) > 220:
            raise ValueError("Falta la clave de reintento del pago; recarga el formulario.")
        monto = Decimal(str(monto_pagado))
        if monto <= 0:
            raise ValueError("El monto pagado debe ser mayor a cero.")
        moneda_normalizada = (moneda or "").strip().upper()
        async with conn.transaction():
            aut = await self.db.get_autorizacion_para_pago_for_update(
                conn, autorizacion_id
            )
            if not aut:
                raise ValueError("Autorización no encontrada.")
            pago_existente = await self.db.get_pago_por_clave_idempotencia(
                conn, clave_limpia
            )
            if pago_existente:
                if pago_existente["autorizacion_id"] != autorizacion_id:
                    raise ValueError("La clave de reintento pertenece a otro pago.")
                return pago_existente
            if aut["estatus"] not in {"AUTORIZADO_FINANZAS", "PAGO_PARCIAL"}:
                raise ValueError(
                    f"La autorización está en estatus {aut['estatus']}."
                )
            if aut["lock_version"] != lock_version_esperado:
                raise ValueError(
                    "La autorizacion cambio; actualiza la pagina e intenta de nuevo."
                )
            if moneda_normalizada != str(aut["moneda"]).strip().upper():
                raise ValueError("La moneda del pago debe coincidir con la autorización.")
            if moneda_normalizada == "USD":
                if tipo_cambio_usado is None or Decimal(str(tipo_cambio_usado)) <= 0:
                    raise ValueError("El tipo de cambio es obligatorio para pagos en USD.")
            elif tipo_cambio_usado is not None:
                raise ValueError("No captures tipo de cambio para un pago en MXN.")

            pagado_previo = Decimal(str(aut.get("monto_pagado_acumulado") or 0))
            autorizado = Decimal(str(aut["monto_total"]))
            saldo = autorizado - pagado_previo
            tolerancia = Decimal("0.005")
            if monto - saldo > tolerancia:
                raise ValueError(
                    f"El pago excede el saldo pendiente de {aut['moneda']} {saldo:.2f}."
                )
            pagado_nuevo = pagado_previo + monto
            pago_completo = autorizado - pagado_nuevo <= tolerancia
            nuevo_estatus = "PAGADO" if pago_completo else "PAGO_PARCIAL"
            pago = await self.db.crear_pago_db(
                conn,
                autorizacion_id=autorizacion_id,
                monto_pagado=monto,
                moneda=moneda_normalizada,
                tipo_cambio_usado=tipo_cambio_usado,
                fecha_pago=fecha_pago,
                referencia_bancaria=referencia_bancaria,
                comprobante_url=comprobante_url,
                registrado_por=registrado_por,
                clave_idempotencia=clave_limpia,
            )
            autorizacion_actualizada = await self.db.actualizar_estatus_autorizacion(
                conn, autorizacion_id, aut["estatus"],
                aut["lock_version"], nuevo_estatus,
            )
            if not autorizacion_actualizada:
                raise ValueError(
                    "La autorización cambió; actualiza la página e intenta de nuevo."
                )

            cotizacion_id = aut.get("cotizacion_id")
            if cotizacion_id and pago_completo:
                bom_db = BomDBService()
                lineas = await bom_db.get_items_cotizacion(conn, cotizacion_id)
                item_ids = sorted(
                    {linea["bom_item_id"] for linea in lineas}, key=str
                )
                bloqueados = await bom_db.lock_items_context_by_ids(conn, item_ids)
                if len(bloqueados) != len(item_ids):
                    raise ValueError(
                        "Los items de la cotización cambiaron; actualiza la página."
                    )
                por_pagar = [
                    item for item in bloqueados
                    if item.get("estatus_compra") == "AUTORIZADO"
                ]
                ids_por_pagar = [item["id_item"] for item in por_pagar]
                await bom_db.actualizar_estatus_compra_items(
                    conn, ids_por_pagar, "PAGADO"
                )
                for item in por_pagar:
                    ejecucion = await bom_db.upsert_item_ejecucion(
                        conn,
                        item["id_item"],
                        updated_by=registrado_por,
                        lock_version_esperado=int(
                            item.get("ejecucion_lock_version") or 0
                        ),
                        estatus_ejecucion="PAGADO",
                    )
                    if not ejecucion:
                        raise ValueError(
                            "La ejecución de un item cambió; actualiza la página."
                        )
                updated_count = len(ids_por_pagar)
                logger.info(
                    "BOM estatus_compra: %d items AUTORIZADO → PAGADO (cotizacion=%s)",
                    updated_count, cotizacion_id,
                )

            await self.db.crear_comprobante_bom(
                conn,
                id_bom_pago=pago["id"],
                fecha_pago=fecha_pago,
                beneficiario_orig=aut.get("nombre_proveedor") or "Sin proveedor",
                monto=monto,
                moneda=moneda_normalizada,
                id_proveedor=aut.get("proveedor_id"),
                id_proyecto=aut.get("proyecto_id"),
                capturado_por=registrado_por,
                comprobante_url=comprobante_url,
            )
            bom_db = BomDBService()
            await bom_db.registrar_evento_outbox(
                conn,
                f"BOM-PAGO:{pago['id']}:{nuevo_estatus}",
                "AUTORIZACION_PAGADA" if pago_completo else "AUTORIZACION_PAGO_PARCIAL",
                aut["proyecto_id"], registrado_por,
                {
                    "version": aut["bom_version"],
                    "paquete_codigo": aut["paquete_codigo"],
                    "monto": str(monto),
                    "moneda": moneda_normalizada,
                    "monto_pagado_acumulado": str(pagado_nuevo),
                    "saldo_pendiente": str(max(autorizado - pagado_nuevo, Decimal("0"))),
                    "estatus_pago": nuevo_estatus,
                },
                id_paquete=aut["id_paquete"], id_bom=aut["bom_id"],
                id_documento=autorizacion_id,
            )

        logger.info(
            "Pago BOM registrado: autorizacion=%s pago=%s monto=%s %s",
            autorizacion_id, pago["id"], monto, moneda_normalizada,
        )
        return {
            **pago,
            "estatus_autorizacion": nuevo_estatus,
            "monto_pagado_acumulado": pagado_nuevo,
            "saldo_pendiente": max(autorizado - pagado_nuevo, Decimal("0")),
        }


def get_finanzas_service() -> FinanzasService:
    return FinanzasService(db=get_finanzas_db_service())
