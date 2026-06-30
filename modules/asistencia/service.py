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
from core.permissions import user_has_module_access
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
    is_in_state,
    is_out_state,
)
from modules.shared.utils import format_minutes
from modules.vacaciones import db_service as vacaciones_db

logger = logging.getLogger("asistencia.service")

_SOLICITUD_MANUAL_ESTADOS = {
    "pendiente": "Pendiente",
    "aprobado": "Aprobado",
    "rechazado": "Rechazado",
}


def validate_aprobacion(minutos_aprobados: int, minutos_extra: int, comentario: str) -> None:
    if not comentario or not comentario.strip():
        raise ValueError("El comentario es obligatorio")
    if minutos_aprobados < 30:
        raise ValueError("El mínimo aprobable es 30 minutos")
    if minutos_aprobados > minutos_extra:
        raise ValueError(f"No puede aprobar más de {minutos_extra} minutos registrados")


async def get_equipo_ids(conn, user_id: UUID, user_ctx: dict) -> list[UUID]:
    if user_has_module_access("rrhh", user_ctx, "editor"):
        rows = await vacaciones_db.get_all_empleados_con_datos(conn, limit=500, offset=0)
        return [r["id_usuario"] for r in rows]

    ids_jefe = await vacaciones_db.get_empleados_donde_soy_jefe(conn, user_id)
    ids_aprobador = await vacaciones_db.get_empleados_donde_soy_aprobador(conn, user_id)
    return list({*ids_jefe, *ids_aprobador})


async def aprobar_horas_extra_svc(
    conn,
    *,
    asistencia_id: UUID,
    aprobador_id: UUID,
    minutos_aprobados: int,
    comentario: str,
    equipo_ids: list[UUID],
) -> dict:
    row = await db.get_asistencia_para_aprobar(conn, asistencia_id)
    if not row:
        raise ValueError("Registro no encontrado")
    if row["horas_extra_estado"] not in ("pendiente", "solicitado"):
        raise ValueError("Este registro ya fue procesado")
    if row["usuario_id"] not in equipo_ids:
        raise ValueError("Registro no encontrado")
    validate_aprobacion(minutos_aprobados, row["minutos_extra"], comentario)

    await db.aprobar_horas_extra(
        conn,
        asistencia_id=asistencia_id,
        aprobador_id=aprobador_id,
        minutos_aprobados=minutos_aprobados,
        comentario=comentario,
    )
    return {
        "empleado_nombre": row["empleado_nombre"],
        "fecha_laboral": row["fecha_laboral"],
        "minutos_aprobados": minutos_aprobados,
        "comentario": comentario,
    }


async def bulk_aprobar_horas_extra_svc(
    conn,
    *,
    asistencia_ids: list[UUID],
    aprobador_id: UUID,
    minutos_aprobados: int,
    comentario: str,
    equipo_ids: list[UUID],
) -> dict:
    if not asistencia_ids:
        raise ValueError("Lista de registros vacía")

    rows = await db.bulk_get_asistencia_info(conn, asistencia_ids)
    if len(rows) != len(asistencia_ids):
        raise ValueError("Uno o más registros no encontrados")

    usuario_ids_set = {row["usuario_id"] for row in rows}
    if len(usuario_ids_set) != 1:
        raise ValueError("Los registros seleccionados deben pertenecer al mismo empleado")

    empleado_id = next(iter(usuario_ids_set))
    if empleado_id not in equipo_ids:
        raise ValueError("Registro no encontrado")

    for row in rows:
        if row["horas_extra_estado"] not in ("pendiente", "solicitado"):
            fecha = row["fecha_laboral"].strftime("%d/%m/%Y")
            raise ValueError(f"El registro del {fecha} ya fue procesado")
        validate_aprobacion(minutos_aprobados, row["minutos_extra"], comentario)

    await db.bulk_aprobar_horas_extra(
        conn,
        asistencia_ids=asistencia_ids,
        aprobador_id=aprobador_id,
        minutos_aprobados=minutos_aprobados,
        comentario=comentario,
    )

    return {
        "empleado_nombre": rows[0]["empleado_nombre"],
        "dias_aprobados": [
            {
                "fecha": row["fecha_laboral"],
                "minutos_aprobados": minutos_aprobados,
            }
            for row in rows
        ],
        "comentario": comentario,
    }


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


