"""
Autorizaciones efimeras para el lanzador local de renovacion CFE.

El navegador autenticado genera un ticket de un solo uso. El lanzador lo
canjea por las credenciales y por una autorizacion distinta, tambien de un
solo uso, que permite subir exclusivamente el nuevo storage_state.

En produccion requiere Redis para compartir estado entre workers y falla
cerrado. El fallback en memoria existe solo para desarrollo local y pruebas.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import time
from contextlib import asynccontextmanager
from typing import TypedDict

from redis.exceptions import RedisError

from core.config import settings
from core.redis_client import get_redis as _shared_get_redis

logger = logging.getLogger("CfeLauncherTicketRepository")

_TICKET_PREFIX = "eco:cfe:launcher:ticket:"
_GRANT_PREFIX = "eco:cfe:launcher:grant:"
_PUBLISH_LOCK_KEY = "eco:cfe:launcher:release:publish"
_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{43}")
_RELEASE_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
end
return 0
"""
_RENEW_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("expire", KEYS[1], ARGV[2])
end
return 0
"""
_memory_publish_lock = asyncio.Lock()


class LauncherAuthorization(TypedDict):
    user_id: str
    user_email: str
    created_at: float


class LauncherTicketRepositoryUnavailable(RuntimeError):
    """Redis no esta disponible para autorizar el lanzador de forma segura."""


class LauncherReleasePublishLockError(ValueError):
    """No fue posible reservar en exclusiva la publicación del lanzador."""


class LauncherReleasePublishLease:
    def __init__(self, redis, token: str) -> None:
        self._redis = redis
        self._token = token
        self._lost = asyncio.Event()

    async def ensure_owned(self) -> None:
        """Renueva y confirma que este proceso todavía posee el lease."""
        if self._redis is None:
            return
        if self._lost.is_set() or not await self._renew():
            self._lost.set()
            raise LauncherReleasePublishLockError(
                "Se perdió la exclusividad de la publicación. Intenta de nuevo."
            )

    async def maintain(self) -> None:
        interval = max(1, settings.CFE_LAUNCHER_PUBLISH_LOCK_TTL_SECONDS // 3)
        while True:
            await asyncio.sleep(interval)
            if not await self._renew():
                self._lost.set()
                return

    async def _renew(self) -> bool:
        try:
            renewed = await self._redis.eval(
                _RENEW_LOCK_SCRIPT,
                1,
                _PUBLISH_LOCK_KEY,
                self._token,
                settings.CFE_LAUNCHER_PUBLISH_LOCK_TTL_SECONDS,
            )
            return bool(renewed)
        except RedisError as exc:
            logger.error("Redis no disponible renovando publicación CFE: %s", exc)
            return False


@asynccontextmanager
async def launcher_release_publish_lock():
    """Serializa publicaciones del lanzador entre workers."""
    redis = _shared_get_redis()
    if redis is None:
        if not settings.DEBUG_MODE:
            raise LauncherReleasePublishLockError(
                "No se puede asegurar la publicación exclusiva porque Redis no está disponible."
            )
        async with _memory_publish_lock:
            yield LauncherReleasePublishLease(None, "")
        return

    lock_token = secrets.token_urlsafe(32)
    try:
        acquired = await redis.set(
            _PUBLISH_LOCK_KEY,
            lock_token,
            nx=True,
            ex=settings.CFE_LAUNCHER_PUBLISH_LOCK_TTL_SECONDS,
        )
    except RedisError as exc:
        logger.error("Redis no disponible reservando publicación CFE: %s", exc)
        raise LauncherReleasePublishLockError(
            "No se puede asegurar la publicación exclusiva porque Redis no está disponible."
        ) from exc
    if not acquired:
        raise LauncherReleasePublishLockError(
            "Ya hay otra publicación del lanzador en curso. Intenta de nuevo en unos minutos."
        )

    lease = LauncherReleasePublishLease(redis, lock_token)
    maintain_task = asyncio.create_task(lease.maintain())
    try:
        yield lease
    finally:
        maintain_task.cancel()
        try:
            await maintain_task
        except asyncio.CancelledError:
            pass
        try:
            await redis.eval(
                _RELEASE_LOCK_SCRIPT,
                1,
                _PUBLISH_LOCK_KEY,
                lock_token,
            )
        except RedisError as exc:
            logger.warning("Redis no disponible liberando publicación CFE: %s", exc)


class LauncherTicketRepository:
    _memory_store: dict[str, tuple[float, LauncherAuthorization]] = {}

    @classmethod
    def _require_backend(cls):
        redis = _shared_get_redis()
        if redis is None and not settings.DEBUG_MODE:
            raise LauncherTicketRepositoryUnavailable(
                "El servicio de autorizacion temporal no esta disponible."
            )
        return redis

    @classmethod
    def _purge_expired_memory(cls) -> None:
        now = time.time()
        expired = [key for key, (expires_at, _) in cls._memory_store.items() if now > expires_at]
        for key in expired:
            cls._memory_store.pop(key, None)

    @classmethod
    async def _create(
        cls,
        *,
        prefix: str,
        ttl_seconds: int,
        authorization: LauncherAuthorization,
    ) -> str:
        redis = cls._require_backend()
        token = secrets.token_urlsafe(32)
        redis_key = f"{prefix}{token}"

        if redis is not None:
            try:
                created = await redis.set(
                    redis_key,
                    json.dumps(authorization),
                    ex=ttl_seconds,
                    nx=True,
                )
            except RedisError as exc:
                logger.error("Redis no disponible creando autorizacion CFE: %s", exc)
                raise LauncherTicketRepositoryUnavailable(
                    "El servicio de autorizacion temporal no esta disponible."
                ) from exc
            if not created:
                raise LauncherTicketRepositoryUnavailable(
                    "No se pudo generar una autorizacion temporal unica."
                )
            return token

        cls._purge_expired_memory()
        cls._memory_store[redis_key] = (time.time() + ttl_seconds, authorization)
        return token

    @classmethod
    async def _consume(
        cls,
        *,
        prefix: str,
        token: str | None,
    ) -> LauncherAuthorization | None:
        if not token or not _TOKEN_RE.fullmatch(token):
            return None

        redis = cls._require_backend()
        redis_key = f"{prefix}{token}"
        if redis is not None:
            try:
                raw = await redis.getdel(redis_key)
            except RedisError as exc:
                logger.error("Redis no disponible consumiendo autorizacion CFE: %s", exc)
                raise LauncherTicketRepositoryUnavailable(
                    "El servicio de autorizacion temporal no esta disponible."
                ) from exc
            if raw is None:
                return None
            try:
                authorization = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                logger.error("Autorizacion CFE corrupta en Redis; se rechazo.")
                return None
            if not isinstance(authorization, dict):
                logger.error("Autorizacion CFE invalida en Redis; se rechazo.")
                return None
            if not authorization.get("user_id") or not authorization.get("user_email"):
                logger.error("Autorizacion CFE incompleta en Redis; se rechazo.")
                return None
            return authorization

        entry = cls._memory_store.pop(redis_key, None)
        if entry is None:
            return None
        expires_at, authorization = entry
        if time.time() > expires_at:
            return None
        return authorization

    @classmethod
    async def create_ticket(cls, *, user_id: str, user_email: str) -> str:
        authorization: LauncherAuthorization = {
            "user_id": user_id,
            "user_email": user_email,
            "created_at": time.time(),
        }
        return await cls._create(
            prefix=_TICKET_PREFIX,
            ttl_seconds=settings.CFE_LAUNCHER_TICKET_TTL_SECONDS,
            authorization=authorization,
        )

    @classmethod
    async def consume_ticket(cls, ticket: str | None) -> LauncherAuthorization | None:
        return await cls._consume(prefix=_TICKET_PREFIX, token=ticket)

    @classmethod
    async def create_upload_grant(cls, authorization: LauncherAuthorization) -> str:
        return await cls._create(
            prefix=_GRANT_PREFIX,
            ttl_seconds=settings.CFE_LAUNCHER_UPLOAD_GRANT_TTL_SECONDS,
            authorization=authorization,
        )

    @classmethod
    async def consume_upload_grant(
        cls,
        grant: str | None,
    ) -> LauncherAuthorization | None:
        return await cls._consume(prefix=_GRANT_PREFIX, token=grant)
