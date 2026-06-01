from __future__ import annotations

import base64
import logging
from datetime import date, timedelta
from typing import Any, Optional
from uuid import UUID

from core.config_service import ConfigService
from core.permissions import user_has_module_access
from core.timezone import fmt_time_mx, today_mx
from modules.asistencia import db_service as asistencia_db
from modules.asistencia.service import recalcular_asistencia
from modules.shared import signatures_db_service as signatures_db
from modules.shared.utils import format_minutes
from modules.vacaciones import db_service as db
from modules.vacaciones.constants import VACACIONES_SLUGS
from modules.vacaciones.logic import (
    asignar_consumo_fifo,
    calcular_balance,
    calcular_periodos,
    calcular_progreso,
    calcular_semestre_liberado,
    contar_dias_habiles,
    siguiente_dia_habil,
)

logger = logging.getLogger("vacaciones.service")


def _saldo_neto(balance: list[dict]) -> int:
    activos = [p for p in balance if not p.get("es_proximo") and not p.get("expirado")]
    adelantos = sum(p["dias_usados"] for p in balance if p.get("es_proximo"))
    return sum(p["dias_restantes"] for p in activos) - adelantos


# ─────────────────────────────────────────────
# Balance y períodos
# ─────────────────────────────────────────────

async def get_balance_usuario(conn, usuario_id: UUID) -> dict[str, Any]:
    """
    Devuelve el balance completo: periodos, saldos, progreso, alertas y datos de anticipacion.
    Retorna None en 'periodos' si el empleado no tiene fecha_contratacion.
    """
    empleado = await db.get_empleado_datos(conn, usuario_id)
    if not empleado or not empleado.get("fecha_contratacion"):
        return {
            "empleado": empleado,
            "periodos": None,
            "progreso": None,
            "total_disponible": 0,
            "semestre": None,
            "dias_efectivos_disponibles": 0,
            "dias_tomados_anticipadamente": 0,
            "anticipo_habilitado": False,
        }

    hoy = today_mx()
    catalogo = await db.get_catalogo_dias(conn)
    meses_exp = await ConfigService.get_global_config(conn, "VACACIONES_MESES_EXPIRACION", 18, int)
    anticipo_habilitado = await ConfigService.get_global_config(conn, "VACACIONES_ANTICIPO_HABILITADO", True, bool)
    meses_semestre = await ConfigService.get_global_config(conn, "VACACIONES_ANTICIPO_MESES_SEMESTRE", 6, int)
    porcentaje_liberacion = await ConfigService.get_global_config(conn, "VACACIONES_ANTICIPO_PORCENTAJE_LIBERACION", 50, int)

    periodos = calcular_periodos(
        empleado["fecha_contratacion"],
        hoy,
        catalogo,
        ajuste_dias=empleado.get("dias_vacaciones_ajuste") or 0,
        meses_expiracion=meses_exp,
    )
    consumos = await db.get_consumos_usuario(conn, usuario_id)
    prorrogas = await db.get_prorrogas_activas_usuario(conn, usuario_id)
    balance = calcular_balance(periodos, consumos, prorrogas=prorrogas)
    progreso = calcular_progreso(empleado["fecha_contratacion"], hoy, catalogo)

    periodos_activos = [p for p in balance if not p.get("es_proximo") and not p.get("expirado")]
    total_disponible = sum(max(p["dias_restantes"], 0) for p in periodos_activos)
    saldo_neto = _saldo_neto(balance)

    semestre = None
    dias_efectivos_disponibles = total_disponible
    dias_tomados_anticipadamente = 0

    if anticipo_habilitado:
        semestre = calcular_semestre_liberado(
            empleado["fecha_contratacion"], hoy, catalogo, meses_semestre, porcentaje_liberacion
        )
        dias_de_aniversarios = sum(p["dias_otorgados"] for p in periodos_activos)
        total_usados = sum(p["dias_usados"] for p in balance)
        dias_semestre = semestre["dias_liberados"] if semestre["semestre_activo"] else 0
        dias_efectivos_disponibles = dias_de_aniversarios + dias_semestre - total_usados
        dias_tomados_anticipadamente = max(0, -dias_efectivos_disponibles)

    return {
        "empleado": empleado,
        "periodos": balance,
        "progreso": progreso,
        "total_disponible": total_disponible,
        "saldo_neto": saldo_neto,
        "semestre": semestre,
        "dias_efectivos_disponibles": dias_efectivos_disponibles,
        "dias_tomados_anticipadamente": dias_tomados_anticipadamente,
        "anticipo_habilitado": anticipo_habilitado,
    }


