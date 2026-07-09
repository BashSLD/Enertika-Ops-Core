"""
Tests unitarios criticos de la bolsa de horas extra y compensatorio
(_Planes_Activos/Planes_Anteriores_Ejecutados/2026-06-29-bolsa-horas-extra.md, seccion 6). Usan mocks/monkeypatch
sobre modules.asistencia.service - no requieren BD real ni la migracion
139 aplicada.
"""

from __future__ import annotations

from datetime import date, datetime, time
from uuid import uuid4

import asyncpg
import pytest

from modules.asistencia import service as asistencia_service
from modules.asistencia.service import (
    _validar_permiso_compensatorio,
    ajuste_manual_svc,
    aprobar_compensatorio_svc,
    aprobar_horas_extra_svc,
    cancelar_compensatorio_svc,
    confirmar_saldo_inicial_svc,
    rechazar_compensatorio_svc,
    revertir_dia_horas_extra_svc,
    solicitar_compensatorio_svc,
    validar_debito_compensatorio,
)
from modules.vacaciones import service as vacaciones_service


class FakeConn:
    def transaction(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _context_row(usuario_id, weekday: int, minutos_programados: int = 480) -> dict:
    return {
        "usuario_id": usuario_id,
        "sucursal_id": None,
        "dia_semana": weekday,
        "horario_id": uuid4(),
        "hora_entrada": time(9, 0),
        "hora_salida": time(18, 0),
        "minutos_programados": minutos_programados,
        "es_laboral": True,
        "cruza_medianoche": False,
        "margen_entrada_antes_min": 0,
        "margen_salida_despues_min": 0,
        "tolerancia_extra_min": 0,
        "descuento_comida_min": 0,
    }


def _mock_lock(monkeypatch) -> None:
    async def fake_lock(_conn, _usuario_id):
        return None

    monkeypatch.setattr(asistencia_service.db, "lock_he_bolsa_usuario", fake_lock)


async def _async_date(value: date) -> date:
    return value


def _he_row(usuario_id, *, minutos_extra=120, minutos_he_compensatorio=0, estado="pendiente") -> dict:
    return {
        "usuario_id": usuario_id,
        "horas_extra_estado": estado,
        "minutos_extra": minutos_extra,
        "minutos_he_compensatorio": minutos_he_compensatorio,
        "empleado_nombre": "Empleado Test",
        "empleado_email": "empleado@test.com",
        "fecha_laboral": date(2026, 7, 1),
    }


# ── validar_debito_compensatorio ──


def test_debito_saldo_exacto_ok():
    validar_debito_compensatorio(120, 120)


def test_debito_saldo_insuficiente():
    with pytest.raises(ValueError, match="insuficiente"):
        validar_debito_compensatorio(60, 120)


def test_debito_minutos_cero_invalido():
    with pytest.raises(ValueError, match="mayores a 0"):
        validar_debito_compensatorio(120, 0)


def test_debito_minutos_negativos_invalido():
    with pytest.raises(ValueError, match="mayores a 0"):
        validar_debito_compensatorio(120, -30)


# ── Auto-aprobacion HE ──


@pytest.mark.asyncio
async def test_aprobar_horas_extra_bloquea_auto_aprobacion(monkeypatch):
    usuario_id = uuid4()
    row = _he_row(usuario_id)

    async def fake_get(_conn, _id):
        return row

    monkeypatch.setattr(asistencia_service.db, "get_asistencia_para_aprobar", fake_get)

    with pytest.raises(ValueError, match="propias horas extra"):
        await aprobar_horas_extra_svc(
            FakeConn(),
            asistencia_id=uuid4(),
            aprobador_id=usuario_id,
            minutos_aprobados=60,
            comentario="ok",
            equipo_ids=[usuario_id],
        )


@pytest.mark.asyncio
async def test_aprobar_horas_extra_exitoso_retorna_email(monkeypatch):
    usuario_id = uuid4()
    row = _he_row(usuario_id)

    async def fake_get(_conn, _id):
        return row

    async def fake_aprobar(_conn, **_kwargs):
        return 1

    monkeypatch.setattr(asistencia_service.db, "get_asistencia_para_aprobar", fake_get)
    monkeypatch.setattr(asistencia_service.db, "aprobar_horas_extra", fake_aprobar)

    result = await aprobar_horas_extra_svc(
        FakeConn(),
        asistencia_id=uuid4(),
        aprobador_id=uuid4(),
        minutos_aprobados=60,
        comentario="Aprobado",
        equipo_ids=[usuario_id],
    )
    assert result["empleado_email"] == "empleado@test.com"


@pytest.mark.asyncio
async def test_aprobar_horas_extra_cero_acreditados_lanza_error(monkeypatch):
    usuario_id = uuid4()
    row = _he_row(usuario_id)

    async def fake_get(_conn, _id):
        return row

    async def fake_aprobar(_conn, **_kwargs):
        return 0

    monkeypatch.setattr(asistencia_service.db, "get_asistencia_para_aprobar", fake_get)
    monkeypatch.setattr(asistencia_service.db, "aprobar_horas_extra", fake_aprobar)

    with pytest.raises(ValueError, match="ya fue procesado"):
        await aprobar_horas_extra_svc(
            FakeConn(),
            asistencia_id=uuid4(),
            aprobador_id=uuid4(),
            minutos_aprobados=60,
            comentario="Aprobado",
            equipo_ids=[usuario_id],
        )


# ── _validar_permiso_compensatorio ──


def test_validar_permiso_compensatorio_bloquea_auto_aprobacion():
    usuario_id = uuid4()
    solicitud = {"usuario_id": usuario_id}
    with pytest.raises(ValueError, match="propia solicitud"):
        _validar_permiso_compensatorio(solicitud, usuario_id, [usuario_id])


def test_validar_permiso_compensatorio_usuario_fuera_de_equipo():
    solicitud = {"usuario_id": uuid4()}
    with pytest.raises(ValueError, match="no encontrada"):
        _validar_permiso_compensatorio(solicitud, uuid4(), [])


# ── aprobar_compensatorio_svc ──


@pytest.mark.asyncio
async def test_aprobar_compensatorio_ya_procesada(monkeypatch):
    usuario_id = uuid4()
    solicitud_id = uuid4()
    solicitud = {
        "id": solicitud_id,
        "usuario_id": usuario_id,
        "estatus": "aprobado",
        "fecha_descanso": date(2026, 8, 1),
        "minutos_solicitados": 60,
    }

    async def fake_get_for_update(_conn, _id, **_kwargs):
        return solicitud

    monkeypatch.setattr(asistencia_service.db, "get_he_compensatorio_by_id", fake_get_for_update)

    with pytest.raises(ValueError, match="ya fue procesada"):
        await aprobar_compensatorio_svc(
            FakeConn(),
            solicitud_id=solicitud_id,
            aprobador_id=uuid4(),
            equipo_ids=[usuario_id],
        )


@pytest.mark.asyncio
async def test_aprobar_compensatorio_bloquea_auto_aprobacion(monkeypatch):
    usuario_id = uuid4()
    solicitud_id = uuid4()
    solicitud = {
        "id": solicitud_id,
        "usuario_id": usuario_id,
        "estatus": "pendiente",
        "fecha_descanso": date(2026, 12, 31),
        "minutos_solicitados": 60,
    }

    async def fake_get_for_update(_conn, _id, **_kwargs):
        return solicitud

    monkeypatch.setattr(asistencia_service.db, "get_he_compensatorio_by_id", fake_get_for_update)

    with pytest.raises(ValueError, match="propia solicitud"):
        await aprobar_compensatorio_svc(
            FakeConn(),
            solicitud_id=solicitud_id,
            aprobador_id=usuario_id,
            equipo_ids=[usuario_id],
        )


@pytest.mark.asyncio
async def test_aprobar_compensatorio_vencida(monkeypatch):
    usuario_id = uuid4()
    solicitud_id = uuid4()
    solicitud = {
        "id": solicitud_id,
        "usuario_id": usuario_id,
        "estatus": "pendiente",
        "fecha_descanso": date(2020, 1, 1),
        "minutos_solicitados": 60,
    }

    async def fake_get_for_update(_conn, _id, **_kwargs):
        return solicitud

    monkeypatch.setattr(asistencia_service.db, "get_he_compensatorio_by_id", fake_get_for_update)

    with pytest.raises(ValueError, match="vencio"):
        await aprobar_compensatorio_svc(
            FakeConn(),
            solicitud_id=solicitud_id,
            aprobador_id=uuid4(),
            equipo_ids=[usuario_id],
        )


@pytest.mark.asyncio
async def test_aprobar_compensatorio_saldo_insuficiente(monkeypatch):
    usuario_id = uuid4()
    solicitud_id = uuid4()
    solicitud = {
        "id": solicitud_id,
        "usuario_id": usuario_id,
        "estatus": "pendiente",
        "fecha_descanso": date(2026, 8, 1),
        "minutos_solicitados": 120,
    }

    monkeypatch.setattr(asistencia_service, "today_mx", lambda: date(2026, 7, 7))

    async def fake_get_for_update(_conn, _id, **_kwargs):
        return solicitud

    async def fake_saldo(_conn, _usuario_id, excluir_solicitud_pendiente_id=None):
        return {"minutos_disponibles": 60}

    async def fake_estado_dia(_conn, _usuario_id, _fecha):
        return "pendiente"

    _mock_lock(monkeypatch)
    monkeypatch.setattr(asistencia_service.db, "get_he_compensatorio_by_id", fake_get_for_update)
    monkeypatch.setattr(asistencia_service.db, "get_he_saldo_usuario", fake_saldo)
    monkeypatch.setattr(asistencia_service.db, "get_horas_extra_estado_en_fecha", fake_estado_dia)

    with pytest.raises(ValueError, match="insuficiente"):
        await aprobar_compensatorio_svc(
            FakeConn(),
            solicitud_id=solicitud_id,
            aprobador_id=uuid4(),
            equipo_ids=[usuario_id],
        )


@pytest.mark.asyncio
async def test_aprobar_compensatorio_exitoso_crea_debito(monkeypatch):
    usuario_id = uuid4()
    aprobador_id = uuid4()
    solicitud_id = uuid4()
    fecha_descanso = date(2026, 8, 1)
    solicitud = {
        "id": solicitud_id,
        "usuario_id": usuario_id,
        "estatus": "pendiente",
        "fecha_descanso": fecha_descanso,
        "minutos_solicitados": 120,
    }
    resultado_final = dict(solicitud, estatus="aprobado")
    calls = {"aprobado": False, "recalculado": None, "notificado": None}

    monkeypatch.setattr(asistencia_service, "today_mx", lambda: date(2026, 7, 7))

    async def fake_get_by_id(_conn, _id, **kwargs):
        return solicitud if kwargs.get("for_update") else resultado_final

    async def fake_saldo(_conn, _usuario_id, excluir_solicitud_pendiente_id=None):
        return {"minutos_disponibles": 120}

    async def fake_aprobar(_conn, *, solicitud_id, aprobador_id, comentario):
        calls["aprobado"] = True
        return resultado_final

    async def fake_recalcular(_conn, targets):
        calls["recalculado"] = targets
        return []

    async def fake_notificar(_conn, _resultado, *, aprobado):
        calls["notificado"] = aprobado

    async def fake_estado_dia(_conn, _usuario_id, _fecha):
        return "pendiente"

    _mock_lock(monkeypatch)
    monkeypatch.setattr(asistencia_service.db, "get_he_compensatorio_by_id", fake_get_by_id)
    monkeypatch.setattr(asistencia_service.db, "get_he_saldo_usuario", fake_saldo)
    monkeypatch.setattr(asistencia_service.db, "get_horas_extra_estado_en_fecha", fake_estado_dia)
    monkeypatch.setattr(asistencia_service.db, "aprobar_he_compensatorio", fake_aprobar)
    monkeypatch.setattr(asistencia_service, "recalcular_asistencia", fake_recalcular)
    monkeypatch.setattr(asistencia_service, "_notificar_compensatorio_resuelto", fake_notificar)

    result = await aprobar_compensatorio_svc(
        FakeConn(),
        solicitud_id=solicitud_id,
        aprobador_id=aprobador_id,
        equipo_ids=[usuario_id],
    )

    assert calls["aprobado"] is True
    assert calls["recalculado"] == [(usuario_id, fecha_descanso)]
    assert calls["notificado"] is True
    assert result["estatus"] == "aprobado"


@pytest.mark.asyncio
@pytest.mark.parametrize("estado_dia", ["solicitado", "aprobado"])
async def test_aprobar_compensatorio_bloquea_colision_con_horas_extra(monkeypatch, estado_dia):
    usuario_id = uuid4()
    solicitud_id = uuid4()
    solicitud = {
        "id": solicitud_id,
        "usuario_id": usuario_id,
        "estatus": "pendiente",
        "fecha_descanso": date(2026, 8, 1),
        "minutos_solicitados": 120,
    }

    monkeypatch.setattr(asistencia_service, "today_mx", lambda: date(2026, 7, 7))

    async def fake_get_for_update(_conn, _id, **_kwargs):
        return solicitud

    async def fake_estado_dia(_conn, _usuario_id, _fecha):
        return estado_dia

    _mock_lock(monkeypatch)
    monkeypatch.setattr(asistencia_service.db, "get_he_compensatorio_by_id", fake_get_for_update)
    monkeypatch.setattr(asistencia_service.db, "get_horas_extra_estado_en_fecha", fake_estado_dia)

    with pytest.raises(ValueError, match="ya tiene horas extra"):
        await aprobar_compensatorio_svc(
            FakeConn(),
            solicitud_id=solicitud_id,
            aprobador_id=uuid4(),
            equipo_ids=[usuario_id],
        )


# ── rechazar_compensatorio_svc ──


@pytest.mark.asyncio
async def test_rechazar_compensatorio_comentario_obligatorio():
    with pytest.raises(ValueError, match="comentario"):
        await rechazar_compensatorio_svc(
            FakeConn(),
            solicitud_id=uuid4(),
            aprobador_id=uuid4(),
            equipo_ids=[],
            comentario="   ",
        )


@pytest.mark.asyncio
async def test_rechazar_compensatorio_ya_procesada(monkeypatch):
    usuario_id = uuid4()
    solicitud_id = uuid4()
    solicitud = {
        "id": solicitud_id,
        "usuario_id": usuario_id,
        "estatus": "rechazado",
        "fecha_descanso": date(2026, 8, 1),
        "minutos_solicitados": 60,
    }

    async def fake_get_for_update(_conn, _id, **_kwargs):
        return solicitud

    monkeypatch.setattr(asistencia_service.db, "get_he_compensatorio_by_id", fake_get_for_update)

    with pytest.raises(ValueError, match="ya fue procesada"):
        await rechazar_compensatorio_svc(
            FakeConn(),
            solicitud_id=solicitud_id,
            aprobador_id=uuid4(),
            equipo_ids=[usuario_id],
            comentario="No aplica",
        )


# ── cancelar_compensatorio_svc ──


@pytest.mark.asyncio
async def test_cancelar_compensatorio_no_propietario_o_no_pendiente(monkeypatch):
    async def fake_cancelar(_conn, **_kwargs):
        return None

    monkeypatch.setattr(asistencia_service.db, "cancelar_he_compensatorio", fake_cancelar)

    with pytest.raises(ValueError, match="pendientes propias"):
        await cancelar_compensatorio_svc(FakeConn(), solicitud_id=uuid4(), usuario_id=uuid4())


@pytest.mark.asyncio
async def test_cancelar_compensatorio_exitoso(monkeypatch):
    resultado = {"id": uuid4(), "estatus": "cancelado"}

    async def fake_cancelar(_conn, **_kwargs):
        return resultado

    monkeypatch.setattr(asistencia_service.db, "cancelar_he_compensatorio", fake_cancelar)

    result = await cancelar_compensatorio_svc(FakeConn(), solicitud_id=uuid4(), usuario_id=uuid4())
    assert result == resultado


# ── _validar_solicitud_horas_extra ──


@pytest.mark.asyncio
async def test_validar_solicitud_horas_extra_bloquea_si_ya_tiene_compensatorio(monkeypatch):
    usuario_id = uuid4()
    row = _he_row(usuario_id, minutos_extra=0, minutos_he_compensatorio=120)

    async def fake_festivos(_conn, _inicio, _fin):
        return set()

    monkeypatch.setattr(asistencia_service.db, "get_festivos_range", fake_festivos)

    with pytest.raises(ValueError, match="ya tiene horas extra"):
        await asistencia_service._validar_solicitud_horas_extra(
            FakeConn(), row, usuario_id, "Proyecto urgente"
        )


@pytest.mark.asyncio
async def test_validar_solicitud_horas_extra_ok_sin_compensatorio(monkeypatch):
    usuario_id = uuid4()
    row = _he_row(usuario_id, minutos_extra=120, minutos_he_compensatorio=0)

    async def fake_festivos(_conn, _inicio, _fin):
        return set()

    monkeypatch.setattr(asistencia_service.db, "get_festivos_range", fake_festivos)

    motivo = await asistencia_service._validar_solicitud_horas_extra(
        FakeConn(), row, usuario_id, "Proyecto urgente"
    )
    assert motivo == "Proyecto urgente"


# ── solicitar_compensatorio_svc ──


@pytest.mark.asyncio
async def test_solicitar_compensatorio_motivo_obligatorio():
    with pytest.raises(ValueError, match="motivo"):
        await solicitar_compensatorio_svc(
            FakeConn(),
            usuario_id=uuid4(),
            fecha_descanso=date(2026, 8, 1),
            minutos_solicitados=60,
            motivo="   ",
        )


@pytest.mark.asyncio
async def test_solicitar_compensatorio_fecha_no_futura(monkeypatch):
    _mock_lock(monkeypatch)
    monkeypatch.setattr(asistencia_service, "today_mx", lambda: date(2026, 7, 7))

    with pytest.raises(ValueError, match="a partir de manana"):
        await solicitar_compensatorio_svc(
            FakeConn(),
            usuario_id=uuid4(),
            fecha_descanso=date(2026, 7, 7),
            minutos_solicitados=60,
            motivo="Descanso",
        )


@pytest.mark.asyncio
async def test_solicitar_compensatorio_fin_de_semana(monkeypatch):
    _mock_lock(monkeypatch)
    monkeypatch.setattr(asistencia_service, "today_mx", lambda: date(2026, 7, 7))

    with pytest.raises(ValueError, match="dia laboral"):
        await solicitar_compensatorio_svc(
            FakeConn(),
            usuario_id=uuid4(),
            fecha_descanso=date(2026, 7, 11),  # sabado
            minutos_solicitados=60,
            motivo="Descanso",
        )


@pytest.mark.asyncio
async def test_solicitar_compensatorio_feriado(monkeypatch):
    fecha = date(2026, 7, 8)  # miercoles
    _mock_lock(monkeypatch)
    monkeypatch.setattr(asistencia_service, "today_mx", lambda: date(2026, 7, 7))

    async def fake_festivos(_conn, _inicio, _fin):
        return {fecha}

    monkeypatch.setattr(asistencia_service.db, "get_festivos_range", fake_festivos)

    with pytest.raises(ValueError, match="feriado"):
        await solicitar_compensatorio_svc(
            FakeConn(),
            usuario_id=uuid4(),
            fecha_descanso=fecha,
            minutos_solicitados=60,
            motivo="Descanso",
        )


@pytest.mark.asyncio
async def test_solicitar_compensatorio_sin_horario(monkeypatch):
    fecha = date(2026, 7, 8)
    _mock_lock(monkeypatch)
    monkeypatch.setattr(asistencia_service, "today_mx", lambda: date(2026, 7, 7))

    async def fake_festivos(_conn, _inicio, _fin):
        return set()

    async def fake_contexts(_conn, _usuario_ids):
        return []

    monkeypatch.setattr(asistencia_service.db, "get_festivos_range", fake_festivos)
    monkeypatch.setattr(asistencia_service.db, "get_attendance_contexts", fake_contexts)

    with pytest.raises(ValueError, match="jornada laboral programada"):
        await solicitar_compensatorio_svc(
            FakeConn(),
            usuario_id=uuid4(),
            fecha_descanso=fecha,
            minutos_solicitados=60,
            motivo="Descanso",
        )


@pytest.mark.asyncio
async def test_solicitar_compensatorio_minutos_fuera_de_rango(monkeypatch):
    usuario_id = uuid4()
    fecha = date(2026, 7, 8)
    _mock_lock(monkeypatch)
    monkeypatch.setattr(asistencia_service, "today_mx", lambda: date(2026, 7, 7))

    async def fake_festivos(_conn, _inicio, _fin):
        return set()

    async def fake_contexts(_conn, _usuario_ids):
        return [_context_row(usuario_id, fecha.weekday(), minutos_programados=480)]

    monkeypatch.setattr(asistencia_service.db, "get_festivos_range", fake_festivos)
    monkeypatch.setattr(asistencia_service.db, "get_attendance_contexts", fake_contexts)

    with pytest.raises(ValueError, match="jornada programada"):
        await solicitar_compensatorio_svc(
            FakeConn(),
            usuario_id=usuario_id,
            fecha_descanso=fecha,
            minutos_solicitados=500,
            motivo="Descanso",
        )


@pytest.mark.asyncio
async def test_solicitar_compensatorio_ausencia_activa_bloquea(monkeypatch):
    usuario_id = uuid4()
    fecha = date(2026, 7, 8)
    _mock_lock(monkeypatch)
    monkeypatch.setattr(asistencia_service, "today_mx", lambda: date(2026, 7, 7))

    async def fake_festivos(_conn, _inicio, _fin):
        return set()

    async def fake_contexts(_conn, _usuario_ids):
        return [_context_row(usuario_id, fecha.weekday())]

    async def fake_ausencias(_conn, _usuario_id, _inicio, _fin, **_kwargs):
        return [{"id": uuid4()}]

    monkeypatch.setattr(asistencia_service.db, "get_festivos_range", fake_festivos)
    monkeypatch.setattr(asistencia_service.db, "get_attendance_contexts", fake_contexts)
    monkeypatch.setattr(
        asistencia_service.vacaciones_db,
        "get_solicitudes_activas_en_rango",
        fake_ausencias,
    )

    with pytest.raises(ValueError, match="ausencia activa"):
        await solicitar_compensatorio_svc(
            FakeConn(),
            usuario_id=usuario_id,
            fecha_descanso=fecha,
            minutos_solicitados=60,
            motivo="Descanso",
        )


@pytest.mark.asyncio
async def test_solicitar_compensatorio_saldo_insuficiente(monkeypatch):
    usuario_id = uuid4()
    fecha = date(2026, 7, 8)
    _mock_lock(monkeypatch)
    monkeypatch.setattr(asistencia_service, "today_mx", lambda: date(2026, 7, 7))

    async def fake_festivos(_conn, _inicio, _fin):
        return set()

    async def fake_contexts(_conn, _usuario_ids):
        return [_context_row(usuario_id, fecha.weekday())]

    async def fake_ausencias(_conn, _usuario_id, _inicio, _fin, **_kwargs):
        return []

    async def fake_saldo(_conn, _usuario_id):
        return {"minutos_disponibles": 30}

    monkeypatch.setattr(asistencia_service.db, "get_festivos_range", fake_festivos)
    monkeypatch.setattr(asistencia_service.db, "get_attendance_contexts", fake_contexts)
    monkeypatch.setattr(
        asistencia_service.vacaciones_db,
        "get_solicitudes_activas_en_rango",
        fake_ausencias,
    )
    monkeypatch.setattr(asistencia_service.db, "get_he_saldo_usuario", fake_saldo)

    with pytest.raises(ValueError, match="insuficiente"):
        await solicitar_compensatorio_svc(
            FakeConn(),
            usuario_id=usuario_id,
            fecha_descanso=fecha,
            minutos_solicitados=60,
            motivo="Descanso",
        )


@pytest.mark.asyncio
async def test_solicitar_compensatorio_duplicada(monkeypatch):
    usuario_id = uuid4()
    fecha = date(2026, 7, 8)
    _mock_lock(monkeypatch)
    monkeypatch.setattr(asistencia_service, "today_mx", lambda: date(2026, 7, 7))

    async def fake_festivos(_conn, _inicio, _fin):
        return set()

    async def fake_contexts(_conn, _usuario_ids):
        return [_context_row(usuario_id, fecha.weekday())]

    async def fake_ausencias(_conn, _usuario_id, _inicio, _fin, **_kwargs):
        return []

    async def fake_saldo(_conn, _usuario_id):
        return {"minutos_disponibles": 480}

    async def fake_crear(_conn, **_kwargs):
        raise asyncpg.UniqueViolationError("duplicate key")

    monkeypatch.setattr(asistencia_service.db, "get_festivos_range", fake_festivos)
    monkeypatch.setattr(asistencia_service.db, "get_attendance_contexts", fake_contexts)
    monkeypatch.setattr(
        asistencia_service.vacaciones_db,
        "get_solicitudes_activas_en_rango",
        fake_ausencias,
    )
    monkeypatch.setattr(asistencia_service.db, "get_he_saldo_usuario", fake_saldo)
    monkeypatch.setattr(asistencia_service.db, "crear_he_solicitud_compensatorio", fake_crear)

    with pytest.raises(ValueError, match="Ya existe una solicitud activa"):
        await solicitar_compensatorio_svc(
            FakeConn(),
            usuario_id=usuario_id,
            fecha_descanso=fecha,
            minutos_solicitados=60,
            motivo="Descanso",
        )


# ── confirmar_saldo_inicial_svc ──


@pytest.mark.asyncio
async def test_confirmar_saldo_inicial_minutos_negativo():
    with pytest.raises(ValueError, match="negativo"):
        await confirmar_saldo_inicial_svc(
            FakeConn(),
            usuario_id=uuid4(),
            minutos=-1,
            confirmado_por=uuid4(),
            context={"role": "USER", "module_roles": {}},
        )


@pytest.mark.asyncio
async def test_confirmar_saldo_inicial_bloquea_no_jefe_no_rrhh(monkeypatch):
    empleado_id = uuid4()

    async def fake_ids_jefe(_conn, _confirmado_por):
        return []

    monkeypatch.setattr(asistencia_service.vacaciones_db, "get_empleados_donde_soy_jefe", fake_ids_jefe)

    with pytest.raises(ValueError, match="jefe directo o RRHH"):
        await confirmar_saldo_inicial_svc(
            FakeConn(),
            usuario_id=empleado_id,
            minutos=0,
            confirmado_por=uuid4(),
            context={"role": "USER", "module_roles": {}},
        )


@pytest.mark.asyncio
async def test_confirmar_saldo_inicial_jefe_directo_ok(monkeypatch):
    empleado_id = uuid4()
    resultado = {"usuario_id": empleado_id, "minutos": 0}

    async def fake_ids_jefe(_conn, _confirmado_por):
        return [empleado_id]

    async def fake_confirmar(_conn, **_kwargs):
        return resultado

    monkeypatch.setattr(asistencia_service.vacaciones_db, "get_empleados_donde_soy_jefe", fake_ids_jefe)
    monkeypatch.setattr(asistencia_service.db, "confirmar_saldo_inicial", fake_confirmar)
    monkeypatch.setattr(asistencia_service, "get_he_bolsa_fecha_corte", lambda _conn: _async_date(date(2026, 7, 7)))

    result = await confirmar_saldo_inicial_svc(
        FakeConn(),
        usuario_id=empleado_id,
        minutos=0,
        confirmado_por=uuid4(),
        context={"role": "USER", "module_roles": {}},
    )
    assert result == resultado


@pytest.mark.asyncio
async def test_confirmar_saldo_inicial_rrhh_editor_backup(monkeypatch):
    empleado_id = uuid4()
    resultado = {"usuario_id": empleado_id, "minutos": 50}

    async def fake_ids_jefe(_conn, _confirmado_por):
        return []

    async def fake_confirmar(_conn, **_kwargs):
        return resultado

    monkeypatch.setattr(asistencia_service.vacaciones_db, "get_empleados_donde_soy_jefe", fake_ids_jefe)
    monkeypatch.setattr(asistencia_service.db, "confirmar_saldo_inicial", fake_confirmar)
    monkeypatch.setattr(asistencia_service, "get_he_bolsa_fecha_corte", lambda _conn: _async_date(date(2026, 7, 7)))

    result = await confirmar_saldo_inicial_svc(
        FakeConn(),
        usuario_id=empleado_id,
        minutos=50,
        confirmado_por=uuid4(),
        context={"role": "MANAGER", "module_roles": {"rrhh": "editor"}},
    )
    assert result == resultado


@pytest.mark.asyncio
async def test_confirmar_saldo_inicial_duplicado(monkeypatch):
    empleado_id = uuid4()

    async def fake_ids_jefe(_conn, _confirmado_por):
        return [empleado_id]

    async def fake_confirmar(_conn, **_kwargs):
        raise asyncpg.UniqueViolationError("duplicate key")

    monkeypatch.setattr(asistencia_service.vacaciones_db, "get_empleados_donde_soy_jefe", fake_ids_jefe)
    monkeypatch.setattr(asistencia_service.db, "confirmar_saldo_inicial", fake_confirmar)
    monkeypatch.setattr(asistencia_service, "get_he_bolsa_fecha_corte", lambda _conn: _async_date(date(2026, 7, 7)))

    with pytest.raises(ValueError, match="ya fue confirmado"):
        await confirmar_saldo_inicial_svc(
            FakeConn(),
            usuario_id=empleado_id,
            minutos=100,
            confirmado_por=uuid4(),
            context={"role": "USER", "module_roles": {}},
        )


# ── ajuste_manual_svc ──


@pytest.mark.asyncio
async def test_ajuste_manual_tipo_invalido():
    with pytest.raises(ValueError, match="invalido"):
        await ajuste_manual_svc(
            FakeConn(), usuario_id=uuid4(), tipo="OTRO", minutos=60, concepto="test", creado_por=uuid4()
        )


@pytest.mark.asyncio
async def test_ajuste_manual_minutos_invalidos():
    with pytest.raises(ValueError, match="mayores a 0"):
        await ajuste_manual_svc(
            FakeConn(), usuario_id=uuid4(), tipo="CREDITO", minutos=0, concepto="test", creado_por=uuid4()
        )


@pytest.mark.asyncio
async def test_ajuste_manual_concepto_obligatorio():
    with pytest.raises(ValueError, match="concepto"):
        await ajuste_manual_svc(
            FakeConn(), usuario_id=uuid4(), tipo="CREDITO", minutos=60, concepto="   ", creado_por=uuid4()
        )


@pytest.mark.asyncio
async def test_ajuste_manual_debito_sin_saldo_suficiente(monkeypatch):
    async def fake_saldo(_conn, _usuario_id):
        return {"minutos_disponibles": 30}

    _mock_lock(monkeypatch)
    monkeypatch.setattr(asistencia_service.db, "get_he_saldo_usuario", fake_saldo)

    with pytest.raises(ValueError, match="insuficiente"):
        await ajuste_manual_svc(
            FakeConn(), usuario_id=uuid4(), tipo="DEBITO", minutos=60, concepto="Correccion", creado_por=uuid4()
        )


@pytest.mark.asyncio
async def test_ajuste_manual_credito_ok(monkeypatch):
    movimiento_id = uuid4()

    async def fake_crear(_conn, **_kwargs):
        return movimiento_id

    _mock_lock(monkeypatch)
    monkeypatch.setattr(asistencia_service.db, "crear_he_ajuste_manual", fake_crear)

    result = await ajuste_manual_svc(
        FakeConn(), usuario_id=uuid4(), tipo="credito", minutos=60, concepto="Bono", creado_por=uuid4()
    )
    assert result == movimiento_id


# ── Conflicto bidireccional: crear_solicitud (vacaciones) vs compensatorio activo ──


@pytest.mark.asyncio
async def test_crear_solicitud_bloquea_compensatorio_activo(monkeypatch):
    usuario_id = uuid4()
    fecha_inicio = date(2026, 7, 13)  # lunes
    fecha_fin = date(2026, 7, 13)
    tipo = {"id": uuid4(), "afecta_saldo": True, "slug": "vacaciones", "nombre": "Vacaciones"}

    async def fake_tipo(_conn, _tipo_id):
        return tipo

    async def fake_festivos_set(_conn):
        return set()

    async def fake_solapadas(_conn, _usuario_id, _inicio, _fin):
        return []

    async def fake_compensatorio_activo(_conn, _usuario_id, _inicio, _fin):
        return [{"id": uuid4(), "fecha_descanso": fecha_inicio, "estatus": "aprobado"}]

    monkeypatch.setattr(vacaciones_service.db, "get_tipo_ausencia_by_id", fake_tipo)
    monkeypatch.setattr(vacaciones_service.db, "get_festivos_set", fake_festivos_set)
    monkeypatch.setattr(vacaciones_service.db, "get_solicitudes_activas_en_rango", fake_solapadas)
    monkeypatch.setattr(
        vacaciones_service.asistencia_db,
        "get_he_compensatorio_activo_en_rango",
        fake_compensatorio_activo,
    )

    with pytest.raises(ValueError, match="tiempo compensatorio"):
        await vacaciones_service.crear_solicitud(
            FakeConn(),
            usuario_id,
            tipo["id"],
            fecha_inicio,
            fecha_fin,
            None,
            "Observaciones",
        )


# ── revertir_dia_horas_extra_svc (correccion manual RH sobre dias congelados) ──


@pytest.mark.asyncio
async def test_revertir_dia_horas_extra_registro_no_encontrado(monkeypatch):
    async def fake_get(_conn, _id):
        return None

    monkeypatch.setattr(asistencia_service.db, "get_asistencia_para_aprobar", fake_get)

    with pytest.raises(ValueError, match="no encontrado"):
        await revertir_dia_horas_extra_svc(
            FakeConn(), asistencia_id=uuid4(), revertido_por=uuid4()
        )


@pytest.mark.asyncio
async def test_revertir_dia_horas_extra_estado_no_corregible(monkeypatch):
    usuario_id = uuid4()
    row = _he_row(usuario_id, estado="pendiente")

    async def fake_get(_conn, _id):
        return row

    monkeypatch.setattr(asistencia_service.db, "get_asistencia_para_aprobar", fake_get)

    with pytest.raises(ValueError, match="feriado.*aprobado"):
        await revertir_dia_horas_extra_svc(
            FakeConn(), asistencia_id=uuid4(), revertido_por=uuid4()
        )


@pytest.mark.asyncio
async def test_revertir_dia_horas_extra_feriado_ok(monkeypatch):
    usuario_id = uuid4()
    row = _he_row(usuario_id, estado="feriado")
    called = {}

    async def fake_get(_conn, _id):
        return row

    async def fake_recuperar_feriado(_conn, asistencia_id):
        called["asistencia_id"] = asistencia_id
        return True

    monkeypatch.setattr(asistencia_service.db, "get_asistencia_para_aprobar", fake_get)
    monkeypatch.setattr(asistencia_service.db, "recuperar_dia_feriado", fake_recuperar_feriado)

    asistencia_id = uuid4()
    result = await revertir_dia_horas_extra_svc(
        FakeConn(), asistencia_id=asistencia_id, revertido_por=uuid4()
    )
    assert called["asistencia_id"] == asistencia_id
    assert result["estado_anterior"] == "feriado"


@pytest.mark.asyncio
async def test_revertir_dia_horas_extra_feriado_ya_no_aplica(monkeypatch):
    usuario_id = uuid4()
    row = _he_row(usuario_id, estado="feriado")

    async def fake_get(_conn, _id):
        return row

    async def fake_recuperar_feriado(_conn, _asistencia_id):
        return False

    monkeypatch.setattr(asistencia_service.db, "get_asistencia_para_aprobar", fake_get)
    monkeypatch.setattr(asistencia_service.db, "recuperar_dia_feriado", fake_recuperar_feriado)

    with pytest.raises(ValueError, match="estado esperado"):
        await revertir_dia_horas_extra_svc(
            FakeConn(), asistencia_id=uuid4(), revertido_por=uuid4()
        )


@pytest.mark.asyncio
async def test_revertir_dia_horas_extra_aprobado_ok(monkeypatch):
    usuario_id = uuid4()
    row = _he_row(usuario_id, estado="aprobado")
    revertido_por = uuid4()
    called = {}

    async def fake_get(_conn, _id):
        return row

    async def fake_revertir_aprobado(_conn, asistencia_id, revertido_por_arg):
        called["asistencia_id"] = asistencia_id
        called["revertido_por"] = revertido_por_arg
        return True

    monkeypatch.setattr(asistencia_service.db, "get_asistencia_para_aprobar", fake_get)
    monkeypatch.setattr(asistencia_service.db, "revertir_horas_extra_aprobado", fake_revertir_aprobado)

    asistencia_id = uuid4()
    result = await revertir_dia_horas_extra_svc(
        FakeConn(), asistencia_id=asistencia_id, revertido_por=revertido_por
    )
    assert called["asistencia_id"] == asistencia_id
    assert called["revertido_por"] == revertido_por
    assert result["estado_anterior"] == "aprobado"


# ── recalcular_asistencia: compensatorio no debe descartar horas reales trabajadas ──


@pytest.mark.asyncio
async def test_recalcular_asistencia_preserva_horas_reales_pese_a_compensatorio(monkeypatch):
    usuario_id = uuid4()
    fecha_laboral = date(2026, 8, 3)
    weekday = fecha_laboral.weekday()
    comp_id = uuid4()
    mx_tz = asistencia_service.MX_TZ

    entrada = datetime.combine(fecha_laboral, time(9, 0), tzinfo=mx_tz)
    salida = datetime.combine(fecha_laboral, time(20, 0), tzinfo=mx_tz)

    async def fake_get_global_config(cls, _conn, _clave, default, tipo=str):
        return default

    async def fake_contexts(_conn, _usuario_ids):
        context = _context_row(usuario_id, weekday)
        context["margen_salida_despues_min"] = 180
        return [context]

    async def fake_ausencias(_conn, **_kwargs):
        return []

    async def fake_festivos(_conn, _inicio, _fin):
        return set()

    async def fake_comp_aprobado(_conn, **_kwargs):
        return [{
            "usuario_id": usuario_id,
            "fecha_descanso": fecha_laboral,
            "id": comp_id,
            "minutos_solicitados": 480,
        }]

    async def fake_checks(_conn, **_kwargs):
        return [
            {"usuario_id": usuario_id, "check_time": entrada, "punch_state": "0"},
            {"usuario_id": usuario_id, "check_time": salida, "punch_state": "1"},
        ]

    saved = {}

    async def fake_upsert(_conn, rows):
        saved["rows"] = rows

    monkeypatch.setattr(
        asistencia_service.ConfigService, "get_global_config", classmethod(fake_get_global_config)
    )
    monkeypatch.setattr(asistencia_service.db, "get_attendance_contexts", fake_contexts)
    monkeypatch.setattr(asistencia_service.db, "get_ausencias_justificadas", fake_ausencias)
    monkeypatch.setattr(asistencia_service.db, "get_festivos_range", fake_festivos)
    monkeypatch.setattr(
        asistencia_service.db, "get_he_compensatorio_aprobado_por_fechas", fake_comp_aprobado
    )
    monkeypatch.setattr(asistencia_service.db, "get_checks_for_users_window", fake_checks)
    monkeypatch.setattr(asistencia_service.db, "upsert_asistencia_diaria_batch", fake_upsert)

    rows = await asistencia_service.recalcular_asistencia(
        FakeConn(), [(usuario_id, fecha_laboral)]
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["minutos_extra"] > 0
    assert row["minutos_he_compensatorio"] == 0
    assert row["he_compensatorio_solicitud_id"] is None
    assert saved["rows"] == rows


@pytest.mark.asyncio
async def test_recalcular_asistencia_aplica_compensatorio_si_no_hay_checadas(monkeypatch):
    usuario_id = uuid4()
    fecha_laboral = date(2026, 8, 3)
    weekday = fecha_laboral.weekday()
    comp_id = uuid4()

    async def fake_get_global_config(cls, _conn, _clave, default, tipo=str):
        return default

    async def fake_contexts(_conn, _usuario_ids):
        return [_context_row(usuario_id, weekday)]

    async def fake_ausencias(_conn, **_kwargs):
        return []

    async def fake_festivos(_conn, _inicio, _fin):
        return set()

    async def fake_comp_aprobado(_conn, **_kwargs):
        return [{
            "usuario_id": usuario_id,
            "fecha_descanso": fecha_laboral,
            "id": comp_id,
            "minutos_solicitados": 480,
        }]

    async def fake_checks(_conn, **_kwargs):
        return []

    saved = {}

    async def fake_upsert(_conn, rows):
        saved["rows"] = rows

    monkeypatch.setattr(
        asistencia_service.ConfigService, "get_global_config", classmethod(fake_get_global_config)
    )
    monkeypatch.setattr(asistencia_service.db, "get_attendance_contexts", fake_contexts)
    monkeypatch.setattr(asistencia_service.db, "get_ausencias_justificadas", fake_ausencias)
    monkeypatch.setattr(asistencia_service.db, "get_festivos_range", fake_festivos)
    monkeypatch.setattr(
        asistencia_service.db, "get_he_compensatorio_aprobado_por_fechas", fake_comp_aprobado
    )
    monkeypatch.setattr(asistencia_service.db, "get_checks_for_users_window", fake_checks)
    monkeypatch.setattr(asistencia_service.db, "upsert_asistencia_diaria_batch", fake_upsert)

    rows = await asistencia_service.recalcular_asistencia(
        FakeConn(), [(usuario_id, fecha_laboral)]
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["minutos_extra"] == 0
    assert row["minutos_he_compensatorio"] == 480
    assert row["he_compensatorio_solicitud_id"] == comp_id
