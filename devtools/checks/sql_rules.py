"""Reglas de correctitud SQL agregadas al diff, fuera del alcance de Python/frontend."""

from __future__ import annotations

import re

from devtools.models import DiffSnapshot, Finding, Severity

_EXTRACT_DOW_RE = re.compile(r"EXTRACT\s*\(\s*DOW", re.IGNORECASE)
_DOW_CONVERSION_RE = re.compile(r"\+\s*6\s*\)\s*%\s*7")


def check_sql_rules(snapshot: DiffSnapshot) -> list[Finding]:
    findings: list[Finding] = []
    for changed_file in snapshot.files:
        if changed_file.suffix not in {".py", ".sql"}:
            continue
        for line in changed_file.added_lines:
            if _EXTRACT_DOW_RE.search(line.text) and not _DOW_CONVERSION_RE.search(
                line.text
            ):
                findings.append(
                    Finding(
                        code="TZ004",
                        severity=Severity.WARNING,
                        message=(
                            "EXTRACT(DOW) usa domingo=0 pero dia_semana en Python usa "
                            "lunes=0; verificar la conversion "
                            "((EXTRACT(DOW FROM fecha)::int + 6) % 7)."
                        ),
                        path=line.path,
                        line=line.number,
                    )
                )
    return findings


__all__ = ["check_sql_rules"]
