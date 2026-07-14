"""
Fixtures compartidos para tests de Enertika Ops Core.
Provee mocks para asyncpg connection y user context sin necesitar BD real.
"""
import os
from pathlib import Path

import pytest
import pytest_asyncio
import asyncpg
from dotenv import load_dotenv
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4


def _test_db_dsn() -> str:
    """DSN de la BD de pruebas leido de .env; hace pytest.skip si faltan credenciales."""
    load_dotenv(Path(__file__).parents[1] / ".env")
    db_user = os.getenv("DB_USER", "")
    db_password = os.getenv("DB_PASSWORD", "")
    db_host = os.getenv("DB_HOST", "")
    db_port = os.getenv("DB_PORT", "6543")

    if not all([db_user, db_password, db_host]):
        pytest.skip("Variables DB_USER/DB_PASSWORD/DB_HOST no disponibles")

    return f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/postgres"


@pytest_asyncio.fixture
async def real_conn():
    """Conexion asyncpg real con rollback automatico. Salta el test si no hay BD."""
    dsn = _test_db_dsn()
    try:
        conn = await asyncpg.connect(dsn, statement_cache_size=0)
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"No se pudo conectar a la BD: {exc}")

    tr = conn.transaction()
    await tr.start()
    try:
        yield conn
    finally:
        await tr.rollback()
        await conn.close()


@pytest_asyncio.fixture
async def two_real_conns():
    """Dos conexiones asyncpg reales e independientes, SIN transaccion envolvente.

    A diferencia de real_conn, aqui el test es responsable de su propio commit/
    rollback y de limpiar lo que persista: el escenario que motiva esta fixture
    (reasignacion concurrente de aprobador HE exclusivo mientras otra conexion
    intenta autorizar) requiere que un COMMIT hecho por una conexion sea visible
    para la otra mientras ambas compiten por el mismo advisory lock -- algo que
    una unica conexion con rollback automatico no puede reproducir.
    """
    dsn = _test_db_dsn()
    try:
        conn_a = await asyncpg.connect(dsn, statement_cache_size=0)
        conn_b = await asyncpg.connect(dsn, statement_cache_size=0)
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"No se pudo conectar a la BD: {exc}")

    try:
        yield conn_a, conn_b
    finally:
        await conn_a.close()
        await conn_b.close()


@pytest.fixture
def fake_sharepoint_he_evidencia(monkeypatch):
    """Mockea get_ms_auth/SharePointService de modules.asistencia.service para pruebas de
    evidencia HE (subida/borrado) sin red real. Devuelve un dict de tracking:
    {"token_requested": bool, "subidos": [...], "eliminados": [...]}."""
    from modules.asistencia import service as asistencia_service

    tracking = {"token_requested": False, "subidos": [], "eliminados": []}

    class FakeMsAuth:
        async def get_application_token(self):
            tracking["token_requested"] = True
            return "token-app-123"

    class FakeSharePointService:
        def __init__(self, _token):
            pass

        async def _resolve_config(self, _conn):
            return {"site_id": "site123", "drive_id": "drive123"}

        async def upload_file(self, _conn, file, _folder, _config=None):
            item_id = f"item-{file.filename}"
            tracking["subidos"].append(item_id)
            return {"id": item_id}

        async def delete_file_by_item_id(self, _conn, item_id, _config=None):
            tracking["eliminados"].append(item_id)

    monkeypatch.setattr(asistencia_service, "get_ms_auth", lambda: FakeMsAuth())
    monkeypatch.setattr(asistencia_service, "SharePointService", FakeSharePointService)
    return tracking


@pytest.fixture
def mock_conn():
    """Mock de conexion asyncpg con metodos fetch/execute."""
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetchval = AsyncMock(return_value=None)
    conn.execute = AsyncMock(return_value="UPDATE 1")
    return conn


@pytest.fixture
def admin_context():
    """Contexto de usuario ADMIN global."""
    return {
        "user_db_id": uuid4(),
        "user_name": "Admin Test",
        "email": "admin@test.com",
        "role": "ADMIN",
        "module_roles": {},
    }


@pytest.fixture
def manager_context():
    """Contexto de usuario MANAGER con permisos de editor en comercial."""
    return {
        "user_db_id": uuid4(),
        "user_name": "Manager Test",
        "email": "manager@test.com",
        "role": "MANAGER",
        "module_roles": {"comercial": "editor", "simulacion": "admin"},
    }


@pytest.fixture
def user_context():
    """Contexto de usuario USER con permisos viewer en comercial."""
    return {
        "user_db_id": uuid4(),
        "user_name": "User Test",
        "email": "user@test.com",
        "role": "USER",
        "module_roles": {"comercial": "viewer"},
    }
