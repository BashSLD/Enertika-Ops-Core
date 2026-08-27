from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import List, Optional
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.templating import Jinja2Templates
from openpyxl.styles import Font

from core.database import DB_REPORT_ERRORS, get_db_connection
from core.jinja_filters import register_timezone_filters
from core.permissions import require_manager_access, require_module_access
from core.security import get_current_user_context
from modules.asistencia import db_service as asistencia_db
from modules.asistencia import service as asistencia_service
from modules.asistencia.constants import (
    ASISTENCIA_ESTADO_LABELS,
    ASISTENCIA_ESTADOS,
    formatear_estado_asistencia_label,
)
from modules.asistencia.logic import ensure_mx
from modules.rrhh import service
from modules.rrhh.excel_utils import autofit_columns, format_date, format_datetime, style_sheet
from modules.shared.utils import excel_response, format_minutes, is_htmx, toast_error
from modules.vacaciones import db_service as vac_db
from modules.vacaciones import service as vac_service
from modules.vacaciones.constants import TIPO_COMPENSATORIO
from core.timezone import today_mx

logger = logging.getLogger("rrhh.router")
router = APIRouter(prefix="/rrhh", tags=["rrhh"])
templates = Jinja2Templates(directory="templates")
register_timezone_filters(templates.env)

REPORTE_ASISTENCIA_PREFIJOS = {
    "consolidado": "Rep_HorasConsolidado",
    "detalle": "Rep_AsistenciaCompleto",
    "departamentos": "Rep_AsistenciaDepto",
    "completo": "FullReport",
}

RRHH_TAB_ENDPOINTS = {
    "asistencia": "/rrhh/asistencia",
    "ausencias": "/rrhh/ausencias",
    "aprobaciones": "/rrhh/aprobaciones",
    "solicitudes": "/rrhh/solicitudes",
    "empleados": "/rrhh/empleados",
    "reportes": "/rrhh/reportes",
    "festivos": "/rrhh/festivos",
    "admin": "/rrhh/admin",
}

RRHH_VIEWER_TABS = {"ausencias", "aprobaciones", "solicitudes", "empleados"}
RRHH_EDITOR_TABS = {"asistencia", "reportes", "festivos"}
RRHH_DETAIL_ORIGENES = {"rrhh_aprobaciones", "rrhh_solicitudes"}


def _parse_optional_uuid(value: Optional[str], field_name: str) -> Optional[UUID]:
    if not value:
        return None
    try:
        return UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{field_name} no es un UUID valido") from exc


def _parse_uuid_list(values: List[str], field_name: str) -> list[UUID]:
    try:
        return [UUID(v) for v in values if v]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{field_name} contiene un ID no valido") from exc


def _migracion_preview_error(request: Request, message: str, status_code: int = 200):
    return templates.TemplateResponse(
        request,
        "rrhh/partials/migracion_preview.html",
        {"error": message},
        status_code=status_code,
    )


def _has_rrhh_admin_access(context: dict) -> bool:
    rrhh_role = (context.get("module_roles") or {}).get("rrhh", "")
    return (
        context.get("role") == "ADMIN"
        or rrhh_role == "admin"
        or (context.get("role") == "MANAGER" and rrhh_role in {"editor", "admin"})
    )


def _get_rrhh_permissions(context: dict) -> dict:
    rrhh_role = (context.get("module_roles") or {}).get("rrhh", "")
    is_admin = context.get("role") == "ADMIN"
    can_view = is_admin or bool(rrhh_role)
    can_edit = is_admin or rrhh_role in {"editor", "admin"}
    can_admin = _has_rrhh_admin_access(context)
    is_viewer_only = can_view and not can_edit
    return {
        "role": rrhh_role,
        "can_view": can_view,
        "can_edit": can_edit,
        "can_admin": can_admin,
        "can_reports": can_edit,
        "can_manage_horas_extra": can_edit,
        "is_viewer_only": is_viewer_only,
        "show_asistencia": not is_viewer_only,
        "show_ausencias": can_view,
        "show_aprobaciones": can_view,
        "show_solicitudes": can_view,
        "show_empleados": can_view,
        "show_reportes": can_edit,
        "show_festivos": can_edit,
        "show_admin": can_admin,
    }


def _resolve_initial_tab(
    tab: Optional[str],
    anio: Optional[int],
    perms: dict,
    solicitud_id: Optional[UUID] = None,
    origen: str = "rrhh_solicitudes",
    solo_consulta: bool = False,
) -> tuple[str, str]:
    if solicitud_id:
        origen = origen if origen in RRHH_DETAIL_ORIGENES else "rrhh_solicitudes"
        initial_tab = "aprobaciones" if origen == "rrhh_aprobaciones" else "solicitudes"
        endpoint = f"/vacaciones/solicitudes/{solicitud_id}?origen={origen}"
        if solo_consulta or origen == "rrhh_solicitudes" or perms["is_viewer_only"]:
            endpoint = f"{endpoint}&solo_consulta=1"
        return initial_tab, endpoint

    default_tab = "ausencias" if perms["is_viewer_only"] else "asistencia"
    initial_tab = tab if tab in RRHH_TAB_ENDPOINTS else default_tab
    if perms["is_viewer_only"] and initial_tab not in RRHH_VIEWER_TABS:
        initial_tab = default_tab
    if initial_tab == "admin" and not perms["can_admin"]:
        initial_tab = default_tab
    if initial_tab in RRHH_EDITOR_TABS and not perms["can_edit"]:
        initial_tab = default_tab
    endpoint = RRHH_TAB_ENDPOINTS[initial_tab]
    if initial_tab == "festivos":
        endpoint = f"{endpoint}?anio={anio or today_mx().year}"
    return initial_tab, endpoint


async def _festivos_template_response(
    request: Request,
    conn,
    context: dict,
    anio: Optional[int],
    *,
    toast_type: Optional[str] = None,
    toast_msg: Optional[str] = None,
):
    ctx = await service.get_festivos_ctx(conn, anio)
    validacion = ctx.get("validacion") or {}
    if validacion.get("validado_at"):
        validacion["validado_at_fmt"] = format_datetime(validacion["validado_at"])
    ctx.update({
        "context": context,
        "rrhh_perms": _get_rrhh_permissions(context),
        "toast_type": toast_type,
        "toast_msg": toast_msg,
    })
    return templates.TemplateResponse(request, "rrhh/partials/festivos_lista.html", ctx)


def _build_horario_dias_form(
    dia_semana: List[int],
    dias_laborales: Optional[List[int]],
    hora_entrada: List[str],
    hora_salida: List[str],
    descuento_comida_min_dia: List[int],
) -> list[dict]:
    campos_semana = (dia_semana, hora_entrada, hora_salida, descuento_comida_min_dia)
    if any(len(campo) != 7 for campo in campos_semana):
        raise ValueError("Debes enviar la configuracion completa de lunes a domingo")
    laborables = set(dias_laborales or [])
    return [
        {
            "dia_semana": dia,
            "es_laboral": dia in laborables,
            "hora_entrada": hora_entrada[index],
            "hora_salida": hora_salida[index],
            "descuento_comida_min": descuento_comida_min_dia[index],
        }
        for index, dia in enumerate(dia_semana)
    ]


