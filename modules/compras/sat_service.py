import asyncio
import io
import logging
import zipfile
from datetime import date
from uuid import UUID

import asyncpg

from core.config import settings
from core.integrations.sharepoint import SharePointService
from core.microsoft import get_ms_auth
from core.timezone import now_mx
from core.sat.client import SATClient
from core.sat.fiel_loader import cargar_signer
from modules.compras.xml_extractor import parse_cfdi_xml
from modules.compras import sat_db_service

logger = logging.getLogger("ComprasSATService")


async def _get_sat_sp_config(conn: asyncpg.Connection) -> tuple[str, str, str]:
    """
    Retorna (site_id, drive_id, base_folder) para el site SAT.
    Prioridad: BD > env var.
    """
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


async def _actualizar_job(conn: asyncpg.Connection, job_id: UUID, **kwargs) -> None:
    invalid = set(kwargs) - _ALLOWED_JOB_FIELDS
    if invalid:
        raise ValueError(f"Campos de job no permitidos: {invalid}")
    sets = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(kwargs))
    values = list(kwargs.values())
    await conn.execute(
        f"UPDATE tb_sat_jobs SET {sets}, updated_at = NOW() WHERE id = $1",
        job_id, *values,
    )


async def _uuid_ya_existe(conn: asyncpg.Connection, uuid_cfdi: str) -> bool:
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
    """Retorna True si hay un job en estado no terminal creado en las ultimas 2 horas."""
    row = await conn.fetchrow(
        "SELECT EXISTS ("
        "  SELECT 1 FROM tb_sat_jobs"
        "  WHERE estado NOT IN ('completado', 'error')"
        "  AND created_at > NOW() - INTERVAL '2 hours'"
        ")"
    )
    return row[0]


async def crear_job(
    conn: asyncpg.Connection,
    fecha_inicio: date,
    fecha_fin: date,
    usuario_id: UUID,
) -> UUID:
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


async def listar_inbox(
    conn: asyncpg.Connection,
    estado: str | None = None,
    limit: int = 50,
) -> tuple[list[dict], int]:
    return await sat_db_service.listar_inbox(conn, estado=estado, limit=limit)


async def descartar_inbox_item(conn: asyncpg.Connection, inbox_id: UUID) -> None:
    result = await conn.execute(
        "UPDATE tb_sat_inbox SET estado = 'descartado', updated_at = NOW() WHERE id = $1",
        inbox_id,
    )
    if result == "UPDATE 0":
        raise ValueError(f"Item de inbox no encontrado: {inbox_id}")


async def marcar_matcheado(
    conn: asyncpg.Connection,
    inbox_id: UUID,
    comprobante_id: UUID,
) -> None:
    result = await conn.execute(
        "UPDATE tb_sat_inbox SET estado = 'matcheado', comprobante_id = $2, updated_at = NOW() "
        "WHERE id = $1",
        inbox_id, comprobante_id,
    )
    if result == "UPDATE 0":
        raise ValueError(f"Item de inbox no encontrado: {inbox_id}")


async def descargar_xml_de_inbox(
    conn: asyncpg.Connection,
    inbox_id: UUID,
) -> tuple[bytes, str]:
    """
    Descarga el XML de SharePoint para un item del inbox.
    Retorna (xml_bytes, uuid_cfdi).
    """
    row = await sat_db_service.obtener_inbox_item_para_descarga(conn, inbox_id)
    if not row["sharepoint_item_id"]:
        raise ValueError("Item no tiene sharepoint_item_id en SharePoint")

    sat_site_id, sat_drive_id, _ = await _get_sat_sp_config(conn)

    token = await get_ms_auth().get_application_token()
    if not token:
        raise ValueError("No se pudo obtener token de aplicacion para descargar XML")

    sp = SharePointService(access_token=token)
    sp.site_id = sat_site_id
    sp.drive_id = sat_drive_id

    content = await sp.download_bytes_direct_by_item_id(row["sharepoint_item_id"])
    head = content[:200].lstrip(b"\xef\xbb\xbf\r\n\t ").lower()
    if not head.startswith(b"<") or head.startswith(b"<html") or head.startswith(b"<!doctype html"):
        raise ValueError("El archivo descargado de SharePoint no parece ser un XML CFDI valido")
    return content, row["uuid_cfdi"]


async def obtener_cfdi_inbox(conn: asyncpg.Connection, inbox_id: UUID):
    xml_bytes, uuid_cfdi = await descargar_xml_de_inbox(conn, inbox_id)
    return parse_cfdi_xml(xml_bytes, f"{uuid_cfdi}.xml")


async def buscar_comprobantes_match(
    conn: asyncpg.Connection,
    q: str,
    limit: int = 10,
) -> list[dict]:
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


