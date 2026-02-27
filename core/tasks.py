import os
import time
import asyncio
import logging
import asyncpg
from datetime import datetime, timedelta

logger = logging.getLogger("BackgroundTasks")

async def cleanup_temp_uploads_periodically(interval_seconds: int = 3600, max_age_seconds: int = 3600):
    """
    Tarea en segundo plano que elimina archivos antiguos de la carpeta temp_uploads.
    
    Args:
        interval_seconds: Cada cuánto tiempo se ejecuta la limpieza (default 1 hora).
        max_age_seconds: Edad máxima del archivo antes de ser borrado (default 1 hora).
    """
    directory = "temp_uploads"
    
    while True:
        try:
            if os.path.exists(directory):
                logger.info("Iniciando limpieza de archivos temporales...")
                count = 0
                now = time.time()
                
                for filename in os.listdir(directory):
                    file_path = os.path.join(directory, filename)
                    # Solo archivos
                    if os.path.isfile(file_path):
                        file_age = now - os.path.getmtime(file_path)
                        if file_age > max_age_seconds:
                            try:
                                os.remove(file_path)
                                count += 1
                                logger.info(f"Eliminado archivo temporal expirado: {filename}")
                            except Exception as e:
                                logger.error(f"Error eliminando {filename}: {e}")
                
                if count > 0:
                    logger.info(f"Limpieza completada. {count} archivos eliminados.")
            
        except Exception as e:
            logger.error(f"Error en tarea de limpieza: {e}")
            
        # Esperar para la siguiente ejecución
        await asyncio.sleep(interval_seconds)


