import asyncpg
from datetime import date
from uuid import UUID
from core.config import settings

async def get_sat_sp_config(conn: asyncpg.Connection) -> tuple[str, str, str]:
    rows = await conn.fetch(
        "SELECT clave, valor FROM tb_configuracion_global "
        "WHERE clave IN ('SP_SAT_SITE_ID', 'SP_SAT_DRIVE_ID', 'SP_SAT_BASE_FOLDER')"
    )
    config = {r["clave"]: r["valor"] for r in rows}
    site_id = config.get("SP_SAT_SITE_ID") or settings.SP_SAT_SITE_ID
    drive_id = config.get("SP_SAT_DRIVE_ID") or settings.SP_SAT_DRIVE_ID
    base_folder = config.get("SP_SAT_BASE_FOLDER") or settings.SP_SAT_BASE_FOLDER or "SAT-Inbox"
    return site_id, drive_id, base_folder

_ALLOWED_JOB_FIELDS = frozenset({
    "estado", "id_solicitud_sat", "cfdi_encontrados", "cfdi_duplicados", "mensaje_error",
    "rfc_emisor_filtro",
})

async def actualizar_job(conn: asyncpg.Connection, job_id: UUID, **kwargs) -> None:
    invalid = set(kwargs) - _ALLOWED_JOB_FIELDS
    if invalid:
        raise ValueError(f"Campos de job no permitidos: {invalid}")
    sets = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(kwargs))
    values = list(kwargs.values())
    await conn.execute(
        f"UPDATE tb_sat_jobs SET {sets}, updated_at = NOW() WHERE id = $1",
        job_id, *values,
    )

async def uuids_existentes(conn: asyncpg.Connection, uuids: list[str]) -> set[str]:
    if not uuids:
        return set()
    rows = await conn.fetch(
        """
        SELECT uuid_cfdi FROM tb_sat_inbox WHERE uuid_cfdi = ANY($1)
        UNION
        SELECT uuid_factura FROM tb_xml_staging WHERE uuid_factura = ANY($1)
        """,
        uuids,
    )
    return {r[0] for r in rows}


async def hay_job_activo(conn: asyncpg.Connection, max_runtime_minutes: int = 120) -> bool:
    row = await conn.fetchrow(
        "SELECT EXISTS ("
        "  SELECT 1 FROM tb_sat_jobs"
        "  WHERE estado NOT IN ('completado', 'error')"
        "  AND created_at > NOW() - ($1::int * INTERVAL '1 minute')"
        ")",
        max_runtime_minutes,
    )
    return row[0]

async def crear_job(
    conn: asyncpg.Connection,
    fecha_inicio: date,
    fecha_fin: date,
    usuario_id: UUID,
    rfc_emisor_filtro: str | None = None,
) -> UUID:
    row = await conn.fetchrow(
        """
        INSERT INTO tb_sat_jobs (
            fecha_inicio_rango, fecha_fin_rango, creado_por, estado, rfc_emisor_filtro
        )
        VALUES ($1, $2, $3, 'iniciando', $4)
        RETURNING id
        """,
        fecha_inicio, fecha_fin, usuario_id, rfc_emisor_filtro,
    )
    return row["id"]

async def obtener_job_status(conn: asyncpg.Connection, job_id: UUID) -> dict:
    row = await conn.fetchrow(
        "SELECT id, estado, id_solicitud_sat, cfdi_encontrados, cfdi_duplicados, mensaje_error, "
        "rfc_emisor_filtro, "
        "fecha_inicio_rango, fecha_fin_rango, created_at, updated_at "
        "FROM tb_sat_jobs WHERE id = $1",
        job_id,
    )
    if not row:
        raise ValueError(f"Job no encontrado: {job_id}")
    return dict(row)

async def obtener_ultimo_job(conn: asyncpg.Connection) -> dict | None:
    row = await conn.fetchrow(
        "SELECT id, estado, id_solicitud_sat, cfdi_encontrados, cfdi_duplicados, mensaje_error, "
        "rfc_emisor_filtro, fecha_inicio_rango, fecha_fin_rango, created_at, updated_at "
        "FROM tb_sat_jobs ORDER BY created_at DESC LIMIT 1"
    )
    return dict(row) if row else None

