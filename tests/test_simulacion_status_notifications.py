from datetime import datetime, timedelta
import sys
import types
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException


redis_module = types.ModuleType("redis")
redis_asyncio_module = types.ModuleType("redis.asyncio")
redis_exceptions_module = types.ModuleType("redis.exceptions")


class RedisError(Exception):
    pass


class Redis:
    pass


redis_asyncio_module.Redis = Redis
redis_asyncio_module.from_url = lambda *args, **kwargs: None
redis_exceptions_module.RedisError = RedisError
redis_module.asyncio = redis_asyncio_module
redis_module.exceptions = redis_exceptions_module

sys.modules.setdefault("redis", redis_module)
sys.modules.setdefault("redis.asyncio", redis_asyncio_module)
sys.modules.setdefault("redis.exceptions", redis_exceptions_module)

from modules.simulacion.service import SimulacionService


MX = ZoneInfo("America/Mexico_City")


def async_now(value):
    async def _now(conn):
        return value

    return _now


def async_fecha_sla(value):
    async def _fecha_sla(conn, fecha_real):
        return value

    return _fecha_sla


class FakeConn:
    def __init__(self, status_rows=None, current_history=None, previous_history=None):
        self.status_rows = status_rows or []
        self.current_history = current_history
        self.previous_history = previous_history
        self.fetch_called = False
        self.fetchrow_calls = []

    async def fetch(self, query, *args):
        self.fetch_called = True
        return self.status_rows

    async def fetchrow(self, query, *args):
        self.fetchrow_calls.append((query, args))
        if "id_estatus_nuevo = $2" in query:
            return self.current_history
        return self.previous_history


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeHistoryConn(FakeConn):
    def transaction(self):
        return FakeTransaction()


class FakeSimulacionDB:
    def __init__(self, statuses, timeline=None, current_data=None, last_change=None):
        self.statuses = statuses
        self.timeline = timeline or []
        self.current_data = current_data
        self.last_change = last_change
        self.inserted = None
        self.reverted_to = None

    async def get_estatus_oportunidades_activos(self, conn):
        return self.statuses

    async def get_historial_estatus_timeline(self, conn, id_oportunidad):
        return self.timeline

    async def insert_historial_estatus(
        self,
        conn,
        id_oportunidad,
        id_estatus_anterior,
        id_estatus_nuevo,
        fecha_cambio_real,
        fecha_cambio_sla,
        cambiado_por_id,
        notas=None,
    ):
        self.inserted = {
            "id_oportunidad": id_oportunidad,
            "id_estatus_anterior": id_estatus_anterior,
            "id_estatus_nuevo": id_estatus_nuevo,
            "fecha_cambio_real": fecha_cambio_real,
            "fecha_cambio_sla": fecha_cambio_sla,
            "cambiado_por_id": cambiado_por_id,
            "notas": notas,
        }
        return self.inserted

    async def get_oportunidad_for_update(self, conn, id_oportunidad):
        return self.current_data

    async def lock_oportunidad_for_update(self, conn, id_oportunidad):
        if self.current_data is None:
            return None
        return {"id_oportunidad": id_oportunidad, "id_estatus_global": self.current_data["id_estatus_global"]}

    async def get_ultima_fecha_cambio_real(self, conn, id_oportunidad):
        return self.last_change

    async def revertir_oportunidad_a_estatus(self, conn, id_oportunidad, id_estatus_destino):
        self.reverted_to = id_estatus_destino


async def fake_get_global_config(conn, clave, default, tipo=str):
    values = {
        "ESTATUS_HITO_CORREO": "Entregado",
        "UMBRAL_LAG_NOTIFICACION": 60,
        "VENTANA_BLOQUE_REGISTRO_MIN": 2,
    }
    return values.get(clave, default)


def status_row(id_estatus, nombre, es_final):
    return {
        "id": id_estatus,
        "nombre": nombre,
        "es_estatus_final": es_final,
    }


def catalog_row(id_estatus, nombre, orden, es_final):
    row = status_row(id_estatus, nombre, es_final)
    row["orden"] = orden
    return row


def history_event(id_estatus, fecha):
    return {
        "id_estatus_nuevo": id_estatus,
        "fecha_cambio_real": fecha,
    }


