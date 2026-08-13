# core/workflow/notification_service.py
"""
Servicio centralizado de notificaciones por email.
Maneja eventos de sistema: NUEVO_COMENTARIO, ASIGNACION, CAMBIO_ESTATUS.

Patrón recomendado por GUIA_MAESTRA: Service Layer con separación de responsabilidades.
"""
from typing import Set, Optional
from uuid import UUID
from datetime import date
import logging
import asyncpg
import httpx
from jinja2 import TemplateError

from fastapi.templating import Jinja2Templates
from core.config_service import ConfigService
from core.microsoft import MicrosoftAuth
from core.notifications.service import get_notifications_service
from core.config import settings
from core.workflow.notification_db_service import (
    WorkflowNotificationDBService,
    get_workflow_notification_db_service,
)

logger = logging.getLogger("NotificationService")

OPPORTUNITY_WON_REMINDER_HOURS = 48
OPPORTUNITY_WON_BASE_ROLES = ("jefe_comercial", "jefe_construccion")
OPPORTUNITY_WON_DIRECTOR_ROLE = "director"
VACACIONES_EVENTO_APROBADA = "VACACIONES_SOLICITUD_APROBADA"
VACACIONES_EVENTO_RECHAZADA = "VACACIONES_SOLICITUD_RECHAZADA"
VACACIONES_REGLAS_MODULOS = {"GLOBAL", "RRHH"}
PLACEHOLDER_EMPLEADO = "{EMPLEADO}"