async def check_levantamientos_sin_asignar_periodically(interval_seconds: int = 21600):
    """
    Tarea en segundo plano que detecta levantamientos en estado 'pendiente'
    sin tecnico asignado por mas de 24 horas y envia recordatorio por email.

    Corre cada 6 horas (21600 s). La primera ejecucion ocurre tras el primer
    ciclo de espera para dar tiempo al pool de BD y a los servicios de startup.

    Destinatarios configurables en Admin > Emails con:
      modulo='LEVANTAMIENTOS', trigger_value='LEV_SIN_ASIGNAR'

    Anti-spam en memoria: no envia dos recordatorios al mismo levantamiento
    en menos de 24 horas (se reinicia si el proceso se reinicia, lo cual es
    aceptable dado el intervalo de 6 horas).
    """
    logger.info("[LEV_REMINDER] Tarea de recordatorios inicializada (intervalo: %sh)", interval_seconds // 3600)

    # Anti-spam: { str(id_levantamiento): datetime_ultimo_envio }
    _sent_reminders: dict = {}

    while True:
        await asyncio.sleep(interval_seconds)
        try:
            from core.database import get_db_pool
            from core.email_rules import EmailRulesService
            from core.microsoft import MicrosoftAuth

            pool = await get_db_pool()
            ms_auth = MicrosoftAuth()
            rules_svc = EmailRulesService()

            async with pool.acquire() as conn:
                # 1. Levantamientos pendientes sin asignar por mas de 24h
                rows = await conn.fetch("""
                    SELECT
                        l.id_levantamiento,
                        l.id_oportunidad,
                        l.fecha_solicitud AT TIME ZONE 'America/Mexico_City' AS fecha_solicitud,
                        o.op_id_estandar,
                        o.nombre_proyecto,
                        o.titulo_proyecto,
                        o.cliente_nombre
                    FROM tb_levantamientos l
                    INNER JOIN tb_oportunidades o ON l.id_oportunidad = o.id_oportunidad
                    INNER JOIN tb_cat_estatus_levantamiento e ON l.id_estatus_global = e.id
                    WHERE e.codigo = 'pendiente'
                      AND l.created_at < NOW() - INTERVAL '24 hours'
                      AND o.email_enviado = true
                      AND l.tecnico_asignado_id IS NULL
                      AND NOT EXISTS (
                          SELECT 1 FROM tb_levantamiento_asignaciones la
                          WHERE la.id_levantamiento = l.id_levantamiento
                      )
                """)

                if not rows:
                    logger.debug("[LEV_REMINDER] Sin levantamientos pendientes sin asignar > 24h")
                    continue

                # 2. Destinatarios configurados en tb_config_emails
                emails = await rules_svc.get_emails_by_event(conn, 'LEVANTAMIENTOS', 'LEV_SIN_ASIGNAR')
                to_emails = set(emails.get('to', []))
                cc_emails = set(emails.get('cc', []))

                if not to_emails:
                    logger.warning(
                        "[LEV_REMINDER] No hay destinatarios TO configurados para LEV_SIN_ASIGNAR. "
                        "Agregar en Admin > Emails (modulo=LEVANTAMIENTOS, trigger=LEV_SIN_ASIGNAR, type=TO)."
                    )
                    continue

                # 3. Remitente configurado (DEFAULT)
                sender_row = await conn.fetchrow("""
                    SELECT email_remitente FROM tb_correos_notificaciones
                    WHERE departamento = 'DEFAULT' AND activo = true
                    LIMIT 1
                """)
                if not sender_row:
                    logger.error("[LEV_REMINDER] No hay remitente DEFAULT configurado en tb_correos_notificaciones")
                    continue
                sender_email = sender_row['email_remitente']

                # 4. Token de aplicacion (una sola vez por ciclo)
                app_token = await ms_auth.get_application_token()
                if not app_token:
                    logger.error("[LEV_REMINDER] No se pudo obtener token de aplicacion para enviar recordatorios")
                    continue

                # 5. Enviar un email por levantamiento (con anti-spam)
                now = datetime.utcnow()

                # Limpiar entradas antiguas del dict anti-spam (> 48h)
                cutoff = now - timedelta(hours=48)
                _sent_reminders = {k: v for k, v in _sent_reminders.items() if v > cutoff}

                for row in rows:
                    lev_id = str(row['id_levantamiento'])

                    # Anti-spam: saltar si ya se envio en las ultimas 24h
                    last_sent = _sent_reminders.get(lev_id)
                    if last_sent and (now - last_sent) < timedelta(hours=24):
                        continue

                    nombre_proyecto = row['nombre_proyecto'] or row['titulo_proyecto'] or 'Sin nombre'
                    op_id = row['op_id_estandar'] or ''
                    cliente = row['cliente_nombre'] or ''
                    fecha_sol = (
                        row['fecha_solicitud'].strftime('%d/%m/%Y %H:%M')
                        if row['fecha_solicitud'] else 'N/A'
                    )

                    html_body = f"""
<html>
<body style="font-family:Arial,sans-serif;color:#333;margin:0;padding:0;">
  <div style="max-width:600px;margin:0 auto;padding:20px;">
    <div style="background:#f59e0b;color:white;padding:16px 20px;border-radius:8px 8px 0 0;">
      <h2 style="margin:0;font-size:18px;font-weight:600;">Levantamiento sin asignar — Recordatorio 24h</h2>
    </div>
    <div style="background:#fffbeb;border:1px solid #fde68a;border-top:none;padding:20px;border-radius:0 0 8px 8px;">
      <table style="width:100%;border-collapse:collapse;">
        <tr><td style="padding:4px 0;color:#78350f;font-weight:600;width:130px;">Proyecto</td>
            <td style="padding:4px 0;">{nombre_proyecto}</td></tr>
        <tr><td style="padding:4px 0;color:#78350f;font-weight:600;">Cliente</td>
            <td style="padding:4px 0;">{cliente}</td></tr>
        <tr><td style="padding:4px 0;color:#78350f;font-weight:600;">OP</td>
            <td style="padding:4px 0;font-family:monospace;">{op_id}</td></tr>
        <tr><td style="padding:4px 0;color:#78350f;font-weight:600;">Fecha solicitud</td>
            <td style="padding:4px 0;">{fecha_sol}</td></tr>
      </table>
      <p style="margin-top:16px;color:#92400e;font-weight:600;border-top:1px solid #fde68a;padding-top:12px;">
        Este levantamiento lleva mas de 24 horas en el sistema sin que se le asigne un tecnico responsable.
      </p>
      <p style="margin:0;color:#555;">Por favor, ingrese al modulo de Levantamientos y realice la asignacion.</p>
    </div>
  </div>
</body>
</html>"""

                    subject = f"[Recordatorio] Levantamiento sin asignar: {op_id} — {cliente}"

                    success, msg = await ms_auth.send_email_with_attachments(
                        access_token=app_token,
                        from_email=sender_email,
                        subject=subject,
                        body=html_body,
                        recipients=list(to_emails),
                        cc_recipients=list(cc_emails) if cc_emails else None,
                        importance="high"
                    )

                    if success:
                        _sent_reminders[lev_id] = now
                        logger.info("[LEV_REMINDER] Recordatorio enviado: lev=%s op=%s", lev_id, op_id)
                    else:
                        logger.error("[LEV_REMINDER] Error enviando recordatorio lev=%s: %s", lev_id, msg)

        except asyncpg.PostgresError as e:
            logger.error("[LEV_REMINDER] Error de BD en tarea de recordatorios: %s", e)
        except Exception as e:
            logger.error("[LEV_REMINDER] Error inesperado en tarea de recordatorios: %s", e, exc_info=True)
