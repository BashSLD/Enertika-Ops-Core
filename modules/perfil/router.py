from __future__ import annotations

import base64
import binascii
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from core.database import get_db_connection
from core.permissions import user_has_module_access
from core.security import get_current_user_context
from modules.perfil import db_service as perfil_db
from modules.perfil import service as perfil_service
from modules.shared import signatures_db_service as signatures_db
from modules.shared.utils import is_htmx, toast_error
from modules.vacaciones import db_service as vac_db
from modules.vacaciones import service as vac_service

router = APIRouter(prefix="/perfil", tags=["perfil"])
templates = Jinja2Templates(directory="templates")

PERFIL_TAB_ENDPOINTS = {
    "vacaciones": "/vacaciones/balance",
    "solicitudes": "/vacaciones/solicitudes",
    "aprobaciones": "/vacaciones/aprobaciones",
    "equipo": "/vacaciones/equipo",
    "firma": "/perfil/firma",
}


def _legacy_redirect(path: str) -> RedirectResponse:
    return RedirectResponse(url=f"/vacaciones{path}", status_code=301)


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

    initial_tab = tab if tab in PERFIL_TAB_ENDPOINTS else "vacaciones"
    if initial_tab in {"aprobaciones", "equipo"} and not es_jefe_o_aprobador:
        initial_tab = "vacaciones"
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
    usuario_id = UUID(str(context["user_db_id"]))
    perfil = await perfil_db.get_perfil_usuario(conn, usuario_id)
    context_perfil = _context_con_perfil(context, perfil)
    balance = await vac_service.get_balance_usuario(conn, usuario_id)
    solicitudes = await vac_db.get_solicitudes_usuario(conn, usuario_id)
    tipos = await vac_db.get_tipos_ausencia(conn)
    firma = await signatures_db.get_firma_usuario(conn, usuario_id)
    es_jefe = await vac_service.es_jefe_o_aprobador_de_alguien(conn, usuario_id)
    es_rrhh_viewer = user_has_module_access("rrhh", context_perfil, "viewer")
    es_rrhh_editor = user_has_module_access("rrhh", context_perfil, "editor")
    if es_rrhh_editor:
        pendientes_aprobacion = await vac_db.get_todas_solicitudes_pendientes(conn)
    elif es_jefe:
        pendientes_aprobacion = await vac_db.get_solicitudes_pendientes_para_aprobador(conn, usuario_id)
    else:
        pendientes_aprobacion = []
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
        "pendientes_aprobaciones_count": len(pendientes_aprobacion),
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
    usuario_id = UUID(str(context["user_db_id"]))
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
    usuario_id = UUID(str(context["user_db_id"]))
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
    usuario_id = UUID(str(context["user_db_id"]))
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
