from __future__ import annotations

from datetime import date
from typing import Optional
from uuid import UUID


async def get_perfil_usuario(conn, usuario_id: UUID) -> Optional[dict]:
    row = await conn.fetchrow(
        """
        SELECT id_usuario, nombre, email, department, puesto
        FROM tb_usuarios
        WHERE id_usuario = $1
        """,
        usuario_id,
    )
    return dict(row) if row else None


async def get_mi_asistencia_heatmap(
    conn,
    usuario_id: UUID,
    fecha_inicio: date,
    fecha_fin: date,
) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT ad.fecha_laboral, ad.estado, ta.nombre AS tipo_ausencia_nombre
        FROM tb_asistencia_diaria ad
        LEFT JOIN tb_solicitudes_ausencia sa ON sa.id = ad.solicitud_ausencia_id
        LEFT JOIN tb_cat_tipos_ausencia ta ON ta.id = sa.tipo_ausencia_id
        WHERE ad.usuario_id = $1
          AND ad.fecha_laboral >= $2
          AND ad.fecha_laboral <= $3
        """,
        usuario_id,
        fecha_inicio,
        fecha_fin,
    )
    return [dict(row) for row in rows]


_ASISTENCIA_ROW_SELECT = """
    SELECT
        ad.id,
        ad.usuario_id,
        ad.fecha_laboral,
        ad.primera_entrada,
        ad.ultima_salida,
        ad.minutos_trabajados,
        ad.minutos_programados,
        ad.minutos_extra,
        ad.estado,
        ad.tiene_ausencia_justificada,
        ad.horas_extra_estado,
        ad.minutos_he_compensatorio,
        ad.he_compensatorio_solicitud_id,
        ad.motivo_solicitud,
        ta.nombre AS tipo_ausencia_nombre,
        ta.abreviatura AS tipo_ausencia_abreviatura,
        ta.slug AS tipo_ausencia_slug,
        s.nombre AS sucursal_nombre
    FROM tb_asistencia_diaria ad
    LEFT JOIN tb_solicitudes_ausencia sa ON sa.id = ad.solicitud_ausencia_id
    LEFT JOIN tb_cat_tipos_ausencia ta ON ta.id = sa.tipo_ausencia_id
    LEFT JOIN tb_cat_sucursales s ON s.id = ad.sucursal_id
    {where}
