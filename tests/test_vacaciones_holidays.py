from datetime import date
import sys
import types
from uuid import UUID

import pytest


def _install_redis_stub() -> None:
    redis_module = types.ModuleType("redis")
    redis_asyncio_module = types.ModuleType("redis.asyncio")
    redis_exceptions_module = types.ModuleType("redis.exceptions")

    class _Redis:
        pass

    class _RedisError(Exception):
        pass

    def _from_url(*_args, **_kwargs):
        return None

    redis_asyncio_module.Redis = _Redis
    redis_asyncio_module.from_url = _from_url
    redis_exceptions_module.RedisError = _RedisError
    redis_module.asyncio = redis_asyncio_module
    redis_module.exceptions = redis_exceptions_module
    sys.modules.setdefault("redis", redis_module)
    sys.modules.setdefault("redis.asyncio", redis_asyncio_module)
    sys.modules.setdefault("redis.exceptions", redis_exceptions_module)


_install_redis_stub()

from modules.rrhh import service as rrhh_service
from modules.vacaciones.holidays import generar_feriados_mexico


class _FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeConn:
    def transaction(self):
        return _FakeTransaction()


def test_generar_feriados_mexico_2026_fechas_lft():
    feriados = {item["descripcion"]: item["fecha"] for item in generar_feriados_mexico(2026)}

    assert feriados["Año Nuevo"] == date(2026, 1, 1)
    assert feriados["Día de la Constitución"] == date(2026, 2, 2)
    assert feriados["Natalicio de Benito Juárez"] == date(2026, 3, 16)
    assert feriados["Día del Trabajo"] == date(2026, 5, 1)
    assert feriados["Día de la Independencia"] == date(2026, 9, 16)
    assert feriados["Revolución Mexicana"] == date(2026, 11, 16)
    assert feriados["Navidad"] == date(2026, 12, 25)


def test_generar_feriados_mexico_2030_incluye_transmision_federal():
    feriados = {item["descripcion"]: item["fecha"] for item in generar_feriados_mexico(2030)}

    assert feriados["Transmisión del Poder Ejecutivo Federal"] == date(2030, 10, 1)


@pytest.mark.asyncio
async def test_generar_festivos_anio_marca_validacion_pendiente(monkeypatch):
    llamadas = {}

    async def fake_insert(conn, feriados, created_by=None):
        llamadas["insertados"] = len(feriados)
        llamadas["created_by"] = created_by
        return 7

    async def fake_mark(conn, anio, updated_by=None):
        llamadas["pendiente"] = (anio, updated_by)
        return {"anio": anio, "estado": "pendiente"}

    async def fake_active_users(conn):
        return []

    monkeypatch.setattr(rrhh_service.vac_db, "insert_festivos_generados", fake_insert)
    monkeypatch.setattr(rrhh_service.vac_db, "mark_festivos_validacion_pendiente", fake_mark)
    monkeypatch.setattr(rrhh_service.asistencia_db, "get_active_attendance_users", fake_active_users)

    user_id = UUID("00000000-0000-0000-0000-000000000001")
    insertados = await rrhh_service.generar_festivos_anio(_FakeConn(), 2026, user_id=user_id)

    assert insertados == 7
    assert llamadas["insertados"] == 7
    assert llamadas["created_by"] == user_id
    assert llamadas["pendiente"] == (2026, user_id)


@pytest.mark.asyncio
async def test_guardar_festivo_manual_marca_anio_pendiente(monkeypatch):
    llamadas = {}

    async def fake_create(conn, fecha, descripcion, es_oficial, created_by):
        llamadas["create"] = (fecha, descripcion, es_oficial, created_by)
        return {"id": UUID("00000000-0000-0000-0000-000000000010")}

    async def fake_mark(conn, anio, updated_by=None):
        llamadas.setdefault("pendientes", []).append((anio, updated_by))
        return {"anio": anio, "estado": "pendiente"}

    async def fake_active_users(conn):
        return []

    monkeypatch.setattr(rrhh_service.vac_db, "create_festivo", fake_create)
    monkeypatch.setattr(rrhh_service.vac_db, "mark_festivos_validacion_pendiente", fake_mark)
    monkeypatch.setattr(rrhh_service.asistencia_db, "get_active_attendance_users", fake_active_users)

    user_id = UUID("00000000-0000-0000-0000-000000000002")
    await rrhh_service.guardar_festivo(
        _FakeConn(),
        fecha=date(2026, 7, 3),
        descripcion="Puente interno",
        es_oficial=False,
        user_id=user_id,
    )

    assert llamadas["create"] == (date(2026, 7, 3), "Puente interno", False, user_id)
    assert llamadas["pendientes"] == [(2026, user_id)]


