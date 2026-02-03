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
from core.database import get_db_connection, get_db_pool
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
    service: NotificationsService = Depends(get_notifications_service)
):
    """
    Endpoint SSE para streaming de notificaciones en tiempo real.
    
    Patrón: MULTIPLEXER
    - No abre conexión a BD.
    - Se suscribe al Queue en memoria del Service.
    """
    usuario_id = context['user_db_id']
    
    async def event_generator():
        """
        Consume notificaciones del Queue en memoria.
        """
        # 1. Registrarse y obtener Queue
        # Si es el primer cliente, el Service activará el LISTEN
        queue = await service.register_connection(usuario_id)
        
        try:
            logger.info(f"[SSE] Stream iniciado para usuario {usuario_id}")

            # 2. Enviar notificaciones pendientes (al conectar)
            # Requiere conexión temporal para consulta inicial
            try:
                # Usar una conexión del pool solo para esto
                pool = await get_db_pool()
                async with pool.acquire() as conn:
                    pending = await asyncio.wait_for(
                        service.get_pending_notifications(conn, usuario_id, limit=5),
                        timeout=5.0
                    )
                    
                    for notif in pending:
                        yield {
                            "event": "pending",
                            "data": json.dumps({
                                "id": str(notif['id']),
                                "type": notif['tipo'],
                                "title": notif['titulo'],
                                "message": notif['mensaje'],
                                "oportunidad_id": str(notif['id_oportunidad']) if notif['id_oportunidad'] else None,
                                "created_at": notif['created_at'].isoformat()
                            })
                        }
            except Exception as e:
                logger.error(f"[SSE] Error cargando pendientes: {e}")
            
            # 3. Loop de eventos (Queue -> SSE)
            while True:
                if await request.is_disconnected():
                    logger.info(f"[SSE] Cliente {usuario_id} desconectado")
                    break
                
                try:
                    # Esperar notificación del Queue
                    notification_data = await asyncio.wait_for(queue.get(), timeout=15.0)
                    
                    yield {
                        "event": "notification",
                        "data": json.dumps(notification_data),
                        "retry": 5000
                    }
                except asyncio.TimeoutError:
                    # Heartbeat
                    yield {
                        "event": "heartbeat",
                        "data": json.dumps({"status": "alive"}),
                        "retry": 5000
                    }
        
        except asyncio.CancelledError:
            logger.info(f"[SSE] Stream cancelado para {usuario_id}")
        except Exception as e:
            logger.error(f"[SSE] Error en stream: {e}", exc_info=True)
        finally:
            # 4. Desregistrar (Si es el último, Service cierra LISTEN)
            await service.unregister_connection(usuario_id)

    return EventSourceResponse(
        event_generator(),
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
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


@router.delete("/all")
async def delete_all_notifications(
    context = Depends(get_current_user_context),
    conn = Depends(get_db_connection),
    service: NotificationsService = Depends(get_notifications_service)
):
    """
    "Elimina" TODAS las notificaciones (Soft Delete: Marca todas como leídas).
    """
    usuario_id = context['user_db_id']
    count = await service.mark_all_read(conn, usuario_id)
    
    return {"status": "ok", "deleted_count": count}


@router.delete("/{notification_id}")
async def delete_notification(
    notification_id: UUID,
    context = Depends(get_current_user_context),
    conn = Depends(get_db_connection),
    service: NotificationsService = Depends(get_notifications_service)
):
    """
    "Elimina" una notificación (Soft Delete: Marca como leída).
    Idempotente: Si ya no existe o ya está leída, retorna OK para evitar errores en frontend.
    """
    usuario_id = context['user_db_id']
    # Cambiamos lógica a Marcar como Leída según solicitud
    await service.mark_as_read(conn, notification_id, usuario_id)
    
    # Siempre retornar OK, incluso si ya estaba leída/borrada
    return {"status": "ok"}


@router.get("/count")
async def get_unread_count(
    context = Depends(get_current_user_context),
    conn = Depends(get_db_connection),
    service: NotificationsService = Depends(get_notifications_service)
):
    """
    Retorna cantidad de notificaciones no leídas.
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
    Lista notificaciones NO LEÍDAS (estilo Inbox).
    Las leídas se consideran "archivadas".
    """
    usuario_id = context['user_db_id']
    
    query = """
        SELECT id, tipo, titulo, mensaje, id_oportunidad, leida, created_at
        FROM tb_notificaciones
        WHERE usuario_id = $1 AND leida = false
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
