from __future__ import annotations

import logging
from datetime import date, datetime
from io import BytesIO
from typing import List, Optional
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.templating import Jinja2Templates
from openpyxl.styles import Font, PatternFill

from core.database import get_db_connection
from core.permissions import require_manager_access, require_module_access
from core.security import get_current_user_context
from modules.asistencia import db_service as asistencia_db
from modules.asistencia.constants import ASISTENCIA_ESTADO_LABELS, ASISTENCIA_ESTADOS
from modules.asistencia.logic import ensure_mx
from modules.rrhh import service
from modules.shared.utils import format_minutes, is_htmx, toast_error, toast_success
from modules.vacaciones import db_service as vac_db
from modules.vacaciones import service as vac_service
from core.timezone import today_mx

logger = logging.getLogger("rrhh.router")
router = APIRouter(prefix="/rrhh", tags=["rrhh"])
templates = Jinja2Templates(directory="templates")



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


def _format_date(value) -> str:
    return value.strftime("%d/%m/%Y") if value else ""


def _format_datetime(value) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        return ensure_mx(value).strftime("%d/%m/%Y %H:%M")
    return str(value)



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


def _format_estado_asistencia(estado: str | None) -> str:
    if not estado:
        return ""
    return ASISTENCIA_ESTADO_LABELS.get(estado, estado.replace("_", " "))


def _excel_response(workbook, filename: str) -> StreamingResponse:
    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _style_sheet(worksheet, headers: list[str]) -> None:
    worksheet.append(headers)
    worksheet.freeze_panes = "A2"
    for cell in worksheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="123456")


def _autofit_columns(worksheet) -> None:
    for column in worksheet.columns:
        width = max(len(str(cell.value or "")) for cell in column) + 2
        worksheet.column_dimensions[column[0].column_letter].width = min(width, 36)


def _build_workbook(title: str, headers: list[str], rows: list[list]):
    from openpyxl import Workbook

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = title
    _style_sheet(worksheet, headers)
    for row in rows:
        worksheet.append(row)
    _autofit_columns(worksheet)
    return workbook


def _append_unmapped_biotime_sheet(workbook, rows: list[dict]) -> None:
    if not rows:
        return
    worksheet = workbook.create_sheet("Checadas sin mapear")
    _style_sheet(worksheet, [
        "Codigo BioTime",
        "Departamento",
        "Checadas",
        "Primera checada",
        "Ultima checada",
    ])
    for row in rows:
        worksheet.append([
            row.get("biotime_emp_code") or "",
            row.get("deptname") or "",
            row.get("total") or 0,
            _format_datetime(row.get("primera_checada")),
            _format_datetime(row.get("ultima_checada")),
        ])
    _autofit_columns(worksheet)


# ─────────────────────────────────────────────
# Dashboard principal
# ─────────────────────────────────────────────

