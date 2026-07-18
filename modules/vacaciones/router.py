from __future__ import annotations

import json
from datetime import date, time, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from core.database import get_db_connection
from core.jinja_filters import register_timezone_filters
from core.permissions import require_authenticated_session, user_has_module_access
from core.security import get_current_user_context
from core.timezone import fmt_time_mx, today_mx
from modules.asistencia import db_service as asistencia_db
from modules.asistencia.service import (
    get_equipo_ids_para_autorizacion_he,
    get_equipo_visible_he,
    marcar_puede_autorizar_he,
)
from modules.shared import signatures_db_service as signatures_db
from modules.shared.utils import format_minutes, is_htmx, toast_error
from modules.vacaciones import db_service as db
from modules.vacaciones import service
from modules.vacaciones.logic import contar_dias_habiles, siguiente_dia_habil

router = APIRouter(prefix="/vacaciones", tags=["vacaciones"])
templates = Jinja2Templates(directory="templates")
register_timezone_filters(templates.env)


def _get_usuario_id(context: dict) -> UUID | None:
    user_db_id = context.get("user_db_id")
    return UUID(str(user_db_id)) if user_db_id else None


def _tab_sync_header(tab: str) -> dict:
    return {"HX-Trigger": json.dumps({"perfil-tab-sync": {"tab": tab}})}


async def _render_mis_solicitudes(
    request: Request, conn, context: dict, pagina: int = 1, headers: dict | None = None, **extra
):
    usuario_id = _get_usuario_id(context)
    solicitudes, tiene_siguiente = await service.get_solicitudes_usuario_pagina_svc(conn, usuario_id, pagina)
    return templates.TemplateResponse(
        request,
        "vacaciones/partials/mis_solicitudes.html",
        {
            "solicitudes": solicitudes,
            "solicitudes_pagina": pagina,
            "solicitudes_tiene_siguiente": tiene_siguiente,
            "context": context,
            **extra,
        },
        headers=headers,
    )


def _perfil_detalle_url(solicitud_id: UUID, origen: str) -> str:
    tab = "aprobaciones" if origen == "aprobaciones" else "solicitudes"
    return f"/perfil/ui?tab={tab}&solicitud_id={solicitud_id}&origen={origen}"


def _rrhh_detalle_url(solicitud_id: UUID, origen: str, solo_consulta: bool = True) -> str:
    tab = "aprobaciones" if origen == "rrhh_aprobaciones" else "solicitudes"
    url = f"/rrhh/ui?tab={tab}&solicitud_id={solicitud_id}&origen={origen}"
    if solo_consulta:
        url = f"{url}&solo_consulta=1"
    return url


# ─────────────────────────────────────────────
# Utilidad: cálculo de días hábiles (usado por el formulario vía JS)
# ─────────────────────────────────────────────

