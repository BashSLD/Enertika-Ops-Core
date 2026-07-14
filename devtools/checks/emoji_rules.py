"""Deteccion de emojis en backend y UI, prohibidos por CLAUDE.md."""

from __future__ import annotations

import re

from devtools.models import DiffSnapshot, Finding, Severity

_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U00002B00-\U00002BFF"
    "\U0001F1E6-\U0001F1FF"
    "]"
)


def check_emoji_rules(snapshot: DiffSnapshot) -> list[Finding]:
    findings: list[Finding] = []
    for changed_file in snapshot.files:
        if not _is_scannable(changed_file.path, changed_file.suffix):
            continue
        for line in changed_file.added_lines:
            if _EMOJI_RE.search(line.text):
                findings.append(
                    Finding(
                        code="EMOJI001",
                        severity=Severity.ERROR,
                        message=(
                            "No usar emojis en backend ni UI; usar SVG inline o "
                            "texto+color para chips/iconos."
                        ),
                        path=line.path,
                        line=line.number,
                    )
                )
    return findings


def _is_scannable(path: str, suffix: str) -> bool:
    if suffix in {".html", ".js"}:
        return True
    if suffix == ".py":
        return _is_backend_file(path)
    return False


def _is_backend_file(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return (
        normalized in {"main.py", "worker.py"}
        or normalized.startswith("core/")
        or normalized.startswith("modules/")
    )


__all__ = ["check_emoji_rules"]
