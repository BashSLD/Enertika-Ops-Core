# core/workflow/notification_service.py
"""
Servicio centralizado de notificaciones por email.
Maneja eventos de sistema: NUEVO_COMENTARIO, ASIGNACION, CAMBIO_ESTATUS.

Patrón recomendado por GUIA_MAESTRA: Service Layer con separación de responsabilidades.
"""
from typing import Set, Optional
from uuid import UUID
import logging
import asyncpg
import httpx

from fastapi.templating import Jinja2Templates
from core.microsoft import MicrosoftAuth
from core.notifications.service import get_notifications_service
from core.config import settings

logger = logging.getLogger("NotificationService")

class NotificationService:
    """
    Servicio centralizado para notificaciones por email.
    
    Responsabilidades:
    - Calcular destinatarios según tipo de evento
    - Leer CCs desde tb_config_emails
    - Renderizar templates HTML
    - Enviar emails usando Application-only token de Microsoft Graph
    """
    
    def __init__(self):
        self.ms_auth = MicrosoftAuth()
        self.templates = Jinja2Templates(directory="templates")
    
    # ===== MÉTODOS PÚBLICOS =====
    
    async def notify_new_comment(
        self, 
        conn, 
        id_oportunidad: UUID, 
        comentario: str, 
        sender_ctx: dict, 
        departamento: str
    ):
        """
        Notifica nuevo comentario en oportunidad.
        
        Args:
            conn: Conexión a base de datos
            id_oportunidad: ID de la oportunidad
            comentario: Texto del comentario
            sender_ctx: Contexto del usuario que comentó (user_name, user_db_id, etc)
            departamento: Slug del departamento origen
            
        TO: Contraparte (si comentó creador → notifica responsable, viceversa)
        CC: Correos configurados en tb_config_emails con trigger_value='NUEVO_COMENTARIO'
        """
        try:
            to_emails = await self._get_comment_recipients(conn, id_oportunidad, sender_ctx)
            cc_emails = await self._get_cc_emails(conn, 'NUEVO_COMENTARIO')
            
            if not to_emails:
                logger.info(f"[NOTIFY] Comentario sin destinatarios - Opp: {id_oportunidad}")
                return
            
            opp = await self._get_opportunity(conn, id_oportunidad)
            html = self._render_template('shared/emails/workflow/new_comment.html', {
                'op': opp,
                'comentario': comentario,
                'autor': sender_ctx['user_name'],
                'departamento': departamento,
                'base_url': settings.APP_BASE_URL
            })
            
            subject = f"Nuevo comentario: {opp['op_id_estandar']} - {opp['cliente_nombre']}"
            
            # Usar buzón configurado en lugar del email del usuario
            sender_config = await self._get_notification_sender(conn, departamento)
            await self._send_email(to_emails, cc_emails, subject, html, sender_config['email'])
            
            # SSE: Guardar y broadcastear notificación
            for email in to_emails:
                await self._save_and_broadcast(
                    conn=conn,
                    recipient_email=email,
                    tipo='NUEVO_COMENTARIO',
                    titulo=f'Nuevo comentario: {opp["op_id_estandar"]}',
                    mensaje=f'{sender_ctx["user_name"]} ha comentado en {opp["cliente_nombre"]}',
                    id_oportunidad=id_oportunidad
                )
        
        except asyncpg.PostgresError as e:
            logger.error(f"[NOTIFY] Error de BD en notificacion de comentario {id_oportunidad}: {e}", exc_info=True)
        except httpx.HTTPError as e:
            logger.error(f"[NOTIFY] Error de red/Graph API en notificacion de comentario {id_oportunidad}: {e}", exc_info=True)
        except KeyError as e:
            logger.error(f"[NOTIFY] Error de contexto/datos faltantes en notificacion {id_oportunidad}: campo {e}", exc_info=True)
        except Exception as e:
            logger.error(f"[NOTIFY] Error inesperado en notificacion de comentario {id_oportunidad}: {e}", exc_info=True)
    
    async def notify_assignment(
        self,
        conn,
        id_oportunidad: UUID,
        old_responsable_id: Optional[UUID],
        new_responsable_id: UUID,
        assigned_by_ctx: dict,
        modulo_nombre: str = "oportunidad"
    ):
        """
        Notifica asignación o cambio de responsable.

        Args:
            conn: Conexión a base de datos
            id_oportunidad: ID de la oportunidad
            old_responsable_id: ID del responsable anterior (None si era sin asignar)
            new_responsable_id: ID del nuevo responsable
            assigned_by_ctx: Contexto del usuario que asignó
            modulo_nombre: Nombre legible del módulo ("simulación", "levantamiento", etc.)

        TO: Nuevo responsable
        CC: Correos configurados en tb_config_emails con trigger_value='ASIGNACION'

        Si old_responsable_id == new_responsable_id, no envía (sin cambio real).
        """
        if old_responsable_id == new_responsable_id:
            logger.info(f"[NOTIFY] Sin cambio de responsable - Opp: {id_oportunidad}")
            return
        
        # Obtener datos del nuevo responsable
        new_resp = await conn.fetchrow(
            "SELECT nombre, email FROM tb_usuarios WHERE id_usuario = $1",
            new_responsable_id
        )
        
        if not new_resp or not new_resp['email']:
            logger.warning(f"[NOTIFY] Responsable {new_responsable_id} sin email")
            return
        
        to_emails = {new_resp['email']}
        cc_emails = await self._get_cc_emails(conn, 'ASIGNACION')
        
        opp = await self._get_opportunity(conn, id_oportunidad)
        html = self._render_template('shared/emails/workflow/new_assignment.html', {
            'oportunidad': opp,
            'assigned_by': assigned_by_ctx['user_name'],
            'new_responsable_name': new_resp['nombre'],
            'base_url': settings.APP_BASE_URL,
            'modulo_nombre': modulo_nombre,
        })
        
        subject = f"Asignacion: {opp['op_id_estandar']} - {opp['cliente_nombre']}"
        
        # Usar buzón configurado en lugar del email del usuario
        # NOTA: Para notify_assignment no recibimos departamento, usar DEFAULT
        sender_config = await self._get_notification_sender(conn, 'DEFAULT')
        await self._send_email(to_emails, cc_emails, subject, html, sender_config['email'])
        
        # SSE: Guardar y broadcastear notificación
        await self._save_and_broadcast(
            conn=conn,
            recipient_email=new_resp['email'],
            tipo='ASIGNACION',
            titulo=f'Asignacion: {opp["op_id_estandar"]}',
            mensaje=f'Te han asignado la oportunidad de {opp["cliente_nombre"]}',
            id_oportunidad=id_oportunidad
        )
    
    async def notify_status_change(
        self,
        conn,
        id_oportunidad: UUID,
        old_status_id: int,
        new_status_id: int,
        changed_by_ctx: dict,
        extra_data: Optional[dict] = None
    ):
        """
        Notifica cambio de estatus de oportunidad.
        
        Args:
            conn: Conexión a base de datos
            id_oportunidad: ID de la oportunidad
            old_status_id: ID del estatus anterior
            new_status_id: ID del nuevo estatus
            changed_by_ctx: Contexto del usuario que cambió el estatus
            extra_data: Datos adicionales (opcional, ej. fecha_visita, motivo)
            
        TO: Creador de la oportunidad
        CC: Correos configurados en tb_config_emails con trigger_value='CAMBIO_ESTATUS'
        
        Si old_status_id == new_status_id, no envía (sin cambio real).
        """
        if old_status_id == new_status_id:
            logger.info(f"[NOTIFY] Sin cambio de estatus - Opp: {id_oportunidad}")
            return
        
        opp = await self._get_opportunity(conn, id_oportunidad)
        
        # Obtener email del creador
        creator = await conn.fetchrow(
            "SELECT nombre, email FROM tb_usuarios WHERE id_usuario = $1",
            opp['creado_por_id']
        )
        
        if not creator or not creator['email']:
            logger.warning(f"[NOTIFY] Creador sin email - Opp: {id_oportunidad}")
            return
        
        # Obtener nombres de estatus
        status_rows = await conn.fetch(
            "SELECT id, nombre FROM tb_cat_estatus_global WHERE id = ANY($1::int[])",
            [old_status_id, new_status_id]
        )
        status_map = {s['id']: s['nombre'] for s in status_rows}
        
        to_emails = {creator['email']}
        cc_emails = await self._get_cc_emails(conn, 'CAMBIO_ESTATUS')
        
        html = self._render_template('shared/emails/workflow/status_changed.html', {
            'oportunidad': opp,
            'old_status': status_map.get(old_status_id, 'Desconocido'),
            'new_status': status_map.get(new_status_id, 'Desconocido'),
            'changed_by': changed_by_ctx['user_name'],
            'base_url': settings.APP_BASE_URL,
            'extra_data': extra_data or {}
        })
        
        subject = f"Cambio de estatus: {opp['op_id_estandar']} - {opp['cliente_nombre']}"
        
        # Usar buzón configurado en lugar del email del usuario
        # NOTA: Para notify_status_change no recibimos departamento, usar DEFAULT
        sender_config = await self._get_notification_sender(conn, 'DEFAULT')
        await self._send_email(to_emails, cc_emails, subject, html, sender_config['email'])
        
        # SSE: Guardar y broadcastear notificación
        await self._save_and_broadcast(
            conn=conn,
            recipient_email=creator['email'],
            tipo='CAMBIO_ESTATUS',
            titulo=f'Cambio de estatus: {opp["op_id_estandar"]}',
            mensaje=f'{opp["cliente_nombre"]} cambio de {status_map.get(old_status_id)} a {status_map.get(new_status_id)}',
            id_oportunidad=id_oportunidad
        )
    
    # ===== MÉTODOS PRIVADOS =====
    
    async def _get_opportunity(self, conn, id_oportunidad: UUID) -> dict:
        """
        Obtiene datos básicos de oportunidad.
        
        Returns:
            dict: Datos de la oportunidad o dict vacío si no existe
        """
        query = """
            SELECT 
                id_oportunidad, 
                op_id_estandar, 
                nombre_proyecto, 
                cliente_nombre, 
                creado_por_id, 
                responsable_simulacion_id,
                id_estatus_global
            FROM tb_oportunidades
            WHERE id_oportunidad = $1
        """
        row = await conn.fetchrow(query, id_oportunidad)
        return dict(row) if row else {}
    
    async def _get_comment_recipients(
        self, 
        conn, 
        id_oportunidad: UUID, 
        sender_ctx: dict
    ) -> Set[str]:
        """
        Calcula destinatarios para notificaciones de comentarios.
        
        Lógica: Notificar a la contraparte
        - Si comentó el creador → notifica al responsable
        - Si comentó el responsable → notifica al creador
        - Si el usuario no es ni creador ni responsable, no notifica a nadie
        
        Returns:
            Set[str]: Conjunto de emails destinatarios
        """
        opp = await self._get_opportunity(conn, id_oportunidad)
        
        # Obtener emails de creador y responsable
        user_ids = {opp.get('creado_por_id'), opp.get('responsable_simulacion_id')}
        user_ids = {uid for uid in user_ids if uid}  # Quitar None
        
        if not user_ids:
            return set()
        
        rows = await conn.fetch(
            "SELECT id_usuario, email FROM tb_usuarios WHERE id_usuario = ANY($1::uuid[])",
            list(user_ids)
        )
        users_map = {str(r['id_usuario']): r['email'] for r in rows if r['email']}
        
        sender_id = str(sender_ctx.get('user_db_id', ''))
        recipients = set()
        
        # Si comentó el responsable → notificar creador
        if opp.get('responsable_simulacion_id') and sender_id == str(opp['responsable_simulacion_id']):
            creator_email = users_map.get(str(opp['creado_por_id']))
            if creator_email:
                recipients.add(creator_email)
        
        # Si comentó el creador → notificar responsable
        elif opp.get('creado_por_id') and sender_id == str(opp['creado_por_id']):
            resp_email = users_map.get(str(opp['responsable_simulacion_id']))
            if resp_email:
                recipients.add(resp_email)
        
        # Si comentó un tercero (ni creador ni responsable) → notificar a ambos (si existen)
        else:
             creator_email = users_map.get(str(opp['creado_por_id']))
             if creator_email:
                 recipients.add(creator_email)
                 
             resp_email = users_map.get(str(opp['responsable_simulacion_id']))
             if resp_email:
                 recipients.add(resp_email)

        return recipients
    
    async def _get_cc_emails(self, conn, trigger_value: str) -> Set[str]:
        """
        Obtiene correos CC desde configuración de admin (tb_config_emails).
        
        Args:
            conn: Conexión a base de datos
            trigger_value: Valor del trigger ('NUEVO_COMENTARIO', 'ASIGNACION', 'CAMBIO_ESTATUS')
            
        Returns:
            Set[str]: Conjunto de emails configurados como CC
        """
        query = """
            SELECT email_to_add 
            FROM tb_config_emails 
            WHERE trigger_field = 'EVENTO' 
              AND trigger_value = $1
              AND type = 'CC'
        """
        rows = await conn.fetch(query, trigger_value)
        return {r['email_to_add'] for r in rows if r['email_to_add']}
    
    async def _get_notification_sender(self, conn, departamento: str = 'DEFAULT') -> dict:
        """
        Obtiene configuración del remitente de notificaciones desde BD.
        
        Args:
            conn: Conexión a base de datos
            departamento: Departamento específico o DEFAULT
            
        Returns:
            dict con 'email' y 'nombre' del remitente
        """
        # Buscar configuración específica del departamento activa
        config = await conn.fetchrow("""
            SELECT email_remitente, nombre_remitente
            FROM tb_correos_notificaciones
            WHERE departamento = $1 AND activo = true
            LIMIT 1
        """, departamento.upper())
        
        # Si no existe configuración específica, usar DEFAULT
        if not config:
            config = await conn.fetchrow("""
                SELECT email_remitente, nombre_remitente
                FROM tb_correos_notificaciones
                WHERE departamento = 'DEFAULT' AND activo = true
                LIMIT 1
            """)
        
        # Fallback hardcoded (solo si la BD está vacía)
        if not config:
            logger.warning("[NOTIFY] No hay configuración de sender en BD, usando fallback")
            return {
                'email': 'app-notifications@enertika.mx',
                'nombre': 'Enertika App Notifications'
            }
        
        return {
            'email': config['email_remitente'],
            'nombre': config['nombre_remitente']
        }
    
    async def _save_and_broadcast(
        self,
        conn,
        recipient_email: str,
        tipo: str,
        titulo: str,
        mensaje: str,
        id_oportunidad: UUID
    ):
        """
        Guarda notificación en BD y la envía via SSE si usuario conectado.
        
        Args:
            conn: Conexión a base de datos
            recipient_email: Email del destinatario
            tipo: Tipo de notificación
            titulo: Título de la notificación
            mensaje: Mensaje de la notificación
            id_oportunidad: ID de la oportunidad relacionada
        """
        # Enmascarar PII para logs
        email_parts = recipient_email.split('@')
        if len(email_parts) == 2:
            masked_email = f"{email_parts[0][:3]}***@{email_parts[1]}"
        else:
            masked_email = "***@***"
        
        # Obtener usuario_id desde email
        user_row = await conn.fetchrow(
            "SELECT id_usuario FROM tb_usuarios WHERE email = $1",
            recipient_email
        )
        
        if not user_row:
            # No loguear email completo - usar identificador anónimo
            logger.warning(f"[NOTIFY] Usuario no encontrado para notificacion en Opp: {id_oportunidad} (email: {masked_email})")
            return
        
        usuario_id = user_row['id_usuario']
        
        # Crear notificación usando NotificationsService
        notif_service = get_notifications_service()
        notification_data = await notif_service.create_notification(
            conn=conn,
            usuario_id=usuario_id,
            tipo=tipo,
            titulo=titulo,
            mensaje=mensaje,
            id_oportunidad=id_oportunidad
        )
        
        # Broadcast via SSE si está conectado
        await notif_service.broadcast_to_user(conn, usuario_id, notification_data)
    
    def _render_template(self, template_path: str, context: dict) -> str:
        """
        Renderiza template HTML para email.
        
        Args:
            template_path: Ruta relativa al directorio templates/
            context: Diccionario con variables para el template
            
        Returns:
            str: HTML renderizado
        """
        template = self.templates.get_template(template_path)
        return template.render(**context)
    
    async def _send_email(
        self,
        to_emails: Set[str],
        cc_emails: Set[str],
        subject: str,
        html_body: str,
        sender_email: str  # Email del usuario que ejecuta la accion
    ):
        """
        Envía email usando Application-only token de Microsoft Graph.
        
        Args:
            to_emails: Destinatarios principales (TO)
            cc_emails: Correos en copia (CC)
            subject: Asunto del email
            html_body: Cuerpo del email en HTML
            sender_email: Email del usuario autenticado que ejecuta la accion (FROM)
        """
        if not to_emails:
            logger.info("[NOTIFY] No hay destinatarios, email no enviado")
            return
        
        # Evitar duplicados: quitar TO de CC
        cc_emails = cc_emails - to_emails
        
        try:
            # Obtener token de aplicación (no requiere usuario logueado)
            app_token = await self.ms_auth.get_application_token()
            
            if not app_token:
                logger.error("[NOTIFY] No se pudo obtener token de aplicacion")
                return
            
            # Enviar email via Microsoft Graph API
            success, msg = await self.ms_auth.send_email_with_attachments(
                access_token=app_token,
                from_email=sender_email,  # Primero from_email
                subject=subject,
                body=html_body,
                recipients=list(to_emails),
                cc_recipients=list(cc_emails) if cc_emails else None,
                importance="normal"
            )
            
            if success:
                logger.info(f"[NOTIFY] Email enviado - TO: {len(to_emails)}, CC: {len(cc_emails)}")
            else:
                # Enmascarar PII en logs de error
                masked_recipients = []
                for email in to_emails:
                    parts = email.split('@')
                    if len(parts) == 2:
                        masked_recipients.append(f"{parts[0][:3]}***@{parts[1]}")
                    else:
                        masked_recipients.append("***@***")
                logger.error(f"[NOTIFY] Error enviando email a {len(to_emails)} destinatarios (sample: {masked_recipients[0] if masked_recipients else 'N/A'}): {msg}")
        
        except httpx.HTTPError as e:
            # Error de red o API de Microsoft Graph
            logger.error(f"[NOTIFY] Error de red/Graph API al enviar email: {e}", exc_info=True)
        except asyncpg.PostgresError as e:
            # Error de base de datos (si aplica)
            logger.error(f"[NOTIFY] Error de BD al enviar email: {e}", exc_info=True)
        except Exception as e:
            # Catch-all para errores inesperados
            logger.error(f"[NOTIFY] Error inesperado al enviar email: {e}", exc_info=True)


def get_notification_service():
    """Helper para inyección de dependencias."""
    return NotificationService()
