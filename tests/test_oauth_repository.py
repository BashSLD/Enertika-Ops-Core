"""
Tests para el repositorio de intentos OAuth (core/oauth_repository.py).

Fuerza el modo sin Redis (REDIS_URL="", DEBUG_MODE=True) para ejercitar el
fallback en memoria de forma deterministica, independiente de si el entorno
local tiene Redis configurado. El camino con Redis real (GETDEL atomico) no
se prueba aqui por requerir un servidor Redis; la logica de consumo unico
es identica en ambos backends (mismo metodo `consume`).
"""
import pytest

from core.config import settings
from core.oauth_repository import OAuthAttemptRepository, OAuthRepositoryUnavailable
from core.redis_client import reset_redis_client


@pytest.fixture(autouse=True)
def _force_memory_backend(monkeypatch):
    monkeypatch.setattr(settings, "REDIS_URL", "")
    monkeypatch.setattr(settings, "DEBUG_MODE", True)
    reset_redis_client()
    OAuthAttemptRepository._memory_store.clear()
    yield
    OAuthAttemptRepository._memory_store.clear()


@pytest.mark.asyncio
async def test_create_returns_state_and_attempt_payload():
    state, attempt = await OAuthAttemptRepository.create(
        mode="direct", next_path="/bom/123/ui", expected_email="user@enertika.mx",
    )

    assert state
    assert attempt["mode"] == "direct"
    assert attempt["next_path"] == "/bom/123/ui"
    assert attempt["expected_email"] == "user@enertika.mx"
    assert attempt["oidc_nonce"]


@pytest.mark.asyncio
async def test_consume_returns_payload_once_then_none():
    state, attempt = await OAuthAttemptRepository.create(mode="popup", next_path="/")

    consumed = await OAuthAttemptRepository.consume(state)
    assert consumed["oidc_nonce"] == attempt["oidc_nonce"]

    # Reuso del mismo state (doble callback, replay): debe fallar la segunda vez.
    assert await OAuthAttemptRepository.consume(state) is None


@pytest.mark.asyncio
async def test_consume_unknown_state_returns_none():
    assert await OAuthAttemptRepository.consume("state-inexistente") is None


@pytest.mark.asyncio
async def test_consume_none_state_returns_none():
    assert await OAuthAttemptRepository.consume(None) is None


@pytest.mark.asyncio
async def test_two_concurrent_attempts_get_independent_states():
    state_a, _ = await OAuthAttemptRepository.create(mode="direct", next_path="/a")
    state_b, _ = await OAuthAttemptRepository.create(mode="popup", next_path="/b")

    assert state_a != state_b

    attempt_a = await OAuthAttemptRepository.consume(state_a)
    attempt_b = await OAuthAttemptRepository.consume(state_b)
    assert attempt_a["next_path"] == "/a"
    assert attempt_b["next_path"] == "/b"


@pytest.mark.asyncio
async def test_create_without_redis_in_production_raises(monkeypatch):
    monkeypatch.setattr(settings, "DEBUG_MODE", False)

    with pytest.raises(OAuthRepositoryUnavailable):
        await OAuthAttemptRepository.create(mode="direct", next_path="/")


@pytest.mark.asyncio
async def test_client_nonce_roundtrip():
    state, attempt = await OAuthAttemptRepository.create(
        mode="popup", next_path="/", client_nonce="opener-generated-nonce",
    )
    consumed = await OAuthAttemptRepository.consume(state)
    assert consumed["client_nonce"] == "opener-generated-nonce"
