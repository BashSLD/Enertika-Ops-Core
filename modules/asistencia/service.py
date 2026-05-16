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


def validate_aprobacion(minutos_aprobados: int, minutos_extra: int, comentario: str) -> None:
    if not comentario or not comentario.strip():
        raise ValueError("El comentario es obligatorio")
    if minutos_aprobados < 30:
        raise ValueError("El mínimo aprobable es 30 minutos")
    if minutos_aprobados > minutos_extra:
        raise ValueError(f"No puede aprobar más de {minutos_extra} minutos registrados")


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

    cfg = await _load_biotime_client_config(conn)
    base_url = cfg["base_url"]
    username = cfg["username"]
    password = cfg["password"]
    page_size = cfg["page_size"]
    timeout_seconds = cfg["timeout_seconds"]
    lookback_hours = await ConfigService.get_global_config(
        conn, BIOTIME_CONFIG_KEYS["lookback_hours"], 48, int
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
        async with BioTimeClient(base_url, username, password, timeout_seconds=timeout_seconds) as client:
            items = await client.fetch_transactions(
                starttime=window_start,
                endtime=window_end,
                page_size=page_size,
            )
            employee_sync = await _sync_employee_mappings_from_biotime(conn, client)
        normalized = await _normalize_transactions(conn, items)
        inserted = await db.insert_checks_batch(conn, normalized)
        reassigned = await db.assign_unmapped_checks_from_mappings(conn)
        affected_targets = _targets_from_inserted(inserted + reassigned)

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
        unmapped = await db.get_unmapped_biotime_checks_summary(
            conn,
            fecha_inicio=ensure_mx(window_start).date(),
            fecha_fin=ensure_mx(window_end).date(),
        )
        insert_metrics = _check_insert_metrics(inserted)
        return {
            "status": "success",
            "records_read": len(items),
            "records_inserted": len(inserted),
            "records_skipped": max(0, len(normalized) - len(inserted)),
            **insert_metrics,
            "historical_checks_mapped": len(reassigned),
            "affected_targets": len(affected_targets),
            "unmapped_biotime_codes": [row["biotime_emp_code"] for row in unmapped],
            "unmapped_biotime_count": sum(row["total"] for row in unmapped),
            **employee_sync,
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
    username: str,
    password: str,
    timeout_seconds: int = 30,
) -> dict:
    async with BioTimeClient(base_url, username, password, timeout_seconds=timeout_seconds) as client:
        total = await client.ping()
    return {"status": "success", "records_read": total}


_MESES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
    5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
    9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
}


def _chunk_label(fecha_inicio: date, fecha_fin: date) -> str:
    if fecha_inicio.year == fecha_fin.year and fecha_inicio.month == fecha_fin.month:
        return f"{_MESES[fecha_inicio.month]} {fecha_inicio.year}"
    return f"{fecha_inicio.strftime('%d/%m/%Y')} – {fecha_fin.strftime('%d/%m/%Y')}"


async def _load_biotime_client_config(conn) -> dict:
    configs = await ConfigService.get_global_configs_bulk(conn, {
        BIOTIME_CONFIG_KEYS["base_url"]: ("", str),
        BIOTIME_CONFIG_KEYS["username"]: ("", str),
        BIOTIME_CONFIG_KEYS["password"]: ("", str),
        BIOTIME_CONFIG_KEYS["page_size"]: (200, int),
        BIOTIME_CONFIG_KEYS["timeout_seconds"]: (30, int),
    })
    return {
        "base_url": configs[BIOTIME_CONFIG_KEYS["base_url"]],
        "username": configs[BIOTIME_CONFIG_KEYS["username"]],
        "password": configs[BIOTIME_CONFIG_KEYS["password"]],
        "page_size": configs[BIOTIME_CONFIG_KEYS["page_size"]],
        "timeout_seconds": configs[BIOTIME_CONFIG_KEYS["timeout_seconds"]],
    }


