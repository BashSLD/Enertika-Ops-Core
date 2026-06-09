# modules/cfe/db_service.py
from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

import asyncpg

logger = logging.getLogger("CfeDBService")


class CfeDBService:

    async def get_all_servicios(self, conn: asyncpg.Connection) -> list[dict]:
        rows = await conn.fetch(
            """
            SELECT s.id, s.numero_servicio, s.nombre, s.alias, s.lada, s.telefono,
                   s.email, s.activo, s.creado_en,
                   COUNT(d.id) FILTER (WHERE d.estatus = 'completado') AS total_descargas,
                   MAX(d.descargado_en) AS ultima_descarga,
                   BOOL_OR(d.estatus IN ('pendiente','descargando')) AS tiene_pendiente
            FROM tb_cfe_servicios s
            LEFT JOIN tb_cfe_descargas d ON d.servicio_id = s.id
            WHERE s.activo = true
            GROUP BY s.id
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

    async def upsert_descarga(
        self, conn: asyncpg.Connection, *, servicio_id: UUID, periodo: str, tipo: str,
        estatus: str, nombre_archivo: Optional[str] = None,
        ruta_sharepoint: Optional[str] = None, error_mensaje: Optional[str] = None,
        descargado_por: Optional[UUID] = None,
    ) -> dict:
        row = await conn.fetchrow(
            """
            INSERT INTO tb_cfe_descargas
                (servicio_id, periodo, tipo, estatus, nombre_archivo,
                 ruta_sharepoint, error_mensaje, descargado_por, descargado_en)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8,
                    CASE WHEN $4 = 'completado' THEN now() ELSE NULL END)
            ON CONFLICT (servicio_id, periodo, tipo)
            DO UPDATE SET
                estatus        = EXCLUDED.estatus,
                nombre_archivo = COALESCE(EXCLUDED.nombre_archivo, tb_cfe_descargas.nombre_archivo),
                ruta_sharepoint= COALESCE(EXCLUDED.ruta_sharepoint, tb_cfe_descargas.ruta_sharepoint),
                error_mensaje  = EXCLUDED.error_mensaje,
                descargado_por = COALESCE(EXCLUDED.descargado_por, tb_cfe_descargas.descargado_por),
                descargado_en  = CASE WHEN EXCLUDED.estatus = 'completado' THEN now()
                                      ELSE tb_cfe_descargas.descargado_en END
            RETURNING *
            """,
            servicio_id, periodo, tipo, estatus, nombre_archivo,
            ruta_sharepoint, error_mensaje, descargado_por,
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
            RETURNING servicio_id, descargado_por
            """
        )
        return dict(row) if row else None

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
