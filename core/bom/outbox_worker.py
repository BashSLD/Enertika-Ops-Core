"""Consumidor durable del outbox BOM.

Cada entrega se reclama con lease mediante SKIP LOCKED. El claim se confirma antes
de cualquier llamada externa y la finalizacion usa CAS por ``worker_id``.
"""

import asyncio
from html import escape
import json
import logging
import os
import socket
from uuid import UUID, uuid4

import asyncpg
import httpx

from core.config_service import ConfigService
from core.database import get_db_pool
from core.notifications.service import get_notifications_service
from core.workflow.notification_service import NotificationService

logger = logging.getLogger("BOM.OutboxWorker")

_MAX_INTENTOS = 8
_LOTE_DEFAULT = 20
_LEASE_SEGUNDOS = 120
_INTERVALO_DEFAULT = 15


def _titulo_evento(tipo_evento: str, payload: dict) -> str:
    identidad = payload.get("paquete_codigo") or payload.get("codigo") or "BOM"
    evento = tipo_evento.replace("_", " ").capitalize()
    return f"{identidad}: {evento}"


def _payload_dict(entrega: dict) -> dict:
    """asyncpg no decodifica jsonb a dict por defecto (sin set_type_codec
    registrado en core/database.py); llega como string JSON crudo."""
    payload = entrega.get("payload")
    if not payload:
        return {}
    if isinstance(payload, str):
        return json.loads(payload)
    return dict(payload)


def _mensaje_evento(tipo_evento: str, payload: dict) -> str:
    estado = payload.get("estado_nuevo") or payload.get("estatus")
    version = payload.get("version") or payload.get("version_nueva")
    detalles = []
    if version is not None:
        detalles.append(f"version {version}")
    if estado:
        detalles.append(f"estado {estado}")
    sufijo = f" ({', '.join(detalles)})" if detalles else ""
    return f"Se registro el evento {tipo_evento.replace('_', ' ').lower()}{sufijo}."


async def _recuperar_leases(conn, max_intentos: int) -> None:
    rows = await conn.fetch(
        """
        UPDATE tb_bom_evento_entregas
        SET estatus = CASE
                WHEN intentos >= $1 THEN 'AGOTADO'
                ELSE 'REINTENTO'
            END,
            disponible_en = CASE
                WHEN intentos >= $1 THEN disponible_en
                ELSE NOW() + INTERVAL '30 seconds'
            END,
            lease_hasta = NULL,
            worker_id = NULL,
            ultimo_error = COALESCE(
                ultimo_error,
                'Lease vencido; entrega recuperada'
            ),
            updated_at = NOW()
        WHERE estatus = 'PROCESANDO'
          AND lease_hasta < NOW()
        RETURNING id_evento
        """,
        max_intentos,
    )
    await _actualizar_estados_eventos(
        conn, [row["id_evento"] for row in rows]
    )


async def _reclamar_lote(
    conn, worker_id: str, limite: int, max_intentos: int,
    lease_segundos: int = _LEASE_SEGUNDOS,
) -> list[dict]:
    async with conn.transaction():
        await _recuperar_leases(conn, max_intentos)
        rows = await conn.fetch(
            """
            WITH candidatas AS (
                SELECT id_entrega
                FROM tb_bom_evento_entregas
                WHERE estatus IN ('PENDIENTE', 'REINTENTO')
                  AND disponible_en <= NOW()
                  AND intentos < $3
                ORDER BY disponible_en, id_entrega
                FOR UPDATE SKIP LOCKED
                LIMIT $2
            )
            UPDATE tb_bom_evento_entregas entrega
            SET estatus = 'PROCESANDO',
                intentos = entrega.intentos + 1,
                lease_hasta = NOW() + ($4::INTEGER * INTERVAL '1 second'),
                worker_id = $1,
                updated_at = NOW()
            FROM candidatas, tb_bom_eventos_outbox evento
            WHERE entrega.id_entrega = candidatas.id_entrega
              AND evento.id_evento = entrega.id_evento
            RETURNING entrega.*, evento.tipo_evento, evento.id_proyecto,
                      evento.id_paquete, evento.id_bom, evento.id_documento,
                      evento.url_destino
            """,
            worker_id, limite, max_intentos, lease_segundos,
        )
        await _actualizar_estados_eventos(
            conn, [row["id_evento"] for row in rows]
        )
        return [dict(row) for row in rows]


