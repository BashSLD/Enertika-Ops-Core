import pytest

from core.config_service import ConfigService


class _FakeRedis:
    def __init__(self):
        self.deleted: tuple[str, ...] = ()

    async def delete(self, *keys: str) -> None:
        self.deleted = keys


@pytest.mark.asyncio
async def test_invalidar_cache_keys_clears_memory_and_redis(monkeypatch):
    fake_redis = _FakeRedis()
    monkeypatch.setattr(
        ConfigService,
        "_get_redis",
        classmethod(lambda cls: fake_redis),
    )
    monkeypatch.setattr(
        ConfigService,
        "_cache_global",
        {
            "CFG_CFE_LANZADOR_VERSION": (0.0, "anterior"),
            "CFG_OTRA": (0.0, "conservar"),
        },
    )

    await ConfigService.invalidar_cache_keys("CFG_CFE_LANZADOR_VERSION")

    assert "CFG_CFE_LANZADOR_VERSION" not in ConfigService._cache_global
    assert "CFG_OTRA" in ConfigService._cache_global
    assert fake_redis.deleted == (
        "eco:config:CFG_CFE_LANZADOR_VERSION",
    )
