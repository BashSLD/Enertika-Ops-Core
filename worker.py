"""
Entry point del Worker service en Railway.
Corre las tareas periódicas en background sin levantar el servidor HTTP.
"""
import asyncio
import logging
import signal
from logging.handlers import RotatingFileHandler

from core.database import connect_to_db, close_db_connection
from core.tasks import (
    cleanup_temp_uploads_periodically,
    check_levantamientos_sin_asignar_periodically,
    refresh_tipo_cambio_periodically,
    check_recordatorios_levantamientos_periodically,
    check_recordatorios_oportunidad_ganada_periodically,
    send_reporte_desarrollo_ceo_periodically,
    sat_inbox_cleanup_periodically,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler("worker_errors.log", maxBytes=5 * 1024 * 1024, backupCount=3),
    ],
)
logger = logging.getLogger("worker")


async def main():
    logger.info("[WORKER] Iniciando worker de tareas periodicas")
    await connect_to_db()

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _handle_signal():
        logger.info("[WORKER] Señal de parada recibida")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    tasks = [
        asyncio.create_task(cleanup_temp_uploads_periodically()),
        asyncio.create_task(check_levantamientos_sin_asignar_periodically()),
        asyncio.create_task(refresh_tipo_cambio_periodically()),
        asyncio.create_task(check_recordatorios_levantamientos_periodically()),
        asyncio.create_task(check_recordatorios_oportunidad_ganada_periodically()),
        asyncio.create_task(send_reporte_desarrollo_ceo_periodically()),
        asyncio.create_task(sat_inbox_cleanup_periodically()),
    ]

    logger.info("[WORKER] %d tareas activas", len(tasks))
    await stop_event.wait()

    logger.info("[WORKER] Cancelando tareas...")
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await close_db_connection()
    logger.info("[WORKER] Apagado limpio")


if __name__ == "__main__":
    asyncio.run(main())
