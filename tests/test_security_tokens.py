"""
Tests para core/security.py:
- safe_redirect_path: proteccion de open redirect en el destino post-login.
- get_valid_graph_token: refresh_token ausente en la respuesta de Microsoft se
  conserva (no se pisa con None), y dos renovaciones concurrentes del mismo
  usuario no se pisan entre si (lock Redis con relectura de BD).
"""
import time

import pytest
from starlette.requests import Request

from core import security
from core.security import safe_redirect_path


# ============================
# safe_redirect_path
# ============================

class TestSafeRedirectPath:

    def test_none_defaults_to_root(self):
        assert safe_redirect_path(None) == "/"

    def test_empty_string_defaults_to_root(self):
        assert safe_redirect_path("") == "/"

    def test_local_path_preserved(self):
        assert safe_redirect_path("/bom/123/ui") == "/bom/123/ui"

    def test_local_path_with_query_preserved(self):
        assert safe_redirect_path("/perfil/ui?tab=solicitudes&id=5") == "/perfil/ui?tab=solicitudes&id=5"

    def test_protocol_relative_blocked(self):
        assert safe_redirect_path("//evil.example.com") == "/"

    def test_absolute_external_url_blocked(self):
        assert safe_redirect_path("https://evil.example.com/steal") == "/"
        assert safe_redirect_path("http://evil.example.com") == "/"

    def test_backslash_disguised_protocol_relative_blocked(self):
        # Los navegadores normalizan "\" a "/" en URLs: "/\evil.com" -> "//evil.com".
        assert safe_redirect_path("/\\evil.example.com") == "/"

    def test_url_encoded_protocol_relative_blocked(self):
        assert safe_redirect_path("/%2F%2Fevil.example.com") == "/"

    def test_control_characters_blocked(self):
        assert safe_redirect_path("/\tevil") == "/"
        assert safe_redirect_path("/\nevil") == "/"

    def test_path_not_starting_with_slash_blocked(self):
        assert safe_redirect_path("evil.example.com") == "/"


# ============================
# get_valid_graph_token: refresh token
# ============================

class FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return self

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class FakeRedisLock:
    """Redis minimo: SET NX EX / GET / DELETE, suficiente para el lock de
    renovacion de tokens (ver core.security._acquire_refresh_lock)."""

    def __init__(self):
        self.store = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def get(self, key):
        return self.store.get(key)

    async def delete(self, key):
        self.store.pop(key, None)


def _build_request(session: dict) -> Request:
    scope = {
        "type": "http",
        "session": session,
        "headers": [],
        "method": "GET",
        "path": "/",
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_refresh_token_ausente_en_respuesta_se_conserva(monkeypatch):
    monkeypatch.setattr(security, "get_db_pool", _async_return(FakePool(conn=object())))
    monkeypatch.setattr(security, "_get_redis", lambda: None)  # sin lock: camino simple

    monkeypatch.setattr(
        security.security_db, "get_user_tokens",
        _async_return({
            "access_token": "old-access",
            "refresh_token": "old-refresh",
            "token_expires_at": int(time.time()) - 100,  # ya vencido
        }),
    )

    captured = {}

    async def fake_update_user_tokens(conn, email, access_token, refresh_token, token_expires_at):
        captured["access_token"] = access_token
        captured["refresh_token"] = refresh_token

    monkeypatch.setattr(security.security_db, "update_user_tokens", fake_update_user_tokens)

    class FakeMsAuth:
        async def refresh_access_token(self, refresh_token):
            assert refresh_token == "old-refresh"
            # Microsoft no siempre reemite un refresh_token nuevo.
            return {"access_token": "new-access", "expires_in": 3600}

    monkeypatch.setattr(security, "get_ms_auth", lambda: FakeMsAuth())

    request = _build_request({"user_email": "user@enertika.mx"})
    token = await security.get_valid_graph_token(request)

    assert token == "new-access"
    assert captured["access_token"] == "new-access"
    assert captured["refresh_token"] == "old-refresh"  # conservado, no None


@pytest.mark.asyncio
async def test_dos_renovaciones_concurrentes_no_se_pisan(monkeypatch):
    fake_redis = FakeRedisLock()
    monkeypatch.setattr(security, "get_db_pool", _async_return(FakePool(conn=object())))
    monkeypatch.setattr(security, "_get_redis", lambda: fake_redis)

    # Worker A ya tiene el lock (simula una renovacion en curso).
    await fake_redis.set("eco:token_refresh_lock:user@enertika.mx", "worker-a-token", nx=True, ex=20)

    now = int(time.time())
    # Worker B lee el token viejo primero; tras fallar el lock, relee y encuentra
    # uno mas fresco (el que "worker A" ya guardo mientras esperaba).
    get_user_tokens_mock = _async_side_effect([
        {"access_token": "old-access", "refresh_token": "old-refresh", "token_expires_at": now - 100},
        {"access_token": "fresher-access", "refresh_token": "fresher-refresh", "token_expires_at": now + 3600},
    ])
    monkeypatch.setattr(security.security_db, "get_user_tokens", get_user_tokens_mock)

    refresh_calls = {"count": 0}

    class FakeMsAuth:
        async def refresh_access_token(self, refresh_token):
            refresh_calls["count"] += 1
            return {"access_token": "should-not-be-used", "expires_in": 3600}

    monkeypatch.setattr(security, "get_ms_auth", lambda: FakeMsAuth())

    request = _build_request({"user_email": "user@enertika.mx"})
    token = await security.get_valid_graph_token(request)

    assert token == "fresher-access"
    assert refresh_calls["count"] == 0  # no renovo: encontro el token mas fresco al esperar


@pytest.mark.asyncio
async def test_lock_nunca_liberado_no_renueva_sin_lock(monkeypatch):
    """Si el lock sigue tomado y nunca aparece un token mas fresco tras los
    reintentos acotados, se devuelve el token viejo en vez de arriesgar una
    segunda llamada a Microsoft sin lock (posible invalid_grant si Azure AD
    rota el refresh_token)."""
    fake_redis = FakeRedisLock()
    monkeypatch.setattr(security, "get_db_pool", _async_return(FakePool(conn=object())))
    monkeypatch.setattr(security, "_get_redis", lambda: fake_redis)
    monkeypatch.setattr(security, "asyncio", _FastAsyncio())

    # Worker A mantiene el lock durante todo el ciclo de vida del test.
    await fake_redis.set("eco:token_refresh_lock:user@enertika.mx", "worker-a-token", nx=True, ex=20)

    now = int(time.time())
    stale = {"access_token": "old-access", "refresh_token": "old-refresh", "token_expires_at": now - 100}
    monkeypatch.setattr(security.security_db, "get_user_tokens", _async_return(stale))

    refresh_calls = {"count": 0}

    class FakeMsAuth:
        async def refresh_access_token(self, refresh_token):
            refresh_calls["count"] += 1
            return {"access_token": "should-not-be-used", "expires_in": 3600}

    monkeypatch.setattr(security, "get_ms_auth", lambda: FakeMsAuth())

    request = _build_request({"user_email": "user@enertika.mx"})
    token = await security.get_valid_graph_token(request)

    assert token == "old-access"  # token viejo, no renovado sin lock
    assert refresh_calls["count"] == 0


class _FastAsyncio:
    """Sustituye asyncio.sleep por un no-op para no esperar ~1.8s reales en el test."""

    async def sleep(self, _seconds):
        return None


def _async_return(value):
    async def _inner(*args, **kwargs):
        return value
    return _inner


def _async_side_effect(values):
    values_iter = iter(values)

    async def _inner(*args, **kwargs):
        return next(values_iter)
    return _inner
