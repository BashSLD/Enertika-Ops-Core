# modules/cfe/service.py
from __future__ import annotations

import asyncio
import base64
import logging
from io import BytesIO
from typing import Optional
from uuid import UUID

import asyncpg
import httpx
from fastapi import UploadFile

from core.database import get_db_pool
from core.config_service import ConfigService
from core.integrations.sharepoint import SharePointService
from core.microsoft import get_ms_auth
from modules.admin.db_service import AdminDBService
from modules.shared.services.cfe.extractor import extraer_datos_xml
from modules.shared.services.cfe.excel import generar_excel_cfe
from modules.shared.services.cfe.schemas import CfeXmlInput

from .constants import CFE_CONFIG_KEYS, SHAREPOINT_CFE_ROOT
from .db_service import CfeDBService, get_cfe_db_service
from .scraper import CfeScraperConfig, descargar_recibo

logger = logging.getLogger("CfeService")

_scrape_lock = asyncio.Semaphore(1)


class CfeService:

    def __init__(self, db: CfeDBService):
        self.db = db
        self._admin_db = AdminDBService()

    # ── Config helpers ────────────────────────────────────────────────────

    async def _get_cfe_config(self, conn: asyncpg.Connection) -> dict:
        """Reads CFE credentials from tb_configuracion_global."""
        return {
            "mi_user": await ConfigService.get_global_config(conn, CFE_CONFIG_KEYS["mi_user"], "", str),
            "mi_pass": await ConfigService.get_global_config(conn, CFE_CONFIG_KEYS["mi_pass"], "", str),
            "session_json": await ConfigService.get_global_config(conn, CFE_CONFIG_KEYS["session_json"], "", str) or None,
        }

    async def _save_session(self, conn: asyncpg.Connection, session_json: str) -> None:
        await self._admin_db.upsert_global_config(conn, CFE_CONFIG_KEYS["session_json"], session_json)
        ConfigService.invalidar_cache()

    # ── Servicios ─────────────────────────────────────────────────────────

    async def listar_servicios(self, conn: asyncpg.Connection) -> list[dict]:
        return await self.db.get_all_servicios(conn)

    async def crear_servicio(
        self, conn: asyncpg.Connection, *, numero_servicio: str, nombre: str,
        alias: Optional[str], lada: str, telefono: str, email: str, usuario_id: UUID,
    ) -> dict:
        # CFE exige el nombre del servicio SIEMPRE en mayusculas (portal publico + MiEspacio).
        # Se normaliza aqui para que quede asi almacenado y lo use tambien el scraper.
        nombre = (nombre or "").strip().upper()

        existing = await self.db.get_servicio_by_numero(conn, numero_servicio)
        if existing:
            raise ValueError(
                f"El número de servicio {numero_servicio} ya está registrado "
                f"como '{existing['nombre']}'."
            )
        return await self.db.crear_servicio(
            conn, numero_servicio=numero_servicio, nombre=nombre, alias=alias,
            lada=lada, telefono=telefono, email=email, creado_por=usuario_id,
        )

    # ── Descarga ──────────────────────────────────────────────────────────

    async def iniciar_descarga(
        self,
        conn: asyncpg.Connection,
        servicio_id: UUID,
        usuario_id: UUID,
    ) -> tuple[str, dict]:
        """
        Encola una descarga. NO ejecuta nada en el proceso web: solo inserta el
        placeholder 'pendiente'. El worker lo recoge en su siguiente ciclo (~30s).
        El UNIQUE(servicio_id, 'pendiente', 'xml') garantiza una sola en cola por servicio.
        Retorna (mensaje, servicio) para que el router no necesite re-fetchear el servicio.
        """
        if await self.db.tiene_descarga_en_progreso(conn, servicio_id):
            raise ValueError("Ya hay una descarga en curso para este servicio.")

        servicio = await self.db.get_servicio_by_id(conn, servicio_id)
        if not servicio:
            raise ValueError("Servicio no encontrado.")

        await self.db.upsert_descarga(
            conn, servicio_id=servicio_id, periodo="pendiente", tipo="xml",
            estatus="pendiente", descargado_por=usuario_id,
        )
        return "Descarga encolada. La página se actualizará automáticamente.", servicio

    # ── Worker: consumo de la cola ───────────────────────────────────────────

    async def procesar_pendientes(self, pool: asyncpg.Pool) -> None:
        """
        Llamado por el worker en cada ciclo. Reclama UN trabajo (atomico) y lo ejecuta
        con timeout. Procesa de a uno por ciclo para acotar memoria/CPU.
        """
        async with pool.acquire() as conn:
            job = await self.db.reclamar_trabajo(conn)
        if not job:
            return

        async with pool.acquire() as conn:
            servicio = await self.db.get_servicio_by_id(conn, job["servicio_id"])
            cfg_global = await self._get_cfe_config(conn)
        if not servicio:
            async with pool.acquire() as conn:
                await self.db.borrar_descarga_pendiente(conn, job["servicio_id"])
            return

        async with _scrape_lock:
            try:
                await asyncio.wait_for(
                    self._ejecutar_descarga(
                        pool=pool, servicio=servicio,
                        cfg_global=cfg_global, usuario_id=job["descargado_por"],
                    ),
                    timeout=180,
                )
            except asyncio.TimeoutError:
                async with pool.acquire() as conn:
                    await self.db.marcar_pendiente_error(
                        conn, servicio["id"], "La descarga excedio el tiempo limite (3 min)."
                    )

    async def reaper_colgados(self, pool: asyncpg.Pool) -> None:
        """Marca error trabajos atascados en 'descargando' (worker reiniciado a mitad)."""
        async with pool.acquire() as conn:
            await self.db.reaper_descargando(conn, minutos=15)

    async def _ejecutar_descarga(
        self,
        pool: asyncpg.Pool,
        servicio: dict,
        cfg_global: dict,
        usuario_id: UUID,
    ) -> None:
        """Background task: scrape → SharePoint upload → DB record."""
        cfg = CfeScraperConfig(
            nombre=servicio["nombre"],
            numero_servicio=servicio["numero_servicio"],
            lada=servicio["lada"],
            telefono=servicio["telefono"],
            email=servicio["email"],
            alias=servicio.get("alias") or servicio["numero_servicio"][:20],
            mi_user=cfg_global["mi_user"],
            mi_pass=cfg_global["mi_pass"],
            session_json=cfg_global["session_json"],
        )

        result = await descargar_recibo(cfg)

        async with pool.acquire() as conn:
            # Delta guard: aplica en éxito Y en error para no sobreescribir un completado.
            if result.periodo:
                completados = await self.db.get_periodos_completados(conn, servicio["id"])
                if result.periodo in completados:
                    logger.info(
                        f"Periodo {result.periodo} ya descargado para {servicio['numero_servicio']}, omitiendo."
                    )
                    await self.db.borrar_descarga_pendiente(conn, servicio["id"])
                    return

            if result.error:
                await self.db.upsert_descarga(
                    conn, servicio_id=servicio["id"], periodo=result.periodo or "desconocido",
                    tipo="xml", estatus="error", error_mensaje=result.error,
                    descargado_por=usuario_id,
                )
                # Limpiar el placeholder 'pendiente' (reclamar_trabajo lo dejo en 'descargando').
                # Sin esto, tiene_descarga_en_progreso bloquea el reintento hasta el reaper (15 min).
                await self.db.borrar_descarga_pendiente(conn, servicio["id"])
                return

            # Upload XML to SharePoint
            xml_sp_url = await self._upload_to_sharepoint(
                conn, content=result.xml_content, filename=result.xml_filename,
                servicio_numero=servicio["numero_servicio"], periodo=result.periodo, tipo="xml",
            )
            await self._registrar_descarga_sp(
                conn, servicio_id=servicio["id"], periodo=result.periodo, tipo="xml",
                nombre_archivo=result.xml_filename, sp_url=xml_sp_url, usuario_id=usuario_id,
            )

            if result.pdf_content:
                pdf_sp_url = await self._upload_to_sharepoint(
                    conn, content=result.pdf_content, filename=result.pdf_filename,
                    servicio_numero=servicio["numero_servicio"], periodo=result.periodo, tipo="pdf",
                )
                await self._registrar_descarga_sp(
                    conn, servicio_id=servicio["id"], periodo=result.periodo, tipo="pdf",
                    nombre_archivo=result.pdf_filename, sp_url=pdf_sp_url, usuario_id=usuario_id,
                )

            await self.db.borrar_descarga_pendiente(conn, servicio["id"])

            # Persist updated session
            if result.session_json_nuevo:
                await self._save_session(conn, result.session_json_nuevo)

    async def _registrar_descarga_sp(
        self, conn: asyncpg.Connection, *, servicio_id: UUID, periodo: str,
        tipo: str, nombre_archivo: str, sp_url: Optional[str], usuario_id: Optional[UUID],
    ) -> None:
        await self.db.upsert_descarga(
            conn, servicio_id=servicio_id, periodo=periodo, tipo=tipo,
            estatus="completado" if sp_url else "error",
            nombre_archivo=nombre_archivo, ruta_sharepoint=sp_url,
            error_mensaje=None if sp_url else f"Error subiendo {tipo.upper()} a SharePoint",
            descargado_por=usuario_id,
        )

    async def _upload_to_sharepoint(
        self,
        conn: asyncpg.Connection,
        *,
        content: bytes,
        filename: str,
        servicio_numero: str,
        periodo: str,
        tipo: str,
    ) -> Optional[str]:
        """Uploads bytes to SharePoint. Returns webUrl or None on failure."""
        try:
            ms_auth = get_ms_auth()
            token = await ms_auth.get_application_token()
            if not token:
                raise RuntimeError("No se pudo obtener token de Microsoft")

            sp = SharePointService(access_token=token)
            # Guard (patron proveedores): validar la config resuelta (BD > Settings) para NO caer
            # silenciosamente a OneDrive personal. upload_file re-resuelve la config internamente
            # via _resolve_config, asi que aqui solo validamos (no asignamos atributos: upload_file
            # los ignora y usaria su propia resolucion).
            sp_cfg = await sp._resolve_config(conn)
            if not sp_cfg.get("site_id") and not sp_cfg.get("drive_id"):
                raise RuntimeError(
                    "SharePoint no configurado (SHAREPOINT_SITE_ID/DRIVE_ID). "
                    "Configuralos en Admin antes de descargar recibos CFE."
                )
            folder = f"{SHAREPOINT_CFE_ROOT}/{servicio_numero}/{periodo}"

            upload = UploadFile(filename=filename, file=BytesIO(content))
            result = await sp.upload_file(conn=conn, file=upload, folder_path=folder)
            return result.get("webUrl")
        except Exception as exc:
            logger.error(f"Error subiendo {tipo} a SharePoint para {servicio_numero}/{periodo}: {exc}")
            return None

    # ── Excel ─────────────────────────────────────────────────────────────

    async def generar_excel(
        self,
        conn: asyncpg.Connection,
        servicio_id: UUID,
        periodos: list[str],
        perfil_slug: str,
    ) -> bytes:
        """
        Downloads XML content from SharePoint for each requested period
        and generates an Excel file using the existing CFE excel service.
        """
        descargas = await self.db.get_descargas_por_servicio(conn, servicio_id)
        xml_rows = [
            d for d in descargas
            if d["tipo"] == "xml" and d["estatus"] == "completado" and d["periodo"] in periodos
        ]

        if not xml_rows:
            raise ValueError("No hay XMLs descargados para los periodos seleccionados.")

        ms_auth = get_ms_auth()
        token = await ms_auth.get_application_token()
        if not token:
            raise ValueError("No se pudo obtener token de Microsoft para leer SharePoint.")

        async def _fetch_xml(client: httpx.AsyncClient, row: dict) -> Optional[CfeXmlInput]:
            url = row["ruta_sharepoint"]
            if not url:
                return None
            download_url = await _resolve_sharepoint_download_url(client, token, url)
            if not download_url:
                return None
            resp = await client.get(download_url, headers={"Authorization": f"Bearer {token}"})
            if resp.status_code == 200:
                return CfeXmlInput(filename=row["nombre_archivo"] or "recibo.xml", content=resp.content)
            return None

        async with httpx.AsyncClient(timeout=30) as client:
            results = await asyncio.gather(*[_fetch_xml(client, row) for row in xml_rows])

        inputs = [r for r in results if r is not None]
        if not inputs:
            raise ValueError("No se pudieron obtener los XMLs desde SharePoint.")

        return generar_excel_cfe(inputs, perfil_slug).getvalue()

    # ── Vista previa ──────────────────────────────────────────────────────

    async def get_url_preview(
        self, conn: asyncpg.Connection, descarga_id: UUID, servicio_id: UUID
    ) -> Optional[str]:
        row = await conn.fetchrow(
            "SELECT ruta_sharepoint FROM tb_cfe_descargas WHERE id=$1 AND servicio_id=$2",
            descarga_id, servicio_id,
        )
        return row["ruta_sharepoint"] if row else None