_ESTADO_APROBACION_HE_LABELS = {
    "aprobado": "Aprobado",
    "omitido": "Descartado",
}


def _format_estado_aprobacion_he(horas_extra_estado: str | None) -> str:
    return _ESTADO_APROBACION_HE_LABELS.get(horas_extra_estado, "Pendiente")


def _build_workbook(title: str, headers: list[str], rows: list[list]):
    from openpyxl import Workbook

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = title
    style_sheet(worksheet, headers)
    for row in rows:
        worksheet.append(row)
    autofit_columns(worksheet)
    return workbook


# ─────────────────────────────────────────────
# Dashboard principal
# ─────────────────────────────────────────────

@router.get("/ui")
async def rrhh_ui(
    request: Request,
    tab: Optional[str] = None,
    anio: Optional[int] = None,
    solicitud_id: Optional[UUID] = None,
    origen: str = "rrhh_solicitudes",
    solo_consulta: bool = False,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("rrhh", "viewer"),
):
    data = await service.get_dashboard_data(conn)
    rrhh_perms = _get_rrhh_permissions(context)
    initial_tab, initial_endpoint = _resolve_initial_tab(
        tab,
        anio,
        rrhh_perms,
        solicitud_id=solicitud_id,
        origen=origen,
        solo_consulta=solo_consulta,
    )
    ctx = {
        **data,
        "context": context,
        "user_name": context.get("user_name"),
        "role": context.get("role"),
        "module_roles": context.get("module_roles", {}),
        "rrhh_perms": rrhh_perms,
        "initial_tab": initial_tab,
        "initial_endpoint": initial_endpoint,
    }
    if is_htmx(request):
        return templates.TemplateResponse(request, "rrhh/partials/content.html", ctx)
    return templates.TemplateResponse(request, "rrhh/dashboard.html", ctx)


# ─────────────────────────────────────────────
# Vacaciones hoy
# ─────────────────────────────────────────────

@router.get("/vacaciones-hoy")
async def vacaciones_hoy(
    request: Request,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("rrhh", "viewer"),
):
    hoy = today_mx()
    vacaciones = await vac_db.get_vacaciones_hoy(conn, hoy)
    return templates.TemplateResponse(
        request, "rrhh/partials/vacaciones_hoy.html",
        {"vacaciones_hoy": vacaciones, "hoy": hoy},
    )


# ─────────────────────────────────────────────
# Ausencias (todas las solicitudes aprobadas activas)
# ─────────────────────────────────────────────

@router.get("/ausencias")
async def ausencias_panel(
    request: Request,
    fecha_inicio: Optional[date] = None,
    fecha_fin: Optional[date] = None,
    tipo: Optional[str] = None,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("rrhh", "viewer"),
):
    hoy = today_mx()
    fi = fecha_inicio or hoy
    ff = fecha_fin or hoy
    if ff < fi:
        ff = fi
    tipo_slug = tipo or None
    ausencias_hoy = await vac_db.get_ausencias_activas(conn, fi, ff, tipo_slug=tipo_slug)
    # Ventana amplia para "proximas": arranca justo despues del rango filtrado. No basta con
    # que la ventana de consulta no se traslape con [fi, ff] -- get_ausencias_activas hace un
    # OVERLAPS contra fecha_inicio/fecha_fin de la solicitud completa, asi que una ausencia
    # larga que ya empezo dentro de [fi, ff] pero termina despues tambien matchea esta segunda
    # ventana. Se filtra en Python por fecha_inicio > ff para quedarnos solo con las que aun no
    # empiezan -- las que ya estan en curso solo deben aparecer en "Actualmente ausentes".
    proximas_inicio = max(ff, hoy) + timedelta(days=1)
    proximas_fin = proximas_inicio + timedelta(days=89)
    ausencias_proximas = await vac_db.get_ausencias_activas(
        conn, proximas_inicio, proximas_fin, tipo_slug=tipo_slug
    )
    ausencias_proximas = [a for a in ausencias_proximas if a["fecha_inicio"] > ff]
    tipos = await vac_db.get_tipos_ausencia(conn)
    tipos.append(TIPO_COMPENSATORIO)
    return templates.TemplateResponse(
        request, "rrhh/partials/ausencias.html",
        {
            "ausencias_hoy": ausencias_hoy,
            "ausencias_proximas": ausencias_proximas,
            "tipos": tipos,
            "fecha_inicio": fi,
            "fecha_fin": ff,
            "tipo_filtro": tipo or "",
            "hoy": hoy,
        },
    )


# ─────────────────────────────────────────────
# Aprobaciones pendientes (vista RH global)
# ─────────────────────────────────────────────

@router.get("/aprobaciones")
async def aprobaciones_pendientes(
    request: Request,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("rrhh", "viewer"),
):
    rrhh_perms = _get_rrhh_permissions(context)
    ctx = await service.get_aprobaciones_ctx_rrhh_svc(conn, context, rrhh_perms)
    return templates.TemplateResponse(request, "rrhh/partials/aprobaciones_pendientes.html", ctx)


# ─────────────────────────────────────────────
# Gestión de empleados
# ─────────────────────────────────────────────

@router.get("/empleados")
async def empleados_lista(
    request: Request,
    offset: int = 0,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("rrhh", "viewer"),
):
    empleados = await vac_db.get_all_empleados_con_datos(conn, limit=50, offset=offset)
    total = await vac_db.count_empleados(conn)
    ids = [emp["id_usuario"] for emp in empleados]
    balances = await vac_service.get_balances_por_ids(conn, ids)
    return templates.TemplateResponse(
        request, "rrhh/partials/empleados_lista.html",
        {
            "empleados": empleados,
            "total": total,
            "offset": offset,
            "balances": balances,
            "rrhh_perms": _get_rrhh_permissions(context),
        },
    )


@router.get("/empleados/exportar-excel")
async def empleados_exportar_excel(
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("rrhh", "editor"),
    sucursal_id: List[str] = Query(default=[]),
    usuario_id: List[str] = Query(default=[]),
    incluir_dados_de_baja: bool = False,
):
    sids = _parse_uuid_list(sucursal_id, "sucursal_id")
    uids = _parse_uuid_list(usuario_id, "usuario_id")
    headers, rows, filename = await service.build_empleados_vacaciones_export(
        conn,
        sucursal_ids=sids or None,
        usuario_ids=uids or None,
        incluir_dados_de_baja=incluir_dados_de_baja,
    )
    workbook = _build_workbook("Vacaciones", headers, rows)
    return excel_response(workbook, filename)


