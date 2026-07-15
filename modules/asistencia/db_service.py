from __future__ import annotations

import json
from datetime import date, datetime
from uuid import UUID, uuid4

# Fragmentos SQL compartidos con TasksDBService (unica fuente, evita reimplementar la misma
# regla de precedencia jefes/override en cada query):
# - ACTIVE_RH_CONTACTS_WHERE: predicado RH editor/admin activo + ADMIN global con correo,
#   usado por los fallback CTEs de get_datos_resolucion_notificacion_he y
#   verificar_fallback_aprobador_he.
# - _jefe_emails_lateral_join / _he_override_lateral_join / _HE_OVERRIDE_SELECT_COLUMNS:
#   mismo LEFT JOIN LATERAL que arma get_active_rh_contacts para recordatorios, reusado aqui
#   por get_datos_resolucion_notificacion_he para resolver un solo empleado.
from core.tasks_db_service import (
    ACTIVE_RH_CONTACTS_WHERE as _FALLBACK_RH_ADMIN_WHERE,
    _HE_OVERRIDE_SELECT_COLUMNS,
    _he_override_lateral_join,
    _jefe_emails_lateral_join,
)
from modules.asistencia.constants import ASISTENCIA_MODALIDAD_METADATA_SLUGS


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


async def get_ausencias_justificadas(
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
        SELECT
            sa.id,
            sa.usuario_id,
            sa.fecha_inicio,
            sa.fecha_fin,
            ta.nombre AS tipo_nombre,
            ta.abreviatura AS tipo_abreviatura,
            ta.slug AS tipo_slug
        FROM tb_solicitudes_ausencia sa
        JOIN tb_cat_tipos_ausencia ta ON ta.id = sa.tipo_ausencia_id
        WHERE sa.usuario_id = ANY($1::uuid[])
          AND sa.estado = 'aprobado'
          AND COALESCE(ta.justifica_asistencia_dia, false) = true
          AND COALESCE(sa.es_migracion, false) = false
          AND sa.fecha_inicio <= $3
          AND sa.fecha_fin >= $2
        ORDER BY sa.updated_at DESC, sa.id
        """,
        usuario_ids,
        fecha_inicio,
        fecha_fin,
    )
    return [dict(row) for row in rows]


async def get_modalidades_metadata_en_rango(
    conn,
    *,
    usuario_ids: list[UUID],
    fecha_inicio: date,
    fecha_fin: date,
) -> list[dict]:
    """Modalidades informativas aprobadas, expandidas a cada fecha visible."""
    if not usuario_ids:
        return []
    rows = await conn.fetch(
        """
        SELECT
            sa.usuario_id,
            dias.fecha_laboral::date AS fecha_laboral,
            ta.slug AS tipo_slug,
            ta.nombre AS tipo_nombre,
            ta.abreviatura AS tipo_abreviatura,
            sa.id AS solicitud_id
        FROM tb_solicitudes_ausencia sa
        JOIN tb_cat_tipos_ausencia ta ON ta.id = sa.tipo_ausencia_id
        CROSS JOIN LATERAL generate_series(
            GREATEST(sa.fecha_inicio, $2::date),
            LEAST(sa.fecha_fin, $3::date),
            INTERVAL '1 day'
        ) AS dias(fecha_laboral)
        WHERE sa.usuario_id = ANY($1::uuid[])
          AND sa.estado = 'aprobado'
          AND COALESCE(sa.es_migracion, false) = false
          AND ta.slug = ANY($4::text[])
          AND sa.fecha_inicio <= $3
          AND sa.fecha_fin >= $2
        ORDER BY sa.usuario_id, dias.fecha_laboral::date, ta.orden NULLS LAST, ta.nombre, sa.id
        """,
        usuario_ids,
        fecha_inicio,
        fecha_fin,
        list(ASISTENCIA_MODALIDAD_METADATA_SLUGS),
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
             tiene_vacaciones, tiene_ausencia_justificada, solicitud_ausencia_id, observaciones, calculated_at,
             horas_extra_estado, minutos_he_compensatorio, he_compensatorio_solicitud_id,
             updated_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,now())
        ON CONFLICT (usuario_id, fecha_laboral) DO UPDATE SET
            sucursal_id = EXCLUDED.sucursal_id,
            primera_entrada = EXCLUDED.primera_entrada,
            ultima_salida = EXCLUDED.ultima_salida,
            minutos_trabajados = EXCLUDED.minutos_trabajados,
            minutos_programados = EXCLUDED.minutos_programados,
            minutos_extra = CASE
                WHEN EXCLUDED.minutos_he_compensatorio > 0 THEN 0
                WHEN tb_asistencia_diaria.horas_extra_estado IN ('solicitado', 'aprobado', 'omitido', 'feriado')
                    THEN tb_asistencia_diaria.minutos_extra
                ELSE EXCLUDED.minutos_extra
            END,
            estado = EXCLUDED.estado,
            tiene_vacaciones = EXCLUDED.tiene_vacaciones,
            tiene_ausencia_justificada = EXCLUDED.tiene_ausencia_justificada,
            solicitud_ausencia_id = EXCLUDED.solicitud_ausencia_id,
            observaciones = EXCLUDED.observaciones,
            calculated_at = EXCLUDED.calculated_at,
            horas_extra_estado = CASE
                WHEN tb_asistencia_diaria.horas_extra_estado IN ('solicitado', 'aprobado', 'omitido', 'feriado')
                    THEN tb_asistencia_diaria.horas_extra_estado
                ELSE EXCLUDED.horas_extra_estado
            END,
            minutos_he_compensatorio = EXCLUDED.minutos_he_compensatorio,
            he_compensatorio_solicitud_id = EXCLUDED.he_compensatorio_solicitud_id,
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
                row["tiene_ausencia_justificada"],
                row.get("solicitud_ausencia_id"),
                row.get("observaciones"),
                row["calculated_at"],
                row.get("horas_extra_estado", "pendiente"),
                row.get("minutos_he_compensatorio", 0),
                row.get("he_compensatorio_solicitud_id"),
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
    incluir_dados_de_baja: bool = False,
    incluir_descanso: bool = False,
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
            ad.tiene_ausencia_justificada,
            ad.observaciones,
            ad.horas_extra_estado,
            ad.minutos_he_compensatorio,
            ad.he_compensatorio_solicitud_id,
            ad.motivo_solicitud,
            ad.horas_extra_motivo_rechazo,
            ta.nombre AS tipo_ausencia_nombre,
            ta.abreviatura AS tipo_ausencia_abreviatura,
            ta.slug AS tipo_ausencia_slug,
            u.id_usuario,
            u.id_usuario AS usuario_id,
            u.nombre AS empleado_nombre,
            u.email AS empleado_email,
            s.nombre AS sucursal_nombre,
            ed.departamento,
            hea.minutos_aprobados,
            hea.comentario AS aprobacion_comentario
        FROM tb_asistencia_diaria ad
        JOIN tb_usuarios u ON u.id_usuario = ad.usuario_id
        LEFT JOIN tb_solicitudes_ausencia sa ON sa.id = ad.solicitud_ausencia_id
        LEFT JOIN tb_cat_tipos_ausencia ta ON ta.id = sa.tipo_ausencia_id
        LEFT JOIN tb_cat_sucursales s ON s.id = ad.sucursal_id
        LEFT JOIN tb_empleados_datos ed ON ed.usuario_id = ad.usuario_id
        LEFT JOIN tb_horas_extra_aprobaciones hea ON hea.asistencia_id = ad.id
        WHERE ad.fecha_laboral >= $1
          AND ad.fecha_laboral <= $2
          AND (cardinality($3::uuid[]) = 0 OR ad.usuario_id = ANY($3))
          AND (cardinality($4::uuid[]) = 0 OR ad.sucursal_id = ANY($4))
          AND (cardinality($5::text[]) = 0 OR ad.estado = ANY($5))
          AND ($6::bool = false OR ad.minutos_extra > 0)
          AND ($7::bool = true OR u.is_active = true)
          AND ($8::bool = true OR NOT (ad.estado = 'descanso' AND ad.primera_entrada IS NULL))
        UNION ALL
        SELECT
            NULL::uuid AS id,
            dias.fecha_laboral::date AS fecha_laboral,
            NULL::timestamptz AS primera_entrada,
            NULL::timestamptz AS ultima_salida,
            0::int AS minutos_trabajados,
            0::int AS minutos_programados,
            0::int AS minutos_extra,
            CASE WHEN ta.slug = 'vacaciones' THEN 'vacaciones' ELSE 'ausencia' END AS estado,
            (ta.slug = 'vacaciones') AS tiene_vacaciones,
            true AS tiene_ausencia_justificada,
            'Ausencia aprobada: ' || ta.nombre AS observaciones,
            NULL::text AS horas_extra_estado,
            0::int AS minutos_he_compensatorio,
            NULL::uuid AS he_compensatorio_solicitud_id,
            NULL::text AS motivo_solicitud,
            NULL::text AS horas_extra_motivo_rechazo,
            ta.nombre AS tipo_ausencia_nombre,
            ta.abreviatura AS tipo_ausencia_abreviatura,
            ta.slug AS tipo_ausencia_slug,
            u.id_usuario,
            u.id_usuario AS usuario_id,
            u.nombre AS empleado_nombre,
            u.email AS empleado_email,
            s.nombre AS sucursal_nombre,
            ed.departamento,
            NULL::int AS minutos_aprobados,
            NULL::text AS aprobacion_comentario
        FROM tb_solicitudes_ausencia sa
        JOIN tb_cat_tipos_ausencia ta ON ta.id = sa.tipo_ausencia_id
        JOIN tb_usuarios u ON u.id_usuario = sa.usuario_id
        LEFT JOIN tb_empleados_datos ed ON ed.usuario_id = sa.usuario_id
        LEFT JOIN LATERAL (
            SELECT sucursal_id
            FROM tb_biotime_empleado_map
            WHERE usuario_id = sa.usuario_id
              AND activo = true
            ORDER BY updated_at DESC NULLS LAST
            LIMIT 1
        ) m ON true
        LEFT JOIN tb_cat_sucursales s ON s.id = COALESCE(m.sucursal_id, ed.sucursal_id)
        CROSS JOIN LATERAL generate_series(
            GREATEST(sa.fecha_inicio, $1::date),
            LEAST(sa.fecha_fin, $2::date),
            INTERVAL '1 day'
        ) AS dias(fecha_laboral)
        LEFT JOIN LATERAL (
            SELECT *
            FROM tb_horarios_sucursal
            WHERE sucursal_id = COALESCE(m.sucursal_id, ed.sucursal_id)
              AND activo = true
            ORDER BY updated_at DESC
            LIMIT 1
        ) h ON true
        LEFT JOIN tb_horarios_sucursal_dias d
            ON d.horario_sucursal_id = h.id
           AND d.dia_semana = ((EXTRACT(DOW FROM dias.fecha_laboral::date)::int + 6) % 7)
        LEFT JOIN tb_cat_festivos fest ON fest.fecha = dias.fecha_laboral::date
        WHERE sa.estado = 'aprobado'
          AND COALESCE(ta.justifica_asistencia_dia, false) = true
          AND COALESCE(sa.es_migracion, false) = false
          AND sa.fecha_inicio <= $2
          AND sa.fecha_fin >= $1
          AND fest.fecha IS NULL
          AND (d.id IS NULL OR d.es_laboral = true)
          AND NOT EXISTS (
              SELECT 1
              FROM tb_asistencia_diaria ad_existing
              WHERE ad_existing.usuario_id = sa.usuario_id
                AND ad_existing.fecha_laboral = dias.fecha_laboral::date
          )
          AND (cardinality($3::uuid[]) = 0 OR sa.usuario_id = ANY($3))
          AND (cardinality($4::uuid[]) = 0 OR COALESCE(m.sucursal_id, ed.sucursal_id) = ANY($4))
          AND (
              cardinality($5::text[]) = 0
              OR (CASE WHEN ta.slug = 'vacaciones' THEN 'vacaciones' ELSE 'ausencia' END) = ANY($5)
          )
          AND $6::bool = false
          AND ($7::bool = true OR u.is_active = true)
        ORDER BY fecha_laboral DESC, empleado_nombre
        LIMIT $9 OFFSET $10
        """,
        fecha_inicio,
        fecha_fin,
        uids,
        sids,
        ests,
        solo_horas_extra,
        incluir_dados_de_baja,
        incluir_descanso,
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
            ad.horas_extra_solicitada_at,
            ad.horas_extra_ultimo_recordatorio_at,
            ad.horas_extra_recordatorios_enviados,
            ad.horas_extra_resumen_rh_at,
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


async def get_horas_extra_todas(
    conn,
    fecha_inicio: date,
    fecha_fin: date,
    *,
    estados: tuple[str, ...] = ("pendiente", "solicitado"),
) -> list[dict]:
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
            ad.horas_extra_solicitada_at,
            ad.horas_extra_ultimo_recordatorio_at,
            ad.horas_extra_recordatorios_enviados,
            ad.horas_extra_resumen_rh_at,
            ad.observaciones,
            u.nombre AS empleado_nombre,
            u.email AS empleado_email,
            s.nombre AS sucursal_nombre
        FROM tb_asistencia_diaria ad
        JOIN tb_usuarios u ON u.id_usuario = ad.usuario_id
        LEFT JOIN tb_cat_sucursales s ON s.id = ad.sucursal_id
        WHERE ad.fecha_laboral >= $1
          AND ad.fecha_laboral <= $2
          AND ad.minutos_extra > 0
          AND ad.horas_extra_estado = ANY($3::text[])
        ORDER BY ad.horas_extra_estado DESC, ad.fecha_laboral DESC, u.nombre
        """,
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
            ad.minutos_he_compensatorio,
            u.nombre AS empleado_nombre,
            u.email AS empleado_email
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
) -> int:
    return await bulk_aprobar_horas_extra(
        conn,
        asistencia_ids=[asistencia_id],
        aprobador_id=aprobador_id,
        minutos_aprobados=minutos_aprobados,
        comentario=comentario,
    )


async def bulk_aprobar_horas_extra(
    conn,
    *,
    asistencia_ids: list[UUID],
    aprobador_id: UUID,
    minutos_aprobados: int,
    comentario: str,
) -> int:
    return await conn.fetchval(
        """
        WITH target AS (
            SELECT ad.id, ad.usuario_id, ad.fecha_laboral
            FROM tb_asistencia_diaria ad
            WHERE ad.id = ANY($1::uuid[])
              AND ad.horas_extra_estado IN ('pendiente', 'solicitado')
              AND ad.minutos_extra > 0
              AND NOT EXISTS (
                  SELECT 1
                  FROM tb_cat_festivos f
                  WHERE f.fecha = ad.fecha_laboral
              )
            FOR UPDATE
        ),
        ins AS (
            INSERT INTO tb_horas_extra_aprobaciones
                (asistencia_id, aprobador_id, minutos_aprobados, comentario)
            SELECT id, $2, $3, $4
            FROM target
            ON CONFLICT (asistencia_id) DO NOTHING
            RETURNING id AS aprobacion_id, asistencia_id
        ),
        mov AS (
            INSERT INTO tb_he_bolsa_movimientos
                (usuario_id, tipo, minutos, concepto, fecha_referencia, aprobacion_id, creado_por)
            SELECT t.usuario_id,
                   'CREDITO',
                   $3,
                   'Horas extra aprobadas',
                   t.fecha_laboral,
                   i.aprobacion_id,
                   $2
            FROM ins i
            JOIN target t ON t.id = i.asistencia_id
            ON CONFLICT DO NOTHING
            RETURNING aprobacion_id
        ),
        credited AS (
            SELECT i.asistencia_id
            FROM ins i
            JOIN mov m ON m.aprobacion_id = i.aprobacion_id
        ),
        upd AS (
            UPDATE tb_asistencia_diaria ad
            SET horas_extra_estado = 'aprobado',
                horas_extra_resumen_rh_at = NULL
            WHERE ad.id IN (SELECT asistencia_id FROM credited)
            RETURNING 1
        )
        SELECT COUNT(*)::int FROM upd
        """,
        asistencia_ids,
        aprobador_id,
        minutos_aprobados,
        comentario,
    ) or 0


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


async def omitir_horas_extra(conn, asistencia_id: UUID, motivo_rechazo: str | None = None) -> bool:
    """Devuelve False si el registro ya no estaba en 'pendiente'/'solicitado' al momento del
    UPDATE (carrera concurrente) — el llamador debe validarlo bajo lock_he_usuario.

    `motivo_rechazo` solo aplica al rechazo de terceros (omitir_horas_extra_svc); el retiro
    propio del empleado (omitir_horas_extra_propio_svc) no lo pide y lo deja NULL."""
    row = await conn.fetchrow(
        """
        UPDATE tb_asistencia_diaria
        SET horas_extra_estado = 'omitido',
            horas_extra_resumen_rh_at = NULL,
            horas_extra_motivo_rechazo = $2
        WHERE id = $1
          AND horas_extra_estado IN ('pendiente', 'solicitado')
        RETURNING id
        """,
        asistencia_id,
        motivo_rechazo,
    )
    return row is not None


async def recuperar_horas_extra(conn, asistencia_id: UUID) -> bool:
    """Devuelve False si el registro ya no estaba en 'omitido' al momento del UPDATE (carrera
    concurrente) — el llamador debe validarlo bajo lock_he_usuario."""
    row = await conn.fetchrow(
        """
        UPDATE tb_asistencia_diaria
        SET horas_extra_estado = 'pendiente',
            motivo_solicitud = NULL,
            horas_extra_solicitada_at = NULL,
            horas_extra_ultimo_recordatorio_at = NULL,
            horas_extra_recordatorios_enviados = 0,
            horas_extra_resumen_rh_at = NULL
        WHERE id = $1
          AND horas_extra_estado = 'omitido'
        RETURNING id
        """,
        asistencia_id,
    )
    return row is not None


async def recuperar_dia_feriado(conn, asistencia_id: UUID) -> bool:
    """Reabre un dia marcado 'feriado' para que el proximo recalculo de BioTime lo recompute.

    'feriado' nunca pasa por aprobar_horas_extra (no genera credito en la bolsa ni
    fila en tb_horas_extra_aprobaciones), por lo que no hay nada que revertir en el
    ledger — a diferencia de 'aprobado', ver revertir_horas_extra_aprobado.
    """
    row = await conn.fetchrow(
        """
        UPDATE tb_asistencia_diaria
        SET horas_extra_estado = 'pendiente',
            horas_extra_resumen_rh_at = NULL
        WHERE id = $1
          AND horas_extra_estado = 'feriado'
        RETURNING id
        """,
        asistencia_id,
    )
    return row is not None


async def revertir_horas_extra_aprobado(conn, asistencia_id: UUID, revertido_por: UUID) -> bool:
    """Corrige manualmente un dia ya 'aprobado' (p.ej. BioTime se corrigio despues del approve).

    upsert_asistencia_diaria_batch congela minutos_extra/horas_extra_estado una vez
    'aprobado' para proteger el credito ya hecho a tb_he_bolsa_movimientos de ser
    sobreescrito silenciosamente por el recalculo periodico. Esta funcion es la
    unica via de reconciliacion: reversa el credito con un DEBITO explicito, libera
    la aprobacion (permite un nuevo approve tras el proximo recalculo) y regresa el
    dia a 'pendiente'. Uso exclusivo de RH via API — sin boton en UI todavia.
    """
    async with conn.transaction():
        row = await conn.fetchrow(
            """
            SELECT ad.usuario_id, ad.fecha_laboral, hea.id AS aprobacion_id, hea.minutos_aprobados
            FROM tb_asistencia_diaria ad
            JOIN tb_horas_extra_aprobaciones hea ON hea.asistencia_id = ad.id
            WHERE ad.id = $1
              AND ad.horas_extra_estado = 'aprobado'
            FOR UPDATE OF ad
            """,
            asistencia_id,
        )
        if not row:
            return False

        await conn.execute(
            "DELETE FROM tb_horas_extra_aprobaciones WHERE id = $1",
            row["aprobacion_id"],
        )
        await conn.execute(
            """
            INSERT INTO tb_he_bolsa_movimientos
                (usuario_id, tipo, minutos, concepto, fecha_referencia, creado_por)
            VALUES ($1, 'DEBITO', $2, 'Reversion de horas extra aprobadas (correccion manual RH)', $3, $4)
            """,
            row["usuario_id"],
            row["minutos_aprobados"],
            row["fecha_laboral"],
            revertido_por,
        )
        await conn.execute(
            """
            UPDATE tb_asistencia_diaria
            SET horas_extra_estado = 'pendiente',
                horas_extra_resumen_rh_at = NULL
            WHERE id = $1
            """,
            asistencia_id,
        )
    return True


async def solicitar_aprobacion_horas_extra(
    conn, asistencia_id: UUID, usuario_id: UUID, motivo: str
) -> bool:
    """Devuelve False si el registro ya no estaba en 'pendiente' al momento del UPDATE
    (carrera concurrente) — el llamador debe validarlo bajo lock_he_usuario antes de persistir
    evidencias asociadas."""
    row = await conn.fetchrow(
        """
        UPDATE tb_asistencia_diaria
        SET horas_extra_estado = 'solicitado',
            motivo_solicitud = $3,
            horas_extra_solicitada_at = now(),
            horas_extra_ultimo_recordatorio_at = NULL,
            horas_extra_recordatorios_enviados = 0,
            horas_extra_resumen_rh_at = NULL
        WHERE id = $1
          AND usuario_id = $2
          AND horas_extra_estado = 'pendiente'
        RETURNING id
        """,
        asistencia_id,
        usuario_id,
        motivo,
    )
    return row is not None


async def _lock_he(conn, prefix: str, identifier: str) -> None:
    """Advisory lock transaccional con namespace propio (prefijos disjuntos entre helpers)."""
    await conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended($1::text, 0))",
        f"{prefix}:{identifier}",
    )


async def lock_he_usuario(conn, usuario_id: UUID) -> None:
    """Lock del empleado dueno de la bolsa/registro HE. Usar en todo movimiento de bolsa
    y en toda transicion de estado HE/compensatorio (incl. saldo inicial y reversion)."""
    await _lock_he(conn, "he_usuario", str(usuario_id))


async def lock_he_actor(conn, actor_id: UUID) -> None:
    """Lock del actor cuya actividad/RBAC se esta revalidando (aprobador, no el empleado)."""
    await _lock_he(conn, "he_actor", str(actor_id))


async def lock_he_fallback(conn) -> None:
    """Lock unico global para la disponibilidad del fallback RH/ADMIN de aprobador HE exclusivo."""
    await _lock_he(conn, "he_fallback", "global")


# Fuente unica de la regla de precedencia "aprobador exclusivo HE > jefe/aprobador de
# vacaciones (solo si el empleado NO tiene aprobador exclusivo)". $1 = aprobador_id;
# $2 (nullable) = empleado_id opcional para acotar a un solo empleado. Con $2 = NULL
# devuelve el set completo de empleados que $1 puede autorizar (get_empleados_para_autorizacion_he);
# con $2 = un empleado especifico, se usa en un EXISTS(...) para el chequeo booleano
# (puede_autorizar_he). Las 3 ramas son deliberadamente separadas (no un solo OR) para que
# cada una use su propio indice (idx_empleados_aprobador_horas_extra + indices existentes de
# jefe/aprobador de vacaciones) sin depender de que el planner especialice un OR compuesto.
#
# ATENCION: modules.asistencia.service.resolver_destinatarios_he_puro consume la MISMA regla
# por separado, via el flag `tiene_override` de get_datos_resolucion_notificacion_he (un simple
# `id_aprobador_horas_extra IS NOT NULL`) -- no se pudo unificar aqui porque esa query devuelve
# una fila de datos de notificacion, no un booleano/lista de UUIDs. Si cambias la regla de
# precedencia, replicala tambien ahi -- tests/test_aprobador_he_exclusivo.py::test_consistencia_*
# corre fixtures compartidos contra las tres para detectar drift.
_HE_AUTORIZACION_PRECEDENCIA_QUERY = """
        SELECT ed.usuario_id
        FROM tb_empleados_datos ed
        WHERE ed.id_aprobador_horas_extra = $1
          AND ($2::uuid IS NULL OR ed.usuario_id = $2)
        UNION
        SELECT ej.empleado_id
        FROM tb_empleados_jefes ej
        LEFT JOIN tb_empleados_datos ed ON ed.usuario_id = ej.empleado_id
        WHERE ej.jefe_id = $1 AND ed.id_aprobador_horas_extra IS NULL
          AND ($2::uuid IS NULL OR ej.empleado_id = $2)
        UNION
        SELECT ed.usuario_id
        FROM tb_empleados_datos ed
        WHERE ed.id_aprobador_vacaciones = $1
          AND ed.id_aprobador_horas_extra IS NULL
          AND ($2::uuid IS NULL OR ed.usuario_id = $2)
"""


async def get_empleados_para_autorizacion_he(conn, aprobador_id: UUID) -> list[UUID]:
    """Empleados que $1 puede autorizar en HE/compensatorio (excluye visibilidad, solo autorizacion).

    Consume _HE_AUTORIZACION_PRECEDENCIA_QUERY sin filtro de empleado (set completo para
    aprobador_id). Ver esa constante para la regla de precedencia y su nota de consistencia.
    """
    rows = await conn.fetch(_HE_AUTORIZACION_PRECEDENCIA_QUERY, aprobador_id, None)
    return [row["usuario_id"] for row in rows]


async def puede_autorizar_he(conn, empleado_id: UUID, aprobador_id: UUID) -> bool:
    """Fuente de verdad de los POST de autorizacion HE/compensatorio de terceros.

    Revalida en BD (nunca reutiliza una lista de UI): actor activo, bypass ADMIN global
    o RH editor/admin, autoaprobacion negada, y -via _HE_AUTORIZACION_PRECEDENCIA_QUERY,
    acotada a `empleado_id`- override de aprobador exclusivo HE vigente o, si no hay
    override, jefe directo/aprobador de vacaciones.
    """
    if empleado_id == aprobador_id:
        return False
    return bool(
        await conn.fetchval(
            f"""
            WITH actor AS (
                SELECT
                    u.rol_sistema = 'ADMIN' AS es_admin,
                    EXISTS (
                        SELECT 1 FROM tb_permisos_modulos pm
                        WHERE pm.usuario_id = u.id_usuario
                          AND pm.modulo_slug = 'rrhh'
                          AND pm.rol_modulo IN ('editor', 'admin')
                    ) AS es_rh_editor
                FROM tb_usuarios u
                WHERE u.id_usuario = $1 AND u.is_active = true
            )
            SELECT
                actor.es_admin
                OR actor.es_rh_editor
                OR EXISTS ({_HE_AUTORIZACION_PRECEDENCIA_QUERY})
            FROM actor
            """,
            aprobador_id,
            empleado_id,
        )
    )


async def get_he_saldo_usuario(
    conn, usuario_id: UUID, excluir_solicitud_pendiente_id: UUID | None = None
) -> dict:
    row = await conn.fetchrow(
        """
        WITH movimientos AS (
            SELECT
                COALESCE(SUM(minutos) FILTER (WHERE tipo = 'CREDITO'), 0)::int AS minutos_acumulados,
                COALESCE(SUM(minutos) FILTER (WHERE tipo = 'DEBITO'), 0)::int AS minutos_tomados
            FROM tb_he_bolsa_movimientos
            WHERE usuario_id = $1
        ),
        pendientes AS (
            SELECT COALESCE(SUM(minutos_solicitados), 0)::int AS minutos_en_proceso
            FROM tb_he_solicitudes_compensatorio
            WHERE usuario_id = $1
              AND estatus = 'pendiente'
              AND ($2::uuid IS NULL OR id <> $2)
        )
        SELECT
            m.minutos_acumulados,
            m.minutos_tomados,
            p.minutos_en_proceso,
            (m.minutos_acumulados - m.minutos_tomados - p.minutos_en_proceso)::int AS minutos_disponibles
        FROM movimientos m
        CROSS JOIN pendientes p
        """,
        usuario_id,
        excluir_solicitud_pendiente_id,
    )
    if not row:
        return {
            "minutos_acumulados": 0,
            "minutos_tomados": 0,
            "minutos_en_proceso": 0,
            "minutos_disponibles": 0,
        }
    return dict(row)


async def get_he_movimientos_usuario(conn, usuario_id: UUID, limit: int = 10) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT
            m.id,
            m.usuario_id,
            m.tipo,
            m.minutos,
            m.concepto,
            m.fecha_referencia,
            m.aprobacion_id,
            m.solicitud_compensatorio_id,
            m.creado_por,
            m.created_at
        FROM tb_he_bolsa_movimientos m
        WHERE m.usuario_id = $1
        ORDER BY m.fecha_referencia DESC, m.created_at DESC, m.id DESC
        LIMIT $2
        """,
        usuario_id,
        limit,
    )
    return [dict(row) for row in rows]


