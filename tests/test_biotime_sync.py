import asyncio
import sys
import types
from uuid import uuid4

import asyncpg
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

from modules.asistencia import db_service
from modules.asistencia import service as asistencia_service


def test_normalize_biotime_employee_uses_email_and_emp_code():
    employee = asistencia_service._normalize_biotime_employee({
        "id": "42",
        "emp_code": 1007,
        "pin": "PIN-OLD",
        "first_name": "Ana",
        "last_name": "Lopez",
        "email": " ANA.LOPEZ@ENERTIKA.COM ",
        "employee_department": "Operaciones",
        "department_id": 3,
    })

    assert employee == {
        "biotime_emp_id": 42,
        "biotime_emp_code": "1007",
        "biotime_pin": "PIN-OLD",
        "email": "ana.lopez@enertika.com",
        "nombre": "Ana Lopez",
        "biotime_deptnumber": "3",
        "biotime_deptname": "Operaciones",
    }


def test_normalize_biotime_employee_rejects_missing_emp_code():
    assert asistencia_service._normalize_biotime_employee({"email": "a@b.com"}) is None


def test_check_insert_metrics_separates_mapped_and_unmapped():
    rows = [
        {"usuario_id": "11111111-1111-1111-1111-111111111111"},
        {"usuario_id": None},
        {},
    ]

    assert asistencia_service._check_insert_metrics(rows) == {
        "records_inserted_mapped": 1,
        "records_inserted_unmapped": 2,
    }


def test_sync_employee_mappings_fetches_employees_without_transactions(monkeypatch):
    captured = {}

    class FakeClient:
        async def fetch_employees(self):
            return [
                {
                    "id": 7,
                    "emp_code": "E-7",
                    "email": "user@enertika.com",
                }
            ]

    async def fake_upsert(conn, employees):
        captured["employees"] = employees
        return [{"usuario_id": "11111111-1111-1111-1111-111111111111"}]

    monkeypatch.setattr(asistencia_service.db, "upsert_biotime_employee_mappings", fake_upsert)

    result = asyncio.run(
        asistencia_service._sync_employee_mappings_from_biotime(None, FakeClient())
    )

    assert result == {"employees_read": 1, "employee_mappings": 1}
    assert captured["employees"][0]["biotime_emp_code"] == "E-7"
    assert captured["employees"][0]["email"] == "user@enertika.com"


def test_get_employee_map_does_not_fallback_to_employee_number():
    class FakeConn:
        def __init__(self):
            self.query = ""

        async def fetch(self, query, *_):
            self.query = query
            return []

    conn = FakeConn()
    asyncio.run(db_service.get_employee_map(conn, ["E-7"]))

    assert "tb_biotime_empleado_map" in conn.query
    assert "numero_empleado" not in conn.query


@pytest.mark.asyncio
async def test_reap_stale_sync_runs_uses_longer_threshold_for_manual_backfill(real_conn):
    stale_periodic_id = uuid4()
    fresh_backfill_id = uuid4()  # atascado 60min: bajo el umbral largo de backfill
    orphaned_backfill_id = uuid4()  # atascado 400min: huerfano, debe reaperse igual
    fresh_periodic_id = uuid4()

    await real_conn.execute(
        """
        INSERT INTO tb_asistencia_sync_runs
            (id, started_at, status, from_transaction_id, records_read, records_inserted, records_skipped)
        VALUES
            ($1, now() - interval '60 minutes', 'running', 100, 0, 0, 0),
            ($2, now() - interval '60 minutes', 'running', NULL, 0, 0, 0),
            ($3, now() - interval '400 minutes', 'running', NULL, 0, 0, 0),
            ($4, now(), 'running', 100, 0, 0, 0)
        """,
        stale_periodic_id, fresh_backfill_id, orphaned_backfill_id, fresh_periodic_id,
    )

    reaped = await db_service.reap_stale_sync_runs(real_conn, minutos=30, minutos_backfill=360)

    rows = {
        row["id"]: row["status"]
        for row in await real_conn.fetch(
            "SELECT id, status FROM tb_asistencia_sync_runs WHERE id = ANY($1::uuid[])",
            [stale_periodic_id, fresh_backfill_id, orphaned_backfill_id, fresh_periodic_id],
        )
    }
    assert reaped == 2
    assert rows[stale_periodic_id] == "error"
    assert rows[fresh_backfill_id] == "running"
    assert rows[orphaned_backfill_id] == "error"
    assert rows[fresh_periodic_id] == "running"


