import time
from typing import Any

from core.microsoft import MicrosoftAuth

from . import db_service


def _extract_user_email(claims: dict[str, Any]) -> str:
    user_email = claims.get("preferred_username") or claims.get("email") or claims.get("upn")
    if not user_email:
        raise ValueError("No se pudo obtener el email del usuario.")
    return user_email.lower()


async def process_login_callback(conn, code: str, ms_auth: MicrosoftAuth) -> dict[str, str]:
    token_result = await ms_auth.get_token_from_code(code)
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
    user_email = _extract_user_email(claims)
    user_name = claims.get("name") or "Usuario"

    profile = await ms_auth.get_user_profile(access_token)
    await db_service.upsert_authenticated_user(
        conn,
        name=user_name,
        email=user_email,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
        department=profile.get("department") or None,
        puesto=profile.get("jobTitle") or None,
    )

    return {"email": user_email, "name": user_name}