async def _entregar_interna(conn, entrega: dict) -> None:
    payload = _payload_dict(entrega)
    titulo = _titulo_evento(entrega["tipo_evento"], payload)
    mensaje = _mensaje_evento(entrega["tipo_evento"], payload)
    row = await conn.fetchrow(
        """
        INSERT INTO tb_notificaciones (
            usuario_id, tipo, titulo, mensaje, id_oportunidad,
            id_evento_bom, modulo_origen, url_destino,
            id_proyecto_bom, id_paquete_bom, id_bom
        )
        VALUES ($1, 'CAMBIO_ESTATUS', $2, $3, NULL, $4, 'bom', $5, $6, $7, $8)
        ON CONFLICT (usuario_id, id_evento_bom) WHERE id_evento_bom IS NOT NULL
        DO UPDATE SET titulo = EXCLUDED.titulo
        RETURNING id, created_at
        """,
        entrega["destinatario_id"], titulo, mensaje, entrega["id_evento"],
        entrega.get("url_destino"), entrega["id_proyecto"],
        entrega.get("id_paquete"), entrega.get("id_bom"),
    )
    notification_data = {
        "id": str(row["id"]),
        "type": "CAMBIO_ESTATUS",
        "title": titulo,
        "message": mensaje,
        "module": "bom",
        "url": entrega.get("url_destino"),
        "created_at": row["created_at"].isoformat(),
    }
    await get_notifications_service().broadcast_to_user(
        conn, entrega["destinatario_id"], notification_data
    )


async def _entregar_correo(conn, entrega: dict, servicio: NotificationService) -> None:
    destino = entrega.get("direccion_destino")
    if not destino:
        raise ValueError("La entrega de correo no tiene direccion de destino")
    payload = _payload_dict(entrega)
    titulo = _titulo_evento(entrega["tipo_evento"], payload)
    mensaje = _mensaje_evento(entrega["tipo_evento"], payload)
    url = entrega.get("url_destino") or ""
    html = (
        f"<p>{escape(mensaje)}</p>"
        f"<p><a href=\"{escape(url, quote=True)}\">Abrir paquete BOM</a></p>"
    )
    enviado = await servicio.send_simple_notification(conn, destino, titulo, html, "BOM")
    if not enviado:
        raise RuntimeError("Microsoft Graph no confirmo el envio")


async def _actualizar_estados_eventos(conn, ids_evento: list[UUID]) -> None:
    ids = sorted(set(ids_evento), key=str)
    if not ids:
        return
    await conn.fetch(
        """
        SELECT id_evento
        FROM tb_bom_eventos_outbox
        WHERE id_evento = ANY($1::UUID[])
        ORDER BY id_evento
        FOR UPDATE
        """,
        ids,
    )
    await conn.execute(
        """
        UPDATE tb_bom_eventos_outbox evento
        SET estatus = resumen.estatus,
            intentos = resumen.intentos,
            disponible_en = COALESCE(resumen.disponible_en, evento.disponible_en),
            procesado_en = CASE WHEN resumen.estatus = 'ENVIADO' THEN NOW()
                                ELSE evento.procesado_en END,
            ultimo_error = resumen.ultimo_error
        FROM (
            SELECT
                id_evento,
                CASE
                    WHEN COUNT(*) = 0 THEN 'ENVIADO'
                    WHEN BOOL_OR(estatus = 'PROCESANDO') THEN 'PROCESANDO'
                    WHEN BOOL_OR(estatus IN ('PENDIENTE', 'REINTENTO')) THEN 'REINTENTO'
                    WHEN BOOL_OR(estatus = 'AGOTADO') THEN 'AGOTADO'
                    ELSE 'ENVIADO'
                END AS estatus,
                COALESCE(MAX(intentos), 0) AS intentos,
                MIN(disponible_en) FILTER (
                    WHERE estatus IN ('PENDIENTE', 'REINTENTO')
                ) AS disponible_en,
                MAX(ultimo_error) FILTER (WHERE ultimo_error IS NOT NULL) AS ultimo_error
            FROM tb_bom_evento_entregas
            WHERE id_evento = ANY($1::UUID[])
            GROUP BY id_evento
        ) resumen
        WHERE evento.id_evento = resumen.id_evento
        """,
        ids,
    )


