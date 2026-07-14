"""Registro de controles deterministas del proyecto."""

from devtools.checks.css_rules import check_css_rules
from devtools.checks.emoji_rules import check_emoji_rules
from devtools.checks.frontend_rules import check_frontend_rules
from devtools.checks.project_actions import check_project_actions
from devtools.checks.python_rules import check_python_rules
from devtools.checks.sql_rules import check_sql_rules
from devtools.models import DiffSnapshot, Finding


def run_checks(snapshot: DiffSnapshot) -> tuple[Finding, ...]:
    """Ejecuta todos los controles y entrega resultados estables."""

    findings = [
        *check_python_rules(snapshot),
        *check_frontend_rules(snapshot),
        *check_project_actions(snapshot),
        *check_emoji_rules(snapshot),
        *check_sql_rules(snapshot),
        *check_css_rules(snapshot),
    ]
    return tuple(
        sorted(
            findings,
            key=lambda item: (
                item.path or "",
                item.line or 0,
                item.severity.value,
                item.code,
            ),
        )
    )


__all__ = ["run_checks"]
