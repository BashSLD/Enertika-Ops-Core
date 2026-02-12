# core/notifications/service.py
"""
Service Layer para notificaciones SSE.
Maneja lógica de negocio: CRUD de notificaciones, gestión de conexiones activas.

Patrón: MULTIPLEXER (Shared Listener)
- Una sola conexión a BD (LISTEN) para TODOS los usuarios.
- Multiplexa eventos en memoria a Queues individuales.
- Evita agotamiento de pool de conexiones.
"""
from typing import Dict, Optional, List, Tuple
from uuid import UUID, uuid4
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

# Lock para sincronizar acceso a la conexión compartida (asyncpg no es thread/task-safe)
_listener_lock = asyncio.Lock()

# Queues en memoria por usuario.
# Estructura: {usuario_id: {conn_id: (queue, callback)}}
# Cada pestana/reconexion tiene su propio conn_id unico, evitando race conditions
# donde un unregister del stream viejo borra el registro del stream nuevo.
active_connections: Dict[UUID, Dict[str, Tuple[Queue, Optional[object]]]] = {}

async def startup_notifications():
    """
    Inicializa la conexion compartida para el Listener Global.
    Se debe llamar en el startup de FastAPI.
    Lock se adquiere POR INTENTO (no durante todo el loop de reintentos),
    para no bloquear register/unregister durante backoff.
    """
    global _shared_listener_conn

    max_retries = 3
    retry_delay = 2

    for attempt in range(max_retries):
        # Lock solo para el intento de conexion (milisegundos si falla rapido, max 5s por timeout)
        async with _listener_lock:
            # Re-check dentro del lock por si otro task ya conecto
            if _shared_listener_conn and not _shared_listener_conn.is_closed():
                return

            try:
                logger.info(f"[SSE-GLOBAL] Intento {attempt + 1}/{max_retries}: Conectando listener...")
                _shared_listener_conn = await asyncio.wait_for(
                    asyncpg.connect(settings.DB_URL_SSE),
                    timeout=5.0
                )
                logger.info("[SSE-GLOBAL] [OK] Shared Listener Conectado y listo.")
                return

            except asyncio.TimeoutError:
                logger.warning(f"[SSE-GLOBAL] Timeout conectando listener (intento {attempt + 1})")
            except Exception as e:
                logger.warning(f"[SSE-GLOBAL] Error conectando listener (intento {attempt + 1}): {e}")

        # Sleep FUERA del lock — register/unregister pueden operar mientras esperamos
        if attempt < max_retries - 1:
            await asyncio.sleep(retry_delay)
            retry_delay *= 2

    logger.critical("[SSE-GLOBAL] [X] No se pudo iniciar listener. Se reintentara en segundo plano.")

async def monitor_connection_task():
    """
    Tarea en segundo plano que vigila la conexion SSE y reconecta si es necesario.
    Lectura de estado SIN lock (seguro en asyncio single-thread, GIL protege asignacion atomica).
    """
    global _shared_listener_conn
    logger.info("[SSE-MONITOR] Iniciando monitor de conexion...")

    while True:
        try:
            # Lectura sin lock: _shared_listener_conn es asignacion atomica en CPython
            # y is_closed() es lectura simple. No hay riesgo en asyncio single-thread.
            needs_reconnect = (
                _shared_listener_conn is None or _shared_listener_conn.is_closed()
            )

            if needs_reconnect:
                logger.info("[SSE-MONITOR] Intentando reconexion automatica...")
                await startup_notifications()

            await asyncio.sleep(60)

        except asyncio.CancelledError:
            logger.info("[SSE-MONITOR] Monitor detenido")
            break
        except Exception as e:
            logger.error(f"[SSE-MONITOR] Error en loop de monitor: {e}")
            await asyncio.sleep(60)

