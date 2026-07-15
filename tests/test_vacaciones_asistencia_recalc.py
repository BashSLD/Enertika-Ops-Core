"""
Tests de la interaccion vacaciones/service.py <-> recalculo de asistencia
(_Planes_Activos/PLAN_ASISTENCIA_AUSENCIAS_DESCANSO.md). Usan FakeConn/monkeypatch,
sin BD real.
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

import pytest

from modules.vacaciones import service as vacaciones_service


class FakeConn:
    def transaction(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _solicitud(
    *,
    usuario_id,
    fecha_inicio: date,
    fecha_fin: date,
    tipo_slug: str,
    justifica_asistencia_dia: bool,
    estado: str = "aprobado",
) -> dict:
    return {
        "id": uuid4(),
        "usuario_id": usuario_id,
        "fecha_inicio": fecha_inicio,
        "fecha_fin": fecha_fin,
        "tipo_slug": tipo_slug,
        "justifica_asistencia_dia": justifica_asistencia_dia,
        "estado": estado,
        "firma_solicitante_pendiente": False,
    }


@pytest.mark.asyncio
async def test_recalcular_por_solicitud_home_office_no_se_omite(monkeypatch):
    """Regresion: antes de este fix, justifica_asistencia_dia=false (home_office,
    permiso_llegar_tarde, permiso_salir_temprano) hacia return temprano y el dia nunca
    se reclasificaba al aprobar/rechazar/cancelar la solicitud."""
    usuario_id = uuid4()
    fecha = date(2026, 7, 20)
    solicitud = _solicitud(
        usuario_id=usuario_id,
        fecha_inicio=fecha,
        fecha_fin=fecha,
        tipo_slug="home_office",
        justifica_asistencia_dia=False,
    )

    llamadas = {}

    async def fake_recalcular(_conn, targets):
        llamadas["targets"] = targets
        return []

    monkeypatch.setattr(vacaciones_service, "recalcular_asistencia", fake_recalcular)

    await vacaciones_service._recalcular_asistencia_por_solicitud(FakeConn(), solicitud)

    assert llamadas.get("targets") == [(usuario_id, fecha)]


@pytest.mark.asyncio
async def test_recalcular_por_solicitud_rango_multiple_dias(monkeypatch):
    usuario_id = uuid4()
    fecha_inicio = date(2026, 7, 17)  # viernes
    fecha_fin = date(2026, 7, 20)  # lunes
    solicitud = _solicitud(
        usuario_id=usuario_id,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        tipo_slug="vacaciones",
        justifica_asistencia_dia=True,
    )

    llamadas = {}

    async def fake_recalcular(_conn, targets):
        llamadas["targets"] = targets
        return []

    monkeypatch.setattr(vacaciones_service, "recalcular_asistencia", fake_recalcular)

    await vacaciones_service._recalcular_asistencia_por_solicitud(FakeConn(), solicitud)

    esperado = [fecha_inicio + timedelta(days=offset) for offset in range(4)]
    assert [t[1] for t in llamadas["targets"]] == esperado


@pytest.mark.asyncio
async def test_aprobar_solicitud_usa_lock_compartido_con_compensatorio(monkeypatch):
    """El lock de aprobar/rechazar/cancelar debe ser el mismo namespace que usa
    solicitar_compensatorio_svc (asistencia_db.lock_he_usuario), para serializar
    ausencias y compensatorio del mismo usuario bajo una sola primitiva."""
    usuario_id = uuid4()
    solicitud_id = uuid4()
    aprobador_id = uuid4()
    fecha = date(2026, 7, 20)
    solicitud = _solicitud(
        usuario_id=usuario_id,
        fecha_inicio=fecha,
        fecha_fin=fecha,
        tipo_slug="vacaciones",
        justifica_asistencia_dia=True,
        estado="pendiente",
    )

    locks = []

    async def fake_lock(_conn, uid):
        locks.append(uid)

    async def fake_puede_aprobar(_conn, _solicitud_id, _aprobador_id, _ctx):
        return True

    async def fake_get_solicitud(_conn, _solicitud_id):
        return solicitud

    async def fake_get_firma(_conn, _usuario_id):
        return {"firma_data": b"x"}

    async def fake_insert_firma(_conn, _solicitud_id, _actor_id, _rol):
        return None

    async def fake_update_estado(_conn, _solicitud_id, _estado, **_kwargs):
        return None

    async def fake_recalcular_por_solicitud(_conn, _solicitud):
        return None

    class _FakeNotif:
        async def notify_vacation_approved(self, _conn, _solicitud):
            return None

    monkeypatch.setattr(vacaciones_service.asistencia_db, "lock_he_usuario", fake_lock)
    monkeypatch.setattr(vacaciones_service, "puede_aprobar", fake_puede_aprobar)
    monkeypatch.setattr(vacaciones_service.db, "get_solicitud", fake_get_solicitud)
    monkeypatch.setattr(vacaciones_service.signatures_db, "get_firma_usuario", fake_get_firma)
    monkeypatch.setattr(vacaciones_service.db, "insert_firma_solicitud", fake_insert_firma)
    monkeypatch.setattr(vacaciones_service.db, "update_solicitud_estado", fake_update_estado)
    monkeypatch.setattr(
        vacaciones_service, "_recalcular_asistencia_por_solicitud", fake_recalcular_por_solicitud
    )
    monkeypatch.setattr(
        "core.workflow.notification_service.get_notification_service", lambda: _FakeNotif()
    )

    await vacaciones_service.aprobar_solicitud(
        FakeConn(), solicitud_id, aprobador_id, {"user_db_id": str(aprobador_id)}
    )

    assert locks == [usuario_id]


@pytest.mark.asyncio
async def test_aprobar_solicitud_revalida_estado_bajo_el_lock(monkeypatch):
    """Regresion: si la solicitud ya fue resuelta por otra transaccion concurrente
    mientras esta esperaba el lock, debe abortar en vez de sobrescribir el estado
    (la validacion previa al lock quedo obsoleta)."""
    usuario_id = uuid4()
    solicitud_id = uuid4()
    aprobador_id = uuid4()
    fecha = date(2026, 7, 20)
    solicitud_pendiente = _solicitud(
        usuario_id=usuario_id,
        fecha_inicio=fecha,
        fecha_fin=fecha,
        tipo_slug="vacaciones",
        justifica_asistencia_dia=True,
        estado="pendiente",
    )
    solicitud_ya_rechazada = dict(solicitud_pendiente, estado="rechazado")

    llamadas_get = {"n": 0}

    async def fake_lock(_conn, uid):
        return None

    async def fake_puede_aprobar(_conn, _solicitud_id, _aprobador_id, _ctx):
        return True

    async def fake_get_solicitud(_conn, _solicitud_id):
        llamadas_get["n"] += 1
        # Primera lectura (antes del lock): pendiente. Segunda (bajo el lock, tras
        # esperar): ya fue rechazada por otra transaccion concurrente.
        return solicitud_pendiente if llamadas_get["n"] == 1 else solicitud_ya_rechazada

    async def fake_get_firma(_conn, _usuario_id):
        return {"firma_data": b"x"}

    async def fake_update_estado(_conn, _solicitud_id, _estado, **_kwargs):
        raise AssertionError("no debe actualizar el estado si ya fue resuelta")

    monkeypatch.setattr(vacaciones_service.asistencia_db, "lock_he_usuario", fake_lock)
    monkeypatch.setattr(vacaciones_service, "puede_aprobar", fake_puede_aprobar)
    monkeypatch.setattr(vacaciones_service.db, "get_solicitud", fake_get_solicitud)
    monkeypatch.setattr(vacaciones_service.signatures_db, "get_firma_usuario", fake_get_firma)
    monkeypatch.setattr(vacaciones_service.db, "update_solicitud_estado", fake_update_estado)

    with pytest.raises(ValueError, match="ya fue resuelta"):
        await vacaciones_service.aprobar_solicitud(
            FakeConn(), solicitud_id, aprobador_id, {"user_db_id": str(aprobador_id)}
        )


@pytest.mark.asyncio
async def test_cancelar_solicitud_compone_con_revalidar_solicitud_pendiente(monkeypatch):
    """cancelar_solicitud debe reusar _revalidar_solicitud_pendiente (no reimplementar el
    fetch+chequeo de estado inline) y solo agregar el chequeo de ownership encima."""
    usuario_id = uuid4()
    solicitud_id = uuid4()
    fecha = date(2026, 7, 20)
    solicitud = _solicitud(
        usuario_id=usuario_id,
        fecha_inicio=fecha,
        fecha_fin=fecha,
        tipo_slug="vacaciones",
        justifica_asistencia_dia=True,
        estado="pendiente",
    )

    llamadas = {"revalidar": 0}

    async def fake_lock(_conn, uid):
        return None

    async def fake_get_solicitud(_conn, _solicitud_id):
        return solicitud

    async def fake_revalidar(_conn, _solicitud_id):
        llamadas["revalidar"] += 1
        return solicitud

    async def fake_delete_consumos(_conn, _solicitud_id):
        return None

    async def fake_update_estado(_conn, _solicitud_id, _estado, **_kwargs):
        return None

    async def fake_recalcular_por_solicitud(_conn, _solicitud):
        return None

    monkeypatch.setattr(vacaciones_service.asistencia_db, "lock_he_usuario", fake_lock)
    monkeypatch.setattr(vacaciones_service.db, "get_solicitud", fake_get_solicitud)
    monkeypatch.setattr(vacaciones_service, "_revalidar_solicitud_pendiente", fake_revalidar)
    monkeypatch.setattr(vacaciones_service.db, "delete_consumos_solicitud", fake_delete_consumos)
    monkeypatch.setattr(vacaciones_service.db, "update_solicitud_estado", fake_update_estado)
    monkeypatch.setattr(
        vacaciones_service, "_recalcular_asistencia_por_solicitud", fake_recalcular_por_solicitud
    )

    await vacaciones_service.cancelar_solicitud(FakeConn(), solicitud_id, usuario_id)

    assert llamadas["revalidar"] == 1


@pytest.mark.asyncio
async def test_cancelar_solicitud_revalida_ownership_bajo_el_lock(monkeypatch):
    """_revalidar_solicitud_pendiente no chequea ownership -- cancelar_solicitud debe
    seguir aplicando su propio chequeo de ownership sobre el valor revalidado bajo el
    lock, no solo confiar en la comprobacion previa (potencialmente obsoleta) al lock."""
    usuario_id = uuid4()
    solicitud_id = uuid4()
    fecha = date(2026, 7, 20)
    solicitud_propia = _solicitud(
        usuario_id=usuario_id,
        fecha_inicio=fecha,
        fecha_fin=fecha,
        tipo_slug="vacaciones",
        justifica_asistencia_dia=True,
        estado="pendiente",
    )
    # Simula que, bajo el lock, la revalidacion trae una solicitud de otro usuario --
    # aisla especificamente el chequeo de ownership post-lock, sin depender de la
    # comprobacion previa (que ya paso con la solicitud "propia").
    solicitud_ajena = dict(solicitud_propia, usuario_id=uuid4())

    async def fake_lock(_conn, uid):
        return None

    async def fake_get_solicitud(_conn, _solicitud_id):
        return solicitud_propia

    async def fake_revalidar(_conn, _solicitud_id):
        return solicitud_ajena

    async def fake_update_estado(_conn, _solicitud_id, _estado, **_kwargs):
        raise AssertionError("no debe actualizar el estado de una solicitud ajena")

    monkeypatch.setattr(vacaciones_service.asistencia_db, "lock_he_usuario", fake_lock)
    monkeypatch.setattr(vacaciones_service.db, "get_solicitud", fake_get_solicitud)
    monkeypatch.setattr(vacaciones_service, "_revalidar_solicitud_pendiente", fake_revalidar)
    monkeypatch.setattr(vacaciones_service.db, "update_solicitud_estado", fake_update_estado)

    with pytest.raises(ValueError, match="Solo puedes cancelar"):
        await vacaciones_service.cancelar_solicitud(FakeConn(), solicitud_id, usuario_id)
