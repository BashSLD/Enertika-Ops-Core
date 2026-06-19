# modules/cfe/db_service.py
from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

import asyncpg

from .constants import CFE_BUSQUEDA_TIMEOUT_MIN_SEGUNDOS, CFE_BUSQUEDA_TIMEOUT_SEGUNDOS_POR_PERIODO

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

    async def get_all_servicios(
        self, conn: asyncpg.Connection, modulos: list[str] | None = None
    ) -> list[dict]:
        rows = await conn.fetch(
            f"""
            SELECT s.id, s.numero_servicio, s.nombre, s.alias, s.lada, s.telefono,
                   s.email, s.activo, s.creado_en, s.modulos,
                   s.miespacio_estatus, s.miespacio_error,
                   COUNT(DISTINCT d.periodo) FILTER (
                       WHERE d.estatus = 'completado'
                         AND d.tipo = 'xml'
                         AND d.periodo <> 'pendiente'
                         AND d.ruta_sharepoint IS NOT NULL
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
              AND ($1::text[] IS NULL OR s.modulos && $1::text[])
            GROUP BY s.id, ba.id, ba.estatus, ba.max_periodos
            ORDER BY s.nombre
            """,
            modulos or None,
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
        modulos: list[str] | None = None,
    ) -> dict:
        row = await conn.fetchrow(
            """
            INSERT INTO tb_cfe_servicios
                (numero_servicio, nombre, alias, lada, telefono, email, creado_por, modulos)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING *
            """,
            numero_servicio, nombre, alias, lada, telefono, email, creado_por,
            modulos or ["oym"],
        )
        return dict(row)

    async def actualizar_servicio(
        self, conn: asyncpg.Connection, servicio_id: UUID, *,
        numero_servicio: str, nombre: str, alias: Optional[str],
    ) -> Optional[dict]:
        """Edita RPU/nombre/alias. Solo permitido si el servicio esta en estatus
        'error' (blindaje a nivel de query, independiente de la validacion en el
        service layer y de lo que muestre la UI)."""
        row = await conn.fetchrow(
            """
            UPDATE tb_cfe_servicios
            SET numero_servicio = $2, nombre = $3, alias = $4
            WHERE id = $1 AND miespacio_estatus = 'error'
            RETURNING *
            """,
            servicio_id, numero_servicio, nombre, alias,
        )
        return dict(row) if row else None

    async def agregar_modulo_a_servicio(
        self, conn: asyncpg.Connection, servicio_id: UUID, modulo: str
    ) -> dict:
        row = await conn.fetchrow(
            """
            UPDATE tb_cfe_servicios
            SET modulos = array_append(modulos, $2)
            WHERE id = $1 AND NOT ($2 = ANY(modulos))
            RETURNING *
            """,
            servicio_id, modulo,
        )
        return dict(row) if row else {}

    # ── Alta en MiEspacio (job del worker, independiente de la descarga) ──────

    async def marcar_alta_miespacio_pendiente(
        self, conn: asyncpg.Connection, servicio_id: UUID
    ) -> bool:
        """Encola el alta del servicio en MiEspacio. Idempotente: no reencola si ya
        esta registrado o en proceso. Devuelve True si quedo encolado."""
        row = await conn.fetchrow(
            """
            UPDATE tb_cfe_servicios
            SET miespacio_estatus = 'pendiente', miespacio_error = NULL
            WHERE id = $1
              AND miespacio_estatus NOT IN ('registrado', 'registrando', 'pendiente')
            RETURNING id
            """,
            servicio_id,
        )
        return row is not None

    async def reclamar_alta_miespacio(self, conn: asyncpg.Connection) -> Optional[dict]:
        """Reclama atomicamente un servicio pendiente de alta y lo pasa a 'registrando'.
        Sella miespacio_verificado_en como marca de inicio para que el reaper pueda
        rescatar altas colgadas (worker reiniciado a mitad)."""
        row = await conn.fetchrow(
            """
            UPDATE tb_cfe_servicios
            SET miespacio_estatus = 'registrando', miespacio_verificado_en = now()
            WHERE id = (
                SELECT id FROM tb_cfe_servicios
                WHERE miespacio_estatus = 'pendiente'
                ORDER BY creado_en
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING *
            """
        )
        return dict(row) if row else None

    async def reaper_alta_miespacio_colgada(self, conn: asyncpg.Connection, minutos: int = 15) -> int:
        """Devuelve a 'pendiente' las altas atascadas en 'registrando' (worker reiniciado
        o timeout) para que el siguiente ciclo las reintente."""
        result = await conn.execute(
            """
            UPDATE tb_cfe_servicios
            SET miespacio_estatus = 'pendiente'
            WHERE miespacio_estatus = 'registrando'
              AND miespacio_verificado_en < now() - make_interval(mins => $1)
            """,
            minutos,
        )
        return int(result.split()[-1]) if result else 0

    async def marcar_miespacio_estatus(
        self, conn: asyncpg.Connection, servicio_id: UUID, estatus: str,
        error: Optional[str] = None,
    ) -> None:
        await conn.execute(
            """
            UPDATE tb_cfe_servicios
            SET miespacio_estatus = $2,
                miespacio_error = $3,
                miespacio_verificado_en = CASE
                    WHEN $2 = 'registrado' THEN now()
                    ELSE miespacio_verificado_en
                END
            WHERE id = $1
            """,
            servicio_id, estatus, error,
        )

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
        advertencia: Optional[str] = None,
        total_disponible_publico: Optional[int] = None,
        total_disponible_miespacio: Optional[int] = None,
    ) -> None:
        await conn.execute(
            """
            UPDATE tb_cfe_busquedas
            SET estatus = 'completado',
                total_detectados = $2,
                total_descargados = $3,
                advertencia = $4,
                total_disponible_publico = $5,
                total_disponible_miespacio = $6,
                actualizado_en = now()
            WHERE id = $1
            """,
            busqueda_id, total_detectados, total_descargados, advertencia,
            total_disponible_publico, total_disponible_miespacio,
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
        tipo_recibo: Optional[str] = None,
    ) -> dict:
        row = await conn.fetchrow(
            """
            INSERT INTO tb_cfe_busqueda_items
                (busqueda_id, periodo, etiqueta_periodo, xml_estatus, pdf_estatus,
                 xml_nombre_archivo, pdf_nombre_archivo, xml_staging_url, pdf_staging_url,
                 xml_drive_item_id, pdf_drive_item_id, ya_descargado_xml, ya_descargado_pdf,
                 error_mensaje, decision, tipo_recibo)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15,
                    NULLIF($16, ''))
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
                tipo_recibo = COALESCE(EXCLUDED.tipo_recibo, tb_cfe_busqueda_items.tipo_recibo),
                actualizado_en = now()
            RETURNING *
            """,
            busqueda_id, periodo, etiqueta_periodo, xml_estatus, pdf_estatus,
            xml_nombre_archivo, pdf_nombre_archivo, xml_staging_url, pdf_staging_url,
            xml_drive_item_id, pdf_drive_item_id, ya_descargado_xml, ya_descargado_pdf,
            error_mensaje, decision, tipo_recibo,
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

    async def reaper_busqueda_colgada(self, conn: asyncpg.Connection, margen_minutos: int = 5) -> int:
        """Marca error las busquedas atascadas en 'descargando' (worker reiniciado
        a mitad, p.ej. por un deploy). El umbral espeja el asyncio.wait_for de
        _ejecutar_busqueda_periodos, para no cortar una busqueda larga que todavia
        esta legitimamente en curso."""
        result = await conn.execute(
            """
            UPDATE tb_cfe_busquedas
            SET estatus = 'error',
                mensaje_error = 'Busqueda interrumpida (worker reiniciado o timeout).',
                actualizado_en = now()
            WHERE estatus = 'descargando'
              AND actualizado_en < now() - (
                    make_interval(secs => GREATEST($2, max_periodos * $3))
                    + make_interval(mins => $1)
                  )
            """,
            margen_minutos, CFE_BUSQUEDA_TIMEOUT_MIN_SEGUNDOS, CFE_BUSQUEDA_TIMEOUT_SEGUNDOS_POR_PERIODO,
        )
        return int(result.split()[-1]) if result else 0


def get_cfe_db_service() -> CfeDBService:
    return CfeDBService()
