import pytest
from core.microsoft import get_ms_auth

def test_health_check(client):
    """Verifica que la app levante y responda lo básico (aunque root path da 404 o redirect)."""
    # En tu main.py puede que la raíz '/' redirija a login o sea 404 porque no tienes ruta '/' definida.
    # Probemos llamar al endpoint de health si tienes o validar que app carga.
    response = client.get("/") 
    # Si no tienes root, esperamos 404 o 307. Solo validamos que no explote (500).
    assert response.status_code != 500

def test_mock_ms_auth_interception():
    """Verifica que el fixture mock_ms_auth esté interceptando la clase real."""
    auth = get_ms_auth()
    
    # 1. Verificar URL Falsa
    url = auth.get_auth_url()
    assert url == "http://localhost/mock-login-url"
    
    # 2. Verificar Envío Simulado
    ok, msg = auth.send_email_with_attachments(
        "token_falso", "Asunto Test", "Cuerpo", ["test@test.com"]
    )
    assert ok is True
    assert msg == "Correo Simulado Exitoso"
