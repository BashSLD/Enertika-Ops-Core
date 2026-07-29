import asyncio
import difflib
import logging
import re
import unicodedata
from typing import Optional, Dict
import asyncpg
import httpx
import urllib.parse
from fastapi import UploadFile

from core.microsoft import get_ms_auth
from core.config import settings
from core.integrations.db_service import get_integrations_db_service

logger = logging.getLogger("SharePointService")

# Umbral de similitud (difflib.SequenceMatcher.ratio) para considerar una carpeta
# de la raíz como candidata al buscar por nombre de proyecto. Tolera typos/espacios
# de más en el nombre real de la carpeta frente a proyecto_id_estandar/nombre_proyecto.
_FOLDER_MATCH_THRESHOLD = 0.6
# Timeout explícito para listar+paginar la raíz del drive: más holgado de lo necesario
# para 1-2 páginas de 200 items, pero corto frente al timeout=120 de gunicorn.
_ROOT_LIST_TIMEOUT_SECONDS = 15.0
_MAX_429_RETRIES = 3
# Cap del backoff por 429: un Retry-After real de Graph puede ser >= 10-60s, lo que
# agotaría _ROOT_LIST_TIMEOUT_SECONDS en un solo sleep y dejaria los reintentos
# restantes sin oportunidad de correr. Preferimos fallar rapido (menos reintentos
# efectivos) a que el timeout externo mate la corrutina a mitad de un sleep largo.
_MAX_429_BACKOFF_SECONDS = 5.0

