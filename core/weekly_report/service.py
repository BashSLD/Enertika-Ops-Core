import logging
from datetime import date, timedelta
from typing import List

logger = logging.getLogger("WeeklyReportCEO")


def _is_valid_email(value: str) -> bool:
    value = (value or "").strip()
    if not value or "@" not in value:
        return False
    local, _, domain = value.partition("@")
    return bool(local and domain and "." in domain)


def parse_ceo_recipients(raw: str) -> List[str]:
    """Normaliza y deduplica destinatarios separados por coma o punto y coma."""
    raw = (raw or "").replace(";", ",")
    recipients: List[str] = []
    seen = set()

    for part in raw.split(","):
        email = part.strip().lower()
        if not email or not _is_valid_email(email):
            continue
        if email in seen:
            continue
        seen.add(email)
        recipients.append(email)

    return recipients


def _build_period_labels(start: date, end: date) -> tuple[str, str, str, str, str]:
    """Retorna etiquetas de alcance para textos, titulos y gramatica."""
    label = f"{start.strftime('%d/%m')} al {end.strftime('%d/%m/%Y')}"
    total_days = (end - start).days + 1
    is_period = total_days > 7
    scope_title = "Periodo" if is_period else "Semana"
    scope_lower = scope_title.lower()
    scope_phrase = "el periodo" if is_period else "la semana"
    scope_descriptor = "de periodo" if is_period else "semanal"
    return label, scope_title, scope_lower, scope_phrase, scope_descriptor


async def generar_y_enviar_reporte_ceo(
    ms_auth,
    sender_email: str,
    ceo_recipients: List[str],
    since: date = None,
    until: date = None,
) -> bool:
    """
    Genera el reporte de desarrollo semanal y lo envía al CEO vía Graph API.
    Retorna True si el envío fue exitoso.
    """
    from .git_reader import get_weekly_commits
    from core.pdf_service.service import get_pdf_service

    data = get_weekly_commits(since=since, until=until)

    if data["total_commits"] == 0:
        logger.info("[CEO_REPORT] Sin commits esta semana — reporte no enviado")
        return False

    if not ceo_recipients:
        logger.warning("[CEO_REPORT] Sin destinatarios válidos — reporte no enviado")
        return False

    semana_label, scope_title, scope_lower, scope_phrase, scope_descriptor = _build_period_labels(
        data["semana_inicio"], data["semana_fin"]
    )

    pdf_service = get_pdf_service()
    pdf_bytes = await pdf_service.generate(
        "reporte_desarrollo_ceo.html",
        {
            **data,
            "semana_label": semana_label,
            "report_scope": scope_title,
            "report_scope_lower": scope_lower,
            "report_scope_phrase": scope_phrase,
            "report_scope_descriptor": scope_descriptor,
        },
    )

    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader("templates"), autoescape=True)
    email_html = env.get_template("shared/emails/reporte_desarrollo_ceo.html").render(
        **data,
        semana_label=semana_label,
        report_scope=scope_title,
        report_scope_lower=scope_lower,
        report_scope_phrase=scope_phrase,
        report_scope_descriptor=scope_descriptor,
    )

    app_token = await ms_auth.get_application_token()
    if not app_token:
        logger.error("[CEO_REPORT] No se pudo obtener token de aplicacion")
        return False

    filename = f"reporte_desarrollo_{data['semana_inicio'].isoformat()}.pdf"
    subject = f"Reporte de Desarrollo ECO — {scope_title} del {semana_label}"

    success, msg = await ms_auth.send_email_with_attachments(
        access_token=app_token,
        from_email=sender_email,
        subject=subject,
        body=email_html,
        recipients=ceo_recipients,
        attachments_files=[
            {
                "name": filename,
                "contentType": "application/pdf",
                "content_bytes": pdf_bytes,
            }
        ],
    )

    if success:
        logger.info("[CEO_REPORT] Enviado a %s — %s %s", ", ".join(ceo_recipients), scope_lower, semana_label)
    else:
        logger.error("[CEO_REPORT] Error al enviar: %s", msg)

    return success
