import re
from typing import Optional
from uuid import UUID

from core.microsoft import get_ms_auth

from .db_service import IntegrationsDBService, get_integrations_db_service
from .schemas import SharePointResolverStatus
from .sharepoint import SharePointService

# Ancla `{prefijo}-{consecutivo}` (ej. "MX-50158") al inicio de proyecto_id_estandar
# (formato "{prefijo}-{consecutivo}-{tecnologia} {nombre_corto}", core/projects/service.py).
# El consecutivo es único en todo el sistema, por eso esta ancla es un identificador
# de carpeta mucho más confiable que el nombre completo para el matching en SharePoint.
_ANCLA_PROYECTO_RE = re.compile(r"^[A-Za-z]+-\d+")


def _extraer_ancla_proyecto(proyecto_id_estandar: str) -> str:
    match = _ANCLA_PROYECTO_RE.match(proyecto_id_estandar or "")
    return match.group(0) if match else ""


class IntegrationsService:
    """Orquesta integraciones externas usadas por endpoints compartidos."""

    def __init__(self, db: IntegrationsDBService | None = None):
        self.db = db or get_integrations_db_service()
        self.ms_auth = get_ms_auth()

    async def list_visitas_sharepoint_folders(self, conn, folder_id: Optional[str]) -> list[dict]:
        site_id, drive_id, _ = await self._get_visitas_sp_config(conn)
        sp = await self._get_sharepoint_client()
        return await sp.list_folder_children(
            drive_id=drive_id,
            site_id=site_id,
            folder_id=folder_id or None,
        )

    async def _get_visitas_sp_config(self, conn) -> tuple[str, str, str]:
        config = await self.db.get_config_values(
            conn,
            ("SP_VISITAS_SITE_ID", "SP_VISITAS_DRIVE_ID", "SP_VISITAS_CARPETA_SIN_EXPEDIENTE"),
        )
        site_id = config.get("SP_VISITAS_SITE_ID", "")
        drive_id = config.get("SP_VISITAS_DRIVE_ID", "")
        carpeta_sin_expediente = config.get("SP_VISITAS_CARPETA_SIN_EXPEDIENTE", "") or "Proyectos sin expediente"
        if not site_id and not drive_id:
            raise ValueError(
                "SharePoint de Visitas no configurado. "
                "Configura SP_VISITAS_SITE_ID y SP_VISITAS_DRIVE_ID en Admin."
            )
        return site_id, drive_id, carpeta_sin_expediente

    async def _get_sharepoint_client(self) -> SharePointService:
        app_token = await self.ms_auth.get_application_token()
        if not app_token:
            raise RuntimeError("No se pudo obtener token de Microsoft")
        return SharePointService(access_token=app_token)

    async def resolver_carpeta_proyecto(
        self,
        conn,
        id_proyecto: UUID,
        proyecto_id_estandar: str,
        nombre_proyecto: Optional[str],
        nombre_corto: Optional[str],
    ) -> dict:
        """
        Resuelve la carpeta de SharePoint de un proyecto: primero busca un mapeo
        ya persistido; si no hay, busca en Graph por proyecto_id_estandar y,
        si no hay match, reintenta con nombre_proyecto/nombre_corto.
        Siempre secuencial (BD → Graph), nunca asyncio.gather() mezclando conn con HTTP.
        """
        mapeo = await self.db.get_sharepoint_mapeo(conn, id_proyecto)
        if mapeo and mapeo.get("sharepoint_folder_id"):
            return {"status": SharePointResolverStatus.MAPEADO, "web_url": mapeo.get("sharepoint_url") or ""}

        site_id, drive_id, carpeta_sin_expediente = await self._get_visitas_sp_config(conn)
        sp = await self._get_sharepoint_client()

        queries = [proyecto_id_estandar]
        query_fallback = nombre_proyecto or nombre_corto
        if query_fallback:
            queries.append(query_fallback)
        ancla = _extraer_ancla_proyecto(proyecto_id_estandar)
        matches, fallback = await sp.resolver_carpeta_con_fallback(
            drive_id, site_id, queries, carpeta_sin_expediente, ancla=ancla
        )

        if not matches:
            return {
                "status": SharePointResolverStatus.SIN_MATCH,
                "fallback_web_url": (fallback or {}).get("webUrl", ""),
                "fallback_label": carpeta_sin_expediente,
            }
        if len(matches) > 1:
            return {"status": SharePointResolverStatus.AMBIGUO}

        match = matches[0]
        web_url = match.get("webUrl", "")
        if not web_url:
            # Graph no devolvio webUrl para este item (caso raro) -- no persistir un
            # mapeo MAPEADO sin url resoluble, o "Ver Expediente" quedaria abriendo
            # about:blank para siempre sin ninguna señal de error.
            return {
                "status": SharePointResolverStatus.SIN_MATCH,
                "fallback_web_url": (fallback or {}).get("webUrl", ""),
                "fallback_label": carpeta_sin_expediente,
            }
        await self.db.persist_sharepoint_mapeo(
            conn,
            id_proyecto,
            folder_id=match["id"],
            drive_id=drive_id,
            web_url=web_url,
            origen="BUSQUEDA_AUTOMATICA",
        )
        return {"status": SharePointResolverStatus.MAPEADO, "web_url": web_url}

    async def set_mapeo_manual(
        self,
        conn,
        id_proyecto: UUID,
        folder_id: str,
        corregir_nombre: bool,
    ) -> dict:
        """
        Persiste una selección manual de carpeta (elegida vía el navegador, que ya
        solo lista contenido del drive SP_VISITAS correcto). drive_id y web_url se
        resuelven server-side — nunca se confía en esos valores del cliente.
        Si corregir_nombre es True, el usuario confirmó explícitamente corregir el
        nombre de la carpeta al estándar del proyecto — el nombre se resuelve desde
        BD (proyecto_id_estandar), nunca se confía en un string que mande el
        cliente. Nunca automático/silencioso: siempre requiere este flag explícito.
        """
        site_id, drive_id, _ = await self._get_visitas_sp_config(conn)
        sp = await self._get_sharepoint_client()

        web_url = ""
        if corregir_nombre:
            nombre_estandar = await self.db.get_proyecto_id_estandar(conn, id_proyecto)
            if nombre_estandar:
                renamed = await sp.rename_folder(drive_id, site_id, folder_id, nombre_estandar)
                web_url = renamed.get("webUrl") or ""
        if not web_url:
            web_url = await sp.get_item_web_url(drive_id, site_id, folder_id)
        if not web_url:
            # No persistir un mapeo "exitoso" sin webUrl resoluble -- el folder_id pudo
            # quedar invalido (borrado entre el listado del navegador y la confirmacion)
            # o Graph no lo devolvio; mejor fallar explicito que dejar "Ver Expediente"
            # abriendo about:blank para siempre sin ninguna señal de error.
            raise RuntimeError("No se pudo resolver el webUrl de la carpeta seleccionada en SharePoint")

        await self.db.persist_sharepoint_mapeo(
            conn,
            id_proyecto,
            folder_id=folder_id,
            drive_id=drive_id,
            web_url=web_url,
            origen="MANUAL",
        )
        return {"status": SharePointResolverStatus.MAPEADO, "web_url": web_url}


def get_integrations_service() -> IntegrationsService:
    return IntegrationsService()