async def get_he_solicitudes_compensatorio_usuario(conn, usuario_id: UUID) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT
            id,
            usuario_id,
            fecha_descanso,
            minutos_solicitados,
            motivo,
            estatus,
            aprobador_id,
            comentario_aprobador,
            movimiento_id,
            fecha_solicitud,
            fecha_resolucion
        FROM tb_he_solicitudes_compensatorio
        WHERE usuario_id = $1
        ORDER BY fecha_descanso DESC, fecha_solicitud DESC
        LIMIT 20
        """,
        usuario_id,
    )
    return [dict(row) for row in rows]


async def crear_he_solicitud_compensatorio(
    conn,
    *,
    usuario_id: UUID,
    fecha_descanso: date,
    minutos_solicitados: int,
    motivo: str,
) -> dict:
    row = await conn.fetchrow(
        """
        WITH nueva AS (
            INSERT INTO tb_he_solicitudes_compensatorio
                (usuario_id, fecha_descanso, minutos_solicitados, motivo)
            VALUES ($1, $2, $3, $4)
            RETURNING *
        )
        SELECT
            nueva.id,
            nueva.usuario_id,
            nueva.fecha_descanso,
            nueva.minutos_solicitados,
            nueva.motivo,
            nueva.estatus,
            nueva.aprobador_id,
            nueva.comentario_aprobador,
            nueva.movimiento_id,
            nueva.fecha_solicitud,
            nueva.fecha_resolucion,
            u.nombre AS empleado_nombre,
            u.email AS empleado_email
        FROM nueva
        JOIN tb_usuarios u ON u.id_usuario = nueva.usuario_id
        """,
        usuario_id,
        fecha_descanso,
        minutos_solicitados,
        motivo,
    )
    return dict(row)


async def get_he_compensatorio_by_id(
    conn, solicitud_id: UUID, *, for_update: bool = False
) -> dict | None:
    row = await conn.fetchrow(
        f"""
        SELECT
            s.id,
            s.usuario_id,
            s.fecha_descanso,
            s.minutos_solicitados,
            s.motivo,
            s.estatus,
            s.aprobador_id,
            s.comentario_aprobador,
            s.movimiento_id,
            s.fecha_solicitud,
            s.fecha_resolucion,
            u.nombre AS empleado_nombre,
            u.email AS empleado_email
        FROM tb_he_solicitudes_compensatorio s
        JOIN tb_usuarios u ON u.id_usuario = s.usuario_id
        WHERE s.id = $1
        {"FOR UPDATE OF s" if for_update else ""}
        """,
        solicitud_id,
    )
    return dict(row) if row else None


async def aprobar_he_compensatorio(
    conn,
    *,
    solicitud_id: UUID,
    aprobador_id: UUID,
    comentario: str | None,
) -> dict | None:
    row = await conn.fetchrow(
        """
        WITH solicitud AS (
            SELECT id, usuario_id, fecha_descanso, minutos_solicitados
            FROM tb_he_solicitudes_compensatorio
            WHERE id = $1
              AND estatus = 'pendiente'
            FOR UPDATE
        ),
        mov AS (
            INSERT INTO tb_he_bolsa_movimientos
                (usuario_id, tipo, minutos, concepto, fecha_referencia, solicitud_compensatorio_id, creado_por)
            SELECT usuario_id,
                   'DEBITO',
                   minutos_solicitados,
                   'Tiempo compensatorio aprobado',
                   fecha_descanso,
                   id,
                   $2
            FROM solicitud
            ON CONFLICT DO NOTHING
            RETURNING id, solicitud_compensatorio_id
        )
        UPDATE tb_he_solicitudes_compensatorio s
        SET estatus = 'aprobado',
            aprobador_id = $2,
            comentario_aprobador = NULLIF($3, ''),
            fecha_resolucion = now(),
            movimiento_id = mov.id,
            updated_at = now()
        FROM mov
        WHERE s.id = mov.solicitud_compensatorio_id
        RETURNING s.*
        """,
        solicitud_id,
        aprobador_id,
        comentario,
    )
    return dict(row) if row else None


async def rechazar_he_compensatorio(
    conn,
    *,
    solicitud_id: UUID,
    aprobador_id: UUID,
    comentario: str,
) -> dict | None:
    row = await conn.fetchrow(
        """
        UPDATE tb_he_solicitudes_compensatorio
        SET estatus = 'rechazado',
            aprobador_id = $2,
            comentario_aprobador = $3,
            fecha_resolucion = now(),
            updated_at = now()
        WHERE id = $1
          AND estatus = 'pendiente'
        RETURNING *
        """,
        solicitud_id,
        aprobador_id,
        comentario,
    )
    return dict(row) if row else None


async def cancelar_he_compensatorio(
    conn,
    *,
    solicitud_id: UUID,
    usuario_id: UUID,
) -> dict | None:
    row = await conn.fetchrow(
        """
        UPDATE tb_he_solicitudes_compensatorio
        SET estatus = 'cancelado',
            fecha_resolucion = now(),
            updated_at = now()
        WHERE id = $1
          AND usuario_id = $2
          AND estatus = 'pendiente'
        RETURNING *
        """,
        solicitud_id,
        usuario_id,
    )
    return dict(row) if row else None


async def get_he_compensatorio_pendientes(conn, usuario_ids: list[UUID] | None = None) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT
            s.id,
            s.usuario_id,
            s.fecha_descanso,
            s.minutos_solicitados,
            s.motivo,
            s.estatus,
            s.fecha_solicitud,
            u.nombre AS empleado_nombre,
            u.email AS empleado_email
        FROM tb_he_solicitudes_compensatorio s
        JOIN tb_usuarios u ON u.id_usuario = s.usuario_id
        WHERE s.estatus = 'pendiente'
          AND ($1::uuid[] IS NULL OR s.usuario_id = ANY($1::uuid[]))
        ORDER BY s.fecha_solicitud, u.nombre
        """,
        usuario_ids,
    )
    return [dict(row) for row in rows]


