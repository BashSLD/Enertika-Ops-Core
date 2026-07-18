from __future__ import annotations

import base64
import binascii
import logging
from datetime import date, timedelta
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from core.database import get_db_connection
from core.permissions import user_has_module_access
from core.security import get_current_user_context
from core.timezone import fmt_time_mx, today_mx
from modules.asistencia import db_service as asistencia_db
from modules.asistencia.constants import (
    ASISTENCIA_ESTADO_COLORES,
    ASISTENCIA_ESTADOS_SIN_HUECO_MANUAL,
    formatear_estado_asistencia_label,
)
from modules.asistencia.schemas import SolicitudManualIn
from modules.asistencia.service import (
    anexar_modalidad_metadata_asistencia,
    crear_solicitud_manual_svc,
    get_dias_retroactivo_manual,
    get_equipo_visible_he,
    get_he_bolsa_ctx,
    marcar_puede_autorizar_he,
    omitir_horas_extra_propio_svc,
    preparar_solicitud_manual_svc,
)
from modules.perfil import db_service as perfil_db
from modules.perfil import service as perfil_service
from modules.shared import signatures_db_service as signatures_db
from modules.shared.utils import is_htmx, toast_error
from modules.vacaciones import db_service as vac_db
from modules.vacaciones import service as vac_service

router = APIRouter(prefix="/perfil", tags=["perfil"])
logger = logging.getLogger("perfil.router")
templates = Jinja2Templates(directory="templates")

PERFIL_TAB_ENDPOINTS = {
    "asistencia": "/perfil/asistencia",
    "vacaciones": "/vacaciones/balance",
    "solicitudes": "/vacaciones/solicitudes",
    "aprobaciones": "/vacaciones/aprobaciones",
    "equipo": "/vacaciones/equipo",
    "firma": "/perfil/firma",
}

_DIAS_SEMANA = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
_ASISTENCIA_DIAS_VENTANA = 90
_HEATMAP_DIAS_VENTANA = 365


def _fmt_minutos(minutos: int | None) -> str:
    if not minutos:
        return "0 min"
    h, m = divmod(int(minutos), 60)
    if h and m:
        return f"{h}h {m}min"
    return f"{h}h" if h else f"{m}min"


_SOLICITUD_MANUAL_ESTADOS_BLOQUEAN = {"pendiente", "aprobado"}


def _solicitudes_manuales_por_fecha(rows: list[dict]) -> dict[date, dict]:
    por_fecha: dict[date, dict] = {}
    for row in rows:
        por_fecha.setdefault(row["fecha_laboral"], row)
    return por_fecha


def _preparar_asistencia_rows(
    rows: list[dict],
    *,
    hoy: date,
    fecha_minima: date,
    solicitudes_por_fecha: dict[date, dict] | None = None,
) -> list[dict]:
    solicitudes_por_fecha = solicitudes_por_fecha or {}
    for row in rows:
        row["dia_semana"] = _DIAS_SEMANA[row["fecha_laboral"].weekday()]
        row["entrada_fmt"] = fmt_time_mx(row.get("primera_entrada"))
        row["salida_fmt"] = fmt_time_mx(row.get("ultima_salida"))
        row["trabajado_fmt"] = _fmt_minutos(row.get("minutos_trabajados"))
        row["extra_fmt"] = _fmt_minutos(row.get("minutos_extra"))
        row["he_compensatorio_fmt"] = _fmt_minutos(row.get("minutos_he_compensatorio"))
        row["estado_label"] = formatear_estado_asistencia_label(
            row.get("estado", ""), row.get("tipo_ausencia_nombre")
        )
        solicitud = solicitudes_por_fecha.get(row["fecha_laboral"])
        row["solicitud_manual"] = solicitud
        bloqueada = bool(solicitud and solicitud["estado"] in _SOLICITUD_MANUAL_ESTADOS_BLOQUEAN)
        row["puede_solicitar_manual"] = (
            row.get("estado") not in ASISTENCIA_ESTADOS_SIN_HUECO_MANUAL
            and fecha_minima <= row["fecha_laboral"] <= hoy
            and not bloqueada
        )
    return rows


