"""Consultas SQL puras del reporte de clientes/empresas de Comercial.

Grano: una solicitud/oportunidad enviada (`id_oportunidad`). Por defecto, el
resumen general incluye clientes canonicos (`tb_clientes`) aun con total cero
(para detectar clientes inactivos), mas un grupo separado para oportunidades
historicas sin `cliente_id` (legacy, sin fusion por nombre). Con
`solo_activos=True` se omiten los clientes canonicos sin solicitudes en el
rango filtrado. El modo enfocado expande a sitio/proyecto para un solo
cliente.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

import asyncpg

def _filtros_oportunidad_sql(start: int) -> str:
    """Filtros opcionales de tipo/tecnologia/estatus/fecha, parametrizados desde `start`."""
    p_tipo, p_tec, p_estatus, p_inicio, p_fin = range(start, start + 5)
    return f"""
      AND (${p_tipo}::int IS NULL OR o.id_tipo_solicitud = ${p_tipo})
      AND (${p_tec}::int IS NULL OR o.id_tecnologia = ${p_tec})
      AND (${p_estatus}::int IS NULL OR o.id_estatus_global = ${p_estatus})
      AND (${p_inicio}::timestamptz IS NULL OR o.fecha_solicitud >= ${p_inicio})
      AND (${p_fin}::timestamptz IS NULL OR o.fecha_solicitud < ${p_fin})
"""


_FILTROS_OPORTUNIDAD = _filtros_oportunidad_sql(1)


def _legacy_grupo_id_expr(columna: str) -> str:
    """Clave estable de grupo legacy: 'legacy:<nombre_normalizado>' o 'legacy:sin_nombre'."""
    return f"'legacy:' || COALESCE(NULLIF(lower(btrim({columna})), ''), 'sin_nombre')"


async def contar_oportunidades_filtradas(
    conn: asyncpg.Connection,
    *,
    filtro_tipo_id: Optional[int],
    filtro_tecnologia_id: Optional[int],
    filtro_estatus_id: Optional[int],
    fecha_inicio_mx: Optional[datetime],
    fecha_fin_mx_exclusive: Optional[datetime],
    filtro_cliente_id: Optional[UUID] = None,
) -> int:
    """Cuenta oportunidades enviadas que cumplen los filtros (general o por cliente)."""
    total = await conn.fetchval(
        f"""
        SELECT COUNT(*)
        FROM tb_oportunidades o
        WHERE o.email_enviado = true
          AND ($6::uuid IS NULL OR o.cliente_id = $6)
          {_FILTROS_OPORTUNIDAD}
        """,
        filtro_tipo_id,
        filtro_tecnologia_id,
        filtro_estatus_id,
        fecha_inicio_mx,
        fecha_fin_mx_exclusive,
        filtro_cliente_id,
    )
    return int(total or 0)


def _clausula_clientes_activos(solo_activos: bool) -> str:
    """Fragmento opcional: exige que el cliente tenga al menos una oportunidad
    que cumpla `_FILTROS_OPORTUNIDAD`. Vacio cuando no se pide filtrar."""
    if not solo_activos:
        return ""
    return f"""
              AND EXISTS (
                  SELECT 1 FROM tb_oportunidades o
                  WHERE o.cliente_id = c.id
                    AND o.email_enviado = true
                    {_FILTROS_OPORTUNIDAD}
              )
