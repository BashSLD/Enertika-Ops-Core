from __future__ import annotations

import json
from datetime import date, datetime
from uuid import UUID


async def get_last_transaction_id(conn) -> int | None:
    return await conn.fetchval(
        """
        SELECT MAX(biotime_transaction_id)
        FROM tb_biotime_checks
        WHERE biotime_transaction_id IS NOT NULL
        """
    )


async def create_sync_run(
    conn,
    *,
    from_transaction_id: int | None,
    window_start: datetime,
    window_end: datetime,
) -> UUID:
    row = await conn.fetchrow(
        """
        INSERT INTO tb_asistencia_sync_runs
            (from_transaction_id, window_start, window_end)
        VALUES ($1, $2, $3)
        RETURNING id
        """,
        from_transaction_id,
        window_start,
        window_end,
    )
    return row["id"]


async def finish_sync_run(
    conn,
    *,
    run_id: UUID,
    status: str,
    to_transaction_id: int | None = None,
    records_read: int = 0,
    records_inserted: int = 0,
    records_skipped: int = 0,
    error_message: str | None = None,
) -> None:
    await conn.execute(
        """
        UPDATE tb_asistencia_sync_runs
        SET finished_at = now(),
            status = $2,
            to_transaction_id = $3,
            records_read = $4,
            records_inserted = $5,
            records_skipped = $6,
            error_message = $7
        WHERE id = $1
        """,
        run_id,
        status,
        to_transaction_id,
        records_read,
        records_inserted,
        records_skipped,
        error_message,
    )


async def get_employee_map(conn, emp_codes: list[str]) -> dict[str, dict]:
    if not emp_codes:
        return {}
    rows = await conn.fetch(
        """
        WITH codes AS (
            SELECT DISTINCT unnest($1::text[]) AS code
        )
        SELECT
            c.code,
            COALESCE(m.usuario_id, ed.usuario_id) AS usuario_id,
            COALESCE(m.sucursal_id, ed.sucursal_id) AS sucursal_id
        FROM codes c
        LEFT JOIN LATERAL (
            SELECT usuario_id, sucursal_id
            FROM tb_biotime_empleado_map
            WHERE activo = true AND biotime_emp_code = c.code
            ORDER BY updated_at DESC
            LIMIT 1
        ) m ON true
        LEFT JOIN tb_empleados_datos ed
            ON (ed.biotime_emp_code = c.code OR ed.numero_empleado = c.code)
        """,
        emp_codes,
    )
    return {row["code"]: dict(row) for row in rows}


