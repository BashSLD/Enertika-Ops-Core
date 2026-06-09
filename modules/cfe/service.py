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

from .constants import CFE_CONFIG_KEYS, SHAREPOINT_CFE_ROOT, SHAREPOINT_CFE_STAGING_ROOT
from .db_service import CfeDBService, get_cfe_db_service
from .scraper import CfeScraperConfig, descargar_pdf_periodo, descargar_periodos_publicos, descargar_recibo

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

    def _build_scraper_config(self, servicio: dict, cfg_global: dict) -> CfeScraperConfig:
        return CfeScraperConfig(
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

    # ── Servicios ─────────────────────────────────────────────────────────

    async def listar_servicios(self, conn: asyncpg.Connection) -> list[dict]:
        return await self.db.get_all_servicios(conn)

    async def limpiar_errores_invalidos(
        self, conn: asyncpg.Connection, servicio_id: Optional[UUID] = None
    ) -> int:
        borrados = await self.db.limpiar_errores_invalidos(conn, servicio_id)
        if borrados:
            logger.info("[CFE] Errores invalidos limpiados: %s", borrados)
        return borrados

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

    async def iniciar_busqueda_periodos(
        self,
        conn: asyncpg.Connection,
        servicio_id: UUID,
        max_periodos: int,
        usuario_id: UUID,
    ) -> tuple[str, dict, dict]:
        if max_periodos < 1 or max_periodos > 60:
            raise ValueError("El numero de periodos debe estar entre 1 y 60.")

        if await self.db.tiene_descarga_en_progreso(conn, servicio_id):
            raise ValueError("Ya hay una descarga en curso para este servicio.")
        if await self.db.tiene_busqueda_en_progreso(conn, servicio_id):
            raise ValueError("Ya hay una busqueda de periodos en curso para este servicio.")

        servicio = await self.db.get_servicio_by_id(conn, servicio_id)
        if not servicio:
            raise ValueError("Servicio no encontrado.")

        busqueda = await self.db.crear_busqueda_periodos(
            conn,
            servicio_id=servicio_id,
            max_periodos=max_periodos,
            solicitado_por=usuario_id,
        )
        return "Busqueda encolada. La pagina se actualizara automaticamente.", servicio, busqueda

    async def get_busqueda_periodos(
        self,
        conn: asyncpg.Connection,
        servicio_id: UUID,
        busqueda_id: UUID,
    ) -> tuple[dict, list[dict]]:
        busqueda = await self.db.get_busqueda_by_id(conn, busqueda_id, servicio_id)
        if not busqueda:
            raise ValueError("Busqueda no encontrada.")
        items = await self.db.get_busqueda_items(conn, busqueda_id)
        return busqueda, items

    async def confirmar_busqueda_periodos(
        self,
        conn: asyncpg.Connection,
        servicio_id: UUID,
        busqueda_id: UUID,
        periodos: list[str],
        usuario_id: UUID,
    ) -> None:
        busqueda, items = await self.get_busqueda_periodos(conn, servicio_id, busqueda_id)
        if busqueda["estatus"] != "completado":
            raise ValueError("La busqueda todavia no esta lista para confirmar.")

        seleccionados = set(periodos)
        invalidos = seleccionados - {item["periodo"] for item in items}
        if invalidos:
            raise ValueError("Se recibieron periodos que no pertenecen a la busqueda.")

        ms_auth = get_ms_auth()
        token = await ms_auth.get_application_token()
        if not token:
            raise ValueError("No se pudo obtener token de Microsoft para conservar los archivos.")
        sp = SharePointService(access_token=token)

        descargas_finales = await self.db.get_descargas_resumen_por_servicio(conn, servicio_id)
        for item in items:
            periodo = item["periodo"]
            es_seleccionado = periodo in seleccionados
            ya_final_xml = descargas_finales.get(periodo, {}).get("xml", {}).get("estatus") == "completado"
            ya_final_pdf = descargas_finales.get(periodo, {}).get("pdf", {}).get("estatus") == "completado"
            puede_conservar = (
                es_seleccionado
                and not (ya_final_xml and ya_final_pdf)
                and (item.get("xml_drive_item_id") or item.get("pdf_drive_item_id"))
            )

            if puede_conservar:
                try:
                    await self._conservar_busqueda_item(
                        conn, sp, item, busqueda, usuario_id, ya_final_xml, ya_final_pdf
                    )
                except (ValueError, RuntimeError, httpx.HTTPError, OSError) as exc:
                    raise ValueError(f"No se pudo conservar el periodo {periodo}: {exc}") from exc
                await self.db.marcar_item_decision(conn, item["id"], "conservado")
            else:
                decision = "no_aplica" if ya_final_xml and ya_final_pdf else "descartado"
                await self.db.marcar_item_decision(conn, item["id"], decision)

            await self._borrar_staging_item(conn, sp, item)

        await self.db.marcar_busqueda_confirmada(conn, busqueda_id)

    async def iniciar_descarga_pdf(
        self,
        conn: asyncpg.Connection,
        servicio_id: UUID,
        periodo: str,
        usuario_id: UUID,
    ) -> tuple[str, dict]:
        """Encola solo el PDF de un periodo cuyo XML ya existe."""
        if await self.db.tiene_descarga_en_progreso(conn, servicio_id):
            raise ValueError("Ya hay una descarga en curso para este servicio.")

        servicio = await self.db.get_servicio_by_id(conn, servicio_id)
        if not servicio:
            raise ValueError("Servicio no encontrado.")

        xml_row = await self.db.get_descarga_por_tipo(conn, servicio_id, periodo, "xml")
        if not xml_row or xml_row["estatus"] != "completado":
            raise ValueError("No se puede reintentar el PDF porque el XML del periodo no está completo.")

        pdf_row = await self.db.get_descarga_por_tipo(conn, servicio_id, periodo, "pdf")
        if pdf_row and pdf_row["estatus"] == "completado":
            raise ValueError("El PDF de este periodo ya está descargado.")

        await self.db.upsert_descarga(
            conn, servicio_id=servicio_id, periodo=periodo, tipo="pdf",
            estatus="pendiente", error_mensaje=None, descargado_por=usuario_id,
        )
        return "Descarga de PDF encolada. La página se actualizará automáticamente.", servicio

    async def procesar_pendientes(self, pool: asyncpg.Pool) -> None:
        """
        Llamado por el worker en cada ciclo. Reclama UN trabajo (atomico) y lo ejecuta
        con timeout. Procesa de a uno por ciclo para acotar memoria/CPU.
        """
        async with pool.acquire() as conn:
            busqueda = await self.db.reclamar_busqueda_periodos(conn)
        if busqueda:
            logger.info(
                "[CFE] Busqueda reclamada busqueda_id=%s servicio_id=%s max_periodos=%s",
                busqueda["id"],
                busqueda["servicio_id"],
                busqueda["max_periodos"],
            )
            async with _scrape_lock:
                try:
                    await asyncio.wait_for(
                        self._ejecutar_busqueda_periodos(pool, busqueda),
                        timeout=max(300, int(busqueda["max_periodos"]) * 90),
                    )
                except asyncio.TimeoutError:
                    async with pool.acquire() as conn:
                        await self.db.marcar_busqueda_error(
                            conn, busqueda["id"], "La busqueda excedio el tiempo limite."
                        )
            return

        async with pool.acquire() as conn:
            job = await self.db.reclamar_trabajo(conn)
        if not job:
            return
        logger.info(
            "[CFE] Trabajo reclamado descarga_id=%s servicio_id=%s periodo=%s tipo=%s",
            job.get("id"),
            job["servicio_id"],
            job["periodo"],
            job["tipo"],
        )

        async with pool.acquire() as conn:
            servicio = await self.db.get_servicio_by_id(conn, job["servicio_id"])
            cfg_global = await self._get_cfe_config(conn)
        if not servicio:
            logger.warning("[CFE] Servicio no encontrado para job servicio_id=%s", job["servicio_id"])
            async with pool.acquire() as conn:
                await self.db.marcar_descarga_error(conn, job["id"], "Servicio no encontrado.")
            return

        async with _scrape_lock:
            try:
                await asyncio.wait_for(
                    self._ejecutar_job(pool, servicio, cfg_global, job),
                    timeout=180,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "[CFE] Timeout procesando servicio=%s (%s)",
                    servicio["numero_servicio"],
                    servicio["nombre"],
                )
                async with pool.acquire() as conn:
                    await self.db.marcar_descarga_error(
                        conn, job["id"], "La descarga excedio el tiempo limite (3 min)."
                    )

    async def reaper_colgados(self, pool: asyncpg.Pool) -> None:
        """Marca error trabajos atascados en 'descargando' (worker reiniciado a mitad)."""
        async with pool.acquire() as conn:
            await self.db.reaper_descargando(conn, minutos=15)
        await self.limpiar_busquedas_expiradas(pool)

    async def limpiar_busquedas_expiradas(self, pool: asyncpg.Pool) -> None:
        async with pool.acquire() as conn:
            expiradas = await self.db.reclamar_busquedas_expiradas(conn)
        if not expiradas:
            return

        async with pool.acquire() as conn:
            ms_auth = get_ms_auth()
            token = await ms_auth.get_application_token()
            if not token:
                logger.warning("[CFE] No se pudo obtener token para limpiar staging expirado")
                return
            sp = SharePointService(access_token=token)
            for busqueda in expiradas:
                items = await self.db.get_busqueda_items(conn, busqueda["id"])
                for item in items:
                    await self._borrar_staging_item(conn, sp, item)

    async def _ejecutar_busqueda_periodos(self, pool: asyncpg.Pool, busqueda: dict) -> None:
        async with pool.acquire() as conn:
            servicio = await self.db.get_servicio_by_id(conn, busqueda["servicio_id"])
            cfg_global = await self._get_cfe_config(conn)
        if not servicio:
            async with pool.acquire() as conn:
                await self.db.marcar_busqueda_error(conn, busqueda["id"], "Servicio no encontrado.")
            return

        cfg = self._build_scraper_config(servicio, cfg_global)
        try:
            resultados = await descargar_periodos_publicos(cfg, busqueda["max_periodos"])
        except ValueError as exc:
            async with pool.acquire() as conn:
                await self.db.marcar_busqueda_error(conn, busqueda["id"], str(exc))
            return

        if not resultados:
            async with pool.acquire() as conn:
                await self.db.marcar_busqueda_error(
                    conn, busqueda["id"], "No se detectaron periodos en el portal publico CFE."
                )
            return

        async with pool.acquire() as conn:
            descargas_finales = await self.db.get_descargas_resumen_por_servicio(conn, servicio["id"])
            total_descargados = 0
            for result in resultados:
                final_xml = descargas_finales.get(result.periodo, {}).get("xml", {})
                final_pdf = descargas_finales.get(result.periodo, {}).get("pdf", {})
                ya_xml = final_xml.get("estatus") == "completado"
                ya_pdf = final_pdf.get("estatus") == "completado"

                xml_upload = None
                pdf_upload = None
                if result.xml_content and not ya_xml:
                    xml_upload = await self._upload_bytes_to_sharepoint(
                        conn,
                        content=result.xml_content,
                        filename=result.xml_filename or f"{servicio['numero_servicio']}-{result.periodo}.xml",
                        folder_path=f"{SHAREPOINT_CFE_STAGING_ROOT}/{busqueda['id']}/{servicio['numero_servicio']}/{result.periodo}",
                        tipo="xml",
                    )
                if result.pdf_content and not ya_pdf:
                    pdf_upload = await self._upload_bytes_to_sharepoint(
                        conn,
                        content=result.pdf_content,
                        filename=result.pdf_filename or f"{servicio['numero_servicio']}-{result.periodo}.pdf",
                        folder_path=f"{SHAREPOINT_CFE_STAGING_ROOT}/{busqueda['id']}/{servicio['numero_servicio']}/{result.periodo}",
                        tipo="pdf",
                    )

                xml_estatus = self._estatus_staging_item(
                    ya_descargado=ya_xml,
                    upload=xml_upload,
                    contenido=bool(result.xml_content),
                    error=result.xml_error,
                )
                pdf_estatus = self._estatus_staging_item(
                    ya_descargado=ya_pdf,
                    upload=pdf_upload,
                    contenido=bool(result.pdf_content),
                    error=result.pdf_error,
                )
                if xml_estatus in ("descargado", "ya_descargado") and pdf_estatus in ("descargado", "ya_descargado"):
                    total_descargados += 1

                errores = [msg for msg in (result.xml_error, result.pdf_error) if msg]
                decision = "no_aplica" if ya_xml and ya_pdf else "pendiente"
                await self.db.upsert_busqueda_item(
                    conn,
                    busqueda_id=busqueda["id"],
                    periodo=result.periodo,
                    etiqueta_periodo=result.etiqueta,
                    xml_estatus=xml_estatus,
                    pdf_estatus=pdf_estatus,
                    xml_nombre_archivo=result.xml_filename or final_xml.get("nombre_archivo"),
                    pdf_nombre_archivo=result.pdf_filename or final_pdf.get("nombre_archivo"),
                    xml_staging_url=xml_upload.get("webUrl") if xml_upload else None,
                    pdf_staging_url=pdf_upload.get("webUrl") if pdf_upload else None,
                    xml_drive_item_id=xml_upload.get("id") if xml_upload else None,
                    pdf_drive_item_id=pdf_upload.get("id") if pdf_upload else None,
                    ya_descargado_xml=ya_xml,
                    ya_descargado_pdf=ya_pdf,
                    error_mensaje=" | ".join(errores) if errores else None,
                    decision=decision,
                )

            await self.db.finalizar_busqueda_periodos(
                conn,
                busqueda["id"],
                total_detectados=len(resultados),
                total_descargados=total_descargados,
            )

    @staticmethod
    def _estatus_staging_item(
        *,
        ya_descargado: bool,
        upload: Optional[dict],
        contenido: bool,
        error: Optional[str],
    ) -> str:
        if ya_descargado:
            return "ya_descargado"
        if upload:
            return "descargado"
        if error:
            return "error"
        if contenido:
            return "error"
        return "no_disponible"

    async def _ejecutar_job(
        self,
        pool: asyncpg.Pool,
        servicio: dict,
        cfg_global: dict,
        job: dict,
    ) -> None:
        if job["tipo"] == "pdf" and job["periodo"] != "pendiente":
            await self._ejecutar_descarga_pdf(
                pool=pool, servicio=servicio, cfg_global=cfg_global,
                periodo=job["periodo"], usuario_id=job["descargado_por"],
            )
            return

        await self._ejecutar_descarga(
            pool=pool, servicio=servicio,
            cfg_global=cfg_global, usuario_id=job["descargado_por"],
        )

    async def _ejecutar_descarga(
        self,
        pool: asyncpg.Pool,
        servicio: dict,
        cfg_global: dict,
        usuario_id: UUID,
    ) -> None:
        """Background task: scrape → SharePoint upload → DB record."""
        logger.info(
            "[CFE] Iniciando descarga servicio=%s nombre=%s",
            servicio["numero_servicio"],
            servicio["nombre"],
        )
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
        logger.info(
            "[CFE] Scraper finalizado servicio=%s periodo=%s xml=%s pdf=%s error=%s pdf_error=%s",
            servicio["numero_servicio"],
            result.periodo or "N/D",
            bool(result.xml_content),
            bool(result.pdf_content),
            bool(result.error),
            bool(result.pdf_error),
        )

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
                logger.warning(
                    "[CFE] Error descargando servicio=%s periodo=%s mensaje=%s",
                    servicio["numero_servicio"],
                    result.periodo or "desconocido",
                    result.error,
                )
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
            logger.info(
                "[CFE] XML procesado servicio=%s periodo=%s archivo=%s sharepoint=%s",
                servicio["numero_servicio"],
                result.periodo,
                result.xml_filename,
                bool(xml_sp_url),
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
                logger.info(
                    "[CFE] PDF procesado servicio=%s periodo=%s archivo=%s sharepoint=%s",
                    servicio["numero_servicio"],
                    result.periodo,
                    result.pdf_filename,
                    bool(pdf_sp_url),
                )
                await self._registrar_descarga_sp(
                    conn, servicio_id=servicio["id"], periodo=result.periodo, tipo="pdf",
                    nombre_archivo=result.pdf_filename, sp_url=pdf_sp_url, usuario_id=usuario_id,
                )
            elif result.pdf_error:
                logger.warning(
                    "[CFE] XML completado pero PDF fallo servicio=%s periodo=%s mensaje=%s",
                    servicio["numero_servicio"],
                    result.periodo,
                    result.pdf_error,
                )
                await self.db.upsert_descarga(
                    conn, servicio_id=servicio["id"], periodo=result.periodo,
                    tipo="pdf", estatus="error", error_mensaje=result.pdf_error,
                    descargado_por=usuario_id,
                )

            await self.db.borrar_descarga_pendiente(conn, servicio["id"])

            # Persist updated session
            if result.session_json_nuevo:
                await self._save_session(conn, result.session_json_nuevo)
                logger.info("[CFE] Sesion MiEspacio renovada servicio=%s", servicio["numero_servicio"])

    async def _ejecutar_descarga_pdf(
        self,
        pool: asyncpg.Pool,
        servicio: dict,
        cfg_global: dict,
        periodo: str,
        usuario_id: UUID,
    ) -> None:
        """Background task: descarga solo PDF desde MiEspacio y actualiza la fila PDF."""
        logger.info(
            "[CFE] Iniciando descarga PDF servicio=%s periodo=%s",
            servicio["numero_servicio"],
            periodo,
        )
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

        result = await descargar_pdf_periodo(cfg, periodo)
        logger.info(
            "[CFE] Scraper PDF finalizado servicio=%s periodo=%s pdf=%s error=%s",
            servicio["numero_servicio"],
            periodo,
            bool(result.pdf_content),
            bool(result.error or result.pdf_error),
        )

        async with pool.acquire() as conn:
            error_mensaje = result.error or result.pdf_error
            if error_mensaje:
                await self.db.upsert_descarga(
                    conn, servicio_id=servicio["id"], periodo=periodo,
                    tipo="pdf", estatus="error", error_mensaje=error_mensaje,
                    descargado_por=usuario_id,
                )
            elif result.pdf_content:
                pdf_sp_url = await self._upload_to_sharepoint(
                    conn, content=result.pdf_content, filename=result.pdf_filename,
                    servicio_numero=servicio["numero_servicio"], periodo=periodo, tipo="pdf",
                )
                logger.info(
                    "[CFE] PDF procesado servicio=%s periodo=%s archivo=%s sharepoint=%s",
                    servicio["numero_servicio"],
                    periodo,
                    result.pdf_filename,
                    bool(pdf_sp_url),
                )
                await self._registrar_descarga_sp(
                    conn, servicio_id=servicio["id"], periodo=periodo, tipo="pdf",
                    nombre_archivo=result.pdf_filename, sp_url=pdf_sp_url, usuario_id=usuario_id,
                )
            else:
                await self.db.upsert_descarga(
                    conn, servicio_id=servicio["id"], periodo=periodo,
                    tipo="pdf", estatus="error",
                    error_mensaje="No se descargó el PDF de MiEspacio.",
                    descargado_por=usuario_id,
                )

            if result.session_json_nuevo:
                await self._save_session(conn, result.session_json_nuevo)
                logger.info("[CFE] Sesion MiEspacio renovada servicio=%s", servicio["numero_servicio"])

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

    async def _conservar_busqueda_item(
        self,
        conn: asyncpg.Connection,
        sp: SharePointService,
        item: dict,
        busqueda: dict,
        usuario_id: UUID,
        ya_final_xml: bool,
        ya_final_pdf: bool,
    ) -> None:
        periodo = item["periodo"]
        folder = f"{SHAREPOINT_CFE_ROOT}/{busqueda['numero_servicio']}/{periodo}"

        if item.get("xml_drive_item_id") and not ya_final_xml:
            xml_content = await sp.download_file_by_item_id(conn, item["xml_drive_item_id"])
            xml_upload = await self._upload_bytes_to_sharepoint(
                conn,
                content=xml_content,
                filename=item.get("xml_nombre_archivo") or f"{busqueda['numero_servicio']}-{periodo}.xml",
                folder_path=folder,
                tipo="xml",
            )
            await self._registrar_descarga_sp(
                conn,
                servicio_id=busqueda["servicio_id"],
                periodo=periodo,
                tipo="xml",
                nombre_archivo=item.get("xml_nombre_archivo") or f"{busqueda['numero_servicio']}-{periodo}.xml",
                sp_url=xml_upload.get("webUrl") if xml_upload else None,
                usuario_id=usuario_id,
            )

        if item.get("pdf_drive_item_id") and not ya_final_pdf:
            pdf_content = await sp.download_file_by_item_id(conn, item["pdf_drive_item_id"])
            pdf_upload = await self._upload_bytes_to_sharepoint(
                conn,
                content=pdf_content,
                filename=item.get("pdf_nombre_archivo") or f"{busqueda['numero_servicio']}-{periodo}.pdf",
                folder_path=folder,
                tipo="pdf",
            )
            await self._registrar_descarga_sp(
                conn,
                servicio_id=busqueda["servicio_id"],
                periodo=periodo,
                tipo="pdf",
                nombre_archivo=item.get("pdf_nombre_archivo") or f"{busqueda['numero_servicio']}-{periodo}.pdf",
                sp_url=pdf_upload.get("webUrl") if pdf_upload else None,
                usuario_id=usuario_id,
            )

    async def _borrar_staging_item(
        self,
        conn: asyncpg.Connection,
        sp: SharePointService,
        item: dict,
    ) -> None:
        for field in ("xml_drive_item_id", "pdf_drive_item_id"):
            drive_item_id = item.get(field)
            if not drive_item_id:
                continue
            try:
                await sp.delete_file_by_item_id(conn, drive_item_id)
            except (ValueError, RuntimeError, httpx.HTTPError) as exc:
                logger.warning(
                    "[CFE] No se pudo borrar staging item_id=%s periodo=%s error=%s",
                    drive_item_id,
                    item.get("periodo"),
                    exc,
                )

    async def _upload_bytes_to_sharepoint(
        self,
        conn: asyncpg.Connection,
        *,
        content: bytes,
        filename: str,
        folder_path: str,
        tipo: str,
    ) -> Optional[dict]:
        try:
            ms_auth = get_ms_auth()
            token = await ms_auth.get_application_token()
            if not token:
                raise RuntimeError("No se pudo obtener token de Microsoft")

            sp = SharePointService(access_token=token)
            sp_cfg = await sp._resolve_config(conn)
            if not sp_cfg.get("site_id") and not sp_cfg.get("drive_id"):
                raise RuntimeError(
                    "SharePoint no configurado (SHAREPOINT_SITE_ID/DRIVE_ID). "
                    "Configuralos en Admin antes de descargar recibos CFE."
                )

            upload = UploadFile(filename=filename, file=BytesIO(content))
            return await sp.upload_file(conn=conn, file=upload, folder_path=folder_path)
        except (ValueError, RuntimeError, httpx.HTTPError, OSError) as exc:
            logger.error("Error subiendo %s a SharePoint carpeta=%s archivo=%s: %s", tipo, folder_path, filename, exc)
            return None

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
        except (ValueError, RuntimeError, httpx.HTTPError, OSError) as exc:
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
