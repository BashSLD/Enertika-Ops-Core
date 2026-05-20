import logging

import asyncpg
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse

from core.database import get_db_connection
from core.microsoft import MicrosoftAuth, get_ms_auth

from .service import process_login_callback

logger = logging.getLogger("AuthRouter")

router = APIRouter(
    prefix="/auth",
    tags=["Autenticacion"],
)


@router.get("/login")
async def login(ms_auth: MicrosoftAuth = Depends(get_ms_auth)):
    """Inicia el flujo de autenticacion con Microsoft."""
    auth_url = ms_auth.get_auth_url()
    return RedirectResponse(auth_url)


@router.get("/callback")
async def callback(
    request: Request,
    code: str,
    ms_auth: MicrosoftAuth = Depends(get_ms_auth),
    conn=Depends(get_db_connection),
):
    """Callback tras el login en Microsoft. Guarda sesion ligera."""
    try:
        user = await process_login_callback(conn, code, ms_auth)
        request.session.clear()
        request.session["user_email"] = user["email"]
        request.session["user_name"] = user["name"]
        return RedirectResponse(url="/")
    except ValueError as exc:
        logger.warning("Callback de autenticacion invalido: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except asyncpg.PostgresError as exc:
        logger.exception("Error de base de datos en callback de autenticacion")
        raise HTTPException(status_code=500, detail="Error guardando sesion de usuario") from exc
    except RuntimeError as exc:
        logger.warning("Error de Microsoft en callback de autenticacion: %s", exc)
        raise HTTPException(status_code=502, detail="Error autenticando con Microsoft") from exc


@router.get("/logout")
async def logout(request: Request):
    """Cierra sesion local y remota de Microsoft."""
    request.session.clear()
    base_url = str(request.base_url).rstrip("/")
    post_logout_redirect_uri = f"{base_url}/auth/login"
    ms_logout_url = (
        "https://login.microsoftonline.com/common/oauth2/v2.0/logout"
        f"?post_logout_redirect_uri={post_logout_redirect_uri}"
    )
    return RedirectResponse(url=ms_logout_url)


@router.api_route("/session", methods=["GET", "HEAD"], tags=["Autenticacion"])
async def session_status(request: Request):
    """Verifica si la sesion del usuario sigue activa."""
    user_email = request.session.get("user_email")
    if not user_email:
        return JSONResponse({"active": False}, status_code=401)
    return JSONResponse({"active": True, "email": user_email})
