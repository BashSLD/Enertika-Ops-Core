"""
DB Service para BOM (Lista de Materiales).
Queries SQL puras con asyncpg. Recibe conn como parametro.
"""

import logging
import json
from decimal import Decimal
from uuid import UUID
from typing import Optional, List

from core.bom.db_compras import BomComprasDBMixin
from core.bom.schemas import EstatusBOM
from core.materials.db_service import interno_similitud_expr_sql, interno_similitud_where_sql

logger = logging.getLogger("BOM.DBService")

# Heuristica de moneda para materiales sin columna moneda propia (tb_materiales_historial):
# tipo_cambio_xml solo se captura cuando el CFDI original viene en USD (ver migracion 048
# y modules/compras/xml_extractor.py). Reusada en buscar_materiales_para_bom,
# get_materiales_recientes y sincronizar_costos_catalogo.
_MONEDA_XML_SQL = "CASE WHEN m.tipo_cambio_xml IS NOT NULL THEN 'USD' ELSE 'MXN' END"


class BomDBService(BomComprasDBMixin):
    """Capa de acceso a datos para BOM."""

    @staticmethod
    def _merge_item_ejecucion(row) -> dict:
        """Combina campos base del item con el overlay de ejecucion real."""
        item = dict(row)
        item["tipo_origen_item"] = item.get("tipo_origen_item") or "BASE"
        item["id_proveedor_base"] = item.get("id_proveedor")
        item["precio_base"] = item.get("precio_unitario")
        item["importe"] = item.get("importe_base")

        if item.get("id_proveedor_real") is not None:
            item["id_proveedor"] = item["id_proveedor_real"]
        item["proveedor_nombre"] = (
            item.get("proveedor_real_nombre") or item.get("proveedor_base_nombre")
        )

        for real_key, public_key in (
            ("fecha_estimada_entrega_real", "fecha_estimada_entrega"),
            ("fecha_llegada_real_ejecucion", "fecha_llegada_real"),
            ("tipo_entrega_real", "tipo_entrega"),
            ("cantidad_recibida_real", "cantidad_recibida"),
        ):
            if item.get(real_key) is not None:
                item[public_key] = item[real_key]

        cantidad_recibida = item.get("cantidad_recibida") or 0
        cantidad = item.get("cantidad") or 0
        if cantidad and cantidad_recibida >= cantidad:
            item["entregado"] = True

        return item

    # ─── BOM CABECERA ───────────────────────────────────────

    async def listar_paquetes_proyecto(self, conn, id_proyecto: UUID) -> List[dict]:
        """Lista paquetes y sus dos cabezas sin consultas N+1."""
        rows = await conn.fetch(
            """
            SELECT
                p.*,
                creador.nombre AS creado_por_nombre,
                ingeniero.nombre AS ingeniero_responsable_nombre,
                trabajo.version AS version_trabajo,
                trabajo.estatus AS estatus_trabajo,
                trabajo.lock_version AS bom_lock_version,
                oficial.version AS version_oficial,
                oficial.fecha_aprobacion_final AS fecha_aprobacion_oficial,
                COALESCE(items.total_items, 0) AS total_items,
                items.total_mxn AS total_trabajo_mxn,
                items.total_usd AS total_trabajo_usd
            FROM tb_bom_paquetes p
            LEFT JOIN tb_usuarios creador ON creador.id_usuario = p.creado_por
            LEFT JOIN tb_usuarios ingeniero ON ingeniero.id_usuario = p.ingeniero_responsable_id
            LEFT JOIN tb_bom trabajo ON trabajo.id_bom = p.cabeza_trabajo_id
            LEFT JOIN tb_bom oficial ON oficial.id_bom = p.cabeza_oficial_id
            LEFT JOIN LATERAL (
                SELECT
                    COUNT(*) FILTER (WHERE i.activo) AS total_items,
                    CASE WHEN COUNT(*) FILTER (
                        WHERE i.activo AND (
                            i.cantidad IS NULL OR i.precio_unitario IS NULL
                            OR i.moneda IS NULL OR i.moneda NOT IN ('MXN', 'USD')
                        )
                    ) > 0 THEN NULL ELSE COALESCE(SUM(
                        i.cantidad * i.precio_unitario
                    ) FILTER (WHERE i.activo AND i.moneda = 'MXN'), 0) END
                        AS total_mxn,
                    CASE WHEN COUNT(*) FILTER (
                        WHERE i.activo AND (
                            i.cantidad IS NULL OR i.precio_unitario IS NULL
                            OR i.moneda IS NULL OR i.moneda NOT IN ('MXN', 'USD')
                        )
                    ) > 0 THEN NULL ELSE COALESCE(SUM(
                        i.cantidad * i.precio_unitario
                    ) FILTER (WHERE i.activo AND i.moneda = 'USD'), 0) END
                        AS total_usd
                FROM tb_bom_items i
                WHERE i.id_bom = p.cabeza_trabajo_id
            ) items ON TRUE
            WHERE p.id_proyecto = $1
              AND p.estado_paquete <> 'CANCELADO'
            ORDER BY p.created_at, p.id_paquete
            """,
            id_proyecto,
        )
        return [dict(row) for row in rows]

    async def get_paquete_by_id(self, conn, id_paquete: UUID) -> Optional[dict]:
        row = await conn.fetchrow(
            """
            SELECT p.*,
                   u.nombre AS ingeniero_responsable_nombre,
                   t.version AS version_trabajo,
                   t.estatus AS estatus_trabajo,
                   o.version AS version_oficial
            FROM tb_bom_paquetes p
            LEFT JOIN tb_usuarios u ON u.id_usuario = p.ingeniero_responsable_id
            LEFT JOIN tb_bom t ON t.id_bom = p.cabeza_trabajo_id
            LEFT JOIN tb_bom o ON o.id_bom = p.cabeza_oficial_id
            WHERE p.id_paquete = $1
            """,
            id_paquete,
        )
        return dict(row) if row else None

    async def get_paquete_for_update(self, conn, id_paquete: UUID) -> Optional[dict]:
        row = await conn.fetchrow(
            "SELECT * FROM tb_bom_paquetes WHERE id_paquete = $1 FOR UPDATE",
            id_paquete,
        )
        return dict(row) if row else None

    async def get_bom_for_update(self, conn, id_bom: UUID) -> Optional[dict]:
        """Bloquea paquete y version, en ese orden, y devuelve cabezas actuales."""
        row = await conn.fetchrow(
            """
            WITH paquete AS MATERIALIZED (
                SELECT p.*
                FROM tb_bom_paquetes p
                WHERE p.id_paquete = (
                    SELECT referencia.id_paquete
                    FROM tb_bom referencia
                    WHERE referencia.id_bom = $1
                )
                FOR UPDATE OF p
            )
            SELECT b.*,
                   p.estado_paquete,
                   p.cabeza_trabajo_id,
                   p.cabeza_oficial_id,
                   (p.cabeza_trabajo_id = b.id_bom) AS es_cabeza_trabajo,
                   (p.cabeza_oficial_id = b.id_bom) AS es_cabeza_oficial,
                   pg.proyecto_id_estandar
            FROM tb_bom b
            JOIN paquete p ON p.id_paquete = b.id_paquete
            LEFT JOIN tb_proyectos_gate pg ON pg.id_proyecto = b.id_proyecto
            WHERE b.id_bom = $1
            FOR UPDATE OF b
            """,
            id_bom,
        )
        return dict(row) if row else None

    async def incrementar_lock_bom_cas(
        self, conn, id_bom: UUID, lock_version_esperado: int,
        estatus_esperado: str,
    ) -> Optional[dict]:
        """Reserva una mutacion base; el primer formulario vigente gana."""
        row = await conn.fetchrow(
            """
            WITH paquete AS MATERIALIZED (
                SELECT p.id_paquete
                FROM tb_bom_paquetes p
                WHERE p.id_paquete = (
                    SELECT referencia.id_paquete
                    FROM tb_bom referencia
                    WHERE referencia.id_bom = $1
                )
                  AND p.estado_paquete = 'ACTIVO'
                  AND p.cabeza_trabajo_id = $1
                FOR UPDATE OF p
            )
            UPDATE tb_bom b
            SET lock_version = b.lock_version + 1,
                updated_at = NOW()
            FROM paquete p
            WHERE b.id_bom = $1
              AND b.lock_version = $2
              AND b.estatus = $3
              AND p.id_paquete = b.id_paquete
            RETURNING b.*
            """,
            id_bom, lock_version_esperado, estatus_esperado,
        )
        return dict(row) if row else None

    async def get_tipo_cambio_manual_info(self, conn, id_proyecto: UUID) -> Optional[dict]:
        """Detalle del TC manual activo del proyecto (para el indicador del consolidado)."""
        row = await conn.fetchrow(
            """
            SELECT e.tipo_cambio_manual, e.tipo_cambio_manual_fijado_en,
                   u.nombre AS tipo_cambio_manual_fijado_por_nombre
            FROM tb_bom_proyecto_estado e
            LEFT JOIN tb_usuarios u ON u.id_usuario = e.tipo_cambio_manual_fijado_por
            WHERE e.id_proyecto = $1 AND e.tipo_cambio_manual IS NOT NULL
            """,
            id_proyecto,
        )
        return dict(row) if row else None

    async def get_id_proyecto_by_bom(self, conn, id_bom: UUID) -> Optional[UUID]:
        """Lookup liviano de id_proyecto por BOM, sin los joins pesados de get_bom_by_id."""
        return await conn.fetchval(
            "SELECT id_proyecto FROM tb_bom WHERE id_bom = $1", id_bom
        )

    async def get_id_paquete_by_bom(self, conn, id_bom: UUID) -> Optional[UUID]:
        """Lookup liviano de id_paquete por BOM, sin los joins pesados de get_bom_by_id."""
        return await conn.fetchval(
            "SELECT id_paquete FROM tb_bom WHERE id_bom = $1", id_bom
        )

    async def get_bom_subtitulo(self, conn, id_bom: UUID) -> Optional[dict]:
        """Lookup liviano de version + codigo de paquete por BOM, para el subtitulo
        de los modales de log (Historial/Aprobaciones/Adendas/Versiones) -- sin los
        joins pesados de get_bom_by_id."""
        row = await conn.fetchrow(
            """
            SELECT b.version, paquete.codigo AS paquete_codigo
            FROM tb_bom b
            JOIN tb_bom_paquetes paquete ON paquete.id_paquete = b.id_paquete
            WHERE b.id_bom = $1
            """,
            id_bom,
        )
        return dict(row) if row else None

    async def get_estado_proyecto_for_update(self, conn, id_proyecto: UUID) -> dict:
        await conn.execute(
            """
            INSERT INTO tb_bom_proyecto_estado (id_proyecto)
            VALUES ($1)
            ON CONFLICT (id_proyecto) DO NOTHING
            """,
            id_proyecto,
        )
        row = await conn.fetchrow(
            "SELECT * FROM tb_bom_proyecto_estado WHERE id_proyecto = $1 FOR UPDATE",
            id_proyecto,
        )
        return dict(row)

    async def get_estado_proyecto(self, conn, id_proyecto: UUID) -> Optional[dict]:
        row = await conn.fetchrow(
            "SELECT * FROM tb_bom_proyecto_estado WHERE id_proyecto = $1",
            id_proyecto,
        )
        return dict(row) if row else None

    async def actualizar_captura_proyecto_cas(
        self, conn, id_proyecto: UUID, lock_version_esperado: int,
        captura_cerrada: bool, actor_id: UUID, motivo: str,
        modulos_fv_snapshot: Optional[int] = None,
        potencia_pico_kwp_snapshot=None,
    ) -> Optional[dict]:
        row = await conn.fetchrow(
            """
            UPDATE tb_bom_proyecto_estado
            SET captura_cerrada = $3,
                cerrada_por = CASE WHEN $3 THEN $4 ELSE NULL END,
                cerrada_en = CASE WHEN $3 THEN NOW() ELSE NULL END,
                motivo = $5,
                actualizado_por = $4,
                cambio_estado_en = NOW(),
                modulos_fv_snapshot = CASE WHEN $3 THEN $6 ELSE modulos_fv_snapshot END,
                potencia_pico_kwp_snapshot = CASE WHEN $3 THEN $7 ELSE potencia_pico_kwp_snapshot END,
                lock_version = lock_version + 1,
                updated_at = NOW()
            WHERE id_proyecto = $1
              AND lock_version = $2
            RETURNING *
            """,
            id_proyecto, lock_version_esperado, captura_cerrada, actor_id, motivo,
            modulos_fv_snapshot, potencia_pico_kwp_snapshot,
        )
        return dict(row) if row else None

    async def set_tipo_cambio_manual_cas(
        self, conn, id_proyecto: UUID, lock_version_esperado: int,
        tipo_cambio_manual: Decimal, actor_id: UUID,
    ) -> Optional[dict]:
        """Fija (o reemplaza) el TC manual del proyecto con CAS sobre lock_version."""
        row = await conn.fetchrow(
            """
            UPDATE tb_bom_proyecto_estado
            SET tipo_cambio_manual = $3,
                tipo_cambio_manual_fijado_por = $4,
                tipo_cambio_manual_fijado_en = NOW(),
                lock_version = lock_version + 1,
                updated_at = NOW()
            WHERE id_proyecto = $1
              AND lock_version = $2
            RETURNING *
            """,
            id_proyecto, lock_version_esperado, tipo_cambio_manual, actor_id,
        )
        return dict(row) if row else None

    async def limpiar_tipo_cambio_manual_cas(
        self, conn, id_proyecto: UUID, lock_version_esperado: int,
    ) -> Optional[dict]:
        """Quita el TC manual del proyecto (vuelve a Banxico/promedio) con CAS."""
        row = await conn.fetchrow(
            """
            UPDATE tb_bom_proyecto_estado
            SET tipo_cambio_manual = NULL,
                tipo_cambio_manual_fijado_por = NULL,
                tipo_cambio_manual_fijado_en = NULL,
                lock_version = lock_version + 1,
                updated_at = NOW()
            WHERE id_proyecto = $1
              AND lock_version = $2
            RETURNING *
            """,
            id_proyecto, lock_version_esperado,
        )
        return dict(row) if row else None

    async def get_siguiente_codigo_paquete(self, conn, id_proyecto: UUID) -> str:
        numero = await conn.fetchval(
            """
            SELECT COALESCE(MAX(
                CASE
                    WHEN codigo ~ '^BOM-[0-9]+$'
                    THEN SUBSTRING(codigo FROM 5)::INTEGER
                    ELSE 0
                END
            ), 0) + 1
            FROM tb_bom_paquetes
            WHERE id_proyecto = $1
            """,
            id_proyecto,
        )
        return f"BOM-{numero:03d}"

    async def crear_paquete(
        self, conn, id_proyecto: UUID, codigo: str, nombre: str,
        tipo_alcance: str, descripcion_alcance: Optional[str], creado_por: UUID,
        ingeniero_responsable_id: UUID, responsable_ing_id: Optional[UUID],
        coordinador_obra_id: Optional[UUID], jefe_construccion_id: Optional[UUID],
        clave_idempotencia: str,
    ) -> dict:
        row = await conn.fetchrow(
            """
            INSERT INTO tb_bom_paquetes (
                id_proyecto, codigo, nombre, tipo_alcance, descripcion_alcance,
                creado_por, ingeniero_responsable_id, responsable_ing_id,
                coordinador_obra_id, jefe_construccion_id, clave_idempotencia
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            RETURNING *
            """,
            id_proyecto, codigo, nombre, tipo_alcance, descripcion_alcance,
            creado_por, ingeniero_responsable_id, responsable_ing_id,
            coordinador_obra_id, jefe_construccion_id, clave_idempotencia,
        )
        return dict(row)

    async def get_paquete_por_clave_idempotencia(
        self, conn, id_proyecto: UUID, clave_idempotencia: str,
    ) -> Optional[dict]:
        row = await conn.fetchrow(
            """
            SELECT *
            FROM tb_bom_paquetes
            WHERE id_proyecto = $1
              AND clave_idempotencia = $2
            """,
            id_proyecto, clave_idempotencia,
        )
        return dict(row) if row else None

    async def actualizar_cabeza_trabajo(
        self, conn, id_paquete: UUID, id_bom: UUID,
        lock_version_esperado: int,
    ) -> Optional[dict]:
        row = await conn.fetchrow(
            """
            UPDATE tb_bom_paquetes
            SET cabeza_trabajo_id = $2,
                lock_version = lock_version + 1,
                updated_at = NOW()
            WHERE id_paquete = $1
              AND lock_version = $3
            RETURNING *
            """,
            id_paquete, id_bom, lock_version_esperado,
        )
        return dict(row) if row else None

    async def actualizar_cabeza_oficial(
        self, conn, id_paquete: UUID, id_bom: UUID,
        lock_version_esperado: int,
    ) -> Optional[dict]:
        row = await conn.fetchrow(
            """
            UPDATE tb_bom_paquetes
            SET cabeza_oficial_id = $2,
                cabeza_trabajo_id = $2,
                lock_version = lock_version + 1,
                updated_at = NOW()
            WHERE id_paquete = $1
              AND lock_version = $3
            RETURNING *
            """,
            id_paquete, id_bom, lock_version_esperado,
        )
        return dict(row) if row else None

    async def actualizar_estado_paquete_cas(
        self, conn, id_paquete: UUID, lock_version_esperado: int,
        estado_esperado: str, nuevo_estado: str,
    ) -> Optional[dict]:
        row = await conn.fetchrow(
            """
            UPDATE tb_bom_paquetes
            SET estado_paquete = $4,
                lock_version = lock_version + 1,
                updated_at = NOW()
            WHERE id_paquete = $1
              AND lock_version = $2
              AND estado_paquete = $3
            RETURNING *
            """,
            id_paquete, lock_version_esperado, estado_esperado, nuevo_estado,
        )
        return dict(row) if row else None

    async def reclasificar_paquete_cas(
        self, conn, id_paquete: UUID, lock_version_esperado: int,
        tipo_alcance: str, nombre: str, descripcion_alcance: Optional[str],
    ) -> Optional[dict]:
        row = await conn.fetchrow(
            """
            UPDATE tb_bom_paquetes
            SET tipo_alcance = $3,
                nombre = $4,
                descripcion_alcance = $5,
                lock_version = lock_version + 1,
                updated_at = NOW()
            WHERE id_paquete = $1
              AND lock_version = $2
              AND estado_paquete <> 'CANCELADO'
            RETURNING *
            """,
            id_paquete, lock_version_esperado, tipo_alcance,
            nombre, descripcion_alcance,
        )
        return dict(row) if row else None

    async def reasignar_paquete_borrador_cas(
        self, conn, id_paquete: UUID, id_bom: UUID,
        lock_version_paquete: int, lock_version_bom: int,
        ingeniero_responsable_id: UUID, responsable_ing_id: Optional[UUID],
        coordinador_obra_id: Optional[UUID], jefe_construccion_id: Optional[UUID],
    ) -> Optional[dict]:
        paquete = await conn.fetchrow(
            """
            UPDATE tb_bom_paquetes
            SET ingeniero_responsable_id = $4,
                responsable_ing_id = $5,
                coordinador_obra_id = $6,
                jefe_construccion_id = $7,
                lock_version = lock_version + 1,
                updated_at = NOW()
            WHERE id_paquete = $1
              AND cabeza_trabajo_id = $2
              AND lock_version = $3
              AND estado_paquete = 'ACTIVO'
            RETURNING *
            """,
            id_paquete, id_bom, lock_version_paquete,
            ingeniero_responsable_id, responsable_ing_id,
            coordinador_obra_id, jefe_construccion_id,
        )
        if not paquete:
            return None
        bom = await conn.fetchrow(
            """
            UPDATE tb_bom
            SET ingeniero_responsable_id = $3,
                responsable_ing = $4,
                coordinador_obra = $5,
                jefe_construccion = $6,
                lock_version = lock_version + 1,
                updated_at = NOW()
            WHERE id_bom = $1
              AND lock_version = $2
              AND estatus = 'BORRADOR'
            RETURNING *
            """,
            id_bom, lock_version_bom, ingeniero_responsable_id,
            responsable_ing_id, coordinador_obra_id, jefe_construccion_id,
        )
        return dict(bom) if bom else None

    async def get_actividad_downstream_paquete(
        self, conn, id_paquete: UUID,
    ) -> bool:
        existe = await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT 1
                FROM tb_bom b
                JOIN tb_bom_cotizaciones c ON c.bom_id = b.id_bom
                WHERE b.id_paquete = $1
                UNION ALL
                SELECT 1
                FROM tb_bom b
                JOIN tb_bom_adendas a ON a.id_bom_base = b.id_bom
                WHERE b.id_paquete = $1
                UNION ALL
                SELECT 1
                FROM tb_bom b
                JOIN tb_bom_item_ejecucion e ON EXISTS (
                    SELECT 1 FROM tb_bom_items i
                    WHERE i.id_item = e.id_item AND i.id_bom = b.id_bom
                )
                WHERE b.id_paquete = $1
            )
            """,
            id_paquete,
        )
        return bool(existe)

    async def listar_versiones_paquete(self, conn, id_paquete: UUID) -> List[dict]:
        rows = await conn.fetch(
            """
            SELECT b.id_bom, b.id_paquete, b.version, b.estatus, b.lock_version,
                   b.created_at AT TIME ZONE 'America/Mexico_City' AS created_at,
                   b.fecha_aprobacion_final,
                   u.nombre AS elaborado_por_nombre
            FROM tb_bom b
            LEFT JOIN tb_usuarios u ON u.id_usuario = b.elaborado_por
            WHERE b.id_paquete = $1
            ORDER BY b.version DESC
            """,
            id_paquete,
        )
        return [dict(row) for row in rows]

    async def get_bom_cabeza_trabajo(self, conn, id_paquete: UUID) -> Optional[dict]:
        id_bom = await conn.fetchval(
            "SELECT cabeza_trabajo_id FROM tb_bom_paquetes WHERE id_paquete = $1",
            id_paquete,
        )
        return await self.get_bom_by_id(conn, id_bom) if id_bom else None

    async def get_bom_cabeza_oficial(self, conn, id_paquete: UUID) -> Optional[dict]:
        id_bom = await conn.fetchval(
            "SELECT cabeza_oficial_id FROM tb_bom_paquetes WHERE id_paquete = $1",
            id_paquete,
        )
        return await self.get_bom_by_id(conn, id_bom) if id_bom else None

    async def crear_bom(
        self, conn, id_proyecto: UUID, elaborado_por: UUID,
        responsable_ing: Optional[UUID] = None,
        jefe_construccion: Optional[UUID] = None,
        coordinador_obra: Optional[UUID] = None,
        notas: Optional[str] = None,
        version: int = 1,
        id_paquete: Optional[UUID] = None,
        ingeniero_responsable_id: Optional[UUID] = None,
    ) -> dict:
        """Crea un nuevo BOM para un proyecto."""
        row = await conn.fetchrow("""
            INSERT INTO tb_bom (id_proyecto, id_paquete, version, estatus, elaborado_por,
                                ingeniero_responsable_id,
                                responsable_ing, jefe_construccion,
                                coordinador_obra, notas)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING *
        """, id_proyecto, id_paquete, version, EstatusBOM.BORRADOR.value,
            elaborado_por, ingeniero_responsable_id or elaborado_por,
            responsable_ing, jefe_construccion, coordinador_obra, notas)
        return dict(row)

    async def get_bom_by_id(self, conn, id_bom: UUID) -> Optional[dict]:
        """Obtiene un BOM por su ID con datos de usuarios y proyecto."""
        row = await conn.fetchrow("""
            SELECT b.*,
                   paquete.codigo AS paquete_codigo,
                   paquete.nombre AS paquete_nombre,
                   paquete.tipo_alcance,
                   paquete.descripcion_alcance,
                   paquete.estado_paquete,
                   paquete.cabeza_trabajo_id,
                   paquete.cabeza_oficial_id,
                   paquete.lock_version AS paquete_lock_version,
                   (paquete.cabeza_trabajo_id = b.id_bom) AS es_cabeza_trabajo,
                   (paquete.cabeza_oficial_id = b.id_bom) AS es_cabeza_oficial,
                   u1.nombre AS elaborado_por_nombre,
                   u2.nombre AS responsable_ing_nombre,
                   u3.nombre AS jefe_construccion_nombre,
                   u4.nombre AS coordinador_obra_nombre,
                   o.nombre_proyecto AS proyecto_nombre,
                   p.id_oportunidad,
                   p.proyecto_id_estandar,
                   COALESCE(items.total, 0) AS total_items,
                   COALESCE(items.entregados, 0) AS items_entregados
            FROM tb_bom b
            JOIN tb_bom_paquetes paquete ON paquete.id_paquete = b.id_paquete
            LEFT JOIN tb_usuarios u1 ON u1.id_usuario = b.elaborado_por
            LEFT JOIN tb_usuarios u2 ON u2.id_usuario = b.responsable_ing
            LEFT JOIN tb_usuarios u3 ON u3.id_usuario = b.jefe_construccion
            LEFT JOIN tb_usuarios u4 ON u4.id_usuario = b.coordinador_obra
            LEFT JOIN tb_proyectos_gate p ON p.id_proyecto = b.id_proyecto
            LEFT JOIN tb_oportunidades o ON o.id_oportunidad = p.id_oportunidad
            LEFT JOIN LATERAL (
                SELECT COUNT(*) FILTER (WHERE activo) AS total,
                       COUNT(*) FILTER (WHERE activo AND entregado) AS entregados
                FROM tb_bom_items WHERE id_bom = b.id_bom
            ) items ON TRUE
            WHERE b.id_bom = $1
        """, id_bom)
        return dict(row) if row else None

    async def update_bom_estatus_cas(
        self, conn, id_bom: UUID, estatus_esperado: str,
        lock_version_esperado: int, nuevo_estatus: str, **kwargs,
    ) -> Optional[dict]:
        """Transicion condicional: estado y revision deben seguir vigentes."""
        sets = ["estatus = $4", "lock_version = lock_version + 1", "updated_at = NOW()"]
        params = [id_bom, estatus_esperado, lock_version_esperado, nuevo_estatus]
        campo_map = {
            "fecha_envio_ing": "fecha_envio_ing",
            "fecha_aprobacion_ing": "fecha_aprobacion_ing",
            "fecha_envio_obra": "fecha_envio_obra",
            "fecha_aprobacion_obra": "fecha_aprobacion_obra",
            "fecha_envio_const": "fecha_envio_const",
            "fecha_aprobacion_const": "fecha_aprobacion_const",
            "fecha_envio_final": "fecha_envio_final",
            "fecha_aprobacion_final": "fecha_aprobacion_final",
            "responsable_ing": "responsable_ing",
            "jefe_construccion": "jefe_construccion",
            "coordinador_obra": "coordinador_obra",
            "notas": "notas",
            "modulos_fv_snapshot": "modulos_fv_snapshot",
            "potencia_pico_kwp_snapshot": "potencia_pico_kwp_snapshot",
            "tipo_cambio_aprobacion": "tipo_cambio_aprobacion",
            "fecha_tipo_cambio_aprobacion": "fecha_tipo_cambio_aprobacion",
            "subtotal_base_mxn_snapshot": "subtotal_base_mxn_snapshot",
            "subtotal_base_usd_snapshot": "subtotal_base_usd_snapshot",
            "total_aprobado_mxn": "total_aprobado_mxn",
        }
        for key, column in campo_map.items():
            if key in kwargs:
                params.append(kwargs[key])
                sets.append(f"{column} = ${len(params)}")
        row = await conn.fetchrow(
            f"""
            WITH paquete AS MATERIALIZED (
                SELECT p.id_paquete
                FROM tb_bom_paquetes p
                WHERE p.id_paquete = (
                    SELECT referencia.id_paquete
                    FROM tb_bom referencia
                    WHERE referencia.id_bom = $1
                )
                  AND p.estado_paquete = 'ACTIVO'
                  AND p.cabeza_trabajo_id = $1
                FOR UPDATE OF p
            )
            UPDATE tb_bom AS b
            SET {', '.join(sets)}
            FROM paquete AS p
            WHERE b.id_bom = $1
              AND b.estatus = $2
              AND b.lock_version = $3
              AND p.id_paquete = b.id_paquete
            RETURNING b.*
            """,
            *params,
        )
        return dict(row) if row else None

    async def invalidar_aprobaciones_vigentes(
        self, conn, id_bom: UUID, invalidada_por: UUID,
    ) -> None:
        await conn.execute(
            """
            UPDATE tb_bom_aprobaciones
            SET vigente = FALSE,
                invalidada_en = NOW(),
                invalidada_por = $2
            WHERE id_bom = $1
              AND vigente = TRUE
            """,
            id_bom, invalidada_por,
        )

    async def registrar_evento_outbox(
        self, conn, clave_idempotencia: str, tipo_evento: str,
        id_proyecto: UUID, actor_id: UUID, payload: dict,
        id_paquete: Optional[UUID] = None, id_bom: Optional[UUID] = None,
        id_item: Optional[UUID] = None, id_documento: Optional[UUID] = None,
    ) -> dict:
        url_destino = (
            f"/bom/paquetes/{id_paquete}/ui"
            if id_paquete else f"/bom/{id_proyecto}/ui"
        )
        paquete_codigo = await conn.fetchval(
            """
            SELECT codigo FROM tb_bom_paquetes
            WHERE ($1::UUID IS NOT NULL AND id_paquete = $1)
               OR ($1::UUID IS NULL AND id_proyecto = $2 AND estado_paquete = 'ACTIVO')
            LIMIT 1
            """,
            id_paquete, id_proyecto,
        )
        payload_completo = {
            **payload,
            "id_proyecto": str(id_proyecto),
            "id_paquete": str(id_paquete) if id_paquete else None,
            "id_bom": str(id_bom) if id_bom else None,
            "id_item": str(id_item) if id_item else None,
            "id_documento": str(id_documento) if id_documento else None,
            "paquete_codigo": paquete_codigo,
            "url_destino": url_destino,
            "payload_version": 1,
        }
        row = await conn.fetchrow(
            """
            INSERT INTO tb_bom_eventos_outbox (
                clave_idempotencia, tipo_evento, id_proyecto, id_paquete,
                id_bom, id_item, id_documento, actor_id, payload,
                payload_version, url_destino
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, 1, $10)
            ON CONFLICT (clave_idempotencia) DO UPDATE SET
                clave_idempotencia = tb_bom_eventos_outbox.clave_idempotencia
            RETURNING *
            """,
            clave_idempotencia, tipo_evento, id_proyecto, id_paquete,
            id_bom, id_item, id_documento, actor_id,
            json.dumps(payload_completo), url_destino,
        )
        evento = dict(row)
        await conn.execute(
            """
            WITH paquete AS (
                SELECT p.*
                FROM tb_bom_paquetes p
                WHERE ($2::UUID IS NOT NULL AND p.id_paquete = $2)
                   OR ($2::UUID IS NULL AND p.id_proyecto = $3
                       AND p.estado_paquete = 'ACTIVO')
            ), direccion AS (
                SELECT CASE
                    WHEN cfg.valor ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
                    THEN cfg.valor::UUID
                    ELSE NULL
                END AS titular_id
                FROM tb_configuracion_global cfg
                WHERE cfg.clave = 'bom_aprobador_final_id'
            ), candidatos_paquete AS (
                SELECT candidato.rol, candidato.titular_id
                FROM paquete p
                CROSS JOIN LATERAL (
                    VALUES
                        ('INGENIERO', p.ingeniero_responsable_id),
                        ('RESPONSABLE_ING', p.responsable_ing_id),
                        ('COORDINADOR_OBRA', p.coordinador_obra_id),
                        ('JEFE_CONSTRUCCION', p.jefe_construccion_id)
                ) candidato(rol, titular_id)
            ), titulares AS (
                SELECT DISTINCT titular_id
                FROM candidatos_paquete
                WHERE titular_id IS NOT NULL
                  AND (
                      ($7 = 'ENVIO_REVISION_ING' AND rol = 'RESPONSABLE_ING')
                      OR ($7 IN ('APROBACION_ING', 'ENVIO_REVISION_OBRA',
                                 'COTIZACION_SELECCIONADA')
                          AND rol = 'COORDINADOR_OBRA')
                      OR ($7 IN ('RECHAZO_ING', 'COTIZACION_RECHAZADA')
                          AND rol = 'INGENIERO')
                      OR ($7 IN ('APROBACION_OBRA', 'ENVIO_REVISION_CONST')
                          AND rol = 'JEFE_CONSTRUCCION')
                      OR ($7 IN ('RECHAZO_OBRA', 'RECHAZO_CONST',
                                 'RECHAZO_FINAL', 'ADENDA_RECHAZADA')
                          AND rol IN ('INGENIERO', 'RESPONSABLE_ING'))
                      OR ($7 = 'ADENDA_PENDIENTE_INGENIERIA'
                          AND rol = 'RESPONSABLE_ING')
                      OR ($7 IN ('PAQUETE_CREADO', 'PAQUETE_ACTIVO',
                                 'PAQUETE_ARCHIVADO', 'PAQUETE_CANCELADO',
                                 'PAQUETE_RECLASIFICADO', 'PAQUETE_REASIGNADO',
                                 'CAPTURA_CERRADA', 'CAPTURA_REABIERTA',
                                 'CANCELACION', 'NUEVA_VERSION',
                                 'APROBACION_FINAL', 'ADENDA_APROBADA')
                          AND rol IN ('INGENIERO', 'RESPONSABLE_ING',
                                      'COORDINADOR_OBRA', 'JEFE_CONSTRUCCION'))
                  )
                UNION
                SELECT titular_id
                FROM direccion
                WHERE titular_id IS NOT NULL
                  AND $7 IN ('APROBACION_CONST', 'ENVIO_REVISION_FINAL',
                             'COTIZACION_APROBACION_SOLICITADA',
                             'AUTORIZACION_OBRA')
                UNION
                SELECT autorizacion.creado_por
                FROM tb_bom_autorizaciones autorizacion
                WHERE autorizacion.id = $8
                  AND $7 IN ('AUTORIZACION_DIRECCION', 'AUTORIZACION_FINANZAS',
                             'AUTORIZACION_RECHAZADA',
                             'AUTORIZACION_PAGO_PARCIAL', 'AUTORIZACION_PAGADA')
                UNION
                SELECT aprobacion.solicitado_por
                FROM tb_bom_cotizacion_aprobaciones aprobacion
                WHERE aprobacion.id = $8
                  AND $7 IN ('COTIZACION_APROBACION_APROBADA',
                             'COTIZACION_APROBACION_RECHAZADA')
                UNION
                SELECT adenda.creado_por
                FROM tb_bom_adendas adenda
                WHERE adenda.id_adenda = $8
                  AND $7 IN ('ADENDA_APROBADA', 'ADENDA_RECHAZADA')
            ), destinos AS (
                SELECT DISTINCT ON (COALESCE(s.suplente_id, t.titular_id))
                    COALESCE(s.suplente_id, t.titular_id) AS destinatario_id,
                    t.titular_id,
                    u.email
                FROM titulares t
                LEFT JOIN LATERAL (
                    SELECT suplente_id
                    FROM tb_bom_suplencias
                    WHERE titular_id = t.titular_id
                      AND activo = TRUE
                      AND fecha_fin >= (NOW() AT TIME ZONE 'America/Mexico_City')::DATE
                    ORDER BY fecha_fin DESC, created_at DESC
                    LIMIT 1
                ) s ON TRUE
                JOIN tb_usuarios u
                  ON u.id_usuario = COALESCE(s.suplente_id, t.titular_id)
                 AND u.is_active = TRUE
                WHERE COALESCE(s.suplente_id, t.titular_id) <> $4
                ORDER BY COALESCE(s.suplente_id, t.titular_id), t.titular_id
            ), canales AS (
                SELECT 'INTERNA'::VARCHAR AS canal
                UNION ALL SELECT 'CORREO'::VARCHAR
            )
            INSERT INTO tb_bom_evento_entregas (
                id_evento, canal, destinatario_id, titular_id,
                direccion_destino, clave_idempotencia, payload, payload_version
            )
            SELECT
                $1,
                canal.canal,
                destino.destinatario_id,
                destino.titular_id,
                CASE WHEN canal.canal = 'CORREO' THEN destino.email END,
                $5 || ':' || canal.canal || ':' || destino.destinatario_id::TEXT,
                $6::JSONB,
                1
            FROM destinos destino
            CROSS JOIN canales canal
            WHERE canal.canal <> 'CORREO' OR destino.email IS NOT NULL
            ON CONFLICT (id_evento, canal, destinatario_id) DO NOTHING
            """,
            evento["id_evento"], id_paquete, id_proyecto, actor_id,
            clave_idempotencia, json.dumps(payload_completo), tipo_evento,
            id_documento,
        )
        return evento

    async def lock_configuracion_proyecto(self, conn, id_proyecto: UUID) -> None:
        await conn.fetchval(
            "SELECT pg_advisory_xact_lock(hashtextextended($1::text, 0))",
            f"bom-config-proyecto:{id_proyecto}",
        )

    async def get_metricas_paneles_proyecto(self, conn, id_proyecto: UUID) -> dict:
        row = await conn.fetchrow(
            """
            SELECT
                SUM(pp.cantidad)::INTEGER AS modulos_fv,
                (SUM(pp.cantidad * panel.potencia_w)::NUMERIC / 1000)
                    ::NUMERIC(16,6)
                    AS potencia_pico_kwp
            FROM tb_proyecto_paneles pp
            JOIN tb_cat_paneles_fv panel ON panel.id = pp.id_panel
            WHERE pp.id_proyecto = $1
            """,
            id_proyecto,
        )
        return dict(row)

    async def get_totales_base_por_moneda(self, conn, id_bom: UUID) -> dict:
        row = await conn.fetchrow(
            """
            SELECT
                COALESCE(SUM(i.cantidad * i.precio_unitario)
                    FILTER (WHERE i.activo AND i.moneda = 'MXN'), 0)
                    AS total_mxn,
                COALESCE(SUM(i.cantidad * i.precio_unitario)
                    FILTER (WHERE i.activo AND i.moneda = 'USD'), 0)
                    AS total_usd,
                COUNT(*) FILTER (
                    WHERE i.activo
                      AND (
                          i.precio_unitario IS NULL
                          OR i.moneda IS NULL
                          OR i.moneda NOT IN ('MXN', 'USD')
                      )
                ) AS costos_desconocidos
            FROM tb_bom_items i
            WHERE i.id_bom = $1
            """,
            id_bom,
        )
        return dict(row)

    async def get_consolidado_paquetes(
        self, conn, id_proyecto: UUID, modo: str,
    ) -> List[dict]:
        """Resumen financiero por paquete usando exactamente una cabeza por paquete."""
        rows = await conn.fetch(
            """
            WITH seleccion AS (
                SELECT
                    p.id_paquete,
                    p.codigo,
                    p.nombre,
                    p.tipo_alcance,
                    p.descripcion_alcance,
                    p.ingeniero_responsable_id,
                    CASE WHEN $2 = 'OFICIAL'
                        THEN p.cabeza_oficial_id
                        ELSE p.cabeza_trabajo_id
                    END AS id_bom
                FROM tb_bom_paquetes p
                WHERE p.id_proyecto = $1
                  AND p.estado_paquete = 'ACTIVO'
            ), base AS (
                SELECT
                    s.id_paquete,
                    COALESCE(SUM(i.cantidad * i.precio_unitario)
                        FILTER (
                            WHERE i.activo
                              AND i.moneda = 'MXN'
                              AND COALESCE(e.estatus_ejecucion, '')
                                  NOT IN ('REEMPLAZADO', 'NO_ADQUIRIDO')
                        ), 0) AS base_vivo_mxn,
                    COALESCE(SUM(i.cantidad * i.precio_unitario)
                        FILTER (
                            WHERE i.activo
                              AND i.moneda = 'USD'
                              AND COALESCE(e.estatus_ejecucion, '')
                                  NOT IN ('REEMPLAZADO', 'NO_ADQUIRIDO')
                        ), 0) AS base_vivo_usd,
                    COUNT(*) FILTER (
                        WHERE i.activo
                          AND (
                              i.precio_unitario IS NULL
                              OR i.moneda IS NULL
                              OR i.moneda NOT IN ('MXN', 'USD')
                          )
                    ) AS costos_desconocidos,
                    COUNT(i.id_item) FILTER (WHERE i.activo) AS total_items
                FROM seleccion s
                LEFT JOIN tb_bom_items i ON i.id_bom = s.id_bom
                LEFT JOIN tb_bom_item_ejecucion e ON e.id_item = i.id_item
                GROUP BY s.id_paquete
            ), adendas AS (
                SELECT
                    s.id_paquete,
                    COALESCE(SUM(a.impacto_base_mxn_snapshot), 0) AS impacto_mxn,
                    COALESCE(SUM(a.impacto_base_usd_snapshot), 0) AS impacto_usd,
                    COALESCE(SUM(a.impacto_aprobado_mxn), 0) AS impacto_total_mxn
                FROM seleccion s
                LEFT JOIN tb_bom_adendas a
                    ON a.id_bom_base = s.id_bom AND a.estatus = 'APROBADA'
                GROUP BY s.id_paquete
            ), cotizado AS (
                SELECT
                    b.id_paquete,
                    COALESCE(SUM(c.total) FILTER (WHERE c.moneda = 'MXN'), 0) AS mxn,
                    COALESCE(SUM(c.total) FILTER (WHERE c.moneda = 'USD'), 0) AS usd
                FROM tb_bom b
                JOIN tb_bom_cotizaciones c ON c.bom_id = b.id_bom
                WHERE b.id_proyecto = $1
                  AND c.estatus = 'SELECCIONADA'
                GROUP BY b.id_paquete
            ), autorizado AS (
                SELECT
                    b.id_paquete,
                    COALESCE(SUM(a.monto_total) FILTER (WHERE a.moneda = 'MXN'), 0) AS mxn,
                    COALESCE(SUM(a.monto_total) FILTER (WHERE a.moneda = 'USD'), 0) AS usd,
                    CASE WHEN COUNT(*) FILTER (
                        WHERE a.moneda IS NULL
                           OR a.moneda NOT IN ('MXN', 'USD')
                           OR (a.moneda = 'USD' AND a.tipo_cambio_snapshot IS NULL)
                    ) > 0 THEN NULL ELSE COALESCE(SUM(
                        CASE WHEN a.moneda = 'USD'
                            THEN a.monto_total * a.tipo_cambio_snapshot
                            ELSE a.monto_total
                        END
                    ), 0) END AS total_mxn
                FROM tb_bom b
                JOIN tb_bom_autorizaciones a ON a.bom_id = b.id_bom
                WHERE b.id_proyecto = $1
                  AND a.estatus IN ('AUTORIZADO_FINANZAS', 'PAGO_PARCIAL', 'PAGADO')
                GROUP BY b.id_paquete
            ), facturado AS (
                SELECT
                    asignacion.id_paquete,
                    COALESCE(SUM(asignacion.importe_asignado) FILTER (
                        WHERE asignacion.moneda = 'MXN'
                    ), 0) AS mxn,
                    COALESCE(SUM(asignacion.importe_asignado) FILTER (
                        WHERE asignacion.moneda = 'USD'
                    ), 0) AS usd,
                    CASE WHEN COUNT(*) FILTER (
                        WHERE asignacion.moneda = 'USD'
                          AND material.tipo_cambio_xml IS NULL
                    ) > 0 THEN NULL ELSE COALESCE(SUM(
                        CASE WHEN asignacion.moneda = 'USD'
                            THEN asignacion.importe_asignado * material.tipo_cambio_xml
                            ELSE asignacion.importe_asignado
                        END
                    ), 0) END AS total_mxn
                FROM tb_bom_concepto_asignaciones asignacion
                JOIN tb_materiales_historial material
                  ON material.id = asignacion.id_material
                JOIN tb_bom b
                  ON b.id_bom = asignacion.id_bom AND b.id_proyecto = $1
                GROUP BY asignacion.id_paquete
            ), pagado AS (
                SELECT
                    b.id_paquete,
                    COALESCE(SUM(p.monto_pagado) FILTER (WHERE p.moneda = 'MXN'), 0) AS mxn,
                    COALESCE(SUM(p.monto_pagado) FILTER (WHERE p.moneda = 'USD'), 0) AS usd,
                    CASE WHEN COUNT(*) FILTER (
                        WHERE p.moneda = 'USD' AND p.tipo_cambio_usado IS NULL
                    ) > 0 THEN NULL ELSE COALESCE(SUM(
                        CASE WHEN p.moneda = 'USD'
                            THEN p.monto_pagado * p.tipo_cambio_usado
                            ELSE p.monto_pagado
                        END
                    ), 0) END AS total_mxn
                FROM tb_bom_pagos p
                JOIN tb_bom_autorizaciones a ON a.id = p.autorizacion_id
                JOIN tb_bom b ON b.id_bom = a.bom_id AND b.id_proyecto = $1
                GROUP BY b.id_paquete
            )
            SELECT
                s.*,
                b.version,
                b.estatus,
                b.fecha_aprobacion_final,
                b.fecha_tipo_cambio_aprobacion,
                b.tipo_cambio_aprobacion,
                b.modulos_fv_snapshot,
                b.potencia_pico_kwp_snapshot,
                base.total_items,
                CASE WHEN $2 = 'OFICIAL'
                    THEN b.subtotal_base_mxn_snapshot + ad.impacto_mxn
                    ELSE base.base_vivo_mxn
                END AS presupuesto_mxn,
                CASE WHEN $2 = 'OFICIAL'
                    THEN b.subtotal_base_usd_snapshot + ad.impacto_usd
                    ELSE base.base_vivo_usd
                END AS presupuesto_usd,
                CASE WHEN $2 = 'OFICIAL'
                    THEN b.total_aprobado_mxn + ad.impacto_total_mxn
                    WHEN base.costos_desconocidos > 0 THEN NULL
                    WHEN base.base_vivo_usd <> 0 AND b.tipo_cambio_aprobacion IS NULL THEN NULL
                    ELSE base.base_vivo_mxn
                        + (base.base_vivo_usd * COALESCE(b.tipo_cambio_aprobacion, 0))
                END AS presupuesto_total_mxn,
                COALESCE(cot.mxn, 0) AS cotizado_mxn,
                COALESCE(cot.usd, 0) AS cotizado_usd,
                COALESCE(aut.mxn, 0) AS autorizado_mxn,
                COALESCE(aut.usd, 0) AS autorizado_usd,
                CASE WHEN aut.id_paquete IS NULL THEN 0 ELSE aut.total_mxn END
                    AS autorizado_total_mxn,
                COALESCE(fac.mxn, 0) AS facturado_mxn,
                COALESCE(fac.usd, 0) AS facturado_usd,
                CASE WHEN fac.id_paquete IS NULL THEN 0 ELSE fac.total_mxn END
                    AS facturado_total_mxn,
                COALESCE(pag.mxn, 0) AS pagado_mxn,
                COALESCE(pag.usd, 0) AS pagado_usd,
                CASE WHEN pag.id_paquete IS NULL THEN 0 ELSE pag.total_mxn END
                    AS pagado_total_mxn
            FROM seleccion s
            JOIN tb_bom b ON b.id_bom = s.id_bom
            LEFT JOIN base ON base.id_paquete = s.id_paquete
            LEFT JOIN adendas ad ON ad.id_paquete = s.id_paquete
            LEFT JOIN cotizado cot ON cot.id_paquete = s.id_paquete
            LEFT JOIN autorizado aut ON aut.id_paquete = s.id_paquete
            LEFT JOIN facturado fac ON fac.id_paquete = s.id_paquete
            LEFT JOIN pagado pag ON pag.id_paquete = s.id_paquete
            WHERE s.id_bom IS NOT NULL
            ORDER BY s.codigo, s.id_paquete
            """,
            id_proyecto, modo,
        )
        return [dict(row) for row in rows]

    async def get_consolidado_lineas(
        self, conn, id_proyecto: UUID, modo: str,
    ) -> List[dict]:
        """Lineas con procedencia, linea estable y posibles solapamientos."""
        rows = await conn.fetch(
            """
            WITH seleccion AS (
                SELECT
                    p.id_paquete,
                    p.codigo,
                    p.nombre,
                    CASE WHEN $2 = 'OFICIAL'
                        THEN p.cabeza_oficial_id
                        ELSE p.cabeza_trabajo_id
                    END AS id_bom
                FROM tb_bom_paquetes p
                WHERE p.id_proyecto = $1
                  AND p.estado_paquete = 'ACTIVO'
            ), lineas AS (
                SELECT
                    s.id_paquete,
                    s.codigo AS paquete_codigo,
                    s.nombre AS paquete_nombre,
                    b.id_bom,
                    b.version,
                    i.id_item,
                    i.id_linea_bom,
                    i.descripcion,
                    i.cantidad,
                    i.unidad_medida,
                    i.moneda,
                    i.precio_unitario,
                    i.tipo_origen_item,
                    COALESCE(e.estatus_ejecucion, i.estatus_compra, 'PENDIENTE')
                        AS estado_ejecucion,
                    COALESCE(e.cantidad_recibida, 0) AS cantidad_recibida,
                    ARRAY_REMOVE(ARRAY_AGG(DISTINCT g.codigo ORDER BY g.codigo), NULL)
                        AS grupos,
                    COALESCE((
                        SELECT JSONB_OBJECT_AGG(
                            distribucion.grupo_codigo_snapshot,
                            distribucion.porcentaje
                            ORDER BY distribucion.grupo_codigo_snapshot
                        )
                        FROM tb_bom_item_grupo_asignaciones distribucion
                        WHERE distribucion.id_bom_item = i.id_item
                          AND ABS((
                              SELECT SUM(otra.porcentaje)
                              FROM tb_bom_item_grupo_asignaciones otra
                              WHERE otra.id_bom_item = i.id_item
                          ) - 1) <= 0.000001
                    ), '{}'::jsonb) AS distribucion_grupos,
                    REGEXP_REPLACE(UPPER(TRIM(i.descripcion)), '\\s+', ' ', 'g')
                        AS descripcion_normalizada
                FROM seleccion s
                JOIN tb_bom b ON b.id_bom = s.id_bom
                JOIN tb_bom_items i ON i.id_bom = b.id_bom AND i.activo
                LEFT JOIN tb_bom_item_ejecucion e ON e.id_item = i.id_item
                LEFT JOIN tb_bom_item_grupos ig ON ig.id_item = i.id_item
                LEFT JOIN tb_cat_grupos_bom g ON g.id = ig.id_grupo
                GROUP BY s.id_paquete, s.codigo, s.nombre, b.id_bom, b.version,
                         i.id_item, e.estatus_ejecucion, e.cantidad_recibida
            ), solapamientos AS (
                SELECT
                    descripcion_normalizada,
                    COUNT(DISTINCT id_paquete) AS paquetes,
                    ARRAY_AGG(DISTINCT paquete_codigo ORDER BY paquete_codigo)
                        AS paquetes_origen
                FROM lineas
                WHERE descripcion_normalizada <> ''
                GROUP BY descripcion_normalizada
                HAVING COUNT(DISTINCT id_paquete) > 1
            ), facturas AS (
                SELECT
                    asignacion.id_linea_bom,
                    CASE WHEN COUNT(*) FILTER (
                        WHERE asignacion.moneda = 'USD'
                          AND material.tipo_cambio_xml IS NULL
                    ) > 0 THEN NULL ELSE COALESCE(SUM(
                        CASE WHEN asignacion.moneda = 'USD'
                             THEN asignacion.importe_asignado * material.tipo_cambio_xml
                             ELSE asignacion.importe_asignado END
                    ), 0) END AS facturado
                FROM tb_bom_concepto_asignaciones asignacion
                JOIN tb_materiales_historial material
                  ON material.id = asignacion.id_material
                JOIN tb_bom b
                  ON b.id_bom = asignacion.id_bom AND b.id_proyecto = $1
                GROUP BY asignacion.id_linea_bom
            ), facturas_grupo_filas AS (
                SELECT
                    asignacion.id_linea_bom,
                    COALESCE(grupo.grupo_codigo_snapshot, 'PENDIENTE_ASIGNACION')
                        AS codigo,
                    CASE WHEN grupo.id_asignacion_grupo IS NULL
                         THEN asignacion.importe_asignado
                         ELSE grupo.importe_asignado END AS importe_asignado,
                    asignacion.moneda,
                    material.tipo_cambio_xml
                FROM tb_bom_concepto_asignaciones asignacion
                JOIN tb_materiales_historial material
                  ON material.id = asignacion.id_material
                JOIN tb_bom b
                  ON b.id_bom = asignacion.id_bom AND b.id_proyecto = $1
                LEFT JOIN tb_bom_hecho_grupo_asignaciones grupo
                  ON grupo.id_asignacion_concepto = asignacion.id_asignacion

                UNION ALL

                SELECT
                    asignacion.id_linea_bom,
                    'PENDIENTE_ASIGNACION',
                    asignacion.importe_asignado
                        - COALESCE(SUM(grupo.importe_asignado), 0),
                    asignacion.moneda,
                    material.tipo_cambio_xml
                FROM tb_bom_concepto_asignaciones asignacion
                JOIN tb_materiales_historial material
                  ON material.id = asignacion.id_material
                JOIN tb_bom b
                  ON b.id_bom = asignacion.id_bom AND b.id_proyecto = $1
                JOIN tb_bom_hecho_grupo_asignaciones grupo
                  ON grupo.id_asignacion_concepto = asignacion.id_asignacion
                WHERE asignacion.asignacion_grupo_completa = FALSE
                GROUP BY asignacion.id_asignacion, asignacion.id_linea_bom,
                         asignacion.importe_asignado, asignacion.moneda,
                         material.tipo_cambio_xml
                HAVING ABS(
                    asignacion.importe_asignado
                    - COALESCE(SUM(grupo.importe_asignado), 0)
                ) > 0.000001
            ), facturas_grupo AS (
                SELECT id_linea_bom, codigo,
                    CASE WHEN COUNT(*) FILTER (
                        WHERE moneda = 'USD' AND tipo_cambio_xml IS NULL
                    ) > 0 THEN NULL ELSE SUM(
                        CASE WHEN moneda = 'USD'
                             THEN importe_asignado * tipo_cambio_xml
                             ELSE importe_asignado END
                    ) END AS facturado_mxn
                FROM facturas_grupo_filas
                GROUP BY id_linea_bom, codigo
            ), facturas_grupo_json AS (
                SELECT id_linea_bom,
                       JSONB_OBJECT_AGG(codigo, facturado_mxn) AS importes
                FROM facturas_grupo
                GROUP BY id_linea_bom
            )
            SELECT
                l.*,
                l.cantidad * l.precio_unitario AS costo_estimado,
                CASE WHEN f.id_linea_bom IS NULL THEN 0 ELSE f.facturado END
                    AS costo_facturado,
                COALESCE(fg.importes, '{}'::jsonb) AS facturado_por_grupo,
                COALESCE(s.paquetes, 0) > 1 AS posible_solapamiento,
                COALESCE(s.paquetes_origen, ARRAY[]::VARCHAR[]) AS paquetes_solapados
            FROM lineas l
            LEFT JOIN facturas f ON f.id_linea_bom = l.id_linea_bom
            LEFT JOIN facturas_grupo_json fg ON fg.id_linea_bom = l.id_linea_bom
            LEFT JOIN solapamientos s
                ON s.descripcion_normalizada = l.descripcion_normalizada
            ORDER BY l.paquete_codigo, l.version, l.descripcion, l.id_item
            """,
            id_proyecto, modo,
        )
        return [dict(row) for row in rows]

    async def get_divisor_oficial_consolidado(
        self, conn, id_proyecto: UUID,
    ) -> Optional[dict]:
        """Snapshot FV congelado al ultimo cierre de captura del proyecto."""
        row = await conn.fetchrow(
            """
            SELECT id_proyecto, captura_cerrada, cerrada_en,
                   modulos_fv_snapshot, potencia_pico_kwp_snapshot
            FROM tb_bom_proyecto_estado
            WHERE id_proyecto = $1
              AND modulos_fv_snapshot IS NOT NULL
              AND potencia_pico_kwp_snapshot IS NOT NULL
            """,
            id_proyecto,
        )
        return dict(row) if row else None

    # ─── BOM ITEMS ──────────────────────────────────────────

    async def agregar_item(
        self, conn, id_bom: UUID, descripcion: str, cantidad,
        id_categoria: Optional[int] = None,
        unidad_medida: Optional[str] = None,
        comentarios: Optional[str] = None,
        orden: int = 0,
        precio_unitario=None,
        origen_precio: Optional[str] = 'MANUAL',
        id_material_ref: Optional[UUID] = None,
        id_material_interno: Optional[UUID] = None,
        tipo_partida: Optional[str] = 'MATERIAL',
        moneda: Optional[str] = 'MXN',
        tipo_origen_item: str = 'BASE',
        id_item_reemplazado: Optional[UUID] = None,
        motivo_adenda: Optional[str] = None,
        creado_en_adenda: Optional[UUID] = None,
        id_linea_bom: Optional[UUID] = None,
        creado_por: Optional[UUID] = None,
        precio_pendiente_confirmacion: bool = False,
    ) -> dict:
        """Agrega un item al BOM."""
        id_paquete = await conn.fetchval(
            "SELECT id_paquete FROM tb_bom WHERE id_bom = $1",
            id_bom,
        )
        if id_linea_bom is None:
            id_linea_reemplazada = None
            if id_item_reemplazado:
                id_linea_reemplazada = await conn.fetchval(
                    "SELECT id_linea_bom FROM tb_bom_items WHERE id_item = $1",
                    id_item_reemplazado,
                )
            id_linea_bom = await conn.fetchval(
                """
                INSERT INTO tb_bom_lineas (
                    id_paquete, id_linea_reemplazada, creado_por
                )
                VALUES ($1, $2, $3)
                RETURNING id_linea_bom
                """,
                id_paquete, id_linea_reemplazada, creado_por,
            )
        row = await conn.fetchrow("""
            INSERT INTO tb_bom_items (id_bom, id_paquete, id_linea_bom,
                                      id_categoria, descripcion,
                                      cantidad, unidad_medida, comentarios, orden,
                                      precio_unitario, origen_precio, id_material_ref,
                                      id_material_interno, tipo_partida, moneda,
                                      tipo_origen_item, id_item_reemplazado,
                                      motivo_adenda, creado_en_adenda,
                                      precio_pendiente_confirmacion)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13,
                    $14, $15, $16, $17, $18, $19, $20)
            RETURNING *
        """, id_bom, id_paquete, id_linea_bom, id_categoria, descripcion, cantidad,
            unidad_medida, comentarios, orden,
            precio_unitario, origen_precio, id_material_ref,
            id_material_interno, tipo_partida, moneda,
            tipo_origen_item, id_item_reemplazado, motivo_adenda, creado_en_adenda,
            precio_pendiente_confirmacion)
        return dict(row)

    async def get_item_ids_by_bom(self, conn, id_bom: UUID) -> List[UUID]:
        """Ids de items activos de un BOM en el orden de despliegue, para navegacion prev/next."""
        rows = await conn.fetch("""
            SELECT id_item
            FROM tb_bom_items
            WHERE id_bom = $1 AND activo = TRUE
            ORDER BY orden ASC, created_at ASC
        """, id_bom)
        return [r['id_item'] for r in rows]

    async def get_items_by_bom(self, conn, id_bom: UUID, solo_activos: bool = True) -> List[dict]:
        """Lista items de un BOM con datos de categoria y proveedor."""
        filtro_activo = "AND i.activo = TRUE" if solo_activos else ""
        rows = await conn.fetch(f"""
            SELECT i.*,
                   c.nombre AS categoria_nombre,
                   p.nombre_comercial AS proveedor_base_nombre,
                   er.id_proveedor_real,
                   pr.nombre_comercial AS proveedor_real_nombre,
                   er.precio_real,
                   er.moneda_real,
                   er.cantidad_recibida AS cantidad_recibida_real,
                   er.fecha_estimada_entrega AS fecha_estimada_entrega_real,
                   er.fecha_llegada_real AS fecha_llegada_real_ejecucion,
                   er.tipo_entrega AS tipo_entrega_real,
                   er.estatus_ejecucion,
                   er.comentarios_operativos,
                   COALESCE(er.lock_version, 0) AS ejecucion_lock_version,
                   (i.cantidad * i.precio_unitario) AS importe_base,
                   (i.cantidad * er.precio_real) AS importe_real
            FROM tb_bom_items i
            LEFT JOIN tb_cat_categorias_compra c ON c.id = i.id_categoria
            LEFT JOIN tb_proveedores p ON p.id_proveedor = i.id_proveedor
            LEFT JOIN tb_bom_item_ejecucion er ON er.id_item = i.id_item
            LEFT JOIN tb_proveedores pr ON pr.id_proveedor = er.id_proveedor_real
            WHERE i.id_bom = $1 {filtro_activo}
            ORDER BY i.orden ASC, i.created_at ASC
        """, id_bom)
        return [self._merge_item_ejecucion(r) for r in rows]

    async def get_items_sin_costo_bom(self, conn, id_bom: UUID) -> List[dict]:
        """Lista items activos sin costo util para presupuesto: sin precio (NULL o
        <=0), o con un precio capturado por Ingenieria que Compras aun no confirma
        (precio_pendiente_confirmacion) — ese precio no es oficial todavia."""
        rows = await conn.fetch("""
            SELECT i.id_item,
                   i.descripcion,
                   i.cantidad,
                   i.unidad_medida,
                   i.precio_unitario,
                   i.moneda,
                   i.tipo_partida,
                   i.orden,
                   i.lock_version,
                   i.id_material_interno,
                   i.precio_pendiente_confirmacion,
                   c.nombre AS categoria_nombre,
                   COALESCE(
                       string_agg(DISTINCT g.codigo, ', ' ORDER BY g.codigo),
                       ''
                   ) AS grupos
            FROM tb_bom_items i
            LEFT JOIN tb_cat_categorias_compra c ON c.id = i.id_categoria
            LEFT JOIN tb_bom_item_grupos ig ON ig.id_item = i.id_item
            LEFT JOIN tb_cat_grupos_bom g ON g.id = ig.id_grupo AND g.activo = TRUE
            WHERE i.id_bom = $1
              AND i.activo = TRUE
              AND COALESCE(i.tipo_origen_item, 'BASE') = 'BASE'
              AND (
                  i.precio_unitario IS NULL OR i.precio_unitario <= 0
                  OR i.precio_pendiente_confirmacion = TRUE
              )
            GROUP BY i.id_item, c.nombre
            ORDER BY i.orden, i.created_at
        """, id_bom)
        return [dict(r) for r in rows]

    async def get_items_por_ids_para_bom(
        self, conn, id_bom: UUID, item_ids: List[UUID]
    ) -> List[dict]:
        """Items solicitados que realmente pertenecen a id_bom (protege contra IDOR:
        un id_item de otro BOM simplemente no aparece en el resultado)."""
        rows = await conn.fetch("""
            SELECT id_item, precio_unitario, moneda, lock_version, activo,
                   COALESCE(tipo_origen_item, 'BASE') AS tipo_origen_item,
                   id_material_interno, precio_pendiente_confirmacion,
                   descripcion, id_categoria, unidad_medida
            FROM tb_bom_items
            WHERE id_bom = $1 AND id_item = ANY($2::uuid[])
        """, id_bom, item_ids)
        return [dict(r) for r in rows]

    async def actualizar_precios_items_compras_cas_batch(
        self, conn, entradas: List[tuple],
    ) -> List[UUID]:
        """CAS a nivel de item sobre tb_bom_items.lock_version (columna existente,
        sin otro consumidor hoy) — evita la colision falsa de un CAS a nivel de BOM
        completo entre Compras e Ingenieria/Construccion editando items distintos.
        Un solo UPDATE con arrays desanidados en vez de N round-trips secuenciales.
        `entradas` es una lista de tuplas
        (id_item, precio_unitario, moneda, lock_version_esperado, id_material_interno).
        El ultimo elemento es opcional (None si no aplica) — cuando viene, gatea el
        vinculo/creacion de material interno (doc 42, BOM 6.1) por el MISMO CAS que
        el precio, en una sola pasada (evita la ventana de material creado pero no
        enlazado). COALESCE preserva el vinculo existente cuando no se pasa uno
        nuevo. Devuelve los id_item cuyo CAS tuvo exito. Tambien limpia
        precio_pendiente_confirmacion: esta funcion es el punto unico donde
        Compras confirma (tal cual) o edita un precio — cualquiera de las dos
        acciones deja el valor como costo oficial (Fase 4)."""
        if not entradas:
            return []
        ids = [e[0] for e in entradas]
        precios = [e[1] for e in entradas]
        monedas = [e[2] for e in entradas]
        locks = [e[3] for e in entradas]
        materiales = [e[4] for e in entradas]
        rows = await conn.fetch("""
            UPDATE tb_bom_items i
            SET precio_unitario = v.precio_unitario,
                moneda = v.moneda,
                origen_precio = 'MANUAL',
                precio_pendiente_confirmacion = FALSE,
                id_material_interno = COALESCE(v.id_material_interno, i.id_material_interno),
                lock_version = i.lock_version + 1,
                updated_at = now()
            FROM (
                SELECT unnest($1::uuid[]) AS id_item,
                       unnest($2::numeric[]) AS precio_unitario,
                       unnest($3::text[]) AS moneda,
                       unnest($4::int[]) AS lock_version_esperado,
                       unnest($5::uuid[]) AS id_material_interno
            ) v
            WHERE i.id_item = v.id_item AND i.lock_version = v.lock_version_esperado
            RETURNING i.id_item
        """, ids, precios, monedas, locks, materiales)
        return [r["id_item"] for r in rows]

    async def actualizar_precio_catalogo_interno(
        self, conn, id_material_interno: UUID, precio_referencia, moneda: str,
        user_id: UUID,
    ) -> bool:
        """Doble escritura opt-in (checkbox del modal): actualiza el precio de
        referencia global del catalogo interno, no solo el item del BOM."""
        row = await conn.fetchrow("""
            UPDATE tb_cat_materiales
            SET precio_referencia = $1,
                moneda = $2,
                actualizado_por = $3,
                updated_at = now()
            WHERE id = $4 AND activo = TRUE
            RETURNING id
        """, precio_referencia, moneda, user_id, id_material_interno)
        return row is not None

    async def actualizar_precios_catalogo_interno_batch(
        self, conn, entradas: List[tuple],
    ) -> None:
        """Version en lote de `actualizar_precio_catalogo_interno` via executemany
        (un solo pipeline de statements preparados en vez de N round-trips).
        `entradas` es una lista de tuplas
        (precio_referencia, moneda, user_id, id_material_interno)."""
        if not entradas:
            return
        await conn.executemany("""
            UPDATE tb_cat_materiales
            SET precio_referencia = $1,
                moneda = $2,
                actualizado_por = $3,
                updated_at = now()
            WHERE id = $4 AND activo = TRUE
        """, entradas)

    async def sincronizar_costos_catalogo(self, conn, id_bom: UUID) -> List[dict]:
        """Sincroniza precio_unitario de items BASE sin costo desde el catalogo interno.

        Precio resuelto por material: precio de la factura XML vinculada mas reciente
        (tb_materiales_interno_xml + tb_materiales_historial) si existe, si no
        precio_referencia del catalogo (tb_cat_materiales). Solo toca items con
        id_material_interno asignado."""
        rows = await conn.fetch(f"""
            WITH resueltos AS (
                SELECT c.id AS id_material_interno,
                       COALESCE(xml.precio_unitario, c.precio_referencia) AS precio_resuelto,
                       COALESCE(xml.moneda_xml, c.moneda, 'MXN') AS moneda_resuelta
                FROM tb_cat_materiales c
                LEFT JOIN LATERAL (
                    SELECT m.precio_unitario, {_MONEDA_XML_SQL} AS moneda_xml
                    FROM tb_materiales_interno_xml v
                    JOIN tb_materiales_historial m ON m.id = v.id_material_xml
                    WHERE v.id_material_interno = c.id
                    ORDER BY m.fecha_factura DESC NULLS LAST
                    LIMIT 1
                ) xml ON TRUE
                WHERE c.activo = TRUE
            ),
            candidatos AS (
                SELECT i.id_item, i.descripcion, i.precio_unitario AS precio_anterior,
                       i.origen_precio AS origen_precio_anterior,
                       r.precio_resuelto, r.moneda_resuelta
                FROM tb_bom_items i
                JOIN resueltos r ON r.id_material_interno = i.id_material_interno
                WHERE i.id_bom = $1
                  AND i.activo = TRUE
                  AND COALESCE(i.tipo_origen_item, 'BASE') = 'BASE'
                  AND (i.precio_unitario IS NULL OR i.precio_unitario <= 0)
                  AND r.precio_resuelto IS NOT NULL
                  AND r.precio_resuelto > 0
            )
            UPDATE tb_bom_items i
            SET precio_unitario = c.precio_resuelto,
                moneda = c.moneda_resuelta,
                origen_precio = 'CATALOGO',
                updated_at = now()
            FROM candidatos c
            WHERE i.id_item = c.id_item
            RETURNING i.id_item, c.descripcion, c.precio_anterior, c.origen_precio_anterior, c.precio_resuelto
        """, id_bom)
        return [dict(r) for r in rows]

    async def get_item_by_id(self, conn, id_item: UUID) -> Optional[dict]:
        """Obtiene un item por ID con datos de BOM."""
        row = await conn.fetchrow("""
            SELECT i.*,
                   c.nombre AS categoria_nombre,
                   p.nombre_comercial AS proveedor_base_nombre,
                   er.id_proveedor_real,
                   pr.nombre_comercial AS proveedor_real_nombre,
                   er.precio_real,
                   er.moneda_real,
                   er.cantidad_recibida AS cantidad_recibida_real,
                   er.fecha_estimada_entrega AS fecha_estimada_entrega_real,
                   er.fecha_llegada_real AS fecha_llegada_real_ejecucion,
                   er.tipo_entrega AS tipo_entrega_real,
                   er.estatus_ejecucion,
                   er.comentarios_operativos,
                   COALESCE(er.lock_version, 0) AS ejecucion_lock_version,
                   b.estatus AS bom_estatus,
                   b.id_proyecto,
                   b.id_paquete,
                   b.version AS bom_version,
                   (i.cantidad * i.precio_unitario) AS importe_base,
                   (i.cantidad * er.precio_real) AS importe_real
            FROM tb_bom_items i
            LEFT JOIN tb_cat_categorias_compra c ON c.id = i.id_categoria
            LEFT JOIN tb_proveedores p ON p.id_proveedor = i.id_proveedor
            LEFT JOIN tb_bom_item_ejecucion er ON er.id_item = i.id_item
            LEFT JOIN tb_proveedores pr ON pr.id_proveedor = er.id_proveedor_real
            JOIN tb_bom b ON b.id_bom = i.id_bom
            WHERE i.id_item = $1
        """, id_item)
        return self._merge_item_ejecucion(row) if row else None

    async def get_items_by_ids(self, conn, item_ids: List[UUID]) -> List[dict]:
        """Obtiene varios items por lista de IDs. Solo items activos."""
        rows = await conn.fetch("""
            SELECT i.id_item, i.id_bom, i.id_paquete,
                   i.descripcion, i.cantidad, i.moneda,
                   i.estatus_compra, i.activo, i.precio_unitario, i.origen_precio,
                   COALESCE(i.tipo_origen_item, 'BASE') AS tipo_origen_item,
                   i.id_item_reemplazado, i.creado_en_adenda,
                   a.estatus AS adenda_estatus,
                   er.estatus_ejecucion
            FROM tb_bom_items i
            LEFT JOIN tb_bom_item_ejecucion er ON er.id_item = i.id_item
            LEFT JOIN tb_bom_adendas a ON a.id_adenda = i.creado_en_adenda
            WHERE i.id_item = ANY($1::uuid[]) AND i.activo = TRUE
        """, item_ids)
        return [dict(r) for r in rows]

    async def get_items_context_by_ids(self, conn, item_ids: List[UUID]) -> List[dict]:
        """Obtiene items con contexto del BOM para validaciones de lote."""
        rows = await conn.fetch("""
            SELECT i.*,
                   er.estatus_ejecucion,
                   b.estatus AS bom_estatus,
                   b.id_proyecto,
                   b.version AS bom_version
            FROM tb_bom_items i
            LEFT JOIN tb_bom_item_ejecucion er ON er.id_item = i.id_item
            JOIN tb_bom b ON b.id_bom = i.id_bom
            WHERE i.id_item = ANY($1::uuid[])
        """, item_ids)
        return [dict(r) for r in rows]

    async def lock_items_context_by_ids(
        self, conn, item_ids: List[UUID],
    ) -> List[dict]:
        """Bloquea items en orden estable y devuelve su contexto de BOM."""
        rows = await conn.fetch("""
            SELECT i.*,
                   er.estatus_ejecucion,
                   er.lock_version AS ejecucion_lock_version,
                   b.estatus AS bom_estatus,
                   b.id_proyecto,
                   b.version AS bom_version
            FROM tb_bom_items i
            LEFT JOIN tb_bom_item_ejecucion er ON er.id_item = i.id_item
            JOIN tb_bom b ON b.id_bom = i.id_bom
            WHERE i.id_item = ANY($1::uuid[])
            ORDER BY i.id_item
            FOR UPDATE OF i
        """, item_ids)
        return [dict(row) for row in rows]

    async def update_item(
        self, conn, id_item: UUID,
        lock_version_esperado: Optional[int] = None,
        **campos,
    ) -> dict:
        """Actualiza campos de un item. Solo actualiza los campos proporcionados.

        `lock_version_esperado`: si se pasa, agrega el CAS a nivel de item
        (WHERE lock_version = ...) — usarlo cuando el campo editado (ej.
        precio_unitario desde Ingenieria) puede chocar con
        actualizar_precios_items_compras_cas_batch, que escribe la misma fila
        via el mismo lock_version. Sin este parametro (caso general de otros
        campos) el UPDATE no valida version, solo la incrementa."""
        if 'id_material_interno' in campos:
            raise ValueError(
                "update_item no soporta id_material_interno (queda fuera de "
                "`allowed` a proposito) -- usa "
                "actualizar_precios_items_compras_cas_batch (doc 42, BOM 6.1), "
                "que lo enlaza gateado por el mismo CAS de precio. Pasarlo aqui "
                "antes solo se descartaba en silencio sin error."
            )
        sets = ["updated_at = NOW()", "lock_version = lock_version + 1"]
        params = [id_item]
        idx = 2

        allowed = {
            'id_categoria', 'descripcion', 'cantidad', 'unidad_medida',
            'fecha_requerida', 'fecha_llegada_real', 'id_proveedor',
            'tipo_entrega', 'fecha_estimada_entrega', 'comentarios',
            'entregado', 'fecha_entrega_check', 'orden',
            'precio_unitario', 'origen_precio', 'id_material_ref',
            'cantidad_recibida', 'tipo_partida', 'moneda',
            'precio_pendiente_confirmacion',
        }

        for key, val in campos.items():
            if key in allowed:
                sets.append(f"{key} = ${idx}")
                params.append(val)
                idx += 1

        where_lock = ""
        if lock_version_esperado is not None:
            where_lock = f" AND lock_version = ${idx}"
            params.append(lock_version_esperado)
            idx += 1

        query = f"""
            UPDATE tb_bom_items SET {', '.join(sets)}
            WHERE id_item = $1{where_lock}
            RETURNING *
        """
        row = await conn.fetchrow(query, *params)
        return dict(row) if row else None

    async def upsert_item_ejecucion(
        self, conn, id_item: UUID, updated_by: Optional[UUID] = None,
        lock_version_esperado: Optional[int] = None, **campos,
    ) -> Optional[dict]:
        """Inserta o actualiza los datos reales de ejecucion/compra de un item."""
        allowed = {
            "id_proveedor_real",
            "precio_real",
            "moneda_real",
            "cantidad_recibida",
            "fecha_estimada_entrega",
            "fecha_llegada_real",
            "tipo_entrega",
            "estatus_ejecucion",
            "comentarios_operativos",
        }
        data = {key: val for key, val in campos.items() if key in allowed}
        if not data:
            return await self.get_item_by_id(conn, id_item)

        if lock_version_esperado is None:
            raise ValueError("Falta la versión esperada de ejecución del ítem")

        data_json = json.dumps(data, default=str)
        row = await conn.fetchrow(
            """
            INSERT INTO tb_bom_item_ejecucion (
                id_item, id_proveedor_real, precio_real, moneda_real,
                cantidad_recibida, fecha_estimada_entrega, fecha_llegada_real,
                tipo_entrega, estatus_ejecucion, comentarios_operativos,
                updated_by, lock_version
            )
            SELECT
                $1,
                (datos->>'id_proveedor_real')::uuid,
                (datos->>'precio_real')::numeric,
                datos->>'moneda_real',
                COALESCE((datos->>'cantidad_recibida')::numeric, 0),
                (datos->>'fecha_estimada_entrega')::date,
                (datos->>'fecha_llegada_real')::date,
                datos->>'tipo_entrega',
                COALESCE(datos->>'estatus_ejecucion', 'PENDIENTE'),
                datos->>'comentarios_operativos',
                $3,
                1
            FROM (SELECT $2::jsonb AS datos) entrada
            WHERE $4 = 0 OR EXISTS (
                SELECT 1 FROM tb_bom_item_ejecucion existente
                WHERE existente.id_item = $1
            )
            ON CONFLICT (id_item) DO UPDATE
            SET id_proveedor_real = CASE WHEN $2::jsonb ? 'id_proveedor_real'
                    THEN EXCLUDED.id_proveedor_real
                    ELSE tb_bom_item_ejecucion.id_proveedor_real END,
                precio_real = CASE WHEN $2::jsonb ? 'precio_real'
                    THEN EXCLUDED.precio_real
                    ELSE tb_bom_item_ejecucion.precio_real END,
                moneda_real = CASE WHEN $2::jsonb ? 'moneda_real'
                    THEN EXCLUDED.moneda_real
                    ELSE tb_bom_item_ejecucion.moneda_real END,
                cantidad_recibida = CASE WHEN $2::jsonb ? 'cantidad_recibida'
                    THEN EXCLUDED.cantidad_recibida
                    ELSE tb_bom_item_ejecucion.cantidad_recibida END,
                fecha_estimada_entrega = CASE
                    WHEN $2::jsonb ? 'fecha_estimada_entrega'
                    THEN EXCLUDED.fecha_estimada_entrega
                    ELSE tb_bom_item_ejecucion.fecha_estimada_entrega END,
                fecha_llegada_real = CASE WHEN $2::jsonb ? 'fecha_llegada_real'
                    THEN EXCLUDED.fecha_llegada_real
                    ELSE tb_bom_item_ejecucion.fecha_llegada_real END,
                tipo_entrega = CASE WHEN $2::jsonb ? 'tipo_entrega'
                    THEN EXCLUDED.tipo_entrega
                    ELSE tb_bom_item_ejecucion.tipo_entrega END,
                estatus_ejecucion = CASE WHEN $2::jsonb ? 'estatus_ejecucion'
                    THEN EXCLUDED.estatus_ejecucion
                    ELSE tb_bom_item_ejecucion.estatus_ejecucion END,
                comentarios_operativos = CASE
                    WHEN $2::jsonb ? 'comentarios_operativos'
                    THEN EXCLUDED.comentarios_operativos
                    ELSE tb_bom_item_ejecucion.comentarios_operativos END,
                updated_by = EXCLUDED.updated_by,
                lock_version = tb_bom_item_ejecucion.lock_version + 1,
                updated_at = NOW()
            WHERE tb_bom_item_ejecucion.lock_version = $4
            RETURNING *
            """,
            id_item, data_json, updated_by, lock_version_esperado,
        )
        return dict(row) if row else None

    async def soft_delete_item(self, conn, id_item: UUID) -> dict:
        """Marca un item como inactivo (soft delete)."""
        row = await conn.fetchrow("""
            UPDATE tb_bom_items SET activo = FALSE, updated_at = NOW()
            WHERE id_item = $1
            RETURNING *
        """, id_item)
        return dict(row) if row else None

    async def restaurar_item(self, conn, id_item: UUID) -> dict:
        """Restaura un item eliminado."""
        row = await conn.fetchrow("""
            UPDATE tb_bom_items SET activo = TRUE, updated_at = NOW()
            WHERE id_item = $1
            RETURNING *
        """, id_item)
        return dict(row) if row else None

    async def get_next_orden(self, conn, id_bom: UUID) -> int:
        """Obtiene el siguiente numero de orden para items."""
        val = await conn.fetchval("""
            SELECT COALESCE(MAX(orden), 0) + 1
            FROM tb_bom_items WHERE id_bom = $1 AND activo = TRUE
        """, id_bom)
        return val

    async def copiar_items_a_nueva_version(
        self, conn, id_bom_origen: UUID, id_bom_destino: UUID
    ) -> int:
        """Copia items activos de un BOM a otro con trazabilidad de origen.
        Items FACTURADOS/PAGADOS se copian como bloqueados.
        Retorna cantidad copiada."""
        result = await conn.execute("""
            INSERT INTO tb_bom_items (id_bom, id_paquete, id_linea_bom,
                                      id_categoria, descripcion,
                                      cantidad, unidad_medida, fecha_requerida,
                                      id_proveedor, tipo_entrega,
                                      fecha_estimada_entrega, comentarios, orden,
                                      precio_unitario, origen_precio, id_material_ref,
                                      id_material_interno, tipo_partida, moneda,
                                      estatus_compra, id_item_origen, bloqueado,
                                      tipo_origen_item, id_item_reemplazado,
                                      motivo_adenda, creado_en_adenda)
            SELECT $2, destino.id_paquete, origen.id_linea_bom,
                   origen.id_categoria, origen.descripcion,
                   origen.cantidad, origen.unidad_medida, origen.fecha_requerida,
                   origen.id_proveedor, origen.tipo_entrega,
                   origen.fecha_estimada_entrega, origen.comentarios, origen.orden,
                   origen.precio_unitario, origen.origen_precio, origen.id_material_ref,
                   origen.id_material_interno, origen.tipo_partida, origen.moneda,
                   'SIN_COTIZAR', origen.id_item,
                   (COALESCE(e.estatus_ejecucion, origen.estatus_compra)
                       IN ('PAGADO', 'FACTURADO')),
                   COALESCE(origen.tipo_origen_item, 'BASE'),
                   origen.id_item_reemplazado,
                   origen.motivo_adenda, origen.creado_en_adenda
            FROM tb_bom_items origen
            JOIN tb_bom destino ON destino.id_bom = $2
            LEFT JOIN tb_bom_item_ejecucion e ON e.id_item = origen.id_item
            WHERE origen.id_bom = $1
              AND origen.activo = TRUE
              AND COALESCE(e.estatus_ejecucion, origen.estatus_compra, '')
                  NOT IN ('NO_ADQUIRIDO', 'REEMPLAZADO')
            ORDER BY origen.orden ASC
        """, id_bom_origen, id_bom_destino)
        await conn.execute(
            """
            INSERT INTO tb_bom_item_grupos (id_item, id_grupo)
            SELECT destino.id_item, grupos.id_grupo
            FROM tb_bom_items destino
            JOIN tb_bom_items origen ON origen.id_item = destino.id_item_origen
            JOIN LATERAL (
                SELECT id_grupo
                FROM tb_bom_item_grupos_operativos
                WHERE id_item = origen.id_item
                UNION
                SELECT id_grupo
                FROM tb_bom_item_grupos
                WHERE id_item = origen.id_item
                  AND NOT EXISTS (
                      SELECT 1
                      FROM tb_bom_item_grupos_operativos
                      WHERE id_item = origen.id_item
                  )
            ) grupos ON TRUE
            WHERE destino.id_bom = $1
            ON CONFLICT (id_item, id_grupo) DO NOTHING
            """,
            id_bom_destino,
        )
        await conn.execute(
            """
            INSERT INTO tb_bom_item_grupo_asignaciones (
                id_bom_item, id_grupo, grupo_codigo_snapshot,
                grupo_nombre_snapshot, porcentaje
            )
            SELECT destino.id_item, asignacion.id_grupo,
                   asignacion.grupo_codigo_snapshot,
                   asignacion.grupo_nombre_snapshot,
                   asignacion.porcentaje
            FROM tb_bom_items destino
            JOIN tb_bom_items origen ON origen.id_item = destino.id_item_origen
            JOIN tb_bom_item_grupo_asignaciones asignacion
              ON asignacion.id_bom_item = origen.id_item
            WHERE destino.id_bom = $1
            ON CONFLICT (id_bom_item, id_grupo) DO UPDATE
            SET grupo_codigo_snapshot = EXCLUDED.grupo_codigo_snapshot,
                grupo_nombre_snapshot = EXCLUDED.grupo_nombre_snapshot,
                porcentaje = EXCLUDED.porcentaje
            """,
            id_bom_destino,
        )
        count = int(result.split()[-1]) if result else 0
        return count

    async def crear_adenda(
        self, conn, id_bom_base: UUID, tipo_adenda: str,
        motivo: str, creado_por: UUID,
        estatus: str = "PENDIENTE_CONSTRUCCION",
    ) -> dict:
        """Crea el encabezado de una adenda operativa del BOM."""
        row = await conn.fetchrow("""
            INSERT INTO tb_bom_adendas (
                id_bom_base, tipo_adenda, motivo, estatus,
                creado_por, enviado_construccion_por, fecha_envio_construccion
            )
            VALUES ($1, $2, $3, $4, $5, $5, NOW())
            RETURNING *
        """, id_bom_base, tipo_adenda, motivo, estatus, creado_por)
        return dict(row)

    async def registrar_adenda_item(
        self, conn, id_adenda: UUID, id_bom: UUID, tipo_linea: str, motivo: str,
        id_item_origen: Optional[UUID] = None,
        id_item_bom: Optional[UUID] = None,
        datos_item: Optional[dict] = None,
        grupo_ids: Optional[List[int]] = None,
    ) -> dict:
        """Registra la relacion entre adenda, item origen e item generado."""
        row = await conn.fetchrow("""
            INSERT INTO tb_bom_adenda_items
                (id_adenda, id_bom, id_item_origen, id_item_bom, tipo_linea, motivo,
                 datos_item, grupo_ids)
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::integer[])
            RETURNING *
        """, id_adenda, id_bom, id_item_origen, id_item_bom, tipo_linea, motivo,
             json.dumps(datos_item or {}), grupo_ids or [])
        return dict(row)

    async def get_adenda_by_id(self, conn, id_adenda: UUID) -> Optional[dict]:
        """Obtiene una adenda con contexto de BOM para validaciones."""
        row = await conn.fetchrow("""
            SELECT a.*,
                   b.id_bom AS id_bom,
                   b.id_proyecto,
                   b.version AS bom_version,
                   b.estatus AS bom_estatus,
                   b.elaborado_por,
                   b.responsable_ing,
                   b.coordinador_obra,
                   b.jefe_construccion
            FROM tb_bom_adendas a
            JOIN tb_bom b ON b.id_bom = a.id_bom_base
            WHERE a.id_adenda = $1
        """, id_adenda)
        return dict(row) if row else None

    async def get_adenda_for_update(self, conn, id_adenda: UUID) -> Optional[dict]:
        """Bloquea una adenda exacta antes de resolver su workflow."""
        row = await conn.fetchrow(
            "SELECT * FROM tb_bom_adendas WHERE id_adenda = $1 FOR UPDATE",
            id_adenda,
        )
        return dict(row) if row else None

    async def get_adenda_items(self, conn, id_adenda: UUID) -> List[dict]:
        """Lista lineas propuestas o aplicadas de una adenda."""
        rows = await conn.fetch("""
            SELECT ai.*,
                   origen.descripcion AS origen_descripcion,
                   origen.cantidad AS origen_cantidad,
                   origen.precio_unitario AS origen_precio_unitario,
                   origen.moneda AS origen_moneda,
                   item.descripcion AS item_bom_descripcion
            FROM tb_bom_adenda_items ai
            LEFT JOIN tb_bom_items origen ON origen.id_item = ai.id_item_origen
            LEFT JOIN tb_bom_items item ON item.id_item = ai.id_item_bom
            WHERE ai.id_adenda = $1
            ORDER BY ai.created_at, ai.id_adenda_item
        """, id_adenda)
        return [dict(r) for r in rows]

    async def marcar_adenda_construccion(
        self, conn, id_adenda: UUID, user_id: UUID, requiere_ingenieria: bool,
        lock_version_esperado: int, tipo_cambio_aprobacion=None,
        fecha_tipo_cambio_aprobacion=None, impacto_base_mxn_snapshot=None,
        impacto_base_usd_snapshot=None, impacto_aprobado_mxn=None,
    ) -> Optional[dict]:
        """Registra aprobacion de Construccion y deja la adenda en el siguiente paso."""
        siguiente = "PENDIENTE_INGENIERIA" if requiere_ingenieria else "APROBADA"
        row = await conn.fetchrow("""
            UPDATE tb_bom_adendas
            SET estatus = $3,
                requiere_aprobacion_ingenieria = $4,
                aprobado_construccion_por = $2,
                fecha_aprobacion_construccion = NOW(),
                tipo_cambio_aprobacion = CASE WHEN $4 THEN NULL ELSE $6 END,
                fecha_tipo_cambio_aprobacion = CASE WHEN $4 THEN NULL ELSE $7 END,
                impacto_base_mxn_snapshot = CASE WHEN $4 THEN NULL ELSE $8 END,
                impacto_base_usd_snapshot = CASE WHEN $4 THEN NULL ELSE $9 END,
                impacto_aprobado_mxn = CASE WHEN $4 THEN NULL ELSE $10 END,
                lock_version = lock_version + 1,
                updated_at = NOW()
            WHERE id_adenda = $1
              AND estatus = 'PENDIENTE_CONSTRUCCION'
              AND lock_version = $5
            RETURNING *
        """, id_adenda, user_id, siguiente, requiere_ingenieria,
             lock_version_esperado, tipo_cambio_aprobacion,
             fecha_tipo_cambio_aprobacion, impacto_base_mxn_snapshot,
             impacto_base_usd_snapshot, impacto_aprobado_mxn)
        return dict(row) if row else None

    async def aprobar_adenda_ingenieria(
        self, conn, id_adenda: UUID, user_id: UUID, lock_version_esperado: int,
        tipo_cambio_aprobacion, fecha_tipo_cambio_aprobacion,
        impacto_base_mxn_snapshot, impacto_base_usd_snapshot,
        impacto_aprobado_mxn,
    ) -> Optional[dict]:
        """Registra aprobacion tecnica de Ingenieria y marca la adenda aprobada."""
        row = await conn.fetchrow("""
            UPDATE tb_bom_adendas
            SET estatus = 'APROBADA',
                aprobado_ingenieria_por = $2,
                fecha_aprobacion_ingenieria = NOW(),
                tipo_cambio_aprobacion = $4,
                fecha_tipo_cambio_aprobacion = $5,
                impacto_base_mxn_snapshot = $6,
                impacto_base_usd_snapshot = $7,
                impacto_aprobado_mxn = $8,
                lock_version = lock_version + 1,
                updated_at = NOW()
            WHERE id_adenda = $1
              AND estatus = 'PENDIENTE_INGENIERIA'
              AND lock_version = $3
            RETURNING *
        """, id_adenda, user_id, lock_version_esperado,
             tipo_cambio_aprobacion, fecha_tipo_cambio_aprobacion,
             impacto_base_mxn_snapshot, impacto_base_usd_snapshot,
             impacto_aprobado_mxn)
        return dict(row) if row else None

    async def rechazar_adenda(
        self, conn, id_adenda: UUID, user_id: UUID, motivo_rechazo: str,
        estatus_esperado: str, lock_version_esperado: int,
    ) -> Optional[dict]:
        """Rechaza una adenda pendiente sin aplicar cambios al BOM."""
        row = await conn.fetchrow("""
            UPDATE tb_bom_adendas
            SET estatus = 'RECHAZADA',
                rechazado_por = $2,
                fecha_rechazo = NOW(),
                motivo_rechazo = $3,
                lock_version = lock_version + 1,
                updated_at = NOW()
            WHERE id_adenda = $1
              AND estatus = $4
              AND lock_version = $5
            RETURNING *
        """, id_adenda, user_id, motivo_rechazo,
             estatus_esperado, lock_version_esperado)
        return dict(row) if row else None

    async def cancelar_adenda(
        self, conn, id_adenda: UUID, user_id: UUID, lock_version_esperado: int,
    ) -> Optional[dict]:
        """Cancela una adenda pendiente de construccion sin mutar items."""
        row = await conn.fetchrow("""
            UPDATE tb_bom_adendas
            SET estatus = 'CANCELADA',
                cancelado_por = $2,
                fecha_cancelacion = NOW(),
                lock_version = lock_version + 1,
                updated_at = NOW()
            WHERE id_adenda = $1
              AND estatus = 'PENDIENTE_CONSTRUCCION'
              AND lock_version = $3
            RETURNING *
        """, id_adenda, user_id, lock_version_esperado)
        return dict(row) if row else None

    async def vincular_adenda_item_bom(
        self, conn, id_adenda_item: UUID, id_item_bom: UUID
    ) -> dict:
        """Vincula una linea de adenda con el item creado al aprobar."""
        row = await conn.fetchrow("""
            UPDATE tb_bom_adenda_items
            SET id_item_bom = $2,
                updated_at = NOW()
            WHERE id_adenda_item = $1
            RETURNING *
        """, id_adenda_item, id_item_bom)
        return dict(row) if row else None

    async def registrar_adenda_comentario(
        self, conn, id_adenda: UUID, comentario: str, creado_por: UUID
    ) -> dict:
        """Agrega un comentario a una adenda."""
        row = await conn.fetchrow("""
            INSERT INTO tb_bom_adenda_comentarios (id_adenda, comentario, creado_por)
            VALUES ($1, $2, $3)
            RETURNING *
        """, id_adenda, comentario, creado_por)
        return dict(row)

    async def get_adenda_comentarios(self, conn, id_adenda: UUID) -> List[dict]:
        """Lista comentarios de una adenda."""
        rows = await conn.fetch("""
            SELECT c.*,
                   u.nombre AS creado_por_nombre
            FROM tb_bom_adenda_comentarios c
            LEFT JOIN tb_usuarios u ON u.id_usuario = c.creado_por
            WHERE c.id_adenda = $1
            ORDER BY c.created_at ASC
        """, id_adenda)
        return [dict(r) for r in rows]

    async def get_adenda_comentarios_by_bom(self, conn, id_bom: UUID) -> dict:
        """Lista comentarios de todas las adendas de un BOM agrupados por adenda."""
        rows = await conn.fetch("""
            SELECT c.*,
                   u.nombre AS creado_por_nombre
            FROM tb_bom_adenda_comentarios c
            JOIN tb_bom_adendas a ON a.id_adenda = c.id_adenda
            LEFT JOIN tb_usuarios u ON u.id_usuario = c.creado_por
            WHERE a.id_bom_base = $1
            ORDER BY c.created_at ASC
        """, id_bom)
        result: dict = {}
        for row in rows:
            data = dict(row)
            result.setdefault(str(data["id_adenda"]), []).append(data)
        return result

    async def get_item_compra_bloqueante(self, conn, id_item: UUID) -> dict:
        """Indica si un item ya tiene cotizacion seleccionada o autorizacion activa."""
        row = await conn.fetchrow("""
            SELECT
                EXISTS (
                    SELECT 1
                    FROM tb_bom_cotizacion_items ci
                    JOIN tb_bom_cotizaciones c ON c.id = ci.cotizacion_id
                    WHERE ci.bom_item_id = $1
                      AND c.estatus = 'SELECCIONADA'
                ) AS tiene_cotizacion_seleccionada,
                EXISTS (
                    SELECT 1
                    FROM tb_bom_cotizacion_items ci
                    JOIN tb_bom_autorizaciones a ON a.cotizacion_id = ci.cotizacion_id
                    WHERE ci.bom_item_id = $1
                      AND a.estatus IN (
                          'PENDIENTE',
                          'AUTORIZADO_OBRA',
                          'AUTORIZADO_DIRECCION',
                          'AUTORIZADO_FINANZAS'
                      )
                ) AS tiene_autorizacion_activa
        """, id_item)
        return dict(row) if row else {
            "tiene_cotizacion_seleccionada": False,
            "tiene_autorizacion_activa": False,
        }

    async def get_adendas_by_bom(self, conn, id_bom: UUID) -> List[dict]:
        """Lista adendas del BOM con resumen de lineas afectadas."""
        rows = await conn.fetch("""
            SELECT a.*,
                   u.nombre AS creado_por_nombre,
                   uc.nombre AS aprobado_construccion_por_nombre,
                   ui.nombre AS aprobado_ingenieria_por_nombre,
                   ur.nombre AS rechazado_por_nombre,
                   COUNT(ai.id_adenda_item) AS total_lineas,
                   COALESCE(
                       string_agg(
                           DISTINCT COALESCE(
                               item.descripcion,
                               origen.descripcion,
                               ai.datos_item->>'descripcion'
                           ),
                           ', '
                       ) FILTER (
                           WHERE COALESCE(
                               item.descripcion,
                               origen.descripcion,
                               ai.datos_item->>'descripcion'
                           ) IS NOT NULL
                       ),
                       ''
                   ) AS items_resumen
            FROM tb_bom_adendas a
            LEFT JOIN tb_usuarios u ON u.id_usuario = a.creado_por
            LEFT JOIN tb_usuarios uc ON uc.id_usuario = a.aprobado_construccion_por
            LEFT JOIN tb_usuarios ui ON ui.id_usuario = a.aprobado_ingenieria_por
            LEFT JOIN tb_usuarios ur ON ur.id_usuario = a.rechazado_por
            LEFT JOIN tb_bom_adenda_items ai ON ai.id_adenda = a.id_adenda
            LEFT JOIN tb_bom_items origen ON origen.id_item = ai.id_item_origen
            LEFT JOIN tb_bom_items item ON item.id_item = ai.id_item_bom
            WHERE a.id_bom_base = $1
            GROUP BY a.id_adenda, u.nombre, uc.nombre, ui.nombre, ur.nombre
            ORDER BY a.created_at DESC
        """, id_bom)
        return [dict(r) for r in rows]

    # ─── HISTORIAL ──────────────────────────────────────────

    async def registrar_historial(
        self, conn, id_bom: UUID, accion: str, version_bom: int,
        realizado_por: UUID, id_item: Optional[UUID] = None,
        campo_modificado: Optional[str] = None,
        valor_anterior: Optional[str] = None,
        valor_nuevo: Optional[str] = None
    ) -> dict:
        """Registra un cambio en el historial de auditoria."""
        row = await conn.fetchrow("""
            INSERT INTO tb_bom_historial (
                id_bom, id_paquete, id_linea_bom, id_item, accion,
                campo_modificado, valor_anterior, valor_nuevo, version_bom,
                realizado_por
            )
            SELECT $1, bom.id_paquete, item.id_linea_bom, $2, $3, $4, $5, $6, $7, $8
            FROM tb_bom bom
            LEFT JOIN tb_bom_items item ON item.id_item = $2 AND item.id_bom = bom.id_bom
            WHERE bom.id_bom = $1
            RETURNING *
        """, id_bom, id_item, accion, campo_modificado,
            valor_anterior, valor_nuevo, version_bom, realizado_por)
        return dict(row)

    async def registrar_historial_batch(self, conn, entradas: List[tuple]) -> None:
        """Version en lote de `registrar_historial` via executemany. `entradas` es
        una lista de tuplas
        (id_bom, id_item, accion, campo_modificado, valor_anterior, valor_nuevo,
        version_bom, realizado_por)."""
        if not entradas:
            return
        await conn.executemany("""
            INSERT INTO tb_bom_historial (
                id_bom, id_paquete, id_linea_bom, id_item, accion,
                campo_modificado, valor_anterior, valor_nuevo, version_bom,
                realizado_por
            )
            SELECT $1, bom.id_paquete, item.id_linea_bom, $2, $3, $4, $5, $6, $7, $8
            FROM tb_bom bom
            LEFT JOIN tb_bom_items item ON item.id_item = $2 AND item.id_bom = bom.id_bom
            WHERE bom.id_bom = $1
        """, entradas)

    async def get_historial_by_bom(
        self, conn, id_bom: UUID,
        usuario_id: Optional[UUID] = None,
        q: Optional[str] = None,
    ) -> List[dict]:
        """Lista historial de cambios de un BOM, con filtro opcional por usuario y texto."""
        condiciones = ["h.id_bom = $1"]
        params: List = [id_bom]
        if usuario_id:
            params.append(usuario_id)
            condiciones.append(f"h.realizado_por = ${len(params)}")
        if q:
            params.append(f"%{q}%")
            condiciones.append(
                f"(h.campo_modificado ILIKE ${len(params)} OR h.valor_anterior ILIKE ${len(params)} "
                f"OR h.valor_nuevo ILIKE ${len(params)})"
            )
        rows = await conn.fetch(f"""
            SELECT h.id, h.id_bom, h.id_item, h.accion, h.campo_modificado,
                   h.valor_anterior, h.valor_nuevo, h.version_bom, h.realizado_por,
                   h.created_at AT TIME ZONE 'America/Mexico_City' AS created_at,
                   u.nombre AS realizado_por_nombre
            FROM tb_bom_historial h
            LEFT JOIN tb_usuarios u ON u.id_usuario = h.realizado_por
            WHERE {' AND '.join(condiciones)}
            ORDER BY h.created_at DESC
        """, *params)
        return [dict(r) for r in rows]

    async def get_historial_usuarios(self, conn, id_bom: UUID) -> List[dict]:
        """Usuarios distintos con cambios registrados en el historial de un BOM (para el filtro)."""
        rows = await conn.fetch("""
            SELECT DISTINCT h.realizado_por AS id_usuario, u.nombre
            FROM tb_bom_historial h
            LEFT JOIN tb_usuarios u ON u.id_usuario = h.realizado_por
            WHERE h.id_bom = $1 AND h.realizado_por IS NOT NULL
            ORDER BY u.nombre
        """, id_bom)
        return [dict(r) for r in rows]

    # ─── APROBACIONES ───────────────────────────────────────

    async def registrar_aprobacion(
        self, conn, id_bom: UUID, tipo: str, version_bom: int,
        usuario_id: UUID, id_paquete: UUID, comentarios: Optional[str] = None,
        destino_rechazo: Optional[str] = None,
    ) -> dict:
        """Registra una accion de aprobacion/rechazo."""
        row = await conn.fetchrow("""
            INSERT INTO tb_bom_aprobaciones (
                id_bom, tipo, version_bom, usuario_id, comentarios,
                destino_rechazo, id_paquete, ciclo
            )
            SELECT $1, $2, $3, $4, $5, $6, $7,
                   1 + COUNT(*) FILTER (
                       WHERE tipo IN (
                           'RECHAZO_ING', 'RECHAZO_OBRA',
                           'RECHAZO_CONST', 'RECHAZO_FINAL',
                           'DEVOLUCION_BORRADOR'
                       )
                   )
            FROM tb_bom_aprobaciones
            WHERE id_bom = $1
            RETURNING *
        """, id_bom, tipo, version_bom, usuario_id, comentarios, destino_rechazo, id_paquete)
        return dict(row)

    async def get_aprobaciones_by_bom(self, conn, id_bom: UUID) -> List[dict]:
        """Lista aprobaciones/rechazos de un BOM."""
        rows = await conn.fetch("""
            SELECT a.id, a.id_bom, a.tipo, a.version_bom, a.usuario_id,
                   a.comentarios, a.destino_rechazo,
                   a.created_at AT TIME ZONE 'America/Mexico_City' AS created_at,
                   u.nombre AS usuario_nombre
            FROM tb_bom_aprobaciones a
            LEFT JOIN tb_usuarios u ON u.id_usuario = a.usuario_id
            WHERE a.id_bom = $1
            ORDER BY a.created_at ASC
        """, id_bom)
        return [dict(r) for r in rows]

    async def get_ultimo_rechazo(self, conn, id_bom: UUID) -> Optional[dict]:
        """Obtiene el ultimo rechazo/devolucion del BOM."""
        row = await conn.fetchrow("""
            SELECT a.tipo, a.comentarios, a.destino_rechazo,
                   a.created_at AT TIME ZONE 'America/Mexico_City' AS created_at,
                   u.nombre AS rechazado_por
            FROM tb_bom_aprobaciones a
            JOIN tb_usuarios u ON a.usuario_id = u.id_usuario
            WHERE a.id_bom = $1
              AND a.tipo IN (
                  'RECHAZO_ING', 'RECHAZO_OBRA', 'RECHAZO_CONST',
                  'RECHAZO_FINAL', 'DEVOLUCION_BORRADOR'
              )
            ORDER BY a.created_at DESC LIMIT 1
        """, id_bom)
        return dict(row) if row else None

    # ─── ESTADISTICAS ───────────────────────────────────────

    async def get_estadisticas_bom(self, conn, id_bom: UUID) -> dict:
        """Estadisticas de items del BOM: totales, entregados, pendientes, costos, recepcion."""
        row = await conn.fetchrow("""
            SELECT
                COUNT(*) FILTER (WHERE i.activo) AS total_items,
                COUNT(*) FILTER (
                    WHERE i.activo
                      AND (
                          i.entregado
                          OR (i.cantidad > 0 AND COALESCE(er.cantidad_recibida, i.cantidad_recibida, 0) >= i.cantidad)
                      )
                ) AS entregados,
                COUNT(*) FILTER (
                    WHERE i.activo
                      AND NOT (
                          i.entregado
                          OR (i.cantidad > 0 AND COALESCE(er.cantidad_recibida, i.cantidad_recibida, 0) >= i.cantidad)
                      )
                ) AS pendientes,
                COUNT(*) FILTER (WHERE i.activo AND COALESCE(er.id_proveedor_real, i.id_proveedor) IS NOT NULL) AS con_proveedor,
                COUNT(*) FILTER (WHERE i.activo AND i.fecha_requerida IS NOT NULL) AS con_fecha_requerida,
                COUNT(*) FILTER (WHERE i.activo AND i.fecha_requerida IS NOT NULL
                                 AND i.fecha_requerida < (NOW() AT TIME ZONE 'America/Mexico_City')::DATE
                                 AND NOT (
                                     i.entregado
                                     OR (i.cantidad > 0 AND COALESCE(er.cantidad_recibida, i.cantidad_recibida, 0) >= i.cantidad)
                                 )) AS atrasados,
                COUNT(*) FILTER (
                    WHERE i.activo AND COALESCE(i.tipo_origen_item, 'BASE') = 'REEMPLAZO'
                ) AS items_reemplazo,
                COUNT(*) FILTER (
                    WHERE i.activo AND COALESCE(i.tipo_origen_item, 'BASE') = 'FUERA_SCOPE'
                ) AS items_fuera_scope,
                COUNT(*) FILTER (
                    WHERE i.activo AND er.estatus_ejecucion IN ('NO_ADQUIRIDO', 'REEMPLAZADO', 'CERRADO')
                ) AS items_no_adquiridos,
                COUNT(*) FILTER (WHERE i.activo AND COALESCE(er.cantidad_recibida, i.cantidad_recibida, 0) > 0
                                 AND COALESCE(er.cantidad_recibida, i.cantidad_recibida, 0) < i.cantidad) AS items_parcialmente_recibidos,
                COUNT(*) FILTER (WHERE i.activo AND COALESCE(er.cantidad_recibida, i.cantidad_recibida, 0) >= i.cantidad
                                 AND i.cantidad > 0) AS items_completamente_recibidos
            FROM tb_bom_items i
            LEFT JOIN tb_bom_item_ejecucion er ON er.id_item = i.id_item
            WHERE i.id_bom = $1
        """, id_bom)
        return dict(row) if row else {}

    # ─── CATALOGOS ──────────────────────────────────────────

    async def get_tipos_entrega(self, conn) -> List[dict]:
        """Lista tipos de entrega activos."""
        rows = await conn.fetch("""
            SELECT id, nombre FROM tb_cat_tipos_entrega
            WHERE activo = TRUE ORDER BY orden ASC
        """)
        return [dict(r) for r in rows]

    async def get_categorias_compra(self, conn) -> List[dict]:
        """Lista categorias de compra activas."""
        rows = await conn.fetch("""
            SELECT id, nombre FROM tb_cat_categorias_compra
            WHERE activo = TRUE ORDER BY orden ASC
        """)
        return [dict(r) for r in rows]

    async def get_unidades_medida(self, conn) -> List[dict]:
        """Lista unidades de medida activas."""
        rows = await conn.fetch("""
            SELECT codigo, nombre FROM tb_cat_unidades_medida
            WHERE activo = TRUE ORDER BY orden ASC
        """)
        return [dict(r) for r in rows]

    async def get_proveedores(self, conn) -> List[dict]:
        """Lista proveedores activos."""
        rows = await conn.fetch("""
            SELECT id_proveedor, nombre_comercial, razon_social, rfc
            FROM tb_proveedores
            WHERE activo = TRUE
            ORDER BY nombre_comercial ASC
        """)
        return [dict(r) for r in rows]

    async def get_usuarios_por_area(self, conn, module_slug: str, solo_jefes: bool = False) -> List[dict]:
        """Lista usuarios activos por modulo; jefes salen de rol_organizacional."""
        if solo_jefes:
            rol_org_por_modulo = {
                "ingenieria": "jefe_ingenieria",
                "construccion": "jefe_construccion",
            }
            rol_org = rol_org_por_modulo.get(module_slug)
            if not rol_org:
                return []
            rows = await conn.fetch("""
                SELECT id_usuario, nombre, email, rol_organizacional
                FROM tb_usuarios
                WHERE rol_organizacional = $1
                  AND is_active = TRUE
                ORDER BY nombre ASC
            """, rol_org)
            return [dict(r) for r in rows]

        rows = await conn.fetch("""
            SELECT u.id_usuario, u.nombre, u.email, pm.rol_modulo
            FROM tb_usuarios u
            JOIN tb_permisos_modulos pm ON pm.usuario_id = u.id_usuario
            WHERE pm.modulo_slug = $1
              AND pm.rol_modulo IN ('editor', 'admin')
              AND u.is_active = TRUE
            ORDER BY u.nombre ASC
        """, module_slug)
        return [dict(r) for r in rows]

    @staticmethod
    def _empaquetar_paginado(rows, limite: int, offset: int) -> dict:
        """Extrae 'total_count' (window function) de la primera fila y arma la respuesta paginada."""
        rows_list = [dict(r) for r in rows]
        total = rows_list[0]["total_count"] if rows_list else 0
        for r in rows_list:
            del r["total_count"]
        return {
            "items": rows_list,
            "total": total,
            "limit": limite,
            "offset": offset,
        }

    async def buscar_materiales_para_bom(
        self, conn, query: str, query_norm: str = "",
        umbral: float = 0.15, limite: int = 20, offset: int = 0
    ) -> dict:
        """Busca materiales en historial XML y catalogo interno.
        query_norm debe ser normalizar_descripcion(query) para el matching contra descripcion_norm."""
        rows = await conn.fetch(f"""
            WITH xml_dedup AS (
                SELECT DISTINCT ON (m.descripcion_proveedor)
                    m.id::text                                        AS id,
                    m.descripcion_proveedor                           AS descripcion,
                    COALESCE(m.unidad_homologada, m.unidad)           AS unidad,
                    m.precio_unitario,
                    p.razon_social                                     AS proveedor_nombre,
                    NULL::text                                         AS categoria_nombre,
                    m.clave_prod_serv,
                    m.fecha_factura,
                    'XML'::text                                        AS fuente,
                    {_MONEDA_XML_SQL} AS moneda,
                    GREATEST(
                        similarity(m.descripcion_proveedor, $1),
                        word_similarity($1, m.descripcion_proveedor)
                    )                                                  AS similitud,
                    vlink.id_material_interno
                FROM tb_materiales_historial m
                LEFT JOIN tb_proveedores p ON p.id_proveedor = m.id_proveedor
                LEFT JOIN tb_materiales_interno_xml vlink ON vlink.id_material_xml = m.id
                WHERE m.descripcion_proveedor ILIKE '%' || $1 || '%'
                   OR word_similarity($1, m.descripcion_proveedor) >= $2
                ORDER BY m.descripcion_proveedor,
                         (vlink.id_material_interno IS NOT NULL) DESC,
                         m.fecha_factura DESC
            ),
            combinado AS (
                SELECT
                    xd.id, xd.descripcion, xd.unidad, xd.precio_unitario,
                    xd.proveedor_nombre, xd.categoria_nombre, xd.clave_prod_serv,
                    xd.fecha_factura, xd.fuente, xd.moneda, xd.similitud,
                    ci.descripcion_canonica                                AS descripcion_interna,
                    xd.id_material_interno::text                           AS id_material_interno,
                    1                                                      AS prioridad
                FROM xml_dedup xd
                LEFT JOIN tb_cat_materiales ci ON ci.id = xd.id_material_interno
                UNION ALL
                SELECT
                    c.id::text,
                    c.descripcion_canonica,
                    u.codigo,
                    c.precio_referencia,
                    NULL,
                    cat.nombre,
                    c.clave_prod_serv,
                    NULL::date,
                    'INTERNO'::text,
                    c.moneda,
                    {interno_similitud_expr_sql('c.descripcion_norm', '$3')},
                    NULL::text,
                    NULL::text,
                    0                                                      AS prioridad
                FROM tb_cat_materiales c
                LEFT JOIN tb_cat_unidades_medida u   ON u.id  = c.id_unidad_medida
                LEFT JOIN tb_cat_categorias_compra cat ON cat.id = c.id_categoria
                WHERE c.activo = TRUE
                  AND {interno_similitud_where_sql('c.descripcion_norm', '$3', '$2')}
            ),
            deduplicado AS (
                -- Un material del catalogo ya vinculado a XML puede calzar por su
                -- descripcion canonica (rama INTERNO) sin calzar por el texto crudo
                -- de la factura (rama XML) o viceversa -- se dedupe por
                -- id_material_interno (o por id propio si no hay vinculo) y se queda
                -- la coincidencia de mayor similitud, no la primera rama que aparezca.
                SELECT DISTINCT ON (COALESCE(id_material_interno, id))
                    id, descripcion, unidad, precio_unitario, proveedor_nombre, categoria_nombre,
                    clave_prod_serv, fecha_factura, fuente, moneda, similitud, descripcion_interna,
                    id_material_interno, prioridad
                FROM combinado
                ORDER BY COALESCE(id_material_interno, id), similitud DESC NULLS LAST, prioridad ASC
            )
            SELECT id, descripcion, unidad, precio_unitario, proveedor_nombre, categoria_nombre,
                   clave_prod_serv, fecha_factura, fuente, moneda, similitud, descripcion_interna,
                   id_material_interno, COUNT(*) OVER() AS total_count
            FROM deduplicado
            ORDER BY prioridad ASC, similitud DESC NULLS LAST
            LIMIT $4 OFFSET $5
        """, query, umbral, query_norm or query, limite, offset)
        if not rows and offset > 0:
            # COUNT(*) OVER() viaja en las filas devueltas; si el offset deja la pagina vacia
            # no hay fila de la cual leer el total real, por eso se recalcula aparte.
            total = await conn.fetchval(f"""
                WITH xml_dedup AS (
                    SELECT DISTINCT ON (m.descripcion_proveedor)
                        m.id, vlink.id_material_interno
                    FROM tb_materiales_historial m
                    LEFT JOIN tb_materiales_interno_xml vlink ON vlink.id_material_xml = m.id
                    WHERE m.descripcion_proveedor ILIKE '%' || $1 || '%'
                       OR word_similarity($1, m.descripcion_proveedor) >= $2
                    ORDER BY m.descripcion_proveedor,
                             (vlink.id_material_interno IS NOT NULL) DESC,
                             m.fecha_factura DESC
                ),
                combinado AS (
                    SELECT xd.id::text AS id, xd.id_material_interno::text AS id_material_interno
                    FROM xml_dedup xd
                    UNION ALL
                    SELECT c.id::text, NULL::text
                    FROM tb_cat_materiales c
                    WHERE c.activo = TRUE
                      AND {interno_similitud_where_sql('c.descripcion_norm', '$3', '$2')}
                )
                SELECT COUNT(DISTINCT COALESCE(id_material_interno, id)) FROM combinado
            """, query, umbral, query_norm or query)
            return {"items": [], "total": total, "limit": limite, "offset": offset}
        return self._empaquetar_paginado(rows, limite, offset)

    async def get_materiales_recientes(self, conn, limite: int = 10, offset: int = 0) -> dict:
        """Lista materiales recientes (XML) y todos los internos activos para el dropdown inicial."""
        rows = await conn.fetch(f"""
            WITH xml_dedup AS (
                SELECT DISTINCT ON (m.descripcion_proveedor)
                    m.id::text                              AS id,
                    m.descripcion_proveedor                 AS descripcion,
                    COALESCE(m.unidad_homologada, m.unidad) AS unidad,
                    m.precio_unitario,
                    p.razon_social                          AS proveedor_nombre,
                    NULL::text                              AS categoria_nombre,
                    m.clave_prod_serv,
                    m.fecha_factura,
                    'XML'::text                             AS fuente,
                    {_MONEDA_XML_SQL} AS moneda,
                    1.0::real                               AS similitud,
                    vlink.id_material_interno
                FROM tb_materiales_historial m
                LEFT JOIN tb_proveedores p ON p.id_proveedor = m.id_proveedor
                LEFT JOIN tb_materiales_interno_xml vlink ON vlink.id_material_xml = m.id
                ORDER BY m.descripcion_proveedor,
                         (vlink.id_material_interno IS NOT NULL) DESC,
                         m.fecha_factura DESC
            ),
            combinado AS (
                SELECT
                    xd.id, xd.descripcion, xd.unidad, xd.precio_unitario,
                    xd.proveedor_nombre, xd.categoria_nombre, xd.clave_prod_serv,
                    xd.fecha_factura, xd.fuente, xd.moneda, xd.similitud,
                    ci.descripcion_canonica                 AS descripcion_interna,
                    xd.id_material_interno::text            AS id_material_interno,
                    1                                        AS prioridad,
                    NULL::text                              AS orden_alfa
                FROM xml_dedup xd
                LEFT JOIN tb_cat_materiales ci ON ci.id = xd.id_material_interno
                UNION ALL
                SELECT
                    c.id::text,
                    c.descripcion_canonica,
                    u.codigo,
                    c.precio_referencia,
                    NULL,
                    cat.nombre,
                    c.clave_prod_serv,
                    (c.created_at AT TIME ZONE 'America/Mexico_City')::date,
                    'INTERNO'::text,
                    c.moneda,
                    1.0::real,
                    NULL::text,
                    NULL::text,
                    0                                        AS prioridad,
                    LOWER(c.descripcion_canonica)           AS orden_alfa
                FROM tb_cat_materiales c
                LEFT JOIN tb_cat_unidades_medida u   ON u.id  = c.id_unidad_medida
                LEFT JOIN tb_cat_categorias_compra cat ON cat.id = c.id_categoria
                WHERE c.activo = TRUE
                  AND NOT EXISTS (
                      SELECT 1 FROM tb_materiales_interno_xml v
                      WHERE v.id_material_interno = c.id
                  )
            )
            SELECT id, descripcion, unidad, precio_unitario, proveedor_nombre, categoria_nombre,
                   clave_prod_serv, fecha_factura, fuente, moneda, similitud, descripcion_interna,
                   id_material_interno, COUNT(*) OVER() AS total_count
            FROM combinado
            ORDER BY prioridad ASC, orden_alfa ASC NULLS LAST, fecha_factura DESC NULLS LAST
            LIMIT $1 OFFSET $2
        """, limite, offset)
        if not rows and offset > 0:
            # COUNT(*) OVER() viaja en las filas devueltas; si el offset deja la pagina vacia
            # no hay fila de la cual leer el total real, por eso se recalcula aparte.
            total = await conn.fetchval("""
                WITH xml_dedup AS (
                    SELECT DISTINCT ON (m.descripcion_proveedor) m.id
                    FROM tb_materiales_historial m
                    ORDER BY m.descripcion_proveedor
                ),
                combinado AS (
                    SELECT id FROM xml_dedup
                    UNION ALL
                    SELECT c.id
                    FROM tb_cat_materiales c
                    WHERE c.activo = TRUE
                      AND NOT EXISTS (
                          SELECT 1 FROM tb_materiales_interno_xml v
                          WHERE v.id_material_interno = c.id
                      )
                )
                SELECT COUNT(*) FROM combinado
            """)
            return {"items": [], "total": total, "limit": limite, "offset": offset}
        return self._empaquetar_paginado(rows, limite, offset)

    async def get_proyecto_info(self, conn, id_proyecto: UUID) -> Optional[dict]:
        """Obtiene info basica del proyecto."""
        row = await conn.fetchrow("""
            SELECT p.id_proyecto, p.proyecto_id_estandar, o.nombre_proyecto, p.area_actual
            FROM tb_proyectos_gate p
            LEFT JOIN tb_oportunidades o ON o.id_oportunidad = p.id_oportunidad
            WHERE p.id_proyecto = $1
        """, id_proyecto)
        return dict(row) if row else None

    async def get_usuario_activo_por_rol_org(
        self, conn, rol_organizacional: str, estricto: bool = False
    ) -> Optional[dict]:
        """Obtiene el usuario activo con un rol organizacional.

        estricto=True lanza ValueError si hay 2+ usuarios activos con el mismo rol,
        en vez de loguear y usar el primero alfabeticamente (comportamiento default).
        """
        rows = await conn.fetch("""
            SELECT id_usuario, nombre, email, rol_organizacional
            FROM tb_usuarios
            WHERE rol_organizacional = $1
              AND is_active = TRUE
            ORDER BY nombre ASC
        """, rol_organizacional)
        if len(rows) > 1:
            if estricto:
                raise ValueError(
                    f"Hay mas de un usuario activo con rol_organizacional='{rol_organizacional}'"
                )
            logger.warning(
                "Multiples usuarios activos con rol_organizacional='%s': %s — usando primero",
                rol_organizacional, [r['nombre'] for r in rows]
            )
        return dict(rows[0]) if rows else None

    async def get_responsable_proyecto_o_global(
        self, conn, id_proyecto, rol_organizacional: str, estricto: bool = False
    ) -> Optional[dict]:
        """
        Resuelve el jefe del area para un proyecto: primero el RC/RI persistido en
        tb_proyecto_usuarios; si el proyecto aun no lo tiene, cae al primer jefe
        organizacional activo (comportamiento previo).

        estricto=True solo aplica al fallback: si el proyecto no tiene RC/RI persistido
        y hay 2+ jefes activos del area, lanza ValueError en vez de autoasignar el primero.
        """
        rol_resp = {
            "jefe_construccion": "responsable_construccion",
            "jefe_ingenieria": "responsable_ingenieria",
        }.get(rol_organizacional)
        if rol_resp:
            row = await conn.fetchrow(
                """
                SELECT u.id_usuario, u.nombre, u.email
                FROM tb_proyecto_usuarios pu
                JOIN tb_usuarios u ON u.id_usuario = pu.id_usuario
                WHERE pu.id_proyecto = $1 AND pu.rol_proyecto = $2 AND pu.activo = TRUE
                  AND u.is_active = TRUE
                LIMIT 1
                """,
                id_proyecto, rol_resp,
            )
            if row:
                return dict(row)
        return await self.get_usuario_activo_por_rol_org(
            conn, rol_organizacional, estricto=estricto
        )

    async def get_asignacion_proyecto(
        self, conn, id_proyecto: UUID, rol_proyecto: str, area: str
    ) -> Optional[dict]:
        """Obtiene una asignacion activa del equipo del proyecto."""
        row = await conn.fetchrow("""
            SELECT pu.id_usuario, pu.rol_proyecto, pu.area, u.nombre, u.email
            FROM tb_proyecto_usuarios pu
            JOIN tb_usuarios u ON u.id_usuario = pu.id_usuario
            WHERE pu.id_proyecto = $1
              AND pu.rol_proyecto = $2
              AND pu.area = $3
              AND pu.activo = TRUE
              AND u.is_active = TRUE
            LIMIT 1
        """, id_proyecto, rol_proyecto, area)
        return dict(row) if row else None

    async def get_asignaciones_proyecto(
        self, conn, id_proyecto: UUID, roles: List[str], area: str
    ) -> dict:
        """Obtiene varias asignaciones activas del proyecto en una sola consulta.

        Retorna dict {rol_proyecto: row}, solo con los roles que tienen asignacion activa.
        """
        rows = await conn.fetch("""
            SELECT pu.id_usuario, pu.rol_proyecto, pu.area, u.nombre, u.email
            FROM tb_proyecto_usuarios pu
            JOIN tb_usuarios u ON u.id_usuario = pu.id_usuario
            WHERE pu.id_proyecto = $1
              AND pu.rol_proyecto = ANY($2::text[])
              AND pu.area = $3
              AND pu.activo = TRUE
              AND u.is_active = TRUE
        """, id_proyecto, roles, area)
        return {row['rol_proyecto']: dict(row) for row in rows}

    async def usuario_tiene_rol_org(
        self, conn, user_id: UUID, rol_organizacional: str
    ) -> bool:
        exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1
                FROM tb_usuarios
                WHERE id_usuario = $1
                  AND rol_organizacional = $2
                  AND is_active = TRUE
            )
        """, user_id, rol_organizacional)
        return bool(exists)

    async def usuario_tiene_asignacion_proyecto(
        self,
        conn,
        id_proyecto: UUID,
        user_id: UUID,
        rol_proyecto: str,
        area: str,
    ) -> bool:
        exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1
                FROM tb_proyecto_usuarios pu
                JOIN tb_usuarios u ON u.id_usuario = pu.id_usuario
                WHERE pu.id_proyecto = $1
                  AND pu.id_usuario = $2
                  AND pu.rol_proyecto = $3
                  AND pu.area = $4
                  AND pu.activo = TRUE
                  AND u.is_active = TRUE
            )
        """, id_proyecto, user_id, rol_proyecto, area)
        return bool(exists)

    # ─── GRUPOS BOM ─────────────────────────────────────────

    async def get_grupos_bom(self, conn) -> List[dict]:
        """Lista grupos BOM activos (AC/DC/CM/OC/TE)."""
        rows = await conn.fetch("""
            SELECT id, codigo, nombre, orden
            FROM tb_cat_grupos_bom
            WHERE activo = TRUE
            ORDER BY orden ASC
        """)
        return [dict(r) for r in rows]

    async def get_grupos_por_item(self, conn, id_item: UUID) -> List[str]:
        """Retorna lista de codigos de grupos para un item."""
        rows = await conn.fetch("""
            SELECT g.codigo
            FROM tb_bom_item_grupos ig
            JOIN tb_cat_grupos_bom g ON g.id = ig.id_grupo
            WHERE ig.id_item = $1
            ORDER BY g.orden ASC
        """, id_item)
        return [r['codigo'] for r in rows]

    async def get_grupos_operativos_por_item(self, conn, id_item: UUID) -> List[str]:
        """Retorna lista de codigos de grupos operativos para un item."""
        rows = await conn.fetch("""
            SELECT g.codigo
            FROM tb_bom_item_grupos_operativos ig
            JOIN tb_cat_grupos_bom g ON g.id = ig.id_grupo
            WHERE ig.id_item = $1
              AND g.activo = TRUE
            ORDER BY g.orden ASC
        """, id_item)
        return [r['codigo'] for r in rows]

    async def get_grupos_por_bom(self, conn, id_bom: UUID) -> dict:
        """Retorna mapa {id_item: [codigo, ...]} para todos los items del BOM. Previene N+1."""
        rows = await conn.fetch("""
            SELECT ig.id_item, g.codigo
            FROM tb_bom_item_grupos ig
            JOIN tb_cat_grupos_bom g ON g.id = ig.id_grupo
            JOIN tb_bom_items i ON i.id_item = ig.id_item
            WHERE i.id_bom = $1 AND i.activo = TRUE
            ORDER BY g.orden ASC
        """, id_bom)
        result: dict = {}
        for r in rows:
            key = str(r['id_item'])
            result.setdefault(key, [])
            result[key].append(r['codigo'])
        return result

    async def get_grupos_operativos_por_bom(self, conn, id_bom: UUID) -> dict:
        """Retorna mapa {id_item: [codigo, ...]} de grupos operativos."""
        rows = await conn.fetch("""
            SELECT ig.id_item, g.codigo
            FROM tb_bom_item_grupos_operativos ig
            JOIN tb_cat_grupos_bom g ON g.id = ig.id_grupo
            JOIN tb_bom_items i ON i.id_item = ig.id_item
            WHERE i.id_bom = $1
              AND i.activo = TRUE
              AND g.activo = TRUE
            ORDER BY g.orden ASC
        """, id_bom)
        result: dict = {}
        for r in rows:
            key = str(r['id_item'])
            result.setdefault(key, [])
            result[key].append(r['codigo'])
        return result

    async def set_item_grupos(self, conn, id_item: UUID, grupo_ids: List[int]) -> None:
        """Reemplaza todos los grupos de un item (delete + insert)."""
        await conn.execute(
            "DELETE FROM tb_bom_item_grupos WHERE id_item = $1", id_item
        )
        if grupo_ids:
            for gid in grupo_ids:
                await conn.execute(
                    "INSERT INTO tb_bom_item_grupos (id_item, id_grupo) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                    id_item, gid
                )

    async def set_item_grupos_operativos(
        self, conn, id_item: UUID, grupo_ids: List[int], user_id: Optional[UUID] = None
    ) -> None:
        """Reemplaza todos los grupos operativos de un item."""
        await conn.execute(
            "DELETE FROM tb_bom_item_grupos_operativos WHERE id_item = $1", id_item
        )
        if grupo_ids:
            await conn.executemany("""
                    INSERT INTO tb_bom_item_grupos_operativos
                        (id_item, id_grupo, created_by)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (id_item, id_grupo) DO UPDATE
                    SET created_by = EXCLUDED.created_by
                """,
                [(id_item, gid, user_id) for gid in grupo_ids],
            )

    async def get_distribucion_grupos_item(
        self, conn, id_item: UUID,
    ) -> List[dict]:
        """Porcentajes explícitos del item; una ausencia multigrupo queda pendiente."""
        rows = await conn.fetch(
            """
            SELECT asignacion.id_grupo,
                   asignacion.grupo_codigo_snapshot AS codigo,
                   asignacion.grupo_nombre_snapshot AS nombre,
                   asignacion.porcentaje
            FROM tb_bom_item_grupo_asignaciones asignacion
            WHERE asignacion.id_bom_item = $1
            ORDER BY asignacion.grupo_codigo_snapshot, asignacion.id_grupo
            """,
            id_item,
        )
        return [dict(row) for row in rows]

    async def set_distribucion_grupos_item(
        self, conn, id_item: UUID, porcentajes: dict[int, Decimal],
    ) -> None:
        """Reemplaza la distribución financiera con snapshots del catálogo."""
        await conn.execute(
            "DELETE FROM tb_bom_item_grupo_asignaciones WHERE id_bom_item = $1",
            id_item,
        )
        if not porcentajes:
            return
        await conn.executemany(
            """
            INSERT INTO tb_bom_item_grupo_asignaciones (
                id_bom_item, id_grupo, grupo_codigo_snapshot,
                grupo_nombre_snapshot, porcentaje
            )
            SELECT $1, grupo.id, grupo.codigo, grupo.nombre, $3
            FROM tb_cat_grupos_bom grupo
            WHERE grupo.id = $2 AND grupo.activo = TRUE
            """,
            [
                (id_item, id_grupo, porcentaje)
                for id_grupo, porcentaje in porcentajes.items()
            ],
        )

    # ─── SUPLENCIAS ─────────────────────────────────────────

    async def get_suplencia_activa_del_titular(self, conn, titular_id: UUID) -> Optional[dict]:
        """Obtiene suplencia activa vigente de un usuario (como titular)."""
        row = await conn.fetchrow("""
            SELECT s.id, s.titular_id, s.suplente_id, s.fecha_fin, s.activo,
                   s.lock_version, s.created_at,
                   u.nombre AS suplente_nombre
            FROM tb_bom_suplencias s
            JOIN tb_usuarios u ON u.id_usuario = s.suplente_id
            WHERE s.titular_id = $1
              AND s.activo = TRUE
              AND s.fecha_fin >= (NOW() AT TIME ZONE 'America/Mexico_City')::DATE
            ORDER BY s.fecha_fin DESC
            LIMIT 1
        """, titular_id)
        return dict(row) if row else None

    async def get_titulares_que_representa(self, conn, suplente_id: UUID) -> List[UUID]:
        """Retorna los titular_ids que este usuario puede representar hoy."""
        rows = await conn.fetch("""
            SELECT titular_id
            FROM tb_bom_suplencias
            WHERE suplente_id = $1
              AND activo = TRUE
              AND fecha_fin >= (NOW() AT TIME ZONE 'America/Mexico_City')::DATE
        """, suplente_id)
        return [r['titular_id'] for r in rows]

    async def crear_suplencia(
        self, conn, titular_id: UUID, suplente_id: UUID, fecha_fin,
        id_esperado: Optional[int], lock_version_esperado: Optional[int],
    ) -> Optional[dict]:
        """Reemplaza con CAS la suplencia activa del titular."""
        await conn.fetchval(
            "SELECT pg_advisory_xact_lock(hashtextextended($1::text, 0))",
            f"bom-suplencia:{titular_id}",
        )
        actual = await conn.fetchrow("""
            SELECT id, lock_version
            FROM tb_bom_suplencias
            WHERE titular_id = $1 AND activo = TRUE
            FOR UPDATE
        """, titular_id)
        if actual:
            if actual["id"] != id_esperado or actual["lock_version"] != lock_version_esperado:
                return None
            desactivada = await conn.fetchval("""
                UPDATE tb_bom_suplencias
                SET activo = FALSE, lock_version = lock_version + 1
                WHERE id = $1 AND lock_version = $2 AND activo = TRUE
                RETURNING id
            """, id_esperado, lock_version_esperado)
            if not desactivada:
                return None
        elif id_esperado is not None or lock_version_esperado is not None:
            return None
        row = await conn.fetchrow("""
            INSERT INTO tb_bom_suplencias (titular_id, suplente_id, fecha_fin)
            VALUES ($1, $2, $3)
            RETURNING *
        """, titular_id, suplente_id, fecha_fin)
        return dict(row)

    async def desactivar_suplencia(
        self, conn, titular_id: UUID, id_esperado: int, lock_version_esperado: int,
    ) -> bool:
        """Desactiva con CAS la suplencia exacta del titular."""
        row = await conn.fetchval("""
            UPDATE tb_bom_suplencias
            SET activo = FALSE, lock_version = lock_version + 1
            WHERE titular_id = $1 AND id = $2
              AND lock_version = $3 AND activo = TRUE
            RETURNING id
        """, titular_id, id_esperado, lock_version_esperado)
        return bool(row)

    # ─── APROBADOR FINAL ────────────────────────────────────

    async def get_aprobador_final_id(self, conn) -> Optional[UUID]:
        """Lee el UUID del aprobador final desde tb_configuracion_global."""
        val = await conn.fetchval("""
            SELECT valor FROM tb_configuracion_global
            WHERE clave = 'bom_aprobador_final_id'
        """)
        if val:
            try:
                from uuid import UUID as _UUID
                return _UUID(val)
            except (ValueError, AttributeError):
                return None
        return None

    async def get_usuario_email(self, conn, user_id: UUID) -> Optional[str]:
        """Retorna el email de un usuario activo, o None si no existe."""
        return await conn.fetchval(
            "SELECT email FROM tb_usuarios WHERE id_usuario = $1 AND is_active = TRUE",
            user_id
        )

    async def get_usuario_activo_basico(self, conn, user_id: UUID) -> Optional[dict]:
        """Retorna id y nombre de un usuario activo."""
        row = await conn.fetchrow(
            "SELECT id_usuario, nombre FROM tb_usuarios WHERE id_usuario = $1 AND is_active = TRUE",
            user_id,
        )
        return dict(row) if row else None

    async def get_usuario_nombre(self, conn, user_id: UUID) -> Optional[str]:
        """Retorna el nombre de un usuario, o None si no existe."""
        return await conn.fetchval(
            "SELECT nombre FROM tb_usuarios WHERE id_usuario = $1",
            user_id,
        )

    async def get_sender_email(self, conn, departamento: str = 'DEFAULT') -> Optional[str]:
        """Retorna email_remitente del buzon de notificaciones configurado."""
        email = await conn.fetchval("""
            SELECT email_remitente FROM tb_correos_notificaciones
            WHERE departamento = $1 AND activo = TRUE LIMIT 1
        """, departamento.upper())
        if not email:
            email = await conn.fetchval("""
                SELECT email_remitente FROM tb_correos_notificaciones
                WHERE departamento = 'DEFAULT' AND activo = TRUE LIMIT 1
            """)
        return email

    async def set_aprobador_final_id(self, conn, user_id: Optional[UUID]) -> None:
        """Actualiza el UUID del aprobador final en tb_configuracion_global."""
        await conn.execute("""
            UPDATE tb_configuracion_global
            SET valor = $1
            WHERE clave = 'bom_aprobador_final_id'
        """, str(user_id) if user_id else "")

    # ─── TIPO DE CAMBIO PARA ITEMS USD ─────────────────────

    async def get_tc_from_linked_materials(
        self, conn, item_ids: List[UUID]
    ) -> dict:
        """Retorna {id_item: tipo_cambio_xml} para items vinculados a materiales con TC del XML."""
        rows = await conn.fetch("""
            SELECT mh.id_bom_item, mh.tipo_cambio_xml
            FROM tb_materiales_historial mh
            WHERE mh.id_bom_item = ANY($1::uuid[])
              AND mh.tipo_cambio_xml IS NOT NULL
            ORDER BY mh.created_at DESC
        """, item_ids)
        result = {}
        for r in rows:
            key = str(r['id_bom_item'])
            if key not in result:
                result[key] = r['tipo_cambio_xml']
        return result

    async def get_tasa_promedio(self, conn, days: int = 7) -> Optional[Decimal]:
        """Promedio de los ultimos N dias de tasa Banxico. Fallback si no hay TC reciente."""
        val = await conn.fetchval("""
            SELECT AVG(tasa_mxn)
            FROM (
                SELECT tasa_mxn FROM tb_tipo_cambio
                ORDER BY fecha DESC
                LIMIT $1
            ) sub
        """, days)
        return val if val else None

    async def get_gasto_real_por_item(self, conn, item_ids: List[UUID]) -> dict:
        """Retorna {id_item: total_gastado} sumando importes del item actual y su item_origen.

        Agrupa por current_id (el ID del item actual) para que el gasto histórico de
        versiones anteriores se sume al item vigente, no se devuelva como clave separada.
        Solo incluye items con al menos una factura vinculada (COUNT > 0): un item sin
        compras registradas no debe distinguirse de uno con $0 de gasto real confirmado.
        """
        rows = await conn.fetch("""
            WITH expanded AS (
                SELECT bi.id_item AS current_id, bi.id_item AS target_id
                FROM tb_bom_items bi WHERE bi.id_item = ANY($1::uuid[])
                UNION ALL
                SELECT bi.id_item AS current_id, bi.id_item_origen AS target_id
                FROM tb_bom_items bi
                WHERE bi.id_item = ANY($1::uuid[]) AND bi.id_item_origen IS NOT NULL
            )
            SELECT e.current_id, SUM(m.importe) AS total_gastado
            FROM expanded e
            JOIN tb_materiales_historial m ON m.id_bom_item = e.target_id
            GROUP BY e.current_id
        """, item_ids)
        return {str(r['current_id']): r['total_gastado'] for r in rows}

    # ─── PANELES FV DEL PROYECTO ────────────────────────────

    async def get_paneles_fv_activos(self, conn) -> List[dict]:
        """Catalogo de modelos de panel FV activos, para el selector de captura."""
        rows = await conn.fetch("""
            SELECT id, marca, modelo, potencia_w
            FROM tb_cat_paneles_fv
            WHERE activo = TRUE
            ORDER BY marca, modelo
        """)
        return [dict(r) for r in rows]

    async def existen_paneles_proyecto(self, conn, id_proyecto: UUID) -> bool:
        """True si el proyecto ya tiene al menos un panel FV capturado."""
        return bool(await conn.fetchval(
            "SELECT 1 FROM tb_proyecto_paneles WHERE id_proyecto = $1 LIMIT 1",
            id_proyecto,
        ))

    async def get_paneles_proyecto(self, conn, id_proyecto: UUID) -> List[dict]:
        """Paneles FV capturados para el proyecto, con datos del catalogo.

        potencia_w se castea a float: NUMERIC llega como Decimal via asyncpg, y el
        template lo serializa con tojson (json.dumps no soporta Decimal).
        """
        rows = await conn.fetch("""
            SELECT pp.id_panel, pp.cantidad, c.marca, c.modelo, c.potencia_w::float AS potencia_w
            FROM tb_proyecto_paneles pp
            JOIN tb_cat_paneles_fv c ON c.id = pp.id_panel
            WHERE pp.id_proyecto = $1
            ORDER BY c.marca, c.modelo
        """, id_proyecto)
        return [dict(r) for r in rows]

    async def reemplazar_paneles_proyecto(
        self, conn, id_proyecto: UUID, paneles: List[dict], user_id: UUID
    ) -> None:
        """Sincroniza el set de paneles del proyecto: quita los que ya no estan, hace
        upsert de los enviados. El upsert preserva creado_por en ediciones (solo
        ON CONFLICT actualiza cantidad/actualizado_por/updated_at) para no perder
        quien capturo originalmente el panel.
        """
        if not paneles:
            await conn.execute(
                "DELETE FROM tb_proyecto_paneles WHERE id_proyecto = $1",
                id_proyecto,
            )
            return
        id_paneles = [p["id_panel"] for p in paneles]
        await conn.execute(
            "DELETE FROM tb_proyecto_paneles WHERE id_proyecto = $1 AND id_panel <> ALL($2::int[])",
            id_proyecto, id_paneles,
        )
        await conn.executemany(
            """
            INSERT INTO tb_proyecto_paneles
                (id_proyecto, id_panel, cantidad, creado_por, actualizado_por)
            VALUES ($1, $2, $3, $4, $4)
            ON CONFLICT (id_proyecto, id_panel) DO UPDATE
                SET cantidad = EXCLUDED.cantidad,
                    actualizado_por = EXCLUDED.actualizado_por,
                    updated_at = now()
            """,
            [
                (id_proyecto, p["id_panel"], p["cantidad"], user_id)
                for p in paneles
            ],
        )
