import pytest
from fastapi.testclient import TestClient
from main import app
import core.microsoft

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture(autouse=True)
def mock_ms_auth(monkeypatch):
    """
    Simula la clase MicrosoftAuth para evitar llamadas reales a Graph API
    durante los tests.
    """
    class MockMicrosoftAuth:
        _instance = None
        def __new__(cls):
            if cls._instance is None:
                cls._instance = super(MockMicrosoftAuth, cls).__new__(cls)
            return cls._instance

        def get_auth_url(self):
            return "http://localhost/mock-login-url"
            
        def get_token_from_code(self, code):
            return {"access_token": "mock_token_123", "refresh_token": "mock_refresh"}
            
        def get_user_profile(self, token):
            return {
                "displayName": "Usuario Test",
                "mail": "test@enertika.mx",
                "userPrincipalName": "test@enertika.mx"
            }

        def send_email_with_attachments(self, access_token, subject, body, recipients, cc_recipients=None, bcc_recipients=None, attachments_files=None):
            # Simulamos éxito siempre
            print(f"[MOCK] Enviando correo a {recipients} | Subject: {subject}")
            return True, "Correo Simulado Exitoso"

    # Reemplazamos la clase real con el Mock en el módulo core.microsoft
    monkeypatch.setattr(core.microsoft, "MicrosoftAuth", MockMicrosoftAuth)