"""


async def contar_filas_resumen_general(
    conn: asyncpg.Connection,
    *,
    filtro_tipo_id: Optional[int],
    filtro_tecnologia_id: Optional[int],
    filtro_estatus_id: Optional[int],
    fecha_inicio_mx: Optional[datetime],
    fecha_fin_mx_exclusive: Optional[datetime],
    solo_activos: bool = False,
) -> int:
    """Cuenta filas de resumen: clientes canonicos (todos, o solo con actividad en el
    rango si `solo_activos`) + grupos legacy filtrados."""
    total = await conn.fetchval(
        f"""
        SELECT
            (
                SELECT COUNT(*) FROM tb_clientes c
                WHERE true
                  {_clausula_clientes_activos(solo_activos)}
            )
            + (
                SELECT COUNT(DISTINCT {_legacy_grupo_id_expr('o.cliente_nombre')})
                FROM tb_oportunidades o
                WHERE o.email_enviado = true
                  AND o.cliente_id IS NULL
                  {_FILTROS_OPORTUNIDAD}
            )
        """,
        filtro_tipo_id,
        filtro_tecnologia_id,
        filtro_estatus_id,
        fecha_inicio_mx,
        fecha_fin_mx_exclusive,
    )
    return int(total or 0)


async def obtener_resumen_clientes(
    conn: asyncpg.Connection,
    *,
    filtro_tipo_id: Optional[int],
    filtro_tecnologia_id: Optional[int],
    filtro_estatus_id: Optional[int],
    fecha_inicio_mx: Optional[datetime],
    fecha_fin_mx_exclusive: Optional[datetime],
    solo_activos: bool = False,
) -> list[dict]:
    """Resumen general: una fila por cliente canonico o grupo legacy, con desglose de estatus.
    Con `solo_activos`, se omiten los clientes canonicos con total_solicitudes en cero."""
    clausula_activos = "WHERE t.total_solicitudes > 0" if solo_activos else ""
    rows = await conn.fetch(
        f"""
        WITH oportunidades_filtradas AS (
            SELECT
                o.id_oportunidad,
                o.cliente_id,
                o.cliente_nombre AS cliente_nombre_raw,
                o.id_estatus_global
            FROM tb_oportunidades o
            WHERE o.email_enviado = true
              {_FILTROS_OPORTUNIDAD}
        ),
        legacy_labels AS (
            SELECT
                {_legacy_grupo_id_expr('f.cliente_nombre_raw')} AS grupo_id,
                MIN(NULLIF(btrim(f.cliente_nombre_raw), '')) AS nombre_min
            FROM oportunidades_filtradas f
            WHERE f.cliente_id IS NULL
            GROUP BY 1
        ),
        resumen_base AS (
            SELECT
                c.id::text AS grupo_id,
                c.nombre_fiscal AS cliente_nombre,
                f.id_oportunidad,
                COALESCE(est.nombre, 'Sin estatus') AS estatus_nombre,
                COALESCE(est.id, -1) AS estatus_orden_id
            FROM tb_clientes c
            LEFT JOIN oportunidades_filtradas f ON f.cliente_id = c.id
            LEFT JOIN tb_cat_estatus_oportunidades est ON est.id = f.id_estatus_global

            UNION ALL

            SELECT
                ll.grupo_id,
                'Registro histórico sin vincular — ' || COALESCE(ll.nombre_min, 'Sin nombre') AS cliente_nombre,
                f.id_oportunidad,
                COALESCE(est.nombre, 'Sin estatus') AS estatus_nombre,
                COALESCE(est.id, -1) AS estatus_orden_id
            FROM oportunidades_filtradas f
            JOIN legacy_labels ll
                ON ll.grupo_id = {_legacy_grupo_id_expr('f.cliente_nombre_raw')}
            LEFT JOIN tb_cat_estatus_oportunidades est ON est.id = f.id_estatus_global
            WHERE f.cliente_id IS NULL
        ),
        estatus_counts AS (
            SELECT grupo_id, cliente_nombre, estatus_nombre, estatus_orden_id, COUNT(id_oportunidad) AS cnt
            FROM resumen_base
            WHERE id_oportunidad IS NOT NULL
            GROUP BY grupo_id, cliente_nombre, estatus_nombre, estatus_orden_id
        ),
        totales AS (
            SELECT grupo_id, cliente_nombre, COUNT(id_oportunidad) AS total_solicitudes
            FROM resumen_base
            GROUP BY grupo_id, cliente_nombre
        )
        SELECT
            t.grupo_id,
            t.cliente_nombre,
            t.total_solicitudes,
            COALESCE(
                string_agg(ec.estatus_nombre || ': ' || ec.cnt, ' | ' ORDER BY ec.estatus_nombre, ec.estatus_orden_id),
                ''
            ) AS desglose_estatus
        FROM totales t
        LEFT JOIN estatus_counts ec ON ec.grupo_id = t.grupo_id AND ec.cliente_nombre = t.cliente_nombre
        {clausula_activos}
        GROUP BY t.grupo_id, t.cliente_nombre, t.total_solicitudes
        ORDER BY t.cliente_nombre
        """,
        filtro_tipo_id,
        filtro_tecnologia_id,
        filtro_estatus_id,
        fecha_inicio_mx,
        fecha_fin_mx_exclusive,
    )
    return [dict(r) for r in rows]


async def obtener_detalle_general(
    conn: asyncpg.Connection,
    *,
    filtro_tipo_id: Optional[int],
    filtro_tecnologia_id: Optional[int],
    filtro_estatus_id: Optional[int],
    fecha_inicio_mx: Optional[datetime],
    fecha_fin_mx_exclusive: Optional[datetime],
) -> list[dict]:
    """Detalle general: una fila por oportunidad enviada, con la fase de proyecto mas reciente."""
    # proyecto_reciente escanea tb_proyectos_gate completa (sin WHERE), a diferencia de
    # _DETALLE_POR_CLIENTE_EXPANSION que sí la une contra oportunidades_filtradas desde el
    # join. Intencional por simplicidad mientras la tabla sea chica (~2 filas en PROD a
    # 2026-07); si crece de forma relevante, acotar con
    # "WHERE p.id_oportunidad IN (SELECT id_oportunidad FROM oportunidades_filtradas)".
    rows = await conn.fetch(
        f"""
        WITH oportunidades_filtradas AS (
            SELECT
                o.id_oportunidad,
                o.op_id_estandar,
                o.cliente_id,
                o.cliente_nombre AS cliente_nombre_raw,
                o.fecha_solicitud,
                o.id_estatus_global
            FROM tb_oportunidades o
            WHERE o.email_enviado = true
              {_FILTROS_OPORTUNIDAD}
        ),
        legacy_labels AS (
            SELECT
                {_legacy_grupo_id_expr('f.cliente_nombre_raw')} AS grupo_id,
                MIN(NULLIF(btrim(f.cliente_nombre_raw), '')) AS nombre_min
            FROM oportunidades_filtradas f
            WHERE f.cliente_id IS NULL
            GROUP BY 1
        ),
        proyecto_reciente AS (
            SELECT DISTINCT ON (p.id_oportunidad)
                p.id_oportunidad,
                p.area_actual
            FROM tb_proyectos_gate p
            ORDER BY p.id_oportunidad, p.fecha_inicio_area DESC NULLS LAST, p.created_at DESC NULLS LAST, p.id_proyecto
        )
        SELECT
            COALESCE(
                c.nombre_fiscal,
                'Registro histórico sin vincular — ' || COALESCE(ll.nombre_min, 'Sin nombre')
            ) AS cliente_nombre,
            f.op_id_estandar AS folio,
            f.fecha_solicitud,
            COALESCE(est.nombre, 'Sin estatus') AS estatus_nombre,
            COALESCE(pr.area_actual, 'N/A') AS fase_proyecto
        FROM oportunidades_filtradas f
        LEFT JOIN tb_clientes c ON c.id = f.cliente_id
        LEFT JOIN legacy_labels ll
            ON f.cliente_id IS NULL
            AND ll.grupo_id = {_legacy_grupo_id_expr('f.cliente_nombre_raw')}
        LEFT JOIN tb_cat_estatus_oportunidades est ON est.id = f.id_estatus_global
        LEFT JOIN proyecto_reciente pr ON pr.id_oportunidad = f.id_oportunidad
        ORDER BY cliente_nombre, f.fecha_solicitud DESC
        """,
        filtro_tipo_id,
        filtro_tecnologia_id,
        filtro_estatus_id,
        fecha_inicio_mx,
        fecha_fin_mx_exclusive,
    )
    return [dict(r) for r in rows]


async def obtener_etiquetas_filtros(
    conn: asyncpg.Connection,
    *,
    filtro_tipo_id: Optional[int],
    filtro_tecnologia_id: Optional[int],
    filtro_estatus_id: Optional[int],
    filtro_cliente_id: Optional[UUID],
) -> dict:
    """Nombres de catalogo para armar el resumen de filtros del PDF (un solo round-trip)."""
    row = await conn.fetchrow(
        """
        SELECT
            (SELECT nombre FROM tb_cat_tipos_solicitud WHERE id = $1) AS tipo_nombre,
            (SELECT nombre FROM tb_cat_tecnologias WHERE id = $2) AS tecnologia_nombre,
            (SELECT nombre FROM tb_cat_estatus_oportunidades WHERE id = $3) AS estatus_nombre,
            (SELECT nombre_fiscal FROM tb_clientes WHERE id = $4) AS cliente_nombre
        """,
        filtro_tipo_id,
        filtro_tecnologia_id,
        filtro_estatus_id,
        filtro_cliente_id,
    )
    return dict(row)


async def obtener_nombre_cliente(conn: asyncpg.Connection, cliente_id: UUID) -> Optional[str]:
    """Nombre fiscal del cliente, para identificar el archivo/hoja del modo enfocado."""
    return await conn.fetchval("SELECT nombre_fiscal FROM tb_clientes WHERE id = $1", cliente_id)


_DETALLE_POR_CLIENTE_EXPANSION = """
        detalle_expandido AS (
            SELECT
                f.op_id_estandar, f.fecha_solicitud, f.id_estatus_global,
                s.direccion AS sitio_direccion, s.nombre_sitio,
                p.proyecto_id_estandar, p.area_actual
            FROM oportunidades_filtradas f
            JOIN tb_sitios_oportunidad s ON s.id_oportunidad = f.id_oportunidad
            LEFT JOIN tb_proyectos_gate p ON p.id_sitio = s.id_sitio AND p.id_oportunidad = f.id_oportunidad

            UNION ALL

            SELECT
                f.op_id_estandar, f.fecha_solicitud, f.id_estatus_global,
                NULL::text AS sitio_direccion, NULL::text AS nombre_sitio,
                p.proyecto_id_estandar, p.area_actual
            FROM oportunidades_filtradas f
            JOIN tb_proyectos_gate p ON p.id_oportunidad = f.id_oportunidad
            WHERE NOT EXISTS (
                SELECT 1 FROM tb_sitios_oportunidad s2
                WHERE s2.id_oportunidad = p.id_oportunidad AND s2.id_sitio = p.id_sitio
            )

            UNION ALL

            SELECT
                f.op_id_estandar, f.fecha_solicitud, f.id_estatus_global,
                NULL::text, NULL::text,
                NULL::text, NULL::text
            FROM oportunidades_filtradas f
            WHERE NOT EXISTS (SELECT 1 FROM tb_sitios_oportunidad s3 WHERE s3.id_oportunidad = f.id_oportunidad)
              AND NOT EXISTS (SELECT 1 FROM tb_proyectos_gate p3 WHERE p3.id_oportunidad = f.id_oportunidad)
        )
