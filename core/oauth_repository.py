"""
Repositorio de intentos de login OAuth (correlacion state/nonce).

Cada intento se registra con un "state" opaco antes de redirigir a Microsoft
y se consume atomicamente una sola vez al recibir el callback (GETDEL),
protegiendo contra CSRF, reuso de code y dos intentos simultaneos en la misma
sesion/pestana pisandose sobre `post_login_redirect`.

No almacena tokens ni secretos: solo modo (direct/popup), destino local,
nonce OIDC y el email esperado (reconexion de la misma cuenta).

En produccion (DEBUG_MODE=False) requiere Redis: sin REDIS_URL configurado,
falla explicito en vez de degradar silenciosamente. El fallback en memoria
solo aplica en DEBUG_MODE (desarrollo local, un solo worker).
"""
import json
import logging
import secrets
import time
from typing import Optional, TypedDict

from redis.exceptions import RedisError

from core.config import settings
from core.redis_client import get_redis as _shared_get_redis

logger = logging.getLogger("OAuthRepository")

_REDIS_PREFIX = "eco:oauth:attempt:"


class OAuthAttempt(TypedDict):
    mode: str  # "direct" | "popup"
    next_path: str
    oidc_nonce: str  # validado contra el claim "nonce" del id_token (MSAL)
    client_nonce: Optional[str]  # generado por el opener; se re-emite en el postMessage para que valide la respuesta
    expected_email: Optional[str]
    created_at: float


class OAuthRepositoryUnavailable(RuntimeError):
    """Redis no configurado/alcanzable en un entorno donde el flujo OAuth lo requiere."""


class OAuthAttemptRepository:
    _memory_store: dict[str, tuple[float, OAuthAttempt]] = {}

    @classmethod
    async def create(
        cls,
        mode: str,
        next_path: str,
        expected_email: str | None = None,
        client_nonce: str | None = None,
    ) -> tuple[str, OAuthAttempt]:
        """Registra un intento y retorna (state, attempt) para construir la URL de auth."""
        redis = _shared_get_redis()
        if redis is None and not settings.DEBUG_MODE:
            raise OAuthRepositoryUnavailable(
                "REDIS_URL no configurado: el flujo de login requiere Redis en produccion."
            )

        state = secrets.token_urlsafe(32)
        payload: OAuthAttempt = {
            "mode": mode,
            "next_path": next_path,
            "oidc_nonce": secrets.token_urlsafe(16),
            "client_nonce": client_nonce,
            "expected_email": expected_email,
            "created_at": time.time(),
        }

        if redis is not None:
            try:
                created = await redis.set(
                    f"{_REDIS_PREFIX}{state}",
                    json.dumps(payload),
                    ex=settings.OAUTH_ATTEMPT_TTL_SECONDS,
                    nx=True,
                )
                if not created:
                    # SET NX no escribio: el state (32 bytes aleatorios) ya existia.
                    # Con secrets.token_urlsafe(32) es una colision practicamente
                    # imposible, pero devolver exito aqui dejaria a Redis con el
                    # payload ORIGINAL mientras el llamador sigue con este nuevo
                    # payload -- consume() mas tarde entregaria datos no relacionados.
                    raise OAuthRepositoryUnavailable(
                        "Colision de state generando el intento de login."
                    )
                return state, payload
            except RedisError as e:
                logger.error("Redis no disponible creando intento OAuth: %s", e)
                if not settings.DEBUG_MODE:
                    raise OAuthRepositoryUnavailable("Redis no disponible para el flujo de login.") from e

        # Fallback solo en DEBUG_MODE (desarrollo local, un solo worker).
        # Purga perezosa: sin esto, un login iniciado y nunca completado (popup
        # cerrado por el usuario) queda para siempre en memoria.
        now = time.time()
        expired = [k for k, (expires_at, _) in cls._memory_store.items() if now > expires_at]
        for k in expired:
            cls._memory_store.pop(k, None)

        cls._memory_store[state] = (now + settings.OAUTH_ATTEMPT_TTL_SECONDS, payload)
        return state, payload

    @classmethod
    async def consume(cls, state: str | None) -> Optional[OAuthAttempt]:
        """Consume el intento atomicamente (una sola vez). None si no existe, ya se
        consumio, o expiro."""
        if not state:
            return None

        redis = _shared_get_redis()
        if redis is not None:
            try:
                raw = await redis.getdel(f"{_REDIS_PREFIX}{state}")
                if raw is None:
                    return None
                return json.loads(raw)
            except RedisError as e:
                logger.error("Redis no disponible consumiendo intento OAuth: %s", e)
                return None

        entry = cls._memory_store.pop(state, None)
        if entry is None:
            return None
        expires_at, payload = entry
        if time.time() > expires_at:
            return None
        return payload