async def backfill_biotime_chunk(
    conn,
    fecha_inicio: date,
    fecha_fin: date,
) -> dict:
    if (fecha_fin - fecha_inicio).days > 31:
        raise ValueError("El rango del chunk no puede superar 31 días")

    cfg = await _load_biotime_client_config(conn)
    base_url = cfg["base_url"]
    username = cfg["username"]
    password = cfg["password"]
    page_size = cfg["page_size"]
    timeout_seconds = cfg["timeout_seconds"]

    window_start = datetime.combine(fecha_inicio, time.min, tzinfo=MX_TZ)
    window_end = datetime.combine(fecha_fin + timedelta(days=1), time.min, tzinfo=MX_TZ)
    chunk_label = _chunk_label(fecha_inicio, fecha_fin)

    run_id = await db.create_sync_run(
        conn,
        from_transaction_id=None,
        window_start=window_start,
        window_end=window_end,
    )

    try:
        async with BioTimeClient(base_url, username, password, timeout_seconds=timeout_seconds) as client:
            items = await client.fetch_transactions(
                starttime=window_start,
                endtime=window_end,
                page_size=page_size,
            )
            employee_sync = await _sync_employee_mappings_from_biotime(conn, client)

        normalized = await _normalize_transactions(conn, items)
        inserted = await db.insert_checks_batch(conn, normalized)
        reassigned = await db.assign_unmapped_checks_from_mappings(conn)
        targets = _targets_from_inserted(inserted + reassigned)

        if targets:
            await recalcular_asistencia(conn, targets)

        to_id = _max_transaction_id(normalized)
        await db.finish_sync_run(
            conn,
            run_id=run_id,
            status="success",
            to_transaction_id=to_id,
            records_read=len(items),
            records_inserted=len(inserted),
            records_skipped=max(0, len(normalized) - len(inserted)),
        )
        unmapped = await db.get_unmapped_biotime_checks_summary(
            conn,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
        )
        return {
            "chunk_label": chunk_label,
            "records_read": len(items),
            "records_inserted": len(inserted),
            "records_skipped": max(0, len(normalized) - len(inserted)),
            **_check_insert_metrics(inserted),
            "historical_checks_mapped": len(reassigned),
            "unmapped_biotime_codes": [row["biotime_emp_code"] for row in unmapped],
            "unmapped_biotime_count": sum(row["total"] for row in unmapped),
            "targets_recalculated": len(targets),
            **employee_sync,
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


async def _normalize_transactions(conn, items: list[dict[str, Any]]) -> list[dict]:
    emp_codes = sorted({
        str(_first_value(item, "emp_code", "pin", "badgenumber", "employee_code") or "").strip()
        for item in items
        if _first_value(item, "emp_code", "pin", "badgenumber", "employee_code")
    })
    employee_map = await db.get_employee_map(conn, emp_codes)
    normalized: list[dict] = []

    for item in items:
        emp_code = str(_first_value(item, "emp_code", "pin", "badgenumber", "employee_code") or "").strip()
        raw_time = _first_value(item, "transaction_punch_time", "checktime", "punch_time", "check_time")
        punch_date = item.get("transaction_punch_date")
        if raw_time and punch_date and ":" in str(raw_time) and "-" not in str(raw_time):
            raw_time = f"{punch_date} {raw_time}"
        check_time = parse_biotime_check_time(raw_time)
        if not emp_code or not check_time:
            continue

        mapping = employee_map.get(emp_code, {})
        normalized.append({
            "biotime_transaction_id": _safe_int(item.get("id")),
            "biotime_emp_code": emp_code,
            "usuario_id": str(mapping["usuario_id"]) if mapping.get("usuario_id") else None,
            "check_time": check_time.isoformat(),
            "punch_state": _string_or_none(_first_value(item, "stateno", "punch_state", "state")),
            "verify_type": _string_or_none(_first_value(item, "verify_type", "verify")),
            "terminal_sn": _string_or_none(_first_value(item, "sn", "terminal_sn")),
            "terminal_alias": _string_or_none(_first_value(item, "alias", "terminal_alias")),
            "deptnumber": _string_or_none(item.get("deptnumber")),
            "deptname": _string_or_none(_first_value(item, "deptname", "employee_department")),
            "raw_payload": item,
        })
    return normalized


async def _sync_employee_mappings_from_biotime(
    conn,
    client: BioTimeClient,
) -> dict:
    try:
        employees = await client.fetch_employees()
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        logger.warning("[BIOTIME_SYNC] No se pudieron consultar empleados BioTime: %s", exc)
        return {"employees_read": 0, "employee_mappings": 0}

    normalized = [
        employee
        for employee in (_normalize_biotime_employee(item) for item in employees)
        if employee
    ]
    mapped = await db.upsert_biotime_employee_mappings(conn, normalized)
    return {"employees_read": len(employees), "employee_mappings": len(mapped)}


def _normalize_biotime_employee(item: dict[str, Any]) -> dict | None:
    emp_code = _string_or_none(_first_value(item, "emp_code", "pin", "userpin", "badgenumber", "employee_code"))
    if not emp_code:
        return None
    first = _string_or_none(_first_value(item, "first_name", "name", "username", "ename"))
    last = _string_or_none(_first_value(item, "last_name", "surname"))
    nombre = " ".join(part for part in [first, last] if part) or None
    dept_name = _string_or_none(_first_value(
        item, "employee_department", "department", "dept_name", "deptname", "department_name",
    ))
    dept_code = _string_or_none(_first_value(item, "dept_code", "deptnumber", "department_code", "department_id"))
    return {
        "biotime_emp_id": _safe_int(item.get("id")),
        "biotime_emp_code": emp_code,
        "biotime_pin": _string_or_none(_first_value(item, "pin", "userpin", "emp_code")),
        "email": _normalize_email(_first_value(item, "email", "mail")),
        "nombre": nombre,
        "biotime_deptnumber": dept_code,
        "biotime_deptname": dept_name,
    }


def _normalize_email(value: Any) -> str | None:
    text = _string_or_none(value)
    return text.lower() if text else None


def _first_value(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = item.get(key)
        if value is not None and value != "":
            return value
    return None


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


def _max_transaction_id(rows: list[dict]) -> int | None:
    values = [row["biotime_transaction_id"] for row in rows if row.get("biotime_transaction_id")]
    return max(values) if values else None


def _check_insert_metrics(rows: list[dict]) -> dict:
    mapped = sum(1 for row in rows if row.get("usuario_id"))
    unmapped = len(rows) - mapped
    return {
        "records_inserted_mapped": mapped,
        "records_inserted_unmapped": unmapped,
    }


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
            fecha_laboral=fecha_laboral,
            now=calculated_at,
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