async def shutdown_notifications():
    """Cierra la conexión compartida."""
    global _shared_listener_conn
    async with _listener_lock:
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

    async def register_connection(self, usuario_id: UUID) -> Tuple[Queue, str]:
        """
        Registra cliente SSE con ID unico por conexion.
        Si es el primer stream para este usuario, activa LISTEN en la BD compartida.
        Retorna (queue, conn_id) — el router debe guardar conn_id para unregister.
        """
        global _shared_listener_conn

        queue = Queue()
        conn_id = str(uuid4())

        async with _listener_lock:
            # Validar conexion compartida
            if not _shared_listener_conn or _shared_listener_conn.is_closed():
                logger.warning(f"[SSE-GLOBAL] No se puede registrar usuario {usuario_id}: conexion no disponible (Modo Degradado)")
                return queue, conn_id

            is_first = usuario_id not in active_connections or len(active_connections[usuario_id]) == 0

            # Definir canal
            channel = f"user_notif_{str(usuario_id).replace('-', '_')}"

            # Closure que despacha a TODAS las queues activas del usuario
            def _user_listener(connection, pid, chan, payload):
                try:
                    data = json.loads(payload)
                    user_conns = active_connections.get(usuario_id, {})
                    for cid, (q, _) in user_conns.items():
                        asyncio.create_task(q.put(data))
                    if user_conns:
                        logger.debug(f"[SSE-LISTENER] Evento para {usuario_id} ({len(user_conns)} streams)")
                except Exception as e:
                    logger.error(f"[SSE-LISTENER] Error decode: {e}")

            # Solo activar LISTEN si es el primer stream de este usuario
            callback = None
            if is_first:
                try:
                    await _shared_listener_conn.add_listener(channel, _user_listener)
                    callback = _user_listener
                    logger.info(f"[SSE-GLOBAL] LISTEN activo para {channel}")
                except Exception as e:
                    logger.error(f"[SSE-GLOBAL] Error adding listener: {e}")
                    return queue, conn_id

            # Registrar en el diccionario
            if usuario_id not in active_connections:
                active_connections[usuario_id] = {}
            active_connections[usuario_id][conn_id] = (queue, callback)

        return queue, conn_id

    async def unregister_connection(self, usuario_id: UUID, conn_id: str):
        """
        Elimina un stream especifico por conn_id.
        Solo desactiva LISTEN si era el ultimo stream del usuario.
        """
        global _shared_listener_conn

        async with _listener_lock:
            user_conns = active_connections.get(usuario_id)
            if not user_conns or conn_id not in user_conns:
                return

            queue, callback = user_conns.pop(conn_id)

            # Si ya no quedan streams para este usuario, limpiar LISTEN
            if len(user_conns) == 0:
                del active_connections[usuario_id]

                # Remover listener de BD (usar el callback del primer registro)
                channel = f"user_notif_{str(usuario_id).replace('-', '_')}"
                # Buscar cualquier callback no-None entre las entradas (el primero tenia el callback)
                cb = callback
                if not cb:
                    # Buscar en las otras entradas (no deberia llegar aqui, pero por seguridad)
                    for _, (_, c) in user_conns.items():
                        if c:
                            cb = c
                            break
                if cb and _shared_listener_conn and not _shared_listener_conn.is_closed():
                    try:
                        await _shared_listener_conn.remove_listener(channel, cb)
                        logger.debug(f"[SSE-GLOBAL] UNLISTEN {channel}")
                    except Exception as e:
                        logger.warning(f"[SSE-GLOBAL] Error removing listener: {e}")

            logger.info(f"[SSE] Stream {conn_id[:8]} desconectado para {usuario_id} (quedan {len(active_connections.get(usuario_id, {}))})")

    async def broadcast_to_user(self, conn, usuario_id: UUID, notification_data: dict):
        """
        Envia notificacion via PostgreSQL NOTIFY.
        Fallback in-memory si PG falla.
        """
        # 1. PostgreSQL NOTIFY (Universal)
        try:
            channel = f"user_notif_{str(usuario_id).replace('-', '_')}"
            payload = json.dumps(notification_data)
            await conn.execute("SELECT pg_notify($1, $2)", channel, payload)
        except Exception as e:
            logger.error(f"[NOTIF] Error broadcasting: {e}")

            # 2. Fallback in-memory (Solo si falla PG)
            user_conns = active_connections.get(usuario_id, {})
            for cid, (q, _) in user_conns.items():
                await q.put(notification_data)

    def get_active_connections_count(self) -> int:
        """Retorna total de streams SSE activos (suma de todos los usuarios)."""
        return sum(len(conns) for conns in active_connections.values())

    def is_broker_connected(self) -> bool:
        """Verifica si la conexión SSE global está activa."""
        global _shared_listener_conn
        # Lectura sin lock (atomicidad de variable) es OK para check rapido, 
        # pero para consistencia usamos lock si hay updates concurrentes.
        # Sin embargo, si startup/shutdown modifican _shared_listener_conn, 
        # la lectura podría ver estado intermedio? No en Python (GIL/atomic assignment).
        # Pero is_closed() es metodo.
        # Mejor no bloquear lectores frecuentes si no es estricto.
        # Dejaremos sin lock explicito aqui para performance, asumiendo riesgo bajo.
        return _shared_listener_conn is not None and not _shared_listener_conn.is_closed()

def get_notifications_service():
    return NotificationsService()


