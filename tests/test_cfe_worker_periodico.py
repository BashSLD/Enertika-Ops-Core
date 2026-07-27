import asyncio

import asyncpg
import pytest

from modules.cfe import service as cfe_service


class _StubCfeService:
    def __init__(self, procesar_pendientes_error):
        self._procesar_pendientes_error = procesar_pendientes_error

    async def reaper_colgados(self, _pool):
        return None

    async def procesar_pendientes(self, _pool):
        raise self._procesar_pendientes_error


class _FakeAsyncioNamespace:
    """Reemplaza el nombre `asyncio` visto desde cfe_service.py (no el modulo real).

    Ver tests/test_worker_supervisor.py: mutar el `asyncio` real interfiere con
    el ProactorEventLoop de Windows. `sleep` corta el `while True` levantando
    CancelledError tras una sola iteracion, en vez de dormir de verdad.
    """

    CancelledError = asyncio.CancelledError

    async def sleep(self, _seconds):
        raise asyncio.CancelledError()


async def _noop_pool():
    return None


async def _run_one_iteration(monkeypatch, error):
    monkeypatch.setattr(cfe_service, "get_cfe_service", lambda: _StubCfeService(error))
    monkeypatch.setattr(cfe_service, "get_db_pool", _noop_pool)
    monkeypatch.setattr(cfe_service, "asyncio", _FakeAsyncioNamespace())
    await cfe_service.procesar_descargas_cfe_periodically()


def test_procesar_descargas_cfe_periodically_catches_known_errors(monkeypatch):
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_run_one_iteration(monkeypatch, asyncpg.PostgresError("conexion perdida")))


def test_procesar_descargas_cfe_periodically_propagates_unanticipated_errors(monkeypatch):
    class _PlaywrightLikeError(Exception):
        pass

    with pytest.raises(_PlaywrightLikeError):
        asyncio.run(_run_one_iteration(monkeypatch, _PlaywrightLikeError("browser crash")))