def _build_heatmap(rows: list[dict], hoy) -> list[list[dict]]:
    por_fecha = {r["fecha_laboral"]: (r["estado"], r.get("tipo_ausencia_nombre")) for r in rows}
    lunes_actual, _ = _semana_actual(hoy)
    inicio = lunes_actual - timedelta(weeks=51)
    fin = lunes_actual + timedelta(days=6)
    semanas: list[list[dict]] = []
    d = inicio
    while d <= fin:
        semana: list[dict] = []
        for _ in range(7):
            estado, tipo_ausencia_nombre = por_fecha.get(d, (None, None))
            if d > hoy:
                semana.append({"color": "#f9fafb", "tip": ""})
            else:
                dia_label = _DIAS_SEMANA[d.weekday()]
                fecha_label = d.strftime("%d/%m")
                if estado:
                    color = ASISTENCIA_ESTADO_COLORES.get(estado, "#e5e7eb")
                    estado_label = formatear_estado_asistencia_label(estado, tipo_ausencia_nombre)
                    tip = f"{dia_label} {fecha_label} · {estado_label}"
                else:
                    color = "#f3f4f6"
                    tip = f"{dia_label} {fecha_label} · Sin registro"
                semana.append({"color": color, "tip": tip})
            d += timedelta(days=1)
        semanas.append(semana)
    return semanas


def _legacy_redirect(path: str) -> RedirectResponse:
    return RedirectResponse(url=f"/vacaciones{path}", status_code=301)


def _semana_actual(hoy: date) -> tuple[date, date]:
    lunes = hoy - timedelta(days=hoy.weekday())
    return lunes, lunes + timedelta(days=6)


def _sanear_rango_equipo_fuera(
    fecha_inicio: str | None, fecha_fin: str | None
) -> tuple[date, date]:
    lunes, domingo = _semana_actual(today_mx())
    try:
        d_inicio = date.fromisoformat(fecha_inicio) if fecha_inicio else lunes
    except ValueError:
        d_inicio = lunes
    try:
        d_fin = date.fromisoformat(fecha_fin) if fecha_fin else domingo
    except ValueError:
        d_fin = domingo
    if d_fin < d_inicio:
        d_inicio, d_fin = d_fin, d_inicio
    return d_inicio, d_fin


def _get_usuario_id(context: dict) -> UUID:
    user_db_id = context.get("user_db_id")
    if not user_db_id:
        raise HTTPException(status_code=403, detail="Usuario sin registro en base de datos")
    return UUID(str(user_db_id))


def _context_con_perfil(context: dict, perfil: dict | None) -> dict:
    perfil = perfil or {}
    return {
        **context,
        "user_name": perfil.get("nombre") or context.get("user_name"),
        "email": perfil.get("email") or context.get("email"),
        "department": perfil.get("department") or context.get("department"),
        "puesto": perfil.get("puesto") or context.get("puesto"),
    }


def _resolve_initial_tab(
    tab: str | None,
    *,
    puede_ver_aprobaciones: bool,
    puede_ver_equipo: bool,
    solicitud_id: UUID | None,
    origen: str,
    equipo_uid: UUID | None,
    solicitud_pendiente_id: UUID | None,
) -> tuple[str, str]:
    if solicitud_id:
        origen = origen if origen in {"solicitudes", "aprobaciones"} else "solicitudes"
        initial_tab = "aprobaciones" if origen == "aprobaciones" else "solicitudes"
        return initial_tab, f"/vacaciones/solicitudes/{solicitud_id}?origen={origen}"

    # equipo_uid intentionally ignored: member detail is intra-tab drill-down,
    # not resolvable URL state — resolving it caused Back to show the member
    # balance instead of the team list when the HTMX history cache expired.

    if solicitud_pendiente_id:
        return "firma", f"/perfil/firma?solicitud_pendiente_id={solicitud_pendiente_id}"

    initial_tab = tab if tab in PERFIL_TAB_ENDPOINTS else "asistencia"
    if initial_tab == "aprobaciones" and not puede_ver_aprobaciones:
        initial_tab = "asistencia"
    elif initial_tab == "equipo" and not puede_ver_equipo:
        initial_tab = "asistencia"
    return initial_tab, PERFIL_TAB_ENDPOINTS[initial_tab]


