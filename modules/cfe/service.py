# modules/cfe/service.py
from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import secrets
import struct
import time
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from collections.abc import Sequence
from typing import Any, Optional
from uuid import UUID

import asyncpg
import httpx
from fastapi import UploadFile
import pypdf
from pypdf import PdfWriter

from core.database import get_db_pool
from core.config_service import ConfigService
from core.timezone import now_mx
from core.integrations.sharepoint import SharePointService
from core.microsoft import get_ms_auth
from modules.admin.db_service import AdminDBService
from modules.shared.services.cfe.extractor import extraer_datos_xml, rpu_del_xml
from modules.shared.services.cfe.excel import generar_excel_cfe
from modules.shared.services.cfe.schemas import CfeReceipt, CfeXmlInput

from core.permissions import get_user_module_role
from modules.oym.db_service import get_oym_db_service
from .analysis import analisis_sin_datos, construir_analisis_recibos, filtrar_xmls_completados
from .constants import (
    CFE_BUSQUEDA_TIMEOUT_MIN_SEGUNDOS,
    CFE_BUSQUEDA_TIMEOUT_SEGUNDOS_POR_PERIODO,
    CFE_CONFIG_KEYS,
    SHAREPOINT_CFE_ROOT,
    SHAREPOINT_CFE_STAGING_ROOT,
)
from .db_service import CfeDBService, get_cfe_db_service
from .scraper import (
    CfeScraperConfig,
    descargar_pdf_periodo,
    descargar_periodos_busqueda,
    descargar_recibo,
    descargar_ultimo_recibo_miespacio,
    registrar_servicio_miespacio,
)

logger = logging.getLogger("CfeService")

_scrape_lock = asyncio.Semaphore(1)
CFE_ZIP_MAX_DOWNLOAD_ATTEMPTS = 3

_MESES_ZIP_SIMULACION = {
    1: "ENE",
    2: "FEB",
    3: "MAR",
    4: "ABR",
    5: "MAY",
    6: "JUN",
    7: "JUL",
    8: "AGO",
    9: "SEP",
    10: "OCT",
    11: "NOV",
    12: "DIC",
}