async def get_he_compensatorio_activo_en_rango(
    conn,
    usuario_id: UUID,
    fecha_inicio: date,
    fecha_fin: date,
) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT id, usuario_id, fecha_descanso, minutos_solicitados, estatus
        FROM tb_he_solicitudes_compensatorio
        WHERE usuario_id = $1
          AND fecha_descanso >= $2
          AND fecha_descanso <= $3
          AND estatus IN ('pendiente', 'aprobado')
        ORDER BY fecha_descanso
        """,
        usuario_id,
        fecha_inicio,
        fecha_fin,
    )
    return [dict(row) for row in rows]


async def get_he_compensatorio_aprobado_por_fechas(
    conn,
    usuario_ids: list[UUID],
    fecha_inicio: date,
    fecha_fin: date,
) -> list[dict]:
    if not usuario_ids:
        return []
    rows = await conn.fetch(
        """
        SELECT id, usuario_id, fecha_descanso, minutos_solicitados
        FROM tb_he_solicitudes_compensatorio
        WHERE usuario_id = ANY($1::uuid[])
          AND fecha_descanso >= $2
          AND fecha_descanso <= $3
          AND estatus = 'aprobado'
        """,
        usuario_ids,
        fecha_inicio,
        fecha_fin,
    )
    return [dict(row) for row in rows]


async def get_horas_extra_estado_en_fecha(
    conn, usuario_id: UUID, fecha_laboral: date
) -> str | None:
    return await conn.fetchval(
        """
        SELECT horas_extra_estado
        FROM tb_asistencia_diaria
        WHERE usuario_id = $1
          AND fecha_laboral = $2
        """,
        usuario_id,
        fecha_laboral,
    )


async def get_saldo_inicial_pendientes(
    conn, usuario_ids: list[UUID] | None = None, *, fecha_corte: date
) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT
            u.id_usuario,
            u.nombre,
            u.email,
            ed.fecha_contratacion
        FROM tb_usuarios u
        LEFT JOIN tb_empleados_datos ed ON ed.usuario_id = u.id_usuario
        LEFT JOIN tb_he_saldo_inicial_confirmaciones c ON c.usuario_id = u.id_usuario
        WHERE u.is_active = true
          AND c.usuario_id IS NULL
          AND ($1::uuid[] IS NULL OR u.id_usuario = ANY($1::uuid[]))
          AND (ed.fecha_contratacion IS NULL OR ed.fecha_contratacion <= $2)
        ORDER BY u.nombre
        """,
        usuario_ids,
        fecha_corte,
    )
    return [dict(row) for row in rows]