@router.get("/ui")
async def rrhh_ui(
    request: Request,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("rrhh", "viewer"),
):
    data = await service.get_dashboard_data(conn)
    hoy = today_mx()
    asistencia_rows = []
    asistencia_unmapped = []
    asistencia_error = None
    try:
        raw = await asistencia_db.get_reporte_asistencia(conn, fecha_inicio=hoy, fecha_fin=hoy)
        asistencia_unmapped = await asistencia_db.get_unmapped_biotime_checks_summary(conn, fecha_inicio=hoy, fecha_fin=hoy)
        asistencia_rows = [
            {
                **row,
                "entrada_fmt": ensure_mx(row["primera_entrada"]).strftime("%H:%M") if row.get("primera_entrada") else "",
                "salida_fmt": ensure_mx(row["ultima_salida"]).strftime("%H:%M") if row.get("ultima_salida") else "",
                "horas_fmt": f"{(row.get('minutos_trabajados') or 0) // 60}:{(row.get('minutos_trabajados') or 0) % 60:02d}",
                "extra_fmt": f"{(row.get('minutos_extra') or 0) // 60}:{(row.get('minutos_extra') or 0) % 60:02d}",
                "estado_label": _format_estado_asistencia(row.get("estado")),
            }
            for row in raw
        ]
    except (ValueError, asyncpg.PostgresError) as exc:
        logger.exception("Error cargando asistencia en dashboard RRHH")
        asistencia_error = str(exc)
    usuarios = await vac_db.get_usuarios_activos_simples(conn)
    sucursales = await asistencia_db.get_sucursales(conn)
    ctx = {
        **data,
        "context": context,
        "user_name": context.get("user_name"),
        "role": context.get("role"),
        "module_roles": context.get("module_roles", {}),
        "rows": asistencia_rows,
        "fecha_inicio": hoy,
        "fecha_fin": hoy,
        "usuario_id_filtro": "",
        "sucursal_id_filtro": "",
        "estado_filtro": "",
        "usuarios": usuarios,
        "sucursales": sucursales,
        "estados_asistencia": sorted(ASISTENCIA_ESTADOS),
        "estados_asistencia_labels": ASISTENCIA_ESTADO_LABELS,
        "checadas_sin_mapear": asistencia_unmapped,
        "error": asistencia_error,
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
    ausencias = await vac_db.get_ausencias_activas(conn, fi, ff, tipo_slug=tipo or None)
    tipos = await vac_db.get_tipos_ausencia(conn)
    return templates.TemplateResponse(
        request, "rrhh/partials/ausencias.html",
        {
            "ausencias": ausencias,
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
    pendientes = await vac_db.get_todas_solicitudes_pendientes(conn)
    return templates.TemplateResponse(
        request, "rrhh/partials/aprobaciones_pendientes.html",
        {"pendientes": pendientes, "context": context},
    )


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
    return templates.TemplateResponse(
        request, "rrhh/partials/empleados_lista.html",
        {"empleados": empleados, "total": total, "offset": offset},
    )


@router.get("/empleados/exportar-excel")
async def empleados_exportar_excel(
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("rrhh", "viewer"),
    sucursal_id: List[str] = Query(default=[]),
    usuario_id: List[str] = Query(default=[]),
):
    sids = _parse_uuid_list(sucursal_id, "sucursal_id")
    uids = _parse_uuid_list(usuario_id, "usuario_id")
    headers, rows, filename = await service.build_empleados_vacaciones_export(
        conn,
        sucursal_ids=sids or None,
        usuario_ids=uids or None,
    )
    workbook = _build_workbook("Vacaciones", headers, rows)
    return _excel_response(workbook, filename)


@router.get("/reportes")
async def reportes_panel(
    request: Request,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("rrhh", "viewer"),
):
    ctx = await service.get_reportes_ctx(conn)
    ctx["context"] = context
    return templates.TemplateResponse(request, "rrhh/partials/reportes.html", ctx)


@router.get("/reportes/asistencia.xlsx")
async def reporte_asistencia_excel(
    fecha_inicio: date,
    fecha_fin: date,
    usuario_id: List[str] = Query(default=[]),
    sucursal_id: List[str] = Query(default=[]),
    estado: Optional[str] = None,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("rrhh", "viewer"),
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
            estado=estado or None,
        )
        unmapped = await asistencia_db.get_unmapped_biotime_checks_summary(
            conn,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except asyncpg.PostgresError as exc:
        logger.exception("Error de BD generando reporte de asistencia")
        raise HTTPException(status_code=500, detail="No se pudo generar el reporte") from exc

    workbook = _build_workbook(
        "Asistencia",
        [
            "Fecha",
            "Empleado",
            "Email",
            "Sucursal",
            "Primera entrada",
            "Ultima salida",
            "Horas trabajadas",
            "Horas programadas",
            "Horas extra",
            "Estado",
            "Vacaciones",
            "Observaciones",
        ],
        [
            [
                _format_date(row["fecha_laboral"]),
                row.get("empleado_nombre") or "",
                row.get("empleado_email") or "",
                row.get("sucursal_nombre") or "",
                _format_datetime(row.get("primera_entrada")),
                _format_datetime(row.get("ultima_salida")),
                format_minutes(row.get("minutos_trabajados")),
                format_minutes(row.get("minutos_programados")),
                format_minutes(row.get("minutos_extra")),
                _format_estado_asistencia(row.get("estado")),
                "Si" if row.get("tiene_vacaciones") else "No",
                row.get("observaciones") or "",
            ]
            for row in rows
        ],
    )
    _append_unmapped_biotime_sheet(workbook, unmapped)
    filename = f"reporte_asistencia_{fecha_inicio:%Y%m%d}_{fecha_fin:%Y%m%d}.xlsx"
    return _excel_response(workbook, filename)


@router.get("/reportes/vacaciones.xlsx")
async def reporte_vacaciones_excel(
    fecha_inicio: date,
    fecha_fin: date,
    usuario_id: List[str] = Query(default=[]),
    estado: Optional[str] = None,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("rrhh", "viewer"),
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
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except asyncpg.PostgresError as exc:
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
                _format_date(row.get("fecha_inicio")),
                _format_date(row.get("fecha_fin")),
                row.get("dias_solicitados") or 0,
                _format_date(row.get("fecha_presentarse")),
                row.get("estado") or "",
                _format_datetime(row.get("fecha_solicitud")),
                _format_datetime(row.get("fecha_resolucion")),
                row.get("aprobado_por_nombre") or "",
            ]
            for row in rows
        ],
    )
    filename = f"reporte_vacaciones_{fecha_inicio:%Y%m%d}_{fecha_fin:%Y%m%d}.xlsx"
    return _excel_response(workbook, filename)


@router.get("/reportes/horas-extra.xlsx")
async def reporte_horas_extra_excel(
    fecha_inicio: date,
    fecha_fin: date,
    usuario_id: List[str] = Query(default=[]),
    sucursal_id: List[str] = Query(default=[]),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("rrhh", "viewer"),
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
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except asyncpg.PostgresError as exc:
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
            "Horas programadas",
            "Horas extra",
            "Estado",
            "Observaciones",
            "Estado aprobacion",
            "Horas aprobadas",
            "Comentario aprobacion",
        ],
        [
            [
                _format_date(row["fecha_laboral"]),
                row.get("empleado_nombre") or "",
                row.get("sucursal_nombre") or "",
                _format_datetime(row.get("primera_entrada")),
                _format_datetime(row.get("ultima_salida")),
                format_minutes(row.get("minutos_trabajados")),
                format_minutes(row.get("minutos_programados")),
                format_minutes(row.get("minutos_extra")),
                _format_estado_asistencia(row.get("estado")),
                row.get("observaciones") or "",
                "Aprobado" if row.get("horas_extra_estado") == "aprobado" else "Pendiente",
                format_minutes(row.get("minutos_aprobados")) if row.get("minutos_aprobados") else "—",
                row.get("aprobacion_comentario") or "—",
            ]
            for row in rows
        ],
    )
    filename = f"reporte_horas_extra_{fecha_inicio:%Y%m%d}_{fecha_fin:%Y%m%d}.xlsx"
    return _excel_response(workbook, filename)


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
    departamento: Optional[str] = Form(None),
    sucursal_id: Optional[UUID] = Form(None),
    id_aprobador_vacaciones: Optional[UUID] = Form(None),
    dias_vacaciones_ajuste: Optional[int] = Form(None),
    jefes_ids: List[UUID] = Form(default=[]),
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
            departamento=departamento or None,
            sucursal_id=sucursal_id,
            id_aprobador_vacaciones=id_aprobador_vacaciones,
            dias_vacaciones_ajuste=dias_vacaciones_ajuste,
            jefes_ids=jefes_ids,
            updated_by=UUID(str(context["user_db_id"])),
        )
    except ValueError as e:
        return toast_error(request, str(e))
    return toast_success(request, "Datos del empleado actualizados")


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
    return _excel_response(workbook, "plantilla_migracion_vacaciones.xlsx")


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
                f"Migracion aplicada: {resultado['empleados_actualizados']} empleados, "
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