async def upsert_biotime_employee_mappings(conn, employees: list[dict]) -> list[dict]:
    if not employees:
        return []
    rows = await conn.fetch(
        """
        WITH incoming_raw AS (
            SELECT *
            FROM jsonb_to_recordset($1::jsonb) AS x(
                biotime_emp_code TEXT,
                biotime_pin TEXT,
                email TEXT,
                nombre TEXT,
                biotime_deptnumber TEXT,
                biotime_deptname TEXT
            )
        ),
        incoming AS (
            SELECT DISTINCT ON (biotime_emp_code)
                NULLIF(TRIM(biotime_emp_code), '') AS biotime_emp_code,
                NULLIF(TRIM(biotime_pin), '') AS biotime_pin,
                NULLIF(LOWER(TRIM(email)), '') AS email,
                NULLIF(TRIM(nombre), '') AS nombre,
                NULLIF(TRIM(biotime_deptnumber), '') AS biotime_deptnumber,
                NULLIF(TRIM(biotime_deptname), '') AS biotime_deptname
            FROM incoming_raw
            WHERE NULLIF(TRIM(biotime_emp_code), '') IS NOT NULL
            ORDER BY biotime_emp_code
        ),
        matched AS (
            SELECT
                i.*,
                COALESCE(u_email.id_usuario, ed_code.usuario_id) AS usuario_id,
                CASE
                    WHEN u_email.id_usuario IS NOT NULL THEN 'email'
                    WHEN ed_code.usuario_id IS NOT NULL THEN 'codigo'
                    ELSE NULL
                END AS matched_by
            FROM incoming i
            LEFT JOIN tb_usuarios u_email
                ON i.email IS NOT NULL
               AND LOWER(u_email.email) = i.email
               AND u_email.is_active = true
            LEFT JOIN tb_empleados_datos ed_code
                ON ed_code.biotime_emp_code = i.biotime_emp_code
                OR ed_code.numero_empleado = i.biotime_emp_code
            WHERE COALESCE(u_email.id_usuario, ed_code.usuario_id) IS NOT NULL
        ),
        ranked AS (
            SELECT
                matched.*,
                ROW_NUMBER() OVER (
                    PARTITION BY usuario_id
                    ORDER BY CASE WHEN matched_by = 'email' THEN 0 ELSE 1 END, biotime_emp_code
                ) AS user_rank
            FROM matched
        ),
        to_upsert AS (
            SELECT
                r.*,
                ed.id AS empleado_datos_id,
                ed.sucursal_id
            FROM ranked r
            LEFT JOIN tb_empleados_datos ed ON ed.usuario_id = r.usuario_id
            WHERE r.user_rank = 1
        ),
        deactivated AS (
            UPDATE tb_biotime_empleado_map m
            SET activo = false,
                updated_at = now()
            FROM to_upsert t
            WHERE m.activo = true
              AND m.usuario_id = t.usuario_id
              AND m.biotime_emp_code <> t.biotime_emp_code
            RETURNING m.id
        )
        INSERT INTO tb_biotime_empleado_map
            (usuario_id, empleado_datos_id, biotime_emp_code, biotime_pin,
             biotime_deptnumber, biotime_deptname, sucursal_id, activo, updated_at)
        SELECT
            usuario_id,
            empleado_datos_id,
            biotime_emp_code,
            COALESCE(biotime_pin, biotime_emp_code),
            biotime_deptnumber,
            biotime_deptname,
            sucursal_id,
            true,
            now()
        FROM to_upsert
        ON CONFLICT (biotime_emp_code) WHERE activo = true
        DO UPDATE SET
            usuario_id = EXCLUDED.usuario_id,
            empleado_datos_id = EXCLUDED.empleado_datos_id,
            biotime_pin = EXCLUDED.biotime_pin,
            biotime_deptnumber = EXCLUDED.biotime_deptnumber,
            biotime_deptname = EXCLUDED.biotime_deptname,
            sucursal_id = COALESCE(EXCLUDED.sucursal_id, tb_biotime_empleado_map.sucursal_id),
            updated_at = now()
        RETURNING usuario_id, biotime_emp_code, biotime_pin, biotime_deptnumber, biotime_deptname
        """,
        json.dumps(employees, default=str),
    )
    return [dict(row) for row in rows]


async def insert_checks_batch(conn, checks: list[dict]) -> list[dict]:
    if not checks:
        return []
    rows = await conn.fetch(
        """
        WITH incoming AS (
            SELECT *
            FROM jsonb_to_recordset($1::jsonb) AS x(
                biotime_transaction_id BIGINT,
                biotime_emp_code TEXT,
                usuario_id TEXT,
                check_time TEXT,
                punch_state TEXT,
                verify_type TEXT,
                terminal_sn TEXT,
                terminal_alias TEXT,
                deptnumber TEXT,
                deptname TEXT,
                raw_payload JSONB
            )
        ),
        inserted AS (
            INSERT INTO tb_biotime_checks
                (biotime_transaction_id, biotime_emp_code, usuario_id, check_time,
                 punch_state, verify_type, terminal_sn, terminal_alias, deptnumber,
                 deptname, raw_payload)
            SELECT
                biotime_transaction_id,
                biotime_emp_code,
                NULLIF(usuario_id, '')::uuid,
                check_time::timestamptz,
                punch_state,
                verify_type,
                terminal_sn,
                terminal_alias,
                deptnumber,
                deptname,
                COALESCE(raw_payload, '{}'::jsonb)
            FROM incoming
            WHERE biotime_emp_code IS NOT NULL
              AND check_time IS NOT NULL
            ON CONFLICT DO NOTHING
            RETURNING usuario_id, check_time
        )
        SELECT usuario_id, check_time
        FROM inserted
        WHERE usuario_id IS NOT NULL
        """,
        json.dumps(checks, default=str),
    )
    return [dict(row) for row in rows]


