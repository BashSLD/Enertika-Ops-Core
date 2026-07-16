from fastapi import Request, Depends, status
from urllib.parse import unquote, urlsplit
import asyncio
import asyncpg
import secrets
from redis.exceptions import RedisError
from core.database import get_db_connection, get_db_pool
from core.config import settings
from core.microsoft import get_ms_auth  # Para renovación de tokens
from core.redis_client import get_redis as _get_redis
from core.security_db_service import get_security_db_service
import logging
import time

security_db = get_security_db_service()

_REFRESH_LOCK_PREFIX = "eco:token_refresh_lock:"
_REFRESH_WAIT_RETRIES = 6  # ~1.8s de espera acumulada (6 x 300ms) antes de desistir

# Compare-and-delete atomico: evita que un GET+DELETE en dos pasos borre el
# lock de otro worker si el TTL expiro justo entre ambos comandos.
_RELEASE_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
end
return 0
"""


async def _acquire_refresh_lock(user_email: str) -> tuple[str, bool]:
    """Lock por usuario con TTL para serializar la renovacion de refresh token
    entre workers concurrentes. Sin Redis (o si falla), sigue sin bloquear
    (mejor una renovacion ocasional duplicada que bloquear login)."""
    redis = _get_redis()
    if redis is None:
        return "", False
    lock_token = secrets.token_urlsafe(8)
    try:
        acquired = await redis.set(
            f"{_REFRESH_LOCK_PREFIX}{user_email}",
            lock_token,
            nx=True,
            ex=settings.TOKEN_REFRESH_LOCK_TTL_SECONDS,
        )
        return lock_token, bool(acquired)
    except RedisError as e:
        logging.warning("Redis no disponible para lock de refresh token: %s", e)
        return "", False


async def _release_refresh_lock(user_email: str, lock_token: str) -> None:
    """Compare-and-delete: solo libera si seguimos siendo los dueños del lock
    (evita borrar el lock de otro worker si el nuestro ya expiro por TTL).
    Se ejecuta como script Lua atomico en Redis: un GET+DELETE en dos
    comandos separados dejaria una ventana entre ambos donde otro worker
    puede tomar un lock nuevo y que nuestro DELETE tardio se lo borre."""
    redis = _get_redis()
    if redis is None or not lock_token:
        return
    try:
        key = f"{_REFRESH_LOCK_PREFIX}{user_email}"
        await redis.eval(_RELEASE_LOCK_SCRIPT, 1, key, lock_token)
    except RedisError as e:
        logging.warning("Redis no disponible liberando lock de refresh token: %s", e)


async def _wait_for_lock_or_fresher(pool, user_email: str, expires_at: int) -> tuple[str, bool, str | None]:
    """Reintenta adquirir el lock de renovacion (ya tomado por otro worker) con
    reintentos acotados, sin mantener ocupada una conexion del pool mientras
    espera -- cada relectura de BD toma y libera su propia conexion.

    Retorna (lock_token, acquired, fresher_access_token). Si fresher_access_token
    no es None, el llamador debe devolverlo de inmediato sin renovar. Si acquired
    es False al agotar los reintentos, el llamador debe devolver el access_token
    actual (para no arriesgar una renovacion duplicada sin lock: una segunda
    llamada a Microsoft con el mismo refresh_token mientras la primera sigue
    en vuelo puede fallar con invalid_grant si Azure AD lo rota en cada uso).
    """
    lock_token, acquired = "", False
    for _ in range(_REFRESH_WAIT_RETRIES):
        await asyncio.sleep(0.3)
        async with pool.acquire() as conn:
            fresher = await security_db.get_user_tokens(conn, user_email)
        if fresher and (fresher['token_expires_at'] or 0) > expires_at:
            return lock_token, acquired, fresher['access_token']
        lock_token, acquired = await _acquire_refresh_lock(user_email)
        if acquired:
            break
    return lock_token, acquired, None


def safe_redirect_path(path: str | None) -> str:
    """Valida que un destino de redirect post-login sea local y seguro.

    Bloquea protocolo/host externo, protocol-relative ("//host"), backslash
    (los navegadores lo normalizan a "/" y permiten disfrazar "//evil.com" como
    "/\\evil.com"), caracteres de control, y variantes codificadas de lo
    anterior (decodifica una vez antes de validar). Preserva query string.
    """
    if not path:
        return "/"
    try:
        candidate = unquote(path).strip()
    except (ValueError, UnicodeDecodeError):
        return "/"
    if any(ch in candidate for ch in ("\\", "\t", "\n", "\r")):
        return "/"
    if not candidate.startswith("/") or candidate.startswith("//"):
        return "/"
    parsed = urlsplit(candidate)
    if parsed.scheme or parsed.netloc:
        return "/"
    return candidate

async def get_current_user_context(
    request: Request, 
    conn = Depends(get_db_connection)
):
    """
    Dependency to get the current logged-in user context.
    Returns a dict with user_name, email, access_token, department, role, etc.
    """
    # 1. Recuperar sesion (cookie)
    user_email = request.session.get("user_email")
    user_name = request.session.get("user_name", "Usuario")
    
    final_email = user_email

    # 2. Si no hay email en sesión (no logueado), retornamos contexto mínimo
    # para que la UI decida si muestra Login o no.
    if not final_email:
        return {
            "user_name": None,
            "email": None,
            "is_admin": False,
            "role": None,
            "access_token": None,
            "department": None,
            "puesto": None,
            "user_db_id": None
        }

    # 3. Consultar DB para obtener ID interno, ROL, DEPARTAMENTO Y MÓDULO PREFERIDO
    row = await security_db.get_user_by_email(conn, final_email)

    # Usuario desactivado — bloquear acceso sin revelar si la cuenta existe
    if row and not row['is_active']:
        from fastapi import HTTPException, status as http_status
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Tu cuenta ha sido desactivada. Contacta al administrador."
        )

    user_db_id = None
    role = "USER"
    db_dept = None
    db_puesto = None
    db_name = None
    modulo_preferido = None

    if row:
        user_db_id = row['id_usuario']
        role = row['rol_sistema'] or "USER"
        db_dept = row['department']
        db_puesto = row['puesto']
        db_name = row['nombre']
        modulo_preferido = row['modulo_preferido']
    else:
        try:
            user_db_id = await security_db.create_user(conn, user_name, final_email)
        except asyncpg.PostgresError as e:
            logging.error(f"Error auto-creating user {final_email}: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="No se pudo registrar tu usuario. Intenta de nuevo en unos momentos.",
            )

    # Fix User Name priority: DB Name > Session Name > Email fallback
    if db_name:
        user_name = db_name
    elif user_name == "Usuario" and final_email:
        user_name = final_email.split("@")[0] # Fallback to part of email
    
    module_roles = {}
    
    if user_db_id:
        # Consultar módulos asignados desde tb_permisos_modulos
        permisos = await security_db.get_module_permissions(conn, user_db_id)
        
        module_roles = {p['modulo_slug']: p['rol_modulo'] for p in permisos}
        
    db_rol_org = row['rol_organizacional'] if row else None

    return {
        "user_name": user_name,
        "email": final_email,
        "user_email": final_email,  # Alias para compatibilidad con WorkflowService
        "is_admin": (role == 'ADMIN'),
        "role": role,
        "department": db_dept,
        "puesto": db_puesto,
        "modulo_preferido": modulo_preferido,
        "module_roles": module_roles,  # Nueva: Dict {slug: rol}
        "user_db_id": user_db_id,
        "rol_organizacional": db_rol_org,
    }

async def get_valid_graph_token(request: Request):
    """
    Versión Híbrida: Lee tokens desde BD para evitar cookies gigantes.
    Usa asyncio.to_thread para no bloquear el event loop durante llamadas a MSAL.
    """
    # 1. Obtener email de la cookie ligera
    user_email = request.session.get("user_email")
    if not user_email:
        return None

    # 2. Conectar a BD para buscar los tokens reales
    try:
        pool = await get_db_pool()

        # 3. Leer los tokens actuales; se libera la conexion de inmediato --
        # el resto de la logica (espera del lock, llamada a MSAL) no la necesita.
        async with pool.acquire() as conn:
            row = await security_db.get_user_tokens(conn, user_email)

        if not row:
            return None

        access_token = row['access_token']
        refresh_token = row['refresh_token']
        expires_at = row['token_expires_at'] or 0

        # 4. Lógica de Renovación con MSAL
        now = time.time()
        margin = settings.TOKEN_REFRESH_MARGIN_SECONDS

        if now < (expires_at - margin):
            return access_token

        if not refresh_token:
            return None

        lock_token, acquired = await _acquire_refresh_lock(user_email)
        if not acquired and _get_redis() is not None:
            # Redis disponible pero el lock esta tomado: otro worker ya esta
            # renovando este usuario. Esperar en vez de renovar tambien sin
            # lock (ver docstring de _wait_for_lock_or_fresher). Si Redis no
            # esta configurado (_get_redis() is None), _acquire_refresh_lock
            # tampoco pudo tomar el lock por diseño: ahi no hay nada que
            # esperar, se sigue sin bloquear.
            lock_token, acquired, fresher_token = await _wait_for_lock_or_fresher(
                pool, user_email, expires_at
            )
            if fresher_token is not None:
                return fresher_token
            if not acquired:
                return access_token

        try:
            ms_auth = get_ms_auth()
            # ZOMBIE FIX: Ejecutar renovación en thread separado para no bloquear Loop
            new_data = await ms_auth.refresh_access_token(refresh_token)

            if new_data and "access_token" in new_data:
                # Guardar nuevos tokens en BD (conexión nueva y de corta vida)
                new_access = new_data["access_token"]
                new_refresh = new_data.get("refresh_token", refresh_token)
                new_expires = int(time.time() + new_data.get("expires_in", 3600))

                async with pool.acquire() as conn:
                    await security_db.update_user_tokens(
                        conn,
                        user_email,
                        new_access,
                        new_refresh,
                        new_expires,
                    )

                return new_access
            else:
                return None
        finally:
            if acquired:
                await _release_refresh_lock(user_email, lock_token)

    except (asyncpg.PostgresError, RuntimeError, ValueError) as e:
        logging.error(f"Error crítico renovando token en BD: {e}")
        return None
