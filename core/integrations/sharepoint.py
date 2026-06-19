import logging
import re
from typing import Optional, Dict
import asyncpg
import httpx
import urllib.parse
from fastapi import UploadFile

from core.microsoft import get_ms_auth
from core.config import settings
from core.integrations.db_service import get_integrations_db_service

logger = logging.getLogger("SharePointService")

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

        if self.drive_id:
            url = f"{self.BASE_URL}/drives/{self.drive_id}/root:/{encoded}"
        elif self.site_id:
            url = f"{self.BASE_URL}/sites/{self.site_id}/drive/root:/{encoded}"
        else:
            return ""

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
        Lista las subcarpetas directas de una carpeta en SharePoint.
        Si folder_id es None lista la raíz del drive.
        Retorna lista de {id, name}.
        """
        if drive_id:
            base = f"{self.BASE_URL}/drives/{drive_id}"
        elif site_id:
            base = f"{self.BASE_URL}/sites/{site_id}/drive"
        else:
            raise ValueError("drive_id o site_id requerido para listar carpetas")

        if folder_id:
            url = f"{base}/items/{folder_id}/children"
        else:
            url = f"{base}/root/children"

        url += "?$select=id,name,folder&$filter=folder ne null&$orderby=name asc&$top=200"

        headers = {"Authorization": f"Bearer {self.access_token}"}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                logger.error("Error listando carpetas SP: %s %s", resp.status_code, resp.text[:200])
                resp.raise_for_status()
            data = resp.json()
            return [
                {"id": item["id"], "name": item["name"]}
                for item in data.get("value", [])
                if "folder" in item
            ]

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
