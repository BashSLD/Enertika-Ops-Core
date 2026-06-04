from __future__ import annotations

import base64
import binascii
import logging
from uuid import UUID

from datetime import timedelta

import asyncpg
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from core.database import get_db_connection
from core.permissions import user_has_module_access
from core.security import get_current_user_context
from core.timezone import fmt_time_mx, today_mx
from modules.asistencia import db_service as asistencia_db
from modules.asistencia.constants import ASISTENCIA_ESTADO_COLORES, ASISTENCIA_ESTADO_LABELS
from modules.asistencia.service import omitir_horas_extra_propio_svc
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


def _preparar_asistencia_rows(rows: list[dict]) -> list[dict]:
    for row in rows:
        row["dia_semana"] = _DIAS_SEMANA[row["fecha_laboral"].weekday()]
        row["entrada_fmt"] = fmt_time_mx(row.get("primera_entrada"))
        row["salida_fmt"] = fmt_time_mx(row.get("ultima_salida"))
        row["trabajado_fmt"] = _fmt_minutos(row.get("minutos_trabajados"))
        row["extra_fmt"] = _fmt_minutos(row.get("minutos_extra"))
        row["estado_label"] = ASISTENCIA_ESTADO_LABELS.get(
            row.get("estado", ""), row.get("estado", "")
        )
    return rows


def _build_heatmap(rows: list[dict], hoy) -> list[list[dict]]:
    por_fecha = {r["fecha_laboral"]: r["estado"] for r in rows}
    lunes_actual = hoy - timedelta(days=hoy.weekday())
    inicio = lunes_actual - timedelta(weeks=51)
    fin = lunes_actual + timedelta(days=6)
    semanas: list[list[dict]] = []
    d = inicio
    while d <= fin:
        semana: list[dict] = []
        for _ in range(7):
            estado = por_fecha.get(d)
            if d > hoy:
                semana.append({"color": "#f9fafb", "tip": ""})
            else:
                dia_label = _DIAS_SEMANA[d.weekday()]
                fecha_label = d.strftime("%d/%m")
                if estado:
                    color = ASISTENCIA_ESTADO_COLORES.get(estado, "#e5e7eb")
                    estado_label = ASISTENCIA_ESTADO_LABELS.get(estado, estado)
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
    es_jefe_o_aprobador: bool,
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
    if initial_tab in {"aprobaciones", "equipo"} and not es_jefe_o_aprobador:
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
    es_rrhh_viewer = user_has_module_access("rrhh", context_perfil, "viewer")
    hoy = today_mx()
    fecha_inicio = hoy - timedelta(days=30)
    if es_jefe:
        pendientes_aprobacion = await vac_db.get_solicitudes_pendientes_para_aprobador(conn, usuario_id)
        equipo_ids = await vac_db.get_empleados_donde_soy_jefe(conn, usuario_id)
        he_solicitadas = await asistencia_db.get_horas_extra_equipo(
            conn, equipo_ids, fecha_inicio, hoy, estados=("solicitado",)
        )
    else:
        pendientes_aprobacion = []
        he_solicitadas = []
    es_jefe_o_aprobador = es_jefe or es_rrhh_viewer
    initial_tab, initial_endpoint = _resolve_initial_tab(
        tab,
        es_jefe_o_aprobador=es_jefe_o_aprobador,
        solicitud_id=solicitud_id,
        origen=origen,
        equipo_uid=equipo_uid,
        solicitud_pendiente_id=solicitud_pendiente_id,
    )

    ctx = {
        "perfil": perfil or {},
        "balance": balance,
        "solicitudes": solicitudes,
        "tipos": tipos,
        "firma": firma,
        "es_jefe_o_aprobador": es_jefe_o_aprobador,
        "pendientes_aprobaciones_count": len(pendientes_aprobacion) + len(he_solicitadas),
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
            "context": context,
        },
    )


@router.post("/firma/upload")
async def subir_firma(
    request: Request,
    firma_file: UploadFile = File(...),
    solicitud_pendiente_id: str = Form(None),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    usuario_id = _get_usuario_id(context)
    if firma_file.content_type != "image/png":
        return toast_error(request, "Solo se aceptan imagenes PNG.", status_code=200)
    firma_bytes = await firma_file.read()
    pending_id = UUID(solicitud_pendiente_id) if solicitud_pendiente_id else None
    try:
        await perfil_service.guardar_firma(conn, usuario_id, firma_bytes, "subida", pending_id)
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
            "context": context,
            "toast_msg": "Firma guardada correctamente.",
            "toast_type": "success",
        },
    )


@router.post("/firma/draw")
async def guardar_firma_dibujada(
    request: Request,
    firma_b64: str = Form(...),
    solicitud_pendiente_id: str = Form(None),
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
        await perfil_service.guardar_firma(conn, usuario_id, firma_bytes, "dibujada", pending_id)
    except ValueError as exc:
        return toast_error(request, str(exc), status_code=200)

    return templates.TemplateResponse(
        request,
        "perfil/partials/form_firma.html",
        {
            "firma": {"tipo_firma": "dibujada"},
            "firma_b64": firma_b64.split(",", 1)[-1],
            "solicitud_pendiente_id": solicitud_pendiente_id,
            "context": context,
            "toast_msg": "Firma guardada correctamente.",
            "toast_type": "success",
        },
    )


async def _fetch_asistencia(conn, usuario_id: UUID, offset: int) -> tuple[list[dict], bool]:
    hoy = today_mx()
    desde = hoy - timedelta(days=_ASISTENCIA_DIAS_VENTANA)
    rows = await perfil_db.get_mi_asistencia(conn, usuario_id, desde, hoy, limit=15, offset=offset)
    tiene_mas = len(rows) > 15
    return _preparar_asistencia_rows(rows[:15]), tiene_mas


@router.get("/asistencia")
async def mi_asistencia(
    request: Request,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    usuario_id = _get_usuario_id(context)
    hoy = today_mx()
    desde = hoy - timedelta(days=_ASISTENCIA_DIAS_VENTANA)
    desde_heatmap = hoy - timedelta(days=_HEATMAP_DIAS_VENTANA)
    rows, tiene_mas = await _fetch_asistencia(conn, usuario_id, offset=0)
    heatmap_raw = await perfil_db.get_mi_asistencia_heatmap(conn, usuario_id, desde_heatmap, hoy)
    heatmap_semanas = _build_heatmap(heatmap_raw, hoy)
    return templates.TemplateResponse(
        request,
        "perfil/partials/tab_asistencia.html",
        {
            "asistencia": rows,
            "tiene_mas": tiene_mas,
            "offset": 0,
            "context": context,
            "heatmap_semanas": heatmap_semanas,
        },
    )


@router.get("/asistencia/mas")
async def mi_asistencia_mas(
    request: Request,
    offset: int = Query(default=15, ge=1),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    usuario_id = _get_usuario_id(context)
    rows, tiene_mas = await _fetch_asistencia(conn, usuario_id, offset=offset)
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
    return templates.TemplateResponse(
        request,
        "perfil/partials/he_omitida_row.html",
        {"asistencia_id": str(asistencia_id)},
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