class _FakeBioTimeClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def fetch_transactions(self, **_kwargs):
        return []


def _patch_common_sync_deps(monkeypatch, *, recalc_days: int = 0):
    run_id = uuid4()

    async def fake_get_global_config(_conn, key, default, _cast):
        if key == asistencia_service.BIOTIME_CONFIG_KEYS["sync_activo"]:
            return True
        if key == asistencia_service.BIOTIME_CONFIG_KEYS["recalc_days"]:
            return recalc_days
        return default

    async def fake_load_config(_conn):
        return {
            "base_url": "http://biotime.local",
            "username": "user",
            "password": "pass",
            "page_size": 200,
            "timeout_seconds": 30,
        }

    async def fake_get_last_transaction_id(_conn):
        return 100

    async def fake_create_sync_run(_conn, **_kwargs):
        return run_id

    async def fake_employee_sync(_conn, _client):
        return {"employees_read": 0, "employee_mappings": 0}

    async def fake_normalize(_conn, items):
        return items

    async def fake_assign_unmapped(_conn):
        return []

    async def fake_unmapped_summary(_conn, **_kwargs):
        return []

    monkeypatch.setattr(asistencia_service.ConfigService, "get_global_config", fake_get_global_config)
    monkeypatch.setattr(asistencia_service, "_load_biotime_client_config", fake_load_config)
    monkeypatch.setattr(asistencia_service.db, "get_last_transaction_id", fake_get_last_transaction_id)
    monkeypatch.setattr(asistencia_service.db, "create_sync_run", fake_create_sync_run)
    monkeypatch.setattr(asistencia_service, "BioTimeClient", lambda *_a, **_k: _FakeBioTimeClient())
    monkeypatch.setattr(asistencia_service, "_sync_employee_mappings_from_biotime", fake_employee_sync)
    monkeypatch.setattr(asistencia_service, "_normalize_transactions", fake_normalize)
    monkeypatch.setattr(asistencia_service.db, "assign_unmapped_checks_from_mappings", fake_assign_unmapped)
    monkeypatch.setattr(asistencia_service.db, "get_unmapped_biotime_checks_summary", fake_unmapped_summary)
    return run_id


def test_sync_biotime_once_marks_run_success(monkeypatch):
    run_id = _patch_common_sync_deps(monkeypatch)
    finish_calls = []

    async def fake_insert_checks_batch(_conn, _normalized):
        return []

    async def fake_finish_sync_run(_conn, **kwargs):
        finish_calls.append(kwargs)

    monkeypatch.setattr(asistencia_service.db, "insert_checks_batch", fake_insert_checks_batch)
    monkeypatch.setattr(asistencia_service.db, "finish_sync_run", fake_finish_sync_run)

    result = asyncio.run(asistencia_service.sync_biotime_once(None, force=True))

    assert result["status"] == "success"
    assert finish_calls == [{
        "run_id": run_id,
        "status": "success",
        "to_transaction_id": 100,
        "records_read": 0,
        "records_inserted": 0,
        "records_skipped": 0,
    }]


