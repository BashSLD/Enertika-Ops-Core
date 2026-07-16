import logging

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates

from core.database import get_db_connection
from core.microsoft import MicrosoftAuth, get_ms_auth
from core.oauth_repository import OAuthAttempt, OAuthAttemptRepository, OAuthRepositoryUnavailable
from core.security import safe_redirect_path

from .service import check_session_active, process_login_callback

logger = logging.getLogger("AuthRouter")
_templates = Jinja2Templates(directory="templates")

router = APIRouter(
    prefix="/auth",
    tags=["Autenticacion"],
)

_NO_STORE_HEADERS = {"Cache-Control": "no-store"}
_POPUP_HINT_COOKIE = "oauth_popup_hint"


def _popup_response(request: Request, status: str, attempt: OAuthAttempt | None, message: str | None = None, email: str | None = None) -> Response:
    payload = {
        "source": "enertika-oauth",
        "status": status,  # "success" | "cancelled" | "error" | "timeout"
        "message": message,
        "email": email,
        "expected_email": attempt.get("expected_email") if attempt else None,
        "nonce": attempt.get("client_nonce") if attempt else None,
    }
    return _templates.TemplateResponse(
        request, "auth/popup_result.html", {"payload": payload},
        headers=_NO_STORE_HEADERS,
    )


def _terminal_response(
    request: Request, attempt: OAuthAttempt | None, status: str, message: str, mode: str | None = None
) -> Response:
    """Respuesta final ante cancelacion/error: nunca 422, nunca reintenta sola.

    `mode` permite al llamador forzar el modo cuando `attempt` es None (state
    invalido/expirado/ya consumido) y por lo tanto no hay de donde leerlo -- ver
    `_POPUP_HINT_COOKIE` en /callback."""
    if mode is None:
        mode = attempt.get("mode") if attempt else "direct"
    if mode == "popup":
        return _popup_response(request, status, attempt, message=message)
    logger.info("Login (modo directo) termino en '%s': %s", status, message)
    return RedirectResponse(url="/auth/login", status_code=302, headers=_NO_STORE_HEADERS)


def _clear_popup_hint(response: Response) -> Response:
    response.delete_cookie(_POPUP_HINT_COOKIE)
    return response


@router.get("/login")
async def login(
    request: Request,
    next_url: str | None = Query(None, alias="next"),
    popup: bool = Query(False),
    email_hint: str | None = Query(None),
    client_nonce: str | None = Query(None),
    ms_auth: MicrosoftAuth = Depends(get_ms_auth),
):
    """Inicia el flujo de autenticacion con Microsoft.

    popup=1 marca el intento para que /auth/callback responda con la pagina
    de postMessage en vez de un redirect de documento completo (usado por la
    reconexion sin perder el estado de la pagina actual).
    """
    next_path = safe_redirect_path(next_url) if next_url else "/"
    try:
        state, attempt = await OAuthAttemptRepository.create(
            mode="popup" if popup else "direct",
            next_path=next_path,
            expected_email=email_hint,
            client_nonce=client_nonce,
        )
    except OAuthRepositoryUnavailable as exc:
        logger.error("No se pudo iniciar login: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="El servicio de autenticacion no esta disponible. Intenta de nuevo en unos momentos.",
            headers=_NO_STORE_HEADERS,
        ) from exc

    auth_url = ms_auth.get_auth_url(state=state, nonce=attempt["oidc_nonce"])
    response = RedirectResponse(auth_url, headers=_NO_STORE_HEADERS)
    if popup:
        # Pista de UX (no de seguridad: el intento en Redis sigue siendo la unica
        # fuente de verdad) para saber si un /auth/callback duplicado (doble hit,
        # back/forward dentro del popup) debe responder via postMessage en vez de
        # redirigir el documento cuando el attempt ya fue consumido por el primer hit.
        response.set_cookie(_POPUP_HINT_COOKIE, "1", max_age=300, httponly=True, samesite="lax")
    return response


