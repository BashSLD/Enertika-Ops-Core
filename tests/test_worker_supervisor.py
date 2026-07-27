import asyncio

import pytest

import worker


class _FakeAsyncioNamespace:
    """Reemplaza el nombre `asyncio` visto desde worker.py (no el modulo real).

    `worker._supervise` solo usa `asyncio.sleep` y `asyncio.CancelledError`.
    Mutar el atributo `sleep` del modulo real `asyncio` (compartido con el
    loop de asyncio.run) interferiria con el scheduling interno; reemplazar
    el nombre `worker.asyncio` por este namespace evita tocar el modulo real.
    """

    CancelledError = asyncio.CancelledError

    def __init__(self):
        self.sleep_calls = []

    async def sleep(self, seconds):
        self.sleep_calls.append(seconds)


class _FakeTime:
    """Idem para `time.monotonic`: reemplaza `worker.time`, no el modulo real.

    El ProactorEventLoop de Windows llama time.monotonic() durante su propio
    scheduling/shutdown; mutar el `time.monotonic` real rompe ese cierre.
    Tras agotar los valores dados, repite el ultimo en vez de fallar.
    """

    def __init__(self, values):
        self._remaining = list(values)
        self._last = values[-1] if values else 0.0

    def monotonic(self):
        if self._remaining:
            self._last = self._remaining.pop(0)
        return self._last


def _patch_sleep(monkeypatch) -> list:
    fake = _FakeAsyncioNamespace()
    monkeypatch.setattr(worker, "asyncio", fake)
    return fake.sleep_calls


def _patch_monotonic(monkeypatch, values) -> None:
    monkeypatch.setattr(worker, "time", _FakeTime(values))


def test_supervise_restarts_after_exception_and_returns_on_success(monkeypatch):
    sleep_calls = _patch_sleep(monkeypatch)
    call_count = 0

    async def factory():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("boom")

    asyncio.run(worker._supervise("test_task", factory))

    assert call_count == 2
    assert len(sleep_calls) == 1
    assert 1.6 <= sleep_calls[0] <= 2.4


def test_supervise_resets_backoff_after_stable_run(monkeypatch):
    sleep_calls = _patch_sleep(monkeypatch)
    _patch_monotonic(monkeypatch, [0.0, 0.1, 10.0, 71.0, 100.0])

    call_count = 0

    async def factory():
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise RuntimeError(f"boom {call_count}")

    asyncio.run(worker._supervise("test_task", factory))

    assert call_count == 3
    assert len(sleep_calls) == 2
    # El segundo intento corrio >= 60s (71.0 - 10.0) antes de morir, asi que
    # el backoff se reseteo a la base en vez de escalar a ~4s.
    assert 1.6 <= sleep_calls[0] <= 2.4
    assert 1.6 <= sleep_calls[1] <= 2.4


def test_supervise_reraises_cancelled_error_without_retry(monkeypatch):
    sleep_calls = _patch_sleep(monkeypatch)

    async def factory():
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(worker._supervise("test_task", factory))

    assert sleep_calls == []


def test_supervise_alerts_sentry_after_threshold_consecutive_failures(monkeypatch):
    _patch_sleep(monkeypatch)
    _patch_monotonic(monkeypatch, [0.0, 0.1, 1.0, 1.1, 2.0, 2.1, 3.0])

    captured = []
    monkeypatch.setattr(worker.sentry_sdk, "capture_exception", lambda exc: captured.append(exc))

    call_count = 0

    async def factory():
        nonlocal call_count
        call_count += 1
        if call_count <= 3:
            raise RuntimeError(f"boom {call_count}")

    asyncio.run(worker._supervise("test_task", factory))

    assert call_count == 4
    assert len(captured) == 1
    assert str(captured[0]) == "boom 3"
