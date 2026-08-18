import json
import re
from io import BytesIO
from urllib.parse import quote

from fastapi import Request, Response
from fastapi.responses import StreamingResponse
from fastapi.templating import Jinja2Templates

_templates = Jinja2Templates(directory="templates")


def sanitize_input_string(text: str) -> str:
    """
    Sanitizes an input string by removing common "finger error" characters
    from the START and END of the string.
    Does NOT modify the internal content of the string.

    Removes: Spaces, dots, pipes, commas, dashes, underscores, asterisks, slashes, backslashes,
    plus signs, quotes, colons, semicolons, equals, exclamation marks, question marks,
    hashes, percent signs, ampersands, ats, parentheses, brackets, braces, angle brackets,
    tildes, backticks.

    Examples:
      "| Project Alpha - ." -> "Project Alpha"
      "  User Name  " -> "User Name"
      "/Path/To/Something/" -> "Path/To/Something"
      "+IZTAPALA" -> "IZTAPALA"
      "[Draft] Project X" -> "Draft] Project X"
    """
    if not text:
        return ""

    # Regex for "dirty" characters at the edges
    dirty_pattern = r"^[\s\.|,_*/\\\+\-\"\':;=!\?#%&@\(\)\[\]\{\}<>~`]+|[\s\.|,_*/\\\+\-\"\':;=!\?#%&@\(\)\[\]\{\}<>~`]+$"

    return re.sub(dirty_pattern, "", text).strip()


def format_minutes(value) -> str:
    total = int(value or 0)
    h, m = divmod(total, 60)
    if h and m:
        return f"{h}h {m:02d}m"
    if h:
        return f"{h}h"
    return f"{m}m"


def sanitize_filename_slug(text: str, max_length: int = 40) -> str:
    """Sanitiza texto libre para usarlo como fragmento de nombre de archivo."""
    return re.sub(r"[^\w\-]", "_", text)[:max_length].strip("_")


_INVALID_SHEET_TITLE_CHARS = re.compile(r"[\\/?*\[\]:]")


def safe_sheet_title(title: str, used_titles: set[str], fallback: str = "Hoja") -> str:
    """
    Sanitiza un titulo de hoja de Excel: reemplaza caracteres invalidos por "_",
    trunca a 31 caracteres y evita colisiones (Excel no permite hojas
    duplicadas por mayus/minus) agregando el sufijo " (2)", " (3)", etc.

    `used_titles` debe contener los titulos ya usados en `casefold()` y se
    actualiza con el titulo devuelto.
    """
    sanitized = _INVALID_SHEET_TITLE_CHARS.sub("_", (title or "").strip())
    base_title = sanitized[:31] if sanitized.strip("_") else fallback

    candidate = base_title
    suffix_number = 2
    while candidate.casefold() in used_titles:
        suffix = f" ({suffix_number})"
        candidate = f"{base_title[:31 - len(suffix)]}{suffix}"
        suffix_number += 1

    used_titles.add(candidate.casefold())
    return candidate


def content_disposition_header(disposition: str, filename: str) -> str:
    """Arma un header Content-Disposition seguro (sanitiza el nombre y agrega filename* UTF-8)."""
    safe_filename = filename.replace("\\", "_").replace("/", "_").replace('"', "")
    safe_filename = safe_filename.replace("\r", "").replace("\n", "") or "documento"
    encoded = quote(safe_filename)
    return f'{disposition}; filename="{safe_filename}"; filename*=UTF-8\'\'{encoded}'


def is_htmx(request: Request) -> bool:
    return bool(
        request.headers.get("hx-request") and not request.headers.get("hx-history-restore-request")
    )


def hx_location_response(
    path: str, target: str = "#main-content", swap: str = "innerHTML", status_code: int = 200
) -> Response:
    """Navega via htmx (HX-Location) sin recargar el documento completo.

    A diferencia de HX-Redirect, no reconstruye el documento entero — preserva
    el x-data raiz de base.html (ej. sidebarOpen) entre navegaciones. Como el
    hx-target original (ej. #modal-action-container) nunca recibe el swap de
    esta respuesta, dispara el evento "clear-modal-overlays" (ver base.html)
    para vaciar los contenedores globales de modal y evitar que quede un
    overlay huerfano flotando sobre el contenido nuevo.

    Se incluye "source" en el payload porque htmx, al procesar HX-Location
    internamente (ajaxHelper -> issueAjaxRequest), usa document.body como
    elemento emisor si no se especifica uno. Eso le agrega la clase
    htmx-request al <body>, lo que activa (via CSS ".htmx-request
    .htmx-indicator") CUALQUIER .htmx-indicator descendiente de body -incluido
    #global-loading-overlay, que ningun elemento de esta navegacion pidio
    explicitamente. Apuntar "source" a un elemento estable (el mismo target)
    evita que ese overlay global aparezca huerfano durante la navegacion.

    ADVERTENCIA: no combinar el elemento que dispara esta ruta con
    hx-disabled-elt="this". saveCurrentPageToHistory() serializa el DOM vivo
    de #main-content en localStorage ANTES de que htmx limpie los indicadores
    de la request (que es lo que revierte el disabled), por lo que el snapshot
    cacheado queda con ese elemento deshabilitado para siempre y navegaciones
    "atras" futuras lo restauran ya muerto. Usar hx-sync="this:drop" si se
    necesita evitar doble submit.
    """
    payload = json.dumps({"path": path, "target": target, "swap": swap, "source": target})
    return Response(
        status_code=status_code,
        headers={"HX-Location": payload, "HX-Trigger": "clear-modal-overlays"},
    )


def toast_error(
    request: Request,
    message: str,
    status_code: int = 400,
    title: str = "Error",
    headers: dict | None = None,
):
    return _templates.TemplateResponse(
        request,
        "shared/toast.html",
        {"type": "error", "title": title, "message": message},
        status_code=status_code,
        headers={**(headers or {}), "HX-Reswap": "none"},
    )


def toast_success(request: Request, message: str):
    return _templates.TemplateResponse(
        request,
        "shared/toast.html",
        {"type": "success", "title": "Listo", "message": message},
        headers={"HX-Reswap": "none"},
    )


def excel_bytes_response(content: bytes, filename: str) -> StreamingResponse:
    """Respuesta de descarga xlsx a partir de bytes ya serializados (ej. workbook armado en un executor)."""
    return StreamingResponse(
        BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def excel_response(workbook, filename: str) -> StreamingResponse:
    output = BytesIO()
    workbook.save(output)
    return excel_bytes_response(output.getvalue(), filename)