async def confirmar_saldo_inicial(
    conn,
    *,
    usuario_id: UUID,
    minutos: int,
    confirmado_por: UUID,
    fecha_corte: date,
) -> dict:
    row = await conn.fetchrow(
        """
        WITH mov AS (
            INSERT INTO tb_he_bolsa_movimientos
                (usuario_id, tipo, minutos, concepto, fecha_referencia, creado_por)
            SELECT $1, 'CREDITO', $2, 'Saldo inicial', $4, $3
            WHERE $2 > 0
            RETURNING id
        )
        INSERT INTO tb_he_saldo_inicial_confirmaciones
            (usuario_id, minutos, confirmado_por, movimiento_id)
        VALUES ($1, $2, $3, (SELECT id FROM mov))
        RETURNING *
        """,
        usuario_id,
        minutos,
        confirmado_por,
        fecha_corte,
    )
    return dict(row)


async def crear_he_ajuste_manual(
    conn,
    *,
    usuario_id: UUID,
    tipo: str,
    minutos: int,
    concepto: str,
    fecha_referencia: date,
    creado_por: UUID,
) -> UUID:
    row = await conn.fetchrow(
        """
        INSERT INTO tb_he_bolsa_movimientos
            (usuario_id, tipo, minutos, concepto, fecha_referencia, creado_por)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id
        """,
        usuario_id,
        tipo,
        minutos,
        concepto,
        fecha_referencia,
        creado_por,
    )
    return row["id"]