@router.get("/reportes")
async def reportes_panel(
    request: Request,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("rrhh", "editor"),
):
    ctx = await service.get_reportes_ctx(conn)
    ctx["context"] = context
    ctx["rrhh_perms"] = _get_rrhh_permissions(context)
    return templates.TemplateResponse(request, "rrhh/partials/reportes.html", ctx)


@router.get("/reportes/asistencia.xlsx")
async def reporte_asistencia_excel(
    fecha_inicio: date,
    fecha_fin: date,
    formato: str = "completo",
    usuario_id: List[str] = Query(default=[]),
    sucursal_id: List[str] = Query(default=[]),
    estado: List[str] = Query(default=[]),
    incluir_dados_de_baja: bool = False,
    incluir_descanso: bool = False,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("rrhh", "editor"),
):
    uids = _parse_uuid_list(usuario_id, "usuario_id")
    sids = _parse_uuid_list(sucursal_id, "sucursal_id")
    estados_clean = [e for e in estado if e]
    try:
        service.validar_rango_reportes(fecha_inicio, fecha_fin)
        service.validar_formato_reporte_asistencia(formato)
        rows = await asistencia_db.get_reporte_asistencia(
            conn,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            usuario_ids=uids or None,
            sucursal_ids=sids or None,
            estados=estados_clean or None,
            incluir_dados_de_baja=incluir_dados_de_baja,
            incluir_descanso=incluir_descanso,
            limit=None,
        )
        unmapped = await asistencia_db.get_unmapped_biotime_checks_summary(
            conn,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
        )
        workbook = service.build_reporte_asistencia_workbook(rows, unmapped, formato)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DB_REPORT_ERRORS as exc:
        logger.exception("Error de BD generando reporte de asistencia")
        raise HTTPException(status_code=500, detail="No se pudo generar el reporte") from exc

    prefijo = REPORTE_ASISTENCIA_PREFIJOS[formato]
    filename = f"{prefijo}_{fecha_inicio:%y%m%d}_{fecha_fin:%y%m%d}.xlsx"
    return excel_response(workbook, filename)