@router.post("/admin/festivos/generar")
async def admin_generar_festivos(
    request: Request,
    anio: int = Form(...),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_manager_access("rrhh", "editor"),
):
    try:
        insertados = await service.generar_festivos_anio(
            conn, anio, UUID(str(context["user_db_id"]))
        )
    except ValueError as exc:
        return toast_error(request, str(exc))
    except asyncpg.PostgresError:
        logger.exception("Error de BD generando festivos")
        return toast_error(request, "No se pudieron generar los festivos")
    ctx = await service.get_admin_ctx(conn, anio)
    ctx.update({
        "context": context,
        "toast_type": "success",
        "toast_msg": f"Festivos generados. Nuevas fechas: {insertados}",
    })
    return templates.TemplateResponse(request, "rrhh/partials/admin.html", ctx)


@router.post("/admin/festivos")
async def admin_crear_festivo(
    request: Request,
    fecha: date = Form(...),
    descripcion: str = Form(...),
    es_oficial: bool = Form(False),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_manager_access("rrhh", "editor"),
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
        return toast_error(request, "No se pudo guardar el festivo")
    ctx = await service.get_admin_ctx(conn, anio)
    ctx.update({"context": context, "toast_type": "success", "toast_msg": "Festivo guardado"})
    return templates.TemplateResponse(request, "rrhh/partials/admin.html", ctx)


@router.post("/admin/festivos/{festivo_id}")
async def admin_actualizar_festivo(
    request: Request,
    festivo_id: UUID,
    fecha: date = Form(...),
    descripcion: str = Form(...),
    es_oficial: bool = Form(False),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_manager_access("rrhh", "editor"),
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
    ctx = await service.get_admin_ctx(conn, anio)
    ctx.update({"context": context, "toast_type": "success", "toast_msg": "Festivo actualizado"})
    return templates.TemplateResponse(request, "rrhh/partials/admin.html", ctx)


@router.delete("/admin/festivos/{festivo_id}")
async def admin_eliminar_festivo(
    request: Request,
    festivo_id: UUID,
    anio: int,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_manager_access("rrhh", "editor"),
):
    try:
        await vac_db.delete_festivo(conn, festivo_id)
    except asyncpg.PostgresError:
        logger.exception("Error de BD eliminando festivo")
        return toast_error(request, "No se pudo eliminar el festivo")
    ctx = await service.get_admin_ctx(conn, anio)
    ctx.update({"context": context, "toast_type": "success", "toast_msg": "Festivo eliminado"})
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
    ctx.update({"context": context, "toast_type": "success", "toast_msg": "Configuracion guardada"})
    return templates.TemplateResponse(request, "rrhh/partials/admin.html", ctx)


# ─────────────────────────────────────────────
# Festivos
# ─────────────────────────────────────────────

@router.get("/festivos")
async def festivos_lista(
    request: Request,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("rrhh", "viewer"),
):
    festivos = await vac_db.get_festivos(conn)
    return templates.TemplateResponse(
        request, "rrhh/partials/festivos_lista.html",
        {"festivos": festivos},
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
    try:
        await vac_db.create_festivo(conn, fecha, descripcion, es_oficial, UUID(str(context["user_db_id"])))
    except asyncpg.UniqueViolationError:
        return toast_error(request, "Ya existe un festivo con esa fecha")
    except asyncpg.PostgresError as e:
        logger.error("Error creando festivo: %s", e)
        return toast_error(request, "No se pudo crear el festivo")
    festivos = await vac_db.get_festivos(conn)
    return templates.TemplateResponse(
        request, "rrhh/partials/festivos_lista.html",
        {"festivos": festivos, "toast_type": "success", "toast_msg": "Festivo agregado"},
    )


@router.delete("/festivos/{festivo_id}")
async def festivo_eliminar(
    request: Request,
    festivo_id: UUID,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("rrhh", "editor"),
):
    await vac_db.delete_festivo(conn, festivo_id)
    festivos = await vac_db.get_festivos(conn)
    return templates.TemplateResponse(
        request, "rrhh/partials/festivos_lista.html", {"festivos": festivos}
    )


# ─────────────────────────────────────────────
# Asistencia (vista HTML)
# ─────────────────────────────────────────────

@router.get("/asistencia")
async def asistencia_panel(
    request: Request,
    fecha_inicio: Optional[date] = None,
    fecha_fin: Optional[date] = None,
    usuario_id: Optional[str] = None,
    sucursal_id: Optional[str] = None,
    estado: Optional[str] = None,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("rrhh", "viewer"),
):
    hoy = today_mx()
    fi = fecha_inicio or hoy
    ff = fecha_fin or hoy

    rows = []
    unmapped = []
    error = None
    try:
        uid = _parse_optional_uuid(usuario_id, "usuario_id")
        sid = _parse_optional_uuid(sucursal_id, "sucursal_id")
        service.validar_rango_reportes(fi, ff)
        raw = await asistencia_db.get_reporte_asistencia(
            conn,
            fecha_inicio=fi,
            fecha_fin=ff,
            usuario_ids=[uid] if uid else None,
            sucursal_ids=[sid] if sid else None,
            estado=estado or None,
        )
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
                "horas_fmt": f"{(row.get('minutos_trabajados') or 0) // 60}:{(row.get('minutos_trabajados') or 0) % 60:02d}",
                "extra_fmt": f"{(row.get('minutos_extra') or 0) // 60}:{(row.get('minutos_extra') or 0) % 60:02d}",
                "estado_label": _format_estado_asistencia(row.get("estado")),
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
            "usuario_id_filtro": usuario_id or "",
            "sucursal_id_filtro": sucursal_id or "",
            "estado_filtro": estado or "",
            "usuarios": usuarios,
            "sucursales": sucursales,
            "estados_asistencia": sorted(ASISTENCIA_ESTADOS),
            "estados_asistencia_labels": ASISTENCIA_ESTADO_LABELS,
            "checadas_sin_mapear": unmapped,
            "error": error,
        },
    )


# ─────────────────────────────────────────────
# Solicitudes (vista global RH)
# ─────────────────────────────────────────────

@router.get("/solicitudes")
async def solicitudes_lista(
    request: Request,
    estado: Optional[str] = None,
    limit: int = 30,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("rrhh", "viewer"),
):
    if limit not in {0, 15, 30, 50, 100}:
        limit = 30
    solicitudes = await vac_db.get_todas_solicitudes(conn, estado=estado, limit=limit)
    return templates.TemplateResponse(
        request, "rrhh/partials/solicitudes_lista.html",
        {"solicitudes": solicitudes, "estado_filtro": estado, "limit": limit},
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
    pendientes = await vac_db.get_todas_solicitudes_pendientes(conn)
    return templates.TemplateResponse(
        request, "rrhh/partials/aprobaciones_pendientes.html",
        {
            "pendientes": pendientes,
            "context": context,
            "toast_type": "success",
            "toast_msg": "Solicitud aprobada",
        },
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
    pendientes = await vac_db.get_todas_solicitudes_pendientes(conn)
    return templates.TemplateResponse(
        request, "rrhh/partials/aprobaciones_pendientes.html",
        {
            "pendientes": pendientes,
            "context": context,
            "toast_type": "success",
            "toast_msg": "Solicitud rechazada",
        },
    )
