import asyncio
import io
import logging
import zipfile
from datetime import date, timedelta
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

SAT_JOB_MAX_RUNTIME_MINUTES = 120


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


def _job_excedio_tiempo(created_at, max_runtime_minutes: int = SAT_JOB_MAX_RUNTIME_MINUTES) -> bool:
    if not created_at:
        return False
    return now_mx() - created_at > timedelta(minutes=max_runtime_minutes)


async def procesar_siguiente_job_pendiente() -> bool:
    """
    Toma el job SAT no terminal mas antiguo y lo procesa desde el worker.
    """
    from core.database import get_db_pool

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        expirados = await sat_db_service.marcar_jobs_expirados(
            conn,
            SAT_JOB_MAX_RUNTIME_MINUTES,
        )
        if expirados:
            logger.warning("[SAT Worker] Jobs expirados marcados como error: %s", expirados)

        job = await sat_db_service.obtener_job_activo_para_worker(conn)

    if not job:
        return False

    logger.info(
        "[SAT Worker] Procesando job %s estado=%s solicitud=%s",
        job["id"],
        job["estado"],
        job.get("id_solicitud_sat") or "pendiente",
    )
    await ejecutar_descarga(job["id"])
    return True


async def ejecutar_descarga(
    job_id: UUID,
    fecha_inicio: date | None = None,
    fecha_fin: date | None = None,
    rfc_emisor: str | None = None,
) -> None:
    """
    Descarga CFDIs del SAT para un job persistido.
    Si el job ya tiene id_solicitud_sat, reanuda el polling sin crear otra solicitud.
    """
    from core.database import get_db_pool

    pool = await get_db_pool()

    async def update(estado: str = None, **kwargs):
        async with pool.acquire() as c:
            fields = {}
            if estado:
                fields["estado"] = estado
            fields.update(kwargs)
            await sat_db_service.actualizar_job(c, job_id, **fields)

    try:
        async with pool.acquire() as conn:
            job = await sat_db_service.obtener_job_status(conn, job_id)

        if job["estado"] in {"completado", "error"}:
            logger.info("Job SAT %s ya esta en estado terminal: %s", job_id, job["estado"])
            return

        fecha_inicio = fecha_inicio or job["fecha_inicio_rango"]
        fecha_fin = fecha_fin or job["fecha_fin_rango"]
        rfc_emisor = rfc_emisor or job.get("rfc_emisor_filtro")
        id_solicitud = job.get("id_solicitud_sat")
        created_at = job.get("created_at")

        if _job_excedio_tiempo(created_at):
            mensaje = "La consulta SAT excedio el tiempo maximo y fue marcada como interrumpida."
            await update(estado="error", mensaje_error=mensaje)
            logger.warning("Job SAT %s expirado antes de procesar", job_id)
            return

        async with pool.acquire() as conn:
            sat_site_id, sat_drive_id, base_folder = await _get_sat_sp_config(conn)
            signer = await cargar_signer(conn, sat_site_id, sat_drive_id)

        token = await get_ms_auth().get_application_token()
        if not token:
            raise ValueError("No se pudo obtener token de aplicacion Microsoft")

        sp = SharePointService(access_token=token)
        sp.site_id = sat_site_id
        sp.drive_id = sat_drive_id

        client = SATClient(signer=signer)
        if id_solicitud:
            logger.info("Job SAT %s reanudando solicitud SAT %s", job_id, id_solicitud)
            await update(estado="esperando_sat")
        else:
            await update(estado="solicitando")
            id_solicitud = await client.solicitar_descarga(fecha_inicio, fecha_fin, rfc_emisor)
            await update(estado="esperando_sat", id_solicitud_sat=id_solicitud)

        async def on_poll(codigo, label):
            logger.info("SAT polling - estado: %s (%s)", codigo, label)
            if _job_excedio_tiempo(created_at):
                raise TimeoutError("La consulta SAT excedio el tiempo maximo permitido.")
            await update(estado="esperando_sat")

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

            # Parsear todos los XMLs del paquete antes de consultar BD
            parsed: list[tuple] = []
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                for nombre in zf.namelist():
                    if not nombre.lower().endswith(".xml"):
                        continue
                    xml_bytes = zf.read(nombre)
                    try:
                        cfdi = parse_cfdi_xml(xml_bytes, nombre)
                        parsed.append((cfdi, xml_bytes))
                    except ValueError as e:
                        logger.warning(
                            "XML no parseable en paquete %s/%s: %s",
                            id_paquete, nombre, e,
                        )

            # Una sola consulta para todos los UUIDs del paquete
            async with pool.acquire() as conn:
                ya_existentes = await sat_db_service.uuids_existentes(
                    conn, [cfdi.uuid for cfdi, _ in parsed]
                )

            # Procesar cada CFDI usando el set en memoria
            for cfdi, xml_bytes in parsed:
                total_encontrados += 1
                tipo = cfdi.tipo_factura.value if cfdi.tipo_factura else "NORMAL"

                if cfdi.uuid in ya_existentes:
                    total_duplicados += 1
                    async with pool.acquire() as conn:
                        await sat_db_service.registrar_cfdi_descargado(
                            conn, job_id, cfdi, "", None, "duplicado",
                            tipo_detectado=tipo,
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
                            tipo_detectado=tipo,
                        )
                except Exception as e:
                    logger.error("Error subiendo XML %s a SharePoint: %s", cfdi.uuid, e)
                    total_errores += 1

        await update(
            estado="completado" if total_errores == 0 else "error",
            cfdi_encontrados=total_encontrados,
            cfdi_duplicados=total_duplicados,
            mensaje_error=f"{total_errores} errores al subir a SharePoint." if total_errores > 0 else None,
        )
        logger.info(
            "Job SAT %s completado - %d CFDIs, %d duplicados, %d errores",
            job_id,
            total_encontrados,
            total_duplicados,
            total_errores,
        )

    except asyncio.CancelledError:
        logger.warning("Job SAT %s cancelado por parada del worker; quedara pendiente para recuperacion", job_id)
        raise
    except TimeoutError as e:
        logger.error("Timeout en job SAT %s: %s", job_id, e)
        await update(estado="error", mensaje_error=str(e)[:500])
    except asyncpg.PostgresError as e:
        logger.error("Error de BD en job SAT %s: %s", job_id, e)
        await update(estado="error", mensaje_error=str(e)[:500])
    except ValueError as e:
        logger.error("Error de validacion en job SAT %s: %s", job_id, e)
        await update(estado="error", mensaje_error=str(e)[:500])
    except Exception as e:
        logger.error("Error inesperado en job SAT %s: %s", job_id, e, exc_info=True)
        await update(estado="error", mensaje_error=str(e)[:500])
