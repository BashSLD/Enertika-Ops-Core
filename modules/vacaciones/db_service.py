from __future__ import annotations

from datetime import date, datetime
import json
from typing import Any, Optional
from uuid import UUID

from core.timezone import today_mx


# ─────────────────────────────────────────────
# Catálogos
# ─────────────────────────────────────────────

async def get_catalogo_dias(conn) -> list[dict]:
    rows = await conn.fetch(
        "SELECT antiguedad_anios, antiguedad_anios_fin, dias_lft, dias_enertika "
        "FROM tb_cat_dias_vacaciones WHERE is_active = true ORDER BY antiguedad_anios"
    )
    return [dict(r) for r in rows]


async def get_catalogo_dias_admin(conn) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT id, antiguedad_anios, antiguedad_anios_fin, dias_lft, dias_enertika,
               is_active, updated_at
        FROM tb_cat_dias_vacaciones
        ORDER BY antiguedad_anios, antiguedad_anios_fin NULLS LAST
        """
    )
    return [dict(r) for r in rows]


async def get_tipos_ausencia(conn) -> list[dict]:
    rows = await conn.fetch(
        "SELECT id::text AS id, nombre, slug, abreviatura, afecta_saldo, requiere_aprobacion, orden "
        "FROM tb_cat_tipos_ausencia WHERE is_active = true ORDER BY orden"
    )
    return [dict(r) for r in rows]


async def get_tipos_ausencia_admin(conn) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT id, nombre, slug, abreviatura, afecta_saldo, requiere_aprobacion,
               is_active, orden, es_sistema, updated_at
        FROM tb_cat_tipos_ausencia
        ORDER BY orden, nombre
        """
    )
    return [dict(r) for r in rows]


async def get_tipo_ausencia_by_id(conn, tipo_id: UUID) -> Optional[dict]:
    row = await conn.fetchrow(
        "SELECT id, nombre, slug, abreviatura, afecta_saldo, requiere_aprobacion "
        "FROM tb_cat_tipos_ausencia WHERE id = $1",
        tipo_id,
    )
    return dict(row) if row else None


async def get_festivos(conn) -> list[dict]:
    rows = await conn.fetch(
        "SELECT id, fecha, descripcion, es_oficial, origen FROM tb_cat_festivos ORDER BY fecha"
    )
    return [dict(r) for r in rows]


