"""
Servicio de traspasos de proyectos entre areas.
Logica de negocio compartida por Ingenieria, Construccion, OyM y Proyectos.
"""
from uuid import UUID, uuid4
from typing import Optional, List, Dict, Any, Set
import asyncpg
import logging

from .db_service import TransferDBService, get_transfer_db_service

logger = logging.getLogger("TransferService")

AREA_FLOW = {
    "INGENIERIA": "CONSTRUCCION",
    "CONSTRUCCION": "OYM",
}

AREA_LABELS = {
    "INGENIERIA": "Ingenieria",
    "CONSTRUCCION": "Construccion",
    "OYM": "O&M",
}

AREA_MODULE_SLUGS = {
    "INGENIERIA": "ingenieria",
    "CONSTRUCCION": "construccion",
    "OYM": "oym",
}


class TransferService:

    def __init__(self):
        self.db = get_transfer_db_service()

    async def get_proyectos_by_area(
        self, conn, area: str,
        q: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        return await self.db.get_proyectos_by_area(conn, area, q, limit)

    async def get_proyectos_pendientes_recepcion(
        self, conn, area: str
    ) -> List[Dict[str, Any]]:
        return await self.db.get_proyectos_pendientes_recepcion(conn, area)

    async def get_all_proyectos(
        self, conn,
        area_filter: Optional[str] = None,
        status_filter: Optional[str] = None,
        q: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        return await self.db.get_all_proyectos(
            conn, area_filter, status_filter, q, limit
        )

    async def get_proyecto_detalle(
        self, conn, id_proyecto: UUID
    ) -> Dict[str, Any]:
        proyecto = await self.db.get_proyecto_detalle(conn, id_proyecto)
        if not proyecto:
            raise ValueError("Proyecto no encontrado")
        return proyecto

    async def get_documentos_checklist(
        self, conn, area_origen: str, area_destino: str
    ) -> List[Dict[str, Any]]:
        return await self.db.get_documentos_checklist(conn, area_origen, area_destino)

    async def get_motivos_rechazo(
        self, conn, area: str
    ) -> List[Dict[str, Any]]:
        return await self.db.get_motivos_rechazo(conn, area)

    async def enviar_traspaso(
        self, conn, id_proyecto: UUID,
        area_origen: str, area_destino: str,
        user_id: UUID, user_name: str,
        comentario: Optional[str] = None,
        documentos_ids: Optional[List[int]] = None
    ) -> Dict[str, Any]:
        # Validar flujo
        expected_destino = AREA_FLOW.get(area_origen)
        if not expected_destino or expected_destino != area_destino:
            raise ValueError(
                f"Traspaso no valido: {area_origen} -> {area_destino}"
            )

        # Validar que el proyecto esta en el area correcta
        proyecto = await self.db.get_proyecto_detalle(conn, id_proyecto)
        if not proyecto:
            raise ValueError("Proyecto no encontrado")

        if proyecto.get('area_actual') != area_origen:
            raise ValueError(
                f"El proyecto no esta en {AREA_LABELS.get(area_origen, area_origen)}"
            )

        # Validar documentos obligatorios
        docs_checklist = await self.db.get_documentos_checklist(
            conn, area_origen, area_destino
        )
        obligatorios = [d['id'] for d in docs_checklist if d['es_obligatorio']]
        docs_ids = documentos_ids or []

        faltantes = [doc_id for doc_id in obligatorios if doc_id not in docs_ids]
        if faltantes:
            raise ValueError(
                "Faltan documentos obligatorios por verificar"
            )

        try:
            id_traspaso = uuid4()

            traspaso = await self.db.crear_traspaso(
                conn, id_traspaso, id_proyecto,
                area_origen, area_destino,
                user_id, user_name, comentario
            )

            if docs_ids:
                await self.db.registrar_documentos_traspaso(
                    conn, id_traspaso, docs_ids, user_id
                )

            logger.info(
                "Traspaso enviado: %s -> %s, proyecto=%s, por=%s",
                area_origen, area_destino,
                proyecto.get('proyecto_id_estandar'), user_name
            )

            # Notificar a editores/admins del modulo destino
            await self._notify_traspaso_enviado(
                conn, proyecto, area_origen, area_destino,
                user_name, comentario
            )

            return traspaso

        except asyncpg.PostgresError:
            logger.exception("Error de BD al crear traspaso")
            raise

    async def recibir_traspaso(
        self, conn, id_traspaso: UUID,
        user_id: UUID, user_name: str
    ) -> Dict[str, Any]:
        traspaso = await self.db.get_traspaso_by_id(conn, id_traspaso)
        if not traspaso:
            raise ValueError("Traspaso no encontrado")

        if traspaso['status'] != 'ENVIADO':
            raise ValueError("Este traspaso ya fue procesado")

        try:
            await self.db.aceptar_traspaso(conn, id_traspaso, user_id, user_name)

            await self.db.actualizar_area_proyecto(
                conn, traspaso['id_proyecto'], traspaso['area_destino']
            )

            logger.info(
                "Traspaso aceptado: %s, proyecto=%s, por=%s",
                id_traspaso, traspaso.get('proyecto_id_estandar'), user_name
            )

            # Notificar al usuario que envio el traspaso
            await self._notify_traspaso_aceptado(
                conn, traspaso, user_name
            )

            return await self.db.get_traspaso_by_id(conn, id_traspaso)

        except asyncpg.PostgresError:
            logger.exception("Error de BD al aceptar traspaso")
            raise

    async def rechazar_traspaso(
        self, conn, id_traspaso: UUID,
        user_id: UUID, user_name: str,
        motivos_ids: Optional[List[int]] = None,
        comentario: Optional[str] = None
    ) -> Dict[str, Any]:
        traspaso = await self.db.get_traspaso_by_id(conn, id_traspaso)
        if not traspaso:
            raise ValueError("Traspaso no encontrado")

        if traspaso['status'] != 'ENVIADO':
            raise ValueError("Este traspaso ya fue procesado")

        try:
            await self.db.rechazar_traspaso(
                conn, id_traspaso, user_id, user_name, comentario
            )

            if motivos_ids:
                await self.db.registrar_motivos_rechazo(
                    conn, id_traspaso, motivos_ids
                )

            # Revertir area al origen
            await self.db.actualizar_area_proyecto(
                conn, traspaso['id_proyecto'], traspaso['area_origen']
            )

            logger.info(
                "Traspaso rechazado: %s, proyecto=%s, por=%s",
                id_traspaso, traspaso.get('proyecto_id_estandar'), user_name
            )

            # Obtener motivos de texto para la notificacion
            motivos_texto = []
            if motivos_ids:
                motivos_rows = await self.db.get_motivos_rechazo_traspaso(
                    conn, id_traspaso
                )
                motivos_texto = [m['motivo'] for m in motivos_rows]

            # Notificar al usuario que envio el traspaso
            await self._notify_traspaso_rechazado(
                conn, traspaso, user_name, comentario, motivos_texto
            )

            return await self.db.get_traspaso_by_id(conn, id_traspaso)

        except asyncpg.PostgresError:
            logger.exception("Error de BD al rechazar traspaso")
            raise

    async def get_historial_traspasos(
        self, conn, id_proyecto: UUID
    ) -> List[Dict[str, Any]]:
        historial = await self.db.get_historial_traspasos(conn, id_proyecto)

        for item in historial:
            if item.get('status') == 'RECHAZADO':
                motivos = await self.db.get_motivos_rechazo_traspaso(
                    conn, item['id_traspaso']
                )
                item['motivos_rechazo'] = motivos

        return historial

    async def get_kpis_area(self, conn, area: str) -> Dict[str, int]:
        return await self.db.get_kpis_area(conn, area)

    async def get_kpis_global(self, conn) -> Dict[str, Any]:
        return await self.db.get_kpis_global(conn)

    # ===== NOTIFICACIONES =====

    async def _get_module_editors(
        self, conn, module_slug: str
    ) -> List[Dict[str, Any]]:
        """
        Obtiene usuarios con rol editor o admin en un modulo.
        Estos son los "jefes" del area que deben recibir notificaciones.
        """
        rows = await conn.fetch("""
            SELECT u.id_usuario, u.nombre, u.email
            FROM tb_permisos_modulos pm
            JOIN tb_usuarios u ON pm.usuario_id = u.id_usuario
            JOIN tb_modulos_catalogo mc ON pm.modulo_id = mc.id
            WHERE mc.slug = $1
            AND pm.rol IN ('editor', 'admin')
            AND u.activo = true
            AND u.email IS NOT NULL
        """, module_slug)
        return [dict(r) for r in rows]

    async def _get_user_by_id(
        self, conn, user_id: UUID
    ) -> Optional[Dict[str, Any]]:
        row = await conn.fetchrow(
            "SELECT id_usuario, nombre, email FROM tb_usuarios WHERE id_usuario = $1",
            user_id
        )
        return dict(row) if row else None

    async def _notify_traspaso_enviado(
        self, conn,
        proyecto: Dict[str, Any],
        area_origen: str, area_destino: str,
        enviado_por: str, comentario: Optional[str]
    ):
        """
        Notifica a editores/admins del modulo destino que hay un traspaso pendiente.
        Ejemplo: Ingenieria envia -> notifica a jefe de Construccion.
        """
        try:
            dest_slug = AREA_MODULE_SLUGS.get(area_destino)
            if not dest_slug:
                return

            destinatarios = await self._get_module_editors(conn, dest_slug)
            if not destinatarios:
                logger.info(
                    "Sin destinatarios para notificacion de traspaso enviado a %s",
                    area_destino
                )
                return

            proyecto_id = proyecto.get('proyecto_id_estandar', 'N/A')
            cliente = proyecto.get('cliente_nombre', 'N/A')
            nombre_proyecto = proyecto.get('nombre_proyecto') or proyecto.get('nombre_corto', '')

            # SSE + Email
            await self._send_notifications(
                conn=conn,
                destinatarios=destinatarios,
                tipo='TRASPASO_ENVIADO',
                titulo=f'Traspaso pendiente: {proyecto_id}',
                mensaje=f'{enviado_por} envio {proyecto_id} de {AREA_LABELS.get(area_origen)} a {AREA_LABELS.get(area_destino)}',
                email_context={
                    'titulo': 'Nuevo Traspaso Pendiente',
                    'subtitulo': f'Proyecto pendiente de recepcion en {AREA_LABELS.get(area_destino)}',
                    'mensaje_intro': f'{enviado_por} ha enviado un proyecto que requiere tu revision y aceptacion.',
                    'proyecto_id': proyecto_id,
                    'proyecto_nombre': nombre_proyecto,
                    'cliente_nombre': cliente,
                    'area_origen': AREA_LABELS.get(area_origen, area_origen),
                    'area_destino': AREA_LABELS.get(area_destino, area_destino),
                    'accion_por_label': 'Enviado por',
                    'accion_por_nombre': enviado_por,
                    'comentario': comentario,
                    'modulo_url': dest_slug,
                    'cta_texto': f'Ir a {AREA_LABELS.get(area_destino)}',
                    'mensaje_cierre': 'Por favor revisa la documentacion y acepta o rechaza el traspaso.',
                    'header_color': '#2563EB',
                    'header_color_end': '#1D4ED8',
                    'accent_color': '#2563EB',
                },
                email_subject=f'Traspaso pendiente: {proyecto_id} - {cliente}',
                departamento=dest_slug.upper(),
            )

        except Exception:
            logger.exception("Error al notificar traspaso enviado")

    async def _notify_traspaso_aceptado(
        self, conn,
        traspaso: Dict[str, Any],
        aceptado_por: str
    ):
        """
        Notifica al usuario que envio el traspaso que fue aceptado.
        """
        try:
            enviado_por_id = traspaso.get('enviado_por')
            if not enviado_por_id:
                return

            usuario = await self._get_user_by_id(conn, enviado_por_id)
            if not usuario or not usuario.get('email'):
                return

            proyecto_id = traspaso.get('proyecto_id_estandar', 'N/A')
            area_destino = traspaso.get('area_destino', '')
            area_origen = traspaso.get('area_origen', '')
            origen_slug = AREA_MODULE_SLUGS.get(area_origen, 'proyectos')

            await self._send_notifications(
                conn=conn,
                destinatarios=[usuario],
                tipo='TRASPASO_ACEPTADO',
                titulo=f'Traspaso aceptado: {proyecto_id}',
                mensaje=f'{aceptado_por} acepto el traspaso de {proyecto_id} en {AREA_LABELS.get(area_destino)}',
                email_context={
                    'titulo': 'Traspaso Aceptado',
                    'subtitulo': f'El proyecto fue recibido en {AREA_LABELS.get(area_destino)}',
                    'mensaje_intro': f'{aceptado_por} ha aceptado el traspaso del proyecto.',
                    'proyecto_id': proyecto_id,
                    'proyecto_nombre': '',
                    'cliente_nombre': '',
                    'area_origen': AREA_LABELS.get(area_origen, area_origen),
                    'area_destino': AREA_LABELS.get(area_destino, area_destino),
                    'accion_por_label': 'Aceptado por',
                    'accion_por_nombre': aceptado_por,
                    'modulo_url': origen_slug,
                    'cta_texto': f'Ir a {AREA_LABELS.get(area_origen)}',
                    'mensaje_cierre': 'El proyecto ahora se encuentra en el area destino.',
                    'header_color': '#059669',
                    'header_color_end': '#047857',
                    'accent_color': '#059669',
                },
                email_subject=f'Traspaso aceptado: {proyecto_id}',
                departamento=origen_slug.upper(),
            )

        except Exception:
            logger.exception("Error al notificar traspaso aceptado")

    async def _notify_traspaso_rechazado(
        self, conn,
        traspaso: Dict[str, Any],
        rechazado_por: str,
        comentario: Optional[str],
        motivos: List[str]
    ):
        """
        Notifica al usuario que envio el traspaso que fue rechazado.
        """
        try:
            enviado_por_id = traspaso.get('enviado_por')
            if not enviado_por_id:
                return

            usuario = await self._get_user_by_id(conn, enviado_por_id)
            if not usuario or not usuario.get('email'):
                return

            proyecto_id = traspaso.get('proyecto_id_estandar', 'N/A')
            area_destino = traspaso.get('area_destino', '')
            area_origen = traspaso.get('area_origen', '')
            origen_slug = AREA_MODULE_SLUGS.get(area_origen, 'proyectos')

            await self._send_notifications(
                conn=conn,
                destinatarios=[usuario],
                tipo='TRASPASO_RECHAZADO',
                titulo=f'Traspaso rechazado: {proyecto_id}',
                mensaje=f'{rechazado_por} rechazo el traspaso de {proyecto_id}. El proyecto regresa a {AREA_LABELS.get(area_origen)}.',
                email_context={
                    'titulo': 'Traspaso Rechazado',
                    'subtitulo': f'El proyecto fue devuelto a {AREA_LABELS.get(area_origen)}',
                    'mensaje_intro': f'{rechazado_por} ha rechazado el traspaso. El proyecto regresa a tu area para corregir las observaciones.',
                    'proyecto_id': proyecto_id,
                    'proyecto_nombre': '',
                    'cliente_nombre': '',
                    'area_origen': AREA_LABELS.get(area_origen, area_origen),
                    'area_destino': AREA_LABELS.get(area_destino, area_destino),
                    'accion_por_label': 'Rechazado por',
                    'accion_por_nombre': rechazado_por,
                    'comentario': comentario,
                    'motivos_rechazo': motivos,
                    'modulo_url': origen_slug,
                    'cta_texto': f'Ir a {AREA_LABELS.get(area_origen)}',
                    'mensaje_cierre': 'Por favor corrige las observaciones y vuelve a enviar el traspaso.',
                    'header_color': '#DC2626',
                    'header_color_end': '#B91C1C',
                    'accent_color': '#DC2626',
                },
                email_subject=f'Traspaso rechazado: {proyecto_id}',
                departamento=origen_slug.upper(),
            )

        except Exception:
            logger.exception("Error al notificar traspaso rechazado")

    async def _send_notifications(
        self, conn,
        destinatarios: List[Dict[str, Any]],
        tipo: str,
        titulo: str,
        mensaje: str,
        email_context: Dict[str, Any],
        email_subject: str,
        departamento: str,
    ):
        """
        Envia notificaciones SSE + Email a una lista de destinatarios.
        Reutiliza la infraestructura existente de core/notifications y core/workflow.
        """
        from core.notifications.service import get_notifications_service
        from core.workflow.notification_service import get_notification_service
        from core.config import settings

        notif_service = get_notifications_service()
        email_service = get_notification_service()

        to_emails: Set[str] = set()

        for dest in destinatarios:
            usuario_id = dest.get('id_usuario')
            email = dest.get('email')
            nombre = dest.get('nombre', '')

            # SSE: crear notificacion en BD y broadcast
            if usuario_id:
                try:
                    notification_data = await notif_service.create_notification(
                        conn=conn,
                        usuario_id=usuario_id,
                        tipo=tipo,
                        titulo=titulo,
                        mensaje=mensaje,
                    )
                    await notif_service.broadcast_to_user(conn, usuario_id, notification_data)
                except Exception:
                    logger.exception(
                        "Error SSE para usuario %s en notificacion %s",
                        usuario_id, tipo
                    )

            # Recolectar emails para envio masivo
            if email:
                to_emails.add(email)
                email_context['destinatario_nombre'] = nombre

        # Email: enviar a todos los destinatarios
        if to_emails:
            try:
                email_context['base_url'] = settings.APP_BASE_URL

                html = email_service._render_template(
                    'shared/emails/transfers/traspaso_notification.html',
                    email_context
                )

                cc_emails = await email_service._get_cc_emails(conn, tipo)
                sender_config = await email_service._get_notification_sender(conn, departamento)

                await email_service._send_email(
                    to_emails, cc_emails, email_subject, html,
                    sender_config['email']
                )
            except Exception:
                logger.exception("Error al enviar email de notificacion %s", tipo)


def get_transfer_service() -> TransferService:
    return TransferService()