@router.get("/calcular-dias")
async def calcular_dias(
    inicio: str = Query(...),
    fin: str = Query(...),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    try:
        d_inicio = date.fromisoformat(inicio)
        d_fin = date.fromisoformat(fin)
    except ValueError:
        return JSONResponse({"dias": 0, "fecha_presentarse": None})
    festivos = await db.get_festivos_set(conn)
    dias = max(contar_dias_habiles(d_inicio, d_fin, festivos), 0)
    fecha_presentarse = siguiente_dia_habil(d_fin, festivos).isoformat()
    return JSONResponse({"dias": dias, "fecha_presentarse": fecha_presentarse})


# ─────────────────────────────────────────────
# Balance (HTMX partial)
# ─────────────────────────────────────────────

@router.get("/balance")
async def perfil_balance(
    request: Request,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_authenticated_session(),
):
    usuario_id = _get_usuario_id(context)
    balance = await service.get_balance_usuario(conn, usuario_id)
    return templates.TemplateResponse(
        request, "vacaciones/partials/balance.html", {"balance": balance, "context": context}
    )


# ─────────────────────────────────────────────
# Solicitudes
# ─────────────────────────────────────────────

@router.get("/solicitudes")
async def mis_solicitudes(
    request: Request,
    pagina: int = Query(1, ge=1),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_authenticated_session(),
):
    return await _render_mis_solicitudes(request, conn, context, pagina)


@router.get("/solicitudes/nueva")
async def form_nueva_solicitud(
    request: Request,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_authenticated_session(),
):
    usuario_id = _get_usuario_id(context)
    tipos = await db.get_tipos_ausencia(conn)
    balance = await service.get_balance_usuario(conn, usuario_id)
    firma = await signatures_db.get_firma_usuario(conn, usuario_id)
    return templates.TemplateResponse(
        request,
        "vacaciones/partials/form_solicitud.html",
        {"tipos": tipos, "balance": balance, "tiene_firma": firma is not None, "context": context},
    )


@router.post("/solicitudes")
async def crear_solicitud(
    request: Request,
    tipo_ausencia_id: UUID = Form(...),
    fecha_inicio: str = Form(...),
    fecha_fin: str = Form(...),
    fecha_presentarse: str | None = Form(None),
    observaciones: str = Form(None),
    hora_llegada: str | None = Form(None),
    hora_salida: str | None = Form(None),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_authenticated_session(),
):
    usuario_id = _get_usuario_id(context)
    try:
        fecha_inicio_date = date.fromisoformat(fecha_inicio)
        fecha_fin_date = date.fromisoformat(fecha_fin)
        fecha_presentarse_date = date.fromisoformat(fecha_presentarse) if fecha_presentarse else None
        hora_llegada_time = time.fromisoformat(hora_llegada) if hora_llegada else None
        hora_salida_time = time.fromisoformat(hora_salida) if hora_salida else None
    except ValueError:
        return toast_error(request, "Las fechas u horas capturadas no son válidas", status_code=200)

    try:
        result = await service.crear_solicitud(
            conn,
            usuario_id=usuario_id,
            tipo_ausencia_id=tipo_ausencia_id,
            fecha_inicio=fecha_inicio_date,
            fecha_fin=fecha_fin_date,
            fecha_presentarse=fecha_presentarse_date,
            observaciones=observaciones or None,
            hora_llegada=hora_llegada_time,
            hora_salida=hora_salida_time,
        )
    except ValueError as exc:
        return toast_error(request, str(exc), status_code=200)

    if result["requiere_firma"]:
        solicitud_id = str(result["solicitud"]["id"])
        return templates.TemplateResponse(
            request,
            "perfil/partials/form_firma.html",
            {
                "solicitud_pendiente_id": solicitud_id,
                "context": context,
                "toast_msg": "Registra tu firma para completar la solicitud.",
                "toast_type": "warning",
            },
            headers=_tab_sync_header("firma"),
        )

    return await _render_mis_solicitudes(
        request, conn, context,
        toast_msg=f"Solicitud enviada ({result['dias']} días hábiles). El aprobador será notificado.",
        toast_type="success",
        headers=_tab_sync_header("solicitudes"),
    )


@router.get("/solicitudes/{solicitud_id}/abrir")
async def abrir_solicitud_desde_cta(
    request: Request,
    solicitud_id: UUID,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_authenticated_session(),
):
    usuario_id = _get_usuario_id(context)

    solicitud = await db.get_solicitud(conn, solicitud_id)
    if not solicitud:
        raise HTTPException(404)

    if solicitud["usuario_id"] == usuario_id:
        return RedirectResponse(url=_perfil_detalle_url(solicitud_id, "solicitudes"), status_code=303)

    if await service.es_aprobador_operativo(conn, solicitud_id, usuario_id, solicitud=solicitud):
        return RedirectResponse(url=_perfil_detalle_url(solicitud_id, "aprobaciones"), status_code=303)

    if user_has_module_access("rrhh", context, "editor"):
        return RedirectResponse(
            url=_rrhh_detalle_url(solicitud_id, "rrhh_aprobaciones", solo_consulta=False),
            status_code=303,
        )

    if user_has_module_access("rrhh", context, "viewer"):
        return RedirectResponse(
            url=_rrhh_detalle_url(solicitud_id, "rrhh_solicitudes", solo_consulta=True),
            status_code=303,
        )

    raise HTTPException(403)


@router.get("/solicitudes/{solicitud_id}")
async def detalle_solicitud(
    request: Request,
    solicitud_id: UUID,
    origen: str = "solicitudes",
    solo_consulta: bool = False,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_authenticated_session(),
):
    es_request_htmx = is_htmx(request)
    origenes_validos = {"solicitudes", "aprobaciones", "rrhh_aprobaciones", "rrhh_solicitudes"}
    if origen not in origenes_validos:
        origen = "solicitudes"
    solicitud = await db.get_solicitud(conn, solicitud_id)
    if not solicitud:
        raise HTTPException(404)
    usuario_id = _get_usuario_id(context)
    es_dueno = solicitud["usuario_id"] == usuario_id
    es_aprobador_operativo = await service.es_aprobador_operativo(conn, solicitud_id, usuario_id, solicitud=solicitud)
    es_aprobador = await service.puede_aprobar(conn, solicitud_id, usuario_id, context, solicitud=solicitud)
    es_rrhh_viewer = user_has_module_access("rrhh", context, "viewer")
    if not es_dueno and not es_aprobador and not es_rrhh_viewer:
        raise HTTPException(403)
    if not es_request_htmx:
        if origen == "solicitudes" and not es_dueno and not es_aprobador_operativo and es_rrhh_viewer:
            return RedirectResponse(
                url=_rrhh_detalle_url(solicitud_id, "rrhh_solicitudes", solo_consulta=True),
                status_code=303,
            )
        if origen in {"rrhh_aprobaciones", "rrhh_solicitudes"}:
            return RedirectResponse(
                url=_rrhh_detalle_url(
                    solicitud_id,
                    origen,
                    solo_consulta=solo_consulta or origen == "rrhh_solicitudes",
                ),
                status_code=303,
            )
    if not es_dueno and es_aprobador_operativo and origen == "solicitudes":
        origen = "aprobaciones"
    if not es_request_htmx:
        if origen == "rrhh_aprobaciones":
            origen = "aprobaciones"
        elif origen == "rrhh_solicitudes":
            origen = "solicitudes"
    firmas = await db.get_firmas_solicitud(conn, solicitud_id)

    ctx = {
        "solicitud": solicitud,
        "firmas": firmas,
        "es_aprobador": es_aprobador,
        "es_dueno": es_dueno,
        "origen": origen,
        "solo_consulta": solo_consulta or origen == "rrhh_solicitudes",
        "context": context,
    }
    if es_request_htmx:
        return templates.TemplateResponse(
            request,
            "vacaciones/partials/detalle_solicitud.html",
            ctx,
        )

    es_jefe = await service.es_jefe_o_aprobador_de_alguien(conn, usuario_id)
    if es_jefe or es_rrhh_viewer:
        autorizable_he_set: set = set()
    else:
        autorizable_he_set = set(await get_equipo_ids_para_autorizacion_he(conn, usuario_id, context))
    if es_jefe:
        pendientes_aprobacion = await db.get_solicitudes_pendientes_para_aprobador(conn, usuario_id)
    else:
        pendientes_aprobacion = []

    puede_ver_equipo_he = es_jefe or es_rrhh_viewer or bool(autorizable_he_set)
    ctx.update(
        {
            "es_jefe_o_aprobador": puede_ver_equipo_he,
            "puede_ver_aprobaciones": puede_ver_equipo_he,
            "puede_ver_equipo": puede_ver_equipo_he,
            "pendientes_aprobaciones_count": len(pendientes_aprobacion),
            "tab_activa": "aprobaciones" if origen == "aprobaciones" else "solicitudes",
            "user_name": context.get("user_name"),
            "role": context.get("role"),
            "module_roles": context.get("module_roles", {}),
        }
    )
    return templates.TemplateResponse(
        request,
        "vacaciones/detalle_solicitud.html",
        ctx,
    )


@router.post("/solicitudes/{solicitud_id}/cancelar")
async def cancelar_solicitud(
    request: Request,
    solicitud_id: UUID,
    pagina: int = Form(1),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_authenticated_session(),
):
    usuario_id = _get_usuario_id(context)
    try:
        await service.cancelar_solicitud(conn, solicitud_id, usuario_id)
    except ValueError as exc:
        return toast_error(request, str(exc), status_code=200)

    return await _render_mis_solicitudes(
        request, conn, context, pagina,
        toast_msg="Solicitud cancelada. Los días han sido liberados.",
        toast_type="success",
    )


@router.post("/solicitudes/{solicitud_id}/recordar")
async def recordar_aprobacion(
    request: Request,
    solicitud_id: UUID,
    pagina: int = Form(1),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_authenticated_session(),
):
    usuario_id = _get_usuario_id(context)
    try:
        await service.enviar_recordatorio_manual(conn, solicitud_id, usuario_id)
    except ValueError as exc:
        return toast_error(request, str(exc), status_code=200)

    return await _render_mis_solicitudes(
        request, conn, context, pagina,
        toast_msg="Recordatorio enviado al aprobador.",
        toast_type="success",
    )


@router.get("/solicitudes/{solicitud_id}/pdf")
async def descargar_pdf(
    solicitud_id: UUID,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_authenticated_session(),
):
    usuario_id = _get_usuario_id(context)
    solicitud = await db.get_solicitud(conn, solicitud_id)
    if not solicitud:
        raise HTTPException(404)
    if solicitud.get("es_migracion"):
        raise HTTPException(status_code=400, detail="Los registros historicos no generan PDF.")
    es_dueno = solicitud["usuario_id"] == usuario_id
    es_aprobador = await service.puede_aprobar(conn, solicitud_id, usuario_id, context)
    es_rh = user_has_module_access("rrhh", context, "viewer")
    if not es_dueno and not es_aprobador and not es_rh:
        raise HTTPException(403)

    pdf_bytes = await service.generar_pdf_solicitud(conn, solicitud_id)
    folio = service._generar_folio(solicitud)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{folio}.pdf"'},
    )


