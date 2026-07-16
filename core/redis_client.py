"""
Cliente Redis compartido por proceso: infraestructura de autenticación (lock
de renovación de tokens, repositorio de intentos OAuth) y cache de
configuración global (core/config_service.py). Un solo pool de conexiones en
vez de uno independiente por consumidor.
"""
from typing import Optional

import redis.asyncio as aioredis

from core.config import settings

_redis_client: Optional[aioredis.Redis] = None


def get_redis() -> Optional[aioredis.Redis]:
    """Retorna el cliente Redis compartido, o None si no hay REDIS_URL configurado."""
    global _redis_client
    if _redis_client is None and settings.REDIS_URL:
        _redis_client = aioredis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
    return _redis_client


def reset_redis_client() -> None:
    """Solo para tests: fuerza que el siguiente get_redis() re-evalue REDIS_URL."""
    global _redis_client
    _redis_client = None
