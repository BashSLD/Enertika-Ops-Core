import re
from io import BytesIO

from fastapi import Request
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


def is_htmx(request: Request) -> bool:
    return bool(
        request.headers.get("hx-request") and not request.headers.get("hx-history-restore-request")
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


def excel_response(workbook, filename: str) -> StreamingResponse:
    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
