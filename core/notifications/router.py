# core/notifications/router.py
"""
Router para endpoints de notificaciones.
Maneja HTTP/SSE requests, delega lógica al Service Layer.

Patrón recomendado por GUIA_MAESTRA: Router delgado, Service robusto.
"""
from typing import AsyncIterator, Optional
from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import AppStatus, EventSourceResponse
from uuid import UUID
import asyncio
import asyncpg
import anyio
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


class GracefulEventSourceResponse(EventSourceResponse):
    """
    Variante de EventSourceResponse que avisa al generador antes de cerrar por
    shutdown. Evita que la tarea de streaming se cancele sin enviar el cierre
    ASGI final, que Uvicorn reporta como respuesta incompleta.
    """

    def __init__(self, content: AsyncIterator, shutdown_event: asyncio.Event, **kwargs):
        super().__init__(content, **kwargs)
        self._shutdown_event = shutdown_event

    async def _listen_for_exit_signal(self) -> None:
        if not AppStatus.should_exit:
            if AppStatus.should_exit_event is None:
                AppStatus.should_exit_event = anyio.Event()

            if not AppStatus.should_exit:
                await AppStatus.should_exit_event.wait()

        self._shutdown_event.set()

        while self.active:
            await anyio.sleep(0.1)


@router.get("/stream")
async def stream_notifications(
    request: Request,
    service: NotificationsService = Depends(get_notifications_service)
):
    """
    Endpoint SSE para streaming de notificaciones en tiempo real.

    Patron: MULTIPLEXER
    - Auth ligera via sesion (NO usa get_current_user_context para evitar
      retener una conexion del pool durante toda la vida del stream).
    - Se suscribe al Queue en memoria del Service.

    NOTA ARQUITECTONICA (Auth):
    Se usa auth via cookie de sesion (user_email) + query rapida en lugar de
    get_current_user_context porque SSE mantiene la conexion abierta indefinidamente.
    Usar Depends(get_db_connection) retendria una conexion del pool durante todo el
    lifetime del stream, agotando el pool bajo carga. La auth ligera acquire+release
    libera la conexion inmediatamente despues de obtener el user_id.
    """
    # --- Auth ligera: leer sesion + query rapida (acquire+release) ---
    user_email = request.session.get("user_email")
    if not user_email:
        async def _not_auth():
            yield {"event": "error", "data": json.dumps({"error": "not_authenticated"}), "retry": 30000}
        return EventSourceResponse(_not_auth())

    try:
        usuario_id = await service.get_user_id_by_email(user_email)
    except (asyncpg.PostgresError, RuntimeError) as e:
        logger.error(f"[SSE] Error obteniendo user_db_id: {e}")
        async def _db_err():
            yield {"event": "error", "data": json.dumps({"error": "db_unavailable"}), "retry": 15000}
        return EventSourceResponse(_db_err())

    if not usuario_id:
        async def _no_user():
            yield {"event": "error", "data": json.dumps({"error": "user_not_found"}), "retry": 30000}
        return EventSourceResponse(_no_user())

    # --- Conexion DB ya liberada. A partir de aqui, 0 conexiones retenidas ---
    shutdown_event = asyncio.Event()

    async def event_generator():
        """
        Consume notificaciones del Queue en memoria.
        """
        # 0. Si el broker no esta disponible, esperar con heartbeats hasta que se recupere
        if not service.is_broker_connected():
            logger.warning(f"[SSE] Broker no disponible para usuario {usuario_id} - MODO DEGRADADO")
            max_degraded_checks = 20  # 20 * 15s = 5 min max en modo degradado
            for _ in range(max_degraded_checks):
                # Verificar si el broker se recupero
                if service.is_broker_connected():
                    logger.info(f"[SSE] Broker recuperado, registrando usuario {usuario_id}")
                    break

                yield {
                    "event": "heartbeat",
                    "data": json.dumps({"status": "degraded", "notifications_disabled": True}),
                    "retry": 15000
                }
                try:
                    await asyncio.wait_for(shutdown_event.wait(), timeout=15)
                    return
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    raise
            else:
                # Timeout de modo degradado: cerrar stream para que el cliente reconecte
                yield {
                    "event": "heartbeat",
                    "data": json.dumps({"status": "degraded_timeout"}),
                    "retry": 10000
                }
                return

        # 1. Registrarse y obtener Queue + conn_id unico
        queue, conn_id = await service.register_connection(usuario_id)

        try:
            logger.info(f"[SSE] Stream {conn_id[:8]} iniciado para usuario {usuario_id}")

            # 2. Loop de eventos (Queue -> SSE)
            # Nota: pendientes se cargan via HTTP (GET /notifications/list) en initNotifications().
            # No duplicamos con pool.acquire() aqui para evitar consume innecesario del pool.
            while not shutdown_event.is_set():
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
            logger.info(f"[SSE] Stream {conn_id[:8]} cancelado para {usuario_id}")
            raise
        except (RuntimeError, TypeError, ValueError) as e:
            logger.error(f"[SSE] Error en stream {conn_id[:8]}: {e}", exc_info=True)
        finally:
            # 4. Desregistrar por conn_id (solo borra ESTE stream, no otros del mismo usuario)
            await service.unregister_connection(usuario_id, conn_id)

    return GracefulEventSourceResponse(
        event_generator(),
        shutdown_event=shutdown_event,
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


@router.get("/resolve/{oportunidad_id}")
async def resolve_notification_target(
    oportunidad_id: UUID,
    tipo: Optional[str] = None,
    modulo_origen: Optional[str] = None,
    context = Depends(get_current_user_context),
    conn = Depends(get_db_connection),
    service: NotificationsService = Depends(get_notifications_service)
):
    """
    Determina a qué módulo/sección pertenece una oportunidad.
    Usado por el frontend para navegar al hacer click en una notificación.
    
    Lógica de resolución (en orden de prioridad):
    1. Si se pasa modulo_origen → usa ese módulo directamente
    2. Si no → fallback a DB check (levantamientos si existe registro, simulacion si no)
    
    Args:
        tipo: Tipo de notificación (legacy, informativo)
        modulo_origen: Módulo que generó la notificación ('simulacion', 'levantamientos')
    
    Returns:
        {module, url, detail_url}
    """
    return await service.resolve_notification_target(
        conn,
        oportunidad_id,
        modulo_origen=modulo_origen,
    )


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

    return {
        "notifications": await service.list_unread_notifications(conn, usuario_id, limit)
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
