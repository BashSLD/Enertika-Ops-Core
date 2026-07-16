"""
Tests end-to-end (via TestClient) del flujo /auth/login -> /auth/callback:
correlacion state/nonce, consumo atomico, cancelacion/error sin 422 ni loop,
open redirects, y modo popup vs directo.

Fuerza el backend en memoria del repositorio OAuth (ver test_oauth_repository.py)
para que las pruebas sean deterministicas sin depender de Redis local.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from core.config import settings
from core.database import get_db_connection
from core.microsoft import get_ms_auth
from core.oauth_repository import OAuthAttemptRepository
from core.redis_client import reset_redis_client
from modules.auth.router import router as auth_router


class FakeConn:
    """Cubre fetchval() (upsert de usuario, RETURNING is_active) y fetchrow()
    (chequeo de sesion en /auth/session)."""

    def __init__(self, active: bool = True):
        self.active = active
        self.fetchval_calls = []

    async def fetchval(self, query, *args):
        self.fetchval_calls.append((query, args))
        return self.active

    async def fetchrow(self, query, email):
        return {
            "id_usuario": 1, "nombre": "Usuario Test", "rol_sistema": "USER",
            "department": None, "puesto": None, "modulo_preferido": None,
            "rol_organizacional": None, "is_active": self.active,
        }


class FakeMsAuth:
    def __init__(self, nonce_matches: bool = True):
        self.nonce_matches = nonce_matches
        self.last_auth_url_args = None

    def get_auth_url(self, state, nonce):
        self.last_auth_url_args = (state, nonce)
        return f"https://login.microsoftonline.com/authorize?state={state}&nonce={nonce}"

    async def get_token_from_code(self, code, nonce=None):
        claims = {"preferred_username": "user@enertika.mx", "name": "Usuario Test"}
        if self.nonce_matches:
            claims["nonce"] = nonce
        else:
            claims["nonce"] = "nonce-equivocado"
        return {
            "access_token": "at", "refresh_token": "rt", "expires_in": 3600,
            "id_token_claims": claims,
        }

    async def get_user_profile(self, token):
        return {"department": None, "jobTitle": None}


@pytest.fixture(autouse=True)
def _force_memory_backend(monkeypatch):
    monkeypatch.setattr(settings, "REDIS_URL", "")
    monkeypatch.setattr(settings, "DEBUG_MODE", True)
    reset_redis_client()
    OAuthAttemptRepository._memory_store.clear()
    yield
    OAuthAttemptRepository._memory_store.clear()


def build_client(fake_conn=None, fake_ms=None):
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret-key", https_only=False)
    app.include_router(auth_router)
    app.dependency_overrides[get_db_connection] = lambda: (fake_conn or FakeConn())
    app.dependency_overrides[get_ms_auth] = lambda: (fake_ms or FakeMsAuth())
    return TestClient(app, follow_redirects=False)


def _extract_state(auth_url: str) -> str:
    from urllib.parse import urlparse, parse_qs
    return parse_qs(urlparse(auth_url).query)["state"][0]


class TestLoginInitiatesCorrelatedAttempt:

    def test_login_redirects_to_microsoft_with_state_and_nonce(self):
        fake_ms = FakeMsAuth()
        client = build_client(fake_ms=fake_ms)

        response = client.get("/auth/login?next=/bom/1/ui")

        assert response.status_code == 307 or response.status_code == 302
        assert fake_ms.last_auth_url_args is not None
        state, nonce = fake_ms.last_auth_url_args
        assert state and nonce
        assert response.headers.get("cache-control") == "no-store"

    @pytest.mark.asyncio
    async def test_login_open_redirect_attempt_is_neutralized(self):
        fake_ms = FakeMsAuth()
        client = build_client(fake_ms=fake_ms)

        client.get("/auth/login?next=https://evil.example.com/steal")

        # El "next" externo nunca llega al intento guardado como destino valido.
        state, _ = fake_ms.last_auth_url_args
        attempt = await OAuthAttemptRepository.consume(state)
        assert attempt["next_path"] == "/"


class TestCallbackHappyPath:

    def test_direct_mode_sets_session_and_redirects_to_next_path(self):
        fake_ms = FakeMsAuth()
        client = build_client(fake_ms=fake_ms)

        login_resp = client.get("/auth/login?next=/bom/1/ui")
        state = _extract_state(login_resp.headers["location"])

        callback_resp = client.get(f"/auth/callback?code=abc123&state={state}")

        assert callback_resp.status_code == 307
        assert callback_resp.headers["location"] == "/bom/1/ui"
        assert client.cookies.get("session") is not None

    def test_popup_mode_returns_html_with_success_payload(self):
        fake_ms = FakeMsAuth()
        client = build_client(fake_ms=fake_ms)

        login_resp = client.get("/auth/login?popup=1&client_nonce=opener-abc")
        state = _extract_state(login_resp.headers["location"])

        callback_resp = client.get(f"/auth/callback?code=abc123&state={state}")

        assert callback_resp.status_code == 200
        assert "enertika-oauth" in callback_resp.text
        assert '"status": "success"' in callback_resp.text or '"status":"success"' in callback_resp.text
        assert "opener-abc" in callback_resp.text


class TestCallbackStateProtection:

    def test_state_is_consumed_only_once(self):
        fake_ms = FakeMsAuth()
        client = build_client(fake_ms=fake_ms)

        login_resp = client.get("/auth/login?next=/x")
        state = _extract_state(login_resp.headers["location"])

        first = client.get(f"/auth/callback?code=abc123&state={state}")
        assert first.status_code == 307

        # Reuso del mismo state (doble callback / replay): no debe 422, cae a login.
        second = client.get(f"/auth/callback?code=abc123&state={state}")
        assert second.status_code == 302
        assert second.headers["location"] == "/auth/login"

    def test_unknown_state_falls_back_to_login_not_422(self):
        client = build_client()

        response = client.get("/auth/callback?code=abc123&state=state-nunca-emitido")

        assert response.status_code == 302
        assert response.headers["location"] == "/auth/login"

    def test_nonce_mismatch_rejected(self):
        fake_ms = FakeMsAuth(nonce_matches=False)
        client = build_client(fake_ms=fake_ms)

        login_resp = client.get("/auth/login?next=/x")
        state = _extract_state(login_resp.headers["location"])

        response = client.get(f"/auth/callback?code=abc123&state={state}")

        # No 422, no sesion creada: cae al flujo de error/login.
        assert response.status_code == 302
        assert response.headers["location"] == "/auth/login"
        assert "session" not in response.cookies or response.cookies.get("session") is None


class TestCallbackCancellationAndError:

    def test_access_denied_does_not_return_422(self):
        client = build_client()

        response = client.get("/auth/callback?error=access_denied&error_description=El+usuario+cancelo&state=algo")

        assert response.status_code == 302
        assert response.headers["location"] == "/auth/login"

    def test_missing_code_does_not_return_422(self):
        fake_ms = FakeMsAuth()
        client = build_client(fake_ms=fake_ms)

        login_resp = client.get("/auth/login?next=/x")
        state = _extract_state(login_resp.headers["location"])

        response = client.get(f"/auth/callback?state={state}")

        assert response.status_code == 302
        assert response.headers["location"] == "/auth/login"

    def test_error_in_popup_mode_reports_via_postmessage_not_422(self):
        fake_ms = FakeMsAuth()
        client = build_client(fake_ms=fake_ms)

        login_resp = client.get("/auth/login?popup=1")
        state = _extract_state(login_resp.headers["location"])

        response = client.get(f"/auth/callback?error=server_error&error_description=Fallo+Microsoft&state={state}")

        assert response.status_code == 200
        assert '"status": "error"' in response.text or '"status":"error"' in response.text


class TestCallbackDeactivatedAccount:

    def test_deactivated_account_never_gets_a_cookie(self):
        fake_ms = FakeMsAuth()
        fake_conn = FakeConn(active=False)
        client = build_client(fake_conn=fake_conn, fake_ms=fake_ms)

        login_resp = client.get("/auth/login?next=/x")
        state = _extract_state(login_resp.headers["location"])

        response = client.get(f"/auth/callback?code=abc123&state={state}")

        assert response.status_code == 302
        assert response.headers["location"] == "/auth/login"
        assert client.cookies.get("session") is None
