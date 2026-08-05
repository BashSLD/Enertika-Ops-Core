"""
DB Service del módulo Finanzas.
Queries SQL para autorizaciones BOM pendientes de pago y registro de pagos.
"""

import logging
from uuid import UUID
from typing import Optional, List, Dict, Any
from datetime import date
from decimal import Decimal

logger = logging.getLogger("FinanzasDB")


class FinanzasDBService:

    # ─── Autorizaciones ──────────────────────────────────────────────────────

    async def get_autorizaciones_pendientes_pago(self, conn) -> List[Dict[str, Any]]:
        """Autorizaciones en AUTORIZADO_FINANZAS (sin pago aún)."""
        rows = await conn.fetch("""
            SELECT
                a.id,
                a.bom_id,
                a.proyecto_id,
                a.monto_total,
                a.moneda,
                a.tipo_cambio_snapshot,
                a.estatus,
                a.lock_version,
                a.fecha_aprobacion_finanzas,
                a.nota_finanzas,
                c.nombre_proveedor,
                b.id_paquete,
                b.version AS bom_version,
                paquete.codigo AS paquete_codigo,
                paquete.nombre AS paquete_nombre,
                p.proyecto_id_estandar,
                p.nombre_corto    AS nombre_proyecto,
                cl.nombre_fiscal  AS cliente_nombre
                ,COALESCE(pagos.monto_pagado_acumulado, 0) AS monto_pagado_acumulado
                ,a.monto_total - COALESCE(pagos.monto_pagado_acumulado, 0) AS saldo_pendiente
            FROM tb_bom_autorizaciones a
            JOIN tb_bom_cotizaciones c ON c.id = a.cotizacion_id
            JOIN tb_bom b              ON b.id_bom = a.bom_id
            JOIN tb_bom_paquetes paquete ON paquete.id_paquete = b.id_paquete
            JOIN tb_proyectos_gate p   ON p.id_proyecto = a.proyecto_id
            LEFT JOIN tb_oportunidades op ON op.id_oportunidad = p.id_oportunidad
            LEFT JOIN tb_clientes cl   ON cl.id = op.cliente_id
            LEFT JOIN LATERAL (
                SELECT SUM(bp.monto_pagado) AS monto_pagado_acumulado
                FROM tb_bom_pagos bp
                WHERE bp.autorizacion_id = a.id
            ) pagos ON TRUE
            WHERE a.estatus IN ('AUTORIZADO_FINANZAS', 'PAGO_PARCIAL')
            ORDER BY a.fecha_aprobacion_finanzas
        """)
        return [dict(r) for r in rows]

    async def actualizar_estatus_autorizacion(
        self, conn, autorizacion_id: UUID, estatus_esperado: str,
        lock_version_esperado: int, nuevo_estatus: str,
    ) -> Optional[Dict[str, Any]]:
        """Actualiza una autorización con estado y revisión esperados."""
        row = await conn.fetchrow("""
            UPDATE tb_bom_autorizaciones
            SET estatus = $4,
                lock_version = lock_version + 1
            WHERE id = $1
              AND estatus = $2
              AND lock_version = $3
            RETURNING *
        """, autorizacion_id, estatus_esperado, lock_version_esperado, nuevo_estatus)
        return dict(row) if row else None

    async def get_historial_pagos(
        self, conn, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Pagos BOM ya registrados, con datos del proyecto y proveedor."""
        rows = await conn.fetch("""
            SELECT
                bp.id,
                bp.autorizacion_id,
                bp.monto_pagado,
                bp.moneda,
                bp.tipo_cambio_usado,
                bp.fecha_pago,
                bp.referencia_bancaria,
                bp.comprobante_url,
                bp.registrado_en,
                a.estatus AS estatus_autorizacion,
                SUM(bp.monto_pagado) OVER (
                    PARTITION BY bp.autorizacion_id
                    ORDER BY bp.registrado_en, bp.id
                ) AS monto_pagado_acumulado,
                a.monto_total - SUM(bp.monto_pagado) OVER (
                    PARTITION BY bp.autorizacion_id
                    ORDER BY bp.registrado_en, bp.id
                ) AS saldo_despues_pago,
                c.nombre_proveedor,
                b.id_paquete,
                b.version AS bom_version,
                paquete.codigo AS paquete_codigo,
                paquete.nombre AS paquete_nombre,
                p.proyecto_id_estandar,
                p.nombre_corto    AS nombre_proyecto,
                cp.id_comprobante,
                u.nombre          AS registrado_por_nombre
            FROM tb_bom_pagos bp
            JOIN tb_bom_autorizaciones a ON a.id = bp.autorizacion_id
            JOIN tb_bom_cotizaciones c   ON c.id = a.cotizacion_id
            JOIN tb_bom b                ON b.id_bom = a.bom_id
            JOIN tb_bom_paquetes paquete ON paquete.id_paquete = b.id_paquete
            JOIN tb_proyectos_gate p     ON p.id_proyecto = a.proyecto_id
            LEFT JOIN tb_comprobantes_pago cp ON cp.id_bom_pago = bp.id
            LEFT JOIN tb_usuarios u       ON u.id_usuario = bp.registrado_por
            ORDER BY bp.fecha_pago DESC
            LIMIT $1
        """, limit)
        return [dict(r) for r in rows]

    async def get_autorizacion_para_pago(
        self, conn, autorizacion_id: UUID
    ) -> Optional[Dict[str, Any]]:
        """Datos completos de una autorización para registrar el pago."""
        row = await conn.fetchrow("""
            SELECT
                a.id,
                a.bom_id,
                a.proyecto_id,
                a.monto_total,
                a.moneda,
                a.tipo_cambio_snapshot,
                a.estatus,
                a.lock_version,
                a.cotizacion_id,
                c.nombre_proveedor,
                c.proveedor_id,
                b.id_paquete,
                b.version AS bom_version,
                paquete.codigo AS paquete_codigo,
                paquete.nombre AS paquete_nombre,
                p.proyecto_id_estandar,
                p.nombre_corto    AS nombre_proyecto,
                p.id_oportunidad
                ,COALESCE(pagos.monto_pagado_acumulado, 0) AS monto_pagado_acumulado
                ,a.monto_total - COALESCE(pagos.monto_pagado_acumulado, 0) AS saldo_pendiente
            FROM tb_bom_autorizaciones a
            JOIN tb_bom_cotizaciones c ON c.id = a.cotizacion_id
            JOIN tb_bom b              ON b.id_bom = a.bom_id
            JOIN tb_bom_paquetes paquete ON paquete.id_paquete = b.id_paquete
            JOIN tb_proyectos_gate p   ON p.id_proyecto = a.proyecto_id
            LEFT JOIN LATERAL (
                SELECT SUM(bp.monto_pagado) AS monto_pagado_acumulado
                FROM tb_bom_pagos bp
                WHERE bp.autorizacion_id = a.id
            ) pagos ON TRUE
            WHERE a.id = $1
        """, autorizacion_id)
        return dict(row) if row else None

    async def get_autorizacion_para_pago_for_update(
        self, conn, autorizacion_id: UUID
    ) -> Optional[Dict[str, Any]]:
        """Bloquea la autorización exacta antes de registrar un pago."""
        row = await conn.fetchrow("""
            SELECT
                a.id, a.bom_id, a.proyecto_id, a.monto_total, a.moneda,
                a.tipo_cambio_snapshot, a.estatus, a.lock_version,
                a.cotizacion_id, c.nombre_proveedor, c.proveedor_id,
                b.id_paquete, b.version AS bom_version,
                paquete.codigo AS paquete_codigo,
                paquete.nombre AS paquete_nombre,
                p.proyecto_id_estandar, p.nombre_corto AS nombre_proyecto,
                p.id_oportunidad,
                COALESCE((
                    SELECT SUM(bp.monto_pagado)
                    FROM tb_bom_pagos bp
                    WHERE bp.autorizacion_id = a.id
                ), 0) AS monto_pagado_acumulado
            FROM tb_bom_autorizaciones a
            JOIN tb_bom_cotizaciones c ON c.id = a.cotizacion_id
            JOIN tb_bom b ON b.id_bom = a.bom_id
            JOIN tb_bom_paquetes paquete ON paquete.id_paquete = b.id_paquete
            JOIN tb_proyectos_gate p ON p.id_proyecto = a.proyecto_id
            WHERE a.id = $1
            FOR UPDATE OF a
        """, autorizacion_id)
        return dict(row) if row else None

    # ─── Registro de pago ────────────────────────────────────────────────────

    async def crear_pago_db(
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
        clave_idempotencia: str,
    ) -> Dict[str, Any]:
        """Inserta en tb_bom_pagos y retorna el registro creado."""
        row = await conn.fetchrow("""
            INSERT INTO tb_bom_pagos (
                autorizacion_id, monto_pagado, moneda, tipo_cambio_usado,
                fecha_pago, referencia_bancaria, comprobante_url, registrado_por
                , clave_idempotencia
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING *
        """,
            autorizacion_id, monto_pagado, moneda, tipo_cambio_usado,
            fecha_pago, referencia_bancaria, comprobante_url, registrado_por,
            clave_idempotencia,
        )
        return dict(row)

    async def get_pago_por_clave_idempotencia(
        self, conn, clave_idempotencia: str,
    ) -> Optional[Dict[str, Any]]:
        row = await conn.fetchrow(
            """
            SELECT *
            FROM tb_bom_pagos
            WHERE clave_idempotencia = $1
            """,
            clave_idempotencia,
        )
        return dict(row) if row else None

    async def crear_comprobante_bom(
        self,
        conn,
        id_bom_pago: UUID,
        fecha_pago: date,
        beneficiario_orig: str,
        monto: Decimal,
        moneda: str,
        id_proveedor: Optional[UUID],
        id_proyecto: Optional[UUID],
        capturado_por: UUID,
        comprobante_url: Optional[str],
    ) -> None:
        """Inserta en tb_comprobantes_pago con origen='BOM' y enlace al pago BOM."""
        await conn.execute("""
            INSERT INTO tb_comprobantes_pago (
                fecha_pago, beneficiario_orig, monto, moneda,
                id_proveedor, id_proyecto, estatus, capturado_por_id,
                id_bom_pago, origen
            ) VALUES ($1, $2, $3, $4, $5, $6, 'PENDIENTE', $7, $8, 'BOM')
        """,
            fecha_pago, beneficiario_orig, monto, moneda,
            id_proveedor, id_proyecto, capturado_por,
            id_bom_pago,
        )

    async def get_kpis(self, conn) -> Dict[str, Any]:
        """KPIs para el dashboard de Finanzas."""
        row = await conn.fetchrow("""
            SELECT
                COUNT(DISTINCT a.id) FILTER (
                    WHERE a.estatus IN ('AUTORIZADO_FINANZAS', 'PAGO_PARCIAL')
                ) AS pendientes_pago,
                COUNT(*) FILTER (
                    WHERE bp.id IS NOT NULL
                    AND bp.fecha_pago >= (
                        NOW() AT TIME ZONE 'America/Mexico_City'
                    )::DATE - INTERVAL '30 days'
                ) AS pagados_30d,
                COALESCE(SUM(bp.monto_pagado) FILTER (
                    WHERE bp.id IS NOT NULL
                    AND DATE_TRUNC('month', bp.fecha_pago::TIMESTAMP)
                        = DATE_TRUNC(
                            'month', NOW() AT TIME ZONE 'America/Mexico_City'
                        )
                    AND bp.moneda = 'MXN'
                ), 0) AS monto_pagado_mes_mxn
            FROM tb_bom_autorizaciones a
            LEFT JOIN tb_bom_pagos bp ON bp.autorizacion_id = a.id
        """)
        return dict(row)


def get_finanzas_db_service() -> FinanzasDBService:
    return FinanzasDBService()
