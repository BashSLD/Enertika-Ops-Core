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
    # conn = Depends(get_db_connection),  <-- REMOVED: Evitar bloquear conexión DB en stream infinito
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
        """
        Generator que mantiene conexión SSE abierta con PostgreSQL LISTEN/NOTIFY.
        Implementa estrategia híbrida: LISTEN para multi-worker + fallback local.
        """
        queue = asyncio.Queue()
        channel = f"user_notif_{str(usuario_id).replace('-', '_')}"
        
        # Conexión dedicada para LISTEN (fuera del pool)
        from core.database import get_db_pool
        pool = await get_db_pool()
        listen_conn = None
        
        try:
            # 1. Adquirir conexión dedicada para LISTEN
            listen_conn = await pool.acquire()
            
            # 2. Callback cuando llega NOTIFY de PostgreSQL
            def pg_listener(connection, pid, channel_name, payload):
                """
                Callback invocado por asyncpg cuando llega NOTIFY.
                Thread-safe via create_task.
                """
                try:
                    data = json.loads(payload)
                    asyncio.create_task(queue.put(data))
                    logger.debug(f"[SSE-PG] Notificación recibida en {channel_name}")
                except json.JSONDecodeError as e:
                    logger.error(f"[SSE-PG] Payload inválido: {e}")
            
            # 3. Registrar listener en PostgreSQL
            await listen_conn.add_listener(channel, pg_listener)
            logger.info(f"[SSE-PG] Listener registrado: {channel}")
            
            # 4. FALLBACK: También registrar en dict local (resiliencia)
            from .service import active_connections
            active_connections[usuario_id] = queue
            logger.info(f"[SSE-LOCAL] Usuario {usuario_id} registrado localmente")
            
            # 5. Enviar notificaciones pendientes (al conectar)
            try:
                pending = await asyncio.wait_for(
                    service.get_pending_notifications(listen_conn, usuario_id, limit=5),
                    timeout=2.0
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
                logger.warning(f"[SSE] Timeout cargando pendientes para {usuario_id}")
            except Exception as e:
                logger.error(f"[SSE] Error cargando pendientes: {e}")
            
            # 6. Mantener stream abierto (escuchar queue que recibe de NOTIFY o fallback)
            while True:
                if await request.is_disconnected():
                    logger.info(f"[SSE] Cliente {usuario_id} desconectado")
                    break
                
                try:
                    # Esperar notificación (puede venir de NOTIFY o fallback local)
                    # Timeout de 45s: evita que Gunicorn (timeout=120s) mate el worker
                    notification_data = await asyncio.wait_for(queue.get(), timeout=45.0)
                    
                    yield {
                        "event": "notification",
                        "data": json.dumps(notification_data)
                    }
                except asyncio.TimeoutError:
                    # Heartbeat para mantener vivo el worker de Gunicorn
                    yield {
                        "event": "heartbeat",
                        "data": json.dumps({"status": "alive"})
                    }
        
        except asyncio.CancelledError:
            logger.info(f"[SSE] Stream cancelado para {usuario_id}")
        except Exception as e:
            logger.error(f"[SSE] Error en stream: {e}", exc_info=True)
        finally:
            # 7. Cleanup completo
            if listen_conn:
                try:
                    await listen_conn.remove_listener(channel, pg_listener)
                    await pool.release(listen_conn)
                    logger.info(f"[SSE-PG] Listener removido: {channel}")
                except Exception as e:
                    logger.warning(f"[SSE-PG] Error en cleanup: {e}")
            
            # Remover de dict local
            from .service import active_connections
            if usuario_id in active_connections:
                del active_connections[usuario_id]
                logger.info(f"[SSE-LOCAL] Usuario {usuario_id} removido localmente")
    
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