# ─────────────────────────────────────────────
# Permisos
# ─────────────────────────────────────────────

async def puede_aprobar(conn, solicitud_id: UUID, current_user_id: UUID, user_ctx: dict) -> bool:
    if user_has_module_access("rrhh", user_ctx, "editor"):
        return True
    solicitud = await db.get_solicitud(conn, solicitud_id)
    if not solicitud:
        return False
    empleado = await db.get_empleado_datos(conn, solicitud["usuario_id"])
    jefes = await db.get_jefes_ids(conn, solicitud["usuario_id"])
    aprobador_designado = empleado and empleado.get("id_aprobador_vacaciones") == current_user_id
    es_jefe = current_user_id in jefes
    return bool(aprobador_designado or es_jefe)


def puede_cancelar(solicitud: dict, current_user_id: UUID) -> bool:
    return solicitud["usuario_id"] == current_user_id and solicitud["estado"] == "pendiente"


async def es_jefe_o_aprobador_de_alguien(conn, user_id: UUID) -> bool:
    jefes_de = await db.get_empleados_donde_soy_jefe(conn, user_id)
    aprobador_de = await db.get_empleados_donde_soy_aprobador(conn, user_id)
    return bool(jefes_de or aprobador_de)


# ─────────────────────────────────────────────
# Solicitudes
# ─────────────────────────────────────────────

async def _validar_anticipo_vacaciones(conn, balance_info: dict, dias_solicitados: int) -> None:
    if not balance_info["periodos"]:
        return

    dias_efectivos = balance_info["dias_efectivos_disponibles"]
    nuevo_efectivo = dias_efectivos - dias_solicitados

    if not balance_info["anticipo_habilitado"]:
        if nuevo_efectivo < 0:
            raise ValueError(
                f"No tienes suficientes dias de vacaciones disponibles. "
                f"Disponibles: {max(0, dias_efectivos)} dias."
            )
        return

    max_anticipado = await ConfigService.get_global_config(conn, "VACACIONES_ANTICIPO_MAXIMO_DIAS", 7, int)
    if nuevo_efectivo < -max_anticipado:
        raise ValueError(
            f"Excede el limite de anticipacion de {max_anticipado} dias. "
            f"Dias disponibles: {max(0, dias_efectivos)}."
        )


async def crear_solicitud(
    conn,
    usuario_id: UUID,
    tipo_ausencia_id: UUID,
    fecha_inicio: date,
    fecha_fin: date,
    fecha_presentarse: date | None,
    observaciones: Optional[str],
) -> dict[str, Any]:
    """
    Crea una solicitud de ausencia. Valida: tipo, solapamiento, días hábiles, firma.
    Si el tipo afecta saldo, registra consumo FIFO.
    Retorna {'solicitud': ..., 'requiere_firma': bool, 'dias': int}.
    """
    tipo = await db.get_tipo_ausencia_by_id(conn, tipo_ausencia_id)
    if not tipo:
        raise ValueError("Tipo de ausencia no válido")

    festivos = await db.get_festivos_set(conn)
    dias = contar_dias_habiles(fecha_inicio, fecha_fin, festivos)
    if dias <= 0:
        raise ValueError("El rango seleccionado no contiene días hábiles")
    if fecha_presentarse is None:
        fecha_presentarse = siguiente_dia_habil(fecha_fin, festivos)

    solapadas = await db.get_solicitudes_activas_en_rango(conn, usuario_id, fecha_inicio, fecha_fin)
    if solapadas:
        raise ValueError("Ya existe una solicitud activa para ese rango de fechas")

    balance_info = None
    if tipo["afecta_saldo"] and tipo["slug"] in VACACIONES_SLUGS:
        balance_info = await get_balance_usuario(conn, usuario_id)
        await _validar_anticipo_vacaciones(conn, balance_info, dias)

    firma = await signatures_db.get_firma_usuario(conn, usuario_id)
    requiere_firma = firma is None

    solicitud = await db.create_solicitud(
        conn, usuario_id, tipo_ausencia_id, fecha_inicio, fecha_fin,
        dias, fecha_presentarse, observaciones,
        firma_solicitante_pendiente=requiere_firma,
    )
    solicitud_id = solicitud["id"]

    if not requiere_firma:
        await _registrar_consumos_si_aplica(conn, solicitud_id, usuario_id, tipo, dias, balance_info)
        await db.insert_firma_solicitud(conn, solicitud_id, usuario_id, "solicitante")
        await _notificar_aprobadores(conn, solicitud_id, solicitud)

    return {
        "solicitud": solicitud,
        "requiere_firma": requiere_firma,
        "dias": dias,
    }


