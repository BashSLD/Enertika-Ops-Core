"""
Tests de las reglas de negocio de los permisos horarios (llegar tarde / salir
temprano) en vacaciones/service.py::crear_solicitud
(_Planes_Activos/PLAN_EQUIPO_FUERA_OFICINA.md, seccion 2). Usan FakeConn/monkeypatch,
sin BD real. Los tipos se modelan como flags de catalogo (requiere_hora_llegada,
requiere_hora_salida, un_solo_dia, combinable_con_tipo_id) en vez de comparar slugs.
"""

from __future__ import annotations

from datetime import date, time
from uuid import uuid4

import pytest

from modules.vacaciones import service as vacaciones_service

ID_LLEGAR_TARDE = uuid4()
ID_SALIR_TEMPRANO = uuid4()


class FakeConn:
    def transaction(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _tipo_llegar_tarde(**overrides) -> dict:
    base = {
        "id": ID_LLEGAR_TARDE,
        "nombre": "permiso_llegar_tarde",
        "slug": "permiso_llegar_tarde",
        "afecta_saldo": False,
        "requiere_aprobacion": True,
        "justifica_asistencia_dia": False,
        "is_active": True,
        "requiere_hora_llegada": True,
        "requiere_hora_salida": False,
        "un_solo_dia": True,
        "combinable_con_tipo_id": ID_SALIR_TEMPRANO,
    }
    base.update(overrides)
    return base


def _tipo_salir_temprano(**overrides) -> dict:
    base = {
        "id": ID_SALIR_TEMPRANO,
        "nombre": "permiso_salir_temprano",
        "slug": "permiso_salir_temprano",
        "afecta_saldo": False,
        "requiere_aprobacion": True,
        "justifica_asistencia_dia": False,
        "is_active": True,
        "requiere_hora_llegada": False,
        "requiere_hora_salida": True,
        "un_solo_dia": True,
        "combinable_con_tipo_id": ID_LLEGAR_TARDE,
    }
    base.update(overrides)
    return base


def _tipo_generico(slug: str, *, is_active: bool = True) -> dict:
    """Tipo sin flags de permiso horario (ej. vacaciones)."""
    return {
        "id": uuid4(),
        "nombre": slug,
        "slug": slug,
        "afecta_saldo": False,
        "requiere_aprobacion": True,
        "justifica_asistencia_dia": False,
        "is_active": is_active,
        "requiere_hora_llegada": False,
        "requiere_hora_salida": False,
        "un_solo_dia": False,
        "combinable_con_tipo_id": None,
    }


def _existente(tipo_ausencia_id, fecha: date, *, hora_llegada=None, hora_salida=None) -> dict:
    return {
        "id": uuid4(),
        "fecha_inicio": fecha,
        "fecha_fin": fecha,
        "tipo_ausencia_id": tipo_ausencia_id,
        "hora_llegada": hora_llegada,
        "hora_salida": hora_salida,
    }


def _wire_common_mocks(
    monkeypatch,
    *,
    tipo: dict,
    festivos: set | None = None,
    solapadas: list[dict] | None = None,
):
    """Mockea todo lo que crear_solicitud toca antes/durante el lock, dejando
    unicamente las reglas de negocio bajo prueba sin mockear."""
    creadas = {}

    async def fake_get_tipo(_conn, _tipo_id):
        return tipo

    async def fake_get_festivos(_conn):
        return festivos or set()

    async def fake_lock(_conn, _usuario_id):
        return None

    async def fake_activas_en_rango(_conn, _usuario_id, _inicio, _fin):
        return solapadas or []

    async def fake_compensatorio_activo(_conn, _usuario_id, _inicio, _fin):
        return []

    async def fake_get_firma(_conn, _usuario_id):
        return {"firma_data": b"x"}

    async def fake_create_solicitud(_conn, *args, **kwargs):
        creadas["args"] = args
        creadas["kwargs"] = kwargs
        return {"id": uuid4(), "usuario_id": args[0] if args else None}

    async def fake_insert_firma(_conn, _solicitud_id, _actor_id, _rol):
        return None

    async def fake_notificar(_conn, _solicitud_id, _solicitud):
        return None

    monkeypatch.setattr(vacaciones_service.db, "get_tipo_ausencia_by_id", fake_get_tipo)
    monkeypatch.setattr(vacaciones_service.db, "get_festivos_set", fake_get_festivos)
    monkeypatch.setattr(vacaciones_service.asistencia_db, "lock_he_usuario", fake_lock)
    monkeypatch.setattr(
        vacaciones_service.db, "get_solicitudes_activas_en_rango", fake_activas_en_rango
    )
    monkeypatch.setattr(
        vacaciones_service.asistencia_db,
        "get_he_compensatorio_activo_en_rango",
        fake_compensatorio_activo,
    )
    monkeypatch.setattr(vacaciones_service.signatures_db, "get_firma_usuario", fake_get_firma)
    monkeypatch.setattr(vacaciones_service.db, "create_solicitud", fake_create_solicitud)
    monkeypatch.setattr(vacaciones_service.db, "insert_firma_solicitud", fake_insert_firma)
    monkeypatch.setattr(vacaciones_service, "_notificar_aprobadores", fake_notificar)
    return creadas


@pytest.mark.asyncio
async def test_llegar_tarde_requiere_hora_llegada(monkeypatch):
    tipo = _tipo_llegar_tarde()
    _wire_common_mocks(monkeypatch, tipo=tipo)
    fecha = date(2026, 7, 20)  # lunes

    with pytest.raises(ValueError, match="hora estimada de llegada"):
        await vacaciones_service.crear_solicitud(
            FakeConn(), uuid4(), tipo["id"], fecha, fecha, None, None,
            hora_llegada=None, hora_salida=None,
        )


@pytest.mark.asyncio
async def test_llegar_tarde_prohibe_hora_salida(monkeypatch):
    tipo = _tipo_llegar_tarde()
    _wire_common_mocks(monkeypatch, tipo=tipo)
    fecha = date(2026, 7, 20)

    with pytest.raises(ValueError, match="no admite hora de salida"):
        await vacaciones_service.crear_solicitud(
            FakeConn(), uuid4(), tipo["id"], fecha, fecha, None, None,
            hora_llegada=time(9, 30), hora_salida=time(14, 0),
        )


@pytest.mark.asyncio
async def test_llegar_tarde_fecha_presentarse_mismo_dia(monkeypatch):
    tipo = _tipo_llegar_tarde()
    creadas = _wire_common_mocks(monkeypatch, tipo=tipo)
    fecha = date(2026, 7, 20)  # lunes

    await vacaciones_service.crear_solicitud(
        FakeConn(), uuid4(), tipo["id"], fecha, fecha, None, None,
        hora_llegada=time(9, 30), hora_salida=None,
    )

    assert creadas["args"][5] == fecha  # fecha_presentarse posicional
    assert creadas["kwargs"]["hora_llegada"] == time(9, 30)
    assert creadas["kwargs"]["hora_salida"] is None


@pytest.mark.asyncio
async def test_salir_temprano_requiere_hora_salida(monkeypatch):
    tipo = _tipo_salir_temprano()
    _wire_common_mocks(monkeypatch, tipo=tipo)
    fecha = date(2026, 7, 20)

    with pytest.raises(ValueError, match="hora de salida"):
        await vacaciones_service.crear_solicitud(
            FakeConn(), uuid4(), tipo["id"], fecha, fecha, None, None,
            hora_llegada=None, hora_salida=None,
        )


@pytest.mark.asyncio
async def test_salir_temprano_prohibe_hora_llegada(monkeypatch):
    tipo = _tipo_salir_temprano()
    _wire_common_mocks(monkeypatch, tipo=tipo)
    fecha = date(2026, 7, 20)

    with pytest.raises(ValueError, match="no admite hora de llegada"):
        await vacaciones_service.crear_solicitud(
            FakeConn(), uuid4(), tipo["id"], fecha, fecha, None, None,
            hora_llegada=time(9, 0), hora_salida=time(14, 0),
        )


@pytest.mark.asyncio
async def test_salir_temprano_regreso_siguiente_dia_habil(monkeypatch):
    tipo = _tipo_salir_temprano()
    creadas = _wire_common_mocks(monkeypatch, tipo=tipo)
    viernes = date(2026, 7, 17)

    await vacaciones_service.crear_solicitud(
        FakeConn(), uuid4(), tipo["id"], viernes, viernes, None, None,
        hora_llegada=None, hora_salida=time(14, 0),
    )

    assert creadas["args"][5] == date(2026, 7, 20)  # lunes siguiente (fin de semana saltado)
    assert creadas["kwargs"]["hora_salida"] == time(14, 0)


@pytest.mark.asyncio
async def test_permiso_horario_rechaza_rango_multi_dia(monkeypatch):
    tipo = _tipo_llegar_tarde()
    _wire_common_mocks(monkeypatch, tipo=tipo)

    with pytest.raises(ValueError, match="un solo día"):
        await vacaciones_service.crear_solicitud(
            FakeConn(), uuid4(), tipo["id"], date(2026, 7, 20), date(2026, 7, 21), None, None,
            hora_llegada=time(9, 0), hora_salida=None,
        )


@pytest.mark.asyncio
async def test_permiso_horario_rechaza_dia_inhabil(monkeypatch):
    tipo = _tipo_llegar_tarde()
    _wire_common_mocks(monkeypatch, tipo=tipo)
    sabado = date(2026, 7, 18)

    with pytest.raises(ValueError, match="no contiene días hábiles"):
        await vacaciones_service.crear_solicitud(
            FakeConn(), uuid4(), tipo["id"], sabado, sabado, None, None,
            hora_llegada=time(9, 0), hora_salida=None,
        )


@pytest.mark.asyncio
async def test_tipo_inactivo_es_rechazado(monkeypatch):
    tipo = _tipo_generico("vacaciones", is_active=False)
    _wire_common_mocks(monkeypatch, tipo=tipo)

    with pytest.raises(ValueError, match="Tipo de ausencia no válido"):
        await vacaciones_service.crear_solicitud(
            FakeConn(), uuid4(), tipo["id"], date(2026, 7, 20), date(2026, 7, 24), None, None,
        )


@pytest.mark.asyncio
async def test_tipo_no_horario_ignora_horas_recibidas(monkeypatch):
    """Defensa en servidor: si llega un POST manipulado con horas para un tipo que no
    es horario, se descartan en vez de persistirse."""
    tipo = _tipo_generico("vacaciones")
    creadas = _wire_common_mocks(monkeypatch, tipo=tipo)

    await vacaciones_service.crear_solicitud(
        FakeConn(), uuid4(), tipo["id"], date(2026, 7, 20), date(2026, 7, 24), None, None,
        hora_llegada=time(9, 0), hora_salida=time(14, 0),
    )

    assert creadas["kwargs"]["hora_llegada"] is None
    assert creadas["kwargs"]["hora_salida"] is None


@pytest.mark.asyncio
async def test_combo_existente_legacy_sin_hora_no_truena(monkeypatch):
    """Solicitud existente creada antes de este feature (tipo correcto, mismo dia,
    pero sin hora_salida) no debe causar TypeError al comparar horas."""
    tipo = _tipo_llegar_tarde()
    fecha = date(2026, 7, 20)
    existente = _existente(ID_SALIR_TEMPRANO, fecha, hora_salida=None)
    _wire_common_mocks(monkeypatch, tipo=tipo, solapadas=[existente])

    with pytest.raises(ValueError, match="Ya existe una solicitud activa"):
        await vacaciones_service.crear_solicitud(
            FakeConn(), uuid4(), tipo["id"], fecha, fecha, None, None,
            hora_llegada=time(9, 30), hora_salida=None,
        )


@pytest.mark.asyncio
async def test_combo_llegar_tarde_salir_temprano_mismo_dia_permitido(monkeypatch):
    tipo = _tipo_llegar_tarde()
    fecha = date(2026, 7, 20)
    existente = _existente(ID_SALIR_TEMPRANO, fecha, hora_salida=time(14, 0))
    creadas = _wire_common_mocks(monkeypatch, tipo=tipo, solapadas=[existente])

    await vacaciones_service.crear_solicitud(
        FakeConn(), uuid4(), tipo["id"], fecha, fecha, None, None,
        hora_llegada=time(9, 30), hora_salida=None,
    )

    assert creadas["kwargs"]["hora_llegada"] == time(9, 30)


@pytest.mark.asyncio
async def test_combo_llegar_tarde_salir_temprano_horas_invalidas(monkeypatch):
    tipo = _tipo_llegar_tarde()
    fecha = date(2026, 7, 20)
    existente = _existente(ID_SALIR_TEMPRANO, fecha, hora_salida=time(9, 0))
    _wire_common_mocks(monkeypatch, tipo=tipo, solapadas=[existente])

    with pytest.raises(ValueError, match="hora de llegada debe ser anterior"):
        await vacaciones_service.crear_solicitud(
            FakeConn(), uuid4(), tipo["id"], fecha, fecha, None, None,
            hora_llegada=time(14, 0), hora_salida=None,
        )


@pytest.mark.asyncio
async def test_combo_mismo_tipo_horario_dos_veces_bloqueado(monkeypatch):
    tipo = _tipo_llegar_tarde()
    fecha = date(2026, 7, 20)
    existente = _existente(ID_LLEGAR_TARDE, fecha, hora_llegada=time(8, 0))
    _wire_common_mocks(monkeypatch, tipo=tipo, solapadas=[existente])

    with pytest.raises(ValueError, match="Ya existe una solicitud activa"):
        await vacaciones_service.crear_solicitud(
            FakeConn(), uuid4(), tipo["id"], fecha, fecha, None, None,
            hora_llegada=time(9, 30), hora_salida=None,
        )


@pytest.mark.asyncio
async def test_traslape_normal_sigue_bloqueado(monkeypatch):
    tipo = _tipo_generico("vacaciones")
    _wire_common_mocks(monkeypatch, tipo=tipo, solapadas=[{"id": uuid4()}])

    with pytest.raises(ValueError, match="Ya existe una solicitud activa"):
        await vacaciones_service.crear_solicitud(
            FakeConn(), uuid4(), tipo["id"], date(2026, 7, 20), date(2026, 7, 24), None, None,
        )