async def get_festivos_by_year(conn, anio: int) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT id, fecha, descripcion, es_oficial, origen, updated_at
        FROM tb_cat_festivos
        WHERE EXTRACT(YEAR FROM fecha)::int = $1
        ORDER BY fecha
        """,
        anio,
    )
    return [dict(r) for r in rows]


async def get_festivo_by_id(conn, festivo_id: UUID) -> Optional[dict]:
    row = await conn.fetchrow(
        """
        SELECT id, fecha, descripcion, es_oficial, origen, updated_at
        FROM tb_cat_festivos
        WHERE id = $1
        """,
        festivo_id,
    )
    return dict(row) if row else None


async def get_festivos_validacion(conn, anio: int) -> Optional[dict]:
    row = await conn.fetchrow(
        """
        SELECT v.id, v.anio, v.estado, v.notas, v.validado_at, v.validado_by,
               v.created_at, v.updated_at, v.updated_by,
               u.nombre AS validado_por_nombre
        FROM tb_rrhh_festivos_validacion v
        LEFT JOIN tb_usuarios u ON u.id_usuario = v.validado_by
        WHERE v.anio = $1
        """,
        anio,
    )
    return dict(row) if row else None


async def mark_festivos_validacion_pendiente(
    conn,
    anio: int,
    updated_by: Optional[UUID] = None,
) -> dict:
    row = await conn.fetchrow(
        """
        INSERT INTO tb_rrhh_festivos_validacion
            (anio, estado, updated_by, updated_at)
        VALUES ($1, 'pendiente', $2, now())
        ON CONFLICT (anio) DO UPDATE SET
            estado = 'pendiente',
            notas = NULL,
            validado_at = NULL,
            validado_by = NULL,
            updated_by = $2,
            updated_at = now()
        RETURNING id, anio, estado, notas, validado_at, validado_by,
                  created_at, updated_at, updated_by
        """,
        anio, updated_by,
    )
    return dict(row)


async def validar_festivos_anio(
    conn,
    anio: int,
    notas: Optional[str],
    user_id: UUID,
) -> dict:
    row = await conn.fetchrow(
        """
        INSERT INTO tb_rrhh_festivos_validacion
            (anio, estado, notas, validado_at, validado_by, updated_by, updated_at)
        VALUES ($1, 'validado', $2, now(), $3, $3, now())
        ON CONFLICT (anio) DO UPDATE SET
            estado = 'validado',
            notas = $2,
            validado_at = now(),
            validado_by = $3,
            updated_by = $3,
            updated_at = now()
        RETURNING id, anio, estado, notas, validado_at, validado_by,
                  created_at, updated_at, updated_by
        """,
        anio, notas, user_id,
    )
    return dict(row)


async def get_festivos_set(conn) -> set[date]:
    rows = await conn.fetch("SELECT fecha FROM tb_cat_festivos")
    return {r["fecha"] for r in rows}


async def create_festivo(conn, fecha: date, descripcion: str, es_oficial: bool, created_by: UUID) -> dict:
    row = await conn.fetchrow(
        """
        INSERT INTO tb_cat_festivos
            (fecha, descripcion, es_oficial, created_by, updated_by, updated_at, origen)
        VALUES ($1, $2, $3, $4, $4, now(), 'manual')
        RETURNING id, fecha, descripcion, es_oficial, origen
        """,
        fecha, descripcion, es_oficial, created_by,
    )
    return dict(row)


async def update_festivo(
    conn,
    festivo_id: UUID,
    fecha: date,
    descripcion: str,
    es_oficial: bool,
    updated_by: UUID,
) -> Optional[dict]:
    row = await conn.fetchrow(
        """
        UPDATE tb_cat_festivos
        SET fecha = $2,
            descripcion = $3,
            es_oficial = $4,
            updated_by = $5,
            updated_at = now(),
            origen = 'manual'
        WHERE id = $1
        RETURNING id, fecha, descripcion, es_oficial, origen
        """,
        festivo_id, fecha, descripcion, es_oficial, updated_by,
    )
    return dict(row) if row else None


async def insert_festivos_generados(conn, feriados: list[dict], created_by: Optional[UUID] = None) -> int:
    inserted = 0
    for feriado in feriados:
        row = await conn.fetchrow(
            """
            INSERT INTO tb_cat_festivos
                (fecha, descripcion, es_oficial, created_by, updated_by, updated_at, origen)
            VALUES ($1, $2, $3, $4, $4, now(), 'automatico')
            ON CONFLICT (fecha) DO NOTHING
            RETURNING id
            """,
            feriado["fecha"], feriado["descripcion"], feriado["es_oficial"], created_by,
        )
        if row:
            inserted += 1
    return inserted


async def delete_festivo(conn, festivo_id: UUID) -> bool:
    result = await conn.execute("DELETE FROM tb_cat_festivos WHERE id = $1", festivo_id)
    return result == "DELETE 1"


async def create_tipo_ausencia(
    conn,
    nombre: str,
    slug: str,
    abreviatura: str,
    afecta_saldo: bool,
    requiere_aprobacion: bool,
    is_active: bool,
    orden: int,
    updated_by: UUID,
) -> dict:
    row = await conn.fetchrow(
        """
        INSERT INTO tb_cat_tipos_ausencia
            (nombre, slug, abreviatura, afecta_saldo, requiere_aprobacion,
             is_active, orden, updated_by, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, now())
        RETURNING id, nombre, slug, abreviatura, afecta_saldo, requiere_aprobacion,
                  is_active, orden, es_sistema
        """,
        nombre, slug, abreviatura, afecta_saldo, requiere_aprobacion,
        is_active, orden, updated_by,
    )
    return dict(row)


async def update_tipo_ausencia(
    conn,
    tipo_id: UUID,
    nombre: str,
    abreviatura: str,
    afecta_saldo: bool,
    requiere_aprobacion: bool,
    is_active: bool,
    orden: int,
    updated_by: UUID,
) -> Optional[dict]:
    row = await conn.fetchrow(
        """
        UPDATE tb_cat_tipos_ausencia
        SET nombre = $2,
            abreviatura = $3,
            afecta_saldo = $4,
            requiere_aprobacion = $5,
            is_active = $6,
            orden = $7,
            updated_by = $8,
            updated_at = now()
        WHERE id = $1
        RETURNING id, nombre, slug, abreviatura, afecta_saldo, requiere_aprobacion,
                  is_active, orden, es_sistema
        """,
        tipo_id, nombre, abreviatura, afecta_saldo, requiere_aprobacion,
        is_active, orden, updated_by,
    )
    return dict(row) if row else None


async def get_tipo_ausencia_admin_by_id(conn, tipo_id: UUID) -> Optional[dict]:
    row = await conn.fetchrow(
        """
        SELECT id, nombre, slug, abreviatura, afecta_saldo, requiere_aprobacion,
               is_active, orden, es_sistema
        FROM tb_cat_tipos_ausencia
        WHERE id = $1
        """,
        tipo_id,
    )
    return dict(row) if row else None


async def create_dias_vacaciones(
    conn,
    antiguedad_anios: int,
    antiguedad_anios_fin: Optional[int],
    dias_lft: int,
    dias_enertika: int,
    is_active: bool,
    updated_by: UUID,
) -> dict:
    row = await conn.fetchrow(
        """
        INSERT INTO tb_cat_dias_vacaciones
            (antiguedad_anios, antiguedad_anios_fin, dias_lft, dias_enertika,
             is_active, updated_by, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, now())
        RETURNING id, antiguedad_anios, antiguedad_anios_fin, dias_lft,
                  dias_enertika, is_active
        """,
        antiguedad_anios, antiguedad_anios_fin, dias_lft, dias_enertika,
        is_active, updated_by,
    )
    return dict(row)


async def update_dias_vacaciones(
    conn,
    row_id: UUID,
    antiguedad_anios: int,
    antiguedad_anios_fin: Optional[int],
    dias_lft: int,
    dias_enertika: int,
    is_active: bool,
    updated_by: UUID,
) -> Optional[dict]:
    row = await conn.fetchrow(
        """
        UPDATE tb_cat_dias_vacaciones
        SET antiguedad_anios = $2,
            antiguedad_anios_fin = $3,
            dias_lft = $4,
            dias_enertika = $5,
            is_active = $6,
            updated_by = $7,
            updated_at = now()
        WHERE id = $1
        RETURNING id, antiguedad_anios, antiguedad_anios_fin, dias_lft,
                  dias_enertika, is_active
        """,
        row_id, antiguedad_anios, antiguedad_anios_fin, dias_lft,
        dias_enertika, is_active, updated_by,
    )
    return dict(row) if row else None


async def get_dias_vacaciones_by_id(conn, row_id: UUID) -> Optional[dict]:
    row = await conn.fetchrow(
        """
        SELECT id, antiguedad_anios, antiguedad_anios_fin, dias_lft,
               dias_enertika, is_active
        FROM tb_cat_dias_vacaciones
        WHERE id = $1
        """,
        row_id,
    )
    return dict(row) if row else None


# ─────────────────────────────────────────────
# Datos laborales de empleado
# ─────────────────────────────────────────────

async def get_empleado_datos(conn, usuario_id: UUID) -> Optional[dict]:
    row = await conn.fetchrow(
        "SELECT id, usuario_id, numero_empleado, fecha_contratacion, puesto, departamento, "
        "id_aprobador_vacaciones, dias_vacaciones_ajuste, sucursal_id, biotime_emp_code "
        "FROM tb_empleados_datos WHERE usuario_id = $1",
        usuario_id,
    )
    return dict(row) if row else None


async def upsert_empleado_datos(
    conn,
    usuario_id: UUID,
    numero_empleado: Optional[str],
    fecha_contratacion: Optional[date],
    puesto: Optional[str],
    departamento: Optional[str],
    id_aprobador_vacaciones: Optional[UUID],
    dias_vacaciones_ajuste: Optional[int],
    sucursal_id: Optional[UUID],
    updated_by: UUID,
) -> dict:
    row = await conn.fetchrow(
        """
        INSERT INTO tb_empleados_datos
            (usuario_id, numero_empleado, fecha_contratacion, puesto, departamento,
             id_aprobador_vacaciones, dias_vacaciones_ajuste, sucursal_id, updated_by, updated_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,now())
        ON CONFLICT (usuario_id) DO UPDATE SET
            numero_empleado           = EXCLUDED.numero_empleado,
            fecha_contratacion        = EXCLUDED.fecha_contratacion,
            puesto                    = EXCLUDED.puesto,
            departamento              = EXCLUDED.departamento,
            id_aprobador_vacaciones   = EXCLUDED.id_aprobador_vacaciones,
            dias_vacaciones_ajuste    = COALESCE(EXCLUDED.dias_vacaciones_ajuste, tb_empleados_datos.dias_vacaciones_ajuste),
            sucursal_id               = EXCLUDED.sucursal_id,
            updated_by                = EXCLUDED.updated_by,
            updated_at                = now()
        RETURNING id, usuario_id, numero_empleado, fecha_contratacion, puesto,
                  departamento, id_aprobador_vacaciones, dias_vacaciones_ajuste,
                  sucursal_id
        """,
        usuario_id, numero_empleado, fecha_contratacion, puesto, departamento,
        id_aprobador_vacaciones, dias_vacaciones_ajuste, sucursal_id, updated_by,
    )
    return dict(row)


async def get_jefes_ids(conn, usuario_id: UUID) -> list[UUID]:
    rows = await conn.fetch(
        "SELECT jefe_id FROM tb_empleados_jefes WHERE empleado_id = $1", usuario_id
    )
    return [r["jefe_id"] for r in rows]


async def set_jefes(conn, usuario_id: UUID, jefes_ids: list[UUID]) -> None:
    await conn.execute("DELETE FROM tb_empleados_jefes WHERE empleado_id = $1", usuario_id)
    if jefes_ids:
        await conn.executemany(
            "INSERT INTO tb_empleados_jefes (empleado_id, jefe_id) VALUES ($1, $2) "
            "ON CONFLICT (empleado_id, jefe_id) DO NOTHING",
            [(usuario_id, jefe_id) for jefe_id in jefes_ids],
        )


async def get_empleados_donde_soy_jefe(conn, jefe_id: UUID) -> list[UUID]:
    rows = await conn.fetch(
        "SELECT empleado_id FROM tb_empleados_jefes WHERE jefe_id = $1", jefe_id
    )
    return [r["empleado_id"] for r in rows]


async def get_empleados_donde_soy_aprobador(conn, aprobador_id: UUID) -> list[UUID]:
    rows = await conn.fetch(
        "SELECT usuario_id FROM tb_empleados_datos WHERE id_aprobador_vacaciones = $1",
        aprobador_id,
    )
    return [r["usuario_id"] for r in rows]


async def get_all_empleados_con_datos(
    conn,
    limit: int = 20,
    offset: int = 0,
    sucursal_ids: list | None = None,
    usuario_ids: list | None = None,
    incluir_dados_de_baja: bool = False,
) -> list[dict]:
    conditions = ["($3::bool = true OR u.is_active = true)"]
    params: list = [limit, offset, incluir_dados_de_baja]
    if sucursal_ids:
        params.append(sucursal_ids)
        conditions.append(f"e.sucursal_id = ANY(${len(params)}::uuid[])")
    if usuario_ids:
        params.append(usuario_ids)
        conditions.append(f"u.id_usuario = ANY(${len(params)}::uuid[])")
    where = " AND ".join(conditions)
    rows = await conn.fetch(
        f"""
        SELECT u.id_usuario, u.nombre, u.email, u.department,
               e.numero_empleado, e.fecha_contratacion, e.puesto, e.departamento,
               e.id_aprobador_vacaciones, e.dias_vacaciones_ajuste,
               a.nombre AS aprobador_nombre,
               s.nombre AS sucursal_nombre
        FROM tb_usuarios u
        LEFT JOIN tb_empleados_datos e ON e.usuario_id = u.id_usuario
        LEFT JOIN tb_usuarios a ON a.id_usuario = e.id_aprobador_vacaciones
        LEFT JOIN tb_cat_sucursales s ON s.id = e.sucursal_id
        WHERE {where}
        ORDER BY u.nombre
        LIMIT $1 OFFSET $2
        """,
        *params,
    )
    return [dict(r) for r in rows]


async def get_empleados_balance_base(conn, usuario_ids: list[UUID]) -> list[dict]:
    if not usuario_ids:
        return []
    rows = await conn.fetch(
        """
        SELECT u.id_usuario, u.nombre, u.email,
               e.id AS empleado_datos_id,
               e.numero_empleado, e.fecha_contratacion, e.puesto, e.departamento,
               e.id_aprobador_vacaciones,
               COALESCE(e.dias_vacaciones_ajuste, 0) AS dias_vacaciones_ajuste
        FROM tb_usuarios u
        LEFT JOIN tb_empleados_datos e ON e.usuario_id = u.id_usuario
        WHERE u.id_usuario = ANY($1::uuid[])
          AND u.is_active = true
        ORDER BY u.nombre
        """,
        usuario_ids,
    )
    return [dict(r) for r in rows]


async def count_empleados(conn) -> int:
    return await conn.fetchval(
        "SELECT COUNT(*) FROM tb_usuarios WHERE is_active = true"
    )


# ─────────────────────────────────────────────
# Migracion historica de vacaciones
# ─────────────────────────────────────────────

async def get_empleados_para_migracion(conn) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT
            u.id_usuario,
            u.nombre,
            u.email,
            e.fecha_contratacion,
            COALESCE(e.dias_vacaciones_ajuste, 0) AS dias_vacaciones_ajuste,
            EXISTS (
                SELECT 1
                FROM tb_solicitudes_ausencia sa
                WHERE sa.usuario_id = u.id_usuario
                  AND sa.es_migracion = TRUE
            ) AS ya_migrado
        FROM tb_usuarios u
        JOIN tb_empleados_datos e ON e.usuario_id = u.id_usuario
        WHERE u.is_active = true
          AND e.fecha_contratacion IS NOT NULL
        ORDER BY u.nombre
        """
    )
    return [dict(r) for r in rows]


