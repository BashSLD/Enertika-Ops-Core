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
            m.usuario_id,
            m.sucursal_id
        FROM codes c
        LEFT JOIN LATERAL (
            SELECT usuario_id, sucursal_id
            FROM tb_biotime_empleado_map
            WHERE activo = true AND biotime_emp_code = c.code
            ORDER BY updated_at DESC
            LIMIT 1
        ) m ON true
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
                biotime_emp_id INTEGER,
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
                biotime_emp_id,
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
        unique_users AS (
            SELECT LOWER(TRIM(email)) AS email, (ARRAY_AGG(id_usuario ORDER BY id_usuario::text))[1] AS usuario_id
            FROM tb_usuarios
            WHERE is_active = true
              AND NULLIF(TRIM(email), '') IS NOT NULL
            GROUP BY LOWER(TRIM(email))
            HAVING COUNT(*) = 1
        ),
        matched AS (
            SELECT
                i.*,
                u.usuario_id,
                'email'::text AS matched_by
            FROM incoming i
            JOIN unique_users u ON u.email = i.email
            WHERE i.email IS NOT NULL
        ),
        ranked AS (
            SELECT
                matched.*,
                ROW_NUMBER() OVER (
                    PARTITION BY usuario_id
                    ORDER BY biotime_emp_code
                ) AS user_rank
            FROM matched
        ),
        empleado_rows AS (
            INSERT INTO tb_empleados_datos
                (usuario_id, biotime_emp_code, updated_at)
            SELECT usuario_id, biotime_emp_code, now()
            FROM ranked
            WHERE user_rank = 1
            ON CONFLICT (usuario_id) DO UPDATE SET
                biotime_emp_code = EXCLUDED.biotime_emp_code,
                updated_at = now()
            RETURNING id, usuario_id, sucursal_id
        ),
        to_upsert AS (
            SELECT
                r.*,
                er.id AS empleado_datos_id,
                er.sucursal_id
            FROM ranked r
            LEFT JOIN empleado_rows er ON er.usuario_id = r.usuario_id
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
            (usuario_id, empleado_datos_id, biotime_emp_id, biotime_emp_code,
             biotime_pin, biotime_email, match_source, biotime_deptnumber,
             biotime_deptname, sucursal_id, activo, updated_at, last_seen_at)
        SELECT
            usuario_id,
            empleado_datos_id,
            biotime_emp_id,
            biotime_emp_code,
            COALESCE(biotime_pin, biotime_emp_code),
            email,
            matched_by,
            biotime_deptnumber,
            biotime_deptname,
            sucursal_id,
            true,
            now(),
            now()
        FROM to_upsert
        ON CONFLICT (biotime_emp_code) WHERE activo = true
        DO UPDATE SET
            usuario_id = EXCLUDED.usuario_id,
            empleado_datos_id = EXCLUDED.empleado_datos_id,
            biotime_emp_id = EXCLUDED.biotime_emp_id,
            biotime_pin = EXCLUDED.biotime_pin,
            biotime_email = EXCLUDED.biotime_email,
            match_source = EXCLUDED.match_source,
            biotime_deptnumber = EXCLUDED.biotime_deptnumber,
            biotime_deptname = EXCLUDED.biotime_deptname,
            sucursal_id = COALESCE(EXCLUDED.sucursal_id, tb_biotime_empleado_map.sucursal_id),
            updated_at = now(),
            last_seen_at = now()
        RETURNING usuario_id, biotime_emp_id, biotime_emp_code, biotime_pin,
                  biotime_email, match_source, biotime_deptnumber, biotime_deptname
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
            RETURNING usuario_id, check_time, biotime_emp_code
        )
        SELECT usuario_id, check_time, biotime_emp_code
        FROM inserted
        """,
        json.dumps(checks, default=str),
    )
    return [dict(row) for row in rows]


async def assign_unmapped_checks_from_mappings(conn) -> list[dict]:
    rows = await conn.fetch(
        """
        UPDATE tb_biotime_checks c
        SET usuario_id = m.usuario_id
        FROM tb_biotime_empleado_map m
        WHERE c.usuario_id IS NULL
          AND m.activo = true
          AND m.biotime_emp_code = c.biotime_emp_code
        RETURNING c.usuario_id, c.check_time, c.biotime_emp_code
        """
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
            COALESCE(d.descuento_comida_min, h.descuento_comida_min, 0) AS descuento_comida_min,
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


async def get_recalculo_bounds(conn, usuario_ids: list[UUID]) -> dict | None:
    if not usuario_ids:
        return None
    row = await conn.fetchrow(
        """
        WITH checks_bounds AS (
            SELECT
                MIN((check_time AT TIME ZONE 'America/Mexico_City')::date) AS fecha_inicio,
                MAX((check_time AT TIME ZONE 'America/Mexico_City')::date) AS fecha_fin
            FROM tb_biotime_checks
            WHERE usuario_id = ANY($1::uuid[])
        ),
        asistencia_bounds AS (
            SELECT
                MIN(fecha_laboral) AS fecha_inicio,
                MAX(fecha_laboral) AS fecha_fin
            FROM tb_asistencia_diaria
            WHERE usuario_id = ANY($1::uuid[])
        )
        SELECT
            (
                SELECT MIN(fecha)
                FROM (VALUES (checks_bounds.fecha_inicio), (asistencia_bounds.fecha_inicio)) AS v(fecha)
            ) AS fecha_inicio,
            (
                SELECT MAX(fecha)
                FROM (VALUES (checks_bounds.fecha_fin), (asistencia_bounds.fecha_fin)) AS v(fecha)
            ) AS fecha_fin
        FROM checks_bounds, asistencia_bounds
        """,
        usuario_ids,
    )
    if not row or not row["fecha_inicio"] or not row["fecha_fin"]:
        return None
    return dict(row)


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


_MAX_EXPORT_ROWS = 50_000


async def get_reporte_asistencia(
    conn,
    *,
    fecha_inicio: date,
    fecha_fin: date,
    usuario_ids: list[UUID] | None = None,
    sucursal_ids: list[UUID] | None = None,
    estados: list[str] | None = None,
    solo_horas_extra: bool = False,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict]:
    uids = usuario_ids or []
    sids = sucursal_ids or []
    ests = estados or []
    lim = limit if limit is not None else _MAX_EXPORT_ROWS
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
            ad.horas_extra_estado,
            u.id_usuario,
            u.nombre AS empleado_nombre,
            u.email AS empleado_email,
            s.nombre AS sucursal_nombre,
            hea.minutos_aprobados,
            hea.comentario AS aprobacion_comentario
        FROM tb_asistencia_diaria ad
        JOIN tb_usuarios u ON u.id_usuario = ad.usuario_id
        LEFT JOIN tb_cat_sucursales s ON s.id = ad.sucursal_id
        LEFT JOIN tb_horas_extra_aprobaciones hea ON hea.asistencia_id = ad.id
        WHERE ad.fecha_laboral >= $1
          AND ad.fecha_laboral <= $2
          AND (cardinality($3::uuid[]) = 0 OR ad.usuario_id = ANY($3))
          AND (cardinality($4::uuid[]) = 0 OR ad.sucursal_id = ANY($4))
          AND (cardinality($5::text[]) = 0 OR ad.estado = ANY($5))
          AND ($6::bool = false OR ad.minutos_extra > 0)
        ORDER BY ad.fecha_laboral DESC, u.nombre
        LIMIT $7 OFFSET $8
        """,
        fecha_inicio,
        fecha_fin,
        uids,
        sids,
        ests,
        solo_horas_extra,
        lim,
        offset,
    )
    return [dict(row) for row in rows]


