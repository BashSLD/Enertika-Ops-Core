"""Reglas estaticas para templates y recursos frontend agregados."""

from __future__ import annotations

import re

from devtools.models import DiffSnapshot, Finding, Severity

_LOCAL_DATE_ISO_RE = re.compile(
    r"\.toISOString\(\)\.(?:"
    r"split\(\s*['\"]T['\"]\s*\)\s*\[\s*0\s*\]"
    r"|slice\(\s*0\s*,\s*10\s*\)"
    r"|substring\(\s*0\s*,\s*10\s*\)"
    r")"
)
_TOAST_TYPO_RE = re.compile(r"#toast-container\b")
_OVERLAY_ROOT_RE = re.compile(r"fixed\s+inset-0")
_OVERLAY_DIM_RE = re.compile(r"bg-opacity|backdrop-blur")


def check_frontend_rules(snapshot: DiffSnapshot) -> list[Finding]:
    findings: list[Finding] = []
    for changed_file in snapshot.files:
        if changed_file.suffix not in {".html", ".js"}:
            continue
        for line in changed_file.added_lines:
            if _LOCAL_DATE_ISO_RE.search(line.text):
                findings.append(
                    Finding(
                        code="TZ003",
                        severity=Severity.ERROR,
                        message=(
                            "No extraer fechas locales con toISOString(); usar toLocalISO."
                        ),
                        path=line.path,
                        line=line.number,
                    )
                )
            if _uses_ternary_tab_class(line.text):
                findings.append(
                    Finding(
                        code="HTMX001",
                        severity=Severity.ERROR,
                        message=(
                            "En tabs Alpine, :class debe usar notacion de objeto, no un "
                            "ternario de cadenas."
                        ),
                        path=line.path,
                        line=line.number,
                    )
                )
            if _TOAST_TYPO_RE.search(line.text):
                findings.append(
                    Finding(
                        code="HTMX002",
                        severity=Severity.ERROR,
                        message=(
                            "Typo de toast OOB: usar #global-toast-container, no "
                            "#toast-container; el ID incorrecto aborta todo el swap."
                        ),
                        path=line.path,
                        line=line.number,
                    )
                )
            if _uses_tojson_in_alpine_data(line.text):
                findings.append(
                    Finding(
                        code="ALPINE001",
                        severity=Severity.ERROR,
                        message=(
                            "No usar |tojson dentro de x-data; usar atributos data- con "
                            "comillas simples y JSON.parse($el.dataset.foo)."
                        ),
                        path=line.path,
                        line=line.number,
                    )
                )
            if _is_overlay_missing_stacking_layer(line.text):
                findings.append(
                    Finding(
                        code="UI001",
                        severity=Severity.WARNING,
                        message=(
                            "Backdrop raiz de modal (fixed inset-0 + bg-opacity/"
                            "backdrop-blur) sin clase modal-overlay-layer para stacking."
                        ),
                        path=line.path,
                        line=line.number,
                    )
                )
    return findings


def _uses_ternary_tab_class(text: str) -> bool:
    return ":class=" in text and "?" in text and "tab" in text


def _uses_tojson_in_alpine_data(text: str) -> bool:
    return "x-data=" in text and "tojson" in text


def _is_overlay_missing_stacking_layer(text: str) -> bool:
    return (
        bool(_OVERLAY_ROOT_RE.search(text))
        and bool(_OVERLAY_DIM_RE.search(text))
        and "modal-overlay-layer" not in text
    )