async def count_empleados_migrados(conn) -> dict:
    row = await conn.fetchrow(
        """
        SELECT
            COUNT(DISTINCT e.usuario_id) AS total_con_contratacion,
            COUNT(DISTINCT e.usuario_id) FILTER (WHERE sa.usuario_id IS NOT NULL) AS total_migrados
        FROM tb_empleados_datos e
        JOIN tb_usuarios u ON u.id_usuario = e.usuario_id
        LEFT JOIN tb_solicitudes_ausencia sa
            ON sa.usuario_id = e.usuario_id
           AND sa.es_migracion = TRUE
        WHERE u.is_active = true
          AND e.fecha_contratacion IS NOT NULL
        """
    )
    if not row:
        return {"total_con_contratacion": 0, "total_migrados": 0}
    return dict(row)


async def limpiar_migracion_usuario(conn, usuario_id: UUID) -> int:
    deleted = await conn.fetchval(
        """
        WITH deleted AS (
            DELETE FROM tb_solicitudes_ausencia
            WHERE usuario_id = $1
              AND es_migracion = TRUE
            RETURNING id
        )
        SELECT COUNT(*) FROM deleted
        """,
        usuario_id,
    )
    return int(deleted or 0)


async def insertar_solicitud_migracion(
    conn,
    usuario_id: UUID,
    tipo_ausencia_id: UUID,
    fecha_aniversario: date,
    dias_solicitados: int,
    num_periodo: int,
    ejecutado_por: UUID,
) -> UUID:
    row = await conn.fetchrow(
        """
        INSERT INTO tb_solicitudes_ausencia
            (usuario_id, tipo_ausencia_id, fecha_inicio, fecha_fin,
             dias_solicitados, fecha_presentarse, observaciones,
             firma_solicitante_pendiente, estado, aprobado_por,
             fecha_resolucion, es_migracion, migrado_por)
        VALUES ($1, $2, $3, $3, $4, $3, $5, false, 'aprobado', $6, now(), true, $6)
        RETURNING id
        """,
        usuario_id,
        tipo_ausencia_id,
        fecha_aniversario,
        dias_solicitados,
        f"Registro historico previo al sistema - Periodo {num_periodo}",
        ejecutado_por,
    )
    return row["id"]


