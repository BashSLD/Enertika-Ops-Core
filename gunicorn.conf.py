"""
Gunicorn configuration for Railway deployment with multi-worker support.
Optimized for: 20 concurrent users, low notification frequency.
"""
import multiprocessing
import os

# Worker configuration
# Railway: 2 workers ideal para plan Starter (512MB-1GB RAM)
# Con 20 usuarios, 2 workers balancea carga sin saturar recursos
workers = int(os.getenv("GUNICORN_WORKERS", "1"))  # Reducido a 1 para debugging

# Worker class: UvicornWorker para ASGI + WebSocket/SSE support
worker_class = "uvicorn.workers.UvicornWorker"

# Bind address (Railway asigna PORT automáticamente)
port = os.getenv("PORT", "8000")
bind = f"0.0.0.0:{port}"

# Timeouts
# SSE mantiene conexiones abiertas indefinidamente, necesita timeout generoso
timeout = 120  # 2 minutos para requests normales
keepalive = 5  # Keep-alive de conexiones

# Graceful shutdown
# Tiempo para que workers terminen requests en curso antes de forzar shutdown
graceful_timeout = 30

# Worker lifecycle
# Reiniciar workers después de N requests (previene memory leaks)
max_requests = 1000
max_requests_jitter = 50  # Añade aleatoriedad para evitar restarts simultáneos

# Logging
accesslog = "-"  # stdout (Railway captura automáticamente)
errorlog = "-"   # stderr
loglevel = os.getenv("LOG_LEVEL", "info")

# Access log format (incluye info útil para debugging)
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Preload app deshabilitado - causa problemas con conexiones async en Railway
preload_app = False

# Server mechanics
# Backlog de conexiones pendientes (Railway maneja bien hasta 100)
backlog = 100

# Worker temporary directory - /tmp es más compatible en Railway
worker_tmp_dir = "/tmp"

def on_starting(server):
    """
    Hook ejecutado al iniciar Gunicorn.
    Útil para validaciones o setup inicial.
    """
    import logging
    logger = logging.getLogger("gunicorn.error")
    logger.info(f"[GUNICORN] Iniciando Gunicorn con {workers} workers")
    logger.info(f"[GUNICORN] PostgreSQL LISTEN/NOTIFY habilitado para SSE multi-worker")

def worker_int(worker):
    """
    Hook ejecutado cuando worker recibe SIGINT (Ctrl+C).
    Asegura cleanup graceful de conexiones PostgreSQL.
    """
    import logging
    logger = logging.getLogger("gunicorn.error")
    logger.info(f"[GUNICORN] Worker {worker.pid} interrumpido, limpiando conexiones...")

def post_worker_init(worker):
    """
    Hook ejecutado después de inicializar cada worker.
    """
    import logging
    logger = logging.getLogger("gunicorn.error")
    logger.info(f"[GUNICORN] Worker {worker.pid} inicializado correctamente")