def test_sync_biotime_once_marks_run_error_on_postgres_error(monkeypatch):
    run_id = _patch_common_sync_deps(monkeypatch)
    finish_calls = []

    async def fake_insert_checks_batch(_conn, _normalized):
        raise asyncpg.PostgresError("conexion perdida")

    async def fake_finish_sync_run(_conn, **kwargs):
        finish_calls.append(kwargs)

    monkeypatch.setattr(asistencia_service.db, "insert_checks_batch", fake_insert_checks_batch)
    monkeypatch.setattr(asistencia_service.db, "finish_sync_run", fake_finish_sync_run)

    with pytest.raises(asyncpg.PostgresError, match="conexion perdida"):
        asyncio.run(asistencia_service.sync_biotime_once(None, force=True))

    assert finish_calls == [{
        "run_id": run_id,
        "status": "error",
        "records_read": 0,
        "error_message": "conexion perdida",
    }]


def test_sync_biotime_once_propagates_original_error_if_finish_sync_run_also_fails(monkeypatch):
    _patch_common_sync_deps(monkeypatch)
    finish_attempts = []

    async def fake_insert_checks_batch(_conn, _normalized):
        raise asyncpg.PostgresError("conexion perdida")

    async def fake_finish_sync_run_fails(_conn, **kwargs):
        finish_attempts.append(kwargs)
        raise asyncpg.PostgresError("tambien perdida")

    monkeypatch.setattr(asistencia_service.db, "insert_checks_batch", fake_insert_checks_batch)
    monkeypatch.setattr(asistencia_service.db, "finish_sync_run", fake_finish_sync_run_fails)

    with pytest.raises(asyncpg.PostgresError, match="conexion perdida"):
        asyncio.run(asistencia_service.sync_biotime_once(None, force=True))

    assert len(finish_attempts) == 1


def test_sync_biotime_once_marks_run_error_on_timeout_error(monkeypatch):
    run_id = _patch_common_sync_deps(monkeypatch)
    finish_calls = []

    async def fake_insert_checks_batch(_conn, _normalized):
        raise TimeoutError("query excedio el limite")

    async def fake_finish_sync_run(_conn, **kwargs):
        finish_calls.append(kwargs)

    monkeypatch.setattr(asistencia_service.db, "insert_checks_batch", fake_insert_checks_batch)
    monkeypatch.setattr(asistencia_service.db, "finish_sync_run", fake_finish_sync_run)

    with pytest.raises(TimeoutError, match="query excedio el limite"):
        asyncio.run(asistencia_service.sync_biotime_once(None, force=True))

    assert finish_calls == [{
        "run_id": run_id,
        "status": "error",
        "records_read": 0,
        "error_message": "query excedio el limite",
    }]


def test_sync_biotime_once_does_not_overwrite_success_when_unmapped_summary_fails(monkeypatch):
    run_id = _patch_common_sync_deps(monkeypatch)
    finish_calls = []

    async def fake_insert_checks_batch(_conn, _normalized):
        return []

    async def fake_finish_sync_run(_conn, **kwargs):
        finish_calls.append(kwargs)

    async def fake_unmapped_summary_fails(_conn, **_kwargs):
        raise asyncpg.PostgresError("conexion perdida")

    monkeypatch.setattr(asistencia_service.db, "insert_checks_batch", fake_insert_checks_batch)
    monkeypatch.setattr(asistencia_service.db, "finish_sync_run", fake_finish_sync_run)
    monkeypatch.setattr(
        asistencia_service.db, "get_unmapped_biotime_checks_summary", fake_unmapped_summary_fails
    )

    with pytest.raises(asyncpg.PostgresError, match="conexion perdida"):
        asyncio.run(asistencia_service.sync_biotime_once(None, force=True))

    # La consulta informativa fallo ANTES de escribir 'success': el run debe
    # marcarse 'error' una sola vez, nunca 'success' seguido de un overwrite a 'error'.
    assert finish_calls == [{
        "run_id": run_id,
        "status": "error",
        "records_read": 0,
        "error_message": "conexion perdida",
    }]


def test_biotime_client_url_sanitization():
    from modules.asistencia.biotime_client import BioTimeClient

    # Test that spaces inside the base_url are completely removed
    client = BioTimeClient(
        base_url=" http:// 201.158.1.231:8082/ ",
        username="admin",
        password="password",
    )
    assert client.base_url == "http://201.158.1.231:8082"