async def insertar_he_evidencia(
    conn,
    *,
    upload_result: dict,
    usuario_id: UUID,
    asistencia_id: UUID,
    subido_por_id: UUID,
    content_type: str,
    tamano_bytes: int,
) -> UUID:
    doc_id = uuid4()
    parent_ref = upload_result.get("parentReference") or {}
    metadata = {
        "id_asistencia": str(asistencia_id),
        "usuario_id": str(usuario_id),
        "content_type": content_type,
    }
    await conn.execute(
        """
        INSERT INTO tb_documentos_attachments (
            id_documento,
            nombre_archivo,
            url_sharepoint,
            drive_item_id,
            parent_drive_id,
            tipo_contenido,
            tamano_bytes,
            subido_por_id,
            origen_slug,
            activo,
            metadata
        )
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'he_evidencia',true,$9::jsonb)
        """,
        doc_id,
        upload_result.get("name", ""),
        upload_result.get("webUrl", ""),
        upload_result.get("id", ""),
        parent_ref.get("driveId"),
        content_type,
        tamano_bytes,
        subido_por_id,
        json.dumps(metadata),
    )
    return doc_id


async def get_he_evidencias_for_aprobador(conn, asistencia_ids: list[UUID]) -> dict[str, list[dict]]:
    if not asistencia_ids:
        return {}
    ids_text = [str(item) for item in asistencia_ids]
    rows = await conn.fetch(
        """
        SELECT id_documento, nombre_archivo, tipo_contenido, tamano_bytes, drive_item_id, metadata
        FROM tb_documentos_attachments
        WHERE origen_slug = 'he_evidencia'
          AND activo = true
          AND metadata->>'id_asistencia' = ANY($1::text[])
        ORDER BY fecha_subida
        """,
        ids_text,
    )
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        item = dict(row)
        metadata = item.get("metadata") or {}
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except (json.JSONDecodeError, TypeError):
                metadata = {}
        grouped.setdefault(metadata.get("id_asistencia"), []).append(item)
    return grouped