async def _actualizar_estado_evento(conn, id_evento: UUID) -> None:
    await _actualizar_estados_eventos(conn, [id_evento])


async def _finalizar_entrega(
    conn, entrega: dict, worker_id: str, error: str | None,
    max_intentos: int,
) -> bool:
    intentos = int(entrega["intentos"])
    if error is None:
        nuevo_estatus = "ENVIADO"
        demora = 0
    elif intentos >= max_intentos:
        nuevo_estatus = "AGOTADO"
        demora = 0
    else:
        nuevo_estatus = "REINTENTO"
        demora = min(30 * (2 ** max(intentos - 1, 0)), 3600)
    async with conn.transaction():
        updated = await conn.fetchval(
            """
            UPDATE tb_bom_evento_entregas
            SET estatus = $4::VARCHAR,
                disponible_en = CASE WHEN $4::VARCHAR = 'REINTENTO'
                    THEN NOW() + ($5::INTEGER * INTERVAL '1 second')
                    ELSE disponible_en END,
                enviado_en = CASE WHEN $4::VARCHAR = 'ENVIADO' THEN NOW() ELSE enviado_en END,
                lease_hasta = NULL,
                worker_id = NULL,
                ultimo_error = $6,
                updated_at = NOW()
            WHERE id_entrega = $1
              AND estatus = 'PROCESANDO'
              AND worker_id = $2
              AND intentos = $3
            RETURNING id_entrega
            """,
            entrega["id_entrega"], worker_id, intentos, nuevo_estatus,
            demora, error[:2000] if error else None,
        )
        if updated:
            await _actualizar_estado_evento(conn, entrega["id_evento"])
        return bool(updated)


async def procesar_bom_outbox_lote(
    conn, *, worker_id: str, limite: int = _LOTE_DEFAULT,
    max_intentos: int = _MAX_INTENTOS,
    lease_segundos: int = _LEASE_SEGUNDOS,
) -> dict:
    """Procesa un lote y retorna métricas compactas para logs/pruebas."""
    entregas = await _reclamar_lote(
        conn, worker_id, limite, max_intentos, lease_segundos
    )
    metricas = {"reclamadas": len(entregas), "enviadas": 0, "reintentos": 0, "agotadas": 0}
    servicio_notificaciones = (
        NotificationService()
        if any(entrega["canal"] == "CORREO" for entrega in entregas)
        else None
    )
    for entrega in entregas:
        error = None
        try:
            if entrega["canal"] == "INTERNA":
                await _entregar_interna(conn, entrega)
            elif entrega["canal"] == "CORREO":
                await _entregar_correo(conn, entrega, servicio_notificaciones)
            else:
                raise ValueError(f"Canal de outbox no soportado: {entrega['canal']}")
        except (asyncpg.PostgresError, httpx.HTTPError, OSError, RuntimeError, ValueError) as exc:
            error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "Entrega BOM fallida: entrega=%s canal=%s intento=%s error=%s",
                entrega["id_entrega"], entrega["canal"], entrega["intentos"], error,
            )
        await _finalizar_entrega(conn, entrega, worker_id, error, max_intentos)
        if error is None:
            metricas["enviadas"] += 1
        elif int(entrega["intentos"]) >= max_intentos:
            metricas["agotadas"] += 1
        else:
            metricas["reintentos"] += 1

    await conn.execute(
        """
        UPDATE tb_bom_eventos_outbox evento
        SET estatus = 'ENVIADO', procesado_en = NOW()
        WHERE evento.estatus IN ('PENDIENTE', 'REINTENTO')
          AND NOT EXISTS (
              SELECT 1 FROM tb_bom_evento_entregas entrega
              WHERE entrega.id_evento = evento.id_evento
          )
        """
    )
    return metricas


