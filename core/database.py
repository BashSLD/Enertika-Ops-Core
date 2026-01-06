# Archivo: core/database.py (Conexión Asíncrona para FastAPI)

import asyncpg
import logging
from core.config import settings
from typing import Optional

logger = logging.getLogger("Database")

# Almacenamos el pool de conexiones globalmente
_connection_pool: Optional[asyncpg.Pool] = None

async def connect_to_db():
    """Inicializa el pool de conexiones al inicio de la aplicación (startup)."""
    global _connection_pool
    if not _connection_pool:
        try:
            logger.info("Inicializando conexión a Supabase (asyncpg)...")
            
            _connection_pool = await asyncpg.create_pool(
                settings.DB_URL_ASYNC,
                min_size=1,
                max_size=3, # Reducido para evitar error de Supabase
                timeout=30 # segundos
            )
            logger.info("Pool de conexiones a Supabase creado exitosamente.")
        except Exception as e: # <-- CAPTURAMOS LA EXCEPCIÓN
            import sys
            logger.error("----------------------------------------------------------------")
            logger.error(f"Tipo de Error: {sys.exc_info()[0].__name__}")
            logger.error(f"Mensaje Detallado: {e!r}")
            logger.error(f"Stack Trace: {sys.exc_info()[2]}")
            logger.error("----------------------------------------------------------------")
            logger.error(f"ERROR CRÍTICO al conectar a Supabase: {e}") # <-- LA IMPRIMIMOS
            logger.error("----------------------------------------------------------------")
            # En producción, forzaríamos un os._exit(1) para detener la app si la DB es crítica.
            
async def close_db_connection():
    """Cierra el pool de conexiones al apagado de la aplicación (shutdown)."""
    global _connection_pool
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



# Configuración recomendada para PRO (Session Mode - Puerto 5432)
#_connection_pool = await asyncpg.create_pool(
#    settings.DB_URL_ASYNC,
#    min_size=5,    # Mantiene conexiones listas
#    max_size=20,   # Permite concurrencia real (ajustar según workers de Uvicorn)
#    timeout=30,
#    max_inactive_connection_lifetime=300
#)