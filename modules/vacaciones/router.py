from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from fastapi.templating import Jinja2Templates

from core.database import get_db_connection
from core.permissions import user_has_module_access
from core.security import get_current_user_context
from modules.shared import signatures_db_service as signatures_db
from modules.shared.utils import is_htmx, toast_error
from modules.vacaciones import db_service as db
from modules.vacaciones import service
from modules.vacaciones.logic import contar_dias_habiles, siguiente_dia_habil

router = APIRouter(prefix="/vacaciones", tags=["vacaciones"])
templates = Jinja2Templates(directory="templates")



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
):
    usuario_id = UUID(str(context["user_db_id"]))
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
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    usuario_id = UUID(str(context["user_db_id"]))
    solicitudes = await db.get_solicitudes_usuario(conn, usuario_id)
    return templates.TemplateResponse(
        request,
        "vacaciones/partials/mis_solicitudes.html",
        {"solicitudes": solicitudes, "context": context},
    )


@router.get("/solicitudes/nueva")
async def form_nueva_solicitud(
    request: Request,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    usuario_id = UUID(str(context["user_db_id"]))
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
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    usuario_id = UUID(str(context["user_db_id"]))
    try:
        fecha_inicio_date = date.fromisoformat(fecha_inicio)
        fecha_fin_date = date.fromisoformat(fecha_fin)
        fecha_presentarse_date = date.fromisoformat(fecha_presentarse) if fecha_presentarse else None
    except ValueError:
        return toast_error(request, "Las fechas capturadas no son válidas", status_code=200)

    try:
        result = await service.crear_solicitud(
            conn,
            usuario_id=usuario_id,
            tipo_ausencia_id=tipo_ausencia_id,
            fecha_inicio=fecha_inicio_date,
            fecha_fin=fecha_fin_date,
            fecha_presentarse=fecha_presentarse_date,
            observaciones=observaciones or None,
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
        )

    solicitudes = await db.get_solicitudes_usuario(conn, usuario_id)
    balance = await service.get_balance_usuario(conn, usuario_id)
    return templates.TemplateResponse(
        request,
        "vacaciones/partials/mis_solicitudes.html",
        {
            "solicitudes": solicitudes,
            "balance": balance,
            "context": context,
            "toast_msg": f"Solicitud enviada ({result['dias']} días hábiles). El aprobador será notificado.",
            "toast_type": "success",
        },
    )


@router.get("/solicitudes/{solicitud_id}")
async def detalle_solicitud(
    request: Request,
    solicitud_id: UUID,
    origen: str = "solicitudes",
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    es_request_htmx = is_htmx(request)
    origenes_validos = {"solicitudes", "aprobaciones", "rrhh_aprobaciones", "rrhh_solicitudes"}
    if origen not in origenes_validos:
        origen = "solicitudes"
    solicitud = await db.get_solicitud(conn, solicitud_id)
    if not solicitud:
        raise HTTPException(404)
    usuario_id = UUID(str(context["user_db_id"]))
    es_dueno = solicitud["usuario_id"] == usuario_id
    es_aprobador = await service.puede_aprobar(conn, solicitud_id, usuario_id, context)
    if not es_dueno and not es_aprobador:
        raise HTTPException(403)
    if not es_dueno and es_aprobador and origen == "solicitudes":
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
        "context": context,
    }
    if es_request_htmx:
        return templates.TemplateResponse(
            request,
            "vacaciones/partials/detalle_solicitud.html",
            ctx,
        )

    es_jefe = await service.es_jefe_o_aprobador_de_alguien(conn, usuario_id)
    es_rrhh_viewer = user_has_module_access("rrhh", context, "viewer")
    if user_has_module_access("rrhh", context, "editor"):
        pendientes_aprobacion = await db.get_todas_solicitudes_pendientes(conn)
    elif es_jefe:
        pendientes_aprobacion = await db.get_solicitudes_pendientes_para_aprobador(conn, usuario_id)
    else:
        pendientes_aprobacion = []

    ctx.update(
        {
            "es_jefe_o_aprobador": es_jefe or es_rrhh_viewer,
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
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    usuario_id = UUID(str(context["user_db_id"]))
    try:
        await service.cancelar_solicitud(conn, solicitud_id, usuario_id)
    except ValueError as exc:
        return toast_error(request, str(exc), status_code=200)

    solicitudes = await db.get_solicitudes_usuario(conn, usuario_id)
    balance = await service.get_balance_usuario(conn, usuario_id)
    return templates.TemplateResponse(
        request,
        "vacaciones/partials/mis_solicitudes.html",
        {
            "solicitudes": solicitudes,
            "balance": balance,
            "context": context,
            "toast_msg": "Solicitud cancelada. Los días han sido liberados.",
            "toast_type": "success",
        },
    )


@router.get("/solicitudes/{solicitud_id}/pdf")
async def descargar_pdf(
    solicitud_id: UUID,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    usuario_id = UUID(str(context["user_db_id"]))
    solicitud = await db.get_solicitud(conn, solicitud_id)
    if not solicitud:
        raise HTTPException(404)
    if solicitud.get("es_migracion"):
        raise HTTPException(status_code=400, detail="Los registros historicos no generan PDF.")
    es_dueno = solicitud["usuario_id"] == usuario_id
    es_aprobador = await service.puede_aprobar(conn, solicitud_id, usuario_id, context)
    es_rh = user_has_module_access("rrhh", context, "editor")
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

_HISTORIAL_PAGE_SIZE = 10


async def _get_historial_pagina(conn, usuario_id: UUID, es_rrhh: bool, pagina: int) -> tuple[list, bool]:
    offset = (pagina - 1) * _HISTORIAL_PAGE_SIZE
    fetch = _HISTORIAL_PAGE_SIZE + 1
    rows = await db.get_historial_aprobaciones(
        conn,
        limit=fetch,
        offset=offset,
        aprobador_id=None if es_rrhh else usuario_id,
    )
    tiene_siguiente = len(rows) > _HISTORIAL_PAGE_SIZE
    return rows[:_HISTORIAL_PAGE_SIZE], tiene_siguiente


async def _render_aprobaciones(request: Request, conn, context: dict, **extra):
    usuario_id = UUID(str(context["user_db_id"]))
    es_rrhh = user_has_module_access("rrhh", context, "editor")
    if es_rrhh:
        pendientes = await db.get_todas_solicitudes_pendientes(conn)
    else:
        pendientes = await db.get_solicitudes_pendientes_para_aprobador(conn, usuario_id)
    historial, tiene_siguiente = await _get_historial_pagina(conn, usuario_id, es_rrhh, 1)
    return templates.TemplateResponse(
        request,
        "vacaciones/partials/aprobaciones.html",
        {
            "pendientes": pendientes,
            "historial": historial,
            "historial_pagina": 1,
            "historial_tiene_siguiente": tiene_siguiente,
            "context": context,
            **extra,
        },
    )


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
):
    usuario_id = UUID(str(context["user_db_id"]))
    es_rrhh = user_has_module_access("rrhh", context, "editor")
    historial, tiene_siguiente = await _get_historial_pagina(conn, usuario_id, es_rrhh, pagina)
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
):
    usuario_id = UUID(str(context["user_db_id"]))
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
):
    usuario_id = UUID(str(context["user_db_id"]))
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
):
    usuario_id = UUID(str(context["user_db_id"]))
    equipo_ctx = await service.get_equipo_dashboard(conn, usuario_id, context)
    return templates.TemplateResponse(
        request,
        "vacaciones/partials/equipo.html",
        {**equipo_ctx, "context": context},
    )


@router.get("/equipo/{uid}")
async def detalle_equipo_usuario(
    request: Request,
    uid: UUID,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    usuario_id = UUID(str(context["user_db_id"]))
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