async def cancelar_solicitud(conn, solicitud_id: UUID, current_user_id: UUID) -> None:
    solicitud = await db.get_solicitud(conn, solicitud_id)
    if not solicitud:
        raise ValueError("Solicitud no encontrada")
    if not puede_cancelar(solicitud, current_user_id):
        raise ValueError("Solo puedes cancelar tus solicitudes pendientes")

    await db.delete_consumos_solicitud(conn, solicitud_id)
    await db.update_solicitud_estado(conn, solicitud_id, "cancelado")
    await _recalcular_asistencia_por_solicitud(conn, solicitud)


async def aprobar_solicitud(
    conn,
    solicitud_id: UUID,
    aprobador_id: UUID,
    user_ctx: dict,
) -> dict:
    if not await puede_aprobar(conn, solicitud_id, aprobador_id, user_ctx):
        raise ValueError("No tienes permiso para aprobar esta solicitud")

    solicitud = await db.get_solicitud(conn, solicitud_id)
    if not solicitud:
        raise ValueError("Solicitud no encontrada")
    if solicitud["estado"] != "pendiente":
        raise ValueError("La solicitud ya fue resuelta")
    if solicitud.get("firma_solicitante_pendiente"):
        raise ValueError("La solicitud aun requiere firma del solicitante")
    firma_aprobador = await signatures_db.get_firma_usuario(conn, aprobador_id)
    if not firma_aprobador:
        raise ValueError("Registra tu firma en Mi Firma antes de aprobar solicitudes")

    await db.insert_firma_solicitud(conn, solicitud_id, aprobador_id, "aprobador")
    await db.update_solicitud_estado(conn, solicitud_id, "aprobado", aprobado_por=aprobador_id)
    aprobada = await db.get_solicitud(conn, solicitud_id)
    await _recalcular_asistencia_por_solicitud(conn, aprobada)

    from core.workflow.notification_service import get_notification_service
    notif = get_notification_service()
    await notif.notify_vacation_approved(conn, aprobada)
    return aprobada


async def rechazar_solicitud(
    conn,
    solicitud_id: UUID,
    aprobador_id: UUID,
    motivo: str,
    user_ctx: dict,
) -> None:
    motivo_limpio = (motivo or "").strip()
    if not motivo_limpio:
        raise ValueError("Debes indicar el motivo del rechazo")

    if not await puede_aprobar(conn, solicitud_id, aprobador_id, user_ctx):
        raise ValueError("No tienes permiso para rechazar esta solicitud")

    solicitud = await db.get_solicitud(conn, solicitud_id)
    if not solicitud:
        raise ValueError("Solicitud no encontrada")
    if solicitud["estado"] != "pendiente":
        raise ValueError("La solicitud ya fue resuelta")

    await db.delete_consumos_solicitud(conn, solicitud_id)
    await db.update_solicitud_estado(
        conn, solicitud_id, "rechazado", aprobado_por=aprobador_id, motivo_rechazo=motivo_limpio
    )
    rechazada = await db.get_solicitud(conn, solicitud_id)
    await _recalcular_asistencia_por_solicitud(conn, rechazada)
    from core.workflow.notification_service import get_notification_service
    notif = get_notification_service()
    await notif.notify_vacation_rejected(conn, rechazada, motivo_limpio)


# ─────────────────────────────────────────────
# Firmas
# ─────────────────────────────────────────────

async def _registrar_consumos_si_aplica(
    conn,
    solicitud_id: UUID,
    usuario_id: UUID,
    tipo: dict,
    dias: int,
    balance_info: dict | None = None,
) -> None:
    if not (tipo["afecta_saldo"] and tipo["slug"] in VACACIONES_SLUGS):
        return
    balance = balance_info or await get_balance_usuario(conn, usuario_id)
    if balance["periodos"]:
        consumos_fifo = asignar_consumo_fifo(balance["periodos"], dias)
        if consumos_fifo:
            await db.insert_consumos(conn, solicitud_id, consumos_fifo)