async def get_migracion_usuario(conn, usuario_id: UUID) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT
            sa.id,
            sa.dias_solicitados,
            sa.observaciones,
            sa.fecha_solicitud,
            sa.fecha_resolucion,
            sa.migrado_por,
            m.nombre AS migrado_por_nombre,
            vc.num_periodo,
            vc.dias_consumidos,
            vc.fecha_aniversario_periodo
        FROM tb_solicitudes_ausencia sa
        JOIN tb_vacaciones_consumo vc ON vc.solicitud_id = sa.id
        LEFT JOIN tb_usuarios m ON m.id_usuario = sa.migrado_por
        WHERE sa.usuario_id = $1
          AND sa.es_migracion = TRUE
        ORDER BY vc.num_periodo
        """,
        usuario_id,
    )
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────
# Firmas
# ─────────────────────────────────────────────

async def insert_firma_solicitud(conn, solicitud_id: UUID, firmante_id: UUID, rol: str) -> None:
    await conn.execute(
        "INSERT INTO tb_solicitudes_firmas (solicitud_id, firmante_id, rol_firma) "
        "VALUES ($1, $2, $3) ON CONFLICT (solicitud_id, rol_firma) DO NOTHING",
        solicitud_id, firmante_id, rol,
    )


async def get_firmas_solicitud(conn, solicitud_id: UUID) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT sf.rol_firma, sf.fecha_firma, u.nombre AS firmante_nombre
        FROM tb_solicitudes_firmas sf
        JOIN tb_usuarios u ON u.id_usuario = sf.firmante_id
        WHERE sf.solicitud_id = $1
        """,
        solicitud_id,
    )
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────
# Solicitudes de ausencia
# ─────────────────────────────────────────────

async def create_solicitud(
    conn,
    usuario_id: UUID,
    tipo_ausencia_id: UUID,
    fecha_inicio: date,
    fecha_fin: date,
    dias_solicitados: int,
    fecha_presentarse: date,
    observaciones: Optional[str],
    firma_solicitante_pendiente: bool = False,
) -> dict:
    row = await conn.fetchrow(
        """
        INSERT INTO tb_solicitudes_ausencia
            (usuario_id, tipo_ausencia_id, fecha_inicio, fecha_fin, dias_solicitados,
             fecha_presentarse, observaciones, firma_solicitante_pendiente)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
        RETURNING id, usuario_id, tipo_ausencia_id, fecha_inicio, fecha_fin,
                  dias_solicitados, fecha_presentarse, observaciones,
                  estado, firma_solicitante_pendiente, fecha_solicitud
        """,
        usuario_id, tipo_ausencia_id, fecha_inicio, fecha_fin, dias_solicitados,
        fecha_presentarse, observaciones, firma_solicitante_pendiente,
    )
    return dict(row)


async def get_solicitud(conn, solicitud_id: UUID) -> Optional[dict]:
    row = await conn.fetchrow(
        """
        SELECT sa.id, sa.usuario_id, sa.tipo_ausencia_id, sa.fecha_inicio, sa.fecha_fin,
               sa.dias_solicitados, sa.fecha_presentarse, sa.observaciones,
               sa.estado, sa.aprobado_por, sa.motivo_rechazo,
               sa.fecha_solicitud, sa.fecha_resolucion,
               sa.ultima_notificacion_aprobador, sa.firma_solicitante_pendiente,
               sa.es_migracion, sa.migrado_por,
               ta.nombre AS tipo_nombre, ta.abreviatura AS tipo_abreviatura,
               ta.slug AS tipo_slug, ta.afecta_saldo,
               u.nombre AS solicitante_nombre, u.email AS solicitante_email,
               a.nombre AS aprobado_por_nombre,
               m.nombre AS migrado_por_nombre
        FROM tb_solicitudes_ausencia sa
        JOIN tb_cat_tipos_ausencia ta ON ta.id = sa.tipo_ausencia_id
        JOIN tb_usuarios u ON u.id_usuario = sa.usuario_id
        LEFT JOIN tb_usuarios a ON a.id_usuario = sa.aprobado_por
        LEFT JOIN tb_usuarios m ON m.id_usuario = sa.migrado_por
        WHERE sa.id = $1
        """,
        solicitud_id,
    )
    return dict(row) if row else None


