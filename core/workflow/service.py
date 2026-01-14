from uuid import UUID, uuid4
from datetime import datetime
from typing import List, Optional
import logging
from zoneinfo import ZoneInfo
from fastapi.templating import Jinja2Templates
from fastapi import HTTPException, UploadFile

# Imports Core
from core.microsoft import MicrosoftAuth
from .notification_service import get_notification_service

logger = logging.getLogger("WorkflowCore")
templates = Jinja2Templates(directory="templates")

from core.integrations.sharepoint import get_sharepoint_service, SharePointService

class WorkflowService:
    """
    Servicio Centralizado para gestion de flujo de trabajo y comunicaciones.
    Usado por: Simulacion, Comercial, Ingenieria, etc.
    """
    
    def __init__(self):
        self.ms_auth = MicrosoftAuth()
        self.notification_service = get_notification_service()

    async def add_comentario(
        self, 
        conn, 
        user_context: dict, 
        id_oportunidad: UUID, 
        comentario: str, 
        departamento_slug: str,
        modulo_origen: str,
        file_uploads: List[UploadFile] = [],
        sharepoint_token: Optional[str] = None
    ) -> dict:
        """
        1. Inserta comentario en BD.
        2. Determina destinatarios inteligentes.
        3. Envia notificacion por correo.
        
        Args:
            conn: Conexion a la base de datos
            user_context: Contexto del usuario actual
            id_oportunidad: UUID de la oportunidad
            comentario: Texto del comentario
            departamento_slug: Slug del departamento (ej: 'SIMULACION', 'COMERCIAL')
            modulo_origen: Modulo desde donde se crea (ej: 'simulacion', 'comercial')
            file_uploads: Lista de archivos adjuntos
            sharepoint_token: Token de acceso a Graph API
            
        Returns:
            dict con datos del comentario creado
        """
        user_id = user_context.get("user_db_id")
        user_name = user_context.get("user_name", "Usuario Sistema")
        user_email = user_context.get("user_email") or user_context.get("email")
        
        # Validación: Si estamos aquí, el usuario DEBE estar autenticado y tener email
        if not user_email:
            logger.error(f"[COMENTARIO] Usuario sin email en contexto: {user_context}")
            raise HTTPException(
                status_code=500,
                detail="Error de sesión: no se pudo obtener el email del usuario. Por favor, cierre sesión y vuelva a iniciar."
            )
        
        logger.info(f"[COMENTARIO] Iniciando add_comentario para {id_oportunidad} por {user_name}")

        # 1. Insertar en BD
        new_id = uuid4()
        now_mx = datetime.now(ZoneInfo("America/Mexico_City"))
        
        query = """
            INSERT INTO tb_comentarios_workflow (
                id, id_oportunidad, usuario_id, usuario_nombre, usuario_email,
                comentario, departamento_origen, modulo_origen, fecha_comentario
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id
        """
        
        logger.info(f"[COMENTARIO] Ejecutando INSERT con ID {new_id}")
        await conn.execute(
            query, 
            new_id, id_oportunidad, user_id, user_name, user_email,
            comentario, departamento_slug, modulo_origen, now_mx
        )
        logger.info(f"[COMENTARIO] INSERT exitoso para {new_id}")
        
        # 1.5 Procesar Adjuntos (SharePoint) - Múltiples Archivos
        attachments_data = [] # Lista de metadatos de adjuntos
        if file_uploads and sharepoint_token:
            logger.info(f"[COMENTARIO] Procesando {len(file_uploads)} adjuntos.")
            
            try:
                # 1.5.1 Cargar configuración una sola vez
                max_size_mb = 500 # Default
                config_rows = await conn.fetch("""
                    SELECT clave, valor FROM tb_configuracion_global 
                    WHERE clave IN ('MAX_UPLOAD_SIZE_MB', 'SHAREPOINT_BASE_FOLDER')
                """)
                config_map = {row['clave']: row['valor'] for row in config_rows}
                
                max_size_mb = int(config_map.get('MAX_UPLOAD_SIZE_MB', '500'))
                base_folder = config_map.get('SHAREPOINT_BASE_FOLDER', '').strip().strip("/")
                
                # Obtener ID estándar para la carpeta
                op_estandar = await conn.fetchval(
                    "SELECT op_id_estandar FROM tb_oportunidades WHERE id_oportunidad = $1",
                    id_oportunidad
                )
                
                if not op_estandar:
                    logger.warning(f"[COMENTARIO] No se pudo subir adjunto: op_id_estandar es NULL para {id_oportunidad}")
                else:
                    # Construir Ruta Base
                    relative_path = f"comentario/{op_estandar}"
                    folder_path = f"{base_folder}/{relative_path}" if base_folder else relative_path
                    
                    # Usamos TOKEN DE APLICACIÓN para garantizar acceso a la carpeta del sistema
                    # independientemente de los permisos individuales del usuario en SharePoint
                    app_token = self.ms_auth.get_application_token()
                    sharepoint = SharePointService(access_token=app_token)

                    # Iterar sobre cada archivo
                    import time
                    for f_obj in file_uploads:
                        try:
                            # Validar Tamaño (Bypass async wrapper issue)
                            f_obj.file.seek(0, 2)
                            f_size = f_obj.file.tell()
                            f_obj.file.seek(0)
                            
                            file_size_mb = f_size / (1024 * 1024)
                            if file_size_mb > max_size_mb:
                                logger.warning(f"[COMENTARIO] Archivo {f_obj.filename} excede limite: {f_size} bytes")
                                continue 
                            
                            # Generar nombre único para evitar colisiones
                            timestamp = int(time.time())
                            original_name = f_obj.filename
                            f_obj.filename = f"{timestamp}_{original_name}"
                            
                            logger.info(f"[COMENTARIO] Subiendo archivo: {f_obj.filename} a {folder_path}")

                            # Subir a SharePoint
                            upload_result = await sharepoint.upload_file(
                                conn, 
                                f_obj, 
                                folder_path
                            )
                            
                            # Registrar en BD
                            doc_id = uuid4()
                            parent_ref = upload_result.get('parentReference', {})
                            
                            await conn.execute("""
                                INSERT INTO tb_documentos_attachments (
                                    id_documento, nombre_archivo, url_sharepoint, drive_item_id, parent_drive_id,
                                    tipo_contenido, tamano_bytes, id_comentario, id_oportunidad, subido_por_id,
                                    origen_slug, activo
                                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 'comentario', TRUE)
                            """, 
                                doc_id, 
                                upload_result['name'],
                                upload_result['webUrl'],
                                upload_result['id'],
                                parent_ref.get('driveId'),
                                f_obj.content_type,
                                upload_result['size'],
                                new_id,
                                id_oportunidad,
                                user_id
                            )
                            
                            attachments_data.append({
                                "nombre": upload_result['name'],
                                "url": upload_result['webUrl']
                            })
                            logger.info(f"[COMENTARIO] Adjunto registrado: {upload_result['name']}")
                            
                        except Exception as e_file:
                             logger.error(f"[COMENTARIO] Error subiendo archivo individual {f_obj.filename}: {e_file}")
                             # Continuar con el siguiente archivo
                             
            except Exception as e:
                logger.error(f"[COMENTARIO] Fallo general en proceso de adjuntos: {e}")
                
        # 2. Notificacion Asincrona
        try:
            await self._notificar_comentario(conn, id_oportunidad, comentario, user_context, departamento_slug)
        except Exception as e:
            logger.error(f"Fallo al enviar notificacion de comentario: {e}")
            
        return {
            "id": new_id,
            "usuario_nombre": user_name,
            "comentario": comentario,
            "fecha": now_mx,
            "departamento": departamento_slug,
            "adjuntos": attachments_data # Return list instead of single obj
        }

    async def get_historial(
        self, 
        conn, 
        id_oportunidad: UUID, 
        limit: Optional[int] = None
    ) -> List[dict]:
        """
        Obtiene historial unificado de comentarios para el Muro.
        Agrupa adjuntos por comentario.
        """
        query = """
            SELECT 
                c.id, c.usuario_nombre, c.usuario_email, c.comentario, 
                c.departamento_origen, c.modulo_origen, c.fecha_comentario,
                d.nombre_archivo as adjunto_nombre,
                d.url_sharepoint as adjunto_url
            FROM tb_comentarios_workflow c
            LEFT JOIN tb_documentos_attachments d ON c.id = d.id_comentario
            WHERE c.id_oportunidad = $1 AND (d.id_documento IS NULL OR d.activo = TRUE)
            ORDER BY c.fecha_comentario DESC
        """
        if limit:
            query += f" LIMIT {limit}"
            
        rows = await conn.fetch(query, id_oportunidad)
        
        # Agrupar por Comentario ID
        grouped = {}
        order = [] # Para mantener orden cronologico
        
        for r in rows:
            cid = r['id']
            if cid not in grouped:
                grouped[cid] = {
                    "id": cid,
                    "usuario_nombre": r['usuario_nombre'],
                    "usuario_email": r['usuario_email'],
                    "comentario": r['comentario'],
                    "departamento_origen": r['departamento_origen'],
                    "modulo_origen": r['modulo_origen'],
                    "fecha_comentario": r['fecha_comentario'],
                    "adjuntos": []
                }
                order.append(cid)
            
            if r['adjunto_url']:
                grouped[cid]['adjuntos'].append({
                    "nombre": r['adjunto_nombre'],
                    "url": r['adjunto_url']
                })
        
        return [grouped[cid] for cid in order]

    # --- LOGICA DE NOTIFICACION INTELIGENTE ---
    
    async def _notificar_comentario(
        self, 
        conn, 
        id_oportunidad: UUID, 
        comentario: str, 
        sender_ctx: dict, 
        depto: str
    ):
        """
        Delega notificación de comentario a NotificationService.
        
        Args:
            conn: Conexión a base de datos
            id_oportunidad: UUID de la oportunidad
            comentario: Texto del comentario
            sender_ctx: Contexto del usuario que comentó
            depto: Slug del departamento/módulo origen
        """
        await self.notification_service.notify_new_comment(
            conn=conn,
            id_oportunidad=id_oportunidad,
            comentario=comentario,
            sender_ctx=sender_ctx,
            departamento=depto.upper()
        )


def get_workflow_service():
    """Helper para inyeccion de dependencias."""
    return WorkflowService()