async def activar_solicitud_tras_firma(
    conn,
    solicitud_id: UUID,
    usuario_id: UUID,
) -> None:
    solicitud = await db.get_solicitud(conn, solicitud_id)
    if not solicitud:
        raise ValueError("Solicitud no encontrada")
    if solicitud["usuario_id"] != usuario_id:
        raise ValueError("No puedes firmar esta solicitud")
    if not solicitud.get("firma_solicitante_pendiente"):
        return
    tipo = await db.get_tipo_ausencia_by_id(conn, solicitud["tipo_ausencia_id"])
    if not tipo:
        raise ValueError("Tipo de ausencia no valido")
    await _registrar_consumos_si_aplica(
        conn, solicitud_id, usuario_id, tipo, solicitud["dias_solicitados"]
    )
    await db.completar_firma_solicitante(conn, solicitud_id)
    await _notificar_aprobadores(conn, solicitud_id, solicitud)


async def _notificar_aprobadores(conn, solicitud_id: UUID, solicitud: dict) -> None:
    aprobador_emails = await db.get_aprobador_emails(conn, solicitud_id)
    if not aprobador_emails:
        logger.warning("Solicitud %s sin aprobador ni RH para notificar", solicitud_id)
        return
    solicitud_notificacion = await db.get_solicitud(conn, solicitud_id)
    if not solicitud_notificacion:
        logger.warning("Solicitud %s no encontrada para notificar aprobadores", solicitud_id)
        return
    from core.workflow.notification_service import get_notification_service
    notif = get_notification_service()
    for aprobador_email in aprobador_emails:
        await notif.notify_vacation_request(conn, solicitud_notificacion, aprobador_email)
    await db.update_ultima_notificacion_aprobador(conn, solicitud_id)


async def _recalcular_asistencia_por_solicitud(conn, solicitud: dict | None) -> None:
    if not solicitud or solicitud.get("tipo_slug") not in VACACIONES_SLUGS:
        return
    fecha_inicio = solicitud["fecha_inicio"]
    fecha_fin = solicitud["fecha_fin"]
    targets = [
        (solicitud["usuario_id"], fecha_inicio + timedelta(days=offset))
        for offset in range((fecha_fin - fecha_inicio).days + 1)
    ]
    await recalcular_asistencia(conn, targets)


# ─────────────────────────────────────────────
# PDF
# ─────────────────────────────────────────────

async def generar_pdf_solicitud(conn, solicitud_id: UUID) -> bytes:
    from core.pdf_service.service import PDFService

    solicitud = await db.get_solicitud(conn, solicitud_id)
    if not solicitud:
        raise ValueError("Solicitud no encontrada")

    firmas_registradas = await db.get_firmas_solicitud(conn, solicitud_id)
    firmas_map = {f["rol_firma"]: f for f in firmas_registradas}

    firma_solicitante_b64 = None
    firma_aprobador_b64 = None

    if "solicitante" in firmas_map:
        row = await signatures_db.get_firma_usuario(conn, solicitud["usuario_id"])
        if row:
            firma_solicitante_b64 = base64.b64encode(bytes(row["firma_data"])).decode()

    if "aprobador" in firmas_map and solicitud["aprobado_por"]:
        row = await signatures_db.get_firma_usuario(conn, solicitud["aprobado_por"])
        if row:
            firma_aprobador_b64 = base64.b64encode(bytes(row["firma_data"])).decode()

    empleado = await db.get_empleado_datos(conn, solicitud["usuario_id"])
    detalle_periodos = await _get_detalle_periodos_pdf(conn, solicitud)
    folio = _generar_folio(solicitud)

    pdf_svc = PDFService()
    return await pdf_svc.generate(
        "solicitud_vacaciones.html",
        {
            "solicitud": solicitud,
            "empleado": empleado,
            "folio": folio,
            "firma_solicitante_b64": firma_solicitante_b64,
            "firma_aprobador_b64": firma_aprobador_b64,
            "firma_solicitante_info": firmas_map.get("solicitante"),
            "firma_aprobador_info": firmas_map.get("aprobador"),
            "detalle_periodos": detalle_periodos,
        },
    )


