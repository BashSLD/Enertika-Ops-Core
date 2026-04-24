import asyncio
import logging
import tempfile
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


async def _actualizar_job(conn: asyncpg.Connection, job_id: UUID, **kwargs) -> None:
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
            SELECT 1 FROM tb_xml_staging WHERE uuid_cfdi = $1
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
    usuario_id: int,
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
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[dict], int]:
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
               i.factura_id, i.sharepoint_url, i.created_at
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


async def marcar_matcheado(
    conn: asyncpg.Connection,
    inbox_id: UUID,
    factura_id: int,
) -> None:
    result = await conn.execute(
        "UPDATE tb_sat_inbox SET estado = 'matcheado', factura_id = $2, updated_at = NOW() "
        "WHERE id = $1",
        inbox_id, factura_id,
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
    import httpx
    row = await conn.fetchrow(
        "SELECT sharepoint_url, uuid_cfdi FROM tb_sat_inbox WHERE id = $1 AND estado = 'pendiente'",
        inbox_id,
    )
    if not row:
        raise ValueError("Item no encontrado o no esta en estado pendiente")

    token = await get_ms_auth().get_application_token()
    if not token:
        raise ValueError("No se pudo obtener token de aplicacion para descargar XML")

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        resp = await client.get(
            row["sharepoint_url"],
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        return resp.content, row["uuid_cfdi"]


async def ejecutar_descarga(job_id: UUID, fecha_inicio: date, fecha_fin: date) -> None:
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
        id_solicitud = await client.solicitar_descarga(fecha_inicio, fecha_fin)
        await update(estado="esperando_sat", id_solicitud_sat=id_solicitud)

        async def on_poll(codigo, label):
            logger.info("SAT polling - estado: %s (%s)", codigo, label)

        ids_paquetes = await client.esperar_paquetes(id_solicitud, on_poll=on_poll)
        await update(estado="descargando")

        total_encontrados = 0
        total_duplicados = 0
        now = now_mx()
        year_str = now.strftime("%Y")
        month_str = now.strftime("%m")

        for id_paquete in ids_paquetes:
            zip_bytes = await client.descargar_paquete(id_paquete)
            await update(estado="procesando")

            with tempfile.NamedTemporaryFile(suffix=".zip", delete=True) as tmp:
                tmp.write(zip_bytes)
                tmp.flush()

                with zipfile.ZipFile(tmp.name) as zf:
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
                                await conn.execute(
                                    """
                                    INSERT INTO tb_sat_inbox
                                      (job_id, uuid_cfdi, rfc_emisor, nombre_emisor,
                                       fecha_cfdi, total, moneda, sharepoint_url, estado)
                                    VALUES ($1,$2,$3,$4,$5,$6,$7,'','duplicado')
                                    ON CONFLICT (uuid_cfdi) DO NOTHING
                                    """,
                                    job_id, cfdi.uuid, cfdi.emisor_rfc, cfdi.emisor_nombre,
                                    cfdi.fecha[:10] if cfdi.fecha else None,
                                    cfdi.total, cfdi.moneda,
                                )
                            continue

                        carpeta = f"{base_folder}/ISA/{year_str}/{month_str}"
                        filename = f"{cfdi.uuid}.xml"
                        sharepoint_url = ""
                        sharepoint_item_id = None
                        try:
                            result = await sp.upload_bytes_direct(xml_bytes, filename, carpeta)
                            sharepoint_url = result.get("webUrl", "")
                            sharepoint_item_id = result.get("id")
                        except Exception as e:
                            logger.error(
                                "Error subiendo XML %s a SharePoint: %s",
                                cfdi.uuid, e,
                            )

                        async with pool.acquire() as conn:
                            await conn.execute(
                                """
                                INSERT INTO tb_sat_inbox
                                  (job_id, uuid_cfdi, rfc_emisor, nombre_emisor,
                                   fecha_cfdi, total, moneda, sharepoint_url,
                                   sharepoint_item_id, estado)
                                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,'pendiente')
                                ON CONFLICT (uuid_cfdi) DO NOTHING
                                """,
                                job_id, cfdi.uuid, cfdi.emisor_rfc, cfdi.emisor_nombre,
                                cfdi.fecha[:10] if cfdi.fecha else None,
                                cfdi.total, cfdi.moneda,
                                sharepoint_url, sharepoint_item_id,
                            )

        await update(
            estado="completado",
            cfdi_encontrados=total_encontrados,
            cfdi_duplicados=total_duplicados,
        )
        logger.info(
            "Job SAT %s completado - %d CFDIs, %d duplicados",
            job_id, total_encontrados, total_duplicados,
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
