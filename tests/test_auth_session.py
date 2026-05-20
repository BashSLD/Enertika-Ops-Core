import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from modules.auth.router import router as auth_router
from modules.auth.service import process_login_callback


def get_test_client():
    app = FastAPI()
    app.add_middleware(
        SessionMiddleware,
        secret_key="test-secret-key",
        same_site="lax",
        https_only=False,
    )
    app.include_router(auth_router)
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
    test_client = TestClient(app)

    test_client.get("/set-session")
    response = test_client.get("/auth/session")

    assert response.status_code == 200
    data = response.json()
    assert data["active"] is True
    assert data["email"] == "test@enertika.mx"


def test_session_endpoint_soporta_head():
    client = get_test_client()

    response = client.head("/auth/session")

    assert response.status_code == 401
    assert response.text == ""


class FakeConn:
    def __init__(self):
        self.query = None
        self.args = None

    async def execute(self, query, *args):
        self.query = query
        self.args = args


class FakeMicrosoftAuth:
    async def get_token_from_code(self, code):
        assert code == "auth-code"
        return {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "expires_in": 3600,
            "id_token_claims": {
                "preferred_username": "USER@ENERTIKA.MX",
                "name": "Usuario Test",
            },
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
async def test_process_login_callback_rejects_missing_email():
    class AuthWithoutEmail(FakeMicrosoftAuth):
        async def get_token_from_code(self, code):
            token_result = await super().get_token_from_code(code)
            token_result["id_token_claims"] = {"name": "Usuario Test"}
            return token_result

    conn = FakeConn()

    with pytest.raises(ValueError, match="email"):
        await process_login_callback(conn, "auth-code", AuthWithoutEmail())

    assert conn.query is None
