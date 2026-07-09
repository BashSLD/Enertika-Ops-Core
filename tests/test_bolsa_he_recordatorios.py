"""
Integracion: recordatorios y resumen RH de compensatorio pendiente
(Fase 6 del plan _Planes_Activos/Planes_Anteriores_Ejecutados/2026-06-29-bolsa-horas-extra.md), sobre las
columnas de tracking de tb_he_solicitudes_compensatorio (migracion
139). Requiere BD real con rollback automatico por test.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio

from core.tasks_db_service import get_tasks_db_service

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

svc = get_tasks_db_service()


@pytest_asyncio.fixture
async def usuario_id(real_conn):
    uid = await real_conn.fetchval(
        "SELECT id_usuario FROM tb_usuarios WHERE is_active = true LIMIT 1"
    )
    if not uid:
        pytest.skip("No hay usuarios activos en la BD")
    return uid


async def _crear_solicitud(real_conn, usuario_id, *, fecha_descanso, **overrides):
    defaults = {
        "id": uuid4(),
        "minutos_solicitados": 60,
        "motivo": "Test recordatorio",
        "estatus": "pendiente",
        "fecha_solicitud": datetime.now(timezone.utc),
        "recordatorios_enviados": 0,
        "ultimo_recordatorio_at": None,
        "resumen_rh_at": None,
    }
    defaults.update(overrides)
    await real_conn.execute(
        """
        INSERT INTO tb_he_solicitudes_compensatorio (
            id, usuario_id, fecha_descanso, minutos_solicitados, motivo,
            estatus, fecha_solicitud, recordatorios_enviados,
            ultimo_recordatorio_at, resumen_rh_at
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        """,
        defaults["id"],
        usuario_id,
        fecha_descanso,
        defaults["minutos_solicitados"],
        defaults["motivo"],
        defaults["estatus"],
        defaults["fecha_solicitud"],
        defaults["recordatorios_enviados"],
        defaults["ultimo_recordatorio_at"],
        defaults["resumen_rh_at"],
    )
    return defaults["id"]


async def test_primer_recordatorio_no_aparece_antes_del_delay(real_conn, usuario_id):
    await _crear_solicitud(
        real_conn,
        usuario_id,
        fecha_descanso=date(2026, 12, 1),
        fecha_solicitud=datetime.now(timezone.utc),
    )

    rows = await svc.get_he_compensatorio_recordatorios_pendientes(
        real_conn, primer_delay_horas=24, intervalo_horas=48, max_recordatorios=3
    )

    assert rows == []


async def test_primer_recordatorio_aparece_tras_el_delay(real_conn, usuario_id):
    solicitud_id = await _crear_solicitud(
        real_conn,
        usuario_id,
        fecha_descanso=date(2026, 12, 2),
        fecha_solicitud=datetime.now(timezone.utc) - timedelta(hours=25),
    )

    rows = await svc.get_he_compensatorio_recordatorios_pendientes(
        real_conn, primer_delay_horas=24, intervalo_horas=48, max_recordatorios=3
    )

    assert solicitud_id in {r["id"] for r in rows}


async def test_recordatorio_respeta_intervalo_desde_el_ultimo_enviado(real_conn, usuario_id):
    solicitud_id = await _crear_solicitud(
        real_conn,
        usuario_id,
        fecha_descanso=date(2026, 12, 3),
        fecha_solicitud=datetime.now(timezone.utc) - timedelta(hours=100),
        recordatorios_enviados=1,
        ultimo_recordatorio_at=datetime.now(timezone.utc) - timedelta(hours=10),
    )

    rows = await svc.get_he_compensatorio_recordatorios_pendientes(
        real_conn, primer_delay_horas=24, intervalo_horas=48, max_recordatorios=3
    )

    assert solicitud_id not in {r["id"] for r in rows}


async def test_recordatorio_respeta_maximo_configurado(real_conn, usuario_id):
    solicitud_id = await _crear_solicitud(
        real_conn,
        usuario_id,
        fecha_descanso=date(2026, 12, 4),
        fecha_solicitud=datetime.now(timezone.utc) - timedelta(hours=200),
        recordatorios_enviados=3,
        ultimo_recordatorio_at=datetime.now(timezone.utc) - timedelta(hours=100),
    )

    rows = await svc.get_he_compensatorio_recordatorios_pendientes(
        real_conn, primer_delay_horas=24, intervalo_horas=48, max_recordatorios=3
    )

    assert solicitud_id not in {r["id"] for r in rows}


async def test_mark_recordatorio_enviado_incrementa_contador(real_conn, usuario_id):
    solicitud_id = await _crear_solicitud(
        real_conn,
        usuario_id,
        fecha_descanso=date(2026, 12, 5),
        fecha_solicitud=datetime.now(timezone.utc) - timedelta(hours=25),
    )

    await svc.mark_he_compensatorio_recordatorio_enviado(real_conn, solicitud_id)

    row = await real_conn.fetchrow(
        "SELECT recordatorios_enviados, ultimo_recordatorio_at FROM tb_he_solicitudes_compensatorio WHERE id=$1",
        solicitud_id,
    )
    assert row["recordatorios_enviados"] == 1
    assert row["ultimo_recordatorio_at"] is not None


async def test_resumen_rh_aparece_cuando_se_agotan_los_recordatorios(real_conn, usuario_id):
    solicitud_id = await _crear_solicitud(
        real_conn,
        usuario_id,
        fecha_descanso=date(2026, 12, 6),
        fecha_solicitud=datetime.now(timezone.utc) - timedelta(days=10),
        recordatorios_enviados=3,
        ultimo_recordatorio_at=datetime.now(timezone.utc) - timedelta(days=8),
    )

    rows = await svc.get_he_compensatorio_resumen_rh_pendiente(
        real_conn, max_recordatorios=3, intervalo_dias=7
    )

    assert solicitud_id in {r["id"] for r in rows}


async def test_resumen_rh_no_se_duplica_si_ya_se_envio_recientemente(real_conn, usuario_id):
    solicitud_id = await _crear_solicitud(
        real_conn,
        usuario_id,
        fecha_descanso=date(2026, 12, 7),
        fecha_solicitud=datetime.now(timezone.utc) - timedelta(days=10),
        recordatorios_enviados=3,
        ultimo_recordatorio_at=datetime.now(timezone.utc) - timedelta(days=8),
        resumen_rh_at=datetime.now(timezone.utc) - timedelta(days=1),
    )

    rows = await svc.get_he_compensatorio_resumen_rh_pendiente(
        real_conn, max_recordatorios=3, intervalo_dias=7
    )

    assert solicitud_id not in {r["id"] for r in rows}


async def test_mark_resumen_rh_enviado_marca_fecha(real_conn, usuario_id):
    solicitud_id = await _crear_solicitud(
        real_conn,
        usuario_id,
        fecha_descanso=date(2026, 12, 8),
        fecha_solicitud=datetime.now(timezone.utc) - timedelta(days=10),
        recordatorios_enviados=3,
        ultimo_recordatorio_at=datetime.now(timezone.utc) - timedelta(days=8),
    )

    await svc.mark_he_compensatorio_resumen_rh_enviado(real_conn, [solicitud_id])

    row = await real_conn.fetchrow(
        "SELECT resumen_rh_at FROM tb_he_solicitudes_compensatorio WHERE id=$1", solicitud_id
    )
    assert row["resumen_rh_at"] is not None
