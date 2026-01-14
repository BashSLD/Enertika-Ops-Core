import logging
from typing import Optional, Dict
from uuid import UUID
import httpx
from datetime import datetime
import os
import urllib.parse
from fastapi import UploadFile

from core.microsoft import get_ms_auth
from core.config import settings

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
                db_config = await conn.fetch("""
                    SELECT clave, valor FROM tb_configuracion_global 
                    WHERE clave IN ('SHAREPOINT_SITE_ID', 'SHAREPOINT_DRIVE_ID')
                """)
                for row in db_config:
                    if row['valor'] and row['valor'].strip():
                        if row['clave'] == 'SHAREPOINT_SITE_ID':
                            config['site_id'] = row['valor'].strip()
                        elif row['clave'] == 'SHAREPOINT_DRIVE_ID':
                            config['drive_id'] = row['valor'].strip()
            except Exception as e:
                logger.warning(f"No se pudo leer configuración de BD: {e}")
                
        return config

    async def upload_file(
        self, 
        conn,
        file: UploadFile, 
        folder_path: str,
        metadata: Optional[dict] = None
    ) -> Dict:
        """
        Sube un archivo a SharePoint en la ruta especificada.
        
        Args:
            conn: Conexión a BD para leer configuración
            file: Archivo UploadFile de FastAPI
            folder_path: Ruta relativa
            metadata: Metadata extra
        """
        if not self.access_token:
            raise ValueError("Requiere token de acceso")

        # Resolving Config
        config = await self._resolve_config(conn)
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
        url = f"{self.BASE_URL}{endpoint}:/content"
        
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
                "@microsoft.graph.conflictBehavior": "rename",
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
                raise Exception("No se obtuvo uploadUrl de Graph API")
            
            # 2. Subir por chunks
            # Graph recomienda 320 KiB * N. Usaremos 320 KB * 10 = ~3.2 MB chunks
            CHUNK_SIZE = 327680 * 10 
            await file.seek(0)
            
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
                            raise Exception(f"Fallo en chunk upload: {put_resp.status_code}")
                        
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
                            
                    except Exception as e:
                        logger.error(f"Excepción subiendo chunk {range_header}: {e}")
                        raise

            # Si llegamos aquí sin retorno final
            raise Exception("Upload finalizado pero no se recibió confirmación 200/201")
    
    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        """Limpia caracteres inválidos para SharePoint."""
        # Caracteres no permitidos en SharePoint: " * : < > ? / \ |
        invalid_chars = r'["*:<>?/\\|]'
        clean = urllib.parse.unquote(filename) # Decodificar primero
        import re
        clean = re.sub(invalid_chars, '_', clean)
        return clean

def get_sharepoint_service(access_token: str = None):
    return SharePointService(access_token)
