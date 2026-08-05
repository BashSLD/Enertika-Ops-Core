"""
Entry point del Worker service en Railway.
Corre las tareas periódicas en background sin levantar el servidor HTTP.
"""
import asyncio
import logging
import random
import signal
import time
from logging.handlers import RotatingFileHandler
from typing import Awaitable, Callable

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from core.config import settings
from core.database import connect_to_db, close_db_connection
from core.bom.outbox_worker import procesar_bom_outbox_periodically
from core.tasks import (
    cleanup_temp_uploads_periodically,
    check_levantamientos_sin_asignar_periodically,
    refresh_tipo_cambio_periodically,
    check_recordatorios_levantamientos_periodically,
    check_recordatorios_en_proceso_periodically,
    check_recordatorios_completado_periodically,
    check_op_levantamiento_sin_cerrar_periodically,
    check_recordatorios_oportunidad_ganada_periodically,
    send_reporte_desarrollo_ceo_periodically,
    sat_jobs_worker_periodically,
    sat_inbox_cleanup_periodically,
    generar_festivos_anuales_periodically,
    verificar_recordatorios_aprobacion_periodically,
    verificar_recordatorios_horas_extra_periodically,
    verificar_periodos_por_expirar_periodically,
    verificar_solicitudes_vencidas_periodically,
)
from modules.asistencia.service import sync_biotime_periodically
from modules.cfe.service import procesar_descargas_cfe_periodically

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler("worker_errors.log", maxBytes=5 * 1024 * 1024, backupCount=3),
    ],
)
logger = logging.getLogger("worker")

def _sentry_before_send(event, hint):
    if "ASGI callable returned without completing response" in event.get("message", ""):
        return None
    return event

if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        before_send=_sentry_before_send,
        integrations=[FastApiIntegration(), StarletteIntegration()],
        traces_sample_rate=0.05,
        send_default_pii=False,
        enable_logs=True,
        environment="production" if not settings.DEBUG_MODE else "development",
    )


_SUPERVISOR_BACKOFF_BASE_SECONDS = 2.0
_SUPERVISOR_BACKOFF_FACTOR = 2.0
_SUPERVISOR_BACKOFF_CAP_SECONDS = 300.0
_SUPERVISOR_BACKOFF_JITTER_RATIO = 0.2
_SUPERVISOR_STABLE_SECONDS = 60.0
_SUPERVISOR_SENTRY_THRESHOLD = 3


async def _supervise(name: str, factory: Callable[[], Awaitable[None]]) -> None:
    """Reinicia `factory()` ante cualquier excepcion no anticipada (auto-heal).

    Backstop para tareas `while True` que hoy mueren en silencio si escapan una
    excepcion no cubierta por su propio manejo interno (ver PLAN_WORKER_RESILIENCIA_BIOTIME.md).
    """
    backoff = _SUPERVISOR_BACKOFF_BASE_SECONDS
    consecutive_failures = 0
    while True:
        started_at = time.monotonic()
        try:
            await factory()
            return  # no deberia pasar: las 17 tareas actuales son while True
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # devtools: allow-broad-except — backstop del supervisor: reinicia ante cualquier excepcion no anticipada; enumerar tipos reintroduce el bug (una excepcion no listada volveria a matar la tarea sin reinicio)
            ran_seconds = time.monotonic() - started_at
            if ran_seconds >= _SUPERVISOR_STABLE_SECONDS:
                backoff = _SUPERVISOR_BACKOFF_BASE_SECONDS
                consecutive_failures = 0
            consecutive_failures += 1
            # logger.error (no .warning) activa el LoggingIntegration por defecto de Sentry
            # y reporta de inmediato; se reserva para el umbral y asi evitar ruido en fallos
            # aislados/transitorios mientras se mantiene visibilidad completa en logs de Railway.
            escalar = consecutive_failures >= _SUPERVISOR_SENTRY_THRESHOLD
            (logger.error if escalar else logger.warning)(
                "[WORKER] Tarea '%s' murio tras %.1fs (intento #%d): %s",
                name, ran_seconds, consecutive_failures, exc, exc_info=True,
            )
            if escalar:
                sentry_sdk.capture_exception(exc)
            jitter = backoff * _SUPERVISOR_BACKOFF_JITTER_RATIO
            sleep_seconds = backoff + random.uniform(-jitter, jitter)
            backoff = min(backoff * _SUPERVISOR_BACKOFF_FACTOR, _SUPERVISOR_BACKOFF_CAP_SECONDS)
            logger.warning("[WORKER] Reiniciando '%s' en %.1fs", name, sleep_seconds)
        await asyncio.sleep(sleep_seconds)


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
        asyncio.create_task(_supervise("cleanup_temp_uploads", cleanup_temp_uploads_periodically)),
        asyncio.create_task(_supervise("check_levantamientos_sin_asignar", check_levantamientos_sin_asignar_periodically)),
        asyncio.create_task(_supervise("refresh_tipo_cambio", refresh_tipo_cambio_periodically)),
        asyncio.create_task(_supervise("check_recordatorios_levantamientos", check_recordatorios_levantamientos_periodically)),
        asyncio.create_task(_supervise("check_recordatorios_en_proceso", check_recordatorios_en_proceso_periodically)),
        asyncio.create_task(_supervise("check_recordatorios_completado", check_recordatorios_completado_periodically)),
        asyncio.create_task(_supervise("check_op_levantamiento_sin_cerrar", check_op_levantamiento_sin_cerrar_periodically)),
        asyncio.create_task(_supervise("check_recordatorios_oportunidad_ganada", check_recordatorios_oportunidad_ganada_periodically)),
        asyncio.create_task(_supervise("send_reporte_desarrollo_ceo", send_reporte_desarrollo_ceo_periodically)),
        asyncio.create_task(_supervise("sat_jobs_worker", sat_jobs_worker_periodically)),
        asyncio.create_task(_supervise("sat_inbox_cleanup", sat_inbox_cleanup_periodically)),
        asyncio.create_task(_supervise("generar_festivos_anuales", generar_festivos_anuales_periodically)),
        asyncio.create_task(_supervise("verificar_recordatorios_aprobacion", verificar_recordatorios_aprobacion_periodically)),
        asyncio.create_task(_supervise("verificar_recordatorios_horas_extra", verificar_recordatorios_horas_extra_periodically)),
        asyncio.create_task(_supervise("verificar_periodos_por_expirar", verificar_periodos_por_expirar_periodically)),
        asyncio.create_task(_supervise("verificar_solicitudes_vencidas", verificar_solicitudes_vencidas_periodically)),
        asyncio.create_task(_supervise("sync_biotime", sync_biotime_periodically)),
        asyncio.create_task(_supervise("procesar_descargas_cfe", procesar_descargas_cfe_periodically)),
        asyncio.create_task(_supervise("procesar_bom_outbox", procesar_bom_outbox_periodically)),
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