async def obtener_job_activo_para_worker(conn: asyncpg.Connection) -> dict | None:
    row = await conn.fetchrow(
        """
        WITH candidato AS (
            SELECT id
            FROM tb_sat_jobs
            WHERE estado NOT IN ('completado', 'error')
            ORDER BY created_at ASC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        )
        UPDATE tb_sat_jobs
        SET estado = CASE WHEN candidato.estado = 'iniciando' THEN 'solicitando' ELSE candidato.estado END,
            updated_at = NOW()
        FROM candidato
        WHERE tb_sat_jobs.id = candidato.id
        RETURNING
            tb_sat_jobs.id,
            tb_sat_jobs.estado,
            tb_sat_jobs.id_solicitud_sat,
            tb_sat_jobs.cfdi_encontrados,
            tb_sat_jobs.cfdi_duplicados,
            tb_sat_jobs.mensaje_error,
            tb_sat_jobs.rfc_emisor_filtro,
            tb_sat_jobs.fecha_inicio_rango,
            tb_sat_jobs.fecha_fin_rango,
            tb_sat_jobs.created_at,
            tb_sat_jobs.updated_at
        """
    )
    return dict(row) if row else None

async def marcar_jobs_expirados(conn: asyncpg.Connection, max_runtime_minutes: int) -> int:
    result = await conn.execute(
        """
        UPDATE tb_sat_jobs
        SET estado = 'error',
            mensaje_error = 'La consulta SAT excedio el tiempo maximo y fue marcada como interrumpida.',
            updated_at = NOW()
        WHERE estado NOT IN ('completado', 'error')
          AND created_at < NOW() - ($1::int * INTERVAL '1 minute')
        """,
        max_runtime_minutes,
    )
    return int(result.split()[1]) if result.startswith("UPDATE") else 0

async def listar_inbox(conn: asyncpg.Connection, estado: str | None = None, limit: int = 50) -> tuple[list[dict], int]:
    filtros = []
    params: list = []
    if estado and estado != "todos":
        params.append(estado)
        filtros.append(f"i.estado = ${len(params)}")
    else:
        filtros.append("i.estado != 'descartado'")
    where = f"WHERE {' AND '.join(filtros)}" if filtros else ""
    count_params = list(params)
    limit_clause = ""
    if limit > 0:
        params.append(limit)
        limit_clause = f"LIMIT ${len(params)}"
    rows = await conn.fetch(
        f"""
        SELECT i.id, i.uuid_cfdi, i.rfc_emisor, i.nombre_emisor,
               i.fecha_cfdi, i.total, i.moneda, i.estado,
               i.comprobante_id, i.sharepoint_url, i.created_at,
               i.tipo_detectado
        FROM tb_sat_inbox i
        {where}
        ORDER BY i.created_at DESC
        {limit_clause}
        """,
        *params,
    )
    count_row = await conn.fetchrow(
        f"SELECT COUNT(*) FROM tb_sat_inbox i {where}", *count_params
    )
    return [dict(r) for r in rows], count_row[0]

async def descartar_inbox_item(conn: asyncpg.Connection, inbox_id: UUID) -> None:
    result = await conn.execute(
        "UPDATE tb_sat_inbox SET estado = 'descartado', updated_at = NOW() WHERE id = $1",
        inbox_id,
    )
    if result == "UPDATE 0":
        raise ValueError(f"Item de inbox no encontrado: {inbox_id}")

async def descartar_inbox_item_bulk(conn: asyncpg.Connection, inbox_ids: list[UUID]) -> int:
    if not inbox_ids:
        return 0
    result = await conn.execute(
        "UPDATE tb_sat_inbox SET estado = 'descartado', updated_at = NOW() WHERE id = ANY($1::uuid[]) AND estado != 'descartado'",
        inbox_ids,
    )
    return int(result.split()[1]) if result.startswith("UPDATE") else 0

