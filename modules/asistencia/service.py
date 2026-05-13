from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import UUID

import asyncpg
import httpx

from core.config_service import ConfigService
from core.database import get_db_pool
from core.timezone import now_mx, today_mx
from modules.asistencia import db_service as db
from modules.asistencia.biotime_client import BioTimeClient
from modules.asistencia.constants import BIOTIME_CONFIG_KEYS
from modules.asistencia.logic import (
    AttendanceCheck,
    MX_TZ,
    ScheduleConfig,
    build_labor_window,
    calcular_resumen_dia,
    ensure_mx,
)

logger = logging.getLogger("asistencia.service")


def parse_biotime_check_time(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return ensure_mx(value)
    raw = str(value).strip()
    if not raw:
        return None
    normalized = raw.replace("T", " ")
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        try:
            parsed = datetime.strptime(normalized[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    return ensure_mx(parsed)


async def sync_biotime_once(conn, *, force: bool = False) -> dict:
    activo = await ConfigService.get_global_config(
        conn, BIOTIME_CONFIG_KEYS["sync_activo"], "false", bool
    )
    if not activo and not force:
        return {"status": "disabled", "message": "Sincronizacion BioTime desactivada"}

    base_url = await ConfigService.get_global_config(conn, BIOTIME_CONFIG_KEYS["base_url"], "", str)
    access_key = await ConfigService.get_global_config(conn, BIOTIME_CONFIG_KEYS["access_key"], "", str)
    page_size = await ConfigService.get_global_config(conn, BIOTIME_CONFIG_KEYS["page_size"], 1000, int)
    lookback_hours = await ConfigService.get_global_config(
        conn, BIOTIME_CONFIG_KEYS["lookback_hours"], 48, int
    )
    timeout_seconds = await ConfigService.get_global_config(
        conn, BIOTIME_CONFIG_KEYS["timeout_seconds"], 30, int
    )
    recalc_days = await ConfigService.get_global_config(
        conn, BIOTIME_CONFIG_KEYS["recalc_days"], 7, int
    )

    last_id = await db.get_last_transaction_id(conn)
    window_end = now_mx()
    window_start = window_end - timedelta(hours=max(1, min(lookback_hours, 31 * 24)))
    run_id = await db.create_sync_run(
        conn,
        from_transaction_id=last_id,
        window_start=window_start,
        window_end=window_end,
    )

    try:
        client = BioTimeClient(base_url, access_key, timeout_seconds=timeout_seconds)
        items = await _fetch_transaction_pages(
            client,
            window_start=window_start,
            window_end=window_end,
            last_id=last_id,
            page_size=page_size,
        )
        normalized = await _normalize_transactions(conn, items)
        inserted = await db.insert_checks_batch(conn, normalized)
        affected_targets = _targets_from_inserted(inserted)

        if affected_targets:
            await recalcular_asistencia(conn, affected_targets)
        if recalc_days > 0:
            await recalcular_asistencia_reciente(conn, days=recalc_days)

        to_id = _max_transaction_id(normalized) or last_id
        await db.finish_sync_run(
            conn,
            run_id=run_id,
            status="success",
            to_transaction_id=to_id,
            records_read=len(items),
            records_inserted=len(inserted),
            records_skipped=max(0, len(normalized) - len(inserted)),
        )
        return {
            "status": "success",
            "records_read": len(items),
            "records_inserted": len(inserted),
            "records_skipped": max(0, len(normalized) - len(inserted)),
            "affected_targets": len(affected_targets),
        }
    except (httpx.HTTPError, ValueError, TypeError, RuntimeError) as exc:
        await db.finish_sync_run(
            conn,
            run_id=run_id,
            status="error",
            records_read=0,
            error_message=str(exc)[:1000],
        )
        raise


async def probar_conexion_biotime(
    *,
    base_url: str,
    access_key: str,
    timeout_seconds: int = 30,
) -> dict:
    window_end = now_mx()
    window_start = window_end - timedelta(days=1)
    client = BioTimeClient(base_url, access_key, timeout_seconds=timeout_seconds)
    items = await client.fetch_transactions(
        starttime=window_start,
        endtime=window_end,
        number=1,
    )
    return {
        "status": "success",
        "records_read": len(items),
        "window_start": window_start,
        "window_end": window_end,
    }


async def _normalize_transactions(conn, items: list[dict[str, Any]]) -> list[dict]:
    emp_codes = sorted({
        str(_first_value(item, "pin", "emp_code", "badgenumber", "employee_code") or "").strip()
        for item in items
        if _first_value(item, "pin", "emp_code", "badgenumber", "employee_code")
    })
    employee_map = await db.get_employee_map(conn, emp_codes)
    normalized: list[dict] = []

    for item in items:
        emp_code = str(_first_value(item, "pin", "emp_code", "badgenumber", "employee_code") or "").strip()
        check_time = parse_biotime_check_time(_first_value(item, "checktime", "punch_time", "check_time"))
        if not emp_code or not check_time:
            continue

        mapping = employee_map.get(emp_code, {})
        normalized.append({
            "biotime_transaction_id": _safe_int(item.get("id")),
            "biotime_emp_code": emp_code,
            "usuario_id": str(mapping["usuario_id"]) if mapping.get("usuario_id") else None,
            "check_time": check_time.isoformat(),
            "punch_state": _string_or_none(_first_value(item, "stateno", "punch_state", "state")),
            "verify_type": _string_or_none(_first_value(item, "verify", "verify_type")),
            "terminal_sn": _string_or_none(_first_value(item, "sn", "terminal_sn")),
            "terminal_alias": _string_or_none(_first_value(item, "alias", "terminal_alias")),
            "deptnumber": _string_or_none(item.get("deptnumber")),
            "deptname": _string_or_none(item.get("deptname")),
            "raw_payload": item,
        })
    return normalized


def _first_value(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = item.get(key)
        if value is not None and value != "":
            return value
    return None


async def _fetch_transaction_pages(
    client: BioTimeClient,
    *,
    window_start: datetime,
    window_end: datetime,
    last_id: int | None,
    page_size: int,
) -> list[dict[str, Any]]:
    all_items: list[dict[str, Any]] = []
    current_id = last_id
    safe_page_size = max(1, min(page_size, 2000))

    for _ in range(20):
        page = await client.fetch_transactions(
            starttime=window_start,
            endtime=window_end,
            last_id=current_id,
            number=safe_page_size,
        )
        if not page:
            break
        all_items.extend(page)
        page_max_id = _max_item_id(page)
        if page_max_id is None or page_max_id == current_id or len(page) < safe_page_size:
            break
        current_id = page_max_id

    return all_items


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _safe_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _max_item_id(items: list[dict[str, Any]]) -> int | None:
    values = [_safe_int(item.get("id")) for item in items]
    valid_values = [value for value in values if value is not None]
    return max(valid_values) if valid_values else None


def _max_transaction_id(rows: list[dict]) -> int | None:
    values = [row["biotime_transaction_id"] for row in rows if row.get("biotime_transaction_id")]
    return max(values) if values else None


def _targets_from_inserted(inserted: list[dict]) -> list[tuple[UUID, date]]:
    targets: set[tuple[UUID, date]] = set()
    for row in inserted:
        usuario_id = row.get("usuario_id")
        check_time = row.get("check_time")
        if not usuario_id or not check_time:
            continue
        local_date = ensure_mx(check_time).date()
        targets.add((usuario_id, local_date))
        targets.add((usuario_id, local_date - timedelta(days=1)))
    return sorted(targets, key=lambda item: (str(item[0]), item[1]))


async def recalcular_asistencia_reciente(conn, *, days: int) -> int:
    usuario_ids = await db.get_active_attendance_users(conn)
    if not usuario_ids:
        return 0
    end = today_mx()
    start = end - timedelta(days=max(0, days - 1))
    targets = [
        (usuario_id, start + timedelta(days=offset))
        for usuario_id in usuario_ids
        for offset in range((end - start).days + 1)
    ]
    await recalcular_asistencia(conn, targets)
    return len(targets)


async def recalcular_asistencia(conn, targets: list[tuple[UUID, date]]) -> list[dict]:
    targets = _dedupe_targets(targets)
    if not targets:
        return []

    usuario_ids = sorted({target[0] for target in targets}, key=str)
    fecha_inicio = min(target[1] for target in targets)
    fecha_fin = max(target[1] for target in targets)

    context_rows = await db.get_attendance_contexts(conn, usuario_ids)
    schedule_by_user_day, sucursal_by_user = _build_context_maps(context_rows)
    vacaciones = await db.get_vacaciones_aprobadas(
        conn,
        usuario_ids=usuario_ids,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
    )
    festivos = await db.get_festivos_range(conn, fecha_inicio, fecha_fin)

    broad_start = datetime.combine(fecha_inicio - timedelta(days=1), time.min, tzinfo=MX_TZ)
    broad_end = datetime.combine(fecha_fin + timedelta(days=2), time.min, tzinfo=MX_TZ)
    checks = await db.get_checks_for_users_window(
        conn,
        usuario_ids=usuario_ids,
        start=broad_start,
        end=broad_end,
    )
    checks_by_user = _group_checks_by_user(checks)

    calculated_at = now_mx()
    rows_to_save: list[dict] = []
    for usuario_id, fecha_laboral in targets:
        schedule = schedule_by_user_day.get((usuario_id, fecha_laboral.weekday()))
        window = build_labor_window(fecha_laboral, schedule)
        checks_dia = [
            check for check in checks_by_user.get(usuario_id, [])
            if window.start <= ensure_mx(check.check_time) < window.end
        ]
        solicitud_id = _find_vacacion_id(vacaciones, usuario_id, fecha_laboral)
        resumen = calcular_resumen_dia(
            checks=checks_dia,
            schedule=schedule,
            tiene_vacaciones=solicitud_id is not None,
            es_feriado=fecha_laboral in festivos,
        )
        rows_to_save.append({
            "usuario_id": usuario_id,
            "sucursal_id": sucursal_by_user.get(usuario_id),
            "fecha_laboral": fecha_laboral,
            "tiene_vacaciones": solicitud_id is not None,
            "solicitud_ausencia_id": solicitud_id,
            "calculated_at": calculated_at,
            **resumen,
        })

    await db.upsert_asistencia_diaria_batch(conn, rows_to_save)
    return rows_to_save


def _dedupe_targets(targets: list[tuple[UUID, date]]) -> list[tuple[UUID, date]]:
    return sorted(set(targets), key=lambda item: (str(item[0]), item[1]))


def _build_context_maps(rows: list[dict]) -> tuple[dict[tuple[UUID, int], ScheduleConfig], dict[UUID, UUID | None]]:
    schedules: dict[tuple[UUID, int], ScheduleConfig] = {}
    sucursales: dict[UUID, UUID | None] = {}
    for row in rows:
        usuario_id = row["usuario_id"]
        sucursales.setdefault(usuario_id, row.get("sucursal_id"))
        if row.get("dia_semana") is None or row.get("horario_id") is None:
            continue
        schedules[(usuario_id, row["dia_semana"])] = ScheduleConfig(
            hora_entrada=row.get("hora_entrada"),
            hora_salida=row.get("hora_salida"),
            minutos_programados=row.get("minutos_programados") or 0,
            es_laboral=row.get("es_laboral", True),
            cruza_medianoche=row.get("cruza_medianoche", False),
            margen_entrada_antes_min=row.get("margen_entrada_antes_min") or 0,
            margen_salida_despues_min=row.get("margen_salida_despues_min") or 0,
            tolerancia_extra_min=row.get("tolerancia_extra_min") or 0,
            descuento_comida_min=row.get("descuento_comida_min") or 0,
        )
    return schedules, sucursales


def _group_checks_by_user(rows: list[dict]) -> dict[UUID, list[AttendanceCheck]]:
    grouped: dict[UUID, list[AttendanceCheck]] = {}
    for row in rows:
        grouped.setdefault(row["usuario_id"], []).append(
            AttendanceCheck(check_time=row["check_time"], punch_state=row.get("punch_state"))
        )
    return grouped


def _find_vacacion_id(vacaciones: list[dict], usuario_id: UUID, fecha_laboral: date) -> UUID | None:
    for row in vacaciones:
        if row["usuario_id"] == usuario_id and row["fecha_inicio"] <= fecha_laboral <= row["fecha_fin"]:
            return row["id"]
    return None


async def sync_biotime_periodically() -> None:
    logger.info("[BIOTIME_SYNC] Tarea inicializada")
    interval_seconds = 900
    while True:
        try:
            pool = await get_db_pool()
            async with pool.acquire() as conn:
                interval_seconds = await ConfigService.get_global_config(
                    conn, BIOTIME_CONFIG_KEYS["interval_seconds"], 900, int
                )
                result = await sync_biotime_once(conn)
                if result.get("status") == "disabled":
                    logger.debug("[BIOTIME_SYNC] Sincronizacion desactivada")
                else:
                    logger.info("[BIOTIME_SYNC] Resultado: %s", result)
        except asyncpg.PostgresError as exc:
            logger.error("[BIOTIME_SYNC] Error de BD: %s", exc)
        except httpx.HTTPError as exc:
            logger.error("[BIOTIME_SYNC] Error HTTP BioTime: %s", exc)
        except (ValueError, TypeError, RuntimeError) as exc:
            logger.error("[BIOTIME_SYNC] Error de sincronizacion: %s", exc)

        await asyncio.sleep(max(60, interval_seconds))
