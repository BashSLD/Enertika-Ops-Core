"""
Tests para el manejador central de autenticacion/autorizacion
(core/error_handlers.py): la respuesta se negocia segun el tipo de
solicitud (documento HTML, HTMX, API/fetch) sin reescribir HTTPException
de negocio.
"""
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from core.error_handlers import auth_exception_handler


def build_app():
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret-key", https_only=False)
    app.add_exception_handler(HTTPException, auth_exception_handler)

    @app.api_route("/protegido-401", methods=["GET", "HEAD"])
    async def protegido_401():
        raise HTTPException(status_code=401, detail="SESSION_EXPIRED")

    @app.get("/protegido-403")
    async def protegido_403():
        raise HTTPException(status_code=403, detail="No tienes permisos para esta accion.")

    @app.get("/negocio-404")
    async def negocio_404():
        raise HTTPException(status_code=404, detail="Recurso no encontrado")

    return app


@pytest.fixture
def client():
    return TestClient(build_app(), follow_redirects=False)


class TestSessionExpired401:

    def test_document_request_redirects_to_login(self, client):
        response = client.get("/protegido-401", headers={"Accept": "text/html"})

        assert response.status_code == 303
        assert response.headers["location"].startswith("/auth/login")
        assert response.headers.get("cache-control") == "no-store"

    def test_htmx_request_returns_401_with_reason_header(self, client):
        response = client.get("/protegido-401", headers={"HX-Request": "true"})

        assert response.status_code == 401
        assert response.headers.get("x-auth-reason") == "SESSION_EXPIRED"
        assert response.headers.get("hx-reswap") == "none"

    def test_history_restore_is_treated_as_document_not_htmx(self, client):
        """hx-history-restore-request activo: debe comportarse como documento
        completo (redirect), no como HTMX (401 in-page)."""
        response = client.get(
            "/protegido-401",
            headers={"HX-Request": "true", "HX-History-Restore-Request": "true"},
        )

        assert response.status_code == 303

    def test_api_request_returns_json_401(self, client):
        response = client.get("/protegido-401", headers={"Accept": "application/json"})

        assert response.status_code == 401
        assert response.json()["error"] == "SESSION_EXPIRED"

    def test_head_request_has_no_body(self, client):
        response = client.head("/protegido-401", headers={"HX-Request": "true"})

        assert response.status_code == 401
        assert response.text == ""


class TestForbidden403:

    def test_document_request_gets_spanish_denied_page(self, client):
        response = client.get("/protegido-403", headers={"Accept": "text/html"})

        assert response.status_code == 403
        assert "text/html" in response.headers["content-type"]
        assert "Acceso denegado" in response.text

    def test_htmx_request_gets_toast_with_reswap_none(self, client):
        response = client.get("/protegido-403", headers={"HX-Request": "true"})

        assert response.status_code == 403
        assert response.headers.get("hx-reswap") == "none"

    def test_api_request_gets_json_403(self, client):
        response = client.get("/protegido-403", headers={"Accept": "application/json"})

        assert response.status_code == 403
        assert response.json()["error"] == "FORBIDDEN"


class TestBusinessExceptionsUntouched:

    def test_404_business_exception_not_rewritten(self, client):
        response = client.get("/negocio-404", headers={"Accept": "text/html"})

        assert response.status_code == 404
        assert response.json()["detail"] == "Recurso no encontrado"

    def test_404_htmx_not_rewritten_as_toast(self, client):
        response = client.get("/negocio-404", headers={"HX-Request": "true"})

        assert response.status_code == 404
        assert response.json()["detail"] == "Recurso no encontrado"