async def get_unmapped_biotime_checks_summary(
    conn,
    *,
    fecha_inicio: date,
    fecha_fin: date,
    limit: int = 50,
) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT
            c.biotime_emp_code,
            MAX(c.deptname) AS deptname,
            COUNT(*)::int AS total,
            MIN(c.check_time) AS primera_checada,
            MAX(c.check_time) AS ultima_checada
        FROM tb_biotime_checks c
        LEFT JOIN tb_biotime_empleado_map m ON m.biotime_emp_code = c.biotime_emp_code
        LEFT JOIN tb_usuarios u ON u.id_usuario = m.usuario_id AND u.is_active = false
        WHERE c.usuario_id IS NULL
          AND (c.check_time AT TIME ZONE 'America/Mexico_City')::date >= $1
          AND (c.check_time AT TIME ZONE 'America/Mexico_City')::date <= $2
          AND u.id_usuario IS NULL
        GROUP BY c.biotime_emp_code
        ORDER BY ultima_checada DESC
        LIMIT $3
        """,
        fecha_inicio,
        fecha_fin,
        limit,
    )
    return [dict(row) for row in rows]


async def get_horas_extra_equipo(
    conn,
    usuario_ids: list[UUID],
    fecha_inicio: date,
    fecha_fin: date,
    *,
    estados: tuple[str, ...] = ("pendiente", "solicitado"),
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
            ad.horas_extra_estado,
            ad.motivo_solicitud,
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
          AND ad.horas_extra_estado = ANY($4::text[])
        ORDER BY ad.horas_extra_estado DESC, ad.fecha_laboral DESC, u.nombre
        """,
        usuario_ids,
        fecha_inicio,
        fecha_fin,
        list(estados),
    )
    return [dict(row) for row in rows]