def simulacion_catalog():
    return [
        catalog_row(1, "Pendiente", 1, False),
        catalog_row(2, "En Proceso", 2, False),
        catalog_row(3, "En Revisión", 3, False),
        catalog_row(15, "Comentarios Recibidos", 4, False),
        catalog_row(5, "Entregado", 5, True),
    ]


@pytest.mark.asyncio
async def test_status_notification_respects_notify_false(monkeypatch):
    monkeypatch.setattr(
        "modules.simulacion.service.ConfigService.get_global_config",
        fake_get_global_config,
    )
    service = SimulacionService()
    conn = FakeConn()

    should_notify = await service._should_notify_status_change(
        conn,
        uuid4(),
        old_status_id=1,
        new_status_id=5,
        datos=SimpleNamespace(fecha_cambio_real=None),
        notify_status=False,
    )

    assert should_notify is False


@pytest.mark.asyncio
async def test_insertar_transicion_historica_inserta_entre_vecinos(monkeypatch):
    monkeypatch.setattr(
        "modules.simulacion.service.ConfigService.get_global_config",
        fake_get_global_config,
    )
    service = SimulacionService()
    service.get_current_datetime_mx = async_now(datetime(2026, 1, 2, 9, 0, tzinfo=MX))
    service._calculate_fecha_sla = async_fecha_sla(datetime(2026, 1, 1, 11, 0, tzinfo=MX))
    service.db = FakeSimulacionDB(
        simulacion_catalog(),
        timeline=[
            history_event(3, datetime(2026, 1, 1, 10, 0, tzinfo=MX)),
            history_event(5, datetime(2026, 1, 1, 12, 0, tzinfo=MX)),
        ],
        current_data={"id_estatus_global": 3},
    )
    user_id = uuid4()

    await service.insertar_transicion_historica(
        FakeHistoryConn(),
        uuid4(),
        15,
        datetime(2026, 1, 1, 11, 0, tzinfo=MX),
        {"user_db_id": user_id},
    )

    assert service.db.inserted["id_estatus_anterior"] == 3
    assert service.db.inserted["id_estatus_nuevo"] == 15
    assert service.db.inserted["cambiado_por_id"] == user_id
    assert service.db.inserted["notas"] == "Reconstrucción manual (correo)"


@pytest.mark.asyncio
async def test_insertar_transicion_historica_rechaza_fuera_de_vecinos(monkeypatch):
    monkeypatch.setattr(
        "modules.simulacion.service.ConfigService.get_global_config",
        fake_get_global_config,
    )
    service = SimulacionService()
    service.get_current_datetime_mx = async_now(datetime(2026, 1, 2, 9, 0, tzinfo=MX))
    service.db = FakeSimulacionDB(
        simulacion_catalog(),
        timeline=[
            history_event(3, datetime(2026, 1, 1, 10, 0, tzinfo=MX)),
            history_event(5, datetime(2026, 1, 1, 12, 0, tzinfo=MX)),
        ],
        current_data={"id_estatus_global": 3},
    )

    with pytest.raises(HTTPException) as exc:
        await service.insertar_transicion_historica(
            FakeHistoryConn(),
            uuid4(),
            15,
            datetime(2026, 1, 1, 13, 0, tzinfo=MX),
            {"user_db_id": uuid4()},
        )

    assert getattr(exc.value, "status_code", None) == 400


@pytest.mark.asyncio
async def test_revertir_cierre_admin_registra_auditoria(monkeypatch):
    monkeypatch.setattr(
        "modules.simulacion.service.ConfigService.get_global_config",
        fake_get_global_config,
    )
    service = SimulacionService()
    now = datetime(2026, 1, 2, 9, 0, tzinfo=MX)
    service.get_current_datetime_mx = async_now(now)
    service._calculate_fecha_sla = async_fecha_sla(now)
    service.db = FakeSimulacionDB(
        simulacion_catalog(),
        current_data={"id_estatus_global": 5},
        last_change=now - timedelta(minutes=10),
    )
    user_id = uuid4()

    await service.revertir_cierre_admin(
        FakeHistoryConn(),
        uuid4(),
        15,
        {"role": "ADMIN", "user_db_id": user_id},
    )

    assert service.db.reverted_to == 15
    assert service.db.inserted["id_estatus_anterior"] == 5
    assert service.db.inserted["id_estatus_nuevo"] == 15
    assert service.db.inserted["notas"] == "Reversión de cierre (Admin)"