async def restaurar_inbox_item(conn: asyncpg.Connection, inbox_id: UUID) -> None:
    result = await conn.execute(
        "UPDATE tb_sat_inbox SET estado = 'pendiente', comprobante_id = NULL, updated_at = NOW() "
        "WHERE id = $1 AND estado IN ('descartado', 'matcheado')",
        inbox_id,
    )
    if result == "UPDATE 0":
        raise ValueError(f"Item de inbox no encontrado o no apto para restaurar: {inbox_id}")

async def marcar_matcheado(conn: asyncpg.Connection, inbox_id: UUID, comprobante_id: UUID) -> None:
    result = await conn.execute(
        "UPDATE tb_sat_inbox SET estado = 'matcheado', comprobante_id = $2, updated_at = NOW() "
        "WHERE id = $1",
        inbox_id, comprobante_id,
    )
    if result == "UPDATE 0":
        raise ValueError(f"Item de inbox no encontrado: {inbox_id}")

async def obtener_inbox_item_para_descarga(conn: asyncpg.Connection, inbox_id: UUID) -> dict:
    row = await conn.fetchrow(
        "SELECT sharepoint_url, sharepoint_item_id, uuid_cfdi FROM tb_sat_inbox WHERE id = $1 AND estado = 'pendiente'",
        inbox_id,
    )
    if not row:
        raise ValueError("Item no encontrado o no esta en estado pendiente")
    return dict(row)

async def buscar_comprobantes_match(conn: asyncpg.Connection, q: str, limit: int = 10) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT c.id_comprobante, c.fecha_pago, c.beneficiario_orig, c.monto, c.moneda,
               p.razon_social AS proveedor_nombre, p.rfc AS proveedor_rfc
        FROM tb_comprobantes_pago c
        LEFT JOIN tb_proveedores p ON c.id_proveedor = p.id_proveedor
        WHERE c.estatus = 'PENDIENTE'
          AND (
            c.beneficiario_orig ILIKE $1
            OR p.rfc ILIKE $1
            OR p.razon_social ILIKE $1
          )
        ORDER BY c.fecha_pago DESC
        LIMIT $2
        """,
        f"%{q}%",
        limit,
    )
    return [dict(r) for r in rows]

async def listar_comprobantes_pendientes(conn: asyncpg.Connection) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT c.id_comprobante, c.fecha_pago, c.beneficiario_orig, c.monto, c.moneda,
               c.estatus, c.monto_facturado,
               p.razon_social AS proveedor_nombre, p.rfc AS proveedor_rfc
        FROM tb_comprobantes_pago c
        LEFT JOIN tb_proveedores p ON c.id_proveedor = p.id_proveedor
        WHERE c.estatus IN ('PENDIENTE', 'PARCIALMENTE_FACTURADO')
        ORDER BY COALESCE(p.razon_social, c.beneficiario_orig) ASC, c.monto DESC
        """
    )
    return [dict(r) for r in rows]

async def listar_comprobantes_anticipo(conn: asyncpg.Connection, rfc_emisor: str) -> list[dict]:
    """Comprobantes en estatus ANTICIPO elegibles para recibir un CIERRE_ANTICIPO.
    Prioriza los del RFC emisor; incluye comprobantes sin proveedor vinculado.
    """
    rows = await conn.fetch(
        """
        SELECT c.id_comprobante, c.fecha_pago, c.beneficiario_orig, c.monto, c.moneda,
               c.estatus, c.monto_facturado,
               p.razon_social AS proveedor_nombre, p.rfc AS proveedor_rfc
        FROM tb_comprobantes_pago c
        LEFT JOIN tb_proveedores p ON p.id_proveedor = c.id_proveedor
        WHERE c.estatus = 'ANTICIPO'
          AND (p.rfc = $1 OR c.id_proveedor IS NULL)
        ORDER BY
            COALESCE(p.rfc = $1, false) DESC,
            c.fecha_pago DESC
        """,
        rfc_emisor,
    )
    return [dict(r) for r in rows]

