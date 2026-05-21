from __future__ import annotations

from datetime import date
from uuid import UUID


async def get_usuario_simple_by_id(conn, usuario_id: UUID) -> dict | None:
    row = await conn.fetchrow(
        "SELECT id_usuario, nombre, email, department, puesto FROM tb_usuarios WHERE id_usuario = $1",
        usuario_id,
    )
    return dict(row) if row else None


async def upsert_vacaciones_meses_expiracion(conn, meses_expiracion: int) -> None:
    await conn.execute(
        """
        INSERT INTO tb_configuracion_global (clave, valor, tipo_dato, descripcion)
        VALUES (
            'VACACIONES_MESES_EXPIRACION', $1::text, 'int',
            'Meses hasta que expira un periodo de vacaciones no utilizado'
        )
        ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor
        """,
        str(meses_expiracion),
    )


async def get_horarios_sucursal_admin(conn) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT
            h.id,
            h.sucursal_id,
            s.nombre AS sucursal_nombre,
            h.nombre,
            h.activo,
            h.margen_entrada_antes_min,
            h.margen_salida_despues_min,
            h.tolerancia_extra_min,
            h.descuento_comida_min,
            h.updated_at,
            d.dia_semana,
            d.hora_entrada,
            d.hora_salida,
            d.minutos_programados,
            d.cruza_medianoche,
            d.es_laboral,
            COALESCE(d.descuento_comida_min, h.descuento_comida_min, 0) AS dia_descuento_comida_min
        FROM tb_horarios_sucursal h
        JOIN tb_cat_sucursales s ON s.id = h.sucursal_id
        LEFT JOIN tb_horarios_sucursal_dias d ON d.horario_sucursal_id = h.id
        ORDER BY s.nombre, h.activo DESC, h.updated_at DESC, d.dia_semana
        """
    )
    return [dict(row) for row in rows]


async def get_sucursales_admin(conn) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT id, codigo, nombre, activa
        FROM tb_cat_sucursales
        ORDER BY activa DESC, nombre
        """
    )
    return [dict(row) for row in rows]


async def get_horario_sucursal(conn, horario_id: UUID) -> dict | None:
    row = await conn.fetchrow(
        """
        SELECT id, sucursal_id, nombre, activo
        FROM tb_horarios_sucursal
        WHERE id = $1
        """,
        horario_id,
    )
    return dict(row) if row else None


async def create_horario_sucursal(
    conn,
    *,
    sucursal_id: UUID,
    nombre: str,
    activo: bool,
    margen_entrada_antes_min: int,
    margen_salida_despues_min: int,
    tolerancia_extra_min: int,
    descuento_comida_min: int,
    updated_by: UUID,
) -> UUID:
    row = await conn.fetchrow(
        """
        INSERT INTO tb_horarios_sucursal (
            sucursal_id, nombre, activo, margen_entrada_antes_min,
            margen_salida_despues_min, tolerancia_extra_min, descuento_comida_min,
            updated_by
        )
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
        RETURNING id
        """,
        sucursal_id,
        nombre,
        activo,
        margen_entrada_antes_min,
        margen_salida_despues_min,
        tolerancia_extra_min,
        descuento_comida_min,
        updated_by,
    )
    return row["id"]


async def update_horario_sucursal(
    conn,
    *,
    horario_id: UUID,
    sucursal_id: UUID,
    nombre: str,
    activo: bool,
    margen_entrada_antes_min: int,
    margen_salida_despues_min: int,
    tolerancia_extra_min: int,
    descuento_comida_min: int,
    updated_by: UUID,
) -> dict | None:
    row = await conn.fetchrow(
        """
        UPDATE tb_horarios_sucursal
        SET sucursal_id = $2,
            nombre = $3,
            activo = $4,
            margen_entrada_antes_min = $5,
            margen_salida_despues_min = $6,
            tolerancia_extra_min = $7,
            descuento_comida_min = $8,
            updated_by = $9,
            updated_at = now()
        WHERE id = $1
        RETURNING id, sucursal_id
        """,
        horario_id,
        sucursal_id,
        nombre,
        activo,
        margen_entrada_antes_min,
        margen_salida_despues_min,
        tolerancia_extra_min,
        descuento_comida_min,
        updated_by,
    )
    return dict(row) if row else None


async def deactivate_horarios_sucursal(
    conn,
    *,
    sucursal_id: UUID,
    exclude_id: UUID | None = None,
) -> None:
    await conn.execute(
        """
        UPDATE tb_horarios_sucursal
        SET activo = false, updated_at = now()
        WHERE sucursal_id = $1
          AND activo = true
          AND ($2::uuid IS NULL OR id <> $2)
        """,
        sucursal_id,
        exclude_id,
    )