async def get_attendance_contexts(conn, usuario_ids: list[UUID]) -> list[dict]:
    if not usuario_ids:
        return []
    rows = await conn.fetch(
        """
        WITH requested AS (
            SELECT DISTINCT unnest($1::uuid[]) AS usuario_id
        )
        SELECT
            r.usuario_id,
            COALESCE(m.sucursal_id, ed.sucursal_id) AS sucursal_id,
            h.id AS horario_id,
            h.margen_entrada_antes_min,
            h.margen_salida_despues_min,
            h.tolerancia_extra_min,
            h.descuento_comida_min,
            d.id AS dia_id,
            d.dia_semana,
            d.hora_entrada,
            d.hora_salida,
            d.minutos_programados,
            d.cruza_medianoche,
            d.es_laboral
        FROM requested r
        LEFT JOIN tb_empleados_datos ed ON ed.usuario_id = r.usuario_id
        LEFT JOIN LATERAL (
            SELECT sucursal_id
            FROM tb_biotime_empleado_map
            WHERE usuario_id = r.usuario_id AND activo = true
            ORDER BY updated_at DESC
            LIMIT 1
        ) m ON true
        LEFT JOIN LATERAL (
            SELECT *
            FROM tb_horarios_sucursal
            WHERE sucursal_id = COALESCE(m.sucursal_id, ed.sucursal_id)
              AND activo = true
            ORDER BY updated_at DESC
            LIMIT 1
        ) h ON true
        LEFT JOIN tb_horarios_sucursal_dias d ON d.horario_sucursal_id = h.id
        """,
        usuario_ids,
    )
    return [dict(row) for row in rows]


async def get_checks_for_users_window(
    conn,
    *,
    usuario_ids: list[UUID],
    start: datetime,
    end: datetime,
) -> list[dict]:
    if not usuario_ids:
        return []
    rows = await conn.fetch(
        """
        SELECT usuario_id, check_time, punch_state
        FROM tb_biotime_checks
        WHERE usuario_id = ANY($1::uuid[])
          AND check_time >= $2
          AND check_time < $3
        ORDER BY usuario_id, check_time
        """,
        usuario_ids,
        start,
        end,
    )
    return [dict(row) for row in rows]


async def get_vacaciones_aprobadas(
    conn,
    *,
    usuario_ids: list[UUID],
    fecha_inicio: date,
    fecha_fin: date,
) -> list[dict]:
    if not usuario_ids:
        return []
    rows = await conn.fetch(
        """
        SELECT sa.id, sa.usuario_id, sa.fecha_inicio, sa.fecha_fin
        FROM tb_solicitudes_ausencia sa
        JOIN tb_cat_tipos_ausencia ta ON ta.id = sa.tipo_ausencia_id
        WHERE sa.usuario_id = ANY($1::uuid[])
          AND sa.estado = 'aprobado'
          AND ta.slug = 'vacaciones'
          AND COALESCE(sa.es_migracion, false) = false
          AND sa.fecha_inicio <= $3
          AND sa.fecha_fin >= $2
        """,
        usuario_ids,
        fecha_inicio,
        fecha_fin,
    )
    return [dict(row) for row in rows]


async def get_festivos_range(conn, fecha_inicio: date, fecha_fin: date) -> set[date]:
    rows = await conn.fetch(
        """
        SELECT fecha
        FROM tb_cat_festivos
        WHERE fecha >= $1 AND fecha <= $2
        """,
        fecha_inicio,
        fecha_fin,
    )
    return {row["fecha"] for row in rows}


async def get_active_attendance_users(conn) -> list[UUID]:
    rows = await conn.fetch(
        """
        SELECT DISTINCT u.id_usuario
        FROM tb_usuarios u
        LEFT JOIN tb_empleados_datos ed ON ed.usuario_id = u.id_usuario
        LEFT JOIN tb_biotime_empleado_map m ON m.usuario_id = u.id_usuario AND m.activo = true
        WHERE u.is_active = true
          AND (ed.biotime_emp_code IS NOT NULL OR ed.numero_empleado IS NOT NULL OR m.id IS NOT NULL)
        """
    )
    return [row["id_usuario"] for row in rows]


