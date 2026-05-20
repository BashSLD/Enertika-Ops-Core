import asyncio
import sys
import types


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


def test_biotime_client_url_sanitization():
    from modules.asistencia.biotime_client import BioTimeClient

    # Test that spaces inside the base_url are completely removed
    client = BioTimeClient(
        base_url=" http:// 201.158.1.231:8082/ ",
        username="admin",
        password="password",
    )
    assert client.base_url == "http://201.158.1.231:8082"
