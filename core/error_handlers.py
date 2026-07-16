"""
Manejador central de excepciones de autenticacion/autorizacion.

Contrato: un HTTPException 401 con detail == "SESSION_EXPIRED" (emitido por
core/permissions.py::_require_authenticated o por los emisores manuales
migrados en routers) senala sesion ausente o vencida. Cualquier otro
HTTPException 401/403 se trata como autorizacion insuficiente con sesion
valida. Este handler NO toca otros HTTPException de negocio (400/404/422/500...)
- esos se re-emiten tal cual via el handler default de FastAPI.

La respuesta se negocia segun el tipo de solicitud:
- documento HTML (navegacion o history-restore): redirect a login / pagina
  de acceso denegado en espanol.
- HTMX: status real + X-Auth-Reason, swap cancelado (HX-Reswap: none) para
  no insertar el login/error dentro de #main-content.
- API/fetch/descargas/streams/SSE: JSON con el status real.
"""
import logging
from urllib.parse import quote

from fastapi import Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from core.permissions import SESSION_EXPIRED_DETAIL
from core.security import safe_redirect_path
from modules.shared.utils import is_htmx, toast_error

logger = logging.getLogger("Auth.ErrorHandlers")

_templates = Jinja2Templates(directory="templates")

_NO_STORE = "no-store"


def _wants_document(request: Request) -> bool:
    """Misma heuristica que static/sw.js: navegacion real pide text/html."""
    accept = request.headers.get("accept", "")
    return "text/html" in accept


def _is_history_restore(request: Request) -> bool:
    return bool(request.headers.get("hx-history-restore-request"))


def _next_path(request: Request) -> str:
    path = request.url.path
    query = request.url.query
    return f"{path}?{query}" if query else path


async def auth_exception_handler(request: Request, exc: HTTPException) -> Response:
    is_session_expired = exc.status_code == 401 and exc.detail == SESSION_EXPIRED_DETAIL
    is_forbidden = exc.status_code == 403

    if not is_session_expired and not is_forbidden:
        # No es un caso de autenticacion/autorizacion: delegar al handler
        # default de FastAPI (mismo serializado que si este handler no existiera).
        return await http_exception_handler(request, exc)

    document_request = _wants_document(request) or _is_history_restore(request)
    htmx_request = is_htmx(request) and not document_request
    no_body = request.method == "HEAD"

    if is_session_expired:
        if document_request:
            next_path = safe_redirect_path(_next_path(request))
            request.session["post_login_redirect"] = next_path
            return RedirectResponse(
                url=f"/auth/login?next={quote(next_path, safe='')}",
                status_code=303,
                headers={"Cache-Control": _NO_STORE},
            )

        headers = {"X-Auth-Reason": SESSION_EXPIRED_DETAIL, "Cache-Control": _NO_STORE}
        if htmx_request:
            headers["HX-Reswap"] = "none"
        if no_body:
            return Response(status_code=401, headers=headers)
        return JSONResponse(
            {"error": SESSION_EXPIRED_DETAIL, "detail": "Sesion ausente o vencida"},
            status_code=401,
            headers=headers,
        )

    # 403: sesion valida, autorizacion insuficiente.
    detail = exc.detail if isinstance(exc.detail, str) else "No tienes permisos para esta accion."

    if document_request:
        response = _templates.TemplateResponse(
            request,
            "shared/acceso_denegado.html",
            {"detail": detail},
            status_code=403,
        )
        response.headers["Cache-Control"] = _NO_STORE
        return response

    headers = dict(exc.headers or {})
    if htmx_request:
        headers["HX-Reswap"] = "none"
    if no_body:
        return Response(status_code=403, headers=headers)
    if htmx_request:
        return toast_error(request, detail, status_code=403, title="Acceso denegado", headers=headers)
    return JSONResponse({"error": "FORBIDDEN", "detail": detail}, status_code=403, headers=headers)
