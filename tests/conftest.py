"""
Fixtures compartidos para tests de Enertika Ops Core.
Provee mocks para asyncpg connection y user context sin necesitar BD real.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4


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
