# Archivo: core/database.py (Conexión Asíncrona para FastAPI)

import asyncpg
from core.config import settings
from typing import Optional

# Almacenamos el pool de conexiones globalmente
_connection_pool: Optional[asyncpg.Pool] = None

async def connect_to_db():
    """Inicializa el pool de conexiones al inicio de la aplicación (startup)."""
    global _connection_pool
    if not _connection_pool:
        try:
            print("Inicializando conexión a Supabase (asyncpg)...")
            
            _connection_pool = await asyncpg.create_pool(
                settings.DB_URL_ASYNC,
                min_size=5,
                max_size=20,
                timeout=30 # segundos
            )
            print("Pool de conexiones a Supabase creado exitosamente.")
        except Exception as e: # <-- CAPTURAMOS LA EXCEPCIÓN
            print("----------------------------------------------------------------")
            import sys
            print(f"Tipo de Error: {sys.exc_info()[0].__name__}")
            print(f"Mensaje Detallado: {e!r}")
            print(f"Stack Trace: {sys.exc_info()[2]}")
            print("----------------------------------------------------------------")
            print(f"ERROR CRÍTICO al conectar a Supabase: {e}") # <-- LA IMPRIMIMOS
            print("----------------------------------------------------------------")
            # En producción, forzaríamos un os._exit(1) para detener la app si la DB es crítica.
            
async def close_db_connection():
    """Cierra el pool de conexiones al apagado de la aplicación (shutdown)."""
    global _connection_pool
    if _connection_pool:
        print("Cerrando pool de conexiones de Supabase.")
        await _connection_pool.close()
        _connection_pool = None

async def get_db_connection() -> asyncpg.Connection:
    """Dependencia de FastAPI para obtener una conexión del pool."""
    if not _connection_pool:
        # En caso de que se intente usar antes del startup
        raise Exception("El pool de conexiones no está inicializado. Verifique el log de startup.")
        
    # Usamos pool.acquire() como un gestor de contexto (with), que la libera automáticamente.
    # El usuario de FastAPI solo necesita la conexión.
    return _connection_pool.acquire()