async def get_he_evidencia_for_preview(conn, documento_id: UUID) -> dict | None:
    row = await conn.fetchrow(
        """
        SELECT
            d.id_documento,
            d.nombre_archivo,
            d.tipo_contenido,
            d.tamano_bytes,
            d.drive_item_id,
            d.metadata,
            (d.metadata->>'usuario_id')::uuid AS usuario_id,
            (d.metadata->>'id_asistencia')::uuid AS asistencia_id
        FROM tb_documentos_attachments d
        WHERE d.id_documento = $1
          AND d.origen_slug = 'he_evidencia'
          AND d.activo = true
        """,
        documento_id,
    )
    return dict(row) if row else None


async def get_he_reporte_usuarios(conn, usuario_ids: list[UUID]) -> list[dict]:
    if not usuario_ids:
        return []
    rows = await conn.fetch(
        """
        SELECT
            u.id_usuario,
            u.nombre,
            u.email,
            jefes.jefes_nombres
        FROM tb_usuarios u
        LEFT JOIN LATERAL (
            SELECT string_agg(j.nombre, ', ' ORDER BY j.nombre) AS jefes_nombres
            FROM tb_empleados_jefes ej
            JOIN tb_usuarios j ON j.id_usuario = ej.jefe_id
            WHERE ej.empleado_id = u.id_usuario
        ) jefes ON true
        WHERE u.id_usuario = ANY($1::uuid[])
        ORDER BY u.nombre
        """,
        usuario_ids,
    )
    return [dict(row) for row in rows]


async def get_he_saldo_reporte(conn, usuario_ids: list[UUID]) -> dict[UUID, dict]:
    if not usuario_ids:
        return {}
    rows = await conn.fetch(
        """
        SELECT
            usuario_id,
            COALESCE(SUM(minutos) FILTER (WHERE tipo = 'CREDITO'), 0)::int AS minutos_acumulados,
            COALESCE(SUM(minutos) FILTER (WHERE tipo = 'DEBITO'), 0)::int AS minutos_tomados
        FROM tb_he_bolsa_movimientos
        WHERE usuario_id = ANY($1::uuid[])
        GROUP BY usuario_id
        """,
        usuario_ids,
    )
    result = {}
    for row in rows:
        item = dict(row)
        item["minutos_disponibles"] = item["minutos_acumulados"] - item["minutos_tomados"]
        result[item["usuario_id"]] = item
    return result


async def get_usuario_ids_con_he_aprobada(conn, usuario_ids: list[UUID]) -> list[UUID]:
    """Subconjunto de `usuario_ids` con al menos un credito (HE aprobada) en la bolsa."""
    if not usuario_ids:
        return []
    rows = await conn.fetch(
        """
        SELECT DISTINCT usuario_id
        FROM tb_he_bolsa_movimientos
        WHERE usuario_id = ANY($1::uuid[]) AND tipo = 'CREDITO'
        """,
        usuario_ids,
    )
    return [row["usuario_id"] for row in rows]


async def get_he_movimientos_reporte(conn, usuario_ids: list[UUID]) -> list[dict]:
    if not usuario_ids:
        return []
    rows = await conn.fetch(
        """
        SELECT
            id,
            usuario_id,
            tipo,
            minutos,
            concepto,
            fecha_referencia,
            created_at,
            SUM(CASE WHEN tipo = 'CREDITO' THEN minutos ELSE -minutos END)
                OVER (
                    PARTITION BY usuario_id
                    ORDER BY fecha_referencia, created_at, id
                    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                )::int AS saldo_despues
        FROM tb_he_bolsa_movimientos
        WHERE usuario_id = ANY($1::uuid[])
        ORDER BY usuario_id, fecha_referencia, created_at, id
        """,
        usuario_ids,
    )
    return [dict(row) for row in rows]


async def get_he_feriados_reporte(conn, usuario_ids: list[UUID]) -> list[dict]:
    if not usuario_ids:
        return []
    rows = await conn.fetch(
        """
        SELECT
            ad.id,
            ad.usuario_id,
            ad.fecha_laboral AS fecha_referencia,
            ad.minutos_extra,
            'FERIADO PAGO ECONOMICO'::text AS concepto
        FROM tb_asistencia_diaria ad
        WHERE ad.usuario_id = ANY($1::uuid[])
          AND ad.horas_extra_estado = 'feriado'
          AND ad.minutos_extra > 0
        ORDER BY ad.usuario_id, ad.fecha_laboral, ad.id
        """,
        usuario_ids,
    )
    return [dict(row) for row in rows]


async def get_he_nivel_usuario(conn, usuario_id: UUID, anio: int) -> dict | None:
    row = await conn.fetchrow(
        """
        WITH total AS (
            SELECT COALESCE(SUM(minutos), 0)::int AS minutos
            FROM tb_he_bolsa_movimientos
            WHERE usuario_id = $1
              AND tipo = 'CREDITO'
              AND aprobacion_id IS NOT NULL
              AND EXTRACT(YEAR FROM fecha_referencia)::int = $2
        ),
        nivel_actual AS (
            SELECT n.*, total.minutos
            FROM total
            JOIN tb_cat_he_niveles n ON n.umbral_horas <= FLOOR(total.minutos / 60.0)
            WHERE total.minutos > 0
              AND n.activo = true
            ORDER BY n.umbral_horas DESC
            LIMIT 1
        ),
        siguiente AS (
            SELECT n.umbral_horas
            FROM tb_cat_he_niveles n, nivel_actual a
            WHERE n.umbral_horas > a.umbral_horas
              AND n.activo = true
            ORDER BY n.umbral_horas
            LIMIT 1
        )
        SELECT
            a.nivel,
            a.nombre,
            a.color_hex,
            FLOOR(a.minutos / 60.0)::int AS horas_actuales,
            GREATEST(0, COALESCE(s.umbral_horas, FLOOR(a.minutos / 60.0)::int) - FLOOR(a.minutos / 60.0)::int) AS horas_faltantes,
            (s.umbral_horas IS NULL) AS es_maximo
        FROM nivel_actual a
        LEFT JOIN siguiente s ON true
        """,
        usuario_id,
        anio,
    )
    return dict(row) if row else None


