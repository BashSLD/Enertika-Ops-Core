import pytest

from core.config import settings
from core.redis_client import reset_redis_client
from modules.cfe import launcher_ticket_repository as repository_module
from modules.cfe.launcher_ticket_repository import (
    LauncherReleasePublishLockError,
    LauncherTicketRepository,
    LauncherTicketRepositoryUnavailable,
    launcher_release_publish_lock,
)


@pytest.fixture(autouse=True)
def _memory_backend(monkeypatch):
    monkeypatch.setattr(settings, "REDIS_URL", "")
    monkeypatch.setattr(settings, "DEBUG_MODE", True)
    reset_redis_client()
    LauncherTicketRepository._memory_store.clear()
    yield
    LauncherTicketRepository._memory_store.clear()


@pytest.mark.asyncio
async def test_ticket_and_upload_grant_are_independent_one_time_tokens():
    ticket = await LauncherTicketRepository.create_ticket(
        user_id="user-123",
        user_email="persona@enertika.mx",
    )

    authorization = await LauncherTicketRepository.consume_ticket(ticket)
    assert authorization["user_id"] == "user-123"
    assert authorization["user_email"] == "persona@enertika.mx"
    assert await LauncherTicketRepository.consume_ticket(ticket) is None

    grant = await LauncherTicketRepository.create_upload_grant(authorization)
    assert grant != ticket
    assert await LauncherTicketRepository.consume_upload_grant(grant) == authorization
    assert await LauncherTicketRepository.consume_upload_grant(grant) is None


@pytest.mark.asyncio
async def test_unknown_or_empty_authorizations_are_rejected():
    assert await LauncherTicketRepository.consume_ticket("") is None
    assert await LauncherTicketRepository.consume_ticket("unknown") is None
    assert await LauncherTicketRepository.consume_upload_grant(None) is None


@pytest.mark.asyncio
async def test_expired_memory_authorization_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "CFE_LAUNCHER_TICKET_TTL_SECONDS", -1)
    ticket = await LauncherTicketRepository.create_ticket(
        user_id="user-123",
        user_email="persona@enertika.mx",
    )

    assert await LauncherTicketRepository.consume_ticket(ticket) is None


@pytest.mark.asyncio
async def test_production_requires_redis(monkeypatch):
    monkeypatch.setattr(settings, "DEBUG_MODE", False)

    with pytest.raises(LauncherTicketRepositoryUnavailable):
        await LauncherTicketRepository.create_ticket(
            user_id="user-123",
            user_email="persona@enertika.mx",
        )


@pytest.mark.asyncio
async def test_release_publish_lock_rejects_concurrent_publication(monkeypatch):
    class FakeRedis:
        def __init__(self):
            self.values = {}

        async def set(self, key, value, *, nx, ex):
            assert nx is True
            assert ex == settings.CFE_LAUNCHER_PUBLISH_LOCK_TTL_SECONDS
            if key in self.values:
                return False
            self.values[key] = value
            return True

        async def eval(self, _script, _key_count, key, token, *args):
            if self.values.get(key) == token:
                if args:
                    assert args == (settings.CFE_LAUNCHER_PUBLISH_LOCK_TTL_SECONDS,)
                    return 1
                self.values.pop(key)
                return 1
            return 0

    fake_redis = FakeRedis()
    monkeypatch.setattr(
        repository_module,
        "_shared_get_redis",
        lambda: fake_redis,
    )

    async with launcher_release_publish_lock() as lease:
        await lease.ensure_owned()
        with pytest.raises(LauncherReleasePublishLockError, match="otra publicación"):
            async with launcher_release_publish_lock():
                pass

    async with launcher_release_publish_lock():
        pass