async def ejecutar_descarga(job_id: UUID, fecha_inicio: date, fecha_fin: date, rfc_emisor: str | None = None) -> None:
    """
    Background task: descarga CFDIs del SAT para el rango de fechas dado.
    Obtiene su propia conexion del pool — no usa la conexion del request.
    """
    from core.database import get_db_pool
    pool = await get_db_pool()

    async def update(estado: str = None, **kwargs):
        async with pool.acquire() as c:
            fields = {}
            if estado:
                fields["estado"] = estado
            fields.update(kwargs)
            await _actualizar_job(c, job_id, **fields)

    try:
        async with pool.acquire() as conn:
            sat_site_id, sat_drive_id, base_folder = await _get_sat_sp_config(conn)
            signer = await cargar_signer(conn, sat_site_id, sat_drive_id)

        token = await get_ms_auth().get_application_token()
        if not token:
            raise ValueError("No se pudo obtener token de aplicacion Microsoft")

        sp = SharePointService(access_token=token)
        sp.site_id = sat_site_id
        sp.drive_id = sat_drive_id

        await update(estado="solicitando")
        client = SATClient(signer=signer)
        id_solicitud = await client.solicitar_descarga(fecha_inicio, fecha_fin, rfc_emisor)
        await update(estado="esperando_sat", id_solicitud_sat=id_solicitud)

        async def on_poll(codigo, label):
            logger.info("SAT polling - estado: %s (%s)", codigo, label)

        ids_paquetes = await client.esperar_paquetes(id_solicitud, on_poll=on_poll)
        await update(estado="descargando")

        total_encontrados = 0
        total_duplicados = 0
        total_errores = 0
        now = now_mx()
        year_str = now.strftime("%Y")
        month_str = now.strftime("%m")

        for id_paquete in ids_paquetes:
            zip_bytes = await client.descargar_paquete(id_paquete)
            await update(estado="procesando")

            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                    for nombre in zf.namelist():
                        if not nombre.lower().endswith(".xml"):
                            continue

                        xml_bytes = zf.read(nombre)

                        try:
                            cfdi = parse_cfdi_xml(xml_bytes, nombre)
                        except ValueError as e:
                            logger.warning(
                                "XML no parseable en paquete %s/%s: %s",
                                id_paquete, nombre, e,
                            )
                            continue

                        total_encontrados += 1

                        async with pool.acquire() as conn:
                            es_duplicado = await _uuid_ya_existe(conn, cfdi.uuid)

                        if es_duplicado:
                            total_duplicados += 1
                            async with pool.acquire() as conn:
                                await sat_db_service.registrar_cfdi_descargado(
                                    conn, job_id, cfdi, "", None, "duplicado",
                                    tipo_detectado=cfdi.tipo_factura.value if cfdi.tipo_factura else "NORMAL",
                                )
                            continue

                        carpeta = f"{base_folder}/ISA/{year_str}/{month_str}"
                        filename = f"{cfdi.uuid}.xml"

                        try:
                            result = await sp.upload_bytes_direct(xml_bytes, filename, carpeta)
                            sharepoint_url = result.get("webUrl", "")
                            sharepoint_item_id = result.get("id")

                            async with pool.acquire() as conn:
                                await sat_db_service.registrar_cfdi_descargado(
                                    conn, job_id, cfdi, sharepoint_url, sharepoint_item_id, "pendiente",
                                    tipo_detectado=cfdi.tipo_factura.value if cfdi.tipo_factura else "NORMAL",
                                )
                        except Exception as e:
                            logger.error(
                                "Error subiendo XML %s a SharePoint: %s",
                                cfdi.uuid, e,
                            )
                            # No se registra en tb_sat_inbox para permitir reintento en el siguiente job
                            total_errores += 1

        await update(
            estado="completado" if total_errores == 0 else "error",
            cfdi_encontrados=total_encontrados,
            cfdi_duplicados=total_duplicados,
            mensaje_error=f"{total_errores} errores al subir a SharePoint." if total_errores > 0 else None,
        )
        logger.info(
            "Job SAT %s completado - %d CFDIs, %d duplicados, %d errores",
            job_id, total_encontrados, total_duplicados, total_errores,
        )

    except asyncpg.PostgresError as e:
        logger.error("Error de BD en job SAT %s: %s", job_id, e)
        await update(estado="error", mensaje_error=str(e)[:500])
    except ValueError as e:
        logger.error("Error de validacion en job SAT %s: %s", job_id, e)
        await update(estado="error", mensaje_error=str(e)[:500])
    except Exception as e:
        logger.error("Error inesperado en job SAT %s: %s", job_id, e, exc_info=True)
        await update(estado="error", mensaje_error=str(e)[:500])