# ─────────────────────────────────────────────
# Aprobaciones
# ─────────────────────────────────────────────

async def _render_aprobaciones(request: Request, conn, context: dict, **extra):
    ctx = await service.get_aprobaciones_ctx_svc(conn, context, **extra)
    return templates.TemplateResponse(request, "vacaciones/partials/aprobaciones.html", ctx)


@router.get("/aprobaciones")
async def mis_aprobaciones(
    request: Request,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    return await _render_aprobaciones(request, conn, context)


@router.get("/aprobaciones/historial")
async def historial_aprobaciones_pagina(
    request: Request,
    pagina: int = Query(1, ge=1),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_authenticated_session(),
):
    usuario_id = _get_usuario_id(context)
    historial, tiene_siguiente = await service.get_historial_aprobaciones_pagina_svc(conn, usuario_id, pagina)
    return templates.TemplateResponse(
        request,
        "vacaciones/partials/historial_aprobaciones.html",
        {
            "historial": historial,
            "historial_pagina": pagina,
            "historial_tiene_siguiente": tiene_siguiente,
            "context": context,
        },
    )


@router.post("/solicitudes/{solicitud_id}/aprobar")
async def aprobar_solicitud(
    request: Request,
    solicitud_id: UUID,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_authenticated_session(),
):
    usuario_id = _get_usuario_id(context)
    try:
        aprobada = await service.aprobar_solicitud(conn, solicitud_id, usuario_id, context)
    except ValueError as exc:
        return toast_error(request, str(exc), status_code=200)
    return await _render_aprobaciones(
        request, conn, context,
        toast_msg=f"Solicitud de {aprobada['solicitante_nombre']} aprobada.",
        toast_type="success",
    )


@router.post("/solicitudes/{solicitud_id}/rechazar")
async def rechazar_solicitud(
    request: Request,
    solicitud_id: UUID,
    motivo: str = Form(...),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_authenticated_session(),
):
    usuario_id = _get_usuario_id(context)
    try:
        await service.rechazar_solicitud(conn, solicitud_id, usuario_id, motivo, context)
    except ValueError as exc:
        return toast_error(request, str(exc), status_code=200)
    return await _render_aprobaciones(
        request, conn, context,
        toast_msg="Solicitud rechazada.",
        toast_type="success",
    )


# ─────────────────────────────────────────────
# Equipo
# ─────────────────────────────────────────────

@router.get("/equipo")
async def mi_equipo(
    request: Request,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_authenticated_session(),
):
    usuario_id = _get_usuario_id(context)
    equipo_ctx = await service.get_equipo_dashboard(conn, usuario_id, context)
    return templates.TemplateResponse(
        request,
        "vacaciones/partials/equipo.html",
        {**equipo_ctx, "context": context},
    )


@router.get("/equipo/horas-extra-omitidas")
async def horas_extra_omitidas(
    request: Request,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_authenticated_session(),
):
    usuario_id = _get_usuario_id(context)
    ids_jefe = await db.get_empleados_donde_soy_jefe(conn, usuario_id)
    ids_aprobador = await db.get_empleados_donde_soy_aprobador(conn, usuario_id)
    equipo_ids = list({*ids_jefe, *ids_aprobador})
    equipo_visible_he, autorizable_he_set = await get_equipo_visible_he(
        conn, usuario_id, context, equipo_ids
    )
    hoy = today_mx()
    rows = await asistencia_db.get_horas_extra_omitidas_equipo(
        conn, equipo_visible_he, hoy - timedelta(days=30), hoy
    )
    marcar_puede_autorizar_he(rows, autorizable_he_set)
    for row in rows:
        row["extra_fmt"] = format_minutes(row.get("minutos_extra") or 0)
        row["entrada_fmt"] = fmt_time_mx(row.get("primera_entrada"))
        row["salida_fmt"] = fmt_time_mx(row.get("ultima_salida"))
    return templates.TemplateResponse(
        request,
        "vacaciones/partials/horas_extra_omitidas.html",
        {"omitidas": rows, "context": context},
    )


@router.get("/equipo/{uid}")
async def detalle_equipo_usuario(
    request: Request,
    uid: UUID,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_authenticated_session(),
):
    usuario_id = _get_usuario_id(context)
    if not (
        user_has_module_access("rrhh", context, "viewer")
        or uid in await db.get_empleados_donde_soy_jefe(conn, usuario_id)
        or uid in await db.get_empleados_donde_soy_aprobador(conn, usuario_id)
    ):
        raise HTTPException(403)
    balance = await service.get_balance_usuario(conn, uid)
    usuario_equipo = await db.get_usuario_simple_by_id(conn, uid)
    return templates.TemplateResponse(
        request,
        "vacaciones/partials/balance.html",
        {"balance": balance, "usuario_equipo": usuario_equipo or {}, "context": context},
    )