async def get_solicitudes_usuario(conn, usuario_id: UUID) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT sa.id, sa.tipo_ausencia_id, sa.fecha_inicio, sa.fecha_fin,
               sa.dias_solicitados, sa.fecha_presentarse, sa.estado,
               sa.motivo_rechazo, sa.fecha_solicitud, sa.fecha_resolucion,
               sa.firma_solicitante_pendiente, sa.es_migracion, sa.migrado_por,
               vc.num_periodo AS migracion_num_periodo,
               ta.nombre AS tipo_nombre, ta.abreviatura AS tipo_abreviatura,
               a.nombre AS aprobado_por_nombre,
               m.nombre AS migrado_por_nombre
        FROM tb_solicitudes_ausencia sa
        JOIN tb_cat_tipos_ausencia ta ON ta.id = sa.tipo_ausencia_id
        LEFT JOIN tb_usuarios a ON a.id_usuario = sa.aprobado_por
        LEFT JOIN tb_usuarios m ON m.id_usuario = sa.migrado_por
        LEFT JOIN tb_vacaciones_consumo vc ON vc.solicitud_id = sa.id AND sa.es_migracion = TRUE
        WHERE sa.usuario_id = $1
        ORDER BY COALESCE(sa.es_migracion, false) ASC, sa.created_at DESC
        """,
        usuario_id,
    )
    return [dict(r) for r in rows]


async def get_solicitudes_pendientes_para_aprobador(conn, aprobador_id: UUID) -> list[dict]:
    """
    Devuelve solicitudes pendientes donde el usuario actual es aprobador designado o jefe.
    """
    rows = await conn.fetch(
        """
        SELECT sa.id, sa.usuario_id, sa.tipo_ausencia_id, sa.fecha_inicio, sa.fecha_fin,
               sa.dias_solicitados, sa.fecha_presentarse, sa.observaciones,
               sa.estado, sa.fecha_solicitud, sa.firma_solicitante_pendiente,
               ta.nombre AS tipo_nombre, ta.abreviatura AS tipo_abreviatura,
               u.nombre AS solicitante_nombre, u.email AS solicitante_email
        FROM tb_solicitudes_ausencia sa
        JOIN tb_cat_tipos_ausencia ta ON ta.id = sa.tipo_ausencia_id
        JOIN tb_usuarios u ON u.id_usuario = sa.usuario_id
        LEFT JOIN tb_empleados_datos ed ON ed.usuario_id = sa.usuario_id
        LEFT JOIN tb_empleados_jefes ej ON ej.empleado_id = sa.usuario_id AND ej.jefe_id = $1
        WHERE sa.estado = 'pendiente'
          AND sa.firma_solicitante_pendiente = false
          AND (ed.id_aprobador_vacaciones = $1 OR ej.jefe_id IS NOT NULL)
        ORDER BY sa.fecha_solicitud
        """,
        aprobador_id,
    )
    return [dict(r) for r in rows]


async def get_todas_solicitudes_pendientes(conn) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT sa.id, sa.usuario_id, sa.tipo_ausencia_id, sa.fecha_inicio, sa.fecha_fin,
               sa.dias_solicitados, sa.fecha_presentarse, sa.observaciones,
               sa.estado, sa.fecha_solicitud, sa.ultima_notificacion_aprobador,
               sa.firma_solicitante_pendiente,
               ta.nombre AS tipo_nombre, ta.abreviatura AS tipo_abreviatura,
               u.nombre AS solicitante_nombre, u.email AS solicitante_email
        FROM tb_solicitudes_ausencia sa
        JOIN tb_cat_tipos_ausencia ta ON ta.id = sa.tipo_ausencia_id
        JOIN tb_usuarios u ON u.id_usuario = sa.usuario_id
        WHERE sa.estado = 'pendiente'
          AND sa.firma_solicitante_pendiente = false
        ORDER BY sa.fecha_solicitud
        """
    )
    return [dict(r) for r in rows]


async def get_historial_aprobaciones(
    conn, limit: int = 10, offset: int = 0, aprobador_id: Optional[UUID] = None
) -> list[dict]:
    if aprobador_id is None:
        rows = await conn.fetch(
            """
            SELECT sa.id, sa.usuario_id, sa.tipo_ausencia_id, sa.fecha_inicio, sa.fecha_fin,
                   sa.dias_solicitados, sa.estado, sa.motivo_rechazo,
                   sa.fecha_solicitud, sa.fecha_resolucion,
                   ta.nombre AS tipo_nombre,
                   u.nombre AS solicitante_nombre
            FROM tb_solicitudes_ausencia sa
            JOIN tb_cat_tipos_ausencia ta ON ta.id = sa.tipo_ausencia_id
            JOIN tb_usuarios u ON u.id_usuario = sa.usuario_id
            WHERE sa.estado IN ('aprobado', 'rechazado')
            ORDER BY sa.fecha_resolucion DESC NULLS LAST
            LIMIT $1 OFFSET $2
            """,
            limit,
            offset,
        )
    else:
        rows = await conn.fetch(
            """
            SELECT sa.id, sa.usuario_id, sa.tipo_ausencia_id, sa.fecha_inicio, sa.fecha_fin,
                   sa.dias_solicitados, sa.estado, sa.motivo_rechazo,
                   sa.fecha_solicitud, sa.fecha_resolucion,
                   ta.nombre AS tipo_nombre,
                   u.nombre AS solicitante_nombre
            FROM tb_solicitudes_ausencia sa
            JOIN tb_cat_tipos_ausencia ta ON ta.id = sa.tipo_ausencia_id
            JOIN tb_usuarios u ON u.id_usuario = sa.usuario_id
            LEFT JOIN tb_empleados_datos ed ON ed.usuario_id = sa.usuario_id
            LEFT JOIN tb_empleados_jefes ej ON ej.empleado_id = sa.usuario_id AND ej.jefe_id = $1
            WHERE sa.estado IN ('aprobado', 'rechazado')
              AND (ed.id_aprobador_vacaciones = $1 OR ej.jefe_id IS NOT NULL)
            ORDER BY sa.fecha_resolucion DESC NULLS LAST
            LIMIT $2 OFFSET $3
            """,
            aprobador_id,
            limit,
            offset,
        )
    return [dict(r) for r in rows]


