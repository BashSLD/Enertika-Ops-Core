import os
import time
import asyncio
import logging
import asyncpg
import urllib.parse
from datetime import timedelta
from jinja2 import Environment, FileSystemLoader, TemplateError

from core.tasks_db_service import get_tasks_db_service
from core.timezone import now_mx

logger = logging.getLogger("BackgroundTasks")
tasks_db = get_tasks_db_service()
TASK_RUNTIME_ERRORS = (RuntimeError, TypeError, ValueError)
TASK_ROW_RUNTIME_ERRORS = (RuntimeError, TypeError, ValueError, KeyError, TemplateError)

_lev_tpl = Environment(
    loader=FileSystemLoader("templates"), autoescape=True
).get_template("shared/emails/levantamientos/recordatorio.html")


def _build_maps_url(sitio_maps, op_maps, coords):
    if sitio_maps:
        return sitio_maps
    if op_maps:
        return op_maps
    if coords:
        return f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(coords)}"
    return None


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
                            except OSError as e:
                                logger.error(f"Error eliminando {filename}: {e}")
                
                if count > 0:
                    logger.info(f"Limpieza completada. {count} archivos eliminados.")
            
        except OSError as e:
            logger.error(f"Error en tarea de limpieza: {e}")
            
        # Esperar para la siguiente ejecución
        await asyncio.sleep(interval_seconds)