@pytest.mark.asyncio
async def test_guardar_festivo_nuevo_recalcula_asistencia_de_la_fecha(monkeypatch):
    llamadas = {}

    async def fake_create(conn, fecha, descripcion, es_oficial, created_by):
        return {"id": UUID("00000000-0000-0000-0000-000000000010")}

    async def fake_mark(conn, anio, updated_by=None):
        return {"anio": anio, "estado": "pendiente"}

    async def fake_recalcular_activos(conn, fechas):
        llamadas["fechas"] = fechas
        return []

    monkeypatch.setattr(rrhh_service.vac_db, "create_festivo", fake_create)
    monkeypatch.setattr(rrhh_service.vac_db, "mark_festivos_validacion_pendiente", fake_mark)
    monkeypatch.setattr(rrhh_service, "recalcular_asistencia_usuarios_activos", fake_recalcular_activos)

    await rrhh_service.guardar_festivo(
        _FakeConn(),
        fecha=date(2026, 7, 3),
        descripcion="Puente interno",
        es_oficial=False,
        user_id=UUID("00000000-0000-0000-0000-000000000002"),
    )

    assert llamadas["fechas"] == {date(2026, 7, 3)}


@pytest.mark.asyncio
async def test_guardar_festivo_movido_recalcula_origen_y_destino(monkeypatch):
    festivo_id = UUID("00000000-0000-0000-0000-000000000011")
    llamadas = {}

    async def fake_get_by_id(conn, _festivo_id):
        return {"id": festivo_id, "fecha": date(2026, 7, 3)}

    async def fake_update(conn, _festivo_id, fecha, descripcion, es_oficial, updated_by):
        return {"id": festivo_id}

    async def fake_mark(conn, anio, updated_by=None):
        return {"anio": anio, "estado": "pendiente"}

    async def fake_recalcular_activos(conn, fechas):
        llamadas["fechas"] = fechas
        return []

    monkeypatch.setattr(rrhh_service.vac_db, "get_festivo_by_id", fake_get_by_id)
    monkeypatch.setattr(rrhh_service.vac_db, "update_festivo", fake_update)
    monkeypatch.setattr(rrhh_service.vac_db, "mark_festivos_validacion_pendiente", fake_mark)
    monkeypatch.setattr(rrhh_service, "recalcular_asistencia_usuarios_activos", fake_recalcular_activos)

    await rrhh_service.guardar_festivo(
        _FakeConn(),
        fecha=date(2026, 7, 6),
        descripcion="Puente interno movido",
        es_oficial=False,
        user_id=UUID("00000000-0000-0000-0000-000000000002"),
        festivo_id=festivo_id,
    )

    assert llamadas["fechas"] == {date(2026, 7, 3), date(2026, 7, 6)}


@pytest.mark.asyncio
async def test_eliminar_festivo_recalcula_la_fecha_liberada(monkeypatch):
    festivo_id = UUID("00000000-0000-0000-0000-000000000012")
    llamadas = {}

    async def fake_delete(conn, _festivo_id):
        return date(2026, 7, 3)

    async def fake_mark(conn, anio, updated_by=None):
        return {"anio": anio, "estado": "pendiente"}

    async def fake_recalcular_activos(conn, fechas):
        llamadas["fechas"] = fechas
        return []

    monkeypatch.setattr(rrhh_service.vac_db, "delete_festivo", fake_delete)
    monkeypatch.setattr(rrhh_service.vac_db, "mark_festivos_validacion_pendiente", fake_mark)
    monkeypatch.setattr(rrhh_service, "recalcular_asistencia_usuarios_activos", fake_recalcular_activos)

    await rrhh_service.eliminar_festivo(
        _FakeConn(), festivo_id, 2026, UUID("00000000-0000-0000-0000-000000000002")
    )

    assert llamadas["fechas"] == {date(2026, 7, 3)}


@pytest.mark.asyncio
async def test_validar_festivos_anio_guarda_usuario_y_notas(monkeypatch):
    llamadas = {}

    async def fake_validar(conn, anio, notas, user_id):
        llamadas["validar"] = (anio, notas, user_id)
        return {"anio": anio, "estado": "validado"}

    monkeypatch.setattr(rrhh_service.vac_db, "validar_festivos_anio", fake_validar)

    user_id = UUID("00000000-0000-0000-0000-000000000003")
    await rrhh_service.validar_festivos_anio(
        _FakeConn(), 2026, " Revisado por RH ", user_id
    )

    assert llamadas["validar"] == (2026, "Revisado por RH", user_id)