async def deactivate_horario_sucursal(conn, horario_id: UUID, updated_by: UUID) -> dict | None:
    row = await conn.fetchrow(
        """
        UPDATE tb_horarios_sucursal
        SET activo = false,
            updated_by = $2,
            updated_at = now()
        WHERE id = $1
        RETURNING id, sucursal_id
        """,
        horario_id,
        updated_by,
    )
    return dict(row) if row else None


async def replace_horario_sucursal_dias(conn, horario_id: UUID, dias: list[dict]) -> None:
    await conn.execute(
        "DELETE FROM tb_horarios_sucursal_dias WHERE horario_sucursal_id = $1",
        horario_id,
    )
    await conn.executemany(
        """
        INSERT INTO tb_horarios_sucursal_dias (
            horario_sucursal_id, dia_semana, hora_entrada, hora_salida,
            minutos_programados, cruza_medianoche, es_laboral, descuento_comida_min
        )
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
        """,
        [
            (
                horario_id,
                dia["dia_semana"],
                dia["hora_entrada"],
                dia["hora_salida"],
                dia["minutos_programados"],
                dia["cruza_medianoche"],
                dia["es_laboral"],
                dia["descuento_comida_min"],
            )
            for dia in dias
        ],
    )


async def get_usuarios_asistencia_por_sucursal(conn, sucursal_id: UUID) -> list[UUID]:
    rows = await conn.fetch(
        """
        SELECT DISTINCT u.id_usuario
        FROM tb_usuarios u
        LEFT JOIN tb_empleados_datos ed ON ed.usuario_id = u.id_usuario
        LEFT JOIN tb_biotime_empleado_map m ON m.usuario_id = u.id_usuario AND m.activo = true
        WHERE u.is_active = true
          AND COALESCE(m.sucursal_id, ed.sucursal_id) = $1
          AND (ed.biotime_emp_code IS NOT NULL OR ed.numero_empleado IS NOT NULL OR m.id IS NOT NULL)
        """,
        sucursal_id,
    )
    return [row["id_usuario"] for row in rows]


async def get_usuarios_asistencia_por_sucursales(conn, sucursal_ids: list[UUID]) -> list[UUID]:
    if not sucursal_ids:
        return []
    rows = await conn.fetch(
        """
        SELECT DISTINCT u.id_usuario
        FROM tb_usuarios u
        LEFT JOIN tb_empleados_datos ed ON ed.usuario_id = u.id_usuario
        LEFT JOIN tb_biotime_empleado_map m ON m.usuario_id = u.id_usuario AND m.activo = true
        WHERE u.is_active = true
          AND COALESCE(m.sucursal_id, ed.sucursal_id) = ANY($1::uuid[])
          AND (ed.biotime_emp_code IS NOT NULL OR ed.numero_empleado IS NOT NULL OR m.id IS NOT NULL)
        """,
        sucursal_ids,
    )
    return [row["id_usuario"] for row in rows]


async def get_reporte_vacaciones(
    conn,
    *,
    fecha_inicio: date,
    fecha_fin: date,
    usuario_ids: list[UUID] | None = None,
    estado: str | None = None,
    incluir_dados_de_baja: bool = False,
) -> list[dict]:
    uids = usuario_ids or []
    rows = await conn.fetch(
        """
        SELECT
            sa.id,
            sa.fecha_inicio,
            sa.fecha_fin,
            sa.fecha_presentarse,
            sa.dias_solicitados,
            sa.estado,
            sa.fecha_solicitud,
            sa.fecha_resolucion,
            ta.nombre AS tipo_nombre,
            u.id_usuario,
            u.nombre AS empleado_nombre,
            u.email AS empleado_email,
            ed.numero_empleado,
            COALESCE(ed.departamento, u.department) AS departamento,
            aprobador.nombre AS aprobado_por_nombre
        FROM tb_solicitudes_ausencia sa
        JOIN tb_cat_tipos_ausencia ta ON ta.id = sa.tipo_ausencia_id
        JOIN tb_usuarios u ON u.id_usuario = sa.usuario_id
        LEFT JOIN tb_empleados_datos ed ON ed.usuario_id = u.id_usuario
        LEFT JOIN tb_usuarios aprobador ON aprobador.id_usuario = sa.aprobado_por
        WHERE ta.slug = 'vacaciones'
          AND COALESCE(sa.es_migracion, false) = false
          AND sa.fecha_inicio <= $2
          AND sa.fecha_fin >= $1
          AND (cardinality($3::uuid[]) = 0 OR sa.usuario_id = ANY($3))
          AND ($4::text IS NULL OR sa.estado = $4)
          AND ($5::bool = true OR u.is_active = true)
        ORDER BY sa.fecha_inicio DESC, u.nombre
        """,
        fecha_inicio,
        fecha_fin,
        uids,
        estado,
        incluir_dados_de_baja,
    )
    return [dict(row) for row in rows]
