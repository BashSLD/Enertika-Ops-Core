import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from core.database import get_db_connection
from modules.auth.router import router as auth_router
from modules.auth.service import process_login_callback


class FakeSessionConn:
    """Sustituye a get_db_connection para las rutas de /auth/session:
    check_session_active usa security_db.get_user_is_active (fetchval),
    otras rutas de auth usan get_user_by_email (fetchrow, dict-like)."""

    def __init__(self, active: bool = True, exists: bool = True):
        self.active = active
        self.exists = exists

    async def fetchrow(self, query, email):
        if not self.exists:
            return None
        return {
            "id_usuario": 1,
            "nombre": "Usuario Test",
            "rol_sistema": "USER",
            "department": None,
            "puesto": None,
            "modulo_preferido": None,
            "rol_organizacional": None,
            "is_active": self.active,
        }

    async def fetchval(self, query, email):
        if not self.exists:
            return None
        return self.active


def get_test_client(fake_conn: FakeSessionConn | None = None):
    app = FastAPI()
    app.add_middleware(
        SessionMiddleware,
        secret_key="test-secret-key",
        same_site="lax",
        https_only=False,
    )
    app.include_router(auth_router)
    app.dependency_overrides[get_db_connection] = lambda: (fake_conn or FakeSessionConn())
    return TestClient(app)


def test_session_no_activa_retorna_401():
    client = get_test_client()

    response = client.get("/auth/session")

    assert response.status_code == 401
    data = response.json()
    assert data["active"] is False


def test_session_activa_retorna_200_con_email():
    app = FastAPI()
    app.add_middleware(
        SessionMiddleware,
        secret_key="test-secret-key",
    )

    @app.get("/set-session")
    def set_session(request: Request):
        request.session["user_email"] = "test@enertika.mx"
        request.session["user_name"] = "Usuario Test"
        return {"status": "ok"}

    app.include_router(auth_router)
    app.dependency_overrides[get_db_connection] = lambda: FakeSessionConn(active=True)
    test_client = TestClient(app)

    test_client.get("/set-session")
    response = test_client.get("/auth/session")

    assert response.status_code == 200
    data = response.json()
    assert data["active"] is True
    assert data["email"] == "test@enertika.mx"


def test_session_usuario_desactivado_retorna_401():
    """Cuenta desactivada localmente (is_active=False): cookie sigue presente
    pero la sesion ya no cuenta como activa (ver /auth/session)."""
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret-key")

    @app.get("/set-session")
    def set_session(request: Request):
        request.session["user_email"] = "deshabilitado@enertika.mx"
        return {"status": "ok"}

    app.include_router(auth_router)
    app.dependency_overrides[get_db_connection] = lambda: FakeSessionConn(active=False)
    test_client = TestClient(app)

    test_client.get("/set-session")
    response = test_client.get("/auth/session")

    assert response.status_code == 401
    assert response.json()["active"] is False


def test_session_endpoint_soporta_head():
    client = get_test_client()

    response = client.head("/auth/session")

    assert response.status_code == 401
    assert response.text == ""


def test_session_response_tiene_cache_control_no_store():
    client = get_test_client()

    response = client.get("/auth/session")

    assert response.headers.get("cache-control") == "no-store"


class FakeConn:
    def __init__(self, active: bool = True):
        self.query = None
        self.args = None
        self.active = active

    async def fetchval(self, query, *args):
        self.query = query
        self.args = args
        return self.active


class FakeMicrosoftAuth:
    def __init__(self, nonce_claim: str | None = "expected-nonce"):
        self._nonce_claim = nonce_claim

    async def get_token_from_code(self, code, nonce=None):
        assert code == "auth-code"
        claims = {
            "preferred_username": "USER@ENERTIKA.MX",
            "name": "Usuario Test",
        }
        if self._nonce_claim is not None:
            claims["nonce"] = self._nonce_claim
        return {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "expires_in": 3600,
            "id_token_claims": claims,
        }

    async def get_user_profile(self, token):
        assert token == "access-token"
        return {"department": "Operaciones", "jobTitle": "Coordinador"}


@pytest.mark.asyncio
async def test_process_login_callback_upserts_user(monkeypatch):
    conn = FakeConn()
    monkeypatch.setattr("modules.auth.service.time.time", lambda: 1000)

    result = await process_login_callback(conn, "auth-code", FakeMicrosoftAuth())

    assert result == {"email": "user@enertika.mx", "name": "Usuario Test"}
    assert "INSERT INTO tb_usuarios" in conn.query
    assert conn.args == (
        "Usuario Test",
        "user@enertika.mx",
        "access-token",
        "refresh-token",
        4600,
        "Operaciones",
        "Coordinador",
    )


@pytest.mark.asyncio
async def test_process_login_callback_rejects_inactive_user(monkeypatch):
    """Microsoft puede autenticar sin problema aunque la cuenta este
    desactivada localmente; el rechazo debe venir del service (no del router)
    para que comparta el mismo camino de manejo de errores que el resto de
    las reglas de negocio del login (nonce, access_token, etc.)."""
    conn = FakeConn(active=False)
    monkeypatch.setattr("modules.auth.service.time.time", lambda: 1000)

    with pytest.raises(ValueError, match="desactivada"):
        await process_login_callback(conn, "auth-code", FakeMicrosoftAuth())


@pytest.mark.asyncio
async def test_process_login_callback_rejects_missing_email():
    class AuthWithoutEmail(FakeMicrosoftAuth):
        async def get_token_from_code(self, code, nonce=None):
            token_result = await super().get_token_from_code(code, nonce=nonce)
            token_result["id_token_claims"] = {"name": "Usuario Test"}
            return token_result

    conn = FakeConn()

    with pytest.raises(ValueError, match="email"):
        await process_login_callback(conn, "auth-code", AuthWithoutEmail())

    assert conn.query is None


@pytest.mark.asyncio
async def test_process_login_callback_valid_nonce_ok(monkeypatch):
    conn = FakeConn()
    monkeypatch.setattr("modules.auth.service.time.time", lambda: 1000)

    result = await process_login_callback(
        conn, "auth-code", FakeMicrosoftAuth(nonce_claim="expected-nonce"),
        expected_nonce="expected-nonce",
    )

    assert result["email"] == "user@enertika.mx"


@pytest.mark.asyncio
async def test_process_login_callback_nonce_mismatch_rejected(monkeypatch):
    """El nonce en el id_token no corresponde al que se genero para este
    intento (posible replay/mezcla de flujos concurrentes): debe rechazarse
    sin guardar nada, no solo confiar en el 'code' recibido."""
    conn = FakeConn()
    monkeypatch.setattr("modules.auth.service.time.time", lambda: 1000)

    with pytest.raises(ValueError, match="nonce"):
        await process_login_callback(
            conn, "auth-code", FakeMicrosoftAuth(nonce_claim="otro-nonce"),
            expected_nonce="expected-nonce",
        )

    assert conn.query is None