@router.get("/reportes/vacaciones.xlsx")
async def reporte_vacaciones_excel(
    fecha_inicio: date,
    fecha_fin: date,
    usuario_id: List[str] = Query(default=[]),
    estado: Optional[str] = None,
    incluir_dados_de_baja: bool = False,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("rrhh", "editor"),
):
    uids = _parse_uuid_list(usuario_id, "usuario_id")
    try:
        service.validar_rango_reportes(fecha_inicio, fecha_fin)
        rows = await service.get_reporte_vacaciones(
            conn,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            usuario_ids=uids or None,
            estado=estado or None,
            incluir_dados_de_baja=incluir_dados_de_baja,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DB_REPORT_ERRORS as exc:
        logger.exception("Error de BD generando reporte de vacaciones")
        raise HTTPException(status_code=500, detail="No se pudo generar el reporte") from exc

    workbook = _build_workbook(
        "Vacaciones",
        [
            "Empleado",
            "Email",
            "No. empleado",
            "Departamento",
            "Inicio",
            "Fin",
            "Dias",
            "Fecha a presentarse",
            "Estado",
            "Fecha solicitud",
            "Fecha resolucion",
            "Aprobado por",
        ],
        [
            [
                row.get("empleado_nombre") or "",
                row.get("empleado_email") or "",
                row.get("numero_empleado") or "",
                row.get("departamento") or "",
                format_date(row.get("fecha_inicio")),
                format_date(row.get("fecha_fin")),
                row.get("dias_solicitados") or 0,
                format_date(row.get("fecha_presentarse")),
                row.get("estado") or "",
                format_datetime(row.get("fecha_solicitud")),
                format_datetime(row.get("fecha_resolucion")),
                row.get("aprobado_por_nombre") or "",
            ]
            for row in rows
        ],
    )
    filename = f"reporte_vacaciones_{fecha_inicio:%Y%m%d}_{fecha_fin:%Y%m%d}.xlsx"
    return excel_response(workbook, filename)


@router.get("/reportes/vacaciones-aprobadas.xlsx")
async def reporte_vacaciones_aprobadas_excel(
    usuario_id: List[str] = Query(default=[]),
    incluir_dados_de_baja: bool = False,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("rrhh", "editor"),
):
    uids = _parse_uuid_list(usuario_id, "usuario_id")
    try:
        rows = await service.get_vacaciones_aprobadas(
            conn,
            fecha_desde=today_mx(),
            usuario_ids=uids or None,
            incluir_dados_de_baja=incluir_dados_de_baja,
        )
    except DB_REPORT_ERRORS as exc:
        logger.exception("Error de BD generando reporte de vacaciones aprobadas")
        raise HTTPException(status_code=500, detail="No se pudo generar el reporte") from exc

    workbook = _build_workbook(
        "Vacaciones aprobadas",
        [
            "Empleado",
            "Email",
            "No. empleado",
            "Departamento",
            "Inicio",
            "Fin",
            "Dias",
            "Fecha a presentarse",
            "Fecha solicitud",
            "Aprobado por",
        ],
        [
            [
                row.get("empleado_nombre") or "",
                row.get("empleado_email") or "",
                row.get("numero_empleado") or "",
                row.get("departamento") or "",
                format_date(row.get("fecha_inicio")),
                format_date(row.get("fecha_fin")),
                row.get("dias_solicitados") or 0,
                format_date(row.get("fecha_presentarse")),
                format_datetime(row.get("fecha_solicitud")),
                row.get("aprobado_por_nombre") or "",
            ]
            for row in rows
        ],
    )
    hoy = today_mx()
    filename = f"vacaciones_aprobadas_{hoy:%Y%m%d}.xlsx"
    return excel_response(workbook, filename)


@router.get("/reportes/horas-extra.xlsx")
async def reporte_horas_extra_excel(
    fecha_inicio: date,
    fecha_fin: date,
    usuario_id: List[str] = Query(default=[]),
    sucursal_id: List[str] = Query(default=[]),
    incluir_dados_de_baja: bool = False,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("rrhh", "editor"),
):
    uids = _parse_uuid_list(usuario_id, "usuario_id")
    sids = _parse_uuid_list(sucursal_id, "sucursal_id")
    try:
        service.validar_rango_reportes(fecha_inicio, fecha_fin)
        rows = await asistencia_db.get_reporte_asistencia(
            conn,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            usuario_ids=uids or None,
            sucursal_ids=sids or None,
            solo_horas_extra=True,
            incluir_dados_de_baja=incluir_dados_de_baja,
            limit=None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DB_REPORT_ERRORS as exc:
        logger.exception("Error de BD generando reporte de horas extra")
        raise HTTPException(status_code=500, detail="No se pudo generar el reporte") from exc

    workbook = _build_workbook(
        "Horas extra",
        [
            "Fecha",
            "Empleado",
            "Sucursal",
            "Primera entrada",
            "Ultima salida",
            "Horas trabajadas",
            "Horas a cubrir",
            "Horas extra",
            "Estado",
            "Observaciones",
            "Motivo solicitud",
            "Estado aprobacion",
            "Horas aprobadas",
            "Comentario Aprobado/Rechazado",
        ],
        [
            [
                format_date(row["fecha_laboral"]),
                row.get("empleado_nombre") or "",
                row.get("sucursal_nombre") or "",
                format_datetime(row.get("primera_entrada")),
                format_datetime(row.get("ultima_salida")),
                format_minutes(row.get("minutos_trabajados")),
                format_minutes(row.get("minutos_programados")),
                format_minutes(row.get("minutos_extra")),
                formatear_estado_asistencia_label(row.get("estado"), row.get("tipo_ausencia_nombre")),
                row.get("observaciones") or "",
                row.get("motivo_solicitud") or "—",
                _format_estado_aprobacion_he(row.get("horas_extra_estado")),
                format_minutes(row.get("minutos_aprobados")) if row.get("minutos_aprobados") else "—",
                row.get("aprobacion_comentario") or row.get("horas_extra_motivo_rechazo") or "—",
            ]
            for row in rows
        ],
    )
    worksheet = workbook.active
    bold_font = Font(bold=True)
    for offset, row in enumerate(rows, start=2):
        if row.get("horas_extra_estado") in ("aprobado", "omitido"):
            for cell in worksheet[offset]:
                cell.font = bold_font
    filename = f"Rep_HrExtra_{fecha_inicio:%y%m%d}_{fecha_fin:%y%m%d}.xlsx"
    return excel_response(workbook, filename)


@router.get("/empleados/{usuario_id}/editar")
async def empleado_editar_form(
    request: Request,
    usuario_id: UUID,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("rrhh", "editor"),
):
    ctx = await service.get_empleado_edit_ctx(conn, usuario_id)
    return templates.TemplateResponse(request, "rrhh/partials/empleado_editar.html", ctx)


@router.post("/empleados/{usuario_id}")
async def empleado_guardar(
    request: Request,
    usuario_id: UUID,
    numero_empleado: Optional[str] = Form(None),
    fecha_contratacion: Optional[date] = Form(None),
    puesto: Optional[str] = Form(None),
    department_slug: Optional[str] = Form(None),
    sucursal_id: Optional[UUID] = Form(None),
    id_aprobador_vacaciones: Optional[UUID] = Form(None),
    dias_vacaciones_ajuste: Optional[int] = Form(None),
    jefes_ids: List[UUID] = Form(default=[]),
    accion_aprobador_he: str = Form("regla_normal"),
    id_aprobador_horas_extra: Optional[UUID] = Form(None),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("rrhh", "editor"),
):
    try:
        await service.guardar_empleado(
            conn,
            usuario_id=usuario_id,
            numero_empleado=numero_empleado or None,
            fecha_contratacion=fecha_contratacion,
            puesto=puesto or None,
            department_slug=department_slug,
            sucursal_id=sucursal_id,
            id_aprobador_vacaciones=id_aprobador_vacaciones,
            dias_vacaciones_ajuste=dias_vacaciones_ajuste,
            jefes_ids=jefes_ids,
            updated_by=UUID(str(context["user_db_id"])),
            accion_aprobador_he=accion_aprobador_he,
            id_aprobador_horas_extra_input=id_aprobador_horas_extra,
        )
    except ValueError as e:
        return toast_error(request, str(e))

    filas = await vac_db.get_all_empleados_con_datos(
        conn, limit=1, offset=0, usuario_ids=[usuario_id], incluir_dados_de_baja=True
    )
    emp = filas[0] if filas else None
    balances = await vac_service.get_balances_por_ids(conn, [usuario_id])
    return templates.TemplateResponse(
        request, "rrhh/partials/empleado_guardado.html",
        {
            "emp": emp,
            "balance": balances.get(usuario_id),
            "can_edit_rrhh": _get_rrhh_permissions(context)["can_edit"],
        },
    )


# ─────────────────────────────────────────────
# Prórrogas de vacaciones
# ─────────────────────────────────────────────

@router.get("/empleados/{usuario_id}/prorrogas")
async def empleado_prorrogas(
    request: Request,
    usuario_id: UUID,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("rrhh", "editor"),
):
    ctx = await service.get_prorrogas_empleado_ctx(conn, usuario_id)
    ctx["context"] = context
    return templates.TemplateResponse(request, "rrhh/partials/prorrogas_vacaciones.html", ctx)


@router.post("/empleados/{usuario_id}/prorrogas")
async def empleado_prorrogas_crear(
    request: Request,
    usuario_id: UUID,
    num_periodo: int = Form(...),
    fecha_aniversario_periodo: date = Form(...),
    dias_prorrogados: int = Form(...),
    fecha_expiracion_prorroga: date = Form(...),
    motivo: str = Form(...),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("rrhh", "editor"),
):
    try:
        await service.crear_prorroga_vacaciones(
            conn,
            usuario_id=usuario_id,
            num_periodo=num_periodo,
            fecha_aniversario_periodo=fecha_aniversario_periodo,
            dias_prorrogados=dias_prorrogados,
            fecha_expiracion_prorroga=fecha_expiracion_prorroga,
            motivo=motivo,
            created_by=UUID(str(context["user_db_id"])),
        )
    except ValueError as e:
        return toast_error(request, str(e))
    except asyncpg.PostgresError:
        logger.exception("Error DB al crear prorroga usuario_id=%s", usuario_id)
        return toast_error(request, "Error al guardar la prórroga")
    ctx = await service.get_prorrogas_empleado_ctx(conn, usuario_id)
    ctx["context"] = context
    ctx["toast_type"] = "success"
    ctx["toast_msg"] = "Prórroga otorgada correctamente"
    return templates.TemplateResponse(request, "rrhh/partials/prorrogas_vacaciones.html", ctx)


@router.post("/prorrogas/{prorroga_id}/cancelar")
async def prorroga_cancelar(
    request: Request,
    prorroga_id: UUID,
    usuario_id: UUID = Form(...),
    motivo_cancelacion: str = Form(...),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("rrhh", "editor"),
):
    try:
        await service.cancelar_prorroga_vacaciones(
            conn,
            prorroga_id=prorroga_id,
            motivo_cancelacion=motivo_cancelacion,
            cancelled_by=UUID(str(context["user_db_id"])),
        )
    except ValueError as e:
        return toast_error(request, str(e))
    except asyncpg.PostgresError:
        logger.exception("Error DB al cancelar prorroga prorroga_id=%s", prorroga_id)
        return toast_error(request, "Error al cancelar la prórroga")
    ctx = await service.get_prorrogas_empleado_ctx(conn, usuario_id)
    ctx["context"] = context
    ctx["toast_type"] = "success"
    ctx["toast_msg"] = "Prórroga cancelada"
    return templates.TemplateResponse(request, "rrhh/partials/prorrogas_vacaciones.html", ctx)


# ─────────────────────────────────────────────
# Admin RRHH
# ─────────────────────────────────────────────

@router.get("/migracion")
async def migracion_vacaciones(
    request: Request,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_manager_access("rrhh", "editor"),
):
    ctx = await service.get_migracion_ctx(conn)
    ctx["context"] = context
    ctx["user_name"] = context.get("user_name")
    ctx["role"] = context.get("role")
    ctx["module_roles"] = context.get("module_roles", {})
    if is_htmx(request):
        return templates.TemplateResponse(request, "rrhh/partials/migracion.html", ctx)
    return templates.TemplateResponse(request, "rrhh/migracion_page.html", ctx)


@router.get("/migracion/plantilla")
async def migracion_vacaciones_plantilla(
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_manager_access("rrhh", "editor"),
):
    workbook = await service.generar_plantilla_migracion(conn)
    return excel_response(workbook, "plantilla_migracion_vacaciones.xlsx")


@router.post("/migracion/importar")
async def migracion_vacaciones_importar(
    request: Request,
    archivo: UploadFile = File(...),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_manager_access("rrhh", "editor"),
):
    filename = (archivo.filename or "").lower()
    if not filename.endswith((".xlsx", ".xlsm")):
        return _migracion_preview_error(
            request,
            "Sube un archivo .xlsx o .xlsm generado desde la plantilla.",
        )

    try:
        preview = await service.validar_importacion_migracion(conn, await archivo.read())
    except ValueError as exc:
        return _migracion_preview_error(request, str(exc))
    except asyncpg.PostgresError:
        logger.exception("Error de BD validando importacion de vacaciones")
        return _migracion_preview_error(request, "No se pudo validar el archivo.", 500)

    return templates.TemplateResponse(
        request,
        "rrhh/partials/migracion_preview.html",
        {"preview": preview},
    )


@router.post("/migracion/confirmar")
async def migracion_vacaciones_confirmar(
    request: Request,
    token: str = Form(...),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_manager_access("rrhh", "editor"),
):
    try:
        resultado = await service.ejecutar_migracion(
            conn,
            token,
            ejecutado_por=UUID(str(context["user_db_id"])),
        )
        ctx = await service.get_migracion_ctx(conn)
        ctx.update({
            "context": context,
            "toast_type": "success",
            "toast_msg": (
                f"Migración aplicada: {resultado['empleados_actualizados']} empleados, "
                f"{resultado['dias_insertados']} dias."
            ),
        })
    except ValueError as exc:
        ctx = await service.get_migracion_ctx(conn)
        ctx.update({"context": context, "toast_type": "error", "toast_msg": str(exc)})
    except asyncpg.PostgresError:
        logger.exception("Error de BD confirmando migracion de vacaciones")
        ctx = await service.get_migracion_ctx(conn)
        ctx.update({
            "context": context,
            "toast_type": "error",
            "toast_msg": "No se pudo aplicar la migracion.",
        })
    return templates.TemplateResponse(request, "rrhh/partials/migracion.html", ctx)


@router.get("/empleados/{usuario_id}/migracion-historial")
async def empleado_migracion_historial(
    request: Request,
    usuario_id: UUID,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_manager_access("rrhh", "editor"),
):
    ctx = await service.get_migracion_empleado_ctx(conn, usuario_id)
    return templates.TemplateResponse(request, "rrhh/partials/migracion_empleado.html", ctx)


@router.post("/empleados/{usuario_id}/migracion-historial")
async def empleado_migracion_historial_guardar(
    request: Request,
    usuario_id: UUID,
    periodo_num: List[int] = Form(default=[]),
    dias_periodo: List[str] = Form(default=[]),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_manager_access("rrhh", "editor"),
):
    try:
        if len(periodo_num) != len(dias_periodo):
            raise ValueError("La captura de periodos esta incompleta")
        await service.guardar_migracion_individual(
            conn,
            usuario_id,
            [
                {"num_periodo": num, "dias": dias}
                for num, dias in zip(periodo_num, dias_periodo)
            ],
            ejecutado_por=UUID(str(context["user_db_id"])),
        )
        ctx = await service.get_migracion_empleado_ctx(conn, usuario_id)
        ctx.update({"toast_type": "success", "toast_msg": "Historial previo actualizado"})
    except ValueError as exc:
        ctx = await service.get_migracion_empleado_ctx(conn, usuario_id)
        ctx.update({"toast_type": "error", "toast_msg": str(exc)})
    except asyncpg.PostgresError:
        logger.exception("Error de BD guardando historial migrado")
        ctx = await service.get_migracion_empleado_ctx(conn, usuario_id)
        ctx.update({"toast_type": "error", "toast_msg": "No se pudo guardar el historial"})
    return templates.TemplateResponse(request, "rrhh/partials/migracion_empleado.html", ctx)


@router.delete("/empleados/{usuario_id}/migracion-historial")
async def empleado_migracion_historial_limpiar(
    request: Request,
    usuario_id: UUID,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_manager_access("rrhh", "editor"),
):
    try:
        eliminados = await service.limpiar_migracion_empleado(conn, usuario_id)
        ctx = await service.get_migracion_empleado_ctx(conn, usuario_id)
        ctx.update({
            "toast_type": "success",
            "toast_msg": f"Registros historicos eliminados: {eliminados}",
        })
    except asyncpg.PostgresError:
        logger.exception("Error de BD limpiando historial migrado")
        ctx = await service.get_migracion_empleado_ctx(conn, usuario_id)
        ctx.update({"toast_type": "error", "toast_msg": "No se pudo limpiar el historial"})
    return templates.TemplateResponse(request, "rrhh/partials/migracion_empleado.html", ctx)


@router.get("/admin")
async def admin_config(
    request: Request,
    anio: Optional[int] = None,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_manager_access("rrhh", "editor"),
):
    ctx = await service.get_admin_ctx(conn, anio)
    ctx["context"] = context
    return templates.TemplateResponse(request, "rrhh/partials/admin.html", ctx)


@router.post("/admin/horarios")
async def admin_crear_horario(
    request: Request,
    sucursal_id: UUID = Form(...),
    nombre: str = Form(...),
    activo: bool = Form(False),
    margen_entrada_antes_min: int = Form(...),
    margen_salida_despues_min: int = Form(...),
    tolerancia_extra_min: int = Form(...),
    descuento_comida_min: int = Form(...),
    dia_semana: List[int] = Form(...),
    dias_laborales: Optional[List[int]] = Form(None),
    hora_entrada: List[str] = Form(...),
    hora_salida: List[str] = Form(...),
    descuento_comida_min_dia: List[int] = Form(...),
    anio: Optional[int] = Form(None),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_manager_access("rrhh", "editor"),
):
    try:
        recalculados = await service.guardar_horario_sucursal(
            conn,
            sucursal_id=sucursal_id,
            nombre=nombre,
            activo=activo,
            margen_entrada_antes_min=margen_entrada_antes_min,
            margen_salida_despues_min=margen_salida_despues_min,
            tolerancia_extra_min=tolerancia_extra_min,
            descuento_comida_min=descuento_comida_min,
            dias=_build_horario_dias_form(
                dia_semana, dias_laborales, hora_entrada, hora_salida, descuento_comida_min_dia
            ),
            user_id=UUID(str(context["user_db_id"])),
        )
    except ValueError as exc:
        return toast_error(request, str(exc))
    except asyncpg.PostgresError:
        logger.exception("Error de BD creando horario de sucursal")
        return toast_error(request, "No se pudo guardar el horario")
    ctx = await service.get_admin_ctx(conn, anio)
    ctx.update({
        "context": context,
        "toast_type": "success",
        "toast_msg": f"Horario guardado. Registros recalculados: {recalculados}",
    })
    return templates.TemplateResponse(request, "rrhh/partials/admin.html", ctx)


@router.post("/admin/horarios/{horario_id}")
async def admin_actualizar_horario(
    request: Request,
    horario_id: UUID,
    sucursal_id: UUID = Form(...),
    nombre: str = Form(...),
    activo: bool = Form(False),
    margen_entrada_antes_min: int = Form(...),
    margen_salida_despues_min: int = Form(...),
    tolerancia_extra_min: int = Form(...),
    descuento_comida_min: int = Form(...),
    dia_semana: List[int] = Form(...),
    dias_laborales: Optional[List[int]] = Form(None),
    hora_entrada: List[str] = Form(...),
    hora_salida: List[str] = Form(...),
    descuento_comida_min_dia: List[int] = Form(...),
    anio: Optional[int] = Form(None),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_manager_access("rrhh", "editor"),
):
    try:
        recalculados = await service.guardar_horario_sucursal(
            conn,
            horario_id=horario_id,
            sucursal_id=sucursal_id,
            nombre=nombre,
            activo=activo,
            margen_entrada_antes_min=margen_entrada_antes_min,
            margen_salida_despues_min=margen_salida_despues_min,
            tolerancia_extra_min=tolerancia_extra_min,
            descuento_comida_min=descuento_comida_min,
            dias=_build_horario_dias_form(
                dia_semana, dias_laborales, hora_entrada, hora_salida, descuento_comida_min_dia
            ),
            user_id=UUID(str(context["user_db_id"])),
        )
    except ValueError as exc:
        return toast_error(request, str(exc))
    except asyncpg.PostgresError:
        logger.exception("Error de BD actualizando horario de sucursal")
        return toast_error(request, "No se pudo actualizar el horario")
    ctx = await service.get_admin_ctx(conn, anio)
    ctx.update({
        "context": context,
        "toast_type": "success",
        "toast_msg": f"Horario actualizado. Registros recalculados: {recalculados}",
    })
    return templates.TemplateResponse(request, "rrhh/partials/admin.html", ctx)


@router.post("/admin/horarios/{horario_id}/desactivar")
async def admin_desactivar_horario(
    request: Request,
    horario_id: UUID,
    anio: Optional[int] = Form(None),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_manager_access("rrhh", "editor"),
):
    try:
        recalculados = await service.desactivar_horario_sucursal(
            conn, horario_id, UUID(str(context["user_db_id"]))
        )
    except ValueError as exc:
        return toast_error(request, str(exc))
    except asyncpg.PostgresError:
        logger.exception("Error de BD desactivando horario de sucursal")
        return toast_error(request, "No se pudo desactivar el horario")
    ctx = await service.get_admin_ctx(conn, anio)
    ctx.update({
        "context": context,
        "toast_type": "success",
        "toast_msg": f"Horario desactivado. Registros recalculados: {recalculados}",
    })
    return templates.TemplateResponse(request, "rrhh/partials/admin.html", ctx)


@router.post("/admin/tipos-ausencia")
async def admin_crear_tipo_ausencia(
    request: Request,
    nombre: str = Form(...),
    slug: str = Form(...),
    abreviatura: str = Form(...),
    afecta_saldo: bool = Form(False),
    requiere_aprobacion: bool = Form(False),
    is_active: bool = Form(False),
    orden: int = Form(0),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_manager_access("rrhh", "editor"),
):
    try:
        await service.crear_tipo_ausencia(
            conn,
            nombre=nombre,
            slug=slug,
            abreviatura=abreviatura,
            afecta_saldo=afecta_saldo,
            requiere_aprobacion=requiere_aprobacion,
            is_active=is_active,
            orden=orden,
            user_id=UUID(str(context["user_db_id"])),
        )
    except ValueError as exc:
        return toast_error(request, str(exc))
    except asyncpg.UniqueViolationError:
        return toast_error(request, "Ya existe un tipo con ese slug")
    except asyncpg.PostgresError:
        logger.exception("Error de BD creando tipo de ausencia")
        return toast_error(request, "No se pudo guardar el tipo de permiso")
    ctx = await service.get_admin_ctx(conn)
    ctx.update({"context": context, "toast_type": "success", "toast_msg": "Tipo de permiso guardado"})
    return templates.TemplateResponse(request, "rrhh/partials/admin.html", ctx)


@router.post("/admin/tipos-ausencia/{tipo_id}")
async def admin_actualizar_tipo_ausencia(
    request: Request,
    tipo_id: UUID,
    nombre: str = Form(...),
    abreviatura: str = Form(...),
    afecta_saldo: bool = Form(False),
    requiere_aprobacion: bool = Form(False),
    is_active: bool = Form(False),
    orden: int = Form(0),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_manager_access("rrhh", "editor"),
):
    try:
        await service.actualizar_tipo_ausencia(
            conn,
            tipo_id=tipo_id,
            nombre=nombre,
            abreviatura=abreviatura,
            afecta_saldo=afecta_saldo,
            requiere_aprobacion=requiere_aprobacion,
            is_active=is_active,
            orden=orden,
            user_id=UUID(str(context["user_db_id"])),
        )
    except ValueError as exc:
        return toast_error(request, str(exc))
    except asyncpg.PostgresError:
        logger.exception("Error de BD actualizando tipo de ausencia")
        return toast_error(request, "No se pudo actualizar el tipo de permiso")
    ctx = await service.get_admin_ctx(conn)
    ctx.update({"context": context, "toast_type": "success", "toast_msg": "Tipo de permiso actualizado"})
    return templates.TemplateResponse(request, "rrhh/partials/admin.html", ctx)


@router.post("/admin/dias-vacaciones")
async def admin_crear_dias_vacaciones(
    request: Request,
    antiguedad_anios: int = Form(...),
    antiguedad_anios_fin: Optional[int] = Form(None),
    dias_lft: int = Form(...),
    dias_enertika: int = Form(...),
    is_active: bool = Form(False),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_manager_access("rrhh", "editor"),
):
    try:
        await service.guardar_dias_vacaciones(
            conn,
            antiguedad_anios=antiguedad_anios,
            antiguedad_anios_fin=antiguedad_anios_fin,
            dias_lft=dias_lft,
            dias_enertika=dias_enertika,
            is_active=is_active,
            user_id=UUID(str(context["user_db_id"])),
        )
    except ValueError as exc:
        return toast_error(request, str(exc))
    except asyncpg.UniqueViolationError:
        return toast_error(request, "Ya existe un rango con esa antiguedad inicial")
    except asyncpg.PostgresError:
        logger.exception("Error de BD creando dias de vacaciones")
        return toast_error(request, "No se pudo guardar el rango")
    ctx = await service.get_admin_ctx(conn)
    ctx.update({"context": context, "toast_type": "success", "toast_msg": "Rango guardado"})
    return templates.TemplateResponse(request, "rrhh/partials/admin.html", ctx)


@router.post("/admin/dias-vacaciones/{row_id}")
async def admin_actualizar_dias_vacaciones(
    request: Request,
    row_id: UUID,
    antiguedad_anios: int = Form(...),
    antiguedad_anios_fin: Optional[int] = Form(None),
    dias_lft: int = Form(...),
    dias_enertika: int = Form(...),
    is_active: bool = Form(False),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_manager_access("rrhh", "editor"),
):
    try:
        await service.guardar_dias_vacaciones(
            conn,
            row_id=row_id,
            antiguedad_anios=antiguedad_anios,
            antiguedad_anios_fin=antiguedad_anios_fin,
            dias_lft=dias_lft,
            dias_enertika=dias_enertika,
            is_active=is_active,
            user_id=UUID(str(context["user_db_id"])),
        )
    except ValueError as exc:
        return toast_error(request, str(exc))
    except asyncpg.UniqueViolationError:
        return toast_error(request, "Ya existe un rango con esa antiguedad inicial")
    except asyncpg.PostgresError:
        logger.exception("Error de BD actualizando dias de vacaciones")
        return toast_error(request, "No se pudo actualizar el rango")
    ctx = await service.get_admin_ctx(conn)
    ctx.update({"context": context, "toast_type": "success", "toast_msg": "Rango actualizado"})
    return templates.TemplateResponse(request, "rrhh/partials/admin.html", ctx)


@router.post("/admin/config")
async def admin_guardar_config(
    request: Request,
    meses_expiracion: int = Form(...),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_manager_access("rrhh", "editor"),
):
    try:
        await service.guardar_config_vacaciones(conn, meses_expiracion=meses_expiracion)
    except ValueError as exc:
        return toast_error(request, str(exc))
    except asyncpg.PostgresError:
        logger.exception("Error de BD guardando config vacaciones")
        return toast_error(request, "No se pudo guardar la configuracion")
    ctx = await service.get_admin_ctx(conn)
    ctx.update({"context": context, "toast_type": "success", "toast_msg": "Configuración guardada"})
    return templates.TemplateResponse(request, "rrhh/partials/admin.html", ctx)


@router.post("/admin/config-asistencia")
async def admin_guardar_config_asistencia(
    request: Request,
    he_minimo_minutos: int = Form(...),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_manager_access("rrhh", "editor"),
):
    try:
        await service.guardar_config_asistencia(conn, he_minimo_minutos=he_minimo_minutos)
    except ValueError as exc:
        return toast_error(request, str(exc))
    except asyncpg.PostgresError:
        logger.exception("Error de BD guardando config asistencia")
        return toast_error(request, "No se pudo guardar la configuracion")
    ctx = await service.get_admin_ctx(conn)
    ctx.update({"context": context, "toast_type": "success", "toast_msg": "Configuración guardada"})
    return templates.TemplateResponse(request, "rrhh/partials/admin.html", ctx)


# ─────────────────────────────────────────────
# Festivos
# ─────────────────────────────────────────────

@router.get("/festivos")
async def festivos_lista(
    request: Request,
    anio: Optional[int] = None,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("rrhh", "editor"),
):
    try:
        return await _festivos_template_response(request, conn, context, anio)
    except ValueError as exc:
        return toast_error(request, str(exc))


@router.post("/festivos/generar")
async def festivos_generar(
    request: Request,
    anio: int = Form(...),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("rrhh", "editor"),
):
    try:
        insertados = await service.generar_festivos_anio(
            conn, anio, UUID(str(context["user_db_id"]))
        )
    except ValueError as exc:
        return toast_error(request, str(exc))
    except asyncpg.PostgresError:
        logger.exception("Error de BD sincronizando festivos")
        return toast_error(request, "No se pudieron sincronizar los festivos")
    return await _festivos_template_response(
        request,
        conn,
        context,
        anio,
        toast_type="success",
        toast_msg=f"Festivos oficiales sincronizados. Nuevas fechas: {insertados}",
    )


@router.post("/festivos")
async def festivo_crear(
    request: Request,
    fecha: date = Form(...),
    descripcion: str = Form(...),
    es_oficial: bool = Form(False),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("rrhh", "editor"),
):
    anio = fecha.year
    try:
        await service.guardar_festivo(
            conn,
            fecha=fecha,
            descripcion=descripcion,
            es_oficial=es_oficial,
            user_id=UUID(str(context["user_db_id"])),
        )
    except ValueError as exc:
        return toast_error(request, str(exc))
    except asyncpg.UniqueViolationError:
        return toast_error(request, "Ya existe un festivo con esa fecha")
    except asyncpg.PostgresError:
        logger.exception("Error de BD creando festivo")
        return toast_error(request, "No se pudo crear el festivo")
    return await _festivos_template_response(
        request, conn, context, anio, toast_type="success", toast_msg="Festivo agregado"
    )


@router.post("/festivos/validar")
async def festivos_validar(
    request: Request,
    anio: int = Form(...),
    notas: Optional[str] = Form(None),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("rrhh", "editor"),
):
    try:
        await service.validar_festivos_anio(
            conn, anio, notas, UUID(str(context["user_db_id"]))
        )
    except ValueError as exc:
        return toast_error(request, str(exc))
    except asyncpg.PostgresError:
        logger.exception("Error de BD validando festivos")
        return toast_error(request, "No se pudo validar el año")
    return await _festivos_template_response(
        request, conn, context, anio, toast_type="success", toast_msg="Año validado por RH"
    )


@router.post("/festivos/{festivo_id}")
async def festivo_actualizar(
    request: Request,
    festivo_id: UUID,
    fecha: date = Form(...),
    descripcion: str = Form(...),
    es_oficial: bool = Form(False),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("rrhh", "editor"),
):
    anio = fecha.year
    try:
        await service.guardar_festivo(
            conn,
            festivo_id=festivo_id,
            fecha=fecha,
            descripcion=descripcion,
            es_oficial=es_oficial,
            user_id=UUID(str(context["user_db_id"])),
        )
    except ValueError as exc:
        return toast_error(request, str(exc))
    except asyncpg.UniqueViolationError:
        return toast_error(request, "Ya existe un festivo con esa fecha")
    except asyncpg.PostgresError:
        logger.exception("Error de BD actualizando festivo")
        return toast_error(request, "No se pudo actualizar el festivo")
    return await _festivos_template_response(
        request, conn, context, anio, toast_type="success", toast_msg="Festivo actualizado"
    )


@router.delete("/festivos/{festivo_id}")
async def festivo_eliminar(
    request: Request,
    festivo_id: UUID,
    anio: Optional[int] = None,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("rrhh", "editor"),
):
    anio_final = anio or today_mx().year
    try:
        await service.eliminar_festivo(
            conn, festivo_id, anio_final, UUID(str(context["user_db_id"]))
        )
    except ValueError as exc:
        return toast_error(request, str(exc))
    except asyncpg.PostgresError:
        logger.exception("Error de BD eliminando festivo")
        return toast_error(request, "No se pudo eliminar el festivo")
    return await _festivos_template_response(
        request, conn, context, anio_final, toast_type="success", toast_msg="Festivo eliminado"
    )


# ─────────────────────────────────────────────
# Asistencia (vista HTML)
# ─────────────────────────────────────────────

_ASISTENCIA_PER_PAGE = 100


@router.get("/asistencia")
async def asistencia_panel(
    request: Request,
    fecha_inicio: Optional[date] = None,
    fecha_fin: Optional[date] = None,
    usuario_id: List[str] = Query(default=[]),
    sucursal_id: Optional[str] = None,
    estado: List[str] = Query(default=[]),
    page: int = 0,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("rrhh", "editor"),
):
    hoy = today_mx()
    fi = fecha_inicio or hoy
    ff = fecha_fin or hoy
    page = max(0, page)

    rows = []
    unmapped = []
    error = None
    tiene_siguiente = False
    try:
        uids = _parse_uuid_list(usuario_id, "usuario_id")
        sid = _parse_optional_uuid(sucursal_id, "sucursal_id")
        service.validar_rango_reportes(fi, ff)
        raw = await asistencia_db.get_reporte_asistencia(
            conn,
            fecha_inicio=fi,
            fecha_fin=ff,
            usuario_ids=uids or None,
            sucursal_ids=[sid] if sid else None,
            estados=estado or None,
            limit=_ASISTENCIA_PER_PAGE + 1,
            offset=page * _ASISTENCIA_PER_PAGE,
        )
        tiene_siguiente = len(raw) > _ASISTENCIA_PER_PAGE
        raw = raw[:_ASISTENCIA_PER_PAGE]
        raw = await asistencia_service.anexar_modalidad_metadata_asistencia(conn, raw)
        unmapped = await asistencia_db.get_unmapped_biotime_checks_summary(
            conn,
            fecha_inicio=fi,
            fecha_fin=ff,
        )
        rows = [
            {
                **row,
                "entrada_fmt": ensure_mx(row["primera_entrada"]).strftime("%H:%M") if row.get("primera_entrada") else "",
                "salida_fmt": ensure_mx(row["ultima_salida"]).strftime("%H:%M") if row.get("ultima_salida") else "",
                "horas_fmt": format_minutes(row.get("minutos_trabajados") or 0),
                "extra_fmt": format_minutes(row.get("minutos_extra") or 0),
                "estado_label": formatear_estado_asistencia_label(row.get("estado"), row.get("tipo_ausencia_nombre")),
            }
            for row in raw
        ]
    except ValueError as exc:
        error = str(exc)

    usuarios = await vac_db.get_usuarios_activos_simples(conn)
    sucursales = await asistencia_db.get_sucursales(conn)
    return templates.TemplateResponse(
        request,
        "rrhh/partials/asistencia.html",
        {
            "rows": rows,
            "fecha_inicio": fi,
            "fecha_fin": ff,
            "usuario_ids_filtro": usuario_id,
            "sucursal_id_filtro": sucursal_id or "",
            "estados_filtro": estado,
            "usuarios_list": [{"id": str(u["id_usuario"]), "nombre": u["nombre"]} for u in usuarios],
            "sucursales": sucursales,
            "estados_asistencia": sorted(ASISTENCIA_ESTADOS),
            "estados_asistencia_labels": ASISTENCIA_ESTADO_LABELS,
            "checadas_sin_mapear": unmapped,
            "error": error,
            "page": page,
            "tiene_anterior": page > 0,
            "tiene_siguiente": tiene_siguiente,
        },
    )


# ─────────────────────────────────────────────
# Solicitudes (vista global RH)
# ─────────────────────────────────────────────

@router.get("/solicitudes")
async def solicitudes_lista(
    request: Request,
    estado: Optional[str] = None,
    usuario_id: Optional[UUID] = None,
    limit: int = 30,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("rrhh", "viewer"),
):
    if limit not in {0, 15, 30, 50, 100}:
        limit = 30
    solicitudes = await vac_db.get_todas_solicitudes(conn, estado=estado, usuario_id=usuario_id, limit=limit)
    usuarios = await vac_db.get_usuarios_activos_simples(conn)
    return templates.TemplateResponse(
        request, "rrhh/partials/solicitudes_lista.html",
        {
            "solicitudes": solicitudes,
            "estado_filtro": estado,
            "usuario_id_filtro": str(usuario_id) if usuario_id else "",
            "usuarios_list": [{"id": str(u["id_usuario"]), "nombre": u["nombre"]} for u in usuarios],
            "limit": limit,
            "rrhh_perms": _get_rrhh_permissions(context),
        },
    )


@router.post("/solicitudes/{solicitud_id}/aprobar")
async def aprobar_solicitud(
    request: Request,
    solicitud_id: UUID,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("rrhh", "editor"),
):
    try:
        await vac_service.aprobar_solicitud(conn, solicitud_id, context["user_db_id"], context)
    except ValueError as e:
        return toast_error(request, str(e))
    ctx = await service.get_aprobaciones_ctx_rrhh_svc(
        conn,
        context,
        _get_rrhh_permissions(context),
        toast_type="success",
        toast_msg="Solicitud aprobada",
    )
    return templates.TemplateResponse(
        request, "rrhh/partials/aprobaciones_pendientes.html",
        ctx,
    )


@router.post("/solicitudes/{solicitud_id}/rechazar")
async def rechazar_solicitud(
    request: Request,
    solicitud_id: UUID,
    motivo: str = Form(...),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("rrhh", "editor"),
):
    try:
        await vac_service.rechazar_solicitud(
            conn, solicitud_id, context["user_db_id"], motivo, context
        )
    except ValueError as e:
        return toast_error(request, str(e))
    ctx = await service.get_aprobaciones_ctx_rrhh_svc(
        conn,
        context,
        _get_rrhh_permissions(context),
        toast_type="success",
        toast_msg="Solicitud rechazada",
    )
    return templates.TemplateResponse(
        request, "rrhh/partials/aprobaciones_pendientes.html",
        ctx,
    )
