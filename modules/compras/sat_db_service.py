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

async def uuid_ya_existe(conn: asyncpg.Connection, uuid_cfdi: str) -> bool:
    row = await conn.fetchrow(
        """
        SELECT EXISTS (
            SELECT 1 FROM tb_sat_inbox WHERE uuid_cfdi = $1
            UNION ALL
            SELECT 1 FROM tb_xml_staging WHERE uuid_factura = $1
        )
        """,
        uuid_cfdi,
    )
    return row[0]

async def hay_job_activo(conn: asyncpg.Connection) -> bool:
    row = await conn.fetchrow(
        "SELECT EXISTS ("
        "  SELECT 1 FROM tb_sat_jobs"
        "  WHERE estado NOT IN ('completado', 'error')"
        "  AND created_at > NOW() - INTERVAL '2 hours'"
        ")"
    )
    return row[0]

async def crear_job(conn: asyncpg.Connection, fecha_inicio: date, fecha_fin: date, usuario_id: UUID) -> UUID:
    row = await conn.fetchrow(
        """
        INSERT INTO tb_sat_jobs (fecha_inicio_rango, fecha_fin_rango, creado_por, estado)
        VALUES ($1, $2, $3, 'iniciando')
        RETURNING id
        """,
        fecha_inicio, fecha_fin, usuario_id,
    )
    return row["id"]

async def obtener_job_status(conn: asyncpg.Connection, job_id: UUID) -> dict:
    row = await conn.fetchrow(
        "SELECT id, estado, cfdi_encontrados, cfdi_duplicados, mensaje_error, "
        "fecha_inicio_rango, fecha_fin_rango, created_at, updated_at "
        "FROM tb_sat_jobs WHERE id = $1",
        job_id,
    )
    if not row:
        raise ValueError(f"Job no encontrado: {job_id}")
    return dict(row)

async def obtener_ultimo_job(conn: asyncpg.Connection) -> dict | None:
    row = await conn.fetchrow(
        "SELECT id, estado, cfdi_encontrados, cfdi_duplicados, mensaje_error, "
        "fecha_inicio_rango, fecha_fin_rango, created_at "
        "FROM tb_sat_jobs ORDER BY created_at DESC LIMIT 1"
    )
    return dict(row) if row else None

async def listar_inbox(conn: asyncpg.Connection, estado: str | None = None, page: int = 1, page_size: int = 50) -> tuple[list[dict], int]:
    filtros = []
    params: list = []
    if estado and estado != "todos":
        params.append(estado)
        filtros.append(f"i.estado = ${len(params)}")
    else:
        filtros.append("i.estado != 'descartado'")
    where = f"WHERE {' AND '.join(filtros)}" if filtros else ""
    offset = (page - 1) * page_size
    n_params = len(params)
    params.extend([page_size, offset])
    rows = await conn.fetch(
        f"""
        SELECT i.id, i.uuid_cfdi, i.rfc_emisor, i.nombre_emisor,
               i.fecha_cfdi, i.total, i.moneda, i.estado,
               i.comprobante_id, i.sharepoint_url, i.created_at
        FROM tb_sat_inbox i
        {where}
        ORDER BY i.created_at DESC
        LIMIT ${n_params + 1} OFFSET ${n_params + 2}
        """,
        *params,
    )
    count_row = await conn.fetchrow(
        f"SELECT COUNT(*) FROM tb_sat_inbox i {where}", *params[:n_params]
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
               p.razon_social AS proveedor_nombre, p.rfc AS proveedor_rfc
        FROM tb_comprobantes_pago c
        LEFT JOIN tb_proveedores p ON c.id_proveedor = p.id_proveedor
        WHERE c.estatus = 'PENDIENTE'
        ORDER BY COALESCE(p.razon_social, c.beneficiario_orig) ASC, c.monto DESC
        """
    )
    return [dict(r) for r in rows]

async def listar_comprobantes_anticipo(conn: asyncpg.Connection, rfc_emisor: str) -> list[dict]:
    """Comprobantes en estatus ANTICIPO del proveedor con el RFC indicado.
    Usado en el modal cuando el CFDI es CIERRE_ANTICIPO.
    """
    rows = await conn.fetch(
        """
        SELECT c.id_comprobante, c.fecha_pago, c.beneficiario_orig, c.monto, c.moneda,
               p.razon_social AS proveedor_nombre, p.rfc AS proveedor_rfc
        FROM tb_comprobantes_pago c
        JOIN tb_proveedores p ON p.id_proveedor = c.id_proveedor
        WHERE c.estatus = 'ANTICIPO'
          AND p.rfc = $1
        ORDER BY c.fecha_pago DESC
        """,
        rfc_emisor,
    )
    return [dict(r) for r in rows]

async def buscar_coincidencias_auto(conn: asyncpg.Connection) -> list[dict]:
    # Busca pares únicos (1 a 1) entre facturas pendientes del SAT y comprobantes pendientes.
    # Caso 1 (NORMAL): empareja por monto ±0.50 y nombre vs comprobantes PENDIENTE/PARCIALMENTE_FACTURADO.
    # Caso 2 (CIERRE_ANTICIPO): empareja por RFC vs comprobantes en estatus ANTICIPO (sin validar monto).
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
