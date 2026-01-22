# Archivo: core/database.py (Conexión Asíncrona para FastAPI)

import asyncpg
import logging
from core.config import settings
from typing import Optional, Dict
from uuid import UUID

logger = logging.getLogger("Database")

# Almacenamos el pool de conexiones globalmente
_connection_pool: Optional[asyncpg.Pool] = None

# Tracking de conexiones SSE dedicadas (fuera del pool)
# Key: user_id (UUID), Value: asyncpg.Connection
_sse_connections: Dict[UUID, asyncpg.Connection] = {}

async def connect_to_db():
    """Inicializa el pool de conexiones al inicio de la aplicación (startup)."""
    global _connection_pool
    if not _connection_pool:
        try:
            logger.info("Inicializando conexión a Supabase (asyncpg)...")
            
            _connection_pool = await asyncpg.create_pool(
                settings.DB_URL_ASYNC,
                min_size=0,
                max_size=35,  # 20 usuarios SSE + 15 para operaciones normales
                timeout=30,  # segundos
                max_inactive_connection_lifetime=300  # Cierra conexiones inactivas tras 5 min
            )
            logger.info("Pool de conexiones a Supabase creado exitosamente.")
        except Exception as e:
            import sys
            logger.critical(f"FALLO FATAL: No se pudo conectar a la DB: {e}")
            sys.exit(1)  # Forzar salida del proceso
            
async def close_db_connection():
    """Cierra el pool de conexiones al apagado de la aplicación (shutdown)."""
    global _connection_pool, _sse_connections
    
    # 1. PRIMERO: Cerrar todas las conexiones SSE activas
    if _sse_connections:
        logger.info(f"Cerrando {len(_sse_connections)} conexiones SSE activas...")
        for user_id, conn in list(_sse_connections.items()):
            try:
                await conn.close()
                logger.info(f"Conexión SSE cerrada para usuario {user_id}")
            except Exception as e:
                logger.warning(f"Error cerrando SSE connection {user_id}: {e}")
        _sse_connections.clear()
        logger.info("Todas las conexiones SSE cerradas.")
    
    # 2. DESPUÉS: Cerrar el pool principal
    if _connection_pool:
        logger.info("Cerrando pool de conexiones de Supabase.")
        await _connection_pool.close()
        _connection_pool = None

async def get_db_connection():
    """Dependencia de FastAPI para obtener una conexión del pool."""
    if not _connection_pool:
        # En caso de que se intente usar antes del startup
        raise Exception("El pool de conexiones no está inicializado. Verifique el log de startup.")
        
    # Usamos pool.acquire() como un gestor de contexto (with), que la libera automáticamente.
    async with _connection_pool.acquire() as conn:
        yield conn

async def get_db_pool():
    """Retorna el pool global para uso interno (seguridad, tareas, etc)."""
    global _connection_pool
    if not _connection_pool:
        raise Exception("DB Pool no inicializado.")
    return _connection_pool


# ========================================
# SSE DEDICATED CONNECTIONS
# ========================================

async def get_sse_connection(user_id: UUID) -> asyncpg.Connection:
    """
    Crea y retorna una conexión dedicada para SSE streaming de un usuario.
    
    Esta conexión es INDEPENDIENTE del pool principal y se mantiene abierta
    mientras el usuario está conectado al stream SSE.
    
    Args:
        user_id: UUID del usuario que se conecta
        
    Returns:
        asyncpg.Connection dedicada para SSE
        
    Raises:
        Exception: Si ya existe una conexión para este usuario
    """
    global _sse_connections
    
    # Validar que no exista conexión previa (evitar duplicados)
    if user_id in _sse_connections:
        logger.warning(f"[SSE-CONN] Ya existe conexión activa para usuario {user_id}, cerrando anterior...")
        await close_sse_connection(user_id)
    
    try:
        # Crear conexión directa (fuera del pool)
        conn = await asyncpg.connect(settings.DB_URL_ASYNC)
        _sse_connections[user_id] = conn
        
        logger.info(f"[SSE-CONN] Conexión SSE creada para usuario {user_id} (Total activas: {len(_sse_connections)})")
        return conn
        
    except Exception as e:
        logger.error(f"[SSE-CONN] Error creando conexión SSE para {user_id}: {e}")
        raise


async def close_sse_connection(user_id: UUID):
    """
    Cierra y remueve la conexión SSE dedicada de un usuario.
    
    Args:
        user_id: UUID del usuario a desconectar
    """
    global _sse_connections
    
    if user_id in _sse_connections:
        try:
            conn = _sse_connections[user_id]
            await conn.close()
            del _sse_connections[user_id]
            
            logger.info(f"[SSE-CONN] Conexión SSE cerrada para usuario {user_id} (Restantes: {len(_sse_connections)})")
        except Exception as e:
            logger.warning(f"[SSE-CONN] Error cerrando conexión SSE para {user_id}: {e}")
            # Asegurar que se remueva del dict incluso si falla el close
            _sse_connections.pop(user_id, None)
    else:
        logger.debug(f"[SSE-CONN] No se encontró conexión activa para usuario {user_id}")


def get_active_sse_connections_count() -> int:
    """
    Retorna el número de conexiones SSE activas actualmente.
    
    Útil para monitoreo y debugging.
    """
    return len(_sse_connections)



# Configuración recomendada para PRO (Session Mode - Puerto 5432)
#_connection_pool = await asyncpg.create_pool(
#    settings.DB_URL_ASYNC,
#    min_size=5,    # Mantiene conexiones listas
#    max_size=20,   # Permite concurrencia real (ajustar según workers de Uvicorn)
#    timeout=30,
#    max_inactive_connection_lifetime=300
#)