@router.get("/callback")
async def callback(
    request: Request,
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    error_description: str | None = Query(None),
    ms_auth: MicrosoftAuth = Depends(get_ms_auth),
    conn=Depends(get_db_connection),
):
    """Callback tras el login en Microsoft. Guarda sesion ligera."""
    attempt = await OAuthAttemptRepository.consume(state)

    if error:
        cancelled = error == "access_denied"
        logger.info("Login %s por Microsoft: %s - %s", "cancelado" if cancelled else "con error", error, error_description)
        return _clear_popup_hint(_terminal_response(request, attempt, "cancelled" if cancelled else "error", error_description or error))

    if not attempt:
        logger.warning("Callback OAuth con state invalido, expirado o ya usado.")
        # Sin attempt no hay de donde leer el modo; usamos la cookie de UX puesta
        # en /login (ver _POPUP_HINT_COOKIE) para no forzar "direct" y redirigir
        # el documento completo dentro de un popup en un doble-hit de /callback.
        fallback_mode = "popup" if request.cookies.get(_POPUP_HINT_COOKIE) else "direct"
        return _clear_popup_hint(_terminal_response(
            request, None, "error", "La solicitud de inicio de sesion expiro o ya fue usada. Intenta de nuevo.", mode=fallback_mode
        ))

    if not code:
        return _clear_popup_hint(_terminal_response(request, attempt, "error", "Microsoft no envio un codigo de autorizacion."))

    try:
        user = await process_login_callback(conn, code, ms_auth, expected_nonce=attempt["oidc_nonce"])
    except ValueError as exc:
        logger.warning("Callback de autenticacion invalido: %s", exc)
        return _clear_popup_hint(_terminal_response(request, attempt, "error", str(exc)))
    except asyncpg.PostgresError:
        logger.exception("Error de base de datos en callback de autenticacion")
        if attempt["mode"] == "popup":
            return _clear_popup_hint(_popup_response(request, "error", attempt, message="Error guardando sesion de usuario"))
        # Modo directo: un 500 real (no un redirect silencioso) para que una
        # caida de BD durante el login siga siendo visible a monitoreo/alertas.
        raise HTTPException(status_code=500, detail="Error guardando sesion de usuario")
    except RuntimeError as exc:
        logger.warning("Error de Microsoft en callback de autenticacion: %s", exc)
        return _clear_popup_hint(_terminal_response(request, attempt, "error", "Error de Microsoft, intenta de nuevo."))

    request.session.clear()
    request.session["user_email"] = user["email"]
    request.session["user_name"] = user["name"]

    if attempt["mode"] == "popup":
        return _clear_popup_hint(_popup_response(request, "success", attempt, email=user["email"]))

    redirect_url = safe_redirect_path(attempt["next_path"])
    return _clear_popup_hint(RedirectResponse(url=redirect_url, headers=_NO_STORE_HEADERS))


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
    return RedirectResponse(url=ms_logout_url, headers=_NO_STORE_HEADERS)


@router.api_route("/session", methods=["GET", "HEAD"], tags=["Autenticacion"])
async def session_status(request: Request, conn=Depends(get_db_connection)):
    """Verifica si la sesion local sigue activa: cookie + usuario existente + activo.

    No confirma un OAuth recien iniciado ni la vigencia del token de Graph
    (eso lo resuelve get_valid_graph_token al usarse); esto es solo la sesion
    ligera de la app.
    """
    user_email = request.session.get("user_email")
    if not user_email:
        return JSONResponse({"active": False}, status_code=401, headers=_NO_STORE_HEADERS)

    if not await check_session_active(conn, user_email):
        return JSONResponse({"active": False}, status_code=401, headers=_NO_STORE_HEADERS)

    return JSONResponse({"active": True, "email": user_email}, headers=_NO_STORE_HEADERS)
