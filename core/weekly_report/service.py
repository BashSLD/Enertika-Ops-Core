import logging
from datetime import date, timedelta

logger = logging.getLogger("WeeklyReportCEO")


async def generar_y_enviar_reporte_ceo(
    ms_auth,
    sender_email: str,
    ceo_email: str,
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

    semana_label = (
        f"{data['semana_inicio'].strftime('%d/%m')} al "
        f"{data['semana_fin'].strftime('%d/%m/%Y')}"
    )

    pdf_service = get_pdf_service()
    pdf_bytes = await pdf_service.generate(
        "reporte_desarrollo_ceo.html",
        {**data, "semana_label": semana_label},
    )

    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader("templates"), autoescape=True)
    email_html = env.get_template("shared/emails/reporte_desarrollo_ceo.html").render(
        **data, semana_label=semana_label
    )

    app_token = await ms_auth.get_application_token()
    if not app_token:
        logger.error("[CEO_REPORT] No se pudo obtener token de aplicacion")
        return False

    filename = f"reporte_desarrollo_{data['semana_inicio'].isoformat()}.pdf"
    subject = f"Reporte de Desarrollo ECO — Semana del {semana_label}"

    success, msg = await ms_auth.send_email_with_attachments(
        access_token=app_token,
        from_email=sender_email,
        subject=subject,
        body=email_html,
        recipients=[ceo_email],
        attachments_files=[
            {
                "name": filename,
                "contentType": "application/pdf",
                "content_bytes": pdf_bytes,
            }
        ],
    )

    if success:
        logger.info("[CEO_REPORT] Enviado a %s — semana %s", ceo_email, semana_label)
    else:
        logger.error("[CEO_REPORT] Error al enviar: %s", msg)

    return success