async def get_he_niveles_equipo(conn, usuario_ids: list[UUID], anio: int) -> list[dict]:
    if not usuario_ids:
        return []
    rows = await conn.fetch(
        """
        WITH total AS (
            SELECT usuario_id, COALESCE(SUM(minutos), 0)::int AS minutos
            FROM tb_he_bolsa_movimientos
            WHERE usuario_id = ANY($1::uuid[])
              AND tipo = 'CREDITO'
              AND aprobacion_id IS NOT NULL
              AND EXTRACT(YEAR FROM fecha_referencia)::int = $2
            GROUP BY usuario_id
            HAVING COALESCE(SUM(minutos), 0) > 0
        ),
        nivel_actual AS (
            SELECT DISTINCT ON (t.usuario_id)
                t.usuario_id,
                u.nombre AS empleado_nombre,
                n.nivel,
                n.nombre,
                n.color_hex,
                FLOOR(t.minutos / 60.0)::int AS horas_actuales,
                n.umbral_horas
            FROM total t
            JOIN tb_usuarios u ON u.id_usuario = t.usuario_id
            JOIN tb_cat_he_niveles n ON n.umbral_horas <= FLOOR(t.minutos / 60.0)
            WHERE n.activo = true
            ORDER BY t.usuario_id, n.umbral_horas DESC
        )
        SELECT
            a.*,
            GREATEST(0, COALESCE(s.umbral_horas, a.horas_actuales) - a.horas_actuales) AS horas_faltantes,
            (s.umbral_horas IS NULL) AS es_maximo
        FROM nivel_actual a
        LEFT JOIN LATERAL (
            SELECT n.umbral_horas
            FROM tb_cat_he_niveles n
            WHERE n.umbral_horas > a.umbral_horas
              AND n.activo = true
            ORDER BY n.umbral_horas
            LIMIT 1
        ) s ON true
        ORDER BY a.empleado_nombre
        """,
        usuario_ids,
        anio,
    )
    return [dict(row) for row in rows]


async def get_he_niveles_catalogo(conn) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT nivel, nombre, umbral_horas, color_hex
        FROM tb_cat_he_niveles
        WHERE activo = true
        ORDER BY umbral_horas
        """
    )
    return [dict(row) for row in rows]


async def get_datos_resolucion_notificacion_he(conn, usuario_id: UUID) -> dict:
    """Todo lo necesario para el resolver unico de destinatarios HE/compensatorio en un round trip:
    aprobador exclusivo (si existe) + su estado, jefes activos + si alguno es director, aprobador de
    vacaciones activo, y el fallback RH editor/admin + ADMIN global con correo."""
    row = await conn.fetchrow(
        f"""
        WITH base AS (
            SELECT $1::uuid AS usuario_id
        ),
        fallback AS (
            SELECT DISTINCT u.email
            FROM tb_usuarios u
            LEFT JOIN tb_permisos_modulos pm
                ON pm.usuario_id = u.id_usuario
               AND pm.modulo_slug = 'rrhh'
               AND pm.rol_modulo IN ('editor', 'admin')
            WHERE {_FALLBACK_RH_ADMIN_WHERE}
        )
        SELECT
            {_HE_OVERRIDE_SELECT_COLUMNS},
            jefes.emails AS jefe_emails,
            COALESCE(jefes.tiene_director, false) AS tiene_director,
            (SELECT array_agg(DISTINCT email) FROM fallback) AS fallback_emails
        FROM base
        {_jefe_emails_lateral_join("base.usuario_id")}
        {_he_override_lateral_join("base.usuario_id")}
        """,
        usuario_id,
    )
    return dict(row)


async def get_fallback_rh_admin_emails(conn) -> set[str]:
    """RH editor/admin activos + ADMIN global con correo — fallback de aprobador HE exclusivo inactivo.

    Mismo criterio que TasksDBService.get_active_rh_contacts (core/tasks_db_service.py) — se
    reusa ese metodo en vez de duplicar el predicado."""
    from core.tasks_db_service import get_tasks_db_service

    rows = await get_tasks_db_service().get_active_rh_contacts(conn)
    return {row["email"] for row in rows}


async def get_empleados_con_aprobador_he_exclusivo(conn, aprobador_id: UUID) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT ed.usuario_id, u.nombre AS empleado_nombre
        FROM tb_empleados_datos ed
        JOIN tb_usuarios u ON u.id_usuario = ed.usuario_id
        WHERE ed.id_aprobador_horas_extra = $1
        """,
        aprobador_id,
    )
    return [dict(row) for row in rows]


async def verificar_fallback_aprobador_he(conn, *, user_id: UUID, sera_fallback_despues: bool) -> dict:
    """Valida que ningun empleado con aprobador HE exclusivo quede sin fallback tras un cambio
    administrativo sobre user_id (baja, cambio de rol o modulos).

    `sera_fallback_despues` indica si, tras el cambio propuesto, user_id seguira contando como
    RH editor/admin/ADMIN activo (para deactivate_user siempre False). "Afectados" incluye tanto
    los empleados cuyo aprobador exclusivo es user_id (relevante al desactivarlo) como los que ya
    dependian del fallback porque su aprobador exclusivo ya estaba inactivo (relevante si este
    cambio reduce el pool de fallback a cero).
    """
    row = await conn.fetchrow(
        f"""
        WITH afectados AS (
            SELECT ed.usuario_id
            FROM tb_empleados_datos ed
            JOIN tb_usuarios u ON u.id_usuario = ed.id_aprobador_horas_extra
            WHERE ed.id_aprobador_horas_extra IS NOT NULL
              AND (u.id_usuario = $1 OR u.is_active = false)
        ),
        fallback AS (
            SELECT DISTINCT u.id_usuario
            FROM tb_usuarios u
            LEFT JOIN tb_permisos_modulos pm
                ON pm.usuario_id = u.id_usuario
               AND pm.modulo_slug = 'rrhh'
               AND pm.rol_modulo IN ('editor', 'admin')
            WHERE {_FALLBACK_RH_ADMIN_WHERE}
              AND (u.id_usuario <> $1 OR $2::boolean)
        )
        SELECT
            (SELECT COUNT(*) FROM afectados)::int AS afectados_count,
            EXISTS (SELECT 1 FROM fallback) AS tiene_fallback
        """,
        user_id,
        sera_fallback_despues,
    )
    return dict(row)


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


async def insert_solicitud_manual(
    conn,
    *,
    usuario_id: UUID,
    fecha_laboral: date,
    solicita_entrada: bool,
    solicita_salida: bool,
    entrada_tiempo: datetime | None,
    salida_tiempo: datetime | None,
    motivo: str,
) -> dict:
    row = await conn.fetchrow(
        """
        INSERT INTO tb_asistencia_solicitudes_manuales (
            usuario_id,
            fecha_laboral,
            solicita_entrada,
            solicita_salida,
            entrada_tiempo,
            salida_tiempo,
            motivo
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING
            id,
            usuario_id,
            fecha_laboral,
            solicita_entrada,
            solicita_salida,
            entrada_tiempo,
            salida_tiempo,
            motivo,
            estado,
            revisado_por,
            comentario_revision,
            check_entrada_id,
            check_salida_id,
            created_at,
            updated_at
        """,
        usuario_id,
        fecha_laboral,
        solicita_entrada,
        solicita_salida,
        entrada_tiempo,
        salida_tiempo,
        motivo,
    )
    return dict(row)


async def get_solicitud_manual(conn, solicitud_id: UUID) -> dict | None:
    row = await conn.fetchrow(
        """
        SELECT
            s.id,
            s.usuario_id,
            s.fecha_laboral,
            s.solicita_entrada,
            s.solicita_salida,
            s.entrada_tiempo,
            s.salida_tiempo,
            s.motivo,
            s.estado,
            s.revisado_por,
            s.comentario_revision,
            s.check_entrada_id,
            s.check_salida_id,
            s.created_at,
            s.updated_at,
            u.nombre AS empleado_nombre,
            u.email AS empleado_email,
            r.nombre AS revisor_nombre
        FROM tb_asistencia_solicitudes_manuales s
        JOIN tb_usuarios u ON u.id_usuario = s.usuario_id
        LEFT JOIN tb_usuarios r ON r.id_usuario = s.revisado_por
        WHERE s.id = $1
        """,
        solicitud_id,
    )
    return dict(row) if row else None