@pytest.mark.asyncio
async def test_revertir_cierre_admin_rechaza_no_admin():
    service = SimulacionService()

    with pytest.raises(HTTPException) as exc:
        await service.revertir_cierre_admin(
            FakeHistoryConn(),
            uuid4(),
            15,
            {"role": "MANAGER", "user_db_id": uuid4()},
        )

    assert getattr(exc.value, "status_code", None) == 403


@pytest.mark.asyncio
async def test_status_notification_uses_history_creation_for_retroactive_lag(monkeypatch):
    monkeypatch.setattr(
        "modules.simulacion.service.ConfigService.get_global_config",
        fake_get_global_config,
    )

    service = SimulacionService()
    service.get_current_datetime_mx = async_now(datetime(2026, 1, 10, 9, 0, tzinfo=MX))
    current_history = {
        "fecha_creacion": datetime(2026, 1, 2, 9, 30, tzinfo=MX),
        "fecha_cambio_real": datetime(2026, 1, 2, 9, 0, tzinfo=MX),
    }
    conn = FakeConn(
        status_rows=[status_row(5, "Entregado", True)],
        current_history=current_history,
    )

    should_notify = await service._should_notify_status_change(
        conn,
        uuid4(),
        old_status_id=4,
        new_status_id=5,
        datos=SimpleNamespace(fecha_cambio_real=datetime(2026, 1, 2, 9, 0, tzinfo=MX)),
    )

    assert should_notify is True


@pytest.mark.asyncio
async def test_status_notification_ignores_non_hito_status(monkeypatch):
    monkeypatch.setattr(
        "modules.simulacion.service.ConfigService.get_global_config",
        fake_get_global_config,
    )

    service = SimulacionService()
    conn = FakeConn(status_rows=[status_row(2, "En Proceso", False)])

    should_notify = await service._should_notify_status_change(
        conn,
        uuid4(),
        old_status_id=1,
        new_status_id=2,
        datos=SimpleNamespace(fecha_cambio_real=None),
    )

    assert should_notify is False
    assert conn.fetchrow_calls == []


@pytest.mark.asyncio
async def test_status_notification_allows_final_hito_after_quick_previous_registration(monkeypatch):
    monkeypatch.setattr(
        "modules.simulacion.service.ConfigService.get_global_config",
        fake_get_global_config,
    )

    service = SimulacionService()
    current_created = datetime(2026, 1, 2, 10, 0, tzinfo=MX)
    service.get_current_datetime_mx = async_now(current_created)
    conn = FakeConn(
        status_rows=[status_row(5, "Entregado", True)],
        current_history={
            "fecha_creacion": current_created,
            "fecha_cambio_real": current_created,
        },
        previous_history={
            "fecha_creacion": current_created - timedelta(seconds=30),
        },
    )

    should_notify = await service._should_notify_status_change(
        conn,
        uuid4(),
        old_status_id=15,
        new_status_id=5,
        datos=SimpleNamespace(fecha_cambio_real=current_created),
    )

    assert should_notify is True


@pytest.mark.asyncio
async def test_status_notification_blocks_non_terminal_batch(monkeypatch):
    async def config_for_non_terminal(conn, clave, default, tipo=str):
        if clave == "ESTATUS_HITO_CORREO":
            return "En Proceso"
        return await fake_get_global_config(conn, clave, default, tipo)

    monkeypatch.setattr(
        "modules.simulacion.service.ConfigService.get_global_config",
        config_for_non_terminal,
    )

    service = SimulacionService()
    service.get_current_datetime_mx = async_now(datetime(2026, 1, 2, 10, 0, tzinfo=MX))
    current_created = datetime(2026, 1, 2, 10, 0, tzinfo=MX)
    conn = FakeConn(
        status_rows=[status_row(2, "En Proceso", False)],
        current_history={
            "fecha_creacion": current_created,
            "fecha_cambio_real": current_created,
        },
        previous_history={
            "fecha_creacion": current_created - timedelta(seconds=30),
        },
    )

    should_notify = await service._should_notify_status_change(
        conn,
        uuid4(),
        old_status_id=1,
        new_status_id=2,
        datos=SimpleNamespace(fecha_cambio_real=current_created),
    )

    assert should_notify is False
