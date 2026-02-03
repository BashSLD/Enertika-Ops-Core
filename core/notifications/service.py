# core/notifications/service.py
"""
Service Layer para notificaciones SSE.
Maneja lógica de negocio: CRUD de notificaciones, gestión de conexiones activas.

Patrón: MULTIPLEXER (Shared Listener)
- Una sola conexión a BD (LISTEN) para TODOS los usuarios.
- Multiplexa eventos en memoria a Queues individuales.
- Evita agotamiento de pool de conexiones.
"""
from typing import Dict, Optional, List
from uuid import UUID
from asyncio import Queue, create_task
import logging
import json
import asyncio
import asyncpg
from core.config import settings
from core.database import get_db_pool

logger = logging.getLogger("NotificationsService")

# =============================================================================
# GLOBAL SHARED STATE (Multiplexer)
# =============================================================================

# Conexión dedicada única para escuchar notificaciones de TODOS los usuarios
_shared_listener_conn: Optional[asyncpg.Connection] = None

# Queues en memoria por usuario
# Un usuario puede tener múltiples conexiones (ej. varias pestañas) -> Lista de Queues?
# Simplificación V1: Una Queue por usuario (broadcast a todas sus pestañas es responsabilidad del cliente o navegador)
# Mejora V2 (implementada): `active_connections` mapea userID -> Queue. 
# Si el usuario abre 2 pestañas, ambas consumen del mismo stream? No, SSE requiere streams únicos.
# Solución: `active_connections` debe ser Dict[UUID, List[Queue]] para soportar multisocessión real.
# Pero para mantener compatibilidad con router actual: Dict[UUID, Queue]. 
# El router maneja el ciclo de vida de la queue.
active_connections: Dict[UUID, Queue] = {}

async def startup_notifications():
    """
    Inicializa la conexión compartida para el Listener Global.
    Se debe llamar en el startup de FastAPI.
    """
    global _shared_listener_conn
    try:
        if not _shared_listener_conn:
            logger.info("[SSE-GLOBAL] Iniciando Shared Listener Connection...")
            # Crear conexión directa fuera del pool
            _shared_listener_conn = await asyncpg.connect(settings.DB_URL_ASYNC)
            
            # Registrar callback global para TODO el canal de notificaciones
            # OJO: Postgres LISTEN funciona por canal.
            # No podemos hacer 'LISTEN *'.
            # Estrategia: 
            # 1. Usar un canal GLOBAL 'system_notifications' para eventos globales? No.
            # 2. La conexión compartida debe hacer LISTEN dinámicamente cuando un usuario se conecta.
            
            logger.info("[SSE-GLOBAL] Shared Listener Conectado y listo.")
    except Exception as e:
        logger.critical(f"[SSE-GLOBAL] Fallo al iniciar listener: {e}")

async def shutdown_notifications():
    """Cierra la conexión compartida."""
    global _shared_listener_conn
    if _shared_listener_conn:
        try:
            await _shared_listener_conn.close()
            logger.info("[SSE-GLOBAL] Shared Listener cerrado.")
        except Exception as e:
            logger.error(f"[SSE-GLOBAL] Error cerrando listener: {e}")
        finally:
            _shared_listener_conn = None

async def _global_pg_listener(connection, pid, channel, payload):
    """
    Callback centralizado. Recibe TODAS las notificaciones de la BD.
    Enruta el payload al Queue del usuario correspondiente.
    """
    try:
        # El canal tiene formato user_notif_{uuid_con_guiones_reemplazados}
        # Pero mejor: confiamos en que si recibimos algo en el canal X, 
        # debemos buscar el usuario dueño del canal X.
        
        # Parsear payload
        data = json.loads(payload)
        
        # Extraer ID de usuario del canal? O del payload?
        # El channel es 'user_notif_UUIDREPLACED'. 
        # Es costoso revertir el string.
        # Mejor estrategia: El payload debe incluir el 'target_user_id'?
        # Actualmente el payload es la notificación en sí.
        
        # Alternativa: Mantener un mapa inverso {channel_name: user_id} ?
        # COSTOSO.
        
        # MEJOR ESTRATEGIA:
        # `active_connections` es UUID -> Queue.
        # Cuando registramos el LISTEN, usamos el UUID.
        # Espera, el callback de asyncpg NO recibe el user_id.
        
        # SOLUCIÓN: Usar `partial` o closure al registrar el listener?
        # NO, un solo connection puede tener múltiples listeners.
        # Pero asyncpg permite: conn.add_listener(channel, callback)
        # Podemos registrar un callback ESPECÍFICO para cada canal que lleva el user_id "pegado".
        pass 

    except Exception as e:
        logger.error(f"[SSE-ROUTER] Error procesando payload: {e}")