async def get_asistencia_para_aprobar(conn, asistencia_id: UUID) -> dict | None:
    row = await conn.fetchrow(
        """
        SELECT
            ad.id,
            ad.usuario_id,
            ad.fecha_laboral,
            ad.minutos_extra,
            ad.horas_extra_estado,
            u.nombre AS empleado_nombre
        FROM tb_asistencia_diaria ad
        JOIN tb_usuarios u ON u.id_usuario = ad.usuario_id
        WHERE ad.id = $1
        """,
        asistencia_id,
    )
    return dict(row) if row else None


async def aprobar_horas_extra(
    conn,
    *,
    asistencia_id: UUID,
    aprobador_id: UUID,
    minutos_aprobados: int,
    comentario: str,
) -> None:
    await conn.execute(
        """
        WITH ins AS (
            INSERT INTO tb_horas_extra_aprobaciones
                (asistencia_id, aprobador_id, minutos_aprobados, comentario)
            VALUES ($1, $2, $3, $4)
        )
        UPDATE tb_asistencia_diaria
        SET horas_extra_estado = 'aprobado'
        WHERE id = $1
        """,
        asistencia_id,
        aprobador_id,
        minutos_aprobados,
        comentario,
    )


async def bulk_get_asistencia_info(
    conn, asistencia_ids: list[UUID]
) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT
            ad.id,
            ad.usuario_id,
            ad.fecha_laboral,
            ad.minutos_extra,
            ad.horas_extra_estado,
            u.nombre AS empleado_nombre
        FROM tb_asistencia_diaria ad
        JOIN tb_usuarios u ON u.id_usuario = ad.usuario_id
        WHERE ad.id = ANY($1::uuid[])
        """,
        asistencia_ids,
    )
    return [dict(row) for row in rows]


async def bulk_aprobar_horas_extra(
    conn,
    *,
    asistencia_ids: list[UUID],
    aprobador_id: UUID,
    minutos_aprobados: int,
    comentario: str,
) -> None:
    await conn.execute(
        """
        WITH ins AS (
            INSERT INTO tb_horas_extra_aprobaciones
                (asistencia_id, aprobador_id, minutos_aprobados, comentario)
            SELECT unnest($1::uuid[]), $2, $3, $4
            ON CONFLICT (asistencia_id) DO NOTHING
        )
        UPDATE tb_asistencia_diaria
        SET horas_extra_estado = 'aprobado'
        WHERE id = ANY($1::uuid[])
        """,
        asistencia_ids,
        aprobador_id,
        minutos_aprobados,
        comentario,
    )


async def count_horas_extra_pendientes(conn, usuario_ids: list[UUID]) -> int:
    if not usuario_ids:
        return 0
    return await conn.fetchval(
        """
        SELECT COUNT(*)
        FROM tb_asistencia_diaria
        WHERE usuario_id = ANY($1::uuid[])
          AND horas_extra_estado IN ('pendiente', 'solicitado')
          AND minutos_extra > 0
        """,
        usuario_ids,
    ) or 0


async def omitir_horas_extra(conn, asistencia_id: UUID) -> None:
    await conn.execute(
        """
        UPDATE tb_asistencia_diaria
        SET horas_extra_estado = 'omitido'
        WHERE id = $1
        """,
        asistencia_id,
    )


async def recuperar_horas_extra(conn, asistencia_id: UUID) -> None:
    await conn.execute(
        """
        UPDATE tb_asistencia_diaria
        SET horas_extra_estado = 'pendiente'
        WHERE id = $1
          AND horas_extra_estado = 'omitido'
        """,
        asistencia_id,
    )


async def solicitar_aprobacion_horas_extra(
    conn, asistencia_id: UUID, usuario_id: UUID, motivo: str
) -> None:
    await conn.execute(
        """
        UPDATE tb_asistencia_diaria
        SET horas_extra_estado = 'solicitado',
            motivo_solicitud = $3
        WHERE id = $1
          AND usuario_id = $2
          AND horas_extra_estado = 'pendiente'
        """,
        asistencia_id,
        usuario_id,
        motivo,
    )


async def get_horas_extra_omitidas_equipo(
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
            ad.minutos_extra,
            ad.motivo_solicitud,
            u.nombre AS empleado_nombre,
            s.nombre AS sucursal_nombre
        FROM tb_asistencia_diaria ad
        JOIN tb_usuarios u ON u.id_usuario = ad.usuario_id
        LEFT JOIN tb_cat_sucursales s ON s.id = ad.sucursal_id
        WHERE ad.usuario_id = ANY($1::uuid[])
          AND ad.fecha_laboral >= $2
          AND ad.fecha_laboral <= $3
          AND ad.minutos_extra > 0
          AND ad.horas_extra_estado = 'omitido'
        ORDER BY ad.fecha_laboral DESC, u.nombre
        """,
        usuario_ids,
        fecha_inicio,
        fecha_fin,
    )
    return [dict(row) for row in rows]