def _generar_folio(solicitud: dict) -> str:
    abrev = solicitud.get("tipo_abreviatura", "SOL")
    ts = solicitud["fecha_solicitud"]
    return f"FO-ADM-002-{abrev}{ts.strftime('%d%m%y%H%M')}"


async def _get_detalle_periodos_pdf(conn, solicitud: dict) -> list[dict]:
    consumos = await db.get_consumos_solicitud(conn, solicitud["id"])
    if not consumos:
        return []
    balance = await get_balance_usuario(conn, solicitud["usuario_id"])
    periodos = {
        p["num_periodo"]: p for p in (balance.get("periodos") or [])
    }
    detalle = []
    for consumo in consumos:
        periodo = periodos.get(consumo["num_periodo"], {})
        detalle.append({
            "num_periodo": consumo["num_periodo"],
            "periodo": periodo.get("periodo") or consumo["fecha_aniversario_periodo"].year,
            "dias_consumidos": consumo["dias_consumidos"],
            "dias_restantes": periodo.get("dias_restantes"),
            "fecha_expiracion": periodo.get("fecha_expiracion"),
        })
    return detalle


# ─────────────────────────────────────────────
# Balance batch (para listados de empleados)
# ─────────────────────────────────────────────

async def get_balances_por_ids(conn, ids: list[UUID]) -> dict:
    if not ids:
        return {}
    hoy = today_mx()
    catalogo = await db.get_catalogo_dias(conn)
    meses_exp = await ConfigService.get_global_config(conn, "VACACIONES_MESES_EXPIRACION", 18, int)
    empleados = await db.get_empleados_balance_base(conn, ids)
    uids = [emp["id_usuario"] for emp in empleados]
    consumos_por_usuario = await db.get_consumos_bulk(conn, uids)
    prorrogas_por_usuario = await db.get_prorrogas_activas_bulk(conn, uids)

    resultado = {}
    for emp in empleados:
        uid = emp["id_usuario"]
        if not emp.get("fecha_contratacion"):
            resultado[uid] = {"periodos": None, "total_disponible": 0, "saldo_neto": 0}
        else:
            periodos = calcular_periodos(
                emp["fecha_contratacion"],
                hoy,
                catalogo,
                ajuste_dias=emp.get("dias_vacaciones_ajuste") or 0,
                meses_expiracion=meses_exp,
            )
            periodos_balance = calcular_balance(
                periodos,
                consumos_por_usuario.get(uid, []),
                prorrogas=prorrogas_por_usuario.get(uid, []),
            )
            periodos_activos = [
                p for p in periodos_balance
                if not p.get("es_proximo") and not p.get("expirado")
            ]
            total_disponible = sum(max(p["dias_restantes"], 0) for p in periodos_activos)
            saldo_neto = _saldo_neto(periodos_balance)
            resultado[uid] = {
                "periodos": periodos_balance,
                "total_disponible": total_disponible,
                "saldo_neto": saldo_neto,
            }
    return resultado


# ─────────────────────────────────────────────
# Vista equipo
# ─────────────────────────────────────────────