async def listar_comprobantes_para_anticipo(conn: asyncpg.Connection, rfc_emisor: str) -> list[dict]:
    """Comprobantes que pueden recibir un ANTICIPO.

    Incluye anticipos abiertos para permitir acumular mas de un XML al mismo pago.
    """
    rows = await conn.fetch(
        """
        SELECT c.id_comprobante, c.fecha_pago, c.beneficiario_orig, c.monto, c.moneda,
               c.estatus, c.monto_facturado,
               p.razon_social AS proveedor_nombre, p.rfc AS proveedor_rfc
        FROM tb_comprobantes_pago c
        LEFT JOIN tb_proveedores p ON p.id_proveedor = c.id_proveedor
        WHERE (c.estatus IN ('PENDIENTE', 'PARCIALMENTE_FACTURADO') OR (c.estatus = 'ANTICIPO' AND COALESCE(c.monto_facturado, 0) < c.monto - 0.50))
        ORDER BY
            COALESCE(p.rfc = $1, false) DESC,
            CASE c.estatus
                WHEN 'ANTICIPO' THEN 0
                WHEN 'PARCIALMENTE_FACTURADO' THEN 1
                ELSE 2
            END,
            c.fecha_pago DESC
        """,
        rfc_emisor,
    )
    return [dict(r) for r in rows]

async def buscar_coincidencias_auto(conn: asyncpg.Connection) -> list[dict]:
    # Busca pares únicos (1 a 1) entre facturas pendientes del SAT y comprobantes pendientes.
    # Caso 1 (NORMAL): empareja por monto ±0.50 y nombre vs comprobantes PENDIENTE/PARCIALMENTE_FACTURADO.
    # Caso 2 (CIERRE_ANTICIPO): empareja por RFC vs comprobantes ANTICIPO que cubren el monto.
    rows = await conn.fetch(
        """
        WITH matches AS (
            SELECT
                i.id AS inbox_id,
                i.uuid_cfdi, i.rfc_emisor, i.nombre_emisor,
                i.total, i.fecha_cfdi, i.tipo_detectado,
                c.id_comprobante, c.beneficiario_orig,
                c.monto AS comprobante_monto, c.fecha_pago
            FROM tb_sat_inbox i
            JOIN tb_comprobantes_pago c ON (
                -- Caso 1: CFDI normal vs comprobantes pendientes/parciales
                (
                    COALESCE(i.tipo_detectado, 'NORMAL') != 'CIERRE_ANTICIPO'
                    AND c.estatus IN ('PENDIENTE', 'PARCIALMENTE_FACTURADO')
                    AND c.moneda = COALESCE(i.moneda, 'MXN')
                    AND ABS(c.monto - i.total) <= 0.50
                    AND (
                        c.beneficiario_orig ILIKE '%' || i.nombre_emisor || '%'
                        OR i.nombre_emisor ILIKE '%' || c.beneficiario_orig || '%'
                    )
                )
                OR
                -- Caso 2: CIERRE_ANTICIPO vs comprobantes en estatus ANTICIPO del mismo RFC
                (
                    i.tipo_detectado = 'CIERRE_ANTICIPO'
                    AND c.estatus = 'ANTICIPO'
                    AND c.monto >= i.total - 0.50
                    AND c.id_proveedor IS NOT NULL
                    AND EXISTS (
                        SELECT 1 FROM tb_proveedores p
                        WHERE p.id_proveedor = c.id_proveedor
                          AND p.rfc = i.rfc_emisor
                    )
                )
            )
            WHERE i.estado = 'pendiente'
        ),
        -- Solo pares 1-a-1: cada inbox_id y cada comprobante aparecen exactamente una vez
        unique_matches AS (
            SELECT * FROM matches m
            WHERE (SELECT COUNT(*) FROM matches WHERE inbox_id = m.inbox_id) = 1
              AND (SELECT COUNT(*) FROM matches WHERE id_comprobante = m.id_comprobante) = 1
        )
        SELECT * FROM unique_matches
        ORDER BY fecha_pago DESC
        """
    )
    return [dict(r) for r in rows]

