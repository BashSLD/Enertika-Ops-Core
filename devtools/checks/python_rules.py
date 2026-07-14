"""Reglas estaticas para codigo Python agregado al diff."""

from __future__ import annotations

import re
from collections.abc import Iterable

from devtools.models import AddedLine, DiffSnapshot, Finding, Severity

_DATE_TODAY_RE = re.compile(r"\bdate\.today\(\)")
_DATETIME_NOW_RE = re.compile(r"\bdatetime\.now\(\s*\)")
_GENERIC_EXCEPTION_RE = re.compile(
    r"^\s*except\s+Exception(?:\s+as\s+[A-Za-z_]\w*)?\s*:"
)
_BARE_EXCEPTION_RE = re.compile(r"^\s*except\s*:")
_PRINT_RE = re.compile(r"(?<![\w.])print\s*\(")
_OLD_TEMPLATE_RESPONSE_RE = re.compile(r"TemplateResponse\(\s*['\"]")
_ASYNC_GATHER_RE = re.compile(r"\basyncio\.gather\s*\(")
_RBAC_DOUBLE_DEPENDS_RE = re.compile(
    r"Depends\(\s*(?:require_module_access|require_manager_access)\s*\("
)
_SQL_MARKER_RE = re.compile(
    r"\b(?:SELECT|INSERT|UPDATE|DELETE|FROM|JOIN|WHERE|RETURNING|ON\s+CONFLICT)\b",
    re.IGNORECASE,
)
_FSTRING_PREFIX_RE = re.compile(r"\bf[\"']")
_STRING_CONCAT_RE = re.compile(r"[\"']\s*\+\s*\w+|\w+\s*\+\s*[\"']")


def check_python_rules(snapshot: DiffSnapshot) -> list[Finding]:
    findings: list[Finding] = []
    for changed_file in snapshot.files:
        if changed_file.suffix != ".py" or not _is_backend_file(changed_file.path):
            continue
        findings.extend(_check_lines(changed_file.path, changed_file.added_lines))
    return findings


def _check_lines(path: str, lines: Iterable[AddedLine]) -> list[Finding]:
    findings: list[Finding] = []
    for line in lines:
        if _DATE_TODAY_RE.search(line.text):
            findings.append(
                _finding("TZ001", line, "date.today() esta prohibido; usar today_mx().")
            )
        if _DATETIME_NOW_RE.search(line.text):
            findings.append(
                _finding(
                    "TZ002",
                    line,
                    "datetime.now() sin zona horaria esta prohibido; usar now_mx().",
                )
            )
        if _GENERIC_EXCEPTION_RE.search(line.text) or _BARE_EXCEPTION_RE.search(
            line.text
        ):
            findings.append(
                _finding(
                    "EXC001",
                    line,
                    "Usar excepciones especificas; no capturar Exception de forma generica.",
                )
            )
        if _PRINT_RE.search(line.text):
            findings.append(
                _finding(
                    "LOG001",
                    line,
                    "El backend debe usar logging estructurado; no usar print().",
                )
            )
        if _OLD_TEMPLATE_RESPONSE_RE.search(line.text):
            findings.append(
                _finding(
                    "TPL001",
                    line,
                    "TemplateResponse requiere request como primer argumento posicional.",
                )
            )
        if _is_db_service(path) and _ASYNC_GATHER_RE.search(line.text):
            findings.append(
                Finding(
                    code="DB001",
                    severity=Severity.WARNING,
                    message=(
                        "No usar asyncio.gather() con consultas que compartan la misma "
                        "conexion asyncpg."
                    ),
                    path=line.path,
                    line=line.number,
                )
            )
        if _RBAC_DOUBLE_DEPENDS_RE.search(line.text):
            findings.append(
                _finding(
                    "RBAC001",
                    line,
                    "require_module_access/require_manager_access ya retornan Depends(); "
                    "no envolver en otro Depends().",
                )
            )
        if _is_db_service(path) and _has_sql_injection_risk(line.text):
            findings.append(
                Finding(
                    code="SQL002",
                    severity=Severity.WARNING,
                    message=(
                        "Posible SQL armado con f-string o concatenacion; usar parametros "
                        "($1, $2, ...) de asyncpg en vez de interpolar valores."
                    ),
                    path=line.path,
                    line=line.number,
                )
            )
    return findings


def _has_sql_injection_risk(text: str) -> bool:
    if not _SQL_MARKER_RE.search(text):
        return False
    if _FSTRING_PREFIX_RE.search(text) and "{" in text:
        return True
    return bool(_STRING_CONCAT_RE.search(text))


def _finding(code: str, line: AddedLine, message: str) -> Finding:
    return Finding(
        code=code,
        severity=Severity.ERROR,
        message=message,
        path=line.path,
        line=line.number,
    )


def _is_backend_file(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return (
        normalized in {"main.py", "worker.py"}
        or normalized.startswith("core/")
        or normalized.startswith("modules/")
    )


def _is_db_service(path: str) -> bool:
    filename = path.replace("\\", "/").rsplit("/", maxsplit=1)[-1]
    return (
        filename == "db_service.py"
        or filename.startswith("db_")
        or filename.endswith("_db_service.py")
    )