async def _resolve_sharepoint_download_url(
    client: httpx.AsyncClient, token: str, web_url: str
) -> Optional[str]:
    """
    Converts a SharePoint webUrl into a direct download URL via Graph API.
    Uses the /shares endpoint which accepts encoded SharePoint URLs.
    """
    encoded = base64.urlsafe_b64encode(web_url.encode()).decode().rstrip("=")
    share_id = f"u!{encoded}"
    url = f"https://graph.microsoft.com/v1.0/shares/{share_id}/driveItem"
    resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
    if resp.status_code == 200:
        data = resp.json()
        return data.get("@microsoft.graph.downloadUrl") or data.get("downloadUrl")
    return None


_instance: Optional[CfeService] = None


def get_cfe_service() -> CfeService:
    global _instance
    if _instance is None:
        _instance = CfeService(db=get_cfe_db_service())
    return _instance


async def procesar_descargas_cfe_periodically():
    """
    Tarea de worker.py: procesa la cola de descargas CFE.
    Patron identico a sat_jobs_worker_periodically. Un trabajo por ciclo + reaper.
    """
    logger.info("[CFE] Worker de descargas iniciado")
    svc = get_cfe_service()
    while True:
        try:
            pool = await get_db_pool()
            await svc.reaper_colgados(pool)
            await svc.procesar_pendientes(pool)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("[CFE] Error en ciclo de descargas")
        await asyncio.sleep(30)
