"""
Tests para el interruptor EMAIL_SEND_ENABLED en MicrosoftAuth.send_email_with_attachments
(core/microsoft.py). Es el unico choke point real de envio de correo: todos los
callers del proyecto (notification_service, tasks.py, pdf_service, etc.) pasan
por aqui, tanto en modo directo como en modo pesado (_send_heavy_email).
"""
import pytest
from unittest.mock import AsyncMock

from core.config import settings
from core.microsoft import MicrosoftAuth


@pytest.mark.asyncio
async def test_send_email_suprimido_cuando_email_send_disabled(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_SEND_ENABLED", False)

    ms_auth = MicrosoftAuth()
    mock_post = AsyncMock()
    monkeypatch.setattr(ms_auth._http_client, "post", mock_post)

    success, msg = await ms_auth.send_email_with_attachments(
        access_token="fake-token",
        from_email="remitente@enertika.mx",
        subject="Asunto de prueba",
        body="<p>Cuerpo</p>",
        recipients=["destino@enertika.mx"],
    )

    assert success is True
    mock_post.assert_not_called()


@pytest.mark.asyncio
async def test_send_email_no_se_suprime_cuando_email_send_enabled(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_SEND_ENABLED", True)

    ms_auth = MicrosoftAuth()
    mock_response = AsyncMock()
    mock_response.status_code = 202
    mock_post = AsyncMock(return_value=mock_response)
    monkeypatch.setattr(ms_auth._http_client, "post", mock_post)

    success, msg = await ms_auth.send_email_with_attachments(
        access_token="fake-token",
        from_email="remitente@enertika.mx",
        subject="Asunto de prueba",
        body="<p>Cuerpo</p>",
        recipients=["destino@enertika.mx"],
    )

    assert success is True
    mock_post.assert_called_once()