"""


# $1 = cliente_id; los filtros opcionales de tipo/tecnologia/estatus/fecha ocupan $2..$6
_OPORTUNIDADES_FILTRADAS_POR_CLIENTE_CTE = f"""
        oportunidades_filtradas AS (
            SELECT o.id_oportunidad, o.op_id_estandar, o.fecha_solicitud, o.id_estatus_global
            FROM tb_oportunidades o
            WHERE o.email_enviado = true
              AND o.cliente_id = $1
              {_filtros_oportunidad_sql(2)}
        ),
    """


async def obtener_detalle_por_cliente(
    conn: asyncpg.Connection,
    *,
    filtro_cliente_id: UUID,
    filtro_tipo_id: Optional[int],
    filtro_tecnologia_id: Optional[int],
    filtro_estatus_id: Optional[int],
    fecha_inicio_mx: Optional[datetime],
    fecha_fin_mx_exclusive: Optional[datetime],
) -> list[dict]:
    """Detalle enfocado: una fila por sitio+proyecto (o N/A) de las solicitudes de un cliente."""
    rows = await conn.fetch(
        f"""
        WITH {_OPORTUNIDADES_FILTRADAS_POR_CLIENTE_CTE}
        {_DETALLE_POR_CLIENTE_EXPANSION}
        SELECT
            d.op_id_estandar AS folio,
            d.fecha_solicitud,
            COALESCE(est.nombre, 'Sin estatus') AS estatus_nombre,
            COALESCE(d.sitio_direccion, 'N/A') AS sitio_direccion,
            COALESCE(d.nombre_sitio, 'N/A') AS sitio_nombre,
            COALESCE(d.proyecto_id_estandar, 'N/A') AS proyecto_id_estandar,
            COALESCE(d.area_actual, 'N/A') AS fase_proyecto
        FROM detalle_expandido d
        LEFT JOIN tb_cat_estatus_oportunidades est ON est.id = d.id_estatus_global
        ORDER BY d.fecha_solicitud DESC, d.op_id_estandar, d.nombre_sitio NULLS LAST
        """,
        filtro_cliente_id,
        filtro_tipo_id,
        filtro_tecnologia_id,
        filtro_estatus_id,
        fecha_inicio_mx,
        fecha_fin_mx_exclusive,
    )
    return [dict(r) for r in rows]