class SharePointService:
    """
    Servicio para integración con SharePoint via Microsoft Graph API.
    Maneja la carga, descarga y gestión de metadatos de archivos.
    """

    BASE_URL = "https://graph.microsoft.com/v1.0"
    
    def __init__(self, access_token: str = None):
        self.access_token = access_token
        self.ms_auth = get_ms_auth()
        # Si no se pasa token, se debe establecer antes de llamar a métodos que lo requieran
        
        # Configuración por defecto (puede sobreescribirse o cargarse de BD/Settings)
        # Por ahora usamos los settings globales si existen, o placeholders
        self.site_id = getattr(settings, 'SHAREPOINT_SITE_ID', None)
        self.drive_id = getattr(settings, 'SHAREPOINT_DRIVE_ID', None)

    def _get_headers(self) -> dict:
        if not self.access_token:
            raise ValueError("Token de acceso no establecido en SharePointService")
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

    async def _resolve_config(self, conn) -> Dict[str, str]:
        """
        Resuelve configuración priorizando BD > Settings > Defaults.
        """
        config = {
            "site_id": getattr(settings, 'SHAREPOINT_SITE_ID', None),
            "drive_id": getattr(settings, 'SHAREPOINT_DRIVE_ID', None)
        }
        
        # Intentar leer de BD si hay conexión
        if conn:
            try:
                db_config = await get_integrations_db_service().get_config_values(
                    conn,
                    ("SHAREPOINT_SITE_ID", "SHAREPOINT_DRIVE_ID"),
                )
                if db_config.get("SHAREPOINT_SITE_ID"):
                    config["site_id"] = db_config["SHAREPOINT_SITE_ID"]
                if db_config.get("SHAREPOINT_DRIVE_ID"):
                    config["drive_id"] = db_config["SHAREPOINT_DRIVE_ID"]
            except asyncpg.PostgresError as e:
                logger.warning(f"No se pudo leer configuración de BD: {e}")
                
        return config

    async def upload_file(
        self,
        conn,
        file: UploadFile,
        folder_path: str,
        metadata: Optional[dict] = None,
        *,
        _config: Optional[dict] = None,
    ) -> Dict:
        if not self.access_token:
            raise ValueError("Requiere token de acceso")

        config = _config if _config is not None else await self._resolve_config(conn)
        site_id = config.get("site_id")
        drive_id = config.get("drive_id")

        # 1. Preparar archivo (Bypass async wrapper issue)
        filename = file.filename
        file.file.seek(0, 2)
        file_size = file.file.tell()
        file.file.seek(0)
        
        # Sanitizar ruta y nombre
        safe_filename = self._sanitize_filename(filename)
        # Codificar ruta para URL
        folder_path = folder_path.strip("/")
        encoded_path = urllib.parse.quote(f"{folder_path}/{safe_filename}")
        
        # Determinar Endpoint
        if drive_id:
            base_endpoint = f"/drives/{drive_id}/root:/{encoded_path}"
        elif site_id:
            base_endpoint = f"/sites/{site_id}/drive/root:/{encoded_path}"
        else:
            # Fallback a la unidad personal del usuario
            base_endpoint = f"/me/drive/root:/{encoded_path}"
            logger.warning("No se configuró SITE_ID ni DRIVE_ID. Subiendo a OneDrive personal del usuario.")

        logger.info(f"Subiendo archivo {safe_filename} ({file_size} bytes) a {base_endpoint}")
        
        # 2. Upload Strategy
        SESSION_THRESHOLD = 4 * 1024 * 1024 # 4 MB
        
        if file_size < SESSION_THRESHOLD:
            return await self._upload_small_file(base_endpoint, file, file_size)
        else:
            return await self._upload_large_file(base_endpoint, file, file_size)

    async def _upload_small_file(self, endpoint: str, file: UploadFile, size: int) -> dict:
        """Carga directa para archivos pequeños."""
        url = f"{self.BASE_URL}{endpoint}:/content?@microsoft.graph.conflictBehavior=replace"
        
        # Leer contenido (FastAPI UploadFile read is async safe)
        content = await file.read()
        await file.seek(0) # Reset
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.put(
                url, 
                headers=self._get_headers(), 
                content=content
            )
            
            if resp.status_code not in (200, 201):
                logger.error(f"Error subiendo archivo pequeño: {resp.text}")
                resp.raise_for_status()
                
            data = resp.json()
            return {
                "id": data.get("id"),
                "webUrl": data.get("webUrl"),
                "name": data.get("name"),
                "size": data.get("size"),
                "parentReference": data.get("parentReference", {}) 
            }

    async def _upload_large_file(self, endpoint: str, file: UploadFile, size: int) -> dict:
        """Carga con sesión para archivos grandes."""
        # 1. Crear sesión de upload
        action_url = f"{self.BASE_URL}{endpoint}:/createUploadSession"
        
        session_payload = {
            "item": {
                "@microsoft.graph.conflictBehavior": "replace",
                "name": self._sanitize_filename(file.filename)
            }
        }
        
        # Timeout 60s para creación de sesión
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                action_url,
                headers=self._get_headers(),
                json=session_payload
            )
            
            if resp.status_code != 200:
                logger.error(f"Error creando sesión upload: {resp.text}")
                resp.raise_for_status()
                
            upload_url = resp.json().get("uploadUrl")
            if not upload_url:
                raise RuntimeError("No se obtuvo uploadUrl de Graph API")
            
            # 2. Subir por chunks
            # Graph recomienda 320 KiB * N. Usaremos 320 KB * 10 = ~3.2 MB chunks
            CHUNK_SIZE = 327680 * 10 
            
            bytes_sent = 0
            logger.info(f"Iniciando subida por chunks. Total: {size} bytes. Chunk size: {CHUNK_SIZE}")
            
            # Usar cliente con timeout largo para los chunks (30s connect, 300s read/write)
            timeout = httpx.Timeout(300.0, connect=30.0)
            
            async with httpx.AsyncClient(timeout=timeout) as chunk_client:
                while bytes_sent < size:
                    chunk = await file.read(CHUNK_SIZE)
                    chunk_len = len(chunk)
                    if not chunk:
                        break
                        
                    # Rango de bytes: bytes start-end/total
                    range_header = f"bytes {bytes_sent}-{bytes_sent + chunk_len - 1}/{size}"
                    
                    # Headers específicos para el chunk (no auth, va en URL)
                    chunk_headers = {
                        "Content-Length": str(chunk_len),
                        "Content-Range": range_header
                    }
                    
                    try:
                        put_resp = await chunk_client.put(
                            upload_url,
                            headers=chunk_headers,
                            content=chunk
                        )
                        
                        if put_resp.status_code not in (200, 201, 202):
                            logger.error(f"Error subiendo chunk {range_header}: {put_resp.text}")
                            raise RuntimeError(f"Fallo en chunk upload: {put_resp.status_code}")
                        
                        bytes_sent += chunk_len
                        # logger.info(f"Chunk subido: {range_header}") # Verbose
                        
                        # Si terminó (201/200), retornar resultado
                        if put_resp.status_code in (200, 201):
                            data = put_resp.json()
                            await file.seek(0) # Reset porsiacaso
                            logger.info(f"Subida completada exitosamente: {data.get('name')}")
                            return {
                                "id": data.get("id"),
                                "webUrl": data.get("webUrl"),
                                "name": data.get("name"),
                                "size": data.get("size"),
                                "parentReference": data.get("parentReference", {}) 
                            }
                            
                    except (httpx.HTTPError, OSError, RuntimeError, ValueError) as e:
                        logger.error(f"Excepción subiendo chunk {range_header}: {e}")
                        raise

            # Si llegamos aquí sin retorno final
            raise RuntimeError("Upload finalizado pero no se recibió confirmación 200/201")
    
    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        """Limpia caracteres inválidos para SharePoint."""
        # Caracteres no permitidos en SharePoint: " * : < > ? / \ |
        invalid_chars = r'["*:<>?/\\|]'
        clean = urllib.parse.unquote(filename) # Decodificar primero
        clean = re.sub(invalid_chars, '_', clean)
        return clean

    async def upload_bytes_direct(
        self,
        content: bytes,
        filename: str,
        folder_path: str,
    ) -> dict:
        """
        Sube bytes crudos a SharePoint usando self.drive_id / self.site_id ya resueltos.
        No requiere conn — resolver config antes con _resolve_config() y asignar a self.
        """
        safe_filename = self._sanitize_filename(filename)
        path = folder_path.strip("/")
        encoded = urllib.parse.quote(f"{path}/{safe_filename}")

        if self.drive_id:
            url = f"{self.BASE_URL}/drives/{self.drive_id}/root:/{encoded}:/content"
        elif self.site_id:
            url = f"{self.BASE_URL}/sites/{self.site_id}/drive/root:/{encoded}:/content"
        else:
            raise ValueError("drive_id o site_id requerido — llamar _resolve_config primero")

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/octet-stream",
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.put(url, headers=headers, content=content)
            if resp.status_code not in (200, 201):
                raise RuntimeError(f"Error subiendo {safe_filename}: HTTP {resp.status_code} - {resp.text[:200]}")
            data = resp.json()
            return {"id": data.get("id"), "webUrl": data.get("webUrl"), "name": data.get("name")}

    async def get_folder_web_url(self, folder_path: str) -> str:
        """
        Obtiene el webUrl de una carpeta en SharePoint.
        Retorna cadena vacia si no existe o hay error.
        No requiere conn — usar self.drive_id / self.site_id ya resueltos.
        """
        path = folder_path.strip("/")
        encoded = urllib.parse.quote(path)

        if not self.drive_id and not self.site_id:
            return ""
        base = self._drive_base_url(self.drive_id, self.site_id)
        url = f"{base}/root:/{encoded}"

        headers = {"Authorization": f"Bearer {self.access_token}"}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                return resp.json().get("webUrl", "")
            return ""

    async def list_folder_children(
        self,
        drive_id: str,
        site_id: str,
        folder_id: str | None = None,
    ) -> list[dict]:
        """
        Lista las subcarpetas directas de una carpeta en SharePoint (o de la
        raíz si folder_id es None). Delega en `_list_children_paginated` para
        heredar paginación de @odata.nextLink y reintento en 429 — mismo Graph
        endpoint que usa el resolver automático, misma garantía de fiabilidad.
        Retorna lista de {id, name, webUrl}.
        """
        return await self._list_children_paginated(drive_id, site_id, folder_id=folder_id)

    @staticmethod
    def _normalize_folder_name(value: str) -> str:
        """Trim, colapsa espacios múltiples, lowercase y quita acentos."""
        value = unicodedata.normalize("NFKD", value)
        value = "".join(c for c in value if not unicodedata.combining(c))
        return re.sub(r"\s+", " ", value.strip().lower())

    async def _get_with_429_retry(self, client: httpx.AsyncClient, url: str, headers: dict) -> httpx.Response:
        """GET con reintento y backoff en HTTP 429, respetando Retry-After."""
        for attempt in range(_MAX_429_RETRIES + 1):
            resp = await client.get(url, headers=headers)
            if resp.status_code != 429:
                return resp
            if attempt == _MAX_429_RETRIES:
                return resp
            try:
                retry_after = float(resp.headers.get("Retry-After", "1"))
            except ValueError:
                retry_after = 1.0
            retry_after = min(retry_after, _MAX_429_BACKOFF_SECONDS)
            logger.warning(
                "Graph 429 en %s, reintentando en %.1fs (intento %d/%d)",
                url, retry_after, attempt + 1, _MAX_429_RETRIES,
            )
            await asyncio.sleep(retry_after)
        return resp

    def _drive_base_url(self, drive_id: str, site_id: str, context: str = "") -> str:
        """Resuelve el endpoint base drives/{id} o sites/{id}/drive. Nunca ambos vacios."""
        if drive_id:
            return f"{self.BASE_URL}/drives/{drive_id}"
        if site_id:
            return f"{self.BASE_URL}/sites/{site_id}/drive"
        suffix = f" {context}" if context else ""
        raise ValueError(f"drive_id o site_id requerido{suffix}")

    async def _list_children_paginated(
        self, drive_id: str, site_id: str, folder_id: str | None = None
    ) -> list[dict]:
        """
        Lista las carpetas hijas de `folder_id` (o de la raíz del drive si es
        None), paginando @odata.nextLink con reintento en 429. Retorna lista de
        {id, name, webUrl}.

        Levanta RuntimeError si excede el timeout, en vez de dejar la búsqueda
        colgada hasta que gunicorn mate el worker. Antes esto retornaba [] en
        silencio, lo que el resolver automático interpretaba como "no existe
        carpeta" (SIN_MATCH) cuando en realidad fue un timeout/throttling
        transitorio de Graph — el caller (router) ya mapea RuntimeError a 503.
        """
        base = self._drive_base_url(drive_id, site_id, context="para listar carpetas")
        children_path = f"/items/{folder_id}/children" if folder_id else "/root/children"
        first_url = base + children_path + "?$select=id,name,folder,webUrl&$filter=folder ne null&$orderby=name asc&$top=200"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        folders: list[dict] = []

        async def _fetch_all() -> None:
            next_url = first_url
            async with httpx.AsyncClient(timeout=30.0) as client:
                while next_url:
                    resp = await self._get_with_429_retry(client, next_url, headers)
                    if resp.status_code != 200:
                        logger.error("Error listando carpetas SP: %s %s", resp.status_code, resp.text[:200])
                        resp.raise_for_status()
                    data = resp.json()
                    folders.extend(
                        {"id": item["id"], "name": item["name"], "webUrl": item.get("webUrl", "")}
                        for item in data.get("value", [])
                        if "folder" in item
                    )
                    next_url = data.get("@odata.nextLink")

        try:
            await asyncio.wait_for(_fetch_all(), timeout=_ROOT_LIST_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            logger.error("Timeout listando raíz de SharePoint (drive_id=%s, site_id=%s)", drive_id, site_id)
            raise RuntimeError("Tiempo de espera agotado al listar carpetas de SharePoint")

        return folders

    def _match_folders(self, folders: list[dict], query: str) -> list[dict]:
        """
        Compara `query` contra una lista de carpetas ya listada (pura, sin I/O).
        Tolera typos/espacios de más: normaliza ambos lados y compara con
        difflib.SequenceMatcher.ratio(). Retorna candidatos con score >= umbral,
        ordenados por score descendente. Cada item: {id, name, webUrl, score}.
        """
        if not query or not query.strip():
            return []

        normalized_query = self._normalize_folder_name(query)
        matches = []
        for folder in folders:
            score = difflib.SequenceMatcher(
                None, normalized_query, self._normalize_folder_name(folder["name"])
            ).ratio()
            if score >= _FOLDER_MATCH_THRESHOLD:
                matches.append({**folder, "score": score})

        matches.sort(key=lambda m: m["score"], reverse=True)
        return matches

    def _match_by_anchor(self, folders: list[dict], ancla: str) -> list[dict]:
        """
        Matching por prefijo del ancla `{prefijo}-{consecutivo}` (ej. "MX-50158"),
        mucho más fuerte que el fuzzy score contra el nombre completo: el
        consecutivo es único en todo el sistema, así que una carpeta cuyo nombre
        normalizado EMPIEZA con este ancla es una coincidencia de alta confianza.
        Tolera que la carpeta real use espacio en vez de guion despues del
        consecutivo (ej. "MX-50158 FV VOESTALPINE" en vez de "MX-50158-FV..."),
        normalizando guiones a espacios en ambos lados antes de comparar.
        Se prioriza sobre el fuzzy matching general (_match_folders), que puede
        producir ambigüedad falsa entre proyectos con nombres descriptivos
        parecidos (ej. mismo cliente/tecnologia en varios proyectos).
        """
        ancla_norm = re.sub(r"\s+", " ", self._normalize_folder_name(ancla).replace("-", " ")).strip()
        if not ancla_norm:
            return []
        pattern = re.compile(r"^" + re.escape(ancla_norm) + r"(?!\d)")

        matches = []
        for folder in folders:
            name_norm = re.sub(r"\s+", " ", self._normalize_folder_name(folder["name"]).replace("-", " ")).strip()
            if pattern.match(name_norm):
                matches.append(folder)
        return matches

    async def resolver_carpeta_con_fallback(
        self, drive_id: str, site_id: str, queries: list[str], carpeta_sin_expediente: str, ancla: str = ""
    ) -> tuple[list[dict], Optional[dict]]:
        """
        Lista la raíz UNA sola vez. Separa la carpeta administrativa de fallback
        (comparación EXACTA normalizada, nunca fuzzy) del resto antes de buscar
        — así nunca compite como falso positivo contra el nombre de un proyecto
        real (ej. un proyecto seed con nombre corto que cruza el umbral de
        similitud contra "Proyectos sin expediente").
        Si `ancla` viene presente (ej. "MX-50158"), se confía EXCLUSIVAMENTE en
        el match por prefijo — encuentre o no encuentre nada. El consecutivo es
        único en todo el sistema, así que la ausencia de match por ancla es en
        sí misma una señal fuerte de que no existe carpeta real: caer al fuzzy
        de `queries` (nombre_proyecto/nombre_corto, strings genéricos) en ese
        caso puede producir un falso MAPEADO contra una carpeta real no
        relacionada — y ese mapeo se persiste solo. El fuzzy de `queries` solo
        se usa cuando no hay ancla extraíble (proyecto_id_estandar no sigue el
        patrón `{prefijo}-{consecutivo}`, caso legado).
        Retorna (matches_del_proyecto, carpeta_fallback_o_None).
        """
        folders = await self._list_children_paginated(drive_id, site_id)
        normalized_fallback = self._normalize_folder_name(carpeta_sin_expediente)
        fallback = next(
            (f for f in folders if self._normalize_folder_name(f["name"]) == normalized_fallback),
            None,
        )
        if fallback is None:
            # La carpeta de fallback se identifica por nombre exacto normalizado, no por
            # id fijo. Si alguien la renombra en SharePoint (o el config drifted), esto
            # deja de encontrarla en silencio y, peor, la reintroduce sin querer en el
            # pool de candidatos del fuzzy matching -- log para poder detectarlo.
            logger.warning(
                "Carpeta de fallback '%s' no encontrada en la raíz del drive (drive_id=%s, site_id=%s) "
                "— revisar si fue renombrada en SharePoint o si SP_VISITAS_CARPETA_SIN_EXPEDIENTE quedó desactualizado.",
                carpeta_sin_expediente, drive_id, site_id,
            )
        candidatos = [f for f in folders if f is not fallback]

        if ancla:
            return self._match_by_anchor(candidatos, ancla), fallback

        for query in queries:
            matches = self._match_folders(candidatos, query)
            if matches:
                return matches, fallback
        return [], fallback

    async def get_item_web_url(self, drive_id: str, site_id: str, item_id: str) -> str:
        """Obtiene el webUrl canonico de un item por su id (no confia en valores del cliente)."""
        base = self._drive_base_url(drive_id, site_id)
        url = f"{base}/items/{item_id}?$select=webUrl"

        headers = {"Authorization": f"Bearer {self.access_token}"}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                logger.warning("No se pudo obtener webUrl item_id=%s: %s", item_id, resp.status_code)
                return ""
            return resp.json().get("webUrl", "")

    async def rename_folder(self, drive_id: str, site_id: str, folder_id: str, new_name: str) -> dict:
        """
        Renombra una carpeta por su item_id. El item_id no cambia con el rename,
        así que cualquier mapeo persistido por folder_id sigue siendo válido.
        """
        base = self._drive_base_url(drive_id, site_id, context="para renombrar carpeta")
        url = f"{base}/items/{folder_id}"
        safe_new_name = self._sanitize_filename(new_name)

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.patch(url, headers=headers, json={"name": safe_new_name})
            if resp.status_code != 200:
                logger.error("Error renombrando carpeta SP item_id=%s: %s %s", folder_id, resp.status_code, resp.text[:200])
                resp.raise_for_status()
            data = resp.json()
            return {"id": data.get("id"), "name": data.get("name"), "webUrl": data.get("webUrl")}

    async def upload_bytes_to_folder_id(
        self,
        content: bytes,
        filename: str,
        folder_id: str,
        drive_id: str,
        site_id: str,
    ) -> dict:
        """
        Sube bytes a una carpeta identificada por su folder_id (no por ruta).
        Usa conflictBehavior=rename para evitar colisiones.
        """
        safe_filename = self._sanitize_filename(filename)
        encoded = urllib.parse.quote(safe_filename)

        if drive_id:
            url = f"{self.BASE_URL}/drives/{drive_id}/items/{folder_id}:/{encoded}:/content"
        elif site_id:
            url = f"{self.BASE_URL}/sites/{site_id}/drive/items/{folder_id}:/{encoded}:/content"
        else:
            raise ValueError("drive_id o site_id requerido")

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/octet-stream",
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.put(url, headers=headers, content=content)
            if resp.status_code not in (200, 201):
                raise RuntimeError(f"Error subiendo {safe_filename}: HTTP {resp.status_code} - {resp.text[:200]}")
            data = resp.json()
            return {"id": data.get("id"), "webUrl": data.get("webUrl"), "name": data.get("name")}

    async def _fetch_item_bytes(self, drive_item_id: str, drive_id: str | None, site_id: str | None) -> bytes:
        if drive_id:
            url = f"{self.BASE_URL}/drives/{drive_id}/items/{drive_item_id}/content"
        elif site_id:
            url = f"{self.BASE_URL}/sites/{site_id}/drive/items/{drive_item_id}/content"
        else:
            raise ValueError("drive_id o site_id requerido en SharePointService")
        headers = {"Authorization": f"Bearer {self.access_token}"}
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.content

    async def download_file_by_item_id(self, conn, drive_item_id: str) -> bytes:
        """Descarga el contenido de un archivo por su drive_item_id vía Graph API."""
        config = await self._resolve_config(conn)
        return await self._fetch_item_bytes(drive_item_id, config.get("drive_id"), config.get("site_id"))

    async def delete_file_by_item_id(
        self, conn, drive_item_id: str, *, _config: Optional[dict] = None
    ) -> bool:
        """Borra un archivo por drive_item_id. Retorna True si se borro o ya no existia."""
        config = _config if _config is not None else await self._resolve_config(conn)
        drive_id = config.get("drive_id")
        site_id = config.get("site_id")
        if drive_id:
            url = f"{self.BASE_URL}/drives/{drive_id}/items/{drive_item_id}"
        elif site_id:
            url = f"{self.BASE_URL}/sites/{site_id}/drive/items/{drive_item_id}"
        else:
            raise ValueError("drive_id o site_id requerido en SharePointService")

        headers = {"Authorization": f"Bearer {self.access_token}"}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.delete(url, headers=headers)
            if resp.status_code in (204, 404):
                return True
            logger.warning(
                "Error borrando archivo SP item_id=%s: %s %s",
                drive_item_id,
                resp.status_code,
                resp.text[:200],
            )
            return False

    async def download_bytes_direct_by_item_id(self, drive_item_id: str) -> bytes:
        """Descarga por item_id usando self.drive_id / self.site_id ya resueltos (sin conn)."""
        return await self._fetch_item_bytes(drive_item_id, self.drive_id, self.site_id)

    async def download_file_by_path(self, relative_path: str) -> bytes:
        """
        Descarga un archivo por ruta relativa dentro del drive configurado.
        Requiere self.site_id o self.drive_id ya asignados.
        relative_path: ruta relativa desde la raiz, ej: 'FIEL/ISA/fiel.cer'
        """
        encoded = urllib.parse.quote(relative_path.strip("/"))
        if self.drive_id:
            url = f"{self.BASE_URL}/drives/{self.drive_id}/root:/{encoded}:/content"
        elif self.site_id:
            url = f"{self.BASE_URL}/sites/{self.site_id}/drive/root:/{encoded}:/content"
        else:
            raise ValueError("drive_id o site_id requerido en SharePointService")

        headers = {"Authorization": f"Bearer {self.access_token}"}
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 404:
                raise ValueError(f"Archivo no encontrado en SharePoint: {relative_path}")
            resp.raise_for_status()
            return resp.content


def get_sharepoint_service(access_token: str = None):
    return SharePointService(access_token)
