from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from fastapi.templating import Jinja2Templates

from core.database import get_db_connection
from core.permissions import user_has_module_access
from core.security import get_current_user_context
from modules.shared import signatures_db_service as signatures_db
from modules.vacaciones import db_service as db
from modules.vacaciones import service

router = APIRouter(prefix="/vacaciones", tags=["vacaciones"])
templates = Jinja2Templates(directory="templates")


def _toast_error(request: Request, message: str, status_code: int = 400):
    return templates.TemplateResponse(
        request,
        "shared/toast.html",
        {"type": "error", "title": "Error", "message": message},
        status_code=status_code,
        headers={"HX-Reswap": "none"},
    )


# ─────────────────────────────────────────────
# Utilidad: cálculo de días hábiles (usado por el formulario vía JS)
# ─────────────────────────────────────────────

@router.get("/dias-habiles")
async def dias_habiles(
    inicio: str = Query(...),
    fin: str = Query(...),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    from datetime import date
    from modules.vacaciones.logic import contar_dias_habiles

    try:
        d_inicio = date.fromisoformat(inicio)
        d_fin = date.fromisoformat(fin)
    except ValueError:
        return JSONResponse({"dias": 0})
    festivos = await db.get_festivos_set(conn)
    dias = contar_dias_habiles(d_inicio, d_fin, festivos)
    return JSONResponse({"dias": max(dias, 0)})


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
    fecha_presentarse: str = Form(...),
    observaciones: str = Form(None),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    from datetime import date

    usuario_id = UUID(str(context["user_db_id"]))
    try:
        result = await service.crear_solicitud(
            conn,
            usuario_id=usuario_id,
            tipo_ausencia_id=tipo_ausencia_id,
            fecha_inicio=date.fromisoformat(fecha_inicio),
            fecha_fin=date.fromisoformat(fecha_fin),
            fecha_presentarse=date.fromisoformat(fecha_presentarse),
            observaciones=observaciones or None,
        )
    except ValueError as exc:
        return _toast_error(request, str(exc))

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
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    solicitud = await db.get_solicitud(conn, solicitud_id)
    if not solicitud:
        raise HTTPException(404)
    usuario_id = UUID(str(context["user_db_id"]))
    es_dueno = solicitud["usuario_id"] == usuario_id
    es_aprobador = await service.puede_aprobar(conn, solicitud_id, usuario_id, context)
    if not es_dueno and not es_aprobador:
        raise HTTPException(403)
    firmas = await db.get_firmas_solicitud(conn, solicitud_id)
    return templates.TemplateResponse(
        request,
        "vacaciones/partials/detalle_solicitud.html",
        {
            "solicitud": solicitud,
            "firmas": firmas,
            "es_aprobador": es_aprobador,
            "es_dueno": es_dueno,
            "context": context,
        },
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
        return _toast_error(request, str(exc))

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
    if not es_dueno and not es_aprobador:
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

@router.get("/aprobaciones")
async def mis_aprobaciones(
    request: Request,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    usuario_id = UUID(str(context["user_db_id"]))
    if user_has_module_access("rrhh", context, "editor"):
        pendientes = await db.get_todas_solicitudes_pendientes(conn)
    else:
        pendientes = await db.get_solicitudes_pendientes_para_aprobador(conn, usuario_id)
    return templates.TemplateResponse(
        request,
        "vacaciones/partials/aprobaciones.html",
        {"pendientes": pendientes, "context": context},
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
        return _toast_error(request, str(exc))

    if user_has_module_access("rrhh", context, "editor"):
        pendientes = await db.get_todas_solicitudes_pendientes(conn)
    else:
        pendientes = await db.get_solicitudes_pendientes_para_aprobador(conn, usuario_id)
    return templates.TemplateResponse(
        request,
        "vacaciones/partials/aprobaciones.html",
        {
            "pendientes": pendientes,
            "context": context,
            "toast_msg": f"Solicitud de {aprobada['solicitante_nombre']} aprobada.",
            "toast_type": "success",
        },
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
        return _toast_error(request, str(exc))

    if user_has_module_access("rrhh", context, "editor"):
        pendientes = await db.get_todas_solicitudes_pendientes(conn)
    else:
        pendientes = await db.get_solicitudes_pendientes_para_aprobador(conn, usuario_id)
    return templates.TemplateResponse(
        request,
        "vacaciones/partials/aprobaciones.html",
        {
            "pendientes": pendientes,
            "context": context,
            "toast_msg": "Solicitud rechazada.",
            "toast_type": "success",
        },
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
