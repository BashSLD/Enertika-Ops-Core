# modules/cfe/db_service.py
from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

import asyncpg

logger = logging.getLogger("CfeDBService")

# Regla unica "busqueda activa de un servicio": filtro de estatus + prioridad.
# La usan get_all_servicios (LATERAL) y get_busqueda_activa_por_servicio; ambas
# deben quedar en lockstep, por eso viven en una sola definicion. Es SQL estatico
# (sin valores de usuario), seguro de interpolar.
_BUSQUEDA_ACTIVA_FILTRO_ORDEN = """
              AND b.estatus IN ('pendiente','descargando','completado')
            ORDER BY
                CASE b.estatus
                    WHEN 'pendiente' THEN 1
                    WHEN 'descargando' THEN 2
                    ELSE 3
                END,
                b.creado_en DESC
            LIMIT 1
"""


class CfeDBService:

    async def get_all_servicios(self, conn: asyncpg.Connection) -> list[dict]:
        rows = await conn.fetch(
            f"""
            SELECT s.id, s.numero_servicio, s.nombre, s.alias, s.lada, s.telefono,
                   s.email, s.activo, s.creado_en,
                   COUNT(DISTINCT d.periodo) FILTER (
                       WHERE d.estatus = 'completado'
                         AND d.tipo = 'xml'
                         AND d.periodo <> 'pendiente'
                   ) AS total_descargas,
                   MAX(d.descargado_en) AS ultima_descarga,
                   COALESCE(BOOL_OR(d.estatus IN ('pendiente','descargando')), false) AS descarga_activa,
                   ba.id AS busqueda_activa_id,
                   ba.estatus AS busqueda_activa_estatus,
                   ba.max_periodos AS busqueda_activa_max_periodos,
                   (
                     COALESCE(BOOL_OR(d.estatus IN ('pendiente','descargando')), false)
                     OR ba.id IS NOT NULL
                   ) AS tiene_pendiente
            FROM tb_cfe_servicios s
            LEFT JOIN tb_cfe_descargas d ON d.servicio_id = s.id
            LEFT JOIN LATERAL (
                SELECT b.id, b.estatus, b.max_periodos
                FROM tb_cfe_busquedas b
                WHERE b.servicio_id = s.id{_BUSQUEDA_ACTIVA_FILTRO_ORDEN}
            ) ba ON true
            WHERE s.activo = true
            GROUP BY s.id, ba.id, ba.estatus, ba.max_periodos
            ORDER BY s.nombre
            """
        )
        return [dict(r) for r in rows]

    async def get_servicio_by_id(self, conn: asyncpg.Connection, servicio_id: UUID) -> Optional[dict]:
        row = await conn.fetchrow(
            "SELECT * FROM tb_cfe_servicios WHERE id = $1", servicio_id
        )
        return dict(row) if row else None

    async def get_servicio_by_numero(self, conn: asyncpg.Connection, numero: str) -> Optional[dict]:
        row = await conn.fetchrow(
            "SELECT * FROM tb_cfe_servicios WHERE numero_servicio = $1", numero
        )
        return dict(row) if row else None

    async def crear_servicio(
        self, conn: asyncpg.Connection, *, numero_servicio: str, nombre: str,
        alias: Optional[str], lada: str, telefono: str, email: str, creado_por: UUID,
    ) -> dict:
        row = await conn.fetchrow(
            """
            INSERT INTO tb_cfe_servicios
                (numero_servicio, nombre, alias, lada, telefono, email, creado_por)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING *
            """,
            numero_servicio, nombre, alias, lada, telefono, email, creado_por,
        )
        return dict(row)

    async def get_descargas_por_servicio(
        self, conn: asyncpg.Connection, servicio_id: UUID
    ) -> list[dict]:
        rows = await conn.fetch(
            """
            SELECT * FROM tb_cfe_descargas
            WHERE servicio_id = $1
            ORDER BY periodo DESC, tipo
            """,
            servicio_id,
        )
        return [dict(r) for r in rows]

    async def get_periodos_completados(
        self, conn: asyncpg.Connection, servicio_id: UUID
    ) -> set[str]:
        rows = await conn.fetch(
            """
            SELECT periodo FROM tb_cfe_descargas
            WHERE servicio_id = $1 AND estatus = 'completado'
            GROUP BY periodo
            HAVING COUNT(DISTINCT tipo) = 2
            """,
            servicio_id,
        )
        return {r["periodo"] for r in rows}

    async def get_descargas_resumen_por_servicio(
        self, conn: asyncpg.Connection, servicio_id: UUID
    ) -> dict[str, dict[str, dict]]:
        rows = await conn.fetch(
            """
            SELECT periodo, tipo, estatus, nombre_archivo, ruta_sharepoint, tipo_recibo
            FROM tb_cfe_descargas
            WHERE servicio_id = $1
            """,
            servicio_id,
        )
        resumen: dict[str, dict[str, dict]] = {}
        for row in rows:
            periodo = row["periodo"]
            resumen.setdefault(periodo, {})[row["tipo"]] = dict(row)
        return resumen

    async def tiene_busqueda_en_progreso(
        self, conn: asyncpg.Connection, servicio_id: UUID
    ) -> bool:
        row = await conn.fetchrow(
            """
            SELECT 1
            FROM tb_cfe_busquedas
            WHERE servicio_id = $1
              AND estatus IN ('pendiente','descargando')
            LIMIT 1
            """,
            servicio_id,
        )
        return row is not None

    async def crear_busqueda_periodos(
        self,
        conn: asyncpg.Connection,
        *,
        servicio_id: UUID,
        max_periodos: int,
        solicitado_por: UUID,
    ) -> dict:
        row = await conn.fetchrow(
            """
            INSERT INTO tb_cfe_busquedas (servicio_id, max_periodos, solicitado_por)
            VALUES ($1, $2, $3)
            RETURNING *
            """,
            servicio_id, max_periodos, solicitado_por,
        )
        return dict(row)

    async def get_busqueda_by_id(
        self, conn: asyncpg.Connection, busqueda_id: UUID, servicio_id: Optional[UUID] = None
    ) -> Optional[dict]:
        row = await conn.fetchrow(
            """
            SELECT b.*, s.numero_servicio, s.nombre, s.alias
            FROM tb_cfe_busquedas b
            JOIN tb_cfe_servicios s ON s.id = b.servicio_id
            WHERE b.id = $1
              AND ($2::uuid IS NULL OR b.servicio_id = $2)
            """,
            busqueda_id, servicio_id,
        )
        return dict(row) if row else None

    async def get_busqueda_activa_por_servicio(
        self, conn: asyncpg.Connection, servicio_id: UUID
    ) -> Optional[dict]:
        row = await conn.fetchrow(
            f"""
            SELECT b.*, s.numero_servicio, s.nombre, s.alias
            FROM tb_cfe_busquedas b
            JOIN tb_cfe_servicios s ON s.id = b.servicio_id
            WHERE b.servicio_id = $1{_BUSQUEDA_ACTIVA_FILTRO_ORDEN}
            """,
            servicio_id,
        )
        return dict(row) if row else None

    async def reclamar_busqueda_periodos(self, conn: asyncpg.Connection) -> Optional[dict]:
        row = await conn.fetchrow(
            """
            UPDATE tb_cfe_busquedas
            SET estatus = 'descargando', actualizado_en = now()
            WHERE id = (
                SELECT id FROM tb_cfe_busquedas
                WHERE estatus = 'pendiente'
                ORDER BY creado_en
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING *
            """
        )
        return dict(row) if row else None

    async def marcar_busqueda_error(
        self, conn: asyncpg.Connection, busqueda_id: UUID, mensaje: str
    ) -> None:
        await conn.execute(
            """
            UPDATE tb_cfe_busquedas
            SET estatus = 'error',
                mensaje_error = $2,
                actualizado_en = now()
            WHERE id = $1
            """,
            busqueda_id, mensaje,
        )

    async def finalizar_busqueda_periodos(
        self,
        conn: asyncpg.Connection,
        busqueda_id: UUID,
        *,
        total_detectados: int,
        total_descargados: int,
    ) -> None:
        await conn.execute(
            """
            UPDATE tb_cfe_busquedas
            SET estatus = 'completado',
                total_detectados = $2,
                total_descargados = $3,
                actualizado_en = now()
            WHERE id = $1
            """,
            busqueda_id, total_detectados, total_descargados,
        )

    async def upsert_busqueda_item(
        self,
        conn: asyncpg.Connection,
        *,
        busqueda_id: UUID,
        periodo: str,
        etiqueta_periodo: Optional[str],
        xml_estatus: str,
        pdf_estatus: str,
        xml_nombre_archivo: Optional[str] = None,
        pdf_nombre_archivo: Optional[str] = None,
        xml_staging_url: Optional[str] = None,
        pdf_staging_url: Optional[str] = None,
        xml_drive_item_id: Optional[str] = None,
        pdf_drive_item_id: Optional[str] = None,
        ya_descargado_xml: bool = False,
        ya_descargado_pdf: bool = False,
        error_mensaje: Optional[str] = None,
        decision: str = "pendiente",
    ) -> dict:
        row = await conn.fetchrow(
            """
            INSERT INTO tb_cfe_busqueda_items
                (busqueda_id, periodo, etiqueta_periodo, xml_estatus, pdf_estatus,
                 xml_nombre_archivo, pdf_nombre_archivo, xml_staging_url, pdf_staging_url,
                 xml_drive_item_id, pdf_drive_item_id, ya_descargado_xml, ya_descargado_pdf,
                 error_mensaje, decision)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
            ON CONFLICT (busqueda_id, periodo)
            DO UPDATE SET
                etiqueta_periodo = EXCLUDED.etiqueta_periodo,
                xml_estatus = EXCLUDED.xml_estatus,
                pdf_estatus = EXCLUDED.pdf_estatus,
                xml_nombre_archivo = EXCLUDED.xml_nombre_archivo,
                pdf_nombre_archivo = EXCLUDED.pdf_nombre_archivo,
                xml_staging_url = EXCLUDED.xml_staging_url,
                pdf_staging_url = EXCLUDED.pdf_staging_url,
                xml_drive_item_id = EXCLUDED.xml_drive_item_id,
                pdf_drive_item_id = EXCLUDED.pdf_drive_item_id,
                ya_descargado_xml = EXCLUDED.ya_descargado_xml,
                ya_descargado_pdf = EXCLUDED.ya_descargado_pdf,
                error_mensaje = EXCLUDED.error_mensaje,
                decision = EXCLUDED.decision,
                actualizado_en = now()
            RETURNING *
            """,
            busqueda_id, periodo, etiqueta_periodo, xml_estatus, pdf_estatus,
            xml_nombre_archivo, pdf_nombre_archivo, xml_staging_url, pdf_staging_url,
            xml_drive_item_id, pdf_drive_item_id, ya_descargado_xml, ya_descargado_pdf,
            error_mensaje, decision,
        )
        return dict(row)

    async def get_busqueda_items(
        self, conn: asyncpg.Connection, busqueda_id: UUID
    ) -> list[dict]:
        rows = await conn.fetch(
            """
            SELECT *
            FROM tb_cfe_busqueda_items
            WHERE busqueda_id = $1
            ORDER BY periodo DESC
            """,
            busqueda_id,
        )
        return [dict(r) for r in rows]

    async def marcar_item_decision(
        self, conn: asyncpg.Connection, item_id: UUID, decision: str
    ) -> None:
        await conn.execute(
            """
            UPDATE tb_cfe_busqueda_items
            SET decision = $2, actualizado_en = now()
            WHERE id = $1
            """,
            item_id, decision,
        )

    async def marcar_busqueda_confirmada(self, conn: asyncpg.Connection, busqueda_id: UUID) -> None:
        await conn.execute(
            """
            UPDATE tb_cfe_busquedas
            SET estatus = 'confirmado', actualizado_en = now()
            WHERE id = $1
            """,
            busqueda_id,
        )

    async def reclamar_busquedas_expiradas(self, conn: asyncpg.Connection, limite: int = 10) -> list[dict]:
        rows = await conn.fetch(
            """
            UPDATE tb_cfe_busquedas
            SET estatus = 'expirado', actualizado_en = now()
            WHERE id IN (
                SELECT id
                FROM tb_cfe_busquedas
                WHERE estatus IN ('completado', 'error')
                  AND expira_en < now()
                ORDER BY expira_en
                LIMIT $1
            )
            RETURNING *
            """,
            limite,
        )
        return [dict(r) for r in rows]

    async def limpiar_errores_invalidos(
        self, conn: asyncpg.Connection, servicio_id: Optional[UUID] = None
    ) -> int:
        result = await conn.execute(
            """
            WITH candidatos AS (
                SELECT d.id
                FROM tb_cfe_descargas d
                WHERE d.estatus = 'error'
                  AND ($1::uuid IS NULL OR d.servicio_id = $1)
                  AND (
                    d.periodo IN ('desconocido', '0000-33')
                    OR d.periodo !~ '^20[0-9]{2}-(0[1-9]|1[0-2])$'
                  )
                  AND EXISTS (
                    SELECT 1
                    FROM tb_cfe_descargas ok
                    WHERE ok.servicio_id = d.servicio_id
                      AND ok.tipo = 'xml'
                      AND ok.estatus = 'completado'
                      AND ok.periodo ~ '^20[0-9]{2}-(0[1-9]|1[0-2])$'
                  )
            )
            DELETE FROM tb_cfe_descargas d
            USING candidatos c
            WHERE d.id = c.id
            """,
            servicio_id,
        )
        return int(result.split()[-1]) if result else 0

    async def get_descarga_por_tipo(
        self, conn: asyncpg.Connection, servicio_id: UUID, periodo: str, tipo: str
    ) -> Optional[dict]:
        row = await conn.fetchrow(
            """
            SELECT * FROM tb_cfe_descargas
            WHERE servicio_id = $1 AND periodo = $2 AND tipo = $3
            """,
            servicio_id, periodo, tipo,
        )
        return dict(row) if row else None

    async def upsert_descarga(
        self, conn: asyncpg.Connection, *, servicio_id: UUID, periodo: str, tipo: str,
        estatus: str, nombre_archivo: Optional[str] = None,
        ruta_sharepoint: Optional[str] = None, error_mensaje: Optional[str] = None,
        descargado_por: Optional[UUID] = None, tipo_recibo: Optional[str] = None,
    ) -> dict:
        row = await conn.fetchrow(
            """
            INSERT INTO tb_cfe_descargas
                (servicio_id, periodo, tipo, estatus, nombre_archivo,
                 ruta_sharepoint, error_mensaje, descargado_por, tipo_recibo, descargado_en)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8,
                    NULLIF($9, ''),
                    CASE WHEN $4 = 'completado' THEN now() ELSE NULL END)
            ON CONFLICT (servicio_id, periodo, tipo)
            DO UPDATE SET
                estatus        = EXCLUDED.estatus,
                nombre_archivo = COALESCE(EXCLUDED.nombre_archivo, tb_cfe_descargas.nombre_archivo),
                ruta_sharepoint= COALESCE(EXCLUDED.ruta_sharepoint, tb_cfe_descargas.ruta_sharepoint),
                error_mensaje  = EXCLUDED.error_mensaje,
                descargado_por = COALESCE(EXCLUDED.descargado_por, tb_cfe_descargas.descargado_por),
                tipo_recibo    = COALESCE(EXCLUDED.tipo_recibo, tb_cfe_descargas.tipo_recibo),
                descargado_en  = CASE WHEN EXCLUDED.estatus = 'completado' THEN now()
                                      ELSE tb_cfe_descargas.descargado_en END
            RETURNING *
            """,
            servicio_id, periodo, tipo, estatus, nombre_archivo,
            ruta_sharepoint, error_mensaje, descargado_por, tipo_recibo,
        )
        return dict(row)

    async def tiene_descarga_en_progreso(
        self, conn: asyncpg.Connection, servicio_id: UUID
    ) -> bool:
        row = await conn.fetchrow(
            "SELECT 1 FROM tb_cfe_descargas WHERE servicio_id=$1 AND estatus IN ('pendiente','descargando') LIMIT 1",
            servicio_id,
        )
        return row is not None

    async def reclamar_trabajo(self, conn: asyncpg.Connection) -> Optional[dict]:
        row = await conn.fetchrow(
            """
            UPDATE tb_cfe_descargas SET estatus = 'descargando'
            WHERE id = (
                SELECT id FROM tb_cfe_descargas
                WHERE estatus = 'pendiente'
                ORDER BY creado_en
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING id, servicio_id, periodo, tipo, descargado_por
            """
        )
        return dict(row) if row else None

    async def marcar_descarga_error(
        self, conn: asyncpg.Connection, descarga_id: UUID, mensaje: str
    ) -> None:
        await conn.execute(
            """
            UPDATE tb_cfe_descargas SET estatus = 'error', error_mensaje = $2
            WHERE id = $1
            """,
            descarga_id, mensaje,
        )

    async def marcar_pendiente_error(
        self, conn: asyncpg.Connection, servicio_id: UUID, mensaje: str
    ) -> None:
        await conn.execute(
            """
            UPDATE tb_cfe_descargas SET estatus = 'error', error_mensaje = $2
            WHERE servicio_id = $1 AND periodo = 'pendiente'
            """,
            servicio_id, mensaje,
        )

    async def borrar_descarga_pendiente(self, conn: asyncpg.Connection, servicio_id: UUID) -> None:
        await conn.execute(
            "DELETE FROM tb_cfe_descargas WHERE servicio_id=$1 AND periodo='pendiente'",
            servicio_id,
        )

    async def reaper_descargando(self, conn: asyncpg.Connection, minutos: int = 15) -> int:
        result = await conn.execute(
            """
            UPDATE tb_cfe_descargas SET estatus = 'error',
                   error_mensaje = 'Descarga interrumpida (worker reiniciado o timeout).'
            WHERE estatus = 'descargando'
              AND creado_en < now() - make_interval(mins => $1)
            """,
            minutos,
        )
        return int(result.split()[-1]) if result else 0


def get_cfe_db_service() -> CfeDBService:
    return CfeDBService()