class CfeZipFaltantesError(ValueError):
    def __init__(self, faltantes: Sequence[dict]):
        super().__init__(
            "No se pudieron descargar todos los archivos del ZIP. "
            "Puedes descargarlos manualmente desde Historial o continuar con faltantes."
        )
        self.faltantes = [dict(item) for item in faltantes]


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

    # ── Renovacion self-service de sesion (lanzador local) ─────────────────

    async def get_estado_sesion(self, conn: asyncpg.Connection) -> dict:
        """Estado de la sesion MiEspacio para mostrarlo a los usuarios en la UI CFE."""
        cfg = await ConfigService.get_global_configs_bulk(conn, {
            CFE_CONFIG_KEYS["session_json"]:     ("", str),
            CFE_CONFIG_KEYS["upload_token"]:     ("", str),
            CFE_CONFIG_KEYS["session_invalida"]: ("", str),
            CFE_CONFIG_KEYS["lanzador_item_id"]: ("", str),
            CFE_CONFIG_KEYS["lanzador_version"]: ("", str),
        })
        sesion          = cfg[CFE_CONFIG_KEYS["session_json"]]
        token           = cfg[CFE_CONFIG_KEYS["upload_token"]]
        session_invalida = cfg[CFE_CONFIG_KEYS["session_invalida"]]

        sesion_estado = "sin_sesion"
        expira_en: Optional[datetime] = None

        if sesion:
            if session_invalida == "1":
                sesion_estado = "expirada"
            else:
                try:
                    data = json.loads(sesion)
                    cfe_cookies = [
                        c for c in data.get("cookies", [])
                        if "cfe.mx" in (c.get("domain") or "")
                    ]
                    if not cfe_cookies:
                        sesion_estado = "invalida"
                    else:
                        now_ts = time.time()
                        expiring = [c for c in cfe_cookies if (c.get("expires") or -1) > now_ts]
                        if not expiring:
                            has_expiry = any((c.get("expires") or -1) > 0 for c in cfe_cookies)
                            sesion_estado = "expirada" if has_expiry else "activa"
                        else:
                            nearest = min(c["expires"] for c in expiring)
                            expira_en = datetime.fromtimestamp(nearest, tz=timezone.utc)
                            sesion_estado = "expira_pronto" if (nearest - now_ts < 86400) else "activa"
                except (json.JSONDecodeError, TypeError, KeyError, OSError, OverflowError):
                    sesion_estado = "invalida"

        return {
            "sesion_activa": sesion_estado in ("activa", "expira_pronto"),
            "sesion_estado": sesion_estado,
            "expira_en": expira_en,
            "renovacion_habilitada": bool(token),
            "lanzador_disponible": bool(cfg[CFE_CONFIG_KEYS["lanzador_item_id"]]),
            "lanzador_version": cfg[CFE_CONFIG_KEYS["lanzador_version"]],
        }

    async def get_lanzador_bytes(self, conn: asyncpg.Connection) -> tuple[bytes, str]:
        """Descarga el ejecutable del lanzador desde SharePoint. Retorna (bytes, version)."""
        cfg = await ConfigService.get_global_configs_bulk(conn, {
            CFE_CONFIG_KEYS["lanzador_item_id"]: ("", str),
            CFE_CONFIG_KEYS["lanzador_version"]: ("", str),
        })
        item_id = cfg[CFE_CONFIG_KEYS["lanzador_item_id"]]
        if not item_id:
            raise ValueError("El ejecutable del lanzador no está disponible todavía.")
        version = cfg[CFE_CONFIG_KEYS["lanzador_version"]]
        app_token = await get_ms_auth().get_application_token()
        sp = SharePointService(access_token=app_token)
        content = await sp.download_file_by_item_id(conn, item_id)
        return content, version

    async def subir_sesion_con_token(
        self, conn: asyncpg.Connection, *, token: str, session_json: str
    ) -> None:
        """
        Guarda el storage_state de MiEspacio enviado por el lanzador local.
        Se autentica con un token compartido (no con sesion Azure AD) porque el
        script corre en la PC del usuario sin cookie de sesion del app.
        """
        configurado = await ConfigService.get_global_config(
            conn, CFE_CONFIG_KEYS["upload_token"], "", str
        )
        if not configurado:
            raise PermissionError(
                "La renovacion de sesion CFE no esta habilitada. "
                "Un administrador debe generar el token en Admin > Configuracion Global > Recibos CFE."
            )
        # compare_digest en bytes: con str lanza TypeError si el token entrante
        # trae caracteres no-ASCII (los headers llegan en latin-1).
        if not token or not secrets.compare_digest(token.encode("utf-8"), configurado.encode("utf-8")):
            raise PermissionError("Token de subida de sesion CFE invalido.")

        self._validar_storage_state(session_json)
        async with conn.transaction():
            await self._save_session(conn, session_json.strip())
            await self._admin_db.upsert_global_config(conn, CFE_CONFIG_KEYS["session_invalida"], "")
        ConfigService.invalidar_cache()
        logger.info("[CFE] Sesion MiEspacio renovada via lanzador local")

    @staticmethod
    def _validar_storage_state(session_json: str) -> None:
        raw = (session_json or "").strip()
        if not raw:
            raise ValueError("El contenido de la sesion esta vacio.")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("El contenido de la sesion no es un JSON valido.") from exc
        if not isinstance(data, dict) or "cookies" not in data or not isinstance(data["cookies"], list):
            raise ValueError("El JSON no parece un storage_state de Playwright (falta 'cookies').")
        if not data["cookies"]:
            raise ValueError("La sesion no contiene cookies; el login no se completo correctamente.")

    @staticmethod
    def _extraer_tipo_recibo(xml_content: Optional[bytes], filename: str) -> Optional[str]:
        if not xml_content:
            return None
        try:
            recibo = extraer_datos_xml(xml_content, filename or "recibo_cfe.xml")
        except ValueError as exc:
            logger.warning("No se pudo extraer tipo de recibo CFE archivo=%s error=%s", filename, exc)
            return None
        tipo_recibo = recibo.get("servicio", {}).get("tarifa")
        return str(tipo_recibo).strip() or None

    @staticmethod
    def _rpu_no_coincide(xml_content: Optional[bytes], filename: str, numero_servicio: str) -> Optional[str]:
        """Si el XML trae un RPU presente y distinto al numero_servicio, devuelve un
        mensaje de error (el XML es de otro cliente). None si coincide, esta ausente
        o no se puede parsear (permisivo ante campo faltante: no bloquea de mas).

        Guardia de defensa en profundidad: el bug que mezclo recibos de servicios
        distintos se previene de raiz al separar el alta de la descarga, pero esta
        validacion impide persistir un XML ajeno aunque algo vuelva a fallar."""
        if not xml_content:
            return None
        try:
            rpu = rpu_del_xml(xml_content, filename or "recibo_cfe.xml")
        except ValueError:
            return None
        esperado = re.sub(r"\D", "", numero_servicio or "")
        if rpu and esperado and rpu != esperado:
            return f"El XML pertenece a otro servicio (RPU {rpu} != {esperado}); se descarto."
        return None

    @staticmethod
    def _es_error_sesion(mensaje: Optional[str]) -> bool:
        """True si el mensaje indica que la sesion MiEspacio expiro (no errores transitorios del portal)."""
        if not mensaje:
            return False
        m = mensaje.lower()
        return "expir" in m and "sesi" in m

    async def _marcar_sesion_invalida(self, conn: asyncpg.Connection) -> None:
        await self._admin_db.upsert_global_config(conn, CFE_CONFIG_KEYS["session_invalida"], "1")
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

    async def resolver_filtro_visibilidad(
        self, conn: asyncpg.Connection, user: dict, modulo_activo: str | None
    ) -> tuple[list[UUID] | None, list[UUID] | None]:
        """
        Devuelve (creado_por_ids, servicio_ids) para filtrar el listado.
        Solo una dimension se activa segun el modulo; la otra es None.

        - oym: filtra por zona del usuario (creado_por_ids). admin de oym /
          ADMIN sistema / sin zona -> (None, None) = ve todo.
        - simulacion: filtra por servicios que el usuario registro (servicio_ids).
          admin de simulacion / ADMIN sistema -> (None, None). Un usuario sin
          registros -> ([] en servicio_ids) = no ve nada. NUNCA colapsar [] a None.
        - sin modulo activo (tiene ambos) -> (None, None) = ve todo.
        """
        if modulo_activo == "oym":
            if get_user_module_role("oym", user) == "admin":
                return None, None
            usuario_id = user.get("user_db_id")
            if not usuario_id:
                return None, None
            oym_db = get_oym_db_service()
            ids = await oym_db.get_usuario_ids_en_misma_zona(conn, usuario_id)
            return (ids or None), None

        if modulo_activo == "simulacion":
            if get_user_module_role("simulacion", user) == "admin":
                return None, None
            usuario_id = user.get("user_db_id")
            if not usuario_id:
                return None, None
            visibles = await self.db.get_servicio_ids_visibles(conn, usuario_id, "simulacion")
            return None, visibles  # lista (posiblemente vacia) = filtro estricto

        return None, None

    async def listar_servicios(
        self, conn: asyncpg.Connection,
        modulos: list[str] | None = None,
        creado_por_ids: list[UUID] | None = None,
        servicio_ids: list[UUID] | None = None,
    ) -> list[dict]:
        return await self.db.get_all_servicios(
            conn, modulos=modulos, creado_por_ids=creado_por_ids, servicio_ids=servicio_ids
        )

    async def limpiar_errores_invalidos(
        self, conn: asyncpg.Connection, servicio_id: Optional[UUID] = None
    ) -> int:
        borrados = await self.db.limpiar_errores_invalidos(conn, servicio_id)
        if borrados:
            logger.info("[CFE] Errores invalidos limpiados: %s", borrados)
        return borrados

    @staticmethod
    def _normalizar_nombre_servicio(nombre: str) -> str:
        # CFE exige el nombre del servicio SIEMPRE en mayusculas (portal publico + MiEspacio).
        return (nombre or "").strip().upper()

    async def crear_servicio(
        self, conn: asyncpg.Connection, *, numero_servicio: str, nombre: str,
        alias: Optional[str], lada: str, telefono: str, email: str, usuario_id: UUID,
        modulo: str = "oym",
    ) -> tuple[dict, str]:
        """Returns (servicio, estado). estado en:
        'creado'              -> servicio nuevo
        'modulo_agregado'     -> el modulo se sumo a un servicio existente
        'visibilidad_otorgada'-> simulacion: ya existia en el modulo, se otorgo visibilidad
        'ya_visible'          -> simulacion: ya existia y el usuario ya era registrador
        Para oym, un servicio ya existente en el modulo sigue lanzando ValueError."""
        nombre = self._normalizar_nombre_servicio(nombre)

        existing = await self.db.get_servicio_by_numero(conn, numero_servicio)
        if existing:
            if modulo in (existing.get("modulos") or []):
                if modulo == "simulacion":
                    otorgado = await self.db.agregar_registrador(
                        conn, existing["id"], usuario_id, "simulacion"
                    )
                    return existing, ("visibilidad_otorgada" if otorgado else "ya_visible")
                raise ValueError(
                    f"El número de servicio {numero_servicio} ya está registrado "
                    f"como '{existing['nombre']}'."
                )
            # El servicio existe en otro módulo: agregar este módulo al array
            await self.db.agregar_modulo_a_servicio(conn, existing["id"], modulo)
            if modulo == "simulacion":
                await self.db.agregar_registrador(conn, existing["id"], usuario_id, "simulacion")
            # Verifica/registra en MiEspacio si aun no esta (idempotente).
            await self.db.marcar_alta_miespacio_pendiente(conn, existing["id"])
            return existing, "modulo_agregado"
        nuevo = await self.db.crear_servicio(
            conn, numero_servicio=numero_servicio, nombre=nombre, alias=alias,
            lada=lada, telefono=telefono, email=email, creado_por=usuario_id,
            modulos=[modulo],
        )
        if modulo == "simulacion":
            await self.db.agregar_registrador(conn, nuevo["id"], usuario_id, "simulacion")
        # Encola el alta en MiEspacio (job del worker, independiente de la descarga).
        await self.db.marcar_alta_miespacio_pendiente(conn, nuevo["id"])
        return nuevo, "creado"

    async def editar_servicio(
        self, conn: asyncpg.Connection, servicio_id: UUID, *,
        numero_servicio: str, nombre: str, alias: Optional[str],
    ) -> tuple[str, dict]:
        """Edita RPU/nombre/alias de un servicio con error de registro y reencola
        el alta en MiEspacio. Solo permitido mientras miespacio_estatus == 'error'."""
        servicio = await self.db.get_servicio_by_id(conn, servicio_id)
        if not servicio:
            raise ValueError("Servicio no encontrado.")
        if servicio.get("miespacio_estatus") != "error":
            raise ValueError("Solo se puede editar un servicio con error de registro.")

        numero_servicio = numero_servicio.strip()
        nombre = self._normalizar_nombre_servicio(nombre)
        alias = (alias or "").strip() or None
        if not numero_servicio or not nombre:
            raise ValueError("Número y nombre son requeridos.")

        try:
            actualizado = await self.db.actualizar_servicio(
                conn, servicio_id, numero_servicio=numero_servicio, nombre=nombre, alias=alias,
            )
        except asyncpg.UniqueViolationError:
            raise ValueError(f"Ya existe un servicio con el número {numero_servicio}.")
        if not actualizado:
            raise ValueError("El servicio ya no está en estado de error; no se puede editar.")

        await self.db.marcar_alta_miespacio_pendiente(conn, servicio_id)
        actualizado["miespacio_estatus"] = "pendiente"
        actualizado["miespacio_error"] = None
        return "Servicio actualizado. Registro en MiEspacio reencolado.", actualizado

    async def reintentar_alta_miespacio(
        self, conn: asyncpg.Connection, servicio_id: UUID
    ) -> tuple[str, dict]:
        """Reencola el alta en MiEspacio de un servicio (tras un error)."""
        servicio = await self.db.get_servicio_by_id(conn, servicio_id)
        if not servicio:
            raise ValueError("Servicio no encontrado.")
        if servicio.get("miespacio_estatus") == "registrado":
            raise ValueError("El servicio ya está registrado en MiEspacio.")
        encolado = await self.db.marcar_alta_miespacio_pendiente(conn, servicio_id)
        if not encolado:
            raise ValueError("El registro en MiEspacio ya está en curso.")
        servicio["miespacio_estatus"] = "pendiente"
        servicio["miespacio_error"] = None
        return "Registro en MiEspacio encolado. La página se actualizará automáticamente.", servicio

    async def iniciar_registro_manual(
        self, conn: asyncpg.Connection, servicio_id: UUID, total: str
    ) -> tuple[str, dict]:
        """Encola el alta en MiEspacio usando un total ingresado manualmente por el usuario."""
        servicio = await self.db.get_servicio_by_id(conn, servicio_id)
        if not servicio:
            raise ValueError("Servicio no encontrado.")
        if servicio.get("miespacio_estatus") == "registrado":
            raise ValueError("El servicio ya está registrado en MiEspacio.")

        total_limpio = re.sub(r"[^\d]", "", total).lstrip("0")
        if not total_limpio:
            raise ValueError("El total debe ser mayor a cero.")

        encolado = await self.db.marcar_alta_miespacio_pendiente(conn, servicio_id)
        if not encolado:
            raise ValueError("El registro en MiEspacio ya está en curso.")

        await self.db.set_miespacio_total_manual(conn, servicio_id, total_limpio)
        servicio["miespacio_estatus"] = "pendiente"
        servicio["miespacio_error"] = None
        return "Intentando registro con el total proporcionado. La página se actualizará automáticamente.", servicio

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

    async def iniciar_descarga_masiva(
        self,
        conn: asyncpg.Connection,
        *,
        modulos: list[str] | None,
        usuario_id: UUID,
        creado_por_ids: list[UUID] | None = None,
        servicio_ids: list[UUID] | None = None,
    ) -> tuple[int, int]:
        """
        Encola la descarga del ultimo recibo de TODOS los servicios registrados en
        MiEspacio dentro de los modulos dados. Salta (sin abortar el lote) los que
        ya tienen una descarga en curso. El worker procesa la cola de a uno.
        Retorna (encolados, omitidos).
        """
        servicios = await self.db.get_all_servicios(
            conn, modulos=modulos, creado_por_ids=creado_por_ids, servicio_ids=servicio_ids
        )
        registrados = [s for s in servicios if s.get("miespacio_estatus") == "registrado"]

        encolados = 0
        omitidos = 0
        for servicio in registrados:
            # descarga_activa viene en el mismo snapshot de get_all_servicios
            # (BOOL_OR pendiente/descargando) — evita una query por servicio.
            if servicio.get("descarga_activa"):
                omitidos += 1
                continue
            await self.db.upsert_descarga(
                conn, servicio_id=servicio["id"], periodo="pendiente", tipo="xml",
                estatus="pendiente", descargado_por=usuario_id,
            )
            encolados += 1

        logger.info(
            "[CFE] Descarga masiva encolada encolados=%s omitidos=%s modulos=%s",
            encolados, omitidos, modulos,
        )
        return encolados, omitidos

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

    async def get_busqueda_activa_periodos(
        self,
        conn: asyncpg.Connection,
        servicio_id: UUID,
    ) -> tuple[Optional[dict], list[dict]]:
        busqueda = await self.db.get_busqueda_activa_por_servicio(conn, servicio_id)
        if not busqueda:
            return None, []
        items = await self.db.get_busqueda_items(conn, busqueda["id"])
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
            tiene_staging = bool(item.get("xml_drive_item_id") or item.get("pdf_drive_item_id"))
            puede_conservar = (
                es_seleccionado
                and not (ya_final_xml and ya_final_pdf)
                and tiene_staging
            )

            if puede_conservar:
                try:
                    await self._conservar_busqueda_item(
                        conn, sp, item, busqueda, usuario_id, ya_final_xml, ya_final_pdf,
                        item.get("tipo_recibo")
                        or descargas_finales.get(periodo, {}).get("xml", {}).get("tipo_recibo"),
                    )
                except (ValueError, RuntimeError, httpx.HTTPError, OSError) as exc:
                    raise ValueError(f"No se pudo conservar el periodo {periodo}: {exc}") from exc
                await self.db.marcar_item_decision(conn, item["id"], "conservado")
            else:
                decision = "descartado" if (tiene_staging and not es_seleccionado) else "no_aplica"
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
        # Alta en MiEspacio: prerequisito de la descarga. Se procesa primero y se
        # corta el ciclo para no encadenar dos scrapes (acota memoria/CPU/bloqueo IP).
        async with pool.acquire() as conn:
            servicio_alta = await self.db.reclamar_alta_miespacio(conn)
        if servicio_alta:
            logger.info(
                "[CFE] Alta MiEspacio reclamada servicio_id=%s numero=%s",
                servicio_alta["id"], servicio_alta["numero_servicio"],
            )
            async with _scrape_lock:
                try:
                    await asyncio.wait_for(
                        self._ejecutar_alta_miespacio(pool, servicio_alta), timeout=240,
                    )
                except asyncio.TimeoutError:
                    async with pool.acquire() as conn:
                        await self.db.marcar_miespacio_estatus(
                            conn, servicio_alta["id"], "error",
                            "El registro en MiEspacio excedió el tiempo límite.",
                        )
            return

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
                        timeout=max(
                            CFE_BUSQUEDA_TIMEOUT_MIN_SEGUNDOS,
                            int(busqueda["max_periodos"]) * CFE_BUSQUEDA_TIMEOUT_SEGUNDOS_POR_PERIODO,
                        ),
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
            await self.db.reaper_alta_miespacio_colgada(conn, minutos=15)
            await self.db.reaper_busqueda_colgada(conn)
        await self.limpiar_busquedas_expiradas(pool)

    async def limpiar_busquedas_expiradas(self, pool: asyncpg.Pool) -> None:
        # Fetch token first — if it fails, busquedas are NOT marked expirado yet
        # so the next reaper cycle can retry.
        ms_auth = get_ms_auth()
        token = await ms_auth.get_application_token()
        if not token:
            logger.warning("[CFE] No se pudo obtener token para limpiar staging expirado")
            return
        sp = SharePointService(access_token=token)

        async with pool.acquire() as conn:
            expiradas = await self.db.reclamar_busquedas_expiradas(conn)
        if not expiradas:
            return

        # Pre-fetch items + SP config in a single short conn block
        async with pool.acquire() as conn:
            sp_cfg = await sp._resolve_config(conn)
            all_items = {
                b["id"]: await self.db.get_busqueda_items(conn, b["id"])
                for b in expiradas
            }

        # SP deletions outside conn (slow HTTP)
        for busqueda in expiradas:
            for item in all_items[busqueda["id"]]:
                await self._borrar_staging_item(None, sp, item, _sp_cfg=sp_cfg)

    async def _ejecutar_alta_miespacio(self, pool: asyncpg.Pool, servicio: dict) -> None:
        """Registra el servicio en MiEspacio (si no existe) y actualiza su estatus.
        Idempotente: 'ya_existia' y 'registrado' marcan 'registrado'.
        Si miespacio_detalle_json contiene 'total_manual', usa ese total en lugar de scraping."""
        async with pool.acquire() as conn:
            cfg_global = await self._get_cfe_config(conn)

        total_manual = servicio.get("miespacio_total_manual")

        cfg = self._build_scraper_config(servicio, cfg_global)
        try:
            resultado = await registrar_servicio_miespacio(
                cfg, candidatos_override=[total_manual] if total_manual else None
            )
        except Exception as exc:
            logger.exception(
                "[CFE] Error inesperado en alta MiEspacio servicio=%s", servicio["numero_servicio"]
            )
            async with pool.acquire() as conn:
                await self.db.marcar_miespacio_estatus(
                    conn, servicio["id"], "error", f"Error inesperado: {exc}"
                )
            return

        logger.info(
            "[CFE] Alta MiEspacio servicio=%s estado=%s total=%s",
            servicio["numero_servicio"], resultado.estado, resultado.total_usado,
        )

        detalle_json: Optional[str] = None
        if resultado.periodos_probados or resultado.candidatos_probados:
            detalle: dict = {}
            if resultado.periodos_probados:
                detalle["periodos"] = resultado.periodos_probados
            if resultado.candidatos_probados:
                detalle["candidatos"] = resultado.candidatos_probados
            if total_manual:
                detalle["total_manual_usado"] = total_manual
            detalle_json = json.dumps(detalle, ensure_ascii=False)

        async with pool.acquire() as conn:
            if resultado.session_json_nuevo:
                await self._save_session(conn, resultado.session_json_nuevo)
            if resultado.estado in ("registrado", "ya_existia"):
                await self.db.marcar_miespacio_estatus(conn, servicio["id"], "registrado", None)
                return
            if resultado.estado == "sesion_invalida":
                await self._marcar_sesion_invalida(conn)
            await self.db.marcar_miespacio_estatus(
                conn, servicio["id"], "error",
                resultado.mensaje or "No se pudo registrar el servicio.",
                detalle_json,
            )

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
            resultado = await descargar_periodos_busqueda(cfg, busqueda["max_periodos"])
        except ValueError as exc:
            logger.warning(
                "[CFE] Busqueda fallo servicio_id=%s busqueda_id=%s error=%s",
                busqueda["servicio_id"],
                busqueda["id"],
                exc,
            )
            async with pool.acquire() as conn:
                await self.db.marcar_busqueda_error(conn, busqueda["id"], str(exc))
            return
        except Exception as exc:
            logger.exception(
                "[CFE] Error inesperado en busqueda servicio_id=%s busqueda_id=%s",
                busqueda["servicio_id"],
                busqueda["id"],
            )
            async with pool.acquire() as conn:
                await self.db.marcar_busqueda_error(conn, busqueda["id"], f"Error inesperado: {exc}")
            return

        if any(self._es_error_sesion(r.pdf_error) for r in resultado.periodos):
            async with pool.acquire() as conn:
                await self._marcar_sesion_invalida(conn)

        resultados = resultado.periodos
        if not resultados:
            async with pool.acquire() as conn:
                await self.db.marcar_busqueda_error(
                    conn, busqueda["id"], "No se detectaron periodos en el portal publico CFE."
                )
            return

        # Phase 1: fetch DB state + resolve SP config (short conn)
        async with pool.acquire() as conn:
            descargas_finales = await self.db.get_descargas_resumen_por_servicio(conn, servicio["id"])
            ms_auth = get_ms_auth()
            token = await ms_auth.get_application_token()
            sp_cfg: dict = {}
            if token:
                sp_tmp = SharePointService(access_token=token)
                sp_cfg = await sp_tmp._resolve_config(conn)

        # Phase 2: SP uploads outside conn (slow HTTP)
        upload_data = []
        for result in resultados:
            final_xml = descargas_finales.get(result.periodo, {}).get("xml", {})
            final_pdf = descargas_finales.get(result.periodo, {}).get("pdf", {})
            ya_xml = final_xml.get("estatus") == "completado"
            ya_pdf = final_pdf.get("estatus") == "completado"
            staging_folder = (
                f"{SHAREPOINT_CFE_STAGING_ROOT}/{busqueda['id']}"
                f"/{servicio['numero_servicio']}/{result.periodo}"
            )
            # Guardia anti-contaminacion: si el XML es de otro servicio, no se
            # stagea ese periodo (ni XML ni PDF) y se marca con el error de RPU.
            rpu_error = self._rpu_no_coincide(
                result.xml_content, result.xml_filename, servicio["numero_servicio"]
            )
            if rpu_error:
                logger.warning(
                    "[CFE] %s servicio=%s periodo=%s", rpu_error,
                    servicio["numero_servicio"], result.periodo,
                )
                result.xml_content = None
                result.pdf_content = None
                result.xml_error = result.xml_error or rpu_error
                result.pdf_error = result.pdf_error or rpu_error
            xml_upload, xml_upload_err = None, None
            if result.xml_content and not ya_xml:
                xml_upload, xml_upload_err = await self._upload_bytes_to_sharepoint(
                    None,
                    content=result.xml_content,
                    filename=result.xml_filename or f"{servicio['numero_servicio']}-{result.periodo}.xml",
                    folder_path=staging_folder,
                    tipo="xml",
                    _sp_cfg=sp_cfg,
                )
            pdf_upload, pdf_upload_err = None, None
            if result.pdf_content and not ya_pdf:
                pdf_upload, pdf_upload_err = await self._upload_bytes_to_sharepoint(
                    None,
                    content=result.pdf_content,
                    filename=result.pdf_filename or f"{servicio['numero_servicio']}-{result.periodo}.pdf",
                    folder_path=staging_folder,
                    tipo="pdf",
                    _sp_cfg=sp_cfg,
                )
            upload_data.append((result, ya_xml, ya_pdf, final_xml, final_pdf, xml_upload, xml_upload_err, pdf_upload, pdf_upload_err))

        # Phase 3: DB writes (short conn)
        async with pool.acquire() as conn:
            total_descargados = 0
            for (result, ya_xml, ya_pdf, final_xml, final_pdf, xml_upload, xml_upload_err, pdf_upload, pdf_upload_err) in upload_data:
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
                # "Nuevos" = periodos con al menos un artefacto recien staged.
                # No cuenta 'ya_descargado' (ya existian) para no inflar la cifra.
                if xml_estatus == "descargado" or pdf_estatus == "descargado":
                    total_descargados += 1

                tipo_recibo = (
                    self._extraer_tipo_recibo(result.xml_content, result.xml_filename)
                    or final_xml.get("tipo_recibo")
                )
                errores = [msg for msg in (result.xml_error, result.pdf_error, xml_upload_err, pdf_upload_err) if msg]
                decision = "no_aplica" if ya_xml and ya_pdf else "pendiente"
                await self.db.upsert_busqueda_item(
                    conn,
                    busqueda_id=busqueda["id"],
                    periodo=result.periodo,
                    etiqueta_periodo=result.etiqueta,
                    tipo_recibo=tipo_recibo,
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
                advertencia=resultado.advertencia,
                total_disponible_publico=(
                    resultado.total_disponible_publico
                    if resultado.total_disponible_publico >= 0 else None
                ),
                total_disponible_miespacio=(
                    resultado.total_disponible_miespacio
                    if resultado.total_disponible_miespacio >= 0 else None
                ),
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
        if error or contenido:
            return "error"
        return "no_disponible"

    async def _ejecutar_job(
        self,
        pool: asyncpg.Pool,
        servicio: dict,
        cfg_global: dict,
        job: dict,
    ) -> None:
        if job["tipo"] == "pdf":
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
        cfg = self._build_scraper_config(servicio, cfg_global)
        # Servicio ya registrado en MiEspacio: ambos archivos (XML + PDF) salen de
        # la misma fila de Otras Facturas, sin tocar el portal publico. Solo se
        # usa el portal publico como fallback para servicios aun no registrados.
        if servicio.get("miespacio_estatus") == "registrado":
            result = await descargar_ultimo_recibo_miespacio(cfg)
        else:
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

            # Guardia anti-contaminacion: el XML debe ser del servicio esperado.
            rpu_error = self._rpu_no_coincide(
                result.xml_content, result.xml_filename, servicio["numero_servicio"]
            )
            if rpu_error:
                logger.warning(
                    "[CFE] %s servicio=%s periodo=%s", rpu_error,
                    servicio["numero_servicio"], result.periodo or "desconocido",
                )
                await self.db.upsert_descarga(
                    conn, servicio_id=servicio["id"], periodo=result.periodo or "desconocido",
                    tipo="xml", estatus="error", error_mensaje=rpu_error,
                    descargado_por=usuario_id,
                )
                await self.db.borrar_descarga_pendiente(conn, servicio["id"])
                return

            # Upload XML to SharePoint
            tipo_recibo = self._extraer_tipo_recibo(result.xml_content, result.xml_filename)
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
                tipo_recibo=tipo_recibo,
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
                    tipo_recibo=tipo_recibo,
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
                    descargado_por=usuario_id, tipo_recibo=tipo_recibo,
                )
                if self._es_error_sesion(result.pdf_error):
                    await self._marcar_sesion_invalida(conn)

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
        cfg = self._build_scraper_config(servicio, cfg_global)
        result = await descargar_pdf_periodo(cfg, periodo)
        logger.info(
            "[CFE] Scraper PDF finalizado servicio=%s periodo=%s pdf=%s error=%s",
            servicio["numero_servicio"],
            periodo,
            bool(result.pdf_content),
            bool(result.error or result.pdf_error),
        )

        async with pool.acquire() as conn:
            xml_row = await self.db.get_descarga_por_tipo(conn, servicio["id"], periodo, "xml")
            tipo_recibo = xml_row.get("tipo_recibo") if xml_row else None
            error_mensaje = result.error or result.pdf_error
            if error_mensaje:
                await self.db.upsert_descarga(
                    conn, servicio_id=servicio["id"], periodo=periodo,
                    tipo="pdf", estatus="error", error_mensaje=error_mensaje,
                    descargado_por=usuario_id, tipo_recibo=tipo_recibo,
                )
                if self._es_error_sesion(error_mensaje):
                    await self._marcar_sesion_invalida(conn)
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
                    tipo_recibo=tipo_recibo,
                )
            else:
                await self.db.upsert_descarga(
                    conn, servicio_id=servicio["id"], periodo=periodo,
                    tipo="pdf", estatus="error",
                    error_mensaje="No se descargó el PDF de MiEspacio.",
                    descargado_por=usuario_id, tipo_recibo=tipo_recibo,
                )

            if result.session_json_nuevo:
                await self._save_session(conn, result.session_json_nuevo)
                logger.info("[CFE] Sesion MiEspacio renovada servicio=%s", servicio["numero_servicio"])

    async def _registrar_descarga_sp(
        self, conn: asyncpg.Connection, *, servicio_id: UUID, periodo: str,
        tipo: str, nombre_archivo: str, sp_url: Optional[str], usuario_id: Optional[UUID],
        tipo_recibo: Optional[str] = None,
    ) -> None:
        await self.db.upsert_descarga(
            conn, servicio_id=servicio_id, periodo=periodo, tipo=tipo,
            estatus="completado" if sp_url else "error",
            nombre_archivo=nombre_archivo, ruta_sharepoint=sp_url,
            error_mensaje=None if sp_url else f"Error subiendo {tipo.upper()} a SharePoint",
            descargado_por=usuario_id, tipo_recibo=tipo_recibo,
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
        tipo_recibo_final: Optional[str] = None,
    ) -> None:
        periodo = item["periodo"]
        folder = f"{SHAREPOINT_CFE_ROOT}/{busqueda['numero_servicio']}/{periodo}"
        tipo_recibo = tipo_recibo_final

        if item.get("xml_drive_item_id") and not ya_final_xml:
            xml_content = await sp.download_file_by_item_id(conn, item["xml_drive_item_id"])
            xml_filename = item.get("xml_nombre_archivo") or f"{busqueda['numero_servicio']}-{periodo}.xml"
            tipo_recibo = self._extraer_tipo_recibo(xml_content, xml_filename) or tipo_recibo
            xml_upload, _ = await self._upload_bytes_to_sharepoint(
                conn,
                content=xml_content,
                filename=xml_filename,
                folder_path=folder,
                tipo="xml",
            )
            await self._registrar_descarga_sp(
                conn,
                servicio_id=busqueda["servicio_id"],
                periodo=periodo,
                tipo="xml",
                nombre_archivo=xml_filename,
                sp_url=xml_upload.get("webUrl") if xml_upload else None,
                usuario_id=usuario_id,
                tipo_recibo=tipo_recibo,
            )

        if item.get("pdf_drive_item_id") and not ya_final_pdf:
            pdf_content = await sp.download_file_by_item_id(conn, item["pdf_drive_item_id"])
            pdf_upload, _ = await self._upload_bytes_to_sharepoint(
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
                tipo_recibo=tipo_recibo,
            )

    async def _borrar_staging_item(
        self,
        conn: Optional[asyncpg.Connection],
        sp: SharePointService,
        item: dict,
        *,
        _sp_cfg: Optional[dict] = None,
    ) -> None:
        for field in ("xml_drive_item_id", "pdf_drive_item_id"):
            drive_item_id = item.get(field)
            if not drive_item_id:
                continue
            try:
                await sp.delete_file_by_item_id(conn, drive_item_id, _config=_sp_cfg)
            except (ValueError, RuntimeError, httpx.HTTPError) as exc:
                logger.warning(
                    "[CFE] No se pudo borrar staging item_id=%s periodo=%s error=%s",
                    drive_item_id,
                    item.get("periodo"),
                    exc,
                )

    async def _upload_bytes_to_sharepoint(
        self,
        conn: Optional[asyncpg.Connection],
        *,
        content: bytes,
        filename: str,
        folder_path: str,
        tipo: str,
        _sp_cfg: Optional[dict] = None,
    ) -> tuple[Optional[dict], Optional[str]]:
        try:
            ms_auth = get_ms_auth()
            token = await ms_auth.get_application_token()
            if not token:
                raise RuntimeError("No se pudo obtener token de Microsoft")

            sp = SharePointService(access_token=token)
            sp_cfg = _sp_cfg if _sp_cfg is not None else await sp._resolve_config(conn)
            if not sp_cfg.get("site_id") and not sp_cfg.get("drive_id"):
                raise RuntimeError(
                    "SharePoint no configurado (SHAREPOINT_SITE_ID/DRIVE_ID). "
                    "Configuralos en Admin antes de descargar recibos CFE."
                )

            upload = UploadFile(filename=filename, file=BytesIO(content))
            result = await sp.upload_file(conn=None, file=upload, folder_path=folder_path, _config=sp_cfg)
            return result, None
        except (ValueError, RuntimeError, httpx.HTTPError, OSError) as exc:
            msg = str(exc)
            logger.error("Error subiendo %s a SharePoint carpeta=%s archivo=%s: %s", tipo, folder_path, filename, msg)
            return None, msg

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
        folder = f"{SHAREPOINT_CFE_ROOT}/{servicio_numero}/{periodo}"
        result, _ = await self._upload_bytes_to_sharepoint(
            conn, content=content, filename=filename, folder_path=folder, tipo=tipo
        )
        return result.get("webUrl") if result else None

    async def get_analisis_servicio(
        self,
        conn: asyncpg.Connection,
        servicio_id: UUID,
    ) -> dict[str, Any]:
        servicio = await self.db.get_servicio_by_id(conn, servicio_id)
        if not servicio:
            raise ValueError("Servicio no encontrado.")

        descargas = await self.db.get_descargas_por_servicio(conn, servicio_id)
        xml_rows = filtrar_xmls_completados(descargas)
        if not xml_rows:
            return analisis_sin_datos(
                servicio,
                "No hay XMLs completados para analizar este servicio.",
            )

        xml_descargados = await self._descargar_xmls_sharepoint(xml_rows)
        if not xml_descargados:
            return analisis_sin_datos(
                servicio,
                "No se pudieron obtener los XMLs desde SharePoint.",
            )

        recibos: list[tuple[dict, CfeReceipt]] = []
        for row, xml_input in xml_descargados:
            try:
                recibos.append((
                    row,
                    extraer_datos_xml(xml_input.content, xml_input.filename),
                ))
            except ValueError as exc:
                logger.warning(
                    "cfe_analisis_xml_omitido servicio_id=%s periodo=%s archivo=%s motivo=%s",
                    servicio_id,
                    row.get("periodo"),
                    xml_input.filename,
                    exc,
                )

        if not recibos:
            return analisis_sin_datos(
                servicio,
                "Los XMLs descargados no contienen recibos CFE válidos.",
            )

        return construir_analisis_recibos(servicio, recibos)

    async def _descargar_xmls_sharepoint(
        self,
        xml_rows: Sequence[dict],
    ) -> list[tuple[dict, CfeXmlInput]]:
        archivos = await self._descargar_archivos_sharepoint(xml_rows)
        return [
            (
                row,
                CfeXmlInput(
                    filename=row.get("nombre_archivo") or "recibo.xml",
                    content=content,
                ),
            )
            for row, content in archivos
        ]

    async def _descargar_archivos_sharepoint(
        self,
        rows: Sequence[dict],
    ) -> list[tuple[dict, bytes]]:
        archivos, _ = await self._descargar_archivos_sharepoint_con_reintentos(
            rows,
            max_intentos=1,
        )
        return archivos

    async def _descargar_archivos_sharepoint_con_reintentos(
        self,
        rows: Sequence[dict],
        *,
        max_intentos: int = CFE_ZIP_MAX_DOWNLOAD_ATTEMPTS,
    ) -> tuple[list[tuple[dict, bytes]], list[dict]]:
        if not rows:
            return [], []

        ms_auth = get_ms_auth()
        token = await ms_auth.get_application_token()
        if not token:
            raise ValueError("No se pudo obtener token de Microsoft para leer SharePoint.")

        async def _fetch_archivo_con_reintentos(
            client: httpx.AsyncClient,
            row: dict,
        ) -> tuple[Optional[tuple[dict, bytes]], Optional[dict]]:
            max_reintentos = max(1, max_intentos)
            ultimo_motivo = "No se pudo descargar el archivo."
            for intento in range(1, max_reintentos + 1):
                content, motivo = await self._descargar_archivo_sharepoint_http(client, token, row)
                if content is not None:
                    return (row, content), None
                ultimo_motivo = motivo or ultimo_motivo
                logger.warning(
                    "cfe_sharepoint_zip_reintento descarga_id=%s periodo=%s tipo=%s intento=%s/%s motivo=%s",
                    row.get("id"),
                    row.get("periodo"),
                    row.get("tipo"),
                    intento,
                    max_reintentos,
                    ultimo_motivo,
                )
            return None, _detalle_faltante_zip(row, ultimo_motivo)

        async with httpx.AsyncClient(timeout=30) as client:
            results = await asyncio.gather(*[_fetch_archivo_con_reintentos(client, row) for row in rows])

        archivos: list[tuple[dict, bytes]] = []
        faltantes: list[dict] = []
        for archivo, faltante in results:
            if archivo is not None:
                archivos.append(archivo)
            if faltante is not None:
                faltantes.append(faltante)
        return archivos, faltantes

    async def _descargar_archivo_sharepoint_http(
        self,
        client: httpx.AsyncClient,
        token: str,
        row: dict,
    ) -> tuple[Optional[bytes], Optional[str]]:
        url = row.get("ruta_sharepoint")
        if not url:
            return None, "La descarga no tiene ruta de SharePoint."

        try:
            download_url = await _resolve_sharepoint_download_url(client, token, url)
            if not download_url:
                return None, "No se pudo resolver la URL directa de SharePoint."

            resp = await client.get(download_url, headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError as exc:
            return None, f"Error de SharePoint: {exc}"

        if resp.status_code != 200:
            return None, f"SharePoint respondio {resp.status_code}."

        return resp.content, None

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

        xml_descargados = await self._descargar_xmls_sharepoint(xml_rows)
        inputs = [xml_input for _, xml_input in xml_descargados]
        if not inputs:
            raise ValueError("No se pudieron obtener los XMLs desde SharePoint.")

        return generar_excel_cfe(inputs, perfil_slug).getvalue()

    async def generar_zip_servicio(
        self,
        conn: asyncpg.Connection,
        servicio_id: UUID,
        perfil_slug: str = "oym",
        permitir_incompleto: bool = False,
    ) -> tuple[bytes, str]:
        servicio = await self.db.get_servicio_by_id(conn, servicio_id)
        if not servicio:
            raise LookupError("Servicio no encontrado.")

        servicio_numero = servicio["numero_servicio"]
        descargas = await self.db.get_descargas_por_servicio(conn, servicio_id)
        rows = []
        for descarga in descargas:
            if (
                descarga["estatus"] == "completado"
                and descarga["tipo"] in ("xml", "pdf")
                and descarga.get("ruta_sharepoint")
            ):
                row = dict(descarga)
                row["numero_servicio"] = servicio_numero
                row["servicio_nombre"] = servicio.get("nombre")
                row["alias"] = servicio.get("alias")
                rows.append(row)
        if not any(row["tipo"] == "xml" for row in rows):
            raise ValueError("No hay XMLs descargados para generar el ZIP con Excel.")

        archivos, faltantes = await self._descargar_archivos_sharepoint_con_reintentos(rows)
        if faltantes and not permitir_incompleto:
            raise CfeZipFaltantesError(faltantes)
        if not archivos:
            raise ValueError("No se pudieron obtener los archivos desde SharePoint.")
        if not permitir_incompleto and not any(row["tipo"] == "xml" for row, _ in archivos):
            raise ValueError("No se pudieron obtener XMLs desde SharePoint para generar el Excel.")

        zip_buffer = BytesIO()
        nombre_servicio = _sanitize_zip_component(
            f"CFE_{servicio_numero}",
            "CFE_servicio",
        )
        nombre_excel = _sanitize_zip_component(
            f"CFE_{servicio_numero}.xlsx",
            "recibos_cfe.xlsx",
        )
        nombre_zip = _sanitize_zip_component(
            f"CFE_{servicio_numero}.zip",
            "recibos_cfe.zip",
        )
        usados: set[str] = set()
        xml_inputs: list[CfeXmlInput] = []

        with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for row, content in sorted(
                archivos,
                key=lambda item: (
                    item[0].get("periodo") or "",
                    item[0].get("tipo") or "",
                    item[0].get("nombre_archivo") or "",
                ),
                reverse=True,
            ):
                tipo = row["tipo"]
                periodo = _sanitize_zip_component(row.get("periodo") or "sin_periodo", "sin_periodo")
                nombre_archivo = _nombre_archivo_zip_cfe(
                    row,
                    perfil_slug=perfil_slug,
                    numero_servicio=servicio_numero,
                    alias_o_nombre=servicio.get("alias") or servicio.get("nombre"),
                )
                archivo_path = (
                    nombre_archivo
                    if perfil_slug == "simulacion"
                    else f"{periodo}_{nombre_archivo}"
                )
                zip_path = _dedupe_zip_path(
                    usados,
                    f"{nombre_servicio}/{tipo.upper()}/{archivo_path}",
                )
                zf.writestr(zip_path, content)

                if tipo == "xml":
                    xml_inputs.append(
                        CfeXmlInput(
                            filename=row.get("nombre_archivo") or f"{servicio_numero}_{periodo}.xml",
                            content=content,
                        )
                    )

            if xml_inputs:
                excel_bytes = generar_excel_cfe(xml_inputs, perfil_slug).getvalue()
                zf.writestr(
                    _dedupe_zip_path(usados, f"{nombre_servicio}/{nombre_excel}"),
                    excel_bytes,
                )
            if faltantes:
                zf.writestr(
                    _dedupe_zip_path(usados, "_FALTANTES.txt"),
                    _contenido_faltantes_zip(faltantes),
                )

        return zip_buffer.getvalue(), nombre_zip

    async def generar_zip_global(
        self,
        conn: asyncpg.Connection,
        *,
        modulos: list[str] | None,
        perfil_slug: str = "oym",
        creado_por_ids: list[UUID] | None = None,
        servicio_ids: list[UUID] | None = None,
        permitir_incompleto: bool = False,
    ) -> tuple[bytes, str]:
        """
        ZIP unico con el ultimo recibo (XML + PDF + Excel) de cada servicio
        registrado en MiEspacio dentro de los modulos dados. Un folder por
        servicio. Corresponde al resultado de la descarga masiva.
        """
        rows = await self.db.get_ultimas_descargas_completadas_por_modulo(
            conn, modulos, creado_por_ids=creado_por_ids, servicio_ids=servicio_ids
        )
        if not rows:
            raise ValueError("No hay recibos descargados para incluir en el ZIP.")

        archivos, faltantes = await self._descargar_archivos_sharepoint_con_reintentos(rows)
        if faltantes and not permitir_incompleto:
            raise CfeZipFaltantesError(faltantes)
        if not archivos:
            raise ValueError("No se pudieron obtener los archivos desde SharePoint.")
        if not permitir_incompleto and not any(row["tipo"] == "xml" for row, _ in archivos):
            raise ValueError("No se pudieron obtener XMLs desde SharePoint para generar el Excel.")

        # Agrupa por servicio para armar un folder + Excel por cada uno.
        por_servicio: dict[str, list[tuple[dict, bytes]]] = {}
        for row, content in archivos:
            por_servicio.setdefault(row["numero_servicio"], []).append((row, content))

        zip_buffer = BytesIO()
        usados: set[str] = set()
        xml_inputs_global: list[CfeXmlInput] = []
        with PdfWriter() as pdf_merger, zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for numero_servicio in sorted(por_servicio):
                primera_fila, _ = por_servicio[numero_servicio][0]
                label = primera_fila.get("servicio_nombre") or numero_servicio
                nombre_carpeta = _sanitize_zip_component(f"{label} ({numero_servicio})", numero_servicio)
                xml_inputs: list[CfeXmlInput] = []
                for row, content in sorted(
                    por_servicio[numero_servicio],
                    key=lambda item: (item[0].get("tipo") or "", item[0].get("nombre_archivo") or ""),
                ):
                    tipo = row["tipo"]
                    periodo = _sanitize_zip_component(row.get("periodo") or "sin_periodo", "sin_periodo")
                    nombre_archivo = _nombre_archivo_zip_cfe(
                        row,
                        perfil_slug=perfil_slug,
                        numero_servicio=numero_servicio,
                        alias_o_nombre=row.get("alias") or label,
                    )
                    archivo_path = (
                        nombre_archivo
                        if perfil_slug == "simulacion"
                        else f"{periodo}_{nombre_archivo}"
                    )
                    zip_path = _dedupe_zip_path(
                        usados, f"{nombre_carpeta}/{archivo_path}"
                    )
                    zf.writestr(zip_path, content)
                    if tipo == "xml":
                        xml_input = CfeXmlInput(
                            filename=row.get("nombre_archivo") or f"{numero_servicio}_{periodo}.xml",
                            content=content,
                        )
                        xml_inputs.append(xml_input)
                        xml_inputs_global.append(xml_input)
                    elif tipo == "pdf":
                        try:
                            pdf_merger.append(BytesIO(content))
                        except (pypdf.errors.PyPdfError, struct.error, ValueError) as exc:
                            logger.warning("No se pudo agregar PDF al merge global: %s %s", numero_servicio, periodo, exc_info=exc)
                if xml_inputs:
                    excel_bytes = generar_excel_cfe(xml_inputs, perfil_slug).getvalue()
                    nombre_excel = _sanitize_zip_component(f"{label}.xlsx", "recibos_cfe.xlsx")
                    zf.writestr(_dedupe_zip_path(usados, f"{nombre_carpeta}/{nombre_excel}"), excel_bytes)

            if pdf_merger.pages:
                merged_pdf = BytesIO()
                pdf_merger.write(merged_pdf)
                nombre_pdf_global = f"CFE_todos_los_recibos_{now_mx().strftime('%Y%m%d')}.pdf"
                zf.writestr(nombre_pdf_global, merged_pdf.getvalue())
            if xml_inputs_global:
                excel_global = generar_excel_cfe(xml_inputs_global, perfil_slug).getvalue()
                nombre_excel_global = f"CFE_todos_los_recibos_{now_mx().strftime('%Y%m%d')}.xlsx"
                zf.writestr(_dedupe_zip_path(usados, nombre_excel_global), excel_global)
            if faltantes:
                zf.writestr(
                    _dedupe_zip_path(usados, "_FALTANTES.txt"),
                    _contenido_faltantes_zip(faltantes),
                )

        nombre_zip = f"CFE_ultimos_recibos_{now_mx().strftime('%Y%m%d')}.zip"
        return zip_buffer.getvalue(), nombre_zip

    # ── Vista previa ──────────────────────────────────────────────────────

    async def get_url_preview(
        self, conn: asyncpg.Connection, descarga_id: UUID, servicio_id: UUID
    ) -> Optional[str]:
        row = await conn.fetchrow(
            "SELECT ruta_sharepoint FROM tb_cfe_descargas WHERE id=$1 AND servicio_id=$2",
            descarga_id, servicio_id,
        )
        return row["ruta_sharepoint"] if row else None


def _detalle_faltante_zip(row: dict, motivo: str) -> dict:
    numero_servicio = row.get("numero_servicio") or ""
    servicio = row.get("servicio_nombre") or row.get("nombre") or numero_servicio
    return {
        "servicio": str(servicio or ""),
        "numero_servicio": str(numero_servicio or ""),
        "periodo": str(row.get("periodo") or ""),
        "tipo": str(row.get("tipo") or "").upper(),
        "nombre_archivo": str(row.get("nombre_archivo") or ""),
        "motivo": motivo,
    }


def _contenido_faltantes_zip(faltantes: Sequence[dict]) -> str:
    lineas = [
        "Archivos CFE no incluidos en este ZIP",
        "",
        "Los siguientes archivos no pudieron descargarse desde SharePoint despues de 3 intentos.",
        "Puedes descargarlos manualmente desde la seccion Historial del servicio.",
        "",
    ]
    for faltante in faltantes:
        servicio = faltante.get("servicio") or "Servicio"
        numero = faltante.get("numero_servicio") or "Sin numero"
        periodo = faltante.get("periodo") or "Sin periodo"
        tipo = faltante.get("tipo") or "ARCHIVO"
        archivo = faltante.get("nombre_archivo") or "Sin nombre"
        motivo = faltante.get("motivo") or "No disponible"
        lineas.append(f"- {servicio} ({numero}) | {periodo} | {tipo} | {archivo} | {motivo}")
    lineas.append("")
    return "\n".join(lineas)


def _nombre_archivo_zip_cfe(
    row: dict,
    *,
    perfil_slug: str,
    numero_servicio: str,
    alias_o_nombre: object,
) -> str:
    tipo = str(row.get("tipo") or "").lower()
    extension = tipo if tipo in {"xml", "pdf"} else "dat"
    if perfil_slug != "simulacion":
        return _sanitize_zip_component(
            row.get("nombre_archivo") or f"{numero_servicio}_{row.get('periodo')}.{extension}",
            f"recibo.{extension}",
        )

    periodo = _periodo_zip_simulacion(row.get("periodo"))
    etiqueta = str(alias_o_nombre or "").strip().upper() or "SIN_ALIAS"
    return _sanitize_zip_filename(
        f"{periodo}_{numero_servicio}_{etiqueta}.{extension}",
        f"{periodo}_{numero_servicio}.{extension}",
    )


def _periodo_zip_simulacion(periodo: object) -> str:
    match = re.match(r"^(\d{4})-(\d{2})$", str(periodo or ""))
    if not match:
        return _sanitize_zip_filename(periodo, "SIN_PERIODO")
    anio, mes_raw = match.groups()
    mes = _MESES_ZIP_SIMULACION.get(int(mes_raw), mes_raw)
    return f"{mes} {anio[-2:]}"


def _sanitize_zip_component(value: object, fallback: str) -> str:
    raw = str(value or "").replace("\\", "/").split("/")[-1].strip()
    invalid_chars = '<>:"/\\|?*'
    clean = "".join(
        "_" if char in invalid_chars or ord(char) < 32 else char
        for char in raw
    ).strip(" .")
    return clean or fallback


def _sanitize_zip_filename(value: object, fallback: str) -> str:
    raw = str(value or "").strip()
    invalid_chars = '<>:"/\\|?*'
    clean = "".join(
        "_" if char in invalid_chars or ord(char) < 32 else char
        for char in raw
    ).strip(" .")
    return clean or fallback


def _dedupe_zip_path(used: set[str], path: str) -> str:
    if path not in used:
        used.add(path)
        return path

    base, dot, ext = path.rpartition(".")
    for index in range(2, 10_000):
        candidate = f"{base}_{index}{dot}{ext}" if dot else f"{path}_{index}"
        if candidate not in used:
            used.add(candidate)
            return candidate

    raise RuntimeError("No se pudo generar un nombre unico dentro del ZIP.")


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