async def get_todas_solicitudes(conn, estado: Optional[str] = None, limit: int = 30) -> list[dict]:
    base = """
        SELECT sa.id, sa.usuario_id, sa.tipo_ausencia_id, sa.fecha_inicio, sa.fecha_fin,
               sa.dias_solicitados, sa.fecha_presentarse, sa.estado,
               sa.motivo_rechazo, sa.fecha_solicitud, sa.fecha_resolucion,
               sa.firma_solicitante_pendiente, sa.es_migracion, sa.migrado_por,
               ta.nombre AS tipo_nombre, ta.abreviatura AS tipo_abreviatura,
               u.nombre AS solicitante_nombre, a.nombre AS aprobado_por_nombre,
               m.nombre AS migrado_por_nombre
        FROM tb_solicitudes_ausencia sa
        JOIN tb_cat_tipos_ausencia ta ON ta.id = sa.tipo_ausencia_id
        JOIN tb_usuarios u ON u.id_usuario = sa.usuario_id
        LEFT JOIN tb_usuarios a ON a.id_usuario = sa.aprobado_por
        LEFT JOIN tb_usuarios m ON m.id_usuario = sa.migrado_por
    """
    params = []
    if estado:
        params.append(estado)
        base += " WHERE sa.estado = $1"
    base += " ORDER BY sa.created_at DESC"
    if limit > 0:
        params.append(limit)
        base += f" LIMIT ${len(params)}"
    rows = await conn.fetch(base, *params)
    return [dict(r) for r in rows]


async def update_solicitud_estado(
    conn,
    solicitud_id: UUID,
    estado: str,
    aprobado_por: Optional[UUID] = None,
    motivo_rechazo: Optional[str] = None,
) -> None:
    await conn.execute(
        """
        UPDATE tb_solicitudes_ausencia
        SET estado = $2::varchar, aprobado_por = $3, motivo_rechazo = $4,
            fecha_resolucion = CASE WHEN $2::varchar IN ('aprobado','rechazado','cancelado') THEN now() ELSE NULL END,
            updated_at = now()
        WHERE id = $1
        """,
        solicitud_id, estado, aprobado_por, motivo_rechazo,
    )


async def update_ultima_notificacion_aprobador(conn, solicitud_id: UUID) -> None:
    await conn.execute(
        "UPDATE tb_solicitudes_ausencia SET ultima_notificacion_aprobador = now() WHERE id = $1",
        solicitud_id,
    )


async def completar_firma_solicitante(conn, solicitud_id: UUID) -> None:
    await conn.execute(
        """
        UPDATE tb_solicitudes_ausencia
        SET firma_solicitante_pendiente = false,
            updated_at = now()
        WHERE id = $1
        """,
        solicitud_id,
    )


async def get_solicitudes_activas_en_rango(
    conn, usuario_id: UUID, fecha_inicio: date, fecha_fin: date, excluir_id: Optional[UUID] = None
) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT id FROM tb_solicitudes_ausencia
        WHERE usuario_id = $1
          AND estado IN ('pendiente','aprobado')
          AND COALESCE(es_migracion, false) = false
          AND fecha_inicio <= $3 AND fecha_fin >= $2
          AND ($4::uuid IS NULL OR id != $4)
        """,
        usuario_id, fecha_inicio, fecha_fin, excluir_id,
    )
    return [dict(r) for r in rows]


async def get_ausencias_activas(
    conn,
    fecha_inicio: date,
    fecha_fin: date,
    tipo_slug: str | None = None,
) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT sa.id, sa.fecha_inicio, sa.fecha_fin, sa.fecha_presentarse,
               sa.dias_solicitados,
               u.nombre AS empleado_nombre, u.email AS empleado_email,
               ta.nombre AS tipo_nombre, ta.abreviatura AS tipo_abreviatura,
               ta.slug AS tipo_slug
        FROM tb_solicitudes_ausencia sa
        JOIN tb_usuarios u ON u.id_usuario = sa.usuario_id
        JOIN tb_cat_tipos_ausencia ta ON ta.id = sa.tipo_ausencia_id
        WHERE sa.estado = 'aprobado'
          AND COALESCE(sa.es_migracion, false) = false
          AND sa.fecha_inicio <= $2
          AND sa.fecha_fin   >= $1
          AND ($3::text IS NULL OR ta.slug = $3)
        ORDER BY ta.orden, u.nombre
        """,
        fecha_inicio, fecha_fin, tipo_slug,
    )
    return [dict(r) for r in rows]


async def get_vacaciones_hoy(conn, hoy: date) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT sa.id, sa.fecha_inicio, sa.fecha_fin, sa.fecha_presentarse,
               sa.dias_solicitados,
               u.nombre AS empleado_nombre, u.email AS empleado_email
        FROM tb_solicitudes_ausencia sa
        JOIN tb_usuarios u ON u.id_usuario = sa.usuario_id
        JOIN tb_cat_tipos_ausencia ta ON ta.id = sa.tipo_ausencia_id
        WHERE sa.estado = 'aprobado'
          AND ta.slug = 'vacaciones'
          AND COALESCE(sa.es_migracion, false) = false
          AND sa.fecha_inicio <= $1 AND sa.fecha_fin >= $1
        ORDER BY u.nombre
        """,
        hoy,
    )
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────
# Consumo de períodos (FIFO)
# ─────────────────────────────────────────────

async def get_vacaciones_aprobadas_equipo(
    conn,
    usuario_ids: list[UUID],
    fecha_inicio: date,
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
            sa.fecha_presentarse,
            sa.dias_solicitados,
            u.nombre AS empleado_nombre,
            u.email AS empleado_email
        FROM tb_solicitudes_ausencia sa
        JOIN tb_usuarios u ON u.id_usuario = sa.usuario_id
        JOIN tb_cat_tipos_ausencia ta ON ta.id = sa.tipo_ausencia_id
        WHERE sa.usuario_id = ANY($1::uuid[])
          AND sa.estado = 'aprobado'
          AND ta.slug = 'vacaciones'
          AND COALESCE(sa.es_migracion, false) = false
          AND sa.fecha_fin >= $2
        ORDER BY sa.fecha_inicio, u.nombre
        """,
        usuario_ids,
        fecha_inicio,
    )
    return [dict(r) for r in rows]