async def get_solicitud_manual_for_update(conn, solicitud_id: UUID) -> dict | None:
    row = await conn.fetchrow(
        """
        SELECT
            s.id,
            s.usuario_id,
            s.fecha_laboral,
            s.solicita_entrada,
            s.solicita_salida,
            s.entrada_tiempo,
            s.salida_tiempo,
            s.motivo,
            s.estado,
            s.revisado_por,
            s.comentario_revision,
            s.check_entrada_id,
            s.check_salida_id,
            s.created_at,
            s.updated_at,
            u.nombre AS empleado_nombre,
            u.email AS empleado_email
        FROM tb_asistencia_solicitudes_manuales s
        JOIN tb_usuarios u ON u.id_usuario = s.usuario_id
        WHERE s.id = $1
        FOR UPDATE OF s
        """,
        solicitud_id,
    )
    return dict(row) if row else None


async def get_solicitud_manual_existente_activa(
    conn,
    usuario_id: UUID,
    fecha_laboral: date,
) -> dict | None:
    row = await conn.fetchrow(
        """
        SELECT id, estado
        FROM tb_asistencia_solicitudes_manuales
        WHERE usuario_id = $1
          AND fecha_laboral = $2
          AND estado IN ('pendiente', 'aprobado')
        ORDER BY created_at DESC
        LIMIT 1
        """,
        usuario_id,
        fecha_laboral,
    )
    return dict(row) if row else None


async def get_mis_solicitudes_manuales(
    conn,
    usuario_id: UUID,
    *,
    limit: int = 10,
) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT
            s.id,
            s.usuario_id,
            s.fecha_laboral,
            s.solicita_entrada,
            s.solicita_salida,
            s.entrada_tiempo,
            s.salida_tiempo,
            s.motivo,
            s.estado,
            s.revisado_por,
            s.comentario_revision,
            s.check_entrada_id,
            s.check_salida_id,
            s.created_at,
            s.updated_at,
            r.nombre AS revisor_nombre
        FROM tb_asistencia_solicitudes_manuales s
        LEFT JOIN tb_usuarios r ON r.id_usuario = s.revisado_por
        WHERE s.usuario_id = $1
        ORDER BY s.created_at DESC
        LIMIT $2
        """,
        usuario_id,
        limit,
    )
    return [dict(row) for row in rows]


async def count_solicitudes_manuales_pendientes_equipo(
    conn,
    usuario_ids: list[UUID],
) -> int:
    if not usuario_ids:
        return 0
    return await conn.fetchval(
        """
        SELECT COUNT(*)::int
        FROM tb_asistencia_solicitudes_manuales
        WHERE usuario_id = ANY($1::uuid[])
          AND estado = 'pendiente'
        """,
        usuario_ids,
    )


async def get_solicitudes_manuales_pendientes_todas(conn) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT
            s.id,
            s.usuario_id,
            s.fecha_laboral,
            s.solicita_entrada,
            s.solicita_salida,
            s.entrada_tiempo,
            s.salida_tiempo,
            s.motivo,
            s.estado,
            s.revisado_por,
            s.comentario_revision,
            s.check_entrada_id,
            s.check_salida_id,
            s.created_at,
            s.updated_at,
            u.nombre AS empleado_nombre,
            u.email AS empleado_email
        FROM tb_asistencia_solicitudes_manuales s
        JOIN tb_usuarios u ON u.id_usuario = s.usuario_id
        WHERE s.estado = 'pendiente'
        ORDER BY s.fecha_laboral DESC, s.created_at ASC
        """
    )
    return [dict(row) for row in rows]


async def aprobar_solicitud_manual(
    conn,
    *,
    solicitud_id: UUID,
    revisado_por: UUID,
    check_entrada_id: UUID | None,
    check_salida_id: UUID | None,
    comentario_revision: str | None = None,
) -> None:
    await conn.execute(
        """
        UPDATE tb_asistencia_solicitudes_manuales
        SET estado = 'aprobado',
            revisado_por = $2,
            comentario_revision = $5,
            check_entrada_id = $3,
            check_salida_id = $4,
            updated_at = now()
        WHERE id = $1
          AND estado = 'pendiente'
        """,
        solicitud_id,
        revisado_por,
        check_entrada_id,
        check_salida_id,
        comentario_revision,
    )


async def rechazar_solicitud_manual(
    conn,
    *,
    solicitud_id: UUID,
    revisado_por: UUID,
    comentario_revision: str,
) -> None:
    await conn.execute(
        """
        UPDATE tb_asistencia_solicitudes_manuales
        SET estado = 'rechazado',
            revisado_por = $2,
            comentario_revision = $3,
            updated_at = now()
        WHERE id = $1
          AND estado = 'pendiente'
        """,
        solicitud_id,
        revisado_por,
        comentario_revision,
    )


async def insert_manual_check(
    conn,
    *,
    usuario_id: UUID,
    biotime_emp_code: str,
    check_time: datetime,
    punch_state: str,
    solicitud_manual_id: UUID,
) -> UUID:
    row = await conn.fetchrow(
        """
        INSERT INTO tb_biotime_checks (
            biotime_transaction_id,
            biotime_emp_code,
            usuario_id,
            check_time,
            punch_state,
            verify_type,
            terminal_alias,
            raw_payload,
            es_manual,
            solicitud_manual_id
        )
        VALUES (
            NULL,
            $1,
            $2,
            $3,
            $4,
            'manual',
            'Registro manual',
            $5::jsonb,
            true,
            $6
        )
        ON CONFLICT (biotime_emp_code, check_time)
        WHERE biotime_transaction_id IS NULL
        DO UPDATE SET
            usuario_id = EXCLUDED.usuario_id,
            punch_state = EXCLUDED.punch_state,
            verify_type = EXCLUDED.verify_type,
            terminal_alias = EXCLUDED.terminal_alias,
            raw_payload = EXCLUDED.raw_payload,
            es_manual = true,
            solicitud_manual_id = EXCLUDED.solicitud_manual_id
        RETURNING id
        """,
        biotime_emp_code,
        usuario_id,
        check_time,
        punch_state,
        json.dumps({"source": "asistencia_manual", "solicitud_manual_id": str(solicitud_manual_id)}),
        solicitud_manual_id,
    )
    return row["id"]


async def get_biotime_checks_usuario_window(
    conn,
    *,
    usuario_id: UUID,
    start: datetime,
    end: datetime,
) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT
            id,
            usuario_id,
            biotime_emp_code,
            check_time,
            punch_state,
            COALESCE(es_manual, false) AS es_manual,
            solicitud_manual_id
        FROM tb_biotime_checks
        WHERE usuario_id = $1
          AND check_time >= $2
          AND check_time < $3
        ORDER BY check_time
        """,
        usuario_id,
        start,
        end,
    )
    return [dict(row) for row in rows]


async def get_biotime_emp_code_para_manual(conn, usuario_id: UUID) -> str | None:
    return await conn.fetchval(
        """
        SELECT COALESCE(
            NULLIF(TRIM(ed.biotime_emp_code), ''),
            NULLIF(TRIM(m.biotime_emp_code), '')
        )
        FROM tb_usuarios u
        LEFT JOIN tb_empleados_datos ed ON ed.usuario_id = u.id_usuario
        LEFT JOIN LATERAL (
            SELECT bm.biotime_emp_code
            FROM tb_biotime_empleado_map bm
            WHERE bm.usuario_id = u.id_usuario
              AND bm.activo = TRUE
            ORDER BY bm.last_seen_at DESC NULLS LAST, bm.updated_at DESC
            LIMIT 1
        ) m ON TRUE
        WHERE u.id_usuario = $1
        """,
        usuario_id,
    )

