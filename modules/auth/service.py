import time
from typing import Any

from core.microsoft import MicrosoftAuth
from core.security_db_service import get_security_db_service

from . import db_service

security_db = get_security_db_service()


def _extract_user_email(claims: dict[str, Any]) -> str:
    user_email = claims.get("preferred_username") or claims.get("email") or claims.get("upn")
    if not user_email:
        raise ValueError("No se pudo obtener el email del usuario.")
    return user_email.lower()


async def process_login_callback(
    conn, code: str, ms_auth: MicrosoftAuth, expected_nonce: str | None = None
) -> dict[str, Any]:
    token_result = await ms_auth.get_token_from_code(code, nonce=expected_nonce)
    access_token = token_result.get("access_token")
    if not access_token:
        raise ValueError("Microsoft no retorno access_token.")

    refresh_token = token_result.get("refresh_token")
    try:
        expires_in = int(token_result.get("expires_in") or 3600)
    except (TypeError, ValueError) as exc:
        raise ValueError("Tiempo de expiracion invalido.") from exc
    expires_at = int(time.time() + expires_in)

    claims = token_result.get("id_token_claims") or {}
    if expected_nonce and claims and claims.get("nonce") != expected_nonce:
        raise ValueError("El id_token no corresponde a esta solicitud de login (nonce invalido).")

    user_email = _extract_user_email(claims)
    user_name = claims.get("name") or "Usuario"

    profile = await ms_auth.get_user_profile(access_token)
    is_active = await db_service.upsert_authenticated_user(
        conn,
        name=user_name,
        email=user_email,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
        department=profile.get("department") or None,
        puesto=profile.get("jobTitle") or None,
    )

    # Microsoft puede autenticar al usuario sin problema aunque la cuenta este
    # desactivada localmente; upsert_authenticated_user ya retorna el is_active
    # vigente (RETURNING), sin necesidad de una segunda lectura.
    if not is_active:
        raise ValueError("Tu cuenta ha sido desactivada. Contacta al administrador.")

    return {"email": user_email, "name": user_name}


async def check_session_active(conn, user_email: str) -> bool:
    """Confirma que la sesion ligera (cookie) siga respaldada por un usuario
    activo en BD. No valida el token de Graph (ver get_valid_graph_token)."""
    return bool(await security_db.get_user_is_active(conn, user_email))