async def get_equipo_balances(conn, user_id: UUID, user_ctx: dict) -> list[dict]:
    """Balances de todos los empleados que este usuario gerencia."""
    ids_jefe = await db.get_empleados_donde_soy_jefe(conn, user_id)
    ids_aprobador = await db.get_empleados_donde_soy_aprobador(conn, user_id)
    all_ids = list({*ids_jefe, *ids_aprobador})

    if not all_ids:
        return []

    hoy = today_mx()
    catalogo = await db.get_catalogo_dias(conn)
    meses_exp = await ConfigService.get_global_config(
        conn, "VACACIONES_MESES_EXPIRACION", 18, int
    )
    empleados = await db.get_empleados_balance_base(conn, all_ids)
    uids = [emp["id_usuario"] for emp in empleados]
    consumos_por_usuario = await db.get_consumos_bulk(conn, uids)
    prorrogas_por_usuario = await db.get_prorrogas_activas_bulk(conn, uids)

    resultados = []
    for emp in empleados:
        empleado = {
            "id": emp.get("empleado_datos_id"),
            "usuario_id": emp["id_usuario"],
            "numero_empleado": emp.get("numero_empleado"),
            "fecha_contratacion": emp.get("fecha_contratacion"),
            "puesto": emp.get("puesto"),
            "departamento": emp.get("departamento"),
            "id_aprobador_vacaciones": emp.get("id_aprobador_vacaciones"),
            "dias_vacaciones_ajuste": emp.get("dias_vacaciones_ajuste") or 0,
        }
        uid = emp["id_usuario"]
        if not empleado["fecha_contratacion"]:
            balance = {
                "empleado": empleado,
                "periodos": None,
                "progreso": None,
                "total_disponible": 0,
            }
        else:
            periodos = calcular_periodos(
                empleado["fecha_contratacion"],
                hoy,
                catalogo,
                ajuste_dias=empleado["dias_vacaciones_ajuste"],
                meses_expiracion=meses_exp,
            )
            periodos_balance = calcular_balance(
                periodos,
                consumos_por_usuario.get(uid, []),
                prorrogas=prorrogas_por_usuario.get(uid, []),
            )
            progreso = calcular_progreso(empleado["fecha_contratacion"], hoy, catalogo)
            total_disponible = sum(
                max(p["dias_restantes"], 0)
                for p in periodos_balance
                if not p.get("es_proximo") and not p.get("expirado")
            )
            balance = {
                "empleado": empleado,
                "periodos": periodos_balance,
                "progreso": progreso,
                "total_disponible": total_disponible,
            }

        resultados.append({
            "usuario": {
                "id_usuario": emp["id_usuario"],
                "nombre": emp["nombre"],
                "email": emp["email"],
            },
            "balance": balance,
        })
    return resultados


async def get_equipo_dashboard(conn, user_id: UUID, user_ctx: dict) -> dict:
    equipo = await get_equipo_balances(conn, user_id, user_ctx)
    usuario_ids = [item["usuario"]["id_usuario"] for item in equipo]
    hoy = today_mx()
    if not usuario_ids:
        return {
            "equipo": [],
            "vacaciones_actuales": [],
            "vacaciones_proximas": [],
            "horas_extra_pendientes": [],
            "horas_extra_pendientes_json": [],
            "hoy": hoy,
        }

    vacaciones = await db.get_vacaciones_aprobadas_equipo(
        conn,
        usuario_ids,
        hoy,
    )
    vacaciones_actuales = [
        row for row in vacaciones if row["fecha_inicio"] <= hoy <= row["fecha_fin"]
    ]
    vacaciones_proximas = [
        row for row in vacaciones if row["fecha_inicio"] > hoy
    ]

    horas_extra = await asistencia_db.get_horas_extra_equipo(
        conn,
        usuario_ids,
        hoy - timedelta(days=30),
        hoy,
    )
    horas_extra_json = []
    grupos_map: dict[str, dict] = {}
    for row in horas_extra:
        row["extra_fmt"] = format_minutes(row.get("minutos_extra") or 0)
        row["entrada_fmt"] = fmt_time_mx(row.get("primera_entrada"))
        row["salida_fmt"] = fmt_time_mx(row.get("ultima_salida"))
        horas_extra_json.append({
            "id": str(row["id"]),
            "usuario_id": str(row["usuario_id"]),
            "empleado_nombre": row["empleado_nombre"],
            "minutos_extra": int(row.get("minutos_extra") or 0),
            "horas_extra_estado": row.get("horas_extra_estado", "pendiente"),
            "motivo_solicitud": row.get("motivo_solicitud"),
            "entrada_fmt": row["entrada_fmt"],
            "salida_fmt": row["salida_fmt"],
        })
        uid = str(row["usuario_id"])
        if uid not in grupos_map:
            grupos_map[uid] = {
                "usuario_id": uid,
                "empleado_nombre": row["empleado_nombre"],
                "rows": [],
                "tiene_solicitado": False,
            }
        grupos_map[uid]["rows"].append(row)
        if row.get("horas_extra_estado") == "solicitado":
            grupos_map[uid]["tiene_solicitado"] = True

    return {
        "equipo": equipo,
        "vacaciones_actuales": vacaciones_actuales,
        "vacaciones_proximas": vacaciones_proximas,
        "horas_extra_pendientes": horas_extra,
        "horas_extra_grupos": list(grupos_map.values()),
        "horas_extra_pendientes_json": horas_extra_json,
        "hoy": hoy,
    }


