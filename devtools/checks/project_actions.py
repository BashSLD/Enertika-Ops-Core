"""Acciones de calidad que dependen del tipo de archivo modificado."""

from __future__ import annotations

import re

from devtools.models import DiffSnapshot, Finding, Severity

_SQL_MARKER_RE = re.compile(
    r"\b(?:SELECT|INSERT|UPDATE|DELETE|FROM|JOIN|WHERE|RETURNING|ON\s+CONFLICT)\b",
    re.IGNORECASE,
)


def check_project_actions(snapshot: DiffSnapshot) -> list[Finding]:
    findings: list[Finding] = []
    sql_location = _first_sql_change(snapshot)
    if sql_location is not None:
        path, line = sql_location
        findings.append(
            Finding(
                code="SQL_AUDIT",
                severity=Severity.ACTION,
                message=(
                    "Se modifico SQL en un servicio de base de datos; ejecutar la "
                    "auditoria SQL antes de revision final."
                ),
                path=path,
                line=line,
                command="/auditar-sql diff",
            )
        )

    tailwind_location = _first_tailwind_change(snapshot)
    if tailwind_location is not None:
        path, line = tailwind_location
        findings.append(
            Finding(
                code="TAILWIND_BUILD",
                severity=Severity.ACTION,
                message=(
                    "Se agregaron clases o estilos frontend; regenerar el CSS compilado."
                ),
                path=path,
                line=line,
                command="npm run build:css",
            )
        )
    return findings


def _first_sql_change(snapshot: DiffSnapshot) -> tuple[str, int] | None:
    for changed_file in snapshot.files:
        if not _is_db_service(changed_file.path):
            continue
        for line in changed_file.added_lines:
            if _SQL_MARKER_RE.search(line.text):
                return changed_file.path, line.number
    return None


def _first_tailwind_change(snapshot: DiffSnapshot) -> tuple[str, int] | None:
    for changed_file in snapshot.files:
        normalized = changed_file.path.replace("\\", "/")
        is_template = (
            normalized.startswith("templates/") and changed_file.suffix == ".html"
        )
        is_style_source = (
            changed_file.suffix == ".css"
            and normalized != "static/css/tailwind.css"
        )
        if not is_template and not is_style_source:
            continue
        for line in changed_file.added_lines:
            if "class=" in line.text or ":class=" in line.text or "@apply" in line.text:
                return changed_file.path, line.number
    return None


def _is_db_service(path: str) -> bool:
    filename = path.replace("\\", "/").rsplit("/", maxsplit=1)[-1]
    return (
        filename == "db_service.py"
        or filename.startswith("db_")
        or filename.endswith("_db_service.py")
    )
