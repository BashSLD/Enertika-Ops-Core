# core/notifications/router.py
"""
Router para endpoints de notificaciones.
Maneja HTTP/SSE requests, delega lógica al Service Layer.

Patrón recomendado por GUIA_MAESTRA: Router delgado, Service robusto.
"""
from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse
from uuid import UUID
import asyncio
import json
import logging

from core.security import get_current_user_context
from core.database import get_db_connection
from .service import get_notifications_service, NotificationsService

logger = logging.getLogger("NotificationsRouter")

router = APIRouter(
    prefix="/notifications",
    tags=["Notificaciones en Tiempo Real"]
)


@router.get("/stream")
async def stream_notifications(
    request: Request,
    context = Depends(get_current_user_context),
    conn = Depends(get_db_connection),
    service: NotificationsService = Depends(get_notifications_service)
):
    """
    Endpoint SSE para streaming de notificaciones en tiempo real.
    
    Cliente se conecta via EventSource (JavaScript) y recibe:
    - Notificaciones pendientes (no leídas) al conectar
    - Nuevas notificaciones en tiempo real mientras está conectado
    
    Returns:
        EventSourceResponse: Stream SSE con eventos tipo 'notification'
    """
    usuario_id = context['user_db_id']
    
    async def event_generator():
        """Generator que mantiene conexión SSE abierta."""
        # 1. Registrar conexión PRIMERO (no bloqueante)
        queue = service.register_connection(usuario_id)
        
        try:
            # 2. Enviar notificaciones pendientes EN BACKGROUND con timeout
            #    NO bloquear el stream esperando la query
            try:
                pending = await asyncio.wait_for(
                    service.get_pending_notifications(conn, usuario_id, limit=5),  # Reducido a 5
                    timeout=1.0  # Timeout de 1 segundo
                )
                
                for notif in pending:
                    yield {
                        "event": "notification",
                        "data": json.dumps({
                            "id": str(notif['id']),
                            "type": notif['tipo'],
                            "title": notif['titulo'],
                            "message": notif['mensaje'],
                            "oportunidad_id": str(notif['id_oportunidad']) if notif['id_oportunidad'] else None,
                            "created_at": notif['created_at'].isoformat()
                        })
                    }
            except asyncio.TimeoutError:
                logger.warning(f"[SSE] Timeout al cargar notificaciones pendientes para {usuario_id}")
                # Continuar sin notificaciones pendientes
            except Exception as e:
                logger.error(f"[SSE] Error cargando pendientes: {e}")
                # Continuar sin notificaciones pendientes
            
            # 3. Mantener conexión abierta esperando nuevas notificaciones
            while True:
                # Esperar nueva notificación en la queue con timeout para detectar desconexiones
                try:
                    notification_data = await asyncio.wait_for(queue.get(), timeout=30.0)
                    
                    yield {
                        "event": "notification",
                        "data": json.dumps(notification_data)
                    }
                except asyncio.TimeoutError:
                    # Enviar heartbeat cada 30s para mantener conexión viva
                    yield {
                        "event": "heartbeat",
                        "data": json.dumps({"status": "alive"})
                    }
                
        except asyncio.CancelledError:
            # Cliente desconectado
            logger.info(f"[SSE] Cliente desconectado: {usuario_id}")
        finally:
            # Limpiar conexión
            service.unregister_connection(usuario_id)
    
    return EventSourceResponse(
        event_generator(),
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Para nginx
            "Connection": "keep-alive"
        }
    )


@router.post("/mark-read/{notification_id}")
async def mark_notification_as_read(
    notification_id: UUID,
    context = Depends(get_current_user_context),
    conn = Depends(get_db_connection),
    service: NotificationsService = Depends(get_notifications_service)
):
    """
    Marca una notificación como leída.
    
    Args:
        notification_id: UUID de la notificación
        
    Returns:
        Status de la operación
    """
    usuario_id = context['user_db_id']
    await service.mark_as_read(conn, notification_id, usuario_id)
    
    return {"status": "ok"}


@router.get("/count")
async def get_unread_count(
    context = Depends(get_current_user_context),
    conn = Depends(get_db_connection),
    service: NotificationsService = Depends(get_notifications_service)
):
    """
    Retorna cantidad de notificaciones no leídas.
    
    Returns:
        Cantidad de notificaciones pendientes
    """
    usuario_id = context['user_db_id']
    count = await service.get_unread_count(conn, usuario_id)
    
    return {"unread_count": count}


@router.get("/list")
async def list_notifications(
    limit: int = 20,
    context = Depends(get_current_user_context),
    conn = Depends(get_db_connection),
    service: NotificationsService = Depends(get_notifications_service)
):
    """
    Lista todas las notificaciones del usuario (leídas y no leídas).
    
    Args:
        limit: Máximo de notificaciones a retornar
        
    Returns:
        Lista de notificaciones
    """
    usuario_id = context['user_db_id']
    
    query = """
        SELECT id, tipo, titulo, mensaje, id_oportunidad, leida, created_at
        FROM tb_notificaciones
        WHERE usuario_id = $1
        ORDER BY created_at DESC
        LIMIT $2
    """
    rows = await conn.fetch(query, usuario_id, limit)
    
    return {
        "notifications": [
            {
                "id": str(r['id']),
                "type": r['tipo'],
                "title": r['titulo'],
                "message": r['mensaje'],
                "oportunidad_id": str(r['id_oportunidad']) if r['id_oportunidad'] else None,
                "read": r['leida'],
                "created_at": r['created_at'].isoformat()
            }
            for r in rows
        ]
    }


@router.get("/stats")
async def get_notification_stats(
    context = Depends(get_current_user_context),
    service: NotificationsService = Depends(get_notifications_service)
):
    """
    Estadísticas de notificaciones (para debugging/monitoring).
    Solo disponible para admins.
    
    Returns:
        Estadísticas del sistema de notificaciones
    """
    if context.get('role') != 'ADMIN':
        return {"error": "Acceso denegado"}
    
    return {
        "active_connections": service.get_active_connections_count()
    }
