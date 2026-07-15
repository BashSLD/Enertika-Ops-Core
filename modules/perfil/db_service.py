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