async def get_consumos_usuario(conn, usuario_id: UUID) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT vc.num_periodo, vc.dias_consumidos, vc.fecha_aniversario_periodo
        FROM tb_vacaciones_consumo vc
        JOIN tb_solicitudes_ausencia sa ON sa.id = vc.solicitud_id
        WHERE sa.usuario_id = $1
          AND sa.estado IN ('pendiente', 'aprobado')
        ORDER BY vc.num_periodo
        """,
        usuario_id,
    )
    return [dict(r) for r in rows]


async def get_consumos_solicitud(conn, solicitud_id: UUID) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT num_periodo, dias_consumidos, fecha_aniversario_periodo
        FROM tb_vacaciones_consumo
        WHERE solicitud_id = $1
        ORDER BY num_periodo
        """,
        solicitud_id,
    )
    return [dict(r) for r in rows]


def _group_consumos_by_usuario(rows) -> dict[UUID, list[dict]]:
    result: dict[UUID, list[dict]] = {}
    for row in rows:
        uid = row["usuario_id"]
        result.setdefault(uid, []).append({
            "num_periodo": row["num_periodo"],
            "dias_consumidos": row["dias_consumidos"],
            "fecha_aniversario_periodo": row["fecha_aniversario_periodo"],
        })
    return result


async def get_consumos_bulk(conn, usuario_ids: list[UUID]) -> dict[UUID, list[dict]]:
    """Returns consumos grouped by usuario_id for a batch of users."""
    if not usuario_ids:
        return {}
    rows = await conn.fetch(
        """
        SELECT sa.usuario_id, vc.num_periodo, vc.dias_consumidos, vc.fecha_aniversario_periodo
        FROM tb_vacaciones_consumo vc
        JOIN tb_solicitudes_ausencia sa ON sa.id = vc.solicitud_id
        WHERE sa.usuario_id = ANY($1::uuid[])
          AND sa.estado IN ('pendiente', 'aprobado')
        ORDER BY sa.usuario_id, vc.num_periodo
        """,
        usuario_ids,
    )
    return _group_consumos_by_usuario(rows)


async def get_consumos_no_migracion_bulk(conn, usuario_ids: list[UUID]) -> dict[UUID, list[dict]]:
    if not usuario_ids:
        return {}
    rows = await conn.fetch(
        """
        SELECT sa.usuario_id, vc.num_periodo, vc.dias_consumidos, vc.fecha_aniversario_periodo
        FROM tb_vacaciones_consumo vc
        JOIN tb_solicitudes_ausencia sa ON sa.id = vc.solicitud_id
        WHERE sa.usuario_id = ANY($1::uuid[])
          AND sa.estado IN ('pendiente', 'aprobado')
          AND COALESCE(sa.es_migracion, false) = false
        ORDER BY sa.usuario_id, vc.num_periodo
        """,
        usuario_ids,
    )
    return _group_consumos_by_usuario(rows)


async def get_consumos_migracion_bulk(conn, usuario_ids: list[UUID]) -> dict[UUID, list[dict]]:
    if not usuario_ids:
        return {}
    rows = await conn.fetch(
        """
        SELECT sa.usuario_id, vc.num_periodo, vc.dias_consumidos, vc.fecha_aniversario_periodo
        FROM tb_vacaciones_consumo vc
        JOIN tb_solicitudes_ausencia sa ON sa.id = vc.solicitud_id
        WHERE sa.usuario_id = ANY($1::uuid[])
          AND sa.estado IN ('pendiente', 'aprobado')
          AND sa.es_migracion = TRUE
        ORDER BY sa.usuario_id, vc.num_periodo
        """,
        usuario_ids,
    )
    return _group_consumos_by_usuario(rows)


async def insert_consumos(conn, solicitud_id: UUID, consumos: list[dict]) -> None:
    await conn.executemany(
        "INSERT INTO tb_vacaciones_consumo "
        "(solicitud_id, num_periodo, dias_consumidos, fecha_aniversario_periodo) "
        "VALUES ($1, $2, $3, $4)",
        [
            (solicitud_id, c["num_periodo"], c["dias_consumir"], c["fecha_aniversario_periodo"])
            for c in consumos
        ],
    )


async def delete_consumos_solicitud(conn, solicitud_id: UUID) -> None:
    await conn.execute(
        "DELETE FROM tb_vacaciones_consumo WHERE solicitud_id = $1", solicitud_id
    )


# ─────────────────────────────────────────────
# Notificaciones — acceso a emails de aprobadores
# ─────────────────────────────────────────────

async def get_aprobador_email(conn, solicitud_id: UUID) -> Optional[str]:
    """Busca el email del aprobador designado; si no hay, devuelve None."""
    emails = await get_aprobador_emails(conn, solicitud_id)
    return emails[0] if emails else None


async def get_aprobador_emails(conn, solicitud_id: UUID) -> list[str]:
    """
    Busca destinatarios de aprobacion: aprobador designado, jefes directos,
    y como ultimo fallback correos de RH.
    """
    row = await conn.fetchrow(
        """
        SELECT u.email
        FROM tb_solicitudes_ausencia sa
        JOIN tb_empleados_datos ed ON ed.usuario_id = sa.usuario_id
        JOIN tb_usuarios u ON u.id_usuario = ed.id_aprobador_vacaciones
        WHERE sa.id = $1
          AND u.is_active = true
        """,
        solicitud_id,
    )
    if row and row["email"]:
        return [row["email"]]

    jefe_rows = await conn.fetch(
        """
        SELECT u.email
        FROM tb_solicitudes_ausencia sa
        JOIN tb_empleados_jefes ej ON ej.empleado_id = sa.usuario_id
        JOIN tb_usuarios u ON u.id_usuario = ej.jefe_id
        WHERE sa.id = $1
          AND u.is_active = true
          AND u.email IS NOT NULL
        ORDER BY u.nombre
        """,
        solicitud_id,
    )
    jefe_emails = [r["email"] for r in jefe_rows if r["email"]]
    if jefe_emails:
        return jefe_emails

    return await get_rh_emails(conn)


async def get_rh_emails(conn) -> list[str]:
    rows = await conn.fetch(
        """
        SELECT DISTINCT u.email
        FROM tb_usuarios u
        JOIN tb_permisos_modulos pm
            ON pm.usuario_id = u.id_usuario
           AND pm.modulo_slug = 'rrhh'
           AND pm.rol_modulo IN ('editor', 'admin')
        WHERE u.is_active = true
          AND u.email IS NOT NULL
        """
    )
    return [r["email"] for r in rows]