async def get_sucursales(conn) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT id, codigo, nombre
        FROM tb_cat_sucursales
        WHERE activa = true
        ORDER BY nombre
        """
    )
    return [dict(row) for row in rows]


async def upsert_asistencia_diaria_batch(conn, rows: list[dict]) -> None:
    if not rows:
        return
    await conn.executemany(
        """
        INSERT INTO tb_asistencia_diaria
            (usuario_id, sucursal_id, fecha_laboral, primera_entrada, ultima_salida,
             minutos_trabajados, minutos_programados, minutos_extra, estado,
             tiene_vacaciones, solicitud_ausencia_id, observaciones, calculated_at,
             updated_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,now())
        ON CONFLICT (usuario_id, fecha_laboral) DO UPDATE SET
            sucursal_id = EXCLUDED.sucursal_id,
            primera_entrada = EXCLUDED.primera_entrada,
            ultima_salida = EXCLUDED.ultima_salida,
            minutos_trabajados = EXCLUDED.minutos_trabajados,
            minutos_programados = EXCLUDED.minutos_programados,
            minutos_extra = EXCLUDED.minutos_extra,
            estado = EXCLUDED.estado,
            tiene_vacaciones = EXCLUDED.tiene_vacaciones,
            solicitud_ausencia_id = EXCLUDED.solicitud_ausencia_id,
            observaciones = EXCLUDED.observaciones,
            calculated_at = EXCLUDED.calculated_at,
            updated_at = now()
        """,
        [
            (
                row["usuario_id"],
                row.get("sucursal_id"),
                row["fecha_laboral"],
                row.get("primera_entrada"),
                row.get("ultima_salida"),
                row["minutos_trabajados"],
                row["minutos_programados"],
                row["minutos_extra"],
                row["estado"],
                row["tiene_vacaciones"],
                row.get("solicitud_ausencia_id"),
                row.get("observaciones"),
                row["calculated_at"],
            )
            for row in rows
        ],
    )


async def get_reporte_asistencia(
    conn,
    *,
    fecha_inicio: date,
    fecha_fin: date,
    usuario_id: UUID | None = None,
    sucursal_id: UUID | None = None,
    estado: str | None = None,
    solo_horas_extra: bool = False,
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
            ad.tiene_vacaciones,
            ad.observaciones,
            u.id_usuario,
            u.nombre AS empleado_nombre,
            u.email AS empleado_email,
            s.nombre AS sucursal_nombre
        FROM tb_asistencia_diaria ad
        JOIN tb_usuarios u ON u.id_usuario = ad.usuario_id
        LEFT JOIN tb_cat_sucursales s ON s.id = ad.sucursal_id
        WHERE ad.fecha_laboral >= $1
          AND ad.fecha_laboral <= $2
          AND ($3::uuid IS NULL OR ad.usuario_id = $3)
          AND ($4::uuid IS NULL OR ad.sucursal_id = $4)
          AND ($5::text IS NULL OR ad.estado = $5)
          AND ($6::bool = false OR ad.minutos_extra > 0)
        ORDER BY ad.fecha_laboral DESC, u.nombre
        """,
        fecha_inicio,
        fecha_fin,
        usuario_id,
        sucursal_id,
        estado,
        solo_horas_extra,
    )
    return [dict(row) for row in rows]


async def get_horas_extra_equipo(
    conn,
    usuario_ids: list[UUID],
    fecha_inicio: date,
    fecha_fin: date,
) -> list[dict]:
    if not usuario_ids:
        return []
    rows = await conn.fetch(
        """
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
            ad.observaciones,
            u.nombre AS empleado_nombre,
            u.email AS empleado_email,
            s.nombre AS sucursal_nombre
        FROM tb_asistencia_diaria ad
        JOIN tb_usuarios u ON u.id_usuario = ad.usuario_id
        LEFT JOIN tb_cat_sucursales s ON s.id = ad.sucursal_id
        WHERE ad.usuario_id = ANY($1::uuid[])
          AND ad.fecha_laboral >= $2
          AND ad.fecha_laboral <= $3
          AND ad.minutos_extra > 0
        ORDER BY ad.fecha_laboral DESC, u.nombre
        """,
        usuario_ids,
        fecha_inicio,
        fecha_fin,
    )
    return [dict(row) for row in rows]
