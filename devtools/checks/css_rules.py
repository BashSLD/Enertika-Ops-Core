"""Reglas de rendimiento para CSS agregado al diff."""

from __future__ import annotations

import re

from devtools.models import DiffSnapshot, Finding, Severity

# Selector universal (*, no descendiente como ".foo *") que abre un bloque con
# una propiedad de transicion. El selector debe iniciar el grupo: precedido por
# inicio de linea, "{", "}" o ",". Asi no se marca ".foo * { transition }",
# que si es un selector acotado permitido.
_GLOBAL_TRANSITION_RE = re.compile(
    r"(?:^|[{},])\s*\*\s*(?:,[^{]*)?\{[^}]*transition",
    re.IGNORECASE,
)

_COMPILED_TAILWIND = "static/css/tailwind.css"


def check_css_rules(snapshot: DiffSnapshot) -> list[Finding]:
    findings: list[Finding] = []
    for changed_file in snapshot.files:
        if changed_file.suffix != ".css":
            continue
        if changed_file.path.replace("\\", "/") == _COMPILED_TAILWIND:
            continue
        for line in changed_file.added_lines:
            if _GLOBAL_TRANSITION_RE.search(line.text):
                findings.append(
                    Finding(
                        code="CSS001",
                        severity=Severity.ERROR,
                        message=(
                            "Transicion en selector universal (* { transition }); usar "
                            "selectores acotados (a, button, [class*=\"transition\"])."
                        ),
                        path=line.path,
                        line=line.number,
                    )
                )
    return findings


__all__ = ["check_css_rules"]
