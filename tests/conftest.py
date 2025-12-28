import pytest
from fastapi.testclient import TestClient
from main import app
import core.microsoft

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture(autouse=True)
def mock_ms_auth(monkeypatch):
    """
    Simula la clase MicrosoftAuth para evitar llamadas reales a Graph API
    durante los tests.
    """
    class MockMicrosoftAuth:
        _instance = None
        def __new__(cls):
            if cls._instance is None:
                cls._instance = super(MockMicrosoftAuth, cls).__new__(cls)
            return cls._instance

        def get_auth_url(self):
            return "http://localhost/mock-login-url"
            
        def get_token_from_code(self, code):
            return {"access_token": "mock_token_123", "refresh_token": "mock_refresh"}
            
        def get_user_profile(self, token):
            return {
                "displayName": "Usuario Test",
                "mail": "test@enertika.mx",
                "userPrincipalName": "test@enertika.mx"
            }

        def send_email_with_attachments(self, access_token, subject, body, recipients, cc_recipients=None, bcc_recipients=None, attachments_files=None):
            # Simulamos éxito siempre
            print(f"[MOCK] Enviando correo a {recipients} | Subject: {subject}")
            return True, "Correo Simulado Exitoso"

    # Reemplazamos la clase real con el Mock en el módulo core.microsoft
    monkeypatch.setattr(core.microsoft, "MicrosoftAuth", MockMicrosoftAuth)


# ===== FIXTURES PARA TESTS DEL MÓDULO ADMIN =====

@pytest.fixture
def mock_db_conn():
    """Mock de conexión a BD para tests unitarios del módulo admin."""
    class MockDbConnection:
        def __init__(self):
            self._execute_calls = []
            self._fetch_results = []
            self._fetchrow_results = []
            self._fetchval_results = []
            self._fetch_nth_results = {}
            
        async def fetch(self, query, *params):
            self._execute_calls.append(('fetch', query, params))
            # Retornar siguiente resultado si hay múltiples
            if self._fetch_nth_results:
                call_count = len([c for c in self._execute_calls if c[0] == 'fetch'])
                if call_count in self._fetch_nth_results:
                    return self._fetch_nth_results[call_count]
            return self._fetch_results.pop(0) if self._fetch_results else []
            
        async def fetchrow(self, query, *params):
            self._execute_calls.append(('fetchrow', query, params))
            return self._fetchrow_results.pop(0) if self._fetchrow_results else None
            
        async def fetchval(self, query, *params):
            self._execute_calls.append(('fetchval', query, params))
            return self._fetchval_results.pop(0) if self._fetchval_results else None
            
        async def execute(self, query, *params):
            self._execute_calls.append(('execute', query, params))
            return "DONE"
        
        # Helpers para configurar mocks
        def set_fetch_result(self, result):
            self._fetch_results.append(result)
            
        def set_fetch_result_nth(self, nth, result):
            """Para cuando fetch se llama múltiples veces en secuencia."""
            self._fetch_nth_results[nth] = result
            
        def set_fetchrow_result(self, result):
            self._fetchrow_results.append(result)
            
        def set_fetchval_result(self, result):
            self._fetchval_results.append(result)
        
        # Helpers para verificar llamadas
        def execute_called_with_pattern(self, pattern):
            """Verifica si execute fue llamado con un query que contiene el patrón."""
            return any(pattern.lower() in call[1].lower() for call in self._execute_calls if call[0] == 'execute')
        
        def execute_called_with_params(self, *expected_params):
            """Verifica si execute fue llamado con ciertos parámetros."""
            for call in self._execute_calls:
                if call[0] == 'execute' and call[2] == expected_params:
                    return True
            return False
    
    return MockDbConnection()


@pytest.fixture
def client_admin(client, monkeypatch):
    """Cliente autenticado como ADMIN."""
    # Mock de get_current_user_context para retornar admin
    async def mock_admin_context():
        return {
            "user_db_id": "admin-uuid",
            "user_name": "Admin Test",
            "email": "admin@enertika.mx",
            "role": "ADMIN",
            "module_roles": {}
        }
    
    from core import security
    monkeypatch.setattr(security, "get_current_user_context", mock_admin_context)
    return client


@pytest.fixture
def client_user(client, monkeypatch):
    """Cliente autenticado como USER normal."""
    async def mock_user_context():
        return {
            "user_db_id": "user-uuid",
            "user_name": "User Test",
            "email": "user@enertika.mx",
            "role": "USER",
            "module_roles": {"comercial": "viewer"}
        }
    
    from core import security
    monkeypatch.setattr(security, "get_current_user_context", mock_user_context)
    return client