async def get_emails_by_usuario_ids(conn, usuario_ids: list[UUID]) -> list[str]:
    if not usuario_ids:
        return []
    rows = await conn.fetch(
        """
        SELECT email
        FROM tb_usuarios
        WHERE id_usuario = ANY($1::uuid[])
          AND is_active = true
          AND email IS NOT NULL
        """,
        usuario_ids,
    )
    return [r["email"] for r in rows]


async def try_register_worker_notification(
    conn,
    *,
    clave: str,
    tipo: str,
    fecha_objetivo: date,
    usuario_id: Optional[UUID] = None,
    solicitud_id: Optional[UUID] = None,
    num_periodo: Optional[int] = None,
    metadata: Optional[dict] = None,
) -> bool:
    row = await conn.fetchrow(
        """
        INSERT INTO tb_vacaciones_notificaciones_worker
            (clave, tipo, usuario_id, solicitud_id, num_periodo, fecha_objetivo, metadata)
        VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
        ON CONFLICT (clave) DO NOTHING
        RETURNING id
        """,
        clave,
        tipo,
        usuario_id,
        solicitud_id,
        num_periodo,
        fecha_objetivo,
        json.dumps(metadata or {}),
    )
    return row is not None


async def get_usuarios_activos_simples(conn) -> list[dict]:
    rows = await conn.fetch(
        "SELECT id_usuario, nombre, email FROM tb_usuarios WHERE is_active = true ORDER BY nombre"
    )
    return [dict(r) for r in rows]


async def get_usuario_simple_by_id(conn, usuario_id: UUID) -> Optional[dict]:
    row = await conn.fetchrow(
        "SELECT id_usuario, nombre, email FROM tb_usuarios WHERE id_usuario = $1",
        usuario_id,
    )
    return dict(row) if row else None


async def get_jefes_con_nombre(conn, usuario_id: UUID) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT u.id_usuario, u.nombre, u.email
        FROM tb_empleados_jefes ej
        JOIN tb_usuarios u ON u.id_usuario = ej.jefe_id
        WHERE ej.empleado_id = $1
        ORDER BY u.nombre
        """,
        usuario_id,
    )
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────
# Prórrogas de vacaciones
# ─────────────────────────────────────────────

async def get_prorrogas_activas_usuario(conn, usuario_id: UUID) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT id, usuario_id, num_periodo, fecha_aniversario_periodo,
               fecha_expiracion_original, fecha_expiracion_prorroga,
               dias_prorrogados, motivo, estado, created_by, created_at
        FROM tb_vacaciones_prorrogas
        WHERE usuario_id = $1
          AND estado = 'activa'
          AND fecha_expiracion_prorroga >= $2
        ORDER BY num_periodo
        """,
        usuario_id, today_mx(),
    )
    return [dict(r) for r in rows]


async def get_prorrogas_activas_bulk(conn, usuario_ids: list[UUID]) -> dict[UUID, list[dict]]:
    if not usuario_ids:
        return {}
    rows = await conn.fetch(
        """
        SELECT id, usuario_id, num_periodo, fecha_aniversario_periodo,
               fecha_expiracion_original, fecha_expiracion_prorroga,
               dias_prorrogados, motivo, estado, created_by, created_at
        FROM tb_vacaciones_prorrogas
        WHERE usuario_id = ANY($1::uuid[])
          AND estado = 'activa'
          AND fecha_expiracion_prorroga >= $2
        ORDER BY usuario_id, num_periodo
        """,
        usuario_ids, today_mx(),
    )
    result: dict[UUID, list[dict]] = {}
    for row in rows:
        uid = row["usuario_id"]
        result.setdefault(uid, []).append(dict(row))
    return result


async def get_prorrogas_usuario(conn, usuario_id: UUID) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT p.id, p.num_periodo, p.fecha_aniversario_periodo,
               p.fecha_expiracion_original, p.fecha_expiracion_prorroga,
               p.dias_prorrogados, p.motivo, p.estado,
               p.created_at, p.cancelled_at, p.motivo_cancelacion,
               cb.nombre AS created_by_nombre,
               ca.nombre AS cancelled_by_nombre
        FROM tb_vacaciones_prorrogas p
        JOIN tb_usuarios cb ON cb.id_usuario = p.created_by
        LEFT JOIN tb_usuarios ca ON ca.id_usuario = p.cancelled_by
        WHERE p.usuario_id = $1
        ORDER BY p.created_at DESC
        """,
        usuario_id,
    )
    return [dict(r) for r in rows]


async def create_prorroga(
    conn,
    usuario_id: UUID,
    num_periodo: int,
    fecha_aniversario_periodo: date,
    fecha_expiracion_original: date,
    fecha_expiracion_prorroga: date,
    dias_prorrogados: int,
    motivo: str,
    created_by: UUID,
) -> dict:
    row = await conn.fetchrow(
        """
        INSERT INTO tb_vacaciones_prorrogas
            (usuario_id, num_periodo, fecha_aniversario_periodo,
             fecha_expiracion_original, fecha_expiracion_prorroga,
             dias_prorrogados, motivo, created_by)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING id, usuario_id, num_periodo, fecha_aniversario_periodo,
                  fecha_expiracion_original, fecha_expiracion_prorroga,
                  dias_prorrogados, motivo, estado, created_at
        """,
        usuario_id, num_periodo, fecha_aniversario_periodo,
        fecha_expiracion_original, fecha_expiracion_prorroga,
        dias_prorrogados, motivo, created_by,
    )
    return dict(row)


async def cancel_prorroga(
    conn,
    prorroga_id: UUID,
    cancelled_by: UUID,
    motivo_cancelacion: str,
) -> Optional[dict]:
    row = await conn.fetchrow(
        """
        UPDATE tb_vacaciones_prorrogas
        SET estado            = 'cancelada',
            cancelled_by      = $2,
            cancelled_at      = now(),
            motivo_cancelacion = $3
        WHERE id = $1
          AND estado = 'activa'
        RETURNING id, usuario_id, num_periodo, estado
        """,
        prorroga_id, cancelled_by, motivo_cancelacion,
    )
    return dict(row) if row else None