async def check_levantamientos_sin_asignar_periodically(interval_seconds: int = 21600):
    """
    Tarea en segundo plano que detecta levantamientos en estado 'pendiente'
    sin ingeniero responsable asignado por mas de 24 horas y envia recordatorio
    al jefe de area asignado al levantamiento.

    Corre cada 6 horas (21600 s). La primera ejecucion ocurre tras el primer
    ciclo de espera para dar tiempo al pool de BD y a los servicios de startup.

    Stop: cuando existe un registro en tb_levantamiento_asignaciones con es_responsable=true.
    Edge case jefe==responsable: cubierto automaticamente porque el NOT EXISTS falla.

    Anti-spam key: "{id_levantamiento}:{jefe_area_id}" — si el jefe cambia, la key
    cambia y el nuevo jefe recibe la alerta sin esperar las 24h del ciclo.
    """
    logger.info("[LEV_REMINDER] Tarea de recordatorios inicializada (intervalo: %sh)", interval_seconds // 3600)

    # Anti-spam: { "{id_levantamiento}:{jefe_area_id}": datetime_ultimo_envio }
    _sent_reminders: dict = {}

    while True:
        await asyncio.sleep(interval_seconds)
        try:
            from core.database import get_db_pool
            from core.microsoft import MicrosoftAuth

            pool = await get_db_pool()
            ms_auth = MicrosoftAuth()

            async with pool.acquire() as conn:
                # Levantamientos pendientes sin responsable asignado > 24h con jefe asignado
                rows = await tasks_db.get_unassigned_levantamientos_reminders(conn)

                if not rows:
                    logger.debug("[LEV_REMINDER] Sin levantamientos pendientes sin responsable > 24h")
                    continue

                # Remitente DEFAULT
                sender_email = await tasks_db.get_default_sender_email(conn)
                if not sender_email:
                    logger.error("[LEV_REMINDER] No hay remitente DEFAULT configurado en tb_correos_notificaciones")
                    continue

                # Token de aplicacion (una sola vez por ciclo)
                app_token = await ms_auth.get_application_token()
                if not app_token:
                    logger.error("[LEV_REMINDER] No se pudo obtener token de aplicacion para enviar recordatorios")
                    continue

                now = now_mx()

                # Limpiar entradas antiguas del dict anti-spam (> 48h)
                cutoff = now - timedelta(hours=48)
                _sent_reminders = {k: v for k, v in _sent_reminders.items() if v > cutoff}

                for row in rows:
                    lev_id = str(row['id_levantamiento'])
                    jefe_id = str(row['jefe_area_id'])
                    # Incluir jefe en la key: si cambia el jefe, el nuevo recibe la alerta de inmediato
                    key = f"{lev_id}:{jefe_id}"

                    last_sent = _sent_reminders.get(key)
                    if last_sent and (now - last_sent) < timedelta(hours=24):
                        continue

                    nombre_proyecto = row['nombre_proyecto'] or row['titulo_proyecto'] or 'Sin nombre'
                    op_id = row['op_id_estandar'] or ''
                    cliente = row['cliente_nombre'] or ''
                    jefe_nombre = row['jefe_nombre'] or ''

                    html_body = _lev_tpl.render(
                        tipo="sin_asignar",
                        destinatario=jefe_nombre,
                        op_id=op_id,
                        proyecto=nombre_proyecto,
                        cliente=cliente,
                        ingeniero=None,
                        fecha_extra=None,
                        nombre_sitio=row['nombre_sitio'],
                        direccion=row['sitio_direccion'] or '',
                        coordenadas_gps=row['coordenadas_gps'],
                        maps_url=_build_maps_url(
                            row['sitio_maps_link'], row['op_maps_link'], row['coordenadas_gps']
                        ),
                    )

                    subject = f"[Recordatorio] Levantamiento sin asignar: {op_id} — {cliente}"

                    success, msg = await ms_auth.send_email_with_attachments(
                        access_token=app_token,
                        from_email=sender_email,
                        subject=subject,
                        body=html_body,
                        recipients=[row['jefe_email']],
                        importance="high"
                    )

                    if success:
                        _sent_reminders[key] = now
                        logger.info(
                            "[LEV_REMINDER] Recordatorio enviado: lev=%s op=%s jefe=%s",
                            lev_id, op_id, row['jefe_email']
                        )
                    else:
                        logger.error("[LEV_REMINDER] Error enviando recordatorio lev=%s: %s", lev_id, msg)

        except asyncpg.PostgresError as e:
            logger.error("[LEV_REMINDER] Error de BD en tarea de recordatorios: %s", e)
        except TASK_ROW_RUNTIME_ERRORS as e:
            logger.error("[LEV_REMINDER] Error inesperado en tarea de recordatorios: %s", e, exc_info=True)


async def check_recordatorios_levantamientos_periodically(interval_seconds: int = 3600):
    """
    Tarea periódica (cada hora) que envía recordatorios al ingeniero responsable
    de levantamientos en dos situaciones:

    1. PENDIENTE_SIN_AGENDAR: lleva > 24h en estado 'pendiente' con responsable asignado
       y sin fecha de visita programada.
    2. AGENDADO_VENCIDO: fecha_visita_programada ya pasó hace > 1 día y sigue 'agendado'.

    Anti-spam en memoria: no reenvía al mismo levantamiento en < 24h por tipo.
    Se reinicia con el proceso (aceptable dado el intervalo de 1 hora).
    """
    logger.info("[LEV_RECORDATORIO] Tarea inicializada (intervalo: %sh)", interval_seconds // 3600)

    # { "tipo:str(id_levantamiento)": datetime_ultimo_envio }
    _enviados: dict = {}

    while True:
        await asyncio.sleep(interval_seconds)
        try:
            from core.database import get_db_pool
            from core.microsoft import MicrosoftAuth

            pool = await get_db_pool()
            ms_auth = MicrosoftAuth()

            async with pool.acquire() as conn:
                # Remitente DEFAULT
                sender_email = await tasks_db.get_default_sender_email(conn)
                if not sender_email:
                    logger.error("[LEV_RECORDATORIO] Sin remitente DEFAULT en tb_correos_notificaciones")
                    continue

                # Token de aplicación
                app_token = await ms_auth.get_application_token()
                if not app_token:
                    logger.error("[LEV_RECORDATORIO] No se pudo obtener token de aplicacion")
                    continue

                # Query unificada: pendientes sin agendar + agendados vencidos
                rows = await tasks_db.get_levantamientos_recordatorios(conn)

                if not rows:
                    logger.debug("[LEV_RECORDATORIO] Sin levantamientos que requieran recordatorio")
                    continue

                now = now_mx()
                # Limpiar anti-spam > 48h
                cutoff = now - timedelta(hours=48)
                _enviados = {k: v for k, v in _enviados.items() if v > cutoff}

                for row in rows:
                    tipo = row["tipo_recordatorio"]
                    lev_id = str(row["id_levantamiento"])
                    key = f"{tipo}:{lev_id}"

                    last = _enviados.get(key)
                    if last and (now - last) < timedelta(hours=24):
                        continue

                    op_id = row["op_id_estandar"] or ""
                    cliente = row["cliente_nombre"] or ""
                    proyecto = row["nombre_proyecto"] or row["titulo_proyecto"] or "Sin nombre"
                    responsable = row["responsable_nombre"] or ""
                    to_email = row["responsable_email"]
                    maps_url = _build_maps_url(
                        row["sitio_maps_link"], row["op_maps_link"], row["coordenadas_gps"]
                    )

                    if tipo == "pendiente_sin_agendar":
                        asunto = f"[Recordatorio] Levantamiento pendiente sin agendar: {op_id}"
                        html_body = _lev_tpl.render(
                            tipo="pendiente_sin_agendar",
                            destinatario=responsable,
                            op_id=op_id,
                            proyecto=proyecto,
                            cliente=cliente,
                            ingeniero=None,
                            fecha_extra=None,
                            nombre_sitio=row["nombre_sitio"],
                            direccion=row["sitio_direccion"] or "",
                            coordenadas_gps=row["coordenadas_gps"],
                            maps_url=maps_url,
                        )
                    else:
                        fecha_str = (
                            row["fecha_programada"].strftime("%d/%m/%Y %H:%M")
                            if row["fecha_programada"] else "N/A"
                        )
                        asunto = f"[Recordatorio] Levantamiento agendado vencido: {op_id}"
                        html_body = _lev_tpl.render(
                            tipo="agendado_vencido",
                            destinatario=responsable,
                            op_id=op_id,
                            proyecto=proyecto,
                            cliente=cliente,
                            ingeniero=None,
                            fecha_extra=fecha_str,
                            nombre_sitio=row["nombre_sitio"],
                            direccion=row["sitio_direccion"] or "",
                            coordenadas_gps=row["coordenadas_gps"],
                            maps_url=maps_url,
                        )

                    success, msg = await ms_auth.send_email_with_attachments(
                        access_token=app_token,
                        from_email=sender_email,
                        subject=asunto,
                        body=html_body,
                        recipients=[to_email],
                        importance="high",
                    )

                    if success:
                        _enviados[key] = now
                        logger.info(
                            "[LEV_RECORDATORIO] Enviado tipo=%s lev=%s a %s", tipo, lev_id, to_email
                        )
                    else:
                        logger.error(
                            "[LEV_RECORDATORIO] Error enviando tipo=%s lev=%s: %s", tipo, lev_id, msg
                        )

        except asyncpg.PostgresError as e:
            logger.error("[LEV_RECORDATORIO] Error de BD: %s", e)
        except TASK_ROW_RUNTIME_ERRORS as e:
            logger.error("[LEV_RECORDATORIO] Error inesperado: %s", e, exc_info=True)


async def send_reporte_desarrollo_ceo_periodically():
    """
    Tarea que envía el reporte de desarrollo semanal al CEO cada viernes a las 6:00 pm
    hora de Mexico. Calcula el tiempo de espera dinamicamente y luego repite semanal.
    """
    def _segundos_hasta_viernes_6pm() -> float:
        now = now_mx()
        dias_hasta_viernes = (4 - now.weekday()) % 7
        if dias_hasta_viernes == 0 and now.hour >= 18:
            dias_hasta_viernes = 7
        target = now.replace(hour=18, minute=0, second=0, microsecond=0)
        if dias_hasta_viernes > 0:
            target += timedelta(days=dias_hasta_viernes)
        return max((target - now).total_seconds(), 0)

    logger.info("[CEO_REPORT] Tarea inicializada")

    while True:
        espera = _segundos_hasta_viernes_6pm()
        logger.info("[CEO_REPORT] Proximo envio en %.1f horas", espera / 3600)
        await asyncio.sleep(espera)

        try:
            from core.database import get_db_pool
            from core.microsoft import MicrosoftAuth
            from core.config_service import ConfigService
            from core.weekly_report.service import generar_y_enviar_reporte_ceo, parse_ceo_recipients

            pool = await get_db_pool()
            ms_auth = MicrosoftAuth()

            async with pool.acquire() as conn:
                activo_raw = await ConfigService.get_global_config(
                    conn, "reporte_desarrollo_ceo_activo", "true", str
                )
                ceo_emails_raw = await ConfigService.get_global_config(
                    conn, "reporte_desarrollo_ceo_email", "", str
                )
                ceo_recipients = parse_ceo_recipients(ceo_emails_raw)
                sender_email = await tasks_db.get_default_sender_email(conn)

            if activo_raw.lower() != "true":
                logger.info("[CEO_REPORT] Envio automatico desactivado — omitiendo")
            elif not ceo_recipients:
                logger.warning(
                    "[CEO_REPORT] Sin destinatarios validos configurados — agregar en Admin > Correos"
                )
            elif not sender_email:
                logger.error("[CEO_REPORT] Sin remitente DEFAULT en tb_correos_notificaciones")
            else:
                await generar_y_enviar_reporte_ceo(
                    ms_auth=ms_auth,
                    sender_email=sender_email,
                    ceo_recipients=ceo_recipients,
                )

        except asyncpg.PostgresError as e:
            logger.error("[CEO_REPORT] Error de BD: %s", e)
        except TASK_RUNTIME_ERRORS as e:
            logger.error("[CEO_REPORT] Error inesperado: %s", e, exc_info=True)

        # Esperar 1 hora antes de recalcular (evita doble ejecucion en el mismo viernes)
        await asyncio.sleep(3600)


async def refresh_tipo_cambio_periodically(interval_seconds: int = 3600):
    """
    Tarea en segundo plano que refresca el tipo de cambio USD/MXN desde Banxico.
    Corre cada hora. Solo consulta la API si la tasa del dia actual no existe en BD.
    Banxico publica el FIX alrededor de las 12:00 PM hora Mexico — el primer ciclo
    exitoso despues de esa hora persiste la tasa del dia.
    """
    logger.info("[TIPO_CAMBIO] Tarea periodica inicializada (intervalo: %sh)", interval_seconds // 3600)

    while True:
        await asyncio.sleep(interval_seconds)
        try:
            from core.database import get_db_pool
            from core.tipo_cambio.service import TipoCambioService
            from core.config import settings

            if not settings.BANXICO_TOKEN:
                logger.debug("[TIPO_CAMBIO] BANXICO_TOKEN no configurado — omitiendo ciclo")
                continue

            pool = await get_db_pool()
            async with pool.acquire() as conn:
                await TipoCambioService().startup_refresh(conn, settings.BANXICO_TOKEN)

        except asyncpg.PostgresError as e:
            logger.error("[TIPO_CAMBIO] Error de BD en tarea periodica: %s", e)
        except TASK_RUNTIME_ERRORS as e:
            logger.error("[TIPO_CAMBIO] Error inesperado en tarea periodica: %s", e)


async def check_recordatorios_oportunidad_ganada_periodically(interval_seconds: int = 3600):
    """
    Tarea periódica (cada hora) para recordatorios automáticos de oportunidades ganadas.

    Reglas:
    - Reenvío cada 48 horas mientras no exista proyecto en tb_proyectos_gate.
    - Director incluido solo en los primeros 3 recordatorios.
    - Destinatarios por rol_organizacional + propietario de la oportunidad.
    """
    logger.info("[OPP_GANADA_REMINDER] Tarea inicializada (intervalo: %sh)", interval_seconds // 3600)

    while True:
        await asyncio.sleep(interval_seconds)
        try:
            from core.database import get_db_pool
            from core.workflow.notification_service import get_notification_service

            pool = await get_db_pool()
            notif_service = get_notification_service()

            async with pool.acquire() as conn:
                ganada_id = await tasks_db.get_estatus_ganada_id(conn)
                if not ganada_id:
                    logger.warning("[OPP_GANADA_REMINDER] No se encontró estatus 'ganada' en catálogo")
                    continue

                # Cerrar ciclos donde ya existe proyecto
                await tasks_db.close_completed_opportunity_won_reminders(conn, ganada_id)

                # Claim de lotes para evitar doble envío entre workers
                due_rows = await tasks_db.claim_due_opportunity_won_reminders(conn, ganada_id)

                if not due_rows:
                    logger.debug("[OPP_GANADA_REMINDER] Sin recordatorios pendientes")
                    continue

                for row in due_rows:
                    id_oportunidad = row["id_oportunidad"]
                    reminder_count = int(row["recordatorios_enviados"] or 0)

                    cobertura_completa = await tasks_db.opportunity_won_has_complete_coverage(
                        conn,
                        id_oportunidad,
                        ganada_id,
                    )
                    if cobertura_completa:
                        await tasks_db.deactivate_opportunity_won_reminder(conn, id_oportunidad)
                        continue

                    include_director = reminder_count < 3
                    reminder_number = reminder_count + 1

                    sent = await notif_service.notify_opportunity_won(
                        conn=conn,
                        id_oportunidad=id_oportunidad,
                        won_by_ctx={"user_name": "Sistema"},
                        include_director=include_director,
                        reminder_number=reminder_number,
                    )

                    if sent:
                        await tasks_db.mark_opportunity_won_reminder_sent(
                            conn,
                            id_oportunidad,
                            reminder_number,
                            include_director,
                        )
                    else:
                        await tasks_db.mark_opportunity_won_reminder_not_sent(
                            conn,
                            id_oportunidad,
                            reminder_number,
                            include_director,
                        )

        except asyncpg.PostgresError as e:
            logger.error("[OPP_GANADA_REMINDER] Error de BD: %s", e)
        except (RuntimeError, TypeError, ValueError) as e:
            logger.error("[OPP_GANADA_REMINDER] Error inesperado: %s", e, exc_info=True)


async def check_recordatorios_en_proceso_periodically(interval_seconds: int = 3600):
    """
    Tarea periódica (cada hora) que envía recordatorios al ingeniero responsable
    y al jefe de área cuando un levantamiento lleva demasiado tiempo en 'en_proceso':

    1. FECHA_VENCIDA: tiene fecha_visita_programada que ya pasó hace >24h.
    2. EN_PROCESO_LARGO: sin fecha_visita_programada, pero lleva >48h en en_proceso
       según la última transición registrada en tb_levantamientos_historial.

    Anti-spam en memoria: no reenvía al mismo levantamiento en <24h.
    """
    logger.info("[LEV_EN_PROCESO] Tarea inicializada (intervalo: %sh)", interval_seconds // 3600)
    _enviados: dict = {}

    while True:
        await asyncio.sleep(interval_seconds)
        try:
            from core.database import get_db_pool
            from core.microsoft import MicrosoftAuth

            pool = await get_db_pool()
            ms_auth = MicrosoftAuth()

            async with pool.acquire() as conn:
                sender_email = await tasks_db.get_default_sender_email(conn)
                if not sender_email:
                    logger.error("[LEV_EN_PROCESO] Sin remitente DEFAULT en tb_correos_notificaciones")
                    continue

                app_token = await ms_auth.get_application_token()
                if not app_token:
                    logger.error("[LEV_EN_PROCESO] No se pudo obtener token de aplicacion")
                    continue

                rows = await tasks_db.get_levantamientos_en_proceso_reminders(conn)

                if not rows:
                    logger.debug("[LEV_EN_PROCESO] Sin levantamientos en proceso que requieran recordatorio")
                    continue

                now = now_mx()
                cutoff = now - timedelta(hours=48)
                _enviados = {k: v for k, v in _enviados.items() if v > cutoff}

                for row in rows:
                    lev_id = str(row["id_levantamiento"])
                    key = f"en_proceso:{lev_id}"

                    last = _enviados.get(key)
                    if last and (now - last) < timedelta(hours=24):
                        continue

                    recipients = [e for e in [row["ingeniero_email"], row["jefe_email"]] if e]
                    if not recipients:
                        logger.debug("[LEV_EN_PROCESO] Sin destinatarios para lev=%s", lev_id)
                        continue

                    subtipo = row["subtipo"]
                    op_id = row["op_id_estandar"] or ""
                    cliente = row["cliente_nombre"] or ""
                    proyecto = row["nombre_proyecto"] or row["titulo_proyecto"] or "Sin nombre"
                    ingeniero = row["ingeniero_nombre"] or "Ingeniero asignado"

                    maps_url = _build_maps_url(
                        row["sitio_maps_link"], row["op_maps_link"], row["coordenadas_gps"]
                    )

                    if subtipo == "fecha_vencida":
                        fecha_str = (
                            row["fecha_programada"].strftime("%d/%m/%Y %H:%M")
                            if row["fecha_programada"] else "N/A"
                        )
                        asunto = f"[Recordatorio] Levantamiento en proceso — visita vencida: {op_id}"
                        html_body = _lev_tpl.render(
                            tipo="en_proceso_fecha",
                            destinatario=None,
                            op_id=op_id,
                            proyecto=proyecto,
                            cliente=cliente,
                            ingeniero=ingeniero,
                            fecha_extra=fecha_str,
                            nombre_sitio=row["nombre_sitio"],
                            direccion=row["sitio_direccion"] or "",
                            coordenadas_gps=row["coordenadas_gps"],
                            maps_url=maps_url,
                        )
                    else:
                        fecha_inicio = (
                            row["fecha_inicio_proceso"].strftime("%d/%m/%Y %H:%M")
                            if row["fecha_inicio_proceso"] else "N/A"
                        )
                        asunto = f"[Recordatorio] Levantamiento en proceso sin concluir: {op_id}"
                        html_body = _lev_tpl.render(
                            tipo="en_proceso_largo",
                            destinatario=None,
                            op_id=op_id,
                            proyecto=proyecto,
                            cliente=cliente,
                            ingeniero=ingeniero,
                            fecha_extra=fecha_inicio,
                            nombre_sitio=row["nombre_sitio"],
                            direccion=row["sitio_direccion"] or "",
                            coordenadas_gps=row["coordenadas_gps"],
                            maps_url=maps_url,
                        )

                    success, msg = await ms_auth.send_email_with_attachments(
                        access_token=app_token,
                        from_email=sender_email,
                        subject=asunto,
                        body=html_body,
                        recipients=recipients,
                        importance="high",
                    )

                    if success:
                        _enviados[key] = now
                        logger.info(
                            "[LEV_EN_PROCESO] Enviado subtipo=%s lev=%s a %s",
                            subtipo, lev_id, recipients,
                        )
                    else:
                        logger.error("[LEV_EN_PROCESO] Error enviando lev=%s: %s", lev_id, msg)

        except asyncpg.PostgresError as e:
            logger.error("[LEV_EN_PROCESO] Error de BD: %s", e)
        except TASK_ROW_RUNTIME_ERRORS as e:
            logger.error("[LEV_EN_PROCESO] Error inesperado: %s", e, exc_info=True)


async def check_recordatorios_completado_periodically(interval_seconds: int = 3600):
    """
    Tarea periódica (cada hora) que envía recordatorios al ingeniero responsable
    y al jefe de área cuando un levantamiento está en 'completado' y no ha sido
    marcado como 'entregado'.

    El mensaje indica que si ya se compartió la evidencia por correo, solo falta
    marcarlo como Entregado en el sistema.

    Anti-spam en memoria: reenvía cada 24h hasta que el estatus cambie a entregado.
    """
    logger.info("[LEV_COMPLETADO] Tarea inicializada (intervalo: %sh)", interval_seconds // 3600)
    _enviados: dict = {}

    while True:
        await asyncio.sleep(interval_seconds)
        try:
            from core.database import get_db_pool
            from core.microsoft import MicrosoftAuth

            pool = await get_db_pool()
            ms_auth = MicrosoftAuth()

            async with pool.acquire() as conn:
                sender_email = await tasks_db.get_default_sender_email(conn)
                if not sender_email:
                    logger.error("[LEV_COMPLETADO] Sin remitente DEFAULT en tb_correos_notificaciones")
                    continue

                app_token = await ms_auth.get_application_token()
                if not app_token:
                    logger.error("[LEV_COMPLETADO] No se pudo obtener token de aplicacion")
                    continue

                rows = await tasks_db.get_completed_levantamientos_reminders(conn)

                if not rows:
                    logger.debug("[LEV_COMPLETADO] Sin levantamientos completados pendientes de entrega")
                    continue

                now = now_mx()
                cutoff = now - timedelta(hours=48)
                _enviados = {k: v for k, v in _enviados.items() if v > cutoff}

                for row in rows:
                    lev_id = str(row["id_levantamiento"])
                    key = f"completado:{lev_id}"

                    last = _enviados.get(key)
                    if last and (now - last) < timedelta(hours=24):
                        continue

                    recipients = [e for e in [row["ingeniero_email"], row["jefe_email"]] if e]
                    if not recipients:
                        logger.debug("[LEV_COMPLETADO] Sin destinatarios para lev=%s", lev_id)
                        continue

                    op_id = row["op_id_estandar"] or ""
                    cliente = row["cliente_nombre"] or ""
                    proyecto = row["nombre_proyecto"] or row["titulo_proyecto"] or "Sin nombre"
                    ingeniero = row["ingeniero_nombre"] or "Ingeniero asignado"
                    fecha_completado = (
                        row["fecha_completado"].strftime("%d/%m/%Y %H:%M")
                        if row["fecha_completado"] else "N/A"
                    )

                    html_body = _lev_tpl.render(
                        tipo="completado",
                        destinatario=None,
                        op_id=op_id,
                        proyecto=proyecto,
                        cliente=cliente,
                        ingeniero=ingeniero,
                        fecha_extra=fecha_completado,
                        nombre_sitio=row["nombre_sitio"],
                        direccion=row["sitio_direccion"] or "",
                        coordenadas_gps=row["coordenadas_gps"],
                        maps_url=_build_maps_url(
                            row["sitio_maps_link"], row["op_maps_link"], row["coordenadas_gps"]
                        ),
                    )

                    success, msg = await ms_auth.send_email_with_attachments(
                        access_token=app_token,
                        from_email=sender_email,
                        subject=f"[Recordatorio] Levantamiento completado sin entregar: {op_id}",
                        body=html_body,
                        recipients=recipients,
                        importance="normal",
                    )

                    if success:
                        _enviados[key] = now
                        logger.info("[LEV_COMPLETADO] Enviado lev=%s a %s", lev_id, recipients)
                    else:
                        logger.error("[LEV_COMPLETADO] Error enviando lev=%s: %s", lev_id, msg)

        except asyncpg.PostgresError as e:
            logger.error("[LEV_COMPLETADO] Error de BD: %s", e)
        except TASK_ROW_RUNTIME_ERRORS as e:
            logger.error("[LEV_COMPLETADO] Error inesperado: %s", e, exc_info=True)


async def sat_jobs_worker_periodically(interval_seconds: int = 30):
    """
    Procesa jobs de descarga SAT desde el Worker service.
    El job queda persistido en BD, por lo que puede recuperarse tras redeploys o reinicios.
    """
    from modules.compras import sat_service

    logger.info("[SAT Worker] Tarea inicializada (intervalo: %ss)", interval_seconds)

    while True:
        try:
            processed = await sat_service.procesar_siguiente_job_pendiente()
            if not processed:
                await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            logger.info("[SAT Worker] Tarea cancelada")
            raise
        except asyncpg.PostgresError as e:
            logger.error("[SAT Worker] Error de BD: %s", e)
            await asyncio.sleep(interval_seconds)
        except TASK_RUNTIME_ERRORS as e:
            logger.error("[SAT Worker] Error inesperado: %s", e, exc_info=True)
            await asyncio.sleep(interval_seconds)


async def verificar_recordatorios_aprobacion_periodically(interval_seconds: int = 3600):
    """
    Tarea periódica (cada hora) que reenvía la notificación de solicitud pendiente
    al aprobador cuando llevan más de 24 h sin resolverse.
    Usa `ultima_notificacion_aprobador` en BD como anti-spam persistente.
    """
    logger.info("[VAC_RECORDATORIO] Tarea inicializada (intervalo: %sh)", interval_seconds // 3600)

    while True:
        await asyncio.sleep(interval_seconds)
        try:
            from core.database import get_db_pool
            from core.workflow.notification_service import get_notification_service

            pool = await get_db_pool()
            notif = get_notification_service()

            async with pool.acquire() as conn:
                rows = await tasks_db.get_pending_absence_approval_reminders(conn)

                if not rows:
                    logger.debug("[VAC_RECORDATORIO] Sin solicitudes pendientes que requieran recordatorio")
                    continue

                for row in rows:
                    solicitud = {
                        "id": row["id"],
                        "tipo_nombre": row["tipo_nombre"],
                        "tipo_abreviatura": row["tipo_abreviatura"],
                        "solicitante_nombre": row["solicitante_nombre"],
                        "solicitante_email": row["solicitante_email"],
                        "fecha_inicio": row["fecha_inicio"],
                        "fecha_fin": row["fecha_fin"],
                        "dias_solicitados": row["dias_solicitados"],
                        "fecha_presentarse": row["fecha_presentarse"],
                        "observaciones": row["observaciones"],
                    }
                    await notif.notify_vacation_request(conn, solicitud, row["aprobador_email"])
                    await tasks_db.mark_absence_approver_notified(conn, row["id"])
                    logger.info(
                        "[VAC_RECORDATORIO] Recordatorio enviado: sol=%s aprobador=%s",
                        row["id"], row["aprobador_email"],
                    )

        except asyncpg.PostgresError as e:
            logger.error("[VAC_RECORDATORIO] Error de BD: %s", e)
        except TASK_ROW_RUNTIME_ERRORS as e:
            logger.error("[VAC_RECORDATORIO] Error inesperado: %s", e, exc_info=True)


async def generar_festivos_anuales_periodically(interval_seconds: int = 86400):
    """
    Verifica diariamente que exista el catalogo de festivos del año actual.
    Solo genera automaticamente cuando el año no tiene ningun festivo registrado,
    y deja el calendario pendiente de validacion de RH.
    """
    logger.info("[VAC_FESTIVOS] Tarea inicializada (intervalo: %sh)", interval_seconds // 3600)

    while True:
        try:
            from core.database import get_db_pool
            from core.timezone import today_mx
            from modules.rrhh.service import ensure_festivos_anio_worker

            pool = await get_db_pool()
            async with pool.acquire() as conn:
                anio = today_mx().year
                insertados = await ensure_festivos_anio_worker(conn, anio)
                if insertados:
                    logger.info("[VAC_FESTIVOS] Festivos generados para %s: %s", anio, insertados)
                else:
                    logger.debug("[VAC_FESTIVOS] Catalogo %s sin cambios", anio)

        except asyncpg.PostgresError as e:
            logger.error("[VAC_FESTIVOS] Error de BD: %s", e)
        except TASK_RUNTIME_ERRORS as e:
            logger.error("[VAC_FESTIVOS] Error inesperado: %s", e, exc_info=True)

        await asyncio.sleep(interval_seconds)


async def verificar_periodos_por_expirar_periodically(interval_seconds: int = 86400):
    """
    Tarea diaria que detecta períodos de vacaciones por vencer y envía notificación SSE
    al empleado. Umbrales: 30, 15, 7, 1 días antes de la fecha de expiración.
    """
    logger.info("[VAC_EXPIRACION] Tarea inicializada (intervalo: %sh)", interval_seconds // 3600)

    while True:
        await asyncio.sleep(interval_seconds)
        try:
            from core.database import get_db_pool
            from core.timezone import today_mx
            from core.config_service import ConfigService
            from modules.vacaciones.logic import calcular_periodos, calcular_balance
            from modules.vacaciones.db_service import (
                get_consumos_bulk,
                try_register_worker_notification,
            )
            from core.notifications.service import get_notifications_service
            from core.workflow.notification_service import get_notification_service

            pool = await get_db_pool()
            notif_svc = get_notifications_service()
            email_svc = get_notification_service()
            UMBRALES = {30, 15, 7, 1}

            async with pool.acquire() as conn:
                hoy = today_mx()
                catalogo = await tasks_db.get_vacation_days_catalog(conn)
                meses_exp = await ConfigService.get_global_config(
                    conn, "VACACIONES_MESES_EXPIRACION", 18, int
                )

                empleados = await tasks_db.get_active_employees_with_vacation_data(conn)

                consumos_por_usuario = await get_consumos_bulk(
                    conn, [emp["id_usuario"] for emp in empleados]
                )

                for emp in empleados:
                    try:
                        periodos = calcular_periodos(
                            emp["fecha_contratacion"],
                            hoy,
                            catalogo,
                            ajuste_dias=emp["ajuste"],
                            meses_expiracion=meses_exp,
                        )
                        balance = calcular_balance(
                            periodos, consumos_por_usuario.get(emp["id_usuario"], [])
                        )

                        for periodo in balance:
                            if periodo.get("es_proximo") or periodo.get("expirado"):
                                continue
                            if periodo.get("dias_restantes", 0) <= 0:
                                continue
                            dias_exp = periodo.get("dias_para_expiracion")
                            if dias_exp not in UMBRALES:
                                continue

                            clave = (
                                f"periodo_expirar:{emp['id_usuario']}:"
                                f"{periodo['num_periodo']}:{dias_exp}"
                            )
                            registrado = await try_register_worker_notification(
                                conn,
                                clave=clave,
                                tipo="PERIODO_POR_EXPIRAR",
                                usuario_id=emp["id_usuario"],
                                num_periodo=periodo["num_periodo"],
                                fecha_objetivo=periodo["fecha_expiracion"],
                                metadata={
                                    "dias_para_expiracion": dias_exp,
                                    "dias_restantes": periodo["dias_restantes"],
                                },
                            )
                            if not registrado:
                                continue

                            notification_data = await notif_svc.create_notification(
                                conn=conn,
                                usuario_id=emp["id_usuario"],
                                tipo="VACACIONES_POR_EXPIRAR",
                                titulo=f"Período {periodo['num_periodo']} por vencer",
                                mensaje=(
                                    f"Tienes {periodo['dias_restantes']} días hábiles "
                                    f"que vencen en {dias_exp} días"
                                ),
                                modulo_origen="vacaciones",
                            )
                            await notif_svc.broadcast_to_user(conn, emp["id_usuario"], notification_data)
                            await email_svc.notify_periodo_expira(conn, dict(emp), periodo)
                            logger.info(
                                "[VAC_EXPIRACION] Notificado usuario=%s periodo=%s dias_exp=%s",
                                emp["id_usuario"], periodo["num_periodo"], dias_exp,
                            )
                    except asyncpg.PostgresError:
                        raise
                    except TASK_ROW_RUNTIME_ERRORS as e:
                        logger.error(
                            "[VAC_EXPIRACION] Error procesando empleado %s: %s", emp["id_usuario"], e
                        )

        except asyncpg.PostgresError as e:
            logger.error("[VAC_EXPIRACION] Error de BD: %s", e)
        except TASK_ROW_RUNTIME_ERRORS as e:
            logger.error("[VAC_EXPIRACION] Error inesperado: %s", e, exc_info=True)


async def verificar_solicitudes_vencidas_periodically(interval_seconds: int = 86400):
    """
    Tarea diaria que detecta solicitudes con estado='pendiente' cuya fecha_inicio
    ya paso y notifica via SSE a RRHH/Admin y al aprobador.
    """
    logger.info("[VAC_VENCIDAS] Tarea inicializada (intervalo: %sh)", interval_seconds // 3600)

    while True:
        await asyncio.sleep(interval_seconds)
        try:
            from core.database import get_db_pool
            from core.timezone import today_mx
            from core.notifications.service import get_notifications_service
            from core.workflow.notification_service import get_notification_service
            from modules.vacaciones.db_service import try_register_worker_notification

            pool = await get_db_pool()
            notif_svc = get_notifications_service()
            email_svc = get_notification_service()

            async with pool.acquire() as conn:
                hoy = today_mx()
                solicitudes = await tasks_db.get_overdue_absence_requests(conn, hoy)

                if not solicitudes:
                    logger.debug("[VAC_VENCIDAS] Sin solicitudes vencidas pendientes")
                    continue

                rh_rows = await tasks_db.get_active_rh_contacts(conn)
                rh_ids = [r["id_usuario"] for r in rh_rows]
                rh_emails = {r["email"] for r in rh_rows if r["email"]}

                for sol in solicitudes:
                    clave = f"solicitud_vencida:{sol['id']}:{hoy.isoformat()}"
                    registrado = await try_register_worker_notification(
                        conn,
                        clave=clave,
                        tipo="SOLICITUD_VENCIDA",
                        solicitud_id=sol["id"],
                        fecha_objetivo=hoy,
                        metadata={
                            "fecha_inicio": sol["fecha_inicio"].isoformat(),
                            "tipo_nombre": sol["tipo_nombre"],
                        },
                    )
                    if not registrado:
                        continue

                    mensaje = (
                        f"{sol['solicitante_nombre']} · {sol['tipo_nombre']} · "
                        f"inicio {sol['fecha_inicio'].strftime('%d/%m/%Y')}"
                    )
                    titulo = f"Solicitud vencida pendiente: {sol['tipo_nombre']}"

                    destinatarios = set(rh_ids)
                    if sol["aprobador_id"]:
                        destinatarios.add(sol["aprobador_id"])

                    for uid in destinatarios:
                        notification_data = await notif_svc.create_notification(
                            conn=conn,
                            usuario_id=uid,
                            tipo="VACACIONES_VENCIDAS",
                            titulo=titulo,
                            mensaje=mensaje,
                            modulo_origen="vacaciones",
                        )
                        await notif_svc.broadcast_to_user(conn, uid, notification_data)

                    to_emails = {sol["aprobador_email"]} if sol["aprobador_email"] else set(rh_emails)
                    cc_emails = rh_emails if sol["aprobador_email"] else set()
                    await email_svc.notify_solicitud_vencida(
                        conn,
                        dict(sol),
                        to_emails=to_emails,
                        cc_emails=cc_emails,
                    )

                    logger.info(
                        "[VAC_VENCIDAS] Solicitud vencida notificada: sol=%s destinatarios=%d",
                        sol["id"], len(destinatarios),
                    )

        except asyncpg.PostgresError as e:
            logger.error("[VAC_VENCIDAS] Error de BD: %s", e)
        except TASK_ROW_RUNTIME_ERRORS as e:
            logger.error("[VAC_VENCIDAS] Error inesperado: %s", e, exc_info=True)


async def sat_inbox_cleanup_periodically(interval_seconds: int = 604800):
    from core.database import get_db_pool

    while True:
        await asyncio.sleep(interval_seconds)
        logger.info("[SAT Cleanup] Iniciando limpieza de inbox SAT")
        pool = await get_db_pool()
        try:
            async with pool.acquire() as conn:
                rows = await tasks_db.get_sat_inbox_cleanup_urls(conn)
                if rows:
                    for row in rows:
                        logger.info("[SAT Cleanup] XML SP pendiente borrado manual: %s", row["sharepoint_url"])

                deleted = await tasks_db.delete_sat_inbox_resolved_old(conn)
                logger.info("[SAT Cleanup] Registros matcheados/descartados eliminados: %s", deleted)

                deleted_old = await tasks_db.delete_sat_inbox_pending_old(conn)
                logger.info("[SAT Cleanup] Registros pendientes antiguos eliminados: %s", deleted_old)

                await tasks_db.delete_sat_orphan_jobs_old(conn)

        except asyncpg.PostgresError as e:
            logger.error("[SAT Cleanup] Error BD en limpieza: %s", e)
        except (RuntimeError, TypeError, ValueError) as e:
            logger.error("[SAT Cleanup] Error inesperado en limpieza: %s", e, exc_info=True)
