"""
notify_horas_extra_aprobacion enruta destinatarios via el mecanismo centralizado
de configuracion (_get_emails_for_event + placeholder {EMPLEADO} en tb_config_emails),
sin logica de negocio hardcodeada por fuera de la configuracion de RH.
Ver migrations/140_evento_aprobacion_horas_extra.sql y PENDIENTES_RH.md #3.3.
"""
from __future__ import annotations

from datetime import date

import pytest

from core.workflow.notification_service import NotificationService, PLACEHOLDER_EMPLEADO

pytestmark = pytest.mark.asyncio


class FakeDB:
    def __init__(self, emails_by_type: dict[str, set[str]]):
        self._emails_by_type = emails_by_type
        self.sender = {"email_remitente": "no-reply@enertika.mx", "nombre_remitente": "Enertika"}

    async def get_emails_for_event(self, _conn, _trigger_value, type_filter, _modulos=None):
        return set(self._emails_by_type.get(type_filter, set()))

    async def get_notification_sender(self, _conn, _departamento):
        return self.sender

    async def get_default_notification_sender(self, _conn):
        return self.sender


async def test_get_emails_for_event_resuelve_placeholder_con_empleado():
    db = FakeDB({"TO": {PLACEHOLDER_EMPLEADO}})
    svc = NotificationService(db=db)

    emails = await svc._get_emails_for_event(
        None, "APROBACION_HORAS_EXTRA", "TO", empleado_email="empleado@enertika.mx"
    )

    assert emails == {"empleado@enertika.mx"}


async def test_get_emails_for_event_descarta_placeholder_sin_empleado():
    db = FakeDB({"TO": {PLACEHOLDER_EMPLEADO, "rh@enertika.mx"}})
    svc = NotificationService(db=db)

    emails = await svc._get_emails_for_event(None, "APROBACION_HORAS_EXTRA", "TO")

    assert emails == {"rh@enertika.mx"}


async def test_notify_horas_extra_aprobacion_envia_to_empleado_cc_configurado(monkeypatch):
    db = FakeDB({"TO": {PLACEHOLDER_EMPLEADO}, "CC": {"rh@enertika.mx"}})
    svc = NotificationService(db=db)
    calls = {}

    async def fake_send_email(to_emails, cc_emails, _subject, _html, _sender_email, **_kwargs):
        calls["to"] = to_emails
        calls["cc"] = cc_emails
        return True

    monkeypatch.setattr(svc, "_send_email", fake_send_email)
    monkeypatch.setattr(svc, "_render_template", lambda *_a, **_k: "<html></html>")

    await svc.notify_horas_extra_aprobacion(
        None,
        aprobador_nombre="Jefe Test",
        empleado_nombre="Empleado Test",
        empleado_email="empleado@enertika.mx",
        dias_aprobados=[{"fecha": date(2026, 7, 1), "minutos_aprobados": 120}],
        comentario="ok",
    )

    assert calls["to"] == {"empleado@enertika.mx"}
    assert calls["cc"] == {"rh@enertika.mx"}


async def test_notify_horas_extra_aprobacion_sin_destinatarios_omite(monkeypatch):
    db = FakeDB({})
    svc = NotificationService(db=db)

    async def fake_send_email(*_a, **_k):
        raise AssertionError("no deberia enviar sin destinatarios TO")

    monkeypatch.setattr(svc, "_send_email", fake_send_email)

    await svc.notify_horas_extra_aprobacion(
        None,
        aprobador_nombre="Jefe Test",
        empleado_nombre="Empleado Test",
        empleado_email=None,
        dias_aprobados=[],
        comentario="",
    )