@router.get("/ui")
async def perfil_ui(
    request: Request,
    tab: str | None = None,
    solicitud_id: UUID | None = None,
    origen: str = "solicitudes",
    equipo_uid: UUID | None = None,
    solicitud_pendiente_id: UUID | None = None,
    equipo_fuera_fecha_inicio: str | None = Query(None, alias="fecha_inicio"),
    equipo_fuera_fecha_fin: str | None = Query(None, alias="fecha_fin"),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    usuario_id = _get_usuario_id(context)
    perfil = await perfil_db.get_perfil_usuario(conn, usuario_id)
    context_perfil = _context_con_perfil(context, perfil)
    balance = await vac_service.get_balance_usuario(conn, usuario_id)
    solicitudes = await vac_db.get_solicitudes_usuario(conn, usuario_id)
    tipos = await vac_db.get_tipos_ausencia(conn)
    firma = await signatures_db.get_firma_usuario(conn, usuario_id)
    es_jefe = await vac_service.es_jefe_o_aprobador_de_alguien(conn, usuario_id)
    es_rrhh_viewer = user_has_module_access("rrhh", context, "viewer")
    hoy = today_mx()
    fecha_inicio = hoy - timedelta(days=30)
    if es_jefe:
        pendientes_aprobacion = await vac_db.get_solicitudes_pendientes_para_aprobador(conn, usuario_id)
        equipo_ids = await vac_db.get_equipo_ids_jefe_o_aprobador(conn, usuario_id)
    else:
        pendientes_aprobacion = []
        equipo_ids = []
    equipo_visible_he, autorizable_he_set = await get_equipo_visible_he(
        conn, usuario_id, context, equipo_ids
    )
    if equipo_visible_he:
        he_solicitadas = await asistencia_db.get_horas_extra_equipo(
            conn, equipo_visible_he, fecha_inicio, hoy, estados=("solicitado",)
        )
        comp_pendientes = await asistencia_db.get_he_compensatorio_pendientes(conn, equipo_visible_he)
    else:
        he_solicitadas = []
        comp_pendientes = []
    marcar_puede_autorizar_he(he_solicitadas, autorizable_he_set)
    marcar_puede_autorizar_he(comp_pendientes, autorizable_he_set)
    he_autorizables_count = sum(1 for r in he_solicitadas if r["puede_autorizar_he"])
    comp_autorizables_count = sum(1 for r in comp_pendientes if r["puede_autorizar_he"])
    es_jefe_o_aprobador = es_jefe
    puede_ver_equipo = es_jefe or es_rrhh_viewer
    puede_ver_aprobaciones = es_jefe or es_rrhh_viewer or bool(autorizable_he_set)
    initial_tab, initial_endpoint = _resolve_initial_tab(
        tab,
        puede_ver_aprobaciones=puede_ver_aprobaciones,
        puede_ver_equipo=puede_ver_equipo,
        solicitud_id=solicitud_id,
        origen=origen,
        equipo_uid=equipo_uid,
        solicitud_pendiente_id=solicitud_pendiente_id,
    )
    if initial_tab == "asistencia" and (equipo_fuera_fecha_inicio or equipo_fuera_fecha_fin):
        d_inicio, d_fin = _sanear_rango_equipo_fuera(equipo_fuera_fecha_inicio, equipo_fuera_fecha_fin)
        initial_endpoint = f"{initial_endpoint}?fecha_inicio={d_inicio.isoformat()}&fecha_fin={d_fin.isoformat()}"

    ctx = {
        "perfil": perfil or {},
        "balance": balance,
        "solicitudes": solicitudes,
        "tipos": tipos,
        "firma": firma,
        "es_jefe_o_aprobador": es_jefe_o_aprobador,
        "puede_ver_aprobaciones": puede_ver_aprobaciones,
        "puede_ver_equipo": puede_ver_equipo,
        "pendientes_aprobaciones_count": (
            len(pendientes_aprobacion) + he_autorizables_count + comp_autorizables_count
        ),
        "initial_tab": initial_tab,
        "initial_endpoint": initial_endpoint,
        "context": context_perfil,
        "user_name": context_perfil.get("user_name"),
        "role": context_perfil.get("role"),
        "module_roles": context_perfil.get("module_roles", {}),
    }
    if is_htmx(request):
        return templates.TemplateResponse(request, "perfil/partials/content.html", ctx)
    return templates.TemplateResponse(request, "perfil/perfil.html", ctx)


@router.get("/firma")
async def ver_firma(
    request: Request,
    solicitud_pendiente_id: str = None,
    embed_target_id: str | None = None,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    usuario_id = _get_usuario_id(context)
    firma = await signatures_db.get_firma_usuario(conn, usuario_id)
    firma_b64 = None
    if firma:
        firma_b64 = perfil_service.firma_bytes_to_base64(bytes(firma["firma_data"]))
    return templates.TemplateResponse(
        request,
        "perfil/partials/form_firma.html",
        {
            "firma": firma,
            "firma_b64": firma_b64,
            "solicitud_pendiente_id": solicitud_pendiente_id,
            "embed_target_id": embed_target_id,
            "context": context,
        },
    )


@router.post("/firma/upload")
async def subir_firma(
    request: Request,
    firma_file: UploadFile = File(...),
    solicitud_pendiente_id: str = Form(None),
    embed_target_id: str | None = Form(None),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    usuario_id = _get_usuario_id(context)
    if firma_file.content_type != "image/png":
        return toast_error(request, "Solo se aceptan imagenes PNG.", status_code=200)
    firma_bytes = await firma_file.read()
    pending_id = UUID(solicitud_pendiente_id) if solicitud_pendiente_id else None
    try:
        firma_bytes, tipo_nombre_enviado = await perfil_service.guardar_firma(
            conn, usuario_id, firma_bytes, "subida", pending_id
        )
    except ValueError as exc:
        return toast_error(request, str(exc), status_code=200)

    firma_b64 = perfil_service.firma_bytes_to_base64(firma_bytes)
    return templates.TemplateResponse(
        request,
        "perfil/partials/form_firma.html",
        {
            "firma": {"tipo_firma": "subida"},
            "firma_b64": firma_b64,
            "solicitud_pendiente_id": solicitud_pendiente_id,
            "embed_target_id": embed_target_id,
            "context": context,
            "firma_guardada": True,
            "tipo_nombre_enviado": tipo_nombre_enviado,
        },
    )


@router.post("/firma/draw")
async def guardar_firma_dibujada(
    request: Request,
    firma_b64: str = Form(...),
    solicitud_pendiente_id: str = Form(None),
    embed_target_id: str | None = Form(None),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    usuario_id = _get_usuario_id(context)
    try:
        raw = firma_b64.split(",", 1)[-1]
        firma_bytes = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        return toast_error(request, "Firma invalida.", status_code=200)

    pending_id = UUID(solicitud_pendiente_id) if solicitud_pendiente_id else None
    try:
        firma_bytes, tipo_nombre_enviado = await perfil_service.guardar_firma(
            conn, usuario_id, firma_bytes, "dibujada", pending_id
        )
    except ValueError as exc:
        return toast_error(request, str(exc), status_code=200)

    return templates.TemplateResponse(
        request,
        "perfil/partials/form_firma.html",
        {
            "firma": {"tipo_firma": "dibujada"},
            "firma_b64": perfil_service.firma_bytes_to_base64(firma_bytes),
            "solicitud_pendiente_id": solicitud_pendiente_id,
            "embed_target_id": embed_target_id,
            "context": context,
            "firma_guardada": True,
            "tipo_nombre_enviado": tipo_nombre_enviado,
        },
    )


async def _fetch_asistencia(
    conn,
    usuario_id: UUID,
    offset: int,
    *,
    fecha_minima: date,
    solicitudes_por_fecha: dict[date, dict] | None = None,
) -> tuple[list[dict], bool]:
    hoy = today_mx()
    desde = hoy - timedelta(days=_ASISTENCIA_DIAS_VENTANA)
    rows = await perfil_db.get_mi_asistencia(conn, usuario_id, desde, hoy, limit=15, offset=offset)
    tiene_mas = len(rows) > 15
    rows_visibles = await anexar_modalidad_metadata_asistencia(conn, rows[:15])
    rows_preparados = _preparar_asistencia_rows(
        rows_visibles, hoy=hoy, fecha_minima=fecha_minima, solicitudes_por_fecha=solicitudes_por_fecha
    )
    return rows_preparados, tiene_mas


async def _build_asistencia_tab_context(
    conn,
    usuario_id: UUID,
    context: dict,
    *,
    equipo_fuera_fecha_inicio: date | None = None,
    equipo_fuera_fecha_fin: date | None = None,
    toast_type: str | None = None,
    toast_title: str | None = None,
    toast_message: str | None = None,
) -> dict:
    hoy = today_mx()
    desde_heatmap = hoy - timedelta(days=_HEATMAP_DIAS_VENTANA)
    dias_retroactivo = await get_dias_retroactivo_manual(conn)
    mis_solicitudes = await asistencia_db.get_mis_solicitudes_manuales(conn, usuario_id, limit=45)
    solicitudes_por_fecha = _solicitudes_manuales_por_fecha(mis_solicitudes)
    rows, tiene_mas = await _fetch_asistencia(
        conn,
        usuario_id,
        offset=0,
        fecha_minima=hoy - timedelta(days=dias_retroactivo),
        solicitudes_por_fecha=solicitudes_por_fecha,
    )
    heatmap_raw = await perfil_db.get_mi_asistencia_heatmap(conn, usuario_id, desde_heatmap, hoy)
    bolsa = await get_he_bolsa_ctx(conn, usuario_id)

    if equipo_fuera_fecha_inicio is None or equipo_fuera_fecha_fin is None:
        equipo_fuera_fecha_inicio, equipo_fuera_fecha_fin = _semana_actual(hoy)

    return {
        "asistencia": rows,
        "bolsa": bolsa,
        "tiene_mas": tiene_mas,
        "offset": 0,
        "context": context,
        "heatmap_semanas": _build_heatmap(heatmap_raw, hoy),
        "hoy_iso": hoy.isoformat(),
        "equipo_fuera_fecha_inicio": equipo_fuera_fecha_inicio,
        "equipo_fuera_fecha_fin": equipo_fuera_fecha_fin,
        "toast_type": toast_type,
        "toast_title": toast_title,
        "toast_message": toast_message,
    }


@router.get("/asistencia")
async def mi_asistencia(
    request: Request,
    fecha_inicio: str | None = Query(None),
    fecha_fin: str | None = Query(None),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    usuario_id = _get_usuario_id(context)
    d_inicio, d_fin = _sanear_rango_equipo_fuera(fecha_inicio, fecha_fin)
    ctx = await _build_asistencia_tab_context(
        conn, usuario_id, context,
        equipo_fuera_fecha_inicio=d_inicio,
        equipo_fuera_fecha_fin=d_fin,
    )
    return templates.TemplateResponse(
        request,
        "perfil/partials/tab_asistencia.html",
        ctx,
    )


@router.get("/asistencia/equipo-fuera")
async def equipo_fuera_oficina_widget(
    request: Request,
    fecha_inicio: str | None = Query(None),
    fecha_fin: str | None = Query(None),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    d_inicio, d_fin = _sanear_rango_equipo_fuera(fecha_inicio, fecha_fin)
    ctx = await perfil_service.get_equipo_fuera_oficina_ctx(conn, d_inicio, d_fin)
    headers = {}
    if request.headers.get("hx-trigger") == "equipo-fuera-filtro":
        canonical_url = (
            f"/perfil/ui?tab=asistencia&fecha_inicio={d_inicio.isoformat()}&fecha_fin={d_fin.isoformat()}"
        )
        headers["HX-Push-Url"] = canonical_url
    return templates.TemplateResponse(
        request,
        "perfil/partials/equipo_fuera_oficina_widget.html",
        {**ctx, "context": context},
        headers=headers,
    )


@router.get("/asistencia/solicitudes-manuales/nueva")
async def nueva_solicitud_manual(
    request: Request,
    fecha_laboral: date | None = Query(None),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    usuario_id = _get_usuario_id(context)
    target_date = fecha_laboral or today_mx()
    modal_ctx = await preparar_solicitud_manual_svc(conn, usuario_id, target_date)
    return templates.TemplateResponse(
        request,
        "perfil/partials/modal_solicitud_manual.html",
        {**modal_ctx, "context": context},
    )


async def _modal_ctx_con_error(
    conn, usuario_id: UUID, payload: SolicitudManualIn, mensaje: str
) -> dict:
    modal_ctx = await preparar_solicitud_manual_svc(conn, usuario_id, payload.fecha_laboral)
    if not modal_ctx.get("bloqueado"):
        if payload.fecha_entrada:
            modal_ctx["fecha_entrada"] = payload.fecha_entrada
        if payload.hora_entrada:
            modal_ctx["hora_entrada"] = payload.hora_entrada
        if payload.fecha_salida:
            modal_ctx["fecha_salida"] = payload.fecha_salida
        if payload.hora_salida:
            modal_ctx["hora_salida"] = payload.hora_salida
    modal_ctx["motivo"] = payload.motivo
    modal_ctx["error_mensaje"] = mensaje
    return modal_ctx


@router.post("/asistencia/solicitudes-manuales")
async def crear_solicitud_manual(
    request: Request,
    fecha_laboral: date = Form(...),
    fecha_entrada: date | None = Form(None),
    hora_entrada: str | None = Form(None),
    fecha_salida: date | None = Form(None),
    hora_salida: str | None = Form(None),
    motivo: str = Form(...),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    usuario_id = _get_usuario_id(context)
    payload = SolicitudManualIn(
        fecha_laboral=fecha_laboral,
        fecha_entrada=fecha_entrada,
        hora_entrada=hora_entrada,
        fecha_salida=fecha_salida,
        hora_salida=hora_salida,
        motivo=motivo,
    )
    try:
        await crear_solicitud_manual_svc(conn, usuario_id, payload)
    except ValueError as exc:
        modal_ctx = await _modal_ctx_con_error(conn, usuario_id, payload, str(exc))
        return templates.TemplateResponse(
            request, "perfil/partials/modal_solicitud_manual.html", {**modal_ctx, "context": context}
        )
    except asyncpg.PostgresError as exc:
        logger.error("Error BD creando solicitud manual: %s", exc)
        modal_ctx = await _modal_ctx_con_error(
            conn, usuario_id, payload, "Error al guardar la solicitud"
        )
        return templates.TemplateResponse(
            request,
            "perfil/partials/modal_solicitud_manual.html",
            {**modal_ctx, "context": context},
            status_code=500,
        )

    ctx = await _build_asistencia_tab_context(
        conn,
        usuario_id,
        context,
        toast_type="success",
        toast_title="Listo",
        toast_message="Solicitud enviada para revision.",
    )
    return templates.TemplateResponse(request, "perfil/partials/asistencia_manual_resultado.html", ctx)


@router.get("/asistencia/mas")
async def mi_asistencia_mas(
    request: Request,
    offset: int = Query(default=15, ge=1),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    usuario_id = _get_usuario_id(context)
    hoy = today_mx()
    dias_retroactivo = await get_dias_retroactivo_manual(conn)
    mis_solicitudes = await asistencia_db.get_mis_solicitudes_manuales(conn, usuario_id, limit=45)
    solicitudes_por_fecha = _solicitudes_manuales_por_fecha(mis_solicitudes)
    rows, tiene_mas = await _fetch_asistencia(
        conn,
        usuario_id,
        offset=offset,
        fecha_minima=hoy - timedelta(days=dias_retroactivo),
        solicitudes_por_fecha=solicitudes_por_fecha,
    )
    return templates.TemplateResponse(
        request,
        "perfil/partials/tab_asistencia_rows.html",
        {"asistencia": rows, "tiene_mas": tiene_mas, "offset": offset, "context": context},
    )


@router.post("/horas-extra/{asistencia_id}/omitir")
async def omitir_horas_extra_propio(
    request: Request,
    asistencia_id: UUID,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    usuario_id = _get_usuario_id(context)
    try:
        await omitir_horas_extra_propio_svc(conn, asistencia_id=asistencia_id, usuario_id=usuario_id)
    except ValueError as exc:
        return toast_error(request, str(exc))
    except asyncpg.PostgresError as exc:
        logger.error("Error BD omitiendo HE propias: %s", exc)
        return toast_error(request, "Error al descartar el registro.", status_code=500)

    row = await perfil_db.get_asistencia_row_por_id(conn, asistencia_id)
    hoy = today_mx()
    dias_retroactivo = await get_dias_retroactivo_manual(conn)
    row = (await anexar_modalidad_metadata_asistencia(conn, [row]))[0]
    row = _preparar_asistencia_rows([row], hoy=hoy, fecha_minima=hoy - timedelta(days=dias_retroactivo))[0]
    return templates.TemplateResponse(
        request,
        "perfil/partials/he_row_actualizada.html",
        {"row": row},
    )


@router.get("/balance")
async def redirect_balance():
    return _legacy_redirect("/balance")


@router.get("/solicitudes")
async def redirect_solicitudes():
    return _legacy_redirect("/solicitudes")


@router.get("/solicitudes/nueva")
async def redirect_solicitudes_nueva():
    return _legacy_redirect("/solicitudes/nueva")


@router.get("/solicitudes/{solicitud_id}")
async def redirect_solicitud_detalle(solicitud_id: UUID):
    return _legacy_redirect(f"/solicitudes/{solicitud_id}")


@router.get("/solicitudes/{solicitud_id}/pdf")
async def redirect_solicitud_pdf(solicitud_id: UUID):
    return _legacy_redirect(f"/solicitudes/{solicitud_id}/pdf")


@router.get("/aprobaciones")
async def redirect_aprobaciones():
    return _legacy_redirect("/aprobaciones")


@router.get("/equipo")
async def redirect_equipo():
    return _legacy_redirect("/equipo")


@router.get("/equipo/{uid}")
async def redirect_equipo_detalle(uid: UUID):
    return _legacy_redirect(f"/equipo/{uid}")