class NotificationService:
    """
    Servicio centralizado para notificaciones por email.
    
    Responsabilidades:
    - Calcular destinatarios según tipo de evento
    - Leer CCs desde tb_config_emails
    - Renderizar templates HTML
    - Enviar emails usando Application-only token de Microsoft Graph
    """
    
    def __init__(self, db: WorkflowNotificationDBService | None = None):
        self.db = db or get_workflow_notification_db_service()
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
        except (AttributeError, KeyError, TemplateError, TypeError, ValueError, RuntimeError) as e:
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
        new_resp = await self.db.get_active_user_contact(conn, new_responsable_id)
        
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
            id_oportunidad=id_oportunidad,
            modulo_origen=modulo_nombre if modulo_nombre else 'simulacion'
        )
    
    async def notify_status_change(
        self,
        conn,
        id_oportunidad: UUID,
        old_status_id: int,
        new_status_id: int,
        changed_by_ctx: dict,
        extra_data: Optional[dict] = None,
        modulo_origen: str = "simulacion"
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
        creator = await self.db.get_active_user_contact(conn, opp['creado_por_id'])
        
        if not creator or not creator['email']:
            logger.warning(f"[NOTIFY] Creador sin email - Opp: {id_oportunidad}")
            return
        
        # Obtener nombres de estatus
        status_map = await self.db.get_status_names(conn, [old_status_id, new_status_id])
        
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
            id_oportunidad=id_oportunidad,
            modulo_origen=modulo_origen
        )
    
    async def notify_cancellation(
        self,
        conn,
        id_levantamiento: UUID,
        id_oportunidad: UUID,
        cancelado_por_ctx: dict,
        motivo: Optional[str] = None,
    ):
        """
        Notifica la cancelación de un levantamiento.
        TO: jefe de área + quien solicitó el levantamiento
        CC: tb_config_emails con trigger_value='CAMBIO_ESTATUS'
        """
        try:
            # Jefe de área y solicitante del levantamiento
            destinatarios = await self.db.get_cancellation_recipients(conn, id_levantamiento)

            to_emails = {r['email'] for r in destinatarios if r['email']}

            if not to_emails:
                logger.warning(f"[NOTIFY] Sin destinatarios para cancelacion lev {id_levantamiento}")
                return

            cc_emails = await self._get_cc_emails(conn, 'CAMBIO_ESTATUS')
            opp = await self._get_opportunity(conn, id_oportunidad)

            html = self._render_template('shared/emails/workflow/cancelacion.html', {
                'oportunidad': opp,
                'cancelado_por': cancelado_por_ctx.get('user_name', 'Usuario'),
                'motivo': motivo,
                'base_url': settings.APP_BASE_URL,
            })

            subject = f"Levantamiento Cancelado: {opp['op_id_estandar']} - {opp['cliente_nombre']}"
            sender_config = await self._get_notification_sender(conn, 'DEFAULT')
            await self._send_email(to_emails, cc_emails, subject, html, sender_config['email'])

            logger.info(f"[NOTIFY] Cancelacion notificada para lev {id_levantamiento}")

        except asyncpg.PostgresError as e:
            logger.error(f"[NOTIFY] Error BD en notificacion cancelacion {id_levantamiento}: {e}", exc_info=True)
        except httpx.HTTPError as e:
            logger.error(f"[NOTIFY] Error red/Graph API en notificacion cancelacion {id_levantamiento}: {e}", exc_info=True)
        except KeyError as e:
            logger.error(f"[NOTIFY] Error datos faltantes en notificacion cancelacion {id_levantamiento}: campo {e}", exc_info=True)
        except (AttributeError, KeyError, TemplateError, TypeError, ValueError, RuntimeError) as e:
            logger.error(f"[NOTIFY] Error inesperado en notificacion cancelacion {id_levantamiento}: {e}", exc_info=True)

    async def notify_op_levantamiento_cancelado_sin_cerrar(
        self,
        conn,
        id_oportunidad: UUID,
        opp: dict,
        to_email: str,
        cc_emails: Set[str],
        motivos: list[str],
    ) -> bool:
        """
        Recordatorio periódico (worker): todos los levantamientos de la OP quedaron
        cancelados pero la OP sigue abierta (ver check_op_levantamiento_sin_cerrar_periodically
        en core/tasks.py). TO: responsable comercial (fallback creador). CC: resuelto
        dinámicamente contra tb_permisos_modulos+tb_usuarios por el caller — NO usa
        tb_config_emails (no puede expresar la regla admin-comercial OR manager+editor).
        `opp` (op_id_estandar/cliente_nombre/nombre_proyecto) viene de la misma query
        que ya produjo el candidato -- evita un fetchrow adicional por OP, por tick.
        Retorna True si el envío tuvo éxito, para que el caller decida si marca el
        anti-spam (tb_oportunidades.recordatorio_lev_cancelado_at).
        """
        try:
            html = self._render_template('shared/emails/workflow/op_levantamiento_cancelado_sin_cerrar.html', {
                'oportunidad': opp,
                'motivos': motivos,
                'base_url': settings.APP_BASE_URL,
            })

            subject = f"Accion requerida: cerrar oportunidad cancelada {opp['op_id_estandar']} - {opp['cliente_nombre']}"
            sender_config = await self._get_notification_sender(conn, 'DEFAULT')
            await self._send_email({to_email}, cc_emails, subject, html, sender_config['email'])

            await self._save_and_broadcast(
                conn=conn,
                recipient_email=to_email,
                tipo='LEV_CANCELADO_SIN_CERRAR',
                titulo=f'Accion requerida: {opp["op_id_estandar"]}',
                mensaje=f'{opp["cliente_nombre"]}: todos los levantamientos quedaron cancelados, cierra la oportunidad para liberar el hilo.',
                id_oportunidad=id_oportunidad,
                modulo_origen='levantamientos',
            )
            logger.info(f"[NOTIFY] Recordatorio OP levantamiento cancelado sin cerrar enviado: {id_oportunidad}")
            return True

        except asyncpg.PostgresError as e:
            logger.error(f"[NOTIFY] Error BD en recordatorio OP levantamiento cancelado {id_oportunidad}: {e}", exc_info=True)
        except httpx.HTTPError as e:
            logger.error(f"[NOTIFY] Error red/Graph API en recordatorio OP levantamiento cancelado {id_oportunidad}: {e}", exc_info=True)
        except (AttributeError, KeyError, TemplateError, TypeError, ValueError, RuntimeError) as e:
            logger.error(f"[NOTIFY] Error inesperado en recordatorio OP levantamiento cancelado {id_oportunidad}: {e}", exc_info=True)
        return False

    async def notify_reassignment_request(
        self,
        conn,
        id_levantamiento: UUID,
        id_oportunidad: UUID,
        solicitado_por_ctx: dict,
        motivo: Optional[str] = None,
    ):
        """
        Notifica solicitud de reasignación de levantamiento.
        TO: quien asignó al responsable + quien solicitó el levantamiento
        CC: tb_config_emails con trigger_value='ASIGNACION'
        """
        try:
            destinatarios = await self.db.get_reassignment_recipients(conn, id_levantamiento)
            to_emails = {row["email"] for row in destinatarios if row.get("email")}

            if not to_emails:
                logger.warning(f"[NOTIFY] Sin destinatarios para solicitud reasignacion lev {id_levantamiento}")
                return

            cc_emails = await self._get_cc_emails(conn, 'ASIGNACION')
            opp = await self._get_opportunity(conn, id_oportunidad)

            html = self._render_template('shared/emails/workflow/solicitud_reasignacion.html', {
                'oportunidad': opp,
                'solicitado_por': solicitado_por_ctx.get('user_name', 'Usuario'),
                'motivo': motivo,
                'base_url': settings.APP_BASE_URL,
            })

            subject = f"Solicitud de Reasignacion: {opp['op_id_estandar']} - {opp['cliente_nombre']}"
            sender_config = await self._get_notification_sender(conn, 'DEFAULT')
            await self._send_email(to_emails, cc_emails, subject, html, sender_config['email'])

            logger.info(f"[NOTIFY] Solicitud reasignacion notificada para lev {id_levantamiento}")

        except asyncpg.PostgresError as e:
            logger.error(f"[NOTIFY] Error BD en solicitud reasignacion {id_levantamiento}: {e}", exc_info=True)
        except httpx.HTTPError as e:
            logger.error(f"[NOTIFY] Error red/Graph API en solicitud reasignacion {id_levantamiento}: {e}", exc_info=True)
        except KeyError as e:
            logger.error(f"[NOTIFY] Error datos faltantes en solicitud reasignacion {id_levantamiento}: campo {e}", exc_info=True)
        except (AttributeError, KeyError, TemplateError, TypeError, ValueError, RuntimeError) as e:
            logger.error(f"[NOTIFY] Error inesperado en solicitud reasignacion {id_levantamiento}: {e}", exc_info=True)

    async def notify_opportunity_won(
        self,
        conn,
        id_oportunidad: UUID,
        won_by_ctx: dict,
        include_director: bool = True,
        reminder_number: Optional[int] = None,
    ) -> bool:
        """
        Envía notificación de oportunidad ganada.

        Destinatarios TO:
        - Jefe Comercial
        - Jefe de Construcción
        - Director (solo si include_director=True)
        - Propietario de la oportunidad

        No usa reglas de tb_config_emails para este evento.

        Returns:
            bool: True si el correo se envió correctamente, False en caso contrario.
        """
        try:
            opp = await self._get_opportunity(conn, id_oportunidad)
            if not opp:
                logger.warning(f"[NOTIFY] notify_opportunity_won: oportunidad no encontrada {id_oportunidad}")
                return False

            to_emails = await self._get_opportunity_won_recipients(
                conn=conn,
                id_oportunidad=id_oportunidad,
                owner_id=opp.get('creado_por_id'),
                include_director=include_director,
            )
            cc_emails: Set[str] = set()

            if not to_emails:
                logger.warning(
                    "[NOTIFY] notify_opportunity_won: sin destinatarios por rol organizacional/owner - Opp: %s",
                    id_oportunidad,
                )
                return False

            subject_prefix = f"Recordatorio #{reminder_number}: " if reminder_number else ""

            html = self._render_template('shared/emails/workflow/oportunidad_ganada.html', {
                'oportunidad': opp,
                'ganada_por': won_by_ctx.get('user_name', 'Sistema'),
                'is_recordatorio': reminder_number is not None,
                'recordatorio_numero': reminder_number,
                'base_url': settings.APP_BASE_URL,
            })

            subject = (
                f"{subject_prefix}Oportunidad Ganada: "
                f"{opp.get('op_id_estandar', '')} - {opp.get('cliente_nombre', '')}"
            )
            sender_config = await self._get_notification_sender(conn, 'COMERCIAL')
            sent = await self._send_email(to_emails, cc_emails, subject, html, sender_config['email'])

            if sent:
                logger.info(
                    "[NOTIFY] Oportunidad ganada notificada - Opp: %s, TO: %s, include_director=%s, reminder=%s",
                    id_oportunidad,
                    len(to_emails),
                    include_director,
                    reminder_number,
                )
            return sent

        except asyncpg.PostgresError as e:
            logger.error(f"[NOTIFY] Error BD en notify_opportunity_won {id_oportunidad}: {e}", exc_info=True)
            return False
        except httpx.HTTPError as e:
            logger.error(f"[NOTIFY] Error red/Graph API en notify_opportunity_won {id_oportunidad}: {e}", exc_info=True)
            return False
        except KeyError as e:
            logger.error(f"[NOTIFY] Error datos faltantes en notify_opportunity_won {id_oportunidad}: campo {e}", exc_info=True)
            return False

    async def schedule_opportunity_won_reminders(self, conn, id_oportunidad: UUID) -> None:
        """
        Activa o reactiva el ciclo automático de recordatorios de oportunidad ganada.

        - Crea registro si no existe.
        - Reagenda el próximo envío a +48 horas.
        - Mantiene histórico de recordatorios enviados en la tabla dedicada.
        """
        await self.db.schedule_opportunity_won_reminders(
            conn,
            id_oportunidad,
            OPPORTUNITY_WON_REMINDER_HOURS,
        )

    async def notify_poliza_estatus_change(
        self,
        conn,
        cotizacion_id,
        cotizacion: dict,
        nuevo_estatus: str,
        changed_by_ctx: dict,
    ):
        """
        Notifica cambio de estatus de poliza OyM al creador de la cotizacion.

        Args:
            conn: Conexion a base de datos
            cotizacion_id: ID de la cotizacion (solo para logs)
            cotizacion: Dict con datos de la cotizacion (creado_por, nombre_planta, etc.)
            nuevo_estatus: 'ACEPTADA' o 'RECHAZADA'
            changed_by_ctx: Contexto del usuario que realizo el cambio

        TO: Creador de la cotizacion
        CC: Correos configurados en tb_config_emails con trigger_value='CAMBIO_ESTATUS'
        """
        try:
            creado_por = cotizacion.get("creado_por")
            if not creado_por:
                logger.warning(f"[NOTIFY] Poliza {cotizacion_id} sin creado_por — email no enviado")
                return

            creator = await self.db.get_active_user_contact(conn, creado_por)
            if not creator or not creator["email"]:
                logger.warning(f"[NOTIFY] Creador de poliza {cotizacion_id} sin email")
                return

            to_emails = {creator["email"]}
            cc_emails = await self._get_cc_emails(conn, "CAMBIO_ESTATUS")

            html = self._render_template(
                "shared/emails/workflow/poliza_estatus_changed.html",
                {
                    "cotizacion": cotizacion,
                    "nuevo_estatus": nuevo_estatus,
                    "changed_by": changed_by_ctx.get("user_name", "Usuario"),
                    "base_url": settings.APP_BASE_URL,
                },
            )

            label = "Aceptada" if nuevo_estatus == "ACEPTADA" else "Rechazada"
            subject = f"Poliza OyM {label}: {cotizacion.get('nombre_planta', '')}"

            sender_config = await self._get_notification_sender(conn, "DEFAULT")
            await self._send_email(to_emails, cc_emails, subject, html, sender_config["email"])

            logger.info(f"[NOTIFY] Poliza {cotizacion_id} — estatus {nuevo_estatus} notificado a {creator['email'][:3]}***")

        except asyncpg.PostgresError as e:
            logger.error(f"[NOTIFY] Error BD en notify_poliza_estatus_change {cotizacion_id}: {e}", exc_info=True)
        except httpx.HTTPError as e:
            logger.error(f"[NOTIFY] Error red/Graph API en notify_poliza_estatus_change {cotizacion_id}: {e}", exc_info=True)
        except KeyError as e:
            logger.error(f"[NOTIFY] Error datos faltantes en notify_poliza_estatus_change {cotizacion_id}: campo {e}", exc_info=True)

    async def notify_horas_extra_aprobacion(
        self,
        conn,
        *,
        aprobador_nombre: str,
        empleado_nombre: str,
        empleado_email: str | None = None,
        dias_aprobados: list[dict],
        comentario: str,
    ) -> None:
        try:
            to_emails = await self._get_emails_for_event(
                conn, "APROBACION_HORAS_EXTRA", "TO", empleado_email=empleado_email
            )
            cc_emails = await self._get_emails_for_event(
                conn, "APROBACION_HORAS_EXTRA", "CC", empleado_email=empleado_email
            )

            if not to_emails:
                logger.info(
                    "[NOTIFY] APROBACION_HORAS_EXTRA sin destinatarios TO configurados — omitiendo"
                )
                return

            html = self._render_template(
                "shared/emails/vacaciones/horas_extra_aprobacion.html",
                {
                    "aprobador_nombre": aprobador_nombre,
                    "empleado_nombre": empleado_nombre,
                    "dias_aprobados": dias_aprobados,
                    "comentario": comentario,
                },
            )
            subject = f"Horas extra aprobadas y abonadas a bolsa: {empleado_nombre}"
            sender_config = await self._get_notification_sender(conn, "DEFAULT")
            await self._send_email(to_emails, cc_emails, subject, html, sender_config["email"])

        except asyncpg.PostgresError as exc:
            logger.error("[NOTIFY] Error BD en APROBACION_HORAS_EXTRA: %s", exc, exc_info=True)
        except httpx.HTTPError as exc:
            logger.error("[NOTIFY] Error red en APROBACION_HORAS_EXTRA: %s", exc, exc_info=True)
        except (AttributeError, KeyError, TemplateError, TypeError, ValueError, RuntimeError) as exc:
            logger.error("[NOTIFY] Error inesperado en APROBACION_HORAS_EXTRA: %s", exc, exc_info=True)

    async def _notify_solicitud_pendiente(
        self,
        conn,
        *,
        template_path: str,
        subject_pendiente: str,
        subject_recordatorio: str,
        titulo_notificacion: str,
        mensaje_notificacion: str,
        modulo_origen: str,
        template_context: dict,
        destinatarios: set[str],
        cc_emails: set[str] | None = None,
        bcc_emails: set[str] | None = None,
        url_aprobacion: str,
        label_boton: str,
        es_recordatorio: bool = False,
        recordatorio_numero: int | None = None,
        log_tag: str,
    ) -> bool:
        """
        Orquestacion compartida por las solicitudes de horas-extra y compensatorio:
        misma forma (render + envio + broadcast in-app), solo cambian el template,
        el copy de asunto/notificacion y los campos propios de cada entidad.

        url_aprobacion/label_boton los entrega el resolver unico de destinatarios
        (modules.asistencia.service.resolver_destinatarios_he_puro) — no se infieren aqui.
        """
        try:
            if not destinatarios:
                logger.info("[NOTIFY] %s sin destinatarios — omitiendo", log_tag)
                return False

            cc_emails = cc_emails or set()

            html = self._render_template(
                template_path,
                {
                    **template_context,
                    "url_aprobacion": url_aprobacion,
                    "label_boton": label_boton,
                    "es_recordatorio": es_recordatorio,
                    "recordatorio_numero": recordatorio_numero,
                },
            )
            subject = subject_recordatorio if es_recordatorio else subject_pendiente
            sender_config = await self._get_notification_sender(conn, "DEFAULT")
            enviado = await self._send_email(
                destinatarios, cc_emails, subject, html, sender_config["email"], bcc_emails=bcc_emails
            )
            if not enviado:
                return False

            for email in destinatarios:
                await self._save_and_broadcast(
                    conn=conn,
                    recipient_email=email,
                    tipo="ASIGNACION",
                    titulo=titulo_notificacion,
                    mensaje=mensaje_notificacion,
                    id_oportunidad=None,
                    modulo_origen=modulo_origen,
                )
            return True

        except asyncpg.PostgresError as exc:
            logger.error("[NOTIFY] Error BD en %s: %s", log_tag, exc, exc_info=True)
        except httpx.HTTPError as exc:
            logger.error("[NOTIFY] Error red en %s: %s", log_tag, exc, exc_info=True)
        except (AttributeError, KeyError, TemplateError, TypeError, ValueError, RuntimeError) as exc:
            logger.error("[NOTIFY] Error inesperado en %s: %s", log_tag, exc, exc_info=True)
        return False

    async def notify_horas_extra_solicitud(
        self,
        conn,
        *,
        empleado_nombre: str,
        fecha_laboral,
        extra_fmt: str,
        motivo: str,
        destinatarios: set[str],
        cc_emails: set[str] | None = None,
        bcc_emails: set[str] | None = None,
        url_aprobacion: str,
        label_boton: str,
        es_recordatorio: bool = False,
        recordatorio_numero: int | None = None,
    ) -> bool:
        fecha_str = fecha_laboral.strftime("%d/%m/%Y")
        return await self._notify_solicitud_pendiente(
            conn,
            template_path="shared/emails/vacaciones/horas_extra_solicitud.html",
            subject_pendiente=f"Solicitud de horas extra: {empleado_nombre}",
            subject_recordatorio=f"Recordatorio de horas extra pendiente: {empleado_nombre}",
            titulo_notificacion=f"Solicitud de horas extra — {empleado_nombre}",
            mensaje_notificacion=f"{fecha_str} · {extra_fmt}",
            modulo_origen="asistencia",
            template_context={
                "empleado_nombre": empleado_nombre,
                "fecha": fecha_str,
                "extra_fmt": extra_fmt,
                "motivo": motivo,
            },
            destinatarios=destinatarios,
            cc_emails=cc_emails,
            bcc_emails=bcc_emails,
            url_aprobacion=url_aprobacion,
            label_boton=label_boton,
            es_recordatorio=es_recordatorio,
            recordatorio_numero=recordatorio_numero,
            log_tag="SOLICITUD_HORAS_EXTRA",
        )

    async def notify_compensatorio_solicitud(
        self,
        conn,
        *,
        empleado_nombre: str,
        fecha_descanso,
        minutos_fmt: str,
        motivo: str,
        destinatarios: set[str],
        cc_emails: set[str] | None = None,
        bcc_emails: set[str] | None = None,
        url_aprobacion: str,
        label_boton: str,
        es_recordatorio: bool = False,
        recordatorio_numero: int | None = None,
    ) -> bool:
        fecha_str = fecha_descanso.strftime("%d/%m/%Y")
        return await self._notify_solicitud_pendiente(
            conn,
            template_path="shared/emails/vacaciones/compensatorio_solicitud.html",
            subject_pendiente=f"Solicitud de tiempo compensatorio: {empleado_nombre}",
            subject_recordatorio=f"Recordatorio de tiempo compensatorio pendiente: {empleado_nombre}",
            titulo_notificacion=f"Solicitud de tiempo compensatorio - {empleado_nombre}",
            mensaje_notificacion=f"{fecha_str} - {minutos_fmt}",
            modulo_origen="asistencia",
            template_context={
                "empleado_nombre": empleado_nombre,
                "fecha": fecha_str,
                "minutos_fmt": minutos_fmt,
                "motivo": motivo,
            },
            destinatarios=destinatarios,
            cc_emails=cc_emails,
            bcc_emails=bcc_emails,
            url_aprobacion=url_aprobacion,
            label_boton=label_boton,
            es_recordatorio=es_recordatorio,
            recordatorio_numero=recordatorio_numero,
            log_tag="SOLICITUD_HE_COMP",
        )

    async def notify_he_solicitud_retirada(
        self,
        conn,
        *,
        empleado_nombre: str,
        fecha_laboral,
        extra_fmt: str,
        destinatarios: set[str],
    ) -> bool:
        """Aviso informativo (sin recordatorios) cuando el dueno retira una HE en estado 'solicitado'."""
        try:
            if not destinatarios:
                logger.info("[NOTIFY] HE_SOLICITUD_RETIRADA sin destinatarios — omitiendo")
                return False
            html = self._render_template(
                "shared/emails/vacaciones/horas_extra_retiro.html",
                {
                    "empleado_nombre": empleado_nombre,
                    "fecha": fecha_laboral.strftime("%d/%m/%Y"),
                    "extra_fmt": extra_fmt,
                },
            )
            subject = f"Solicitud de horas extra retirada: {empleado_nombre}"
            sender_config = await self._get_notification_sender(conn, "DEFAULT")
            return await self._send_email(destinatarios, set(), subject, html, sender_config["email"])
        except asyncpg.PostgresError as exc:
            logger.error("[NOTIFY] Error BD en HE_SOLICITUD_RETIRADA: %s", exc, exc_info=True)
        except httpx.HTTPError as exc:
            logger.error("[NOTIFY] Error red en HE_SOLICITUD_RETIRADA: %s", exc, exc_info=True)
        except (AttributeError, KeyError, TemplateError, TypeError, ValueError, RuntimeError) as exc:
            logger.error("[NOTIFY] Error inesperado en HE_SOLICITUD_RETIRADA: %s", exc, exc_info=True)
        return False

    async def notify_aprobador_he_inactivo(
        self,
        conn,
        *,
        empleados_afectados: list[dict],
        destinatarios: set[str],
    ) -> bool:
        """Post-baja: avisa a RH/ADMIN que un aprobador HE exclusivo quedo inactivo y debe reasignarse."""
        try:
            if not destinatarios or not empleados_afectados:
                return False
            html = self._render_template(
                "shared/emails/vacaciones/aprobador_he_inactivo.html",
                {"empleados_afectados": empleados_afectados},
            )
            subject = f"Aprobador de horas extra inactivo — {len(empleados_afectados)} empleado(s) afectados"
            sender_config = await self._get_notification_sender(conn, "DEFAULT")
            return await self._send_email(destinatarios, set(), subject, html, sender_config["email"])
        except asyncpg.PostgresError as exc:
            logger.error("[NOTIFY] Error BD en APROBADOR_HE_INACTIVO: %s", exc, exc_info=True)
        except httpx.HTTPError as exc:
            logger.error("[NOTIFY] Error red en APROBADOR_HE_INACTIVO: %s", exc, exc_info=True)
        except (AttributeError, KeyError, TemplateError, TypeError, ValueError, RuntimeError) as exc:
            logger.error("[NOTIFY] Error inesperado en APROBADOR_HE_INACTIVO: %s", exc, exc_info=True)
        return False

    async def _notify_resumen_rh(
        self,
        conn,
        *,
        template_path: str,
        subject: str,
        rows: list[dict],
        rh_emails: set[str],
        log_tag: str,
    ) -> bool:
        try:
            if not rows or not rh_emails:
                logger.info("[NOTIFY] %s sin registros o destinatarios", log_tag)
                return False
            html = self._render_template(template_path, {"rows": rows})
            sender_config = await self._get_notification_sender(conn, "DEFAULT")
            return await self._send_email(rh_emails, set(), subject, html, sender_config["email"])
        except asyncpg.PostgresError as exc:
            logger.error("[NOTIFY] Error BD en %s: %s", log_tag, exc, exc_info=True)
        except httpx.HTTPError as exc:
            logger.error("[NOTIFY] Error red en %s: %s", log_tag, exc, exc_info=True)
        except (AttributeError, KeyError, TemplateError, TypeError, ValueError, RuntimeError) as exc:
            logger.error("[NOTIFY] Error inesperado en %s: %s", log_tag, exc, exc_info=True)
        return False

    async def notify_horas_extra_resumen_rh(
        self,
        conn,
        *,
        rows: list[dict],
        rh_emails: set[str],
    ) -> bool:
        return await self._notify_resumen_rh(
            conn,
            template_path="shared/emails/vacaciones/horas_extra_resumen_rh.html",
            subject="Resumen semanal: horas extra pendientes de resolver",
            rows=rows,
            rh_emails=rh_emails,
            log_tag="RESUMEN_HE_RH",
        )

    async def notify_compensatorio_resumen_rh(
        self,
        conn,
        *,
        rows: list[dict],
        rh_emails: set[str],
    ) -> bool:
        return await self._notify_resumen_rh(
            conn,
            template_path="shared/emails/vacaciones/compensatorio_resumen_rh.html",
            subject="Resumen semanal: tiempo compensatorio pendiente",
            rows=rows,
            rh_emails=rh_emails,
            log_tag="RESUMEN_HE_COMP_RH",
        )

    async def notify_compensatorio_resuelto(
        self,
        conn,
        solicitud: dict,
        *,
        aprobado: bool,
    ) -> bool:
        try:
            empleado_email = solicitud.get("empleado_email")
            if not empleado_email:
                logger.info("[NOTIFY] HE_COMP_RESUELTO sin email de empleado: %s", solicitud.get("id"))
                return False

            estado_label = "aprobado" if aprobado else "rechazado"
            html = self._render_template(
                "shared/emails/vacaciones/compensatorio_resuelto.html",
                {
                    "empleado_nombre": solicitud["empleado_nombre"],
                    "fecha": solicitud["fecha_descanso"].strftime("%d/%m/%Y"),
                    "minutos": solicitud["minutos_solicitados"],
                    "estado_label": estado_label,
                    "comentario": solicitud.get("comentario_aprobador") or "",
                },
            )
            subject = f"Tiempo compensatorio {estado_label}: {solicitud['fecha_descanso'].strftime('%d/%m/%Y')}"
            cc_emails = await self._get_emails_for_event(conn, "APROBACION_COMPENSATORIO", "CC")
            sender_config = await self._get_notification_sender(conn, "DEFAULT")
            return await self._send_email({empleado_email}, cc_emails, subject, html, sender_config["email"])

        except asyncpg.PostgresError as exc:
            logger.error("[NOTIFY] Error BD en HE_COMP_RESUELTO: %s", exc, exc_info=True)
        except httpx.HTTPError as exc:
            logger.error("[NOTIFY] Error red en HE_COMP_RESUELTO: %s", exc, exc_info=True)
        except (AttributeError, KeyError, TemplateError, TypeError, ValueError, RuntimeError) as exc:
            logger.error("[NOTIFY] Error inesperado en HE_COMP_RESUELTO: %s", exc, exc_info=True)
        return False

    async def notify_he_saldo_inicial_arranque(self, conn) -> bool:
        try:
            fecha_corte_str = await ConfigService.get_global_config(
                conn, "HE_BOLSA_FECHA_CORTE", "2026-07-07", str
            )
            fecha_corte = date.fromisoformat(fecha_corte_str)
            rows = await conn.fetch(
                """
                SELECT
                    u.id_usuario,
                    u.nombre AS empleado_nombre,
                    COALESCE(jefes.emails, ARRAY[]::text[]) AS jefe_emails
                FROM tb_usuarios u
                JOIN tb_empleados_datos ed ON ed.usuario_id = u.id_usuario
                LEFT JOIN tb_he_saldo_inicial_confirmaciones c
                    ON c.usuario_id = u.id_usuario
                LEFT JOIN LATERAL (
                    SELECT ARRAY_AGG(DISTINCT j.email) FILTER (WHERE j.email IS NOT NULL) AS emails
                    FROM tb_empleados_jefes ej
                    JOIN tb_usuarios j ON j.id_usuario = ej.jefe_id AND j.is_active = true
                    WHERE ej.empleado_id = u.id_usuario
                ) jefes ON true
                WHERE u.is_active = true
                  AND c.id IS NULL
                  AND (ed.fecha_contratacion IS NULL OR ed.fecha_contratacion <= $1)
                ORDER BY u.nombre
                """,
                fecha_corte,
            )
            if not rows:
                logger.info("[NOTIFY] HE_SALDO_INICIAL sin pendientes")
                return False

            rh_emails = await self._get_rh_emails_cc(conn)
            por_destinatario: dict[str, list[dict]] = {}
            for row in rows:
                jefe_emails = {email for email in (row.get("jefe_emails") or []) if email}
                destinatarios = jefe_emails or rh_emails
                for email in destinatarios:
                    por_destinatario.setdefault(email, []).append(dict(row))

            if not por_destinatario:
                logger.info("[NOTIFY] HE_SALDO_INICIAL sin destinatarios")
                return False

            sender_config = await self._get_notification_sender(conn, "DEFAULT")
            enviados = 0
            for email, empleados in por_destinatario.items():
                url_aprobacion = (
                    f"{settings.APP_BASE_URL}/rrhh?tab=aprobaciones"
                    if email in rh_emails
                    else f"{settings.APP_BASE_URL}/perfil/ui?tab=equipo"
                )
                html = self._render_template(
                    "shared/emails/vacaciones/saldo_inicial_arranque.html",
                    {
                        "empleados": empleados,
                        "url_aprobacion": url_aprobacion,
                    },
                )
                cc_emails = rh_emails if email not in rh_emails else set()
                enviado = await self._send_email(
                    {email},
                    cc_emails,
                    "Confirmacion de saldo inicial de bolsa HE",
                    html,
                    sender_config["email"],
                )
                if enviado:
                    enviados += 1

            return enviados > 0

        except asyncpg.PostgresError as exc:
            logger.error("[NOTIFY] Error BD en HE_SALDO_INICIAL: %s", exc, exc_info=True)
        except httpx.HTTPError as exc:
            logger.error("[NOTIFY] Error red en HE_SALDO_INICIAL: %s", exc, exc_info=True)
        except (AttributeError, KeyError, TemplateError, TypeError, ValueError, RuntimeError) as exc:
            logger.error("[NOTIFY] Error inesperado en HE_SALDO_INICIAL: %s", exc, exc_info=True)
        return False

    # ===== MÉTODOS PRIVADOS =====

    async def _get_opportunity(self, conn, id_oportunidad: UUID) -> dict:
        """
        Obtiene datos básicos de oportunidad.
        
        Returns:
            dict: Datos de la oportunidad o dict vacío si no existe
        """
        return await self.db.get_opportunity(conn, id_oportunidad)

    async def _get_opportunity_won_recipients(
        self,
        conn,
        id_oportunidad: UUID,
        owner_id: Optional[UUID],
        include_director: bool,
    ) -> Set[str]:
        """
        Obtiene destinatarios para oportunidad ganada por roles organizacionales + propietario.
        """
        roles = list(OPPORTUNITY_WON_BASE_ROLES)
        if include_director:
            roles.append(OPPORTUNITY_WON_DIRECTOR_ROLE)

        recipients = await self.db.get_emails_by_organizational_roles(conn, roles)

        if owner_id:
            owner_email = await self.db.get_active_user_email(conn, owner_id)
            if owner_email:
                recipients.add(owner_email.strip().lower())

        if not recipients:
            logger.warning(
                "[NOTIFY] Sin destinatarios para oportunidad ganada %s (roles=%s, owner=%s)",
                id_oportunidad,
                roles,
                owner_id,
            )

        return recipients
    
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
        
        users_map = await self.db.get_active_user_emails_by_ids(conn, list(user_ids))
        
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
        return await self._get_emails_for_event(conn, trigger_value, 'CC')

    async def _get_emails_for_event(
        self,
        conn,
        trigger_value: str,
        type_filter: str,
        modulos: Optional[Set[str]] = None,
        *,
        empleado_email: str | None = None,
    ) -> Set[str]:
        """
        Obtiene emails TO, CC o CCO desde tb_config_emails para un evento dado.

        Si RH configuró el placeholder dinámico PLACEHOLDER_EMPLEADO ("{EMPLEADO}")
        para el evento, se resuelve al email pasado en `empleado_email`; si no hay
        email disponible, el placeholder se descarta sin sustituto.

        Args:
            conn: Conexión a base de datos
            trigger_value: Valor del trigger (ej. 'OPORTUNIDAD_GANADA', 'NUEVO_COMENTARIO')
            type_filter: 'TO', 'CC' o 'CCO'
            empleado_email: email del empleado destinatario dinámico, si aplica

        Returns:
            Set[str]: Conjunto de emails configurados
        """
        emails = await self.db.get_emails_for_event(conn, trigger_value, type_filter, modulos)
        if PLACEHOLDER_EMPLEADO in emails:
            emails = emails - {PLACEHOLDER_EMPLEADO}
            if empleado_email:
                emails = emails | {empleado_email}
        return emails
    
    async def send_simple_notification(
        self, conn, destinatario: str, asunto: str, html_body: str,
        departamento: str = 'DEFAULT',
    ) -> bool:
        """Envia un correo de una sola vez resolviendo el remitente configurado.

        Pensado para callers fuera de este modulo (ej. consumidores de outbox)
        que no necesitan las plantillas Jinja de _render_template.
        """
        remitente = await self._get_notification_sender(conn, departamento)
        return await self._send_email(
            {destinatario}, set(), asunto, html_body, remitente["email"]
        )

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
        config = await self.db.get_notification_sender(conn, departamento)
        
        # Si no existe configuración específica, usar DEFAULT
        if not config:
            config = await self.db.get_default_notification_sender(conn)
        
        # Sin fallback hardcodeado: el remitente debe estar configurado en BD.
        if not config:
            logger.error("[NOTIFY] No hay configuración de sender en BD para %s", departamento)
            raise ValueError(f"No hay configuracion de remitente para {departamento}")
        
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
        id_oportunidad: UUID,
        modulo_origen: str = "simulacion"
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
            modulo_origen: Módulo que generó la notificación ('simulacion', 'levantamientos')
        """
        # Enmascarar PII para logs
        email_parts = recipient_email.split('@')
        if len(email_parts) == 2:
            masked_email = f"{email_parts[0][:3]}***@{email_parts[1]}"
        else:
            masked_email = "***@***"
        
        # Obtener usuario_id desde email
        usuario_id = await self.db.get_user_id_by_email(conn, recipient_email)
        
        if not usuario_id:
            # No loguear email completo - usar identificador anónimo
            logger.warning(f"[NOTIFY] Usuario no encontrado para notificacion en Opp: {id_oportunidad} (email: {masked_email})")
            return
        
        # Crear notificación usando NotificationsService
        notif_service = get_notifications_service()
        notification_data = await notif_service.create_notification(
            conn=conn,
            usuario_id=usuario_id,
            tipo=tipo,
            titulo=titulo,
            mensaje=mensaje,
            id_oportunidad=id_oportunidad,
            modulo_origen=modulo_origen
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
    
    async def _get_vacaciones_bcc_emails(self, conn, trigger_value: str) -> set[str]:
        bcc = await self._get_emails_for_event(
            conn,
            trigger_value,
            "CCO",
            VACACIONES_REGLAS_MODULOS,
        )
        if bcc:
            return bcc

        raw = await ConfigService.get_global_config(conn, "VACACIONES_CCO_EMAILS", "", str)
        normalized = raw.replace(";", ",")
        return {e.strip() for e in normalized.split(",") if e.strip()}

    async def _send_email(
        self,
        to_emails: Set[str],
        cc_emails: Set[str],
        subject: str,
        html_body: str,
        sender_email: str,  # Email del usuario que ejecuta la accion
        attachments_files: Optional[list[dict]] = None,
        bcc_emails: Optional[set[str]] = None,
    ) -> bool:
        """
        Envía email usando Application-only token de Microsoft Graph.

        Args:
            to_emails: Destinatarios principales (TO)
            cc_emails: Correos en copia (CC)
            bcc_emails: Correos en copia oculta (CCO)
            subject: Asunto del email
            html_body: Cuerpo del email en HTML
            sender_email: Email del usuario autenticado que ejecuta la accion (FROM)
        """
        if settings.DEBUG_MODE:
            logger.debug("[NOTIFY][DEV] Email suprimido (DEBUG_MODE): subject=%s", subject)
            return True
        if not to_emails:
            logger.info("[NOTIFY] No hay destinatarios, email no enviado")
            return False
        
        # Evitar duplicados: quitar TO de CC
        cc_emails = cc_emails - to_emails
        
        try:
            # Obtener token de aplicación (no requiere usuario logueado)
            app_token = await self.ms_auth.get_application_token()
            
            if not app_token:
                logger.error("[NOTIFY] No se pudo obtener token de aplicacion")
                return False
            
            # Enviar email via Microsoft Graph API
            bcc = (bcc_emails or set()) - to_emails - cc_emails
            success, msg = await self.ms_auth.send_email_with_attachments(
                access_token=app_token,
                from_email=sender_email,
                subject=subject,
                body=html_body,
                recipients=list(to_emails),
                cc_recipients=list(cc_emails) if cc_emails else None,
                bcc_recipients=list(bcc) if bcc else None,
                importance="normal",
                attachments_files=attachments_files,
            )

            if success:
                logger.info("[NOTIFY] Email enviado - TO: %d, CC: %d, BCC: %d", len(to_emails), len(cc_emails), len(bcc))
                return True
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
                return False

        except httpx.HTTPError as e:
            # Error de red o API de Microsoft Graph
            logger.error(f"[NOTIFY] Error de red/Graph API al enviar email: {e}", exc_info=True)
            return False
        except asyncpg.PostgresError as e:
            # Error de base de datos (si aplica)
            logger.error(f"[NOTIFY] Error de BD al enviar email: {e}", exc_info=True)
            return False


    # ===== VACACIONES =====

    async def _get_rh_emails_cc(self, conn) -> set[str]:
        return await self.db.get_rh_emails(conn)

    @staticmethod
    def _vacaciones_hito_label(hito: str) -> str:
        labels = {
            "t2": "dos dias habiles",
            "t1": "un dia habil",
            "manual": "breve",
        }
        return labels.get(hito, "pocos dias")

    @staticmethod
    def _vacaciones_detalle_url(solicitud_id: UUID | str) -> str:
        return f"{settings.APP_BASE_URL}/vacaciones/solicitudes/{solicitud_id}/abrir"

    @staticmethod
    def _hora_fields(solicitud: dict) -> dict:
        return {
            "hora_llegada": solicitud["hora_llegada"].strftime("%H:%M") if solicitud.get("hora_llegada") else None,
            "hora_salida": solicitud["hora_salida"].strftime("%H:%M") if solicitud.get("hora_salida") else None,
        }

    async def notify_periodo_expira(self, conn, empleado: dict, periodo: dict) -> None:
        """Notifica por email al empleado y CC a RH cuando un periodo esta por expirar."""
        try:
            if not empleado.get("email"):
                logger.info("[NOTIFY] Periodo por expirar sin email de empleado: %s", empleado.get("id_usuario"))
                return
            cc = await self._get_rh_emails_cc(conn)
            tiene_prorroga = periodo.get("tiene_prorroga", False)
            html = self._render_template("shared/emails/vacaciones/periodo_expira.html", {
                "empleado_nombre": empleado["nombre"],
                "num_periodo": periodo["num_periodo"],
                "dias_restantes": periodo["dias_restantes"],
                "dias_para_expiracion": periodo["dias_para_expiracion"],
                "fecha_expiracion": periodo["fecha_expiracion_efectiva"].strftime("%d/%m/%Y"),
                "tiene_prorroga": tiene_prorroga,
                "base_url": settings.APP_BASE_URL,
            })
            sender = await self._get_notification_sender(conn)
            asunto = "Prorroga de vacaciones por expirar" if tiene_prorroga else "Periodo de vacaciones por expirar"
            await self._send_email(
                {empleado["email"]},
                cc,
                asunto,
                html,
                sender["email"],
            )
        except asyncpg.PostgresError as e:
            logger.error("[NOTIFY] BD error en notify_periodo_expira: %s", e, exc_info=True)
        except httpx.HTTPError as e:
            logger.error("[NOTIFY] HTTP error en notify_periodo_expira: %s", e, exc_info=True)
        except (AttributeError, KeyError, TemplateError, TypeError, ValueError, RuntimeError) as e:
            logger.error("[NOTIFY] Error en notify_periodo_expira: %s", e, exc_info=True)

    async def notify_solicitud_vencida(
        self,
        conn,
        solicitud: dict,
        to_emails: set[str],
        cc_emails: set[str],
    ) -> None:
        """Notifica por email una solicitud pendiente vencida."""
        try:
            if not to_emails:
                logger.info("[NOTIFY] Solicitud vencida sin destinatarios: %s", solicitud.get("id"))
                return
            html = self._render_template("shared/emails/vacaciones/solicitud_vencida.html", {
                "solicitud_id": str(solicitud["id"]),
                "solicitante_nombre": solicitud["solicitante_nombre"],
                "tipo_nombre": solicitud["tipo_nombre"],
                "fecha_inicio": solicitud["fecha_inicio"].strftime("%d/%m/%Y"),
                "fecha_fin": solicitud["fecha_fin"].strftime("%d/%m/%Y"),
                "base_url": settings.APP_BASE_URL,
                "detalle_url": self._vacaciones_detalle_url(solicitud["id"]),
            })
            sender = await self._get_notification_sender(conn)
            await self._send_email(
                to_emails,
                cc_emails,
                f"Solicitud vencida pendiente: {solicitud['tipo_nombre']}",
                html,
                sender["email"],
            )
        except asyncpg.PostgresError as e:
            logger.error("[NOTIFY] BD error en notify_solicitud_vencida: %s", e, exc_info=True)
        except httpx.HTTPError as e:
            logger.error("[NOTIFY] HTTP error en notify_solicitud_vencida: %s", e, exc_info=True)
        except (AttributeError, KeyError, TemplateError, TypeError, ValueError, RuntimeError) as e:
            logger.error("[NOTIFY] Error en notify_solicitud_vencida: %s", e, exc_info=True)

    async def notify_pending_vacation_approval(
        self,
        conn,
        solicitud: dict,
        to_emails: set[str],
        cc_emails: set[str],
        hito: str,
    ) -> None:
        """Notifica a responsables/RH que una solicitud inicia pronto y sigue pendiente."""
        try:
            if not to_emails:
                logger.info("[NOTIFY] Recordatorio de aprobacion sin destinatarios: %s", solicitud.get("id"))
                return
            hito_label = self._vacaciones_hito_label(hito)
            html = self._render_template("shared/emails/vacaciones/solicitud_pendiente_aprobacion.html", {
                "solicitud_id": str(solicitud["id"]),
                "solicitante_nombre": solicitud["solicitante_nombre"],
                "tipo_nombre": solicitud["tipo_nombre"],
                "fecha_inicio": solicitud["fecha_inicio"].strftime("%d/%m/%Y"),
                "fecha_fin": solicitud["fecha_fin"].strftime("%d/%m/%Y"),
                "dias": solicitud["dias_solicitados"],
                "fecha_presentarse": solicitud["fecha_presentarse"].strftime("%d/%m/%Y"),
                **self._hora_fields(solicitud),
                "observaciones": solicitud.get("observaciones"),
                "hito_label": hito_label,
                "base_url": settings.APP_BASE_URL,
                "detalle_url": self._vacaciones_detalle_url(solicitud["id"]),
            })
            sender = await self._get_notification_sender(conn)
            await self._send_email(
                to_emails,
                cc_emails,
                f"Solicitud pendiente de aprobacion: {solicitud['tipo_nombre']} - {solicitud['solicitante_nombre']}",
                html,
                sender["email"],
            )
        except asyncpg.PostgresError as e:
            logger.error("[NOTIFY] BD error en notify_pending_vacation_approval: %s", e, exc_info=True)
        except httpx.HTTPError as e:
            logger.error("[NOTIFY] HTTP error en notify_pending_vacation_approval: %s", e, exc_info=True)
        except (AttributeError, KeyError, TemplateError, TypeError, ValueError, RuntimeError) as e:
            logger.error("[NOTIFY] Error en notify_pending_vacation_approval: %s", e, exc_info=True)

    async def notify_vacation_pending_requester(self, conn, solicitud: dict, hito: str) -> None:
        """Notifica al solicitante que su solicitud sigue pendiente de aprobacion."""
        try:
            solicitante_email = solicitud.get("solicitante_email")
            if not solicitante_email:
                logger.info("[NOTIFY] Recordatorio a solicitante sin email: %s", solicitud.get("id"))
                return
            hito_label = self._vacaciones_hito_label(hito)
            html = self._render_template("shared/emails/vacaciones/solicitud_pendiente_solicitante.html", {
                "solicitante_nombre": solicitud["solicitante_nombre"],
                "tipo_nombre": solicitud["tipo_nombre"],
                "fecha_inicio": solicitud["fecha_inicio"].strftime("%d/%m/%Y"),
                "fecha_fin": solicitud["fecha_fin"].strftime("%d/%m/%Y"),
                "dias": solicitud["dias_solicitados"],
                "hito_label": hito_label,
                "solicitud_id": str(solicitud["id"]),
                "base_url": settings.APP_BASE_URL,
                "detalle_url": self._vacaciones_detalle_url(solicitud["id"]),
            })
            sender = await self._get_notification_sender(conn)
            await self._send_email(
                {solicitante_email},
                set(),
                f"Tu solicitud de {solicitud['tipo_nombre'].lower()} sigue pendiente",
                html,
                sender["email"],
            )

            await self._save_and_broadcast(
                conn=conn,
                recipient_email=solicitante_email,
                tipo="CAMBIO_ESTATUS",
                titulo="Solicitud pendiente",
                mensaje=f"{solicitud['tipo_nombre']} aun no ha sido aprobada",
                id_oportunidad=None,
                modulo_origen="vacaciones",
            )
        except asyncpg.PostgresError as e:
            logger.error("[NOTIFY] BD error en notify_vacation_pending_requester: %s", e, exc_info=True)
        except httpx.HTTPError as e:
            logger.error("[NOTIFY] HTTP error en notify_vacation_pending_requester: %s", e, exc_info=True)
        except (AttributeError, KeyError, TemplateError, TypeError, ValueError, RuntimeError) as e:
            logger.error("[NOTIFY] Error en notify_vacation_pending_requester: %s", e, exc_info=True)

    async def notify_vacation_request(self, conn, solicitud: dict, aprobador_email: str) -> None:
        """Notifica al aprobador cuando el empleado envía una solicitud de ausencia."""
        try:
            aprobador_nombre = (
                await self.db.get_user_name_by_email(conn, aprobador_email)
            ) or aprobador_email

            html = self._render_template("shared/emails/vacaciones/solicitud_recibida.html", {
                "aprobador_nombre": aprobador_nombre,
                "solicitante_nombre": solicitud["solicitante_nombre"],
                "tipo_nombre": solicitud["tipo_nombre"],
                "fecha_inicio": solicitud["fecha_inicio"].strftime("%d/%m/%Y"),
                "fecha_fin": solicitud["fecha_fin"].strftime("%d/%m/%Y"),
                "dias": solicitud["dias_solicitados"],
                "fecha_presentarse": solicitud["fecha_presentarse"].strftime("%d/%m/%Y"),
                **self._hora_fields(solicitud),
                "observaciones": solicitud.get("observaciones"),
                "solicitud_id": str(solicitud["id"]),
                "base_url": settings.APP_BASE_URL,
                "detalle_url": self._vacaciones_detalle_url(solicitud["id"]),
            })
            sender = await self._get_notification_sender(conn)
            await self._send_email(
                {aprobador_email},
                set(),
                f"Nueva Solicitud de {solicitud['tipo_nombre']} - {solicitud['solicitante_nombre']}",
                html,
                sender["email"],
            )

            await self._save_and_broadcast(
                conn=conn,
                recipient_email=aprobador_email,
                tipo="ASIGNACION",
                titulo=f"Nueva solicitud de {solicitud['solicitante_nombre']}",
                mensaje=f"{solicitud['tipo_nombre']} · {solicitud['dias_solicitados']} días hábiles",
                id_oportunidad=None,
                modulo_origen="vacaciones",
            )
        except asyncpg.PostgresError as e:
            logger.error("[NOTIFY] BD error en notify_vacation_request: %s", e, exc_info=True)
        except httpx.HTTPError as e:
            logger.error("[NOTIFY] HTTP error en notify_vacation_request: %s", e, exc_info=True)
        except (AttributeError, KeyError, TemplateError, TypeError, ValueError, RuntimeError) as e:
            logger.error("[NOTIFY] Error en notify_vacation_request: %s", e, exc_info=True)

    async def notify_vacation_approved(self, conn, solicitud: dict) -> None:
        """Notifica al solicitante + CC a RH + CCO configurado cuando la solicitud es aprobada."""
        try:
            cc = await self._get_rh_emails_cc(conn)
            bcc = await self._get_vacaciones_bcc_emails(conn, VACACIONES_EVENTO_APROBADA)

            html = self._render_template("shared/emails/vacaciones/solicitud_aprobada.html", {
                "solicitante_nombre": solicitud["solicitante_nombre"],
                "aprobador_nombre": solicitud.get("aprobado_por_nombre", ""),
                "tipo_nombre": solicitud["tipo_nombre"],
                "fecha_inicio": solicitud["fecha_inicio"].strftime("%d/%m/%Y"),
                "fecha_fin": solicitud["fecha_fin"].strftime("%d/%m/%Y"),
                "dias": solicitud["dias_solicitados"],
                "fecha_presentarse": solicitud["fecha_presentarse"].strftime("%d/%m/%Y"),
                **self._hora_fields(solicitud),
                "solicitud_id": str(solicitud["id"]),
                "base_url": settings.APP_BASE_URL,
                "detalle_url": self._vacaciones_detalle_url(solicitud["id"]),
            })
            sender = await self._get_notification_sender(conn)
            attachments = []
            try:
                from modules.vacaciones.service import generar_pdf_solicitud, _generar_folio
                pdf_bytes = await generar_pdf_solicitud(conn, solicitud["id"])
                attachments.append({
                    "name": f"{_generar_folio(solicitud)}.pdf",
                    "contentType": "application/pdf",
                    "content_bytes": pdf_bytes,
                })
            except ValueError as e:
                logger.error("[NOTIFY] No se pudo generar PDF de solicitud aprobada: %s", e)
            await self._send_email(
                {solicitud["solicitante_email"]},
                cc,
                f"Solicitud aprobada: {solicitud['tipo_nombre']} - {solicitud['solicitante_nombre']}",
                html,
                sender["email"],
                attachments_files=attachments,
                bcc_emails=bcc,
            )

            await self._save_and_broadcast(
                conn=conn,
                recipient_email=solicitud["solicitante_email"],
                tipo="CAMBIO_ESTATUS",
                titulo="Solicitud aprobada",
                mensaje=f"{solicitud['tipo_nombre']} · {solicitud['fecha_inicio'].strftime('%d/%m')} al {solicitud['fecha_fin'].strftime('%d/%m/%Y')}",
                id_oportunidad=None,
                modulo_origen="vacaciones",
            )
        except asyncpg.PostgresError as e:
            logger.error("[NOTIFY] BD error en notify_vacation_approved: %s", e, exc_info=True)
        except httpx.HTTPError as e:
            logger.error("[NOTIFY] HTTP error en notify_vacation_approved: %s", e, exc_info=True)
        except (AttributeError, KeyError, TemplateError, TypeError, ValueError, RuntimeError) as e:
            logger.error("[NOTIFY] Error en notify_vacation_approved: %s", e, exc_info=True)

    async def notify_vacation_rejected(self, conn, solicitud: dict, motivo: str) -> None:
        """Notifica al solicitante + CC a RH + CCO configurado cuando la solicitud es rechazada."""
        try:
            cc = await self._get_rh_emails_cc(conn)
            bcc = await self._get_vacaciones_bcc_emails(conn, VACACIONES_EVENTO_RECHAZADA)

            html = self._render_template("shared/emails/vacaciones/solicitud_rechazada.html", {
                "solicitante_nombre": solicitud["solicitante_nombre"],
                "aprobador_nombre": solicitud.get("aprobado_por_nombre", ""),
                "tipo_nombre": solicitud["tipo_nombre"],
                "fecha_inicio": solicitud["fecha_inicio"].strftime("%d/%m/%Y"),
                "fecha_fin": solicitud["fecha_fin"].strftime("%d/%m/%Y"),
                "motivo": motivo,
                "solicitud_id": str(solicitud["id"]),
                "base_url": settings.APP_BASE_URL,
                "detalle_url": self._vacaciones_detalle_url(solicitud["id"]),
            })
            sender = await self._get_notification_sender(conn)
            await self._send_email({solicitud["solicitante_email"]}, cc, f"Solicitud de {solicitud['tipo_nombre'].lower()} no aprobada", html, sender["email"], bcc_emails=bcc)

            await self._save_and_broadcast(
                conn=conn,
                recipient_email=solicitud["solicitante_email"],
                tipo="CAMBIO_ESTATUS",
                titulo="Solicitud rechazada",
                mensaje=f"{solicitud['tipo_nombre']} · Motivo: {motivo[:80]}",
                id_oportunidad=None,
                modulo_origen="vacaciones",
            )
        except asyncpg.PostgresError as e:
            logger.error("[NOTIFY] BD error en notify_vacation_rejected: %s", e, exc_info=True)
        except httpx.HTTPError as e:
            logger.error("[NOTIFY] HTTP error en notify_vacation_rejected: %s", e, exc_info=True)
        except (AttributeError, KeyError, TemplateError, TypeError, ValueError, RuntimeError) as e:
            logger.error("[NOTIFY] Error en notify_vacation_rejected: %s", e, exc_info=True)


def get_notification_service():
    """Helper para inyección de dependencias."""
    return NotificationService()