async def recalcular_asistencia_reciente_usuario(conn, usuario_id: UUID, *, days: int = 7) -> int:
    end = today_mx()
    start = end - timedelta(days=max(0, days - 1))
    targets = [
        (usuario_id, start + timedelta(days=offset))
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

    min_minutos_he = await ConfigService.get_global_config(
        conn, "ASISTENCIA_HE_MINIMO_MINUTOS", 30, int
    )

    context_rows = await db.get_attendance_contexts(conn, usuario_ids)
    schedule_by_user_day, sucursal_by_user = _build_context_maps(context_rows)
    ausencias = await db.get_ausencias_justificadas(
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
        ausencia = _find_ausencia_justificada(ausencias, usuario_id, fecha_laboral)
        tipo_slug = ausencia.get("tipo_slug") if ausencia else None
        solicitud_id = ausencia["id"] if ausencia else None
        tiene_vacaciones = tipo_slug == "vacaciones"
        tiene_ausencia_justificada = ausencia is not None
        resumen = calcular_resumen_dia(
            checks=checks_dia,
            schedule=schedule,
            tiene_vacaciones=tiene_vacaciones,
            tiene_ausencia_justificada=tiene_ausencia_justificada,
            ausencia_tipo_nombre=ausencia.get("tipo_nombre") if ausencia else None,
            es_feriado=fecha_laboral in festivos,
            fecha_laboral=fecha_laboral,
            now=calculated_at,
            min_minutos_he=min_minutos_he,
        )
        rows_to_save.append({
            "usuario_id": usuario_id,
            "sucursal_id": sucursal_by_user.get(usuario_id),
            "fecha_laboral": fecha_laboral,
            "tiene_vacaciones": tiene_vacaciones,
            "tiene_ausencia_justificada": tiene_ausencia_justificada,
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


def _find_ausencia_justificada(
    ausencias: list[dict],
    usuario_id: UUID,
    fecha_laboral: date,
) -> dict | None:
    for row in ausencias:
        if row["usuario_id"] == usuario_id and row["fecha_inicio"] <= fecha_laboral <= row["fecha_fin"]:
            return row
    return None


async def omitir_horas_extra_propio_svc(
    conn,
    *,
    asistencia_id: UUID,
    usuario_id: UUID,
) -> None:
    row = await db.get_asistencia_para_aprobar(conn, asistencia_id)
    if not row:
        raise ValueError("Registro no encontrado")
    if row["usuario_id"] != usuario_id:
        raise ValueError("No tienes permiso para modificar este registro")
    if row["horas_extra_estado"] != "pendiente":
        raise ValueError("Solo puedes descartar registros pendientes")
    await db.omitir_horas_extra(conn, asistencia_id)


async def omitir_horas_extra_svc(
    conn,
    *,
    asistencia_id: UUID,
    equipo_ids: list[UUID],
) -> dict:
    row = await db.get_asistencia_para_aprobar(conn, asistencia_id)
    if not row:
        raise ValueError("Registro no encontrado")
    if row["horas_extra_estado"] not in ("pendiente", "solicitado"):
        raise ValueError("Solo se pueden descartar registros pendientes o solicitados")
    if row["usuario_id"] not in equipo_ids:
        raise ValueError("Registro no encontrado")
    await db.omitir_horas_extra(conn, asistencia_id)
    return {"empleado_nombre": row["empleado_nombre"]}


async def recuperar_horas_extra_svc(
    conn,
    *,
    asistencia_id: UUID,
    equipo_ids: list[UUID],
) -> dict:
    row = await db.get_asistencia_para_aprobar(conn, asistencia_id)
    if not row:
        raise ValueError("Registro no encontrado")
    if row["horas_extra_estado"] != "omitido":
        raise ValueError("El registro no está descartado")
    if row["usuario_id"] not in equipo_ids:
        raise ValueError("Registro no encontrado")
    await db.recuperar_horas_extra(conn, asistencia_id)
    return {"empleado_nombre": row["empleado_nombre"]}


async def solicitar_aprobacion_svc(
    conn,
    *,
    asistencia_id: UUID,
    usuario_id: UUID,
    motivo: str,
    empleado_nombre: str | None = None,
) -> dict:
    row = await db.get_asistencia_para_aprobar(conn, asistencia_id)
    if not row:
        raise ValueError("Registro no encontrado")
    if row["usuario_id"] != usuario_id:
        raise ValueError("No tienes permiso para este registro")
    if row["horas_extra_estado"] != "pendiente":
        raise ValueError("Solo puedes solicitar aprobacion de registros pendientes")
    if not motivo or not motivo.strip():
        raise ValueError("El motivo es obligatorio")
    motivo_limpio = motivo.strip()
    await db.solicitar_aprobacion_horas_extra(conn, asistencia_id, usuario_id, motivo_limpio)
    if empleado_nombre:
        await _notificar_solicitud_horas_extra(
            conn,
            usuario_id=usuario_id,
            empleado_nombre=empleado_nombre,
            fecha_laboral=row["fecha_laboral"],
            minutos_extra=row["minutos_extra"],
            motivo=motivo_limpio,
        )
    return {"fecha_laboral": row["fecha_laboral"], "minutos_extra": row["minutos_extra"]}


async def _notificar_solicitud_horas_extra(
    conn,
    *,
    usuario_id: UUID,
    empleado_nombre: str,
    fecha_laboral: date,
    minutos_extra: int,
    motivo: str,
) -> None:
    from core.workflow.notification_service import NotificationService

    svc_notif = NotificationService()
    jefes = await db.get_jefes_del_empleado(conn, usuario_id)
    jefe_emails = {j["email"] for j in jefes if j.get("email")}
    rh_emails = await svc_notif._get_rh_emails_cc(conn)
    tiene_director = any((j.get("rol_organizacional") or "").lower() == "director" for j in jefes)
    destinatarios = jefe_emails or rh_emails
    cc_emails = rh_emails if tiene_director and jefe_emails else set()
    await svc_notif.notify_horas_extra_solicitud(
        conn,
        empleado_nombre=empleado_nombre,
        fecha_laboral=fecha_laboral,
        extra_fmt=format_minutes(minutos_extra),
        motivo=motivo,
        destinatarios=destinatarios,
        cc_emails=cc_emails,
        via_rh=not jefe_emails,
    )


async def _get_config_manual_asistencia(conn) -> tuple[int, int]:
    configs = await ConfigService.get_global_configs_bulk(
        conn,
        {
            "ASISTENCIA_MANUAL_DIAS_RETROACTIVO": 7,
            "ASISTENCIA_MANUAL_MAX_HORAS": 16,
        },
    )
    return int(configs["ASISTENCIA_MANUAL_DIAS_RETROACTIVO"]), int(configs["ASISTENCIA_MANUAL_MAX_HORAS"])


def _parse_manual_datetime(fecha: date | None, hora: str | None) -> datetime:
    if not fecha or not hora:
        raise ValueError("Fecha y hora son obligatorias")
    try:
        parsed_time = time.fromisoformat(hora)
    except ValueError as exc:
        raise ValueError("Hora invalida") from exc
    return datetime.combine(fecha, parsed_time, tzinfo=MX_TZ)


def _format_manual_datetime(value: datetime | None) -> str | None:
    if not value:
        return None
    return ensure_mx(value).strftime("%d/%m/%Y %H:%M")


def _format_manual_request(row: dict) -> dict:
    formatted = dict(row)
    formatted["estado_label"] = _SOLICITUD_MANUAL_ESTADOS.get(row.get("estado"), row.get("estado", ""))
    formatted["fecha_laboral_fmt"] = row["fecha_laboral"].strftime("%d/%m/%Y")
    formatted["entrada_fmt"] = _format_manual_datetime(row.get("entrada_tiempo"))
    formatted["salida_fmt"] = _format_manual_datetime(row.get("salida_tiempo"))
    formatted["created_at_fmt"] = _format_manual_datetime(row.get("created_at"))
    return formatted


def format_solicitudes_manuales(rows: list[dict]) -> list[dict]:
    return [_format_manual_request(row) for row in rows]


async def _get_labor_window_usuario_fecha(conn, usuario_id: UUID, fecha_laboral: date):
    context_rows = await db.get_attendance_contexts(conn, [usuario_id])
    schedule_by_user_day, _ = _build_context_maps(context_rows)
    schedule = schedule_by_user_day.get((usuario_id, fecha_laboral.weekday()))
    return build_labor_window(fecha_laboral, schedule), schedule


async def _detectar_huecos_manual(conn, usuario_id: UUID, fecha_laboral: date) -> dict:
    labor_window, schedule = await _get_labor_window_usuario_fecha(conn, usuario_id, fecha_laboral)
    checks = await db.get_biotime_checks_usuario_window(
        conn,
        usuario_id=usuario_id,
        start=labor_window.start,
        end=labor_window.end,
    )
    huecos = _clasificar_huecos_biotime(checks)
    return {
        "labor_window": labor_window,
        "schedule": schedule,
        "checks": checks,
        "huecos": huecos,
    }


def _clasificar_huecos_biotime(checks: list[dict]) -> dict:
    real_checks = sorted(
        [check for check in checks if not check.get("es_manual")],
        key=lambda check: ensure_mx(check["check_time"]),
    )
    if not real_checks:
        return {
            "falta_entrada": True,
            "falta_salida": True,
            "entrada_real": None,
            "salida_real": None,
            "bloqueado": False,
            "mensaje_bloqueo": None,
        }

    entradas = [check for check in real_checks if is_in_state(check.get("punch_state"))]
    salidas = [check for check in real_checks if is_out_state(check.get("punch_state"))]
    desconocidas = [
        check
        for check in real_checks
        if not is_in_state(check.get("punch_state")) and not is_out_state(check.get("punch_state"))
    ]
    if desconocidas or len(entradas) > 1 or len(salidas) > 1:
        return {
            "falta_entrada": False,
            "falta_salida": False,
            "entrada_real": ensure_mx(entradas[0]["check_time"]) if entradas else None,
            "salida_real": ensure_mx(salidas[-1]["check_time"]) if salidas else None,
            "bloqueado": True,
            "mensaje_bloqueo": "El dia tiene checadas BioTime ambiguas. Solicita revision de RRHH.",
        }

    entrada_real = ensure_mx(entradas[0]["check_time"]) if entradas else None
    salida_real = ensure_mx(salidas[-1]["check_time"]) if salidas else None
    return {
        "falta_entrada": entrada_real is None,
        "falta_salida": salida_real is None,
        "entrada_real": entrada_real,
        "salida_real": salida_real,
        "bloqueado": False,
        "mensaje_bloqueo": None,
    }


def _validar_fechas_manual(
    *,
    fecha_laboral: date,
    fecha_entrada: date | None,
    fecha_salida: date | None,
    solicita_entrada: bool,
    solicita_salida: bool,
    entrada_tiempo: datetime | None,
    salida_tiempo: datetime | None,
    dias_retroactivo: int,
    max_horas: int,
    labor_window,
    huecos: dict,
) -> None:
    hoy = today_mx()
    if fecha_laboral > hoy:
        raise ValueError("La fecha laboral no puede ser futura")
    if fecha_laboral < hoy - timedelta(days=dias_retroactivo):
        raise ValueError(f"Solo puedes solicitar registros de los ultimos {dias_retroactivo} dias")
    if solicita_entrada and fecha_entrada != fecha_laboral:
        raise ValueError("La fecha de entrada debe coincidir con la fecha laboral")
    if solicita_salida and fecha_salida not in {fecha_laboral, fecha_laboral + timedelta(days=1)}:
        raise ValueError("La fecha de salida debe ser la fecha laboral o el dia siguiente")

    _validar_tiempos_manual(
        solicita_entrada=solicita_entrada,
        solicita_salida=solicita_salida,
        entrada_tiempo=entrada_tiempo,
        salida_tiempo=salida_tiempo,
        max_horas=max_horas,
        labor_window=labor_window,
        huecos=huecos,
    )


def _validar_tiempos_manual(
    *,
    solicita_entrada: bool,
    solicita_salida: bool,
    entrada_tiempo: datetime | None,
    salida_tiempo: datetime | None,
    max_horas: int,
    labor_window,
    huecos: dict,
) -> None:
    ahora = now_mx()
    if solicita_entrada:
        if not entrada_tiempo:
            raise ValueError("La fecha y hora de entrada son obligatorias")
        if entrada_tiempo > ahora:
            raise ValueError("La fecha y hora capturada no puede ser futura.")
        if not labor_window.start <= entrada_tiempo <= labor_window.end:
            raise ValueError("La entrada esta fuera de la ventana laboral esperada")

    if solicita_salida:
        if not salida_tiempo:
            raise ValueError("La fecha y hora de salida son obligatorias")
        if salida_tiempo > ahora:
            raise ValueError("La fecha y hora capturada no puede ser futura.")
        if not labor_window.start <= salida_tiempo <= labor_window.end:
            raise ValueError("La salida esta fuera de la ventana laboral esperada")

    entrada_ref = entrada_tiempo if solicita_entrada else huecos.get("entrada_real")
    salida_ref = salida_tiempo if solicita_salida else huecos.get("salida_real")
    if entrada_ref and salida_ref:
        if salida_ref <= entrada_ref:
            raise ValueError("La hora de salida es anterior a la entrada. Revisa la fecha y hora correcta.")
        duracion_horas = (salida_ref - entrada_ref).total_seconds() / 3600
        if duracion_horas > max_horas:
            raise ValueError(f"La jornada no puede exceder {max_horas} horas")


def _validar_solicitud_vs_huecos(
    *,
    solicita_entrada: bool,
    solicita_salida: bool,
    huecos: dict,
) -> dict:
    if huecos.get("bloqueado"):
        raise ValueError(huecos.get("mensaje_bloqueo") or "El dia tiene checadas BioTime ambiguas")

    falta_entrada = bool(huecos.get("falta_entrada"))
    falta_salida = bool(huecos.get("falta_salida"))
    if not falta_entrada and not falta_salida:
        raise ValueError("El dia ya tiene entrada y salida registradas")
    if falta_entrada and not solicita_entrada:
        raise ValueError("La solicitud ya no coincide con los huecos actuales de BioTime.")
    if falta_salida and not solicita_salida:
        raise ValueError("La solicitud ya no coincide con los huecos actuales de BioTime.")

    insertar_entrada = solicita_entrada and falta_entrada
    insertar_salida = solicita_salida and falta_salida
    if not insertar_entrada and not insertar_salida:
        raise ValueError("La solicitud ya no coincide con los huecos actuales de BioTime.")
    return {"insertar_entrada": insertar_entrada, "insertar_salida": insertar_salida}


def _prefill_manual_times(fecha_laboral: date, schedule: ScheduleConfig | None) -> dict:
    fecha_salida = fecha_laboral
    hora_entrada = "08:00"
    hora_salida = "17:00"
    if schedule:
        if schedule.hora_entrada:
            hora_entrada = schedule.hora_entrada.strftime("%H:%M")
        if schedule.hora_salida:
            hora_salida = schedule.hora_salida.strftime("%H:%M")
        if schedule.cruza_medianoche or (
            schedule.hora_entrada and schedule.hora_salida and schedule.hora_salida < schedule.hora_entrada
        ):
            fecha_salida = fecha_laboral + timedelta(days=1)
    return {
        "fecha_entrada": fecha_laboral,
        "fecha_salida": fecha_salida,
        "hora_entrada": hora_entrada,
        "hora_salida": hora_salida,
    }


async def preparar_solicitud_manual_svc(conn, usuario_id: UUID, fecha_laboral: date) -> dict:
    dias_retroactivo, _ = await _get_config_manual_asistencia(conn)
    hoy = today_mx()
    base = {
        "fecha_laboral": fecha_laboral,
        "fecha_laboral_iso": fecha_laboral.isoformat(),
        "fecha_laboral_fmt": fecha_laboral.strftime("%d/%m/%Y"),
    }
    if fecha_laboral > hoy:
        return {**base, "bloqueado": True, "mensaje_bloqueo": "La fecha laboral no puede ser futura"}
    if fecha_laboral < hoy - timedelta(days=dias_retroactivo):
        return {
            **base,
            "bloqueado": True,
            "mensaje_bloqueo": f"Solo puedes solicitar registros de los ultimos {dias_retroactivo} dias",
        }

    deteccion = await _detectar_huecos_manual(conn, usuario_id, fecha_laboral)
    huecos = deteccion["huecos"]
    if huecos.get("bloqueado"):
        return {**base, "bloqueado": True, "mensaje_bloqueo": huecos["mensaje_bloqueo"]}
    if not huecos["falta_entrada"] and not huecos["falta_salida"]:
        return {**base, "bloqueado": True, "mensaje_bloqueo": "El dia ya tiene entrada y salida registradas"}

    return {
        **base,
        **_prefill_manual_times(fecha_laboral, deteccion["schedule"]),
        "bloqueado": False,
        "mensaje_bloqueo": None,
        "solicita_entrada": huecos["falta_entrada"],
        "solicita_salida": huecos["falta_salida"],
    }


async def crear_solicitud_manual_svc(conn, usuario_id: UUID, payload) -> dict:
    motivo = (payload.motivo or "").strip()
    if not motivo:
        raise ValueError("El motivo es obligatorio")

    existente = await db.get_solicitud_manual_existente_activa(conn, usuario_id, payload.fecha_laboral)
    if existente:
        raise ValueError("Ya existe una solicitud activa para esa fecha")

    dias_retroactivo, max_horas = await _get_config_manual_asistencia(conn)
    deteccion = await _detectar_huecos_manual(conn, usuario_id, payload.fecha_laboral)
    huecos = deteccion["huecos"]
    solicita_entrada = huecos["falta_entrada"]
    solicita_salida = huecos["falta_salida"]
    _validar_solicitud_vs_huecos(
        solicita_entrada=solicita_entrada,
        solicita_salida=solicita_salida,
        huecos=huecos,
    )

    entrada_tiempo = _parse_manual_datetime(payload.fecha_entrada, payload.hora_entrada) if solicita_entrada else None
    salida_tiempo = _parse_manual_datetime(payload.fecha_salida, payload.hora_salida) if solicita_salida else None
    _validar_fechas_manual(
        fecha_laboral=payload.fecha_laboral,
        fecha_entrada=payload.fecha_entrada,
        fecha_salida=payload.fecha_salida,
        solicita_entrada=solicita_entrada,
        solicita_salida=solicita_salida,
        entrada_tiempo=entrada_tiempo,
        salida_tiempo=salida_tiempo,
        dias_retroactivo=dias_retroactivo,
        max_horas=max_horas,
        labor_window=deteccion["labor_window"],
        huecos=huecos,
    )

    row = await db.insert_solicitud_manual(
        conn,
        usuario_id=usuario_id,
        fecha_laboral=payload.fecha_laboral,
        solicita_entrada=solicita_entrada,
        solicita_salida=solicita_salida,
        entrada_tiempo=entrada_tiempo,
        salida_tiempo=salida_tiempo,
        motivo=motivo,
    )
    return _format_manual_request(row)


async def aprobar_solicitud_manual_svc(
    conn,
    *,
    solicitud_id: UUID,
    aprobador_id: UUID,
    equipo_ids: list[UUID],
) -> dict:
    async with conn.transaction():
        solicitud = await db.get_solicitud_manual_for_update(conn, solicitud_id)
        if not solicitud:
            raise ValueError("Solicitud no encontrada")
        if solicitud["usuario_id"] not in equipo_ids:
            raise ValueError("Solicitud no encontrada")
        if solicitud["estado"] != "pendiente":
            raise ValueError("Esta solicitud ya fue procesada")

        _, max_horas = await _get_config_manual_asistencia(conn)
        deteccion = await _detectar_huecos_manual(conn, solicitud["usuario_id"], solicitud["fecha_laboral"])
        acciones = _validar_solicitud_vs_huecos(
            solicita_entrada=solicitud["solicita_entrada"],
            solicita_salida=solicitud["solicita_salida"],
            huecos=deteccion["huecos"],
        )
        _validar_tiempos_manual(
            solicita_entrada=acciones["insertar_entrada"],
            solicita_salida=acciones["insertar_salida"],
            entrada_tiempo=solicitud["entrada_tiempo"] if acciones["insertar_entrada"] else None,
            salida_tiempo=solicitud["salida_tiempo"] if acciones["insertar_salida"] else None,
            max_horas=max_horas,
            labor_window=deteccion["labor_window"],
            huecos=deteccion["huecos"],
        )

        emp_code = await db.get_biotime_emp_code_para_manual(conn, solicitud["usuario_id"])
        if not emp_code:
            raise ValueError("No hay codigo BioTime configurado para este usuario")

        check_entrada_id = None
        check_salida_id = None
        if acciones["insertar_entrada"]:
            check_entrada_id = await db.insert_manual_check(
                conn,
                usuario_id=solicitud["usuario_id"],
                biotime_emp_code=emp_code,
                check_time=solicitud["entrada_tiempo"],
                punch_state="0",
                solicitud_manual_id=solicitud_id,
            )
        if acciones["insertar_salida"]:
            check_salida_id = await db.insert_manual_check(
                conn,
                usuario_id=solicitud["usuario_id"],
                biotime_emp_code=emp_code,
                check_time=solicitud["salida_tiempo"],
                punch_state="1",
                solicitud_manual_id=solicitud_id,
            )

        await db.aprobar_solicitud_manual(
            conn,
            solicitud_id=solicitud_id,
            revisado_por=aprobador_id,
            check_entrada_id=check_entrada_id,
            check_salida_id=check_salida_id,
        )
        await recalcular_asistencia(conn, [(solicitud["usuario_id"], solicitud["fecha_laboral"])])

    return _format_manual_request({**solicitud, "estado": "aprobado"})


async def rechazar_solicitud_manual_svc(
    conn,
    *,
    solicitud_id: UUID,
    aprobador_id: UUID,
    equipo_ids: list[UUID],
    comentario: str,
) -> dict:
    comentario = (comentario or "").strip()
    if not comentario:
        raise ValueError("El comentario es obligatorio")

    async with conn.transaction():
        solicitud = await db.get_solicitud_manual_for_update(conn, solicitud_id)
        if not solicitud:
            raise ValueError("Solicitud no encontrada")
        if solicitud["usuario_id"] not in equipo_ids:
            raise ValueError("Solicitud no encontrada")
        if solicitud["estado"] != "pendiente":
            raise ValueError("Esta solicitud ya fue procesada")
        await db.rechazar_solicitud_manual(
            conn,
            solicitud_id=solicitud_id,
            revisado_por=aprobador_id,
            comentario_revision=comentario,
        )

    return _format_manual_request({**solicitud, "estado": "rechazado", "comentario_revision": comentario})


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
            logger.error("[BIOTIME_SYNC] Error HTTP BioTime: %s: %s", type(exc).__name__, exc or "(sin mensaje)")
        except (ValueError, TypeError, RuntimeError) as exc:
            logger.error("[BIOTIME_SYNC] Error de sincronizacion: %s", exc)

        await asyncio.sleep(max(60, interval_seconds))