async def obtener_metricas_bom_outbox(conn) -> dict:
    """Estado durable de la cola para alertas y diagnóstico operativo."""
    row = await conn.fetchrow(
        """
        SELECT
            COUNT(*) FILTER (
                WHERE estatus IN ('PENDIENTE', 'REINTENTO')
            ) AS pendientes,
            COUNT(*) FILTER (WHERE estatus = 'PROCESANDO') AS procesando,
            COUNT(*) FILTER (WHERE estatus = 'AGOTADO') AS agotadas,
            COUNT(*) FILTER (
                WHERE estatus IN ('PENDIENTE', 'REINTENTO')
                  AND disponible_en < NOW() - INTERVAL '5 minutes'
            ) AS atrasadas,
            EXTRACT(EPOCH FROM (
                NOW() - MIN(created_at) FILTER (
                    WHERE estatus IN ('PENDIENTE', 'REINTENTO')
                )
            ))::BIGINT AS antiguedad_maxima_segundos
        FROM tb_bom_evento_entregas
        """
    )
    return dict(row)


async def reprogramar_entrega_agotada(
    conn, id_entrega: UUID, actor_id: UUID, motivo: str,
) -> dict:
    """Replay manual auditable de una entrega agotada, sin duplicar el evento."""
    motivo_limpio = (motivo or "").strip()
    if not motivo_limpio:
        raise ValueError("El motivo del replay es obligatorio")
    async with conn.transaction():
        row = await conn.fetchrow(
            """
            UPDATE tb_bom_evento_entregas
            SET estatus = 'REINTENTO',
                intentos = 0,
                disponible_en = NOW(),
                lease_hasta = NULL,
                worker_id = NULL,
                ultimo_error = NULL,
                replay_count = replay_count + 1,
                ultimo_replay_por = $2,
                ultimo_replay_en = NOW(),
                ultimo_replay_motivo = $3,
                updated_at = NOW()
            WHERE id_entrega = $1
              AND estatus = 'AGOTADO'
            RETURNING *
            """,
            id_entrega, actor_id, motivo_limpio,
        )
        if not row:
            raise ValueError("La entrega no existe o no está agotada")
        await _actualizar_estado_evento(conn, row["id_evento"])
    return dict(row)


async def procesar_bom_outbox_periodically() -> None:
    worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid4()}"
    while True:
        try:
            pool = await get_db_pool()
            async with pool.acquire() as conn:
                configs = await ConfigService.get_global_configs_bulk(conn, {
                    "bom.outbox_intervalo_segundos": (_INTERVALO_DEFAULT, int),
                    "bom.outbox_lote": (_LOTE_DEFAULT, int),
                    "bom.outbox_max_intentos": (_MAX_INTENTOS, int),
                    "bom.outbox_lease_segundos": (_LEASE_SEGUNDOS, int),
                })
                intervalo = configs["bom.outbox_intervalo_segundos"]
                limite = configs["bom.outbox_lote"]
                max_intentos = configs["bom.outbox_max_intentos"]
                lease_segundos = configs["bom.outbox_lease_segundos"]
                metricas = await procesar_bom_outbox_lote(
                    conn,
                    worker_id=worker_id,
                    limite=max(1, min(limite, 100)),
                    max_intentos=max(1, min(max_intentos, 50)),
                    lease_segundos=max(30, min(lease_segundos, 3600)),
                )
                cola = await obtener_metricas_bom_outbox(conn)
            if metricas["reclamadas"]:
                logger.info("BOM outbox procesado: %s", metricas)
            if cola["atrasadas"] or cola["agotadas"]:
                logger.warning("BOM outbox requiere atención: %s", cola)
            await asyncio.sleep(max(1, intervalo))
        except asyncio.CancelledError:
            logger.info("Consumidor BOM outbox detenido")
            raise
        except (asyncpg.PostgresError, OSError, RuntimeError, ValueError) as exc:
            logger.warning("Consumidor BOM outbox en reintento: %s", exc, exc_info=True)
            await asyncio.sleep(_INTERVALO_DEFAULT)