async def contar_solicitudes_hoy(conn: asyncpg.Connection) -> int:
    val = await conn.fetchval(
        "SELECT COUNT(*) FROM tb_sat_jobs "
        "WHERE (created_at AT TIME ZONE 'America/Mexico_City')::date = "
        "(NOW() AT TIME ZONE 'America/Mexico_City')::date"
    )
    return int(val or 0)


async def registrar_cfdi_descargado(
    conn: asyncpg.Connection,
    job_id: UUID,
    cfdi,
    sharepoint_url: str,
    sharepoint_item_id: str,
    estado: str,
    tipo_detectado: str = "NORMAL",
) -> None:
    await conn.execute(
        """
        INSERT INTO tb_sat_inbox
          (job_id, uuid_cfdi, rfc_emisor, nombre_emisor,
           fecha_cfdi, total, moneda, sharepoint_url,
           sharepoint_item_id, estado, tipo_detectado)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
        ON CONFLICT (uuid_cfdi) DO NOTHING
        """,
        job_id, cfdi.uuid, cfdi.emisor_rfc, cfdi.emisor_nombre,
        date.fromisoformat(cfdi.fecha[:10]) if cfdi.fecha else None,
        cfdi.total, cfdi.moneda,
        sharepoint_url, sharepoint_item_id, estado, tipo_detectado,
    )


async def buscar_candidatos_para_comprobante(
    conn,
    monto: float,
    beneficiario_orig: str,
    proveedor_rfc=None,
    moneda: str = "MXN",
    estatus: str | None = None,
    monto_facturado: float = 0,
    q=None,
) -> list:
    if q:
        rows = await conn.fetch(
            """
            SELECT id, uuid_cfdi, rfc_emisor, nombre_emisor, total, moneda,
                   fecha_cfdi, tipo_detectado
            FROM tb_sat_inbox
            WHERE estado = 'pendiente'
              AND (
                  uuid_cfdi::text ILIKE '%' || $1 || '%'
                  OR nombre_emisor ILIKE '%' || $1 || '%'
                  OR rfc_emisor ILIKE '%' || $1 || '%'
                  OR CAST(total AS TEXT) LIKE '%' || $1 || '%'
              )
            ORDER BY fecha_cfdi DESC
            LIMIT 50
            """,
            q,
        )
    else:
        rows = await conn.fetch(
            """
            SELECT id, uuid_cfdi, rfc_emisor, nombre_emisor, total, moneda,
                   fecha_cfdi, tipo_detectado
            FROM tb_sat_inbox
            WHERE estado = 'pendiente'
              AND total IS NOT NULL
              AND COALESCE(moneda, 'MXN') = $4
              AND (
                  ($2 <> '' AND (
                      COALESCE(nombre_emisor, '') ILIKE '%' || $2 || '%'
                      OR $2 ILIKE '%' || COALESCE(nombre_emisor, '') || '%'
                  ))
                  OR ($3::text IS NOT NULL AND rfc_emisor = $3)
              )
              AND (
                  (
                      COALESCE(tipo_detectado, 'NORMAL') != 'CIERRE_ANTICIPO'
                      AND $5 IN ('PENDIENTE', 'PARCIALMENTE_FACTURADO')
                      AND (
                          ABS(total - $1) <= 1.00
                          OR (
                              $3::text IS NOT NULL
                              AND rfc_emisor = $3
                              AND total <= ($1 - $6::numeric) + 0.50
                          )
                      )
                  )
                  OR (
                      tipo_detectado = 'CIERRE_ANTICIPO'
                      AND $5 = 'ANTICIPO'
                      AND total <= $1 + 0.50
                  )
              )
            ORDER BY
              CASE
                WHEN ABS(total - $1) <= 1.00 THEN 0
                ELSE 1
              END,
              ABS(total - ($1 - $6::numeric)) ASC,
              fecha_cfdi DESC
            """,
            monto,
            beneficiario_orig,
            proveedor_rfc,
            moneda or "MXN",
            estatus or "",
            monto_facturado or 0,
        )
    return [dict(r) for r in rows]
