import re

from fastapi import Request
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
    return f"{total // 60}:{total % 60:02d}"


def is_htmx(request: Request) -> bool:
    return bool(
        request.headers.get("hx-request") and not request.headers.get("hx-history-restore-request")
    )


def toast_error(request: Request, message: str, status_code: int = 400):
    return _templates.TemplateResponse(
        request,
        "shared/toast.html",
        {"type": "error", "title": "Error", "message": message},
        status_code=status_code,
        headers={"HX-Reswap": "none"},
    )


def toast_success(request: Request, message: str):
    return _templates.TemplateResponse(
        request,
        "shared/toast.html",
        {"type": "success", "title": "Listo", "message": message},
        headers={"HX-Reswap": "none"},
    )
