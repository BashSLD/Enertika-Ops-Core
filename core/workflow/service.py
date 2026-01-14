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

from core.integrations.sharepoint import get_sharepoint_service

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
        # So I might need to pass the access_token explicitly to add_comentario.
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
            
        Returns:
            dict con datos del comentario creado
        """
        # ... implementation ...

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
        
        # 1.5 Procesar Adjunto (SharePoint)
        attachment_data = None
        if file_upload and sharepoint_token:
            try:
                # Obtener ID estándar para la carpeta
                op_estandar = await conn.fetchval(
                    "SELECT op_id_estandar FROM tb_oportunidades WHERE id_oportunidad = $1",
                    id_oportunidad
                )
                if op_estandar:
                    sp_service = get_sharepoint_service(sharepoint_token)
                    folder_path = f"Proyectos/{op_estandar}/Comentarios"
                    
                    # Upload
                    upload_result = await sp_service.upload_file(file_upload, folder_path)
                    
                    # Guardar Metadata en tb_documentos
                    doc_id = uuid4()
                    await conn.execute("""
                        INSERT INTO tb_documentos (
                            id_documento, nombre_archivo, url_sharepoint, drive_item_id,
                            tipo_contenido, tamano_bytes, id_comentario, id_oportunidad, subido_por_id
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    """, 
                        doc_id, 
                        upload_result['name'],
                        upload_result['webUrl'],
                        upload_result['id'],
                        file_upload.content_type,
                        upload_result['size'],
                        new_id,
                        id_oportunidad,
                        user_id
                    )
                    
                    attachment_data = {
                        "nombre": upload_result['name'],
                        "url": upload_result['webUrl']
                    }
                    logger.info(f"[COMENTARIO] Adjunto subido: {upload_result['name']}")
                    
            except Exception as e:
                logger.error(f"[COMENTARIO] Fallo subida de adjunto: {e}")
                # No fallamos todo el comentario, pero logueamos error
                # Podríamos agregar una alerta al usuario, pero por ahora seguimos.

        # 2. Notificacion Asincrona (Fire & Forget logic)
        try:
            await self._notificar_comentario(conn, id_oportunidad, comentario, user_context, departamento_slug)
        except Exception as e:
            logger.error(f"Fallo al enviar notificacion de comentario: {e}")
            # No bloqueamos el flujo si falla el correo
            
        return {
            "id": new_id,
            "usuario_nombre": user_name,
            "comentario": comentario,
            "fecha": now_mx,
            "departamento": departamento_slug,
            "adjunto": attachment_data
        }

    async def get_historial(
        self, 
        conn, 
        id_oportunidad: UUID, 
        limit: Optional[int] = None
    ) -> List[dict]:
        """
        Obtiene historial unificado de comentarios para el Muro.
        
        Args:
            conn: Conexion a la base de datos
            id_oportunidad: UUID de la oportunidad
            limit: Limite opcional de resultados
            
        Returns:
            Lista de diccionarios con comentarios ordenados por fecha (mas reciente primero)
        """
        query = """
            SELECT 
                c.id, c.usuario_nombre, c.usuario_email, c.comentario, 
                c.departamento_origen, c.modulo_origen, c.fecha_comentario,
                d.nombre_archivo as adjunto_nombre,
                d.url_sharepoint as adjunto_url
            FROM tb_comentarios_workflow c
            LEFT JOIN tb_documentos d ON c.id = d.id_comentario
            WHERE c.id_oportunidad = $1
            ORDER BY c.fecha_comentario DESC
        """
        if limit:
            query += f" LIMIT {limit}"
            
        rows = await conn.fetch(query, id_oportunidad)
        return [dict(r) for r in rows]

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
