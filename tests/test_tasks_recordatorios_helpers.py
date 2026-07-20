"""
Los helpers _procesar_recordatorios_pendientes / _enviar_resumen_rh_si_corresponde
(core/tasks.py) generalizan la logica de orquestacion que antes estaba duplicada
casi linea por linea entre horas-extra y compensatorio dentro de
verificar_recordatorios_horas_extra_periodically. Ver PENDIENTES_RH.md #3.1.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from core.tasks import _enviar_resumen_rh_si_corresponde, _procesar_recordatorios_pendientes

pytestmark = pytest.mark.asyncio


async def test_procesar_recordatorios_omite_sin_destinatarios():
    row_id = uuid4()
    calls = {"notify": 0, "mark": 0}

    async def notify_fn(_conn, **_kwargs):
        calls["notify"] += 1
        return True

    async def mark_fn(_conn, _row_id):
        calls["mark"] += 1

    await _procesar_recordatorios_pendientes(
        None,
        [{"id": row_id, "jefe_emails": [], "recordatorios_enviados": 0}],
        rh_emails=set(),
        escalacion_cc=set(),
        escalacion_cco=set(),
        campo_contador="recordatorios_enviados",
        notify_fn=notify_fn,
        row_to_kwargs=lambda row: {},
        mark_fn=mark_fn,
        log_tag="TEST",
    )

    assert calls["notify"] == 0
    assert calls["mark"] == 0


async def test_procesar_recordatorios_envia_y_marca():
    row_id = uuid4()
    row = {
        "id": row_id,
        "jefe_emails": ["jefe@enertika.mx"],
        "tiene_director": False,
        "recordatorios_enviados": 1,
        "empleado_nombre": "Empleado Test",
    }
    captured = {}

    async def notify_fn(_conn, **kwargs):
        captured.update(kwargs)
        return True

    async def mark_fn(_conn, marked_id):
        captured["marked_id"] = marked_id

    await _procesar_recordatorios_pendientes(
        None,
        [row],
        rh_emails={"rh@enertika.mx"},
        escalacion_cc=set(),
        escalacion_cco=set(),
        campo_contador="recordatorios_enviados",
        notify_fn=notify_fn,
        row_to_kwargs=lambda r: {"empleado_nombre": r["empleado_nombre"]},
        mark_fn=mark_fn,
        log_tag="TEST",
    )

    assert captured["destinatarios"] == {"jefe@enertika.mx"}
    assert captured["cc_emails"] == set()
    assert captured["bcc_emails"] == set()
    assert captured["url_aprobacion"].endswith("/perfil/ui?tab=aprobaciones")
    assert captured["recordatorio_numero"] == 2
    assert captured["empleado_nombre"] == "Empleado Test"
    assert captured["marked_id"] == row_id


async def test_procesar_recordatorios_no_marca_si_no_enviado():
    calls = {"mark": 0}

    async def notify_fn(_conn, **_kwargs):
        return False

    async def mark_fn(_conn, _row_id):
        calls["mark"] += 1

    await _procesar_recordatorios_pendientes(
        None,
        [{"id": uuid4(), "jefe_emails": ["jefe@enertika.mx"], "recordatorios_enviados": 0}],
        rh_emails=set(),
        escalacion_cc=set(),
        escalacion_cco=set(),
        campo_contador="recordatorios_enviados",
        notify_fn=notify_fn,
        row_to_kwargs=lambda row: {},
        mark_fn=mark_fn,
        log_tag="TEST",
    )

    assert calls["mark"] == 0


async def test_procesar_recordatorios_override_activo_ignora_jerarquia_normal():
    captured = {}

    async def notify_fn(_conn, **kwargs):
        captured.update(kwargs)
        return True

    async def mark_fn(_conn, _row_id):
        return None

    await _procesar_recordatorios_pendientes(
        None,
        [{
            "id": uuid4(),
            "tiene_override": True,
            "override_email": "aprobador.exclusivo@enertika.mx",
            "jefe_emails": ["jefe_historico@enertika.mx"],
            "tiene_director": True,
            "aprobador_vac_email": "aprobador.vacaciones@enertika.mx",
            "recordatorios_enviados": 0,
        }],
        rh_emails={"rh@enertika.mx"},
        escalacion_cc={"rh_config@enertika.mx"},
        escalacion_cco={"admin_config@enertika.mx"},
        campo_contador="recordatorios_enviados",
        notify_fn=notify_fn,
        row_to_kwargs=lambda row: {},
        mark_fn=mark_fn,
        log_tag="TEST",
    )

    assert captured["destinatarios"] == {"aprobador.exclusivo@enertika.mx"}
    assert captured["cc_emails"] == set()
    assert captured["bcc_emails"] == set()
    assert captured["url_aprobacion"].endswith("/perfil/ui?tab=aprobaciones")


async def test_procesar_recordatorios_override_inactivo_cae_a_fallback_rh():
    captured = {}

    async def notify_fn(_conn, **kwargs):
        captured.update(kwargs)
        return True

    async def mark_fn(_conn, _row_id):
        return None

    await _procesar_recordatorios_pendientes(
        None,
        [{
            "id": uuid4(),
            "tiene_override": True,
            "override_email": None,
            "jefe_emails": ["jefe_historico@enertika.mx"],
            "tiene_director": False,
            "aprobador_vac_email": None,
            "recordatorios_enviados": 0,
        }],
        rh_emails={"rh@enertika.mx", "admin@enertika.mx"},
        escalacion_cc=set(),
        escalacion_cco=set(),
        campo_contador="recordatorios_enviados",
        notify_fn=notify_fn,
        row_to_kwargs=lambda row: {},
        mark_fn=mark_fn,
        log_tag="TEST",
    )

    assert captured["destinatarios"] == {"rh@enertika.mx", "admin@enertika.mx"}
    assert captured["url_aprobacion"].endswith("/rrhh/ui?tab=aprobaciones")


async def test_procesar_recordatorios_via_rh_y_cc_cuando_tiene_director():
    captured = {}

    async def notify_fn(_conn, **kwargs):
        captured.update(kwargs)
        return True

    async def mark_fn(_conn, _row_id):
        return None

    await _procesar_recordatorios_pendientes(
        None,
        [{"id": uuid4(), "jefe_emails": [], "tiene_director": True, "recordatorios_enviados": 0}],
        rh_emails={"rh@enertika.mx"},
        escalacion_cc={"rh_config@enertika.mx"},
        escalacion_cco={"admin_config@enertika.mx"},
        campo_contador="recordatorios_enviados",
        notify_fn=notify_fn,
        row_to_kwargs=lambda row: {},
        mark_fn=mark_fn,
        log_tag="TEST",
    )

    assert captured["destinatarios"] == {"rh@enertika.mx"}
    assert captured["url_aprobacion"].endswith("/rrhh/ui?tab=aprobaciones")
    assert captured["cc_emails"] == set()
    assert captured["bcc_emails"] == set()


async def test_procesar_recordatorios_escalacion_director_usa_cc_cco_configurados():
    """Jefe real en TO + tiene_director=True: a diferencia del caso anterior (sin jefe,
    cae al fallback RH por TO), aqui si aplica la escalacion y CC/CCO deben venir de la
    config de Admin, no del pool de fallback por rol."""
    captured = {}

    async def notify_fn(_conn, **kwargs):
        captured.update(kwargs)
        return True

    async def mark_fn(_conn, _row_id):
        return None

    await _procesar_recordatorios_pendientes(
        None,
        [{
            "id": uuid4(),
            "jefe_emails": ["jefe@enertika.mx"],
            "tiene_director": True,
            "recordatorios_enviados": 0,
        }],
        rh_emails={"rh@enertika.mx"},
        escalacion_cc={"rh_config@enertika.mx"},
        escalacion_cco={"admin_config@enertika.mx"},
        campo_contador="recordatorios_enviados",
        notify_fn=notify_fn,
        row_to_kwargs=lambda row: {},
        mark_fn=mark_fn,
        log_tag="TEST",
    )

    assert captured["destinatarios"] == {"jefe@enertika.mx"}
    assert captured["cc_emails"] == {"rh_config@enertika.mx"}
    assert captured["bcc_emails"] == {"admin_config@enertika.mx"}
    assert captured["url_aprobacion"].endswith("/perfil/ui?tab=aprobaciones")


async def test_enviar_resumen_rh_no_envia_sin_rows_o_sin_rh_emails():
    calls = {"notify": 0}

    async def notify_fn(_conn, **_kwargs):
        calls["notify"] += 1
        return True

    async def mark_fn(_conn, _ids):
        pass

    await _enviar_resumen_rh_si_corresponde(
        None, [], rh_emails={"rh@enertika.mx"},
        row_to_extra_fields=lambda row: {},
        notify_fn=notify_fn, mark_fn=mark_fn, log_tag="TEST",
    )
    await _enviar_resumen_rh_si_corresponde(
        None, [{"id": uuid4()}], rh_emails=set(),
        row_to_extra_fields=lambda row: {},
        notify_fn=notify_fn, mark_fn=mark_fn, log_tag="TEST",
    )

    assert calls["notify"] == 0


async def test_enviar_resumen_rh_envia_y_marca_ids():
    row_ids = [uuid4(), uuid4()]
    rows = [{"id": rid, "valor": i} for i, rid in enumerate(row_ids)]
    captured = {}

    async def notify_fn(_conn, *, rows, rh_emails):
        captured["rows"] = rows
        captured["rh_emails"] = rh_emails
        return True

    async def mark_fn(_conn, ids):
        captured["marked_ids"] = ids

    await _enviar_resumen_rh_si_corresponde(
        None, rows, rh_emails={"rh@enertika.mx"},
        row_to_extra_fields=lambda row: {"extra": row["valor"] * 10},
        notify_fn=notify_fn, mark_fn=mark_fn, log_tag="TEST",
    )

    assert captured["rh_emails"] == {"rh@enertika.mx"}
    assert captured["marked_ids"] == row_ids
    assert captured["rows"][0]["extra"] == 0
    assert captured["rows"][1]["extra"] == 10


async def test_enviar_resumen_rh_no_marca_si_no_enviado():
    calls = {"mark": 0}

    async def notify_fn(_conn, **_kwargs):
        return False

    async def mark_fn(_conn, _ids):
        calls["mark"] += 1

    await _enviar_resumen_rh_si_corresponde(
        None, [{"id": uuid4()}], rh_emails={"rh@enertika.mx"},
        row_to_extra_fields=lambda row: {},
        notify_fn=notify_fn, mark_fn=mark_fn, log_tag="TEST",
    )

    assert calls["mark"] == 0
