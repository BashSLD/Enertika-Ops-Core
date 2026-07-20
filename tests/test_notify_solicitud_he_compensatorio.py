"""
notify_horas_extra_solicitud / notify_compensatorio_solicitud y
notify_horas_extra_resumen_rh / notify_compensatorio_resumen_rh comparten
ahora la orquestacion via _notify_solicitud_pendiente / _notify_resumen_rh
(core/workflow/notification_service.py). Antes eran ~4 metodos casi
duplicados linea por linea. Ver PENDIENTES_RH.md #3.2.
"""
from __future__ import annotations

from datetime import date

import pytest

from core.workflow.notification_service import NotificationService

pytestmark = pytest.mark.asyncio


class FakeDB:
    sender = {"email_remitente": "no-reply@enertika.mx", "nombre_remitente": "Enertika"}

    async def get_notification_sender(self, _conn, _departamento):
        return self.sender

    async def get_default_notification_sender(self, _conn):
        return self.sender


def _svc_con_captura(monkeypatch):
    svc = NotificationService(db=FakeDB())
    captured = {}

    async def fake_send_email(to_emails, cc_emails, subject, _html, _sender_email, **kwargs):
        captured["to"] = to_emails
        captured["cc"] = cc_emails
        captured["bcc"] = kwargs.get("bcc_emails")
        captured["subject"] = subject
        return True

    async def fake_save_and_broadcast(*, conn, recipient_email, tipo, titulo, mensaje, id_oportunidad, modulo_origen):
        captured.setdefault("broadcasts", []).append(
            {"recipient_email": recipient_email, "titulo": titulo, "mensaje": mensaje, "modulo_origen": modulo_origen}
        )

    monkeypatch.setattr(svc, "_send_email", fake_send_email)
    monkeypatch.setattr(svc, "_save_and_broadcast", fake_save_and_broadcast)
    monkeypatch.setattr(svc, "_render_template", lambda *_a, **_k: "<html></html>")
    return svc, captured


async def test_notify_horas_extra_solicitud_envia_y_notifica(monkeypatch):
    svc, captured = _svc_con_captura(monkeypatch)

    enviado = await svc.notify_horas_extra_solicitud(
        None,
        empleado_nombre="Empleado Test",
        fecha_laboral=date(2026, 7, 1),
        extra_fmt="2h",
        motivo="Cierre urgente",
        destinatarios={"jefe@enertika.mx"},
        url_aprobacion="https://app.test/perfil/ui?tab=aprobaciones",
        label_boton="Revisar en Aprobaciones",
    )

    assert enviado is True
    assert captured["subject"] == "Solicitud de horas extra: Empleado Test"
    assert captured["broadcasts"][0]["modulo_origen"] == "asistencia"
    assert "01/07/2026" in captured["broadcasts"][0]["mensaje"]


async def test_notify_horas_extra_solicitud_recordatorio_cambia_subject(monkeypatch):
    svc, captured = _svc_con_captura(monkeypatch)

    await svc.notify_horas_extra_solicitud(
        None,
        empleado_nombre="Empleado Test",
        fecha_laboral=date(2026, 7, 1),
        extra_fmt="2h",
        motivo="Cierre urgente",
        destinatarios={"jefe@enertika.mx"},
        url_aprobacion="https://app.test/perfil/ui?tab=aprobaciones",
        label_boton="Revisar en Aprobaciones",
        es_recordatorio=True,
    )

    assert captured["subject"] == "Recordatorio de horas extra pendiente: Empleado Test"


async def test_notify_horas_extra_solicitud_propaga_bcc(monkeypatch):
    svc, captured = _svc_con_captura(monkeypatch)

    await svc.notify_horas_extra_solicitud(
        None,
        empleado_nombre="Empleado Test",
        fecha_laboral=date(2026, 7, 1),
        extra_fmt="2h",
        motivo="Cierre urgente",
        destinatarios={"jefe@enertika.mx"},
        cc_emails={"rh@enertika.mx"},
        bcc_emails={"admin@enertika.mx"},
        url_aprobacion="https://app.test/perfil/ui?tab=aprobaciones",
        label_boton="Revisar en Aprobaciones",
    )

    assert captured["cc"] == {"rh@enertika.mx"}
    assert captured["bcc"] == {"admin@enertika.mx"}


async def test_notify_compensatorio_solicitud_envia_y_notifica(monkeypatch):
    svc, captured = _svc_con_captura(monkeypatch)

    enviado = await svc.notify_compensatorio_solicitud(
        None,
        empleado_nombre="Empleado Test",
        fecha_descanso=date(2026, 7, 10),
        minutos_fmt="1h 30m",
        motivo="Descanso",
        destinatarios={"jefe@enertika.mx"},
        url_aprobacion="https://app.test/perfil/ui?tab=aprobaciones",
        label_boton="Revisar en Aprobaciones",
    )

    assert enviado is True
    assert captured["subject"] == "Solicitud de tiempo compensatorio: Empleado Test"
    assert captured["broadcasts"][0]["modulo_origen"] == "asistencia"


async def test_notify_solicitud_sin_destinatarios_no_envia(monkeypatch):
    svc, captured = _svc_con_captura(monkeypatch)

    enviado = await svc.notify_horas_extra_solicitud(
        None,
        empleado_nombre="Empleado Test",
        fecha_laboral=date(2026, 7, 1),
        extra_fmt="2h",
        motivo="",
        destinatarios=set(),
        url_aprobacion="https://app.test/perfil/ui?tab=aprobaciones",
        label_boton="Revisar en Aprobaciones",
    )

    assert enviado is False
    assert "to" not in captured


async def test_notify_horas_extra_resumen_rh_envia(monkeypatch):
    svc, captured = _svc_con_captura(monkeypatch)

    enviado = await svc.notify_horas_extra_resumen_rh(
        None, rows=[{"id": 1}], rh_emails={"rh@enertika.mx"}
    )

    assert enviado is True
    assert captured["subject"] == "Resumen semanal: horas extra pendientes de resolver"
    assert captured["to"] == {"rh@enertika.mx"}


async def test_notify_compensatorio_resumen_rh_envia(monkeypatch):
    svc, captured = _svc_con_captura(monkeypatch)

    enviado = await svc.notify_compensatorio_resumen_rh(
        None, rows=[{"id": 1}], rh_emails={"rh@enertika.mx"}
    )

    assert enviado is True
    assert captured["subject"] == "Resumen semanal: tiempo compensatorio pendiente"


async def test_notify_resumen_rh_sin_rows_no_envia(monkeypatch):
    svc, captured = _svc_con_captura(monkeypatch)

    enviado = await svc.notify_horas_extra_resumen_rh(None, rows=[], rh_emails={"rh@enertika.mx"})

    assert enviado is False
    assert "subject" not in captured
