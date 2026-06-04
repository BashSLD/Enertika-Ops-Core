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
        SELECT fecha_laboral, estado
        FROM tb_asistencia_diaria
        WHERE usuario_id = $1
          AND fecha_laboral >= $2
          AND fecha_laboral <= $3
        """,
        usuario_id,
        fecha_inicio,
        fecha_fin,
    )
    return [dict(row) for row in rows]


async def get_mi_asistencia(
    conn,
    usuario_id: UUID,
    fecha_inicio: date,
    fecha_fin: date,
    limit: int = 15,
    offset: int = 0,
) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT
            ad.id,
            ad.fecha_laboral,
            ad.primera_entrada,
            ad.ultima_salida,
            ad.minutos_trabajados,
            ad.minutos_programados,
            ad.minutos_extra,
            ad.estado,
            ad.horas_extra_estado,
            ad.motivo_solicitud,
            s.nombre AS sucursal_nombre
        FROM tb_asistencia_diaria ad
        LEFT JOIN tb_cat_sucursales s ON s.id = ad.sucursal_id
        WHERE ad.usuario_id = $1
          AND ad.fecha_laboral >= $2
          AND ad.fecha_laboral <= $3
        ORDER BY ad.fecha_laboral DESC
        LIMIT $4 OFFSET $5
        """,
        usuario_id,
        fecha_inicio,
        fecha_fin,
        limit + 1,
        offset,
    )
    return [dict(row) for row in rows]
