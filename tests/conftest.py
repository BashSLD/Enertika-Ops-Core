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


@pytest_asyncio.fixture
async def real_conn():
    """Conexion asyncpg real con rollback automatico. Salta el test si no hay BD."""
    load_dotenv(Path(__file__).parents[1] / ".env")
    db_user = os.getenv("DB_USER", "")
    db_password = os.getenv("DB_PASSWORD", "")
    db_host = os.getenv("DB_HOST", "")
    db_port = os.getenv("DB_PORT", "6543")

    if not all([db_user, db_password, db_host]):
        pytest.skip("Variables DB_USER/DB_PASSWORD/DB_HOST no disponibles")

    try:
        conn = await asyncpg.connect(
            f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/postgres",
            statement_cache_size=0,
        )
    except Exception as exc:
        pytest.skip(f"No se pudo conectar a la BD: {exc}")

    tr = conn.transaction()
    await tr.start()
    try:
        yield conn
    finally:
        await tr.rollback()
        await conn.close()


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