class NotificationsService:
    """
    Maneja lógica de negocio de notificaciones con Multiplexer.
    """
    
    # ... CRUD METODOS MANTENIDOS IGUAL ...
    
    async def get_pending_notifications(self, conn, usuario_id: UUID, limit: int = 10):
        query = """
            SELECT id, tipo, titulo, mensaje, id_oportunidad, created_at
            FROM tb_notificaciones
            WHERE usuario_id = $1 AND leida = false
            ORDER BY created_at DESC
            LIMIT $2
        """
        rows = await conn.fetch(query, usuario_id, limit)
        return [dict(r) for r in rows]
    
    async def get_unread_count(self, conn, usuario_id: UUID) -> int:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM tb_notificaciones WHERE usuario_id = $1 AND leida = false",
            usuario_id
        ) or 0
    
    async def mark_as_read(self, conn, notification_id: UUID, usuario_id: UUID):
        await conn.execute(
            "UPDATE tb_notificaciones SET leida = true WHERE id = $1 AND usuario_id = $2",
            notification_id, usuario_id
        )
    
    async def delete_notification(self, conn, notification_id: UUID, usuario_id: UUID) -> bool:
        result = await conn.execute(
            "DELETE FROM tb_notificaciones WHERE id = $1 AND usuario_id = $2",
            notification_id, usuario_id
        )
        return int(result.split()[-1]) > 0

    async def mark_all_read(self, conn, usuario_id: UUID) -> int:
        result = await conn.execute(
            "UPDATE tb_notificaciones SET leida = true WHERE usuario_id = $1 AND leida = false",
            usuario_id
        )
        return int(result.split()[-1])

    async def delete_all_notifications(self, conn, usuario_id: UUID) -> int:
        # Mantener método legacy por si acaso, pero router usará mark_all_read
        result = await conn.execute(
            "DELETE FROM tb_notificaciones WHERE usuario_id = $1",
            usuario_id
        )
        return int(result.split()[-1])
    
    async def create_notification(self, conn, usuario_id: UUID, tipo: str, titulo: str, mensaje: str, id_oportunidad: Optional[UUID] = None) -> dict:
        query = """
            INSERT INTO tb_notificaciones (usuario_id, tipo, titulo, mensaje, id_oportunidad)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id, created_at
        """
        row = await conn.fetchrow(query, usuario_id, tipo, titulo, mensaje, id_oportunidad)
        
        data = {
            "id": str(row['id']),
            "type": tipo,
            "title": titulo,
            "message": mensaje,
            "oportunidad_id": str(id_oportunidad) if id_oportunidad else None,
            "created_at": row['created_at'].isoformat()
        }
        
        return data

    # ... NUEVA LÓGICA MULTIPLEXER ...

    async def register_connection(self, usuario_id: UUID) -> Queue:
        """
        Registra cliente SSE.
        Si es el primero para este usuario, activa el LISTEN en la BD compartida.
        """
        global _shared_listener_conn
        
        queue = Queue()
        active_connections[usuario_id] = queue
        
        # Definir canal
        channel = f"user_notif_{str(usuario_id).replace('-', '_')}"
        
        # Crear closure para capturar el queue específico
        def _user_listener(conn, pid, chan, payload):
            try:
                data = json.loads(payload)
                # Poner en la queue del usuario (Non-blocking)
                asyncio.create_task(queue.put(data))
                logger.debug(f"[SSE-LISTENER] Evento para {usuario_id}")
            except Exception as e:
                logger.error(f"[SSE-LISTENER] Error decode: {e}")

        # Activar LISTEN en la conexión compartida
        if _shared_listener_conn and not _shared_listener_conn.is_closed():
            try:
                # Add listener with dedicated callback
                # OJO: asyncpg permite múltiples listeners en la misma conexión
                await _shared_listener_conn.add_listener(channel, _user_listener)
                logger.info(f"[SSE-GLOBAL] LISTEN activo para {channel}")
                
                # Guardar referencia al listener para poder removerlo?
                # active_connections ahora guarda (Queue, callback)?
                # Simplificación: No guardamos callback.
                # Al desconectar, removemos listener con el MISMO objeto función?
                # Problema: Necesitamos la misma instancia de función para removerla.
                # Solución: Guardar callback en active_connections.
                active_connections[usuario_id] = (queue, _user_listener)
                
            except Exception as e:
                logger.error(f"[SSE-GLOBAL] Error adding listener: {e}")
        else:
             logger.warning("[SSE-GLOBAL] Conexión compartida no disponible")
             
        return queue

    async def unregister_connection(self, usuario_id: UUID):
        """Elimina cliente y desactivar LISTEN."""
        global _shared_listener_conn
        
        if usuario_id in active_connections:
            # Recuperar callback
            data = active_connections[usuario_id]
            if isinstance(data, tuple):
                queue, callback = data
            else:
                queue = data
                callback = None
            
            # Remover listener de BD
            channel = f"user_notif_{str(usuario_id).replace('-', '_')}"
            if _shared_listener_conn and not _shared_listener_conn.is_closed() and callback:
                try:
                    await _shared_listener_conn.remove_listener(channel, callback)
                    logger.debug(f"[SSE-GLOBAL] UNLISTEN {channel}")
                except Exception as e:
                     logger.warning(f"[SSE-GLOBAL] Error removing listener: {e}")
            
            del active_connections[usuario_id]
            logger.info(f"[SSE] Usuario desconectado: {usuario_id}")

    async def broadcast_to_user(self, conn, usuario_id: UUID, notification_data: dict):
        """
        Envía notificación.
        """
        # 1. PostgreSQL NOTIFY (Universal)
        try:
            channel = f"user_notif_{str(usuario_id).replace('-', '_')}"
            payload = json.dumps(notification_data)
            await conn.execute("SELECT pg_notify($1, $2)", channel, payload)
        except Exception as e:
            logger.error(f"[NOTIF] Error broadcasting: {e}")
            
            # 2. Fallback in-memory (Solo si falla PG o para tests)
            if usuario_id in active_connections:
                data = active_connections[usuario_id]
                queue = data[0] if isinstance(data, tuple) else data
                await queue.put(notification_data)

    def get_active_connections_count(self) -> int:
        return len(active_connections)

def get_notifications_service():
    return NotificationsService()