"""


async def get_mi_asistencia(
    conn,
    usuario_id: UUID,
    fecha_inicio: date,
    fecha_fin: date,
    limit: int = 15,
    offset: int = 0,
) -> list[dict]:
    rows = await conn.fetch(
        _ASISTENCIA_ROW_SELECT.format(
            where="""
            WHERE ad.usuario_id = $1
              AND ad.fecha_laboral >= $2
              AND ad.fecha_laboral <= $3
            ORDER BY ad.fecha_laboral DESC
            LIMIT $4 OFFSET $5
            """
        ),
        usuario_id,
        fecha_inicio,
        fecha_fin,
        limit + 1,
        offset,
    )
    return [dict(row) for row in rows]


async def get_asistencia_row_por_id(conn, asistencia_id: UUID) -> Optional[dict]:
    row = await conn.fetchrow(
        _ASISTENCIA_ROW_SELECT.format(where="WHERE ad.id = $1"),
        asistencia_id,
    )
    return dict(row) if row else None


# ─────────────────────────────────────────────
# Equipo fuera de oficina (widget colaborativo)
# ─────────────────────────────────────────────

_EQUIPO_FUERA_OFICINA_SQL = """
    WITH RECURSIVE eventos AS (
        SELECT
            sa.usuario_id,
            u.nombre AS nombre_persona,
            'ausencia' AS origen,
            ta.nombre AS tipo_nombre,
            ta.slug AS tipo_slug,
            sa.fecha_inicio,
            sa.fecha_fin,
            sa.fecha_presentarse,
            sa.hora_llegada,
            sa.hora_salida
        FROM tb_solicitudes_ausencia sa
        JOIN tb_usuarios u ON u.id_usuario = sa.usuario_id AND u.is_active = true
        JOIN tb_cat_tipos_ausencia ta ON ta.id = sa.tipo_ausencia_id
        WHERE sa.estado = 'aprobado'
          AND COALESCE(sa.es_migracion, false) = false
          AND sa.fecha_inicio <= $2
          AND sa.fecha_fin >= $1

        UNION ALL

        SELECT
            hc.usuario_id,
            u.nombre AS nombre_persona,
            'compensatorio' AS origen,
            'Permiso con goce de sueldo' AS tipo_nombre,
            'compensatorio' AS tipo_slug,
            hc.fecha_descanso AS fecha_inicio,
            hc.fecha_descanso AS fecha_fin,
            hc.fecha_descanso AS fecha_presentarse,
            NULL::time AS hora_llegada,
            NULL::time AS hora_salida
        FROM tb_he_solicitudes_compensatorio hc
        JOIN tb_usuarios u ON u.id_usuario = hc.usuario_id AND u.is_active = true
        WHERE hc.estatus = 'aprobado'
          AND hc.fecha_descanso BETWEEN $1 AND $2
    ),
    candidatos AS (
        SELECT DISTINCT e.usuario_id AS empleado_id, ej.jefe_id
        FROM eventos e
        JOIN tb_empleados_jefes ej ON ej.empleado_id = e.usuario_id
        JOIN tb_usuarios uj ON uj.id_usuario = ej.jefe_id AND uj.is_active = true
        WHERE ej.jefe_id != e.usuario_id
    ),
    -- Con un solo jefe directo activo no hay nada que excluir; el recorrido de
    -- ancestros solo se arma para empleados con mas de un candidato.
    multi_jefe AS (
        SELECT empleado_id FROM candidatos GROUP BY empleado_id HAVING COUNT(*) > 1
    ),
    -- Recorre hacia arriba la cadena de jefes de cada candidato (camino de UUIDs
    -- para detectar ciclos) y asA permite excluir al candidato que resulte ser
    -- jefe directo/indirecto de otro candidato del mismo empleado.
    ancestros AS (
        SELECT
            c.empleado_id,
            c.jefe_id AS candidato_id,
            c.jefe_id AS ancestro_id,
            ARRAY[c.jefe_id] AS camino,
            false AS ciclo
        FROM candidatos c
        JOIN multi_jefe mj ON mj.empleado_id = c.empleado_id

        UNION ALL

        SELECT
            a.empleado_id,
            a.candidato_id,
            ej.jefe_id AS ancestro_id,
            a.camino || ej.jefe_id,
            ej.jefe_id = ANY(a.camino)
        FROM ancestros a
        JOIN tb_empleados_jefes ej ON ej.empleado_id = a.ancestro_id
        WHERE NOT a.ciclo
    ),
    excluidos AS (
        SELECT DISTINCT a.empleado_id, a.ancestro_id AS candidato_excluido
        FROM ancestros a
        WHERE a.ancestro_id != a.candidato_id
          AND EXISTS (
              SELECT 1 FROM candidatos c2
              WHERE c2.empleado_id = a.empleado_id AND c2.jefe_id = a.ancestro_id
          )
          AND NOT EXISTS (
              SELECT 1 FROM ancestros a2
              WHERE a2.empleado_id = a.empleado_id AND a2.ciclo
          )
    ),
    responsables_agg AS (
        SELECT c.empleado_id,
               array_agg(u.nombre ORDER BY u.nombre, c.jefe_id) AS responsables_nombres
        FROM candidatos c
        JOIN tb_usuarios u ON u.id_usuario = c.jefe_id
        WHERE NOT EXISTS (
            SELECT 1 FROM excluidos ex
            WHERE ex.empleado_id = c.empleado_id AND ex.candidato_excluido = c.jefe_id
        )
        GROUP BY c.empleado_id
    )
    SELECT
        e.usuario_id,
        e.nombre_persona,
        e.origen,
        e.tipo_nombre,
        e.tipo_slug,
        e.fecha_inicio,
        e.fecha_fin,
        e.fecha_presentarse,
        e.hora_llegada,
        e.hora_salida,
        COALESCE(ra.responsables_nombres, ARRAY[]::text[]) AS responsables_nombres
    FROM eventos e
    LEFT JOIN responsables_agg ra ON ra.empleado_id = e.usuario_id
    ORDER BY e.fecha_inicio, e.nombre_persona
"""


async def get_equipo_fuera_oficina(conn, fecha_inicio: date, fecha_fin: date) -> list[dict]:
    rows = await conn.fetch(_EQUIPO_FUERA_OFICINA_SQL, fecha_inicio, fecha_fin)
    return [dict(row) for row in rows]
