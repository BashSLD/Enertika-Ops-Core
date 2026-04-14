# modules/calculadora_polizas/router.py
"""
Router del Módulo Calculadora Pólizas.

Endpoints:
- GET  /calculadora-polizas/ui                          — Dashboard + calculadora
- GET  /calculadora-polizas/api/plantas                 — JSON dropdown
- POST /calculadora-polizas/api/calcular                — HTMX → resultado.html
- POST /calculadora-polizas/cotizaciones/guardar        — Guarda cotización
- GET  /calculadora-polizas/cotizaciones/ui             — Polizas Generadas
- PATCH /calculadora-polizas/cotizaciones/{id}/estatus  — Actualizar estatus (editor+ oym)
- GET  /calculadora-polizas/cotizaciones/{id}/asignar-modal — Decision ACEPTADA/RECHAZADA (editor+ comercial)
- PATCH /calculadora-polizas/cotizaciones/{id}/asignar  — Guardar decision + email creador (editor+ comercial)
- GET  /calculadora-polizas/cotizaciones/{id}/editar-modal — Modal edicion (editor+ oym)
- PUT  /calculadora-polizas/cotizaciones/{id}           — Guardar edicion recalculada (editor+)
- GET  /calculadora-polizas/plantas/ui                  — CRUD plantas (editor+)
- POST /calculadora-polizas/plantas/import-excel        — Import .xlsx (editor+)
- POST /calculadora-polizas/plantas                     — Crear planta (editor+)
- POST /calculadora-polizas/plantas/{id}/toggle         — Activar/desactivar (editor+)
- GET  /calculadora-polizas/admin/ui                    — Editar precios/costos (manager+)
- PATCH /calculadora-polizas/admin/precios-zona/{zona}
- PATCH /calculadora-polizas/admin/wattabit/{id}
- PATCH /calculadora-polizas/admin/costos-fijos/{concepto}
"""

from fastapi import APIRouter, Depends, Request, Form, File, UploadFile, Query, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse, Response
from typing import Optional, List
from uuid import UUID
import json
import logging
from datetime import datetime
import pytz

from core.database import get_db_connection
from core.security import get_current_user_context
from core.permissions import require_module_access, require_manager_access, user_has_module_access
from core.config import settings

from .service import CalculadoraService, get_service
from .schemas import CalcularRequest, EstatusCotizacion
from core.pdf_service.service import get_pdf_service, PDFService

logger = logging.getLogger("CalculadoraPolizas.Router")
templates = Jinja2Templates(directory="templates")
templates.env.globals["DEBUG_MODE"] = settings.DEBUG_MODE

from core.jinja_filters import register_timezone_filters
register_timezone_filters(templates.env)

router = APIRouter(prefix="/calculadora-polizas", tags=["Modulo Calculadora Polizas"])

SLUG = "oym"          # sub-herramienta de O&M — hereda permisos del módulo oym
TPL = "calculadora_polizas"

_MESES_ES = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
    5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
    9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre",
}


def _base_ctx(context: dict, mod_role: str) -> dict:
    is_admin = context.get("role") == "ADMIN"
    return {
        "user_name": context.get("user_name"),
        "role": context.get("role"),
        "module_roles": context.get("module_roles", {}),
        "current_module_role": mod_role,
        "puede_editar": mod_role in ("editor", "admin") or is_admin,
        "puede_admin": mod_role == "admin" or is_admin or context.get("role") == "MANAGER",
    }


def _parse_cotizacion_id(cotizacion_id: str) -> UUID:
    try:
        return UUID(cotizacion_id)
    except ValueError:
        raise HTTPException(404, "Cotizacion no encontrada")


def _plantas_for_template(plantas_db: list) -> list:
    return [
        {
            "id": p["id"], "nombre": p["nombre"], "zona": p["zona"],
            "potencia_kw": float(p["potencia_kw"]) if p["potencia_kw"] else None,
            "num_paneles": p["num_paneles"],
        }
        for p in plantas_db
    ]


# ============================================================
# UI PRINCIPAL
# ============================================================

@router.api_route("/ui", methods=["GET", "HEAD"], include_in_schema=False)
async def get_calculadora_ui(
    request: Request,
    context=Depends(get_current_user_context),
    _=require_module_access(SLUG),
    conn=Depends(get_db_connection),
    service: CalculadoraService = Depends(get_service),
):
    mod_role = context.get("module_roles", {}).get("oym", "viewer")
    plantas_db = await service.db.get_plantas_dropdown(conn)
    plantas = _plantas_for_template(plantas_db)
    costos = await service.db.get_costos_fijos(conn)

    ctx = {
        **_base_ctx(context, mod_role),
        "plantas": plantas,
        "utilidad_default": costos.get("utilidad_default", 0.30),
        "resultado": None,
    }

    if request.headers.get("hx-request") and not request.headers.get("hx-history-restore-request"):
        return templates.TemplateResponse(request, f"{TPL}/partials/content.html", ctx)
    return templates.TemplateResponse(request, f"{TPL}/dashboard.html", ctx)


# ============================================================
# API: PLANTAS DROPDOWN (JSON)
# ============================================================

@router.get("/api/plantas", include_in_schema=False)
async def api_plantas(
    context=Depends(get_current_user_context),
    _=require_module_access(SLUG),
    conn=Depends(get_db_connection),
    service: CalculadoraService = Depends(get_service),
):
    plantas = await service.db.get_plantas_dropdown(conn)
    return JSONResponse(_plantas_for_template(plantas))


# ============================================================
# CALCULAR (HTMX)
# ============================================================

@router.post("/api/calcular", include_in_schema=False)
async def calcular(
    request: Request,
    planta_id: str = Form(...),
    tipo_poliza: str = Form(...),
    utilidad: float = Form(0.30),
    descuento_pct: float = Form(0.0),
    descuento_anios: List[int] = Form(default=[]),
    context=Depends(get_current_user_context),
    _=require_module_access(SLUG),
    conn=Depends(get_db_connection),
    service: CalculadoraService = Depends(get_service),
):
    mod_role = context.get("module_roles", {}).get("oym", "viewer")
    try:
        req = CalcularRequest(
            planta_id=planta_id, tipo_poliza=tipo_poliza, utilidad=utilidad,
            descuento_pct=descuento_pct, descuento_anios=descuento_anios,
        )
        resultado = await service.calcular(conn, req)
    except ValueError as exc:
        return templates.TemplateResponse(
            request, f"{TPL}/partials/resultado.html",
            {**_base_ctx(context, mod_role), "resultado": None, "error": str(exc)},
            status_code=422,
        )

    return templates.TemplateResponse(
        request, f"{TPL}/partials/resultado.html",
        {**_base_ctx(context, mod_role), "resultado": resultado, "error": None},
    )


# ============================================================
# GUARDAR COTIZACIÓN
# ============================================================

@router.get("/partials/guardar-modal", include_in_schema=False)
async def guardar_modal(
    request: Request,
    planta_id: str = Query(...),
    tipo_poliza: str = Query(...),
    utilidad: float = Query(0.30),
    descuento_pct: float = Query(0.0),
    descuento_anios: str = Query(""),   # lista como "3,5" o "" si no aplica
    context=Depends(get_current_user_context),
    _=require_module_access(SLUG),
    conn=Depends(get_db_connection),
    service: CalculadoraService = Depends(get_service),
):
    usuarios_comercial = await service.db.get_usuarios_comercial(conn)
    mod_role = context.get("module_roles", {}).get("oym", "viewer")
    anios_list = [int(x) for x in descuento_anios.split(",") if x.strip().isdigit()]
    return templates.TemplateResponse(
        request, f"{TPL}/partials/guardar_cotizacion_modal.html",
        {
            **_base_ctx(context, mod_role),
            "planta_id": planta_id,
            "tipo_poliza": tipo_poliza,
            "utilidad": utilidad,
            "descuento_pct": descuento_pct,
            "descuento_anios": anios_list,
            "usuarios_comercial": usuarios_comercial,
        },
    )


@router.post("/cotizaciones/guardar", include_in_schema=False)
async def guardar_cotizacion(
    request: Request,
    planta_id: str = Form(...),
    tipo_poliza: str = Form(...),
    utilidad: float = Form(0.30),
    descuento_pct: float = Form(0.0),
    descuento_anios: List[int] = Form(default=[]),
    solicitante_id: Optional[str] = Form(None),
    context=Depends(get_current_user_context),
    _=require_module_access(SLUG),
    conn=Depends(get_db_connection),
    service: CalculadoraService = Depends(get_service),
):
    user_id = context.get("user_db_id")
    sol_id = None
    if solicitante_id and solicitante_id.strip():
        try:
            sol_id = UUID(solicitante_id)
        except ValueError:
            pass
    try:
        req = CalcularRequest(
            planta_id=planta_id, tipo_poliza=tipo_poliza, utilidad=utilidad,
            descuento_pct=descuento_pct, descuento_anios=descuento_anios,
        )
        resultado = await service.calcular(conn, req)
        await service.guardar_cotizacion(conn, resultado, user_id, solicitante_id=sol_id)
    except ValueError as exc:
        return templates.TemplateResponse(
            request, "shared/toast.html",
            {"type": "error", "title": "Error", "message": str(exc)},
            headers={"HX-Reswap": "none"},
        )

    return templates.TemplateResponse(
        request, "shared/toast.html",
        {"type": "success", "title": "Guardado", "message": "Cotizacion guardada correctamente"},
        headers={"HX-Reswap": "none"},
    )


# ============================================================
# POLIZAS GENERADAS (cotizaciones)
# ============================================================

async def _build_cotizaciones_ctx(context, conn, service, page: int,
                                  estatus_filter: Optional[str]) -> dict:
    mod_role = context.get("module_roles", {}).get("oym", "viewer")
    per_page = 50
    offset = (page - 1) * per_page
    ef = estatus_filter or None
    cotizaciones = await service.db.get_cotizaciones(conn, limit=per_page, offset=offset, estatus_filter=ef)
    total = await service.db.count_cotizaciones(conn, estatus_filter=ef)
    resumen = await service.db.get_resumen_estatus(conn)
    return {
        **_base_ctx(context, mod_role),
        "cotizaciones": cotizaciones,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, -(-total // per_page)),
        "estatus_filter": estatus_filter or "",
        "resumen": resumen,
    }


@router.get("/cotizaciones/ui", include_in_schema=False)
async def cotizaciones_ui(
    request: Request,
    page: int = Query(1, ge=1),
    estatus_filter: Optional[str] = Query(None),
    context=Depends(get_current_user_context),
    _=require_module_access(SLUG),
    conn=Depends(get_db_connection),
    service: CalculadoraService = Depends(get_service),
):
    ctx = await _build_cotizaciones_ctx(context, conn, service, page, estatus_filter)
    if request.headers.get("hx-request") and not request.headers.get("hx-history-restore-request"):
        return templates.TemplateResponse(request, f"{TPL}/partials/cotizaciones_tabla.html", ctx)
    return templates.TemplateResponse(request, f"{TPL}/cotizaciones.html", ctx)


@router.patch("/cotizaciones/{cotizacion_id}/estatus", include_in_schema=False)
async def update_cotizacion_estatus(
    request: Request,
    cotizacion_id: str,
    estatus: EstatusCotizacion = Form(...),
    estatus_filter: str = Form(""),
    page: int = Form(1),
    context=Depends(get_current_user_context),
    _=require_module_access(SLUG, "editor"),
    conn=Depends(get_db_connection),
    service: CalculadoraService = Depends(get_service),
):
    uid = _parse_cotizacion_id(cotizacion_id)
    user_id = context.get("user_db_id")
    ok = await service.db.update_cotizacion_estatus(conn, uid, estatus, user_id)
    if not ok:
        raise HTTPException(404, "Cotizacion no encontrada")

    ef = estatus_filter or None
    ctx = await _build_cotizaciones_ctx(context, conn, service, page, ef)
    return templates.TemplateResponse(request, f"{TPL}/partials/cotizaciones_tabla.html", ctx)


# ============================================================
# RESUMEN EMBEBIDO (para tab en OyM)
# ============================================================

@router.get("/partials/polizas-resumen", include_in_schema=False)
async def polizas_resumen(
    request: Request,
    context=Depends(get_current_user_context),
    _=require_module_access(SLUG),
    conn=Depends(get_db_connection),
    service: CalculadoraService = Depends(get_service),
):
    mod_role = context.get("module_roles", {}).get("oym", "viewer")
    cotizaciones = await service.db.get_cotizaciones(conn, limit=20, offset=0)
    resumen = await service.db.get_resumen_estatus(conn)
    return templates.TemplateResponse(
        request, f"{TPL}/partials/polizas_resumen.html",
        {
            **_base_ctx(context, mod_role),
            "cotizaciones": cotizaciones,
            "resumen": resumen,
        },
    )


# ============================================================
# PÓLIZAS PARA MÓDULO COMERCIAL
# ============================================================

@router.get("/partials/polizas-comercial", include_in_schema=False)
async def polizas_comercial(
    request: Request,
    page: int = Query(1, ge=1),
    estatus_filter: Optional[str] = Query(None),
    context=Depends(get_current_user_context),
    _=require_module_access("comercial"),
    conn=Depends(get_db_connection),
    service: CalculadoraService = Depends(get_service),
):
    role = context.get("role", "USER")
    user_id = context.get("user_db_id")
    es_admin_o_manager = role in ("ADMIN", "MANAGER")
    es_admin_modulo = user_has_module_access("comercial", context, "admin")
    ver_todas = es_admin_o_manager or es_admin_modulo

    per_page = 50
    offset = (page - 1) * per_page
    ef = estatus_filter or None

    cotizaciones = await service.db.get_cotizaciones_comercial(
        conn, limit=per_page, offset=offset,
        ver_todas=ver_todas, user_id=user_id, estatus_filter=ef,
    )
    total = await service.db.count_cotizaciones_comercial(
        conn, ver_todas=ver_todas, user_id=user_id, estatus_filter=ef,
    )

    comercial_role = context.get("module_roles", {}).get("comercial", "viewer")
    return templates.TemplateResponse(
        request, "comercial/partials/polizas_tab.html",
        {
            **_base_ctx(context, comercial_role),
            "cotizaciones": cotizaciones,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": max(1, -(-total // per_page)),
            "estatus_filter": estatus_filter or "",
            "ver_todas": ver_todas,
        },
    )


# ============================================================
# EDITAR COTIZACIÓN (editor+)
# ============================================================

@router.get("/cotizaciones/{cotizacion_id}/editar-modal", include_in_schema=False)
async def editar_cotizacion_modal(
    request: Request,
    cotizacion_id: str,
    estatus_filter: str = Query(""),
    page: int = Query(1, ge=1),
    context=Depends(get_current_user_context),
    _=require_module_access(SLUG, "editor"),
    conn=Depends(get_db_connection),
    service: CalculadoraService = Depends(get_service),
):
    uid = _parse_cotizacion_id(cotizacion_id)
    cotizacion = await service.db.get_cotizacion_by_id(conn, uid)
    if not cotizacion:
        raise HTTPException(404, "Cotizacion no encontrada")

    plantas_db = await service.db.get_plantas_dropdown(conn)
    plantas = _plantas_for_template(plantas_db)
    usuarios_comercial = await service.db.get_usuarios_comercial(conn)

    mod_role = context.get("module_roles", {}).get("oym", "viewer")
    return templates.TemplateResponse(
        request, f"{TPL}/partials/editar_cotizacion_modal.html",
        {
            **_base_ctx(context, mod_role),
            "cotizacion": cotizacion,
            "plantas": plantas,
            "usuarios_comercial": usuarios_comercial,
            "estatus_filter": estatus_filter,
            "page": page,
        },
    )


@router.put("/cotizaciones/{cotizacion_id}", include_in_schema=False)
async def update_cotizacion(
    request: Request,
    cotizacion_id: str,
    planta_id: str = Form(...),
    tipo_poliza: str = Form(...),
    utilidad: float = Form(0.30),
    descuento_pct: float = Form(0.0),
    descuento_anios: List[int] = Form(default=[]),
    solicitante_id: Optional[str] = Form(None),
    estatus_filter: str = Form(""),
    page: int = Form(1),
    context=Depends(get_current_user_context),
    _=require_module_access(SLUG, "editor"),
    conn=Depends(get_db_connection),
    service: CalculadoraService = Depends(get_service),
):
    uid = _parse_cotizacion_id(cotizacion_id)

    sol_id = None
    if solicitante_id and solicitante_id.strip():
        try:
            sol_id = UUID(solicitante_id)
        except ValueError:
            pass

    try:
        req = CalcularRequest(
            planta_id=planta_id, tipo_poliza=tipo_poliza, utilidad=utilidad,
            descuento_pct=descuento_pct, descuento_anios=descuento_anios,
        )
        resultado = await service.calcular(conn, req)
    except ValueError as exc:
        return templates.TemplateResponse(
            request, "shared/toast.html",
            {"type": "error", "title": "Error al recalcular", "message": str(exc)},
            headers={"HX-Reswap": "none"},
        )

    ok = await service.db.update_cotizacion_full(conn, uid, {
        "planta_id": resultado.planta_id,
        "nombre_planta": resultado.nombre_planta,
        "tipo_poliza": resultado.tipo_poliza,
        "utilidad": resultado.utilidad,
        "sub_total": resultado.sub_total,
        "sub_total_utilidad": resultado.sub_total_utilidad,
        "total_final": resultado.total_final,
        "resultado_json": resultado.model_dump(),
        "solicitante_id": sol_id,
        "descuento_pct": resultado.descuento_pct if resultado.descuento_pct > 0 else None,
        "descuento_anios": resultado.descuento_anios if resultado.descuento_anios else None,
    })
    if not ok:
        raise HTTPException(404, "Cotizacion no encontrada")

    ef = estatus_filter or None
    ctx = await _build_cotizaciones_ctx(context, conn, service, page, ef)
    return templates.TemplateResponse(request, f"{TPL}/partials/cotizaciones_tabla.html", ctx)


# ============================================================
# DECISION ACEPTADA/RECHAZADA (desde Comercial, editor+)
# ============================================================

@router.get("/cotizaciones/{cotizacion_id}/asignar-modal", include_in_schema=False)
async def asignar_modal(
    request: Request,
    cotizacion_id: str,
    page: int = Query(1, ge=1),
    estatus_filter: str = Query(""),
    context=Depends(get_current_user_context),
    _=require_module_access("comercial", "editor"),
    conn=Depends(get_db_connection),
    service: CalculadoraService = Depends(get_service),
):
    uid = _parse_cotizacion_id(cotizacion_id)
    cotizacion = await service.db.get_cotizacion_by_id(conn, uid)
    if not cotizacion:
        raise HTTPException(404, "Cotizacion no encontrada")

    comercial_role = context.get("module_roles", {}).get("comercial", "viewer")
    return templates.TemplateResponse(
        request, f"{TPL}/partials/asignar_cotizacion_modal.html",
        {
            **_base_ctx(context, comercial_role),
            "cotizacion": cotizacion,
            "page": page,
            "estatus_filter": estatus_filter,
        },
    )


@router.patch("/cotizaciones/{cotizacion_id}/asignar", include_in_schema=False)
async def asignar_cotizacion(
    request: Request,
    cotizacion_id: str,
    estatus: str = Form(...),
    page: int = Form(1),
    estatus_filter: str = Form(""),
    context=Depends(get_current_user_context),
    _=require_module_access("comercial", "editor"),
    conn=Depends(get_db_connection),
    service: CalculadoraService = Depends(get_service),
):
    from core.workflow.notification_service import NotificationService

    if estatus not in {"ACEPTADA", "RECHAZADA"}:
        return templates.TemplateResponse(
            request, "shared/toast.html",
            {"type": "error", "title": "Error", "message": "Solo se permite Aceptada o Rechazada"},
            headers={"HX-Reswap": "none"},
        )

    uid = _parse_cotizacion_id(cotizacion_id)
    cotizacion = await service.db.get_cotizacion_by_id(conn, uid)
    if not cotizacion:
        raise HTTPException(404, "Cotizacion no encontrada")

    user_id = context.get("user_db_id")
    ok = await service.db.update_cotizacion_estatus(conn, uid, estatus, user_id)
    if not ok:
        raise HTTPException(404, "Cotizacion no encontrada")

    # Notificar al creador por email (fire-and-forget)
    cotizacion_actualizada = {**cotizacion, "estatus": estatus}
    try:
        notif = NotificationService()
        await notif.notify_poliza_estatus_change(
            conn=conn,
            cotizacion_id=uid,
            cotizacion=cotizacion_actualizada,
            nuevo_estatus=estatus,
            changed_by_ctx=context,
        )
    except Exception as e:
        logger.error(f"[ASIGNAR] Error al notificar poliza {uid}: {e}", exc_info=True)

    # Reconstruir el listado del tab de Comercial con los mismos filtros activos
    role = context.get("role", "USER")
    es_admin_o_manager = role in ("ADMIN", "MANAGER")
    es_admin_modulo = user_has_module_access("comercial", context, "admin")
    ver_todas = es_admin_o_manager or es_admin_modulo

    per_page = 50
    offset = (page - 1) * per_page
    ef = estatus_filter or None

    cotizaciones = await service.db.get_cotizaciones_comercial(
        conn, limit=per_page, offset=offset,
        ver_todas=ver_todas, user_id=user_id, estatus_filter=ef,
    )
    total = await service.db.count_cotizaciones_comercial(
        conn, ver_todas=ver_todas, user_id=user_id, estatus_filter=ef,
    )

    comercial_role = context.get("module_roles", {}).get("comercial", "viewer")
    return templates.TemplateResponse(
        request, "comercial/partials/polizas_tab.html",
        {
            "user_name": context.get("user_name"),
            "role": role,
            "module_roles": context.get("module_roles", {}),
            "current_module_role": comercial_role,
            "cotizaciones": cotizaciones,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": max(1, -(-total // per_page)),
            "estatus_filter": estatus_filter,
            "ver_todas": ver_todas,
        },
    )


# ============================================================
# PLANTAS — CRUD (editor+)
# ============================================================

@router.get("/plantas/ui", include_in_schema=False)
async def plantas_ui(
    request: Request,
    q: Optional[str] = Query(None),
    context=Depends(get_current_user_context),
    _=require_module_access(SLUG, "editor"),
    conn=Depends(get_db_connection),
    service: CalculadoraService = Depends(get_service),
):
    mod_role = context.get("module_roles", {}).get("oym", "viewer")
    plantas = await service.db.get_plantas_list(conn, q)
    precios_zona = await service.db.get_precios_zona(conn)

    ctx = {
        **_base_ctx(context, mod_role),
        "plantas": plantas,
        "zonas": sorted(precios_zona.keys()),
        "q": q or "",
    }

    if request.headers.get("hx-request") and not request.headers.get("hx-history-restore-request"):
        return templates.TemplateResponse(request, f"{TPL}/partials/plantas_tabla.html", ctx)
    return templates.TemplateResponse(request, f"{TPL}/plantas.html", ctx)


@router.post("/plantas", include_in_schema=False)
async def crear_planta(
    request: Request,
    id: str = Form(...),
    nombre: str = Form(...),
    zona: str = Form(...),
    potencia_kw: Optional[float] = Form(None),
    num_paneles: Optional[int] = Form(None),
    cliente: Optional[str] = Form(None),
    direccion: Optional[str] = Form(None),
    context=Depends(get_current_user_context),
    _=require_module_access(SLUG, "editor"),
    conn=Depends(get_db_connection),
    service: CalculadoraService = Depends(get_service),
):
    mod_role = context.get("module_roles", {}).get("oym", "viewer")
    try:
        await service.db.upsert_planta(conn, {
            "id": id.strip().upper(),
            "nombre": nombre.strip(),
            "zona": zona.strip(),
            "potencia_kw": potencia_kw,
            "num_paneles": num_paneles,
            "cliente": cliente.strip() if cliente else None,
            "direccion": direccion.strip() if direccion else None,
            "activa": True,
        })
    except Exception as exc:
        logger.error("Error creando planta: %s", exc)
        return templates.TemplateResponse(
            request, "shared/toast.html",
            {"type": "error", "title": "Error", "message": "Error al crear la planta"},
            headers={"HX-Reswap": "none"},
        )

    plantas = await service.db.get_plantas_list(conn)
    precios_zona = await service.db.get_precios_zona(conn)
    return templates.TemplateResponse(
        request, f"{TPL}/partials/plantas_tabla.html",
        {**_base_ctx(context, mod_role), "plantas": plantas,
         "zonas": sorted(precios_zona.keys()), "q": ""},
    )


@router.post("/plantas/{planta_id}/toggle", include_in_schema=False)
async def toggle_planta(
    request: Request,
    planta_id: str,
    context=Depends(get_current_user_context),
    _=require_module_access(SLUG, "editor"),
    conn=Depends(get_db_connection),
    service: CalculadoraService = Depends(get_service),
):
    mod_role = context.get("module_roles", {}).get("oym", "viewer")
    nuevo_estado = await service.db.toggle_planta_activa(conn, planta_id)
    if nuevo_estado is None:
        raise HTTPException(404, "Planta no encontrada")
    plantas = await service.db.get_plantas_list(conn)
    precios_zona = await service.db.get_precios_zona(conn)
    return templates.TemplateResponse(
        request, f"{TPL}/partials/plantas_tabla.html",
        {**_base_ctx(context, mod_role), "plantas": plantas,
         "zonas": sorted(precios_zona.keys()), "q": ""},
    )


@router.post("/plantas/import-excel", include_in_schema=False)
async def import_excel(
    request: Request,
    archivo: UploadFile = File(...),
    context=Depends(get_current_user_context),
    _=require_module_access(SLUG, "editor"),
    conn=Depends(get_db_connection),
    service: CalculadoraService = Depends(get_service),
):
    mod_role = context.get("module_roles", {}).get("oym", "viewer")
    if not archivo.filename.endswith((".xlsx", ".xls")):
        return templates.TemplateResponse(
            request, "shared/toast.html",
            {"type": "error", "title": "Archivo invalido", "message": "Solo se aceptan archivos .xlsx"},
            headers={"HX-Reswap": "none"},
        )

    contenido = await archivo.read()
    try:
        resultado = await service.importar_plantas_excel(conn, contenido)
    except ValueError as exc:
        return templates.TemplateResponse(
            request, "shared/toast.html",
            {"type": "error", "title": "Error", "message": str(exc)},
            headers={"HX-Reswap": "none"},
        )

    msg = f"{resultado.insertadas} plantas nuevas, {resultado.actualizadas} actualizadas"
    if resultado.errores:
        msg += f". {len(resultado.errores)} con errores."
    toast_type = "success" if not resultado.errores else "warning"

    plantas = await service.db.get_plantas_list(conn)
    precios_zona = await service.db.get_precios_zona(conn)
    return templates.TemplateResponse(
        request, f"{TPL}/partials/plantas_tabla.html",
        {**_base_ctx(context, mod_role), "plantas": plantas,
         "zonas": sorted(precios_zona.keys()), "q": "",
         "import_msg": msg, "import_type": toast_type},
    )


# ============================================================
# ADMIN — EDICIÓN DE PRECIOS/COSTOS (manager+)
# ============================================================

@router.get("/admin/ui", include_in_schema=False)
async def admin_ui(
    request: Request,
    context=Depends(get_current_user_context),
    _=require_manager_access(SLUG),
    conn=Depends(get_db_connection),
    service: CalculadoraService = Depends(get_service),
):
    mod_role = context.get("module_roles", {}).get("oym", "viewer")
    ctx = {
        **_base_ctx(context, mod_role),
        "precios_zona": await service.db.get_precios_zona_list(conn),
        "wattabit": await service.db.get_wattabit_list(conn),
        "costos_fijos": await service.db.get_costos_fijos_list(conn),
    }
    if request.headers.get("hx-request") and not request.headers.get("hx-history-restore-request"):
        return templates.TemplateResponse(request, f"{TPL}/partials/admin_content.html", ctx)
    return templates.TemplateResponse(request, f"{TPL}/admin.html", ctx)


@router.patch("/admin/precios-zona/{zona}", include_in_schema=False)
async def update_precio_zona(
    request: Request,
    zona: str,
    precio: float = Form(...),
    context=Depends(get_current_user_context),
    _=require_manager_access(SLUG),
    conn=Depends(get_db_connection),
    service: CalculadoraService = Depends(get_service),
):
    if precio <= 0:
        raise HTTPException(400, "El precio debe ser mayor a 0")
    ok = await service.db.update_precio_zona(conn, zona, precio)
    if not ok:
        raise HTTPException(404, f"Zona '{zona}' no encontrada")
    return templates.TemplateResponse(
        request, "shared/toast.html",
        {"type": "success", "title": "Actualizado", "message": f"Precio de {zona} actualizado"},
        headers={"HX-Reswap": "none"},
    )


@router.patch("/admin/wattabit/{wattabit_id}", include_in_schema=False)
async def update_wattabit(
    request: Request,
    wattabit_id: int,
    precio: float = Form(...),
    context=Depends(get_current_user_context),
    _=require_manager_access(SLUG),
    conn=Depends(get_db_connection),
    service: CalculadoraService = Depends(get_service),
):
    if precio <= 0:
        raise HTTPException(400, "El precio debe ser mayor a 0")
    ok = await service.db.update_wattabit(conn, wattabit_id, precio)
    if not ok:
        raise HTTPException(404, "Registro Wattabit no encontrado")
    return templates.TemplateResponse(
        request, "shared/toast.html",
        {"type": "success", "title": "Actualizado", "message": "Precio Wattabit actualizado"},
        headers={"HX-Reswap": "none"},
    )


@router.patch("/admin/costos-fijos/{concepto}", include_in_schema=False)
async def update_costo_fijo(
    request: Request,
    concepto: str,
    valor: float = Form(...),
    context=Depends(get_current_user_context),
    _=require_manager_access(SLUG),
    conn=Depends(get_db_connection),
    service: CalculadoraService = Depends(get_service),
):
    if valor < 0:
        raise HTTPException(400, "El valor no puede ser negativo")
    ok = await service.db.update_costo_fijo(conn, concepto, valor)
    if not ok:
        raise HTTPException(404, f"Concepto '{concepto}' no encontrado")
    return templates.TemplateResponse(
        request, "shared/toast.html",
        {"type": "success", "title": "Actualizado", "message": f"{concepto} actualizado"},
        headers={"HX-Reswap": "none"},
    )


# ============================================================
# PDF — PROPUESTA DE PÓLIZA
# ============================================================

@router.get("/cotizaciones/{cotizacion_id}/pdf", include_in_schema=False)
async def descargar_pdf_poliza(
    cotizacion_id: str,
    show_projection: bool = Query(True),
    context=Depends(get_current_user_context),
    _=require_module_access(SLUG),
    conn=Depends(get_db_connection),
    service: CalculadoraService = Depends(get_service),
    pdf_service: PDFService = Depends(get_pdf_service),
):
    uid = _parse_cotizacion_id(cotizacion_id)
    cotizacion = await service.db.get_cotizacion_by_id(conn, uid)
    if not cotizacion:
        raise HTTPException(404, "Cotizacion no encontrada")

    resultado = cotizacion["resultado_json"]
    if isinstance(resultado, str):
        resultado = json.loads(resultado)

    planta = None
    if cotizacion.get("planta_id"):
        planta = await service.db.get_planta_by_id(conn, cotizacion["planta_id"])

    tz = pytz.timezone("America/Mexico_City")
    _dt = cotizacion["created_at"].astimezone(tz) if cotizacion.get("created_at") else datetime.now(tz)
    fecha_emision = f"{_dt.day} de {_MESES_ES[_dt.month]} de {_dt.year}"

    factor = 1.03
    anio_1 = resultado.get("anio_1", resultado.get("sub_total_utilidad", 0))
    descuento_pct = resultado.get("descuento_pct", 0.0)
    descuento_anios = resultado.get("descuento_anios") or []
    proyeccion = [
        {
            "anio": 1,
            "valor": round(anio_1, 2),
            "acumulado": round(anio_1, 2),
            "acumulado_desc": resultado.get("anio_1_desc") if 1 in descuento_anios else None,
        },
        {
            "anio": 3,
            "valor": round(anio_1 * (factor ** 2), 2),
            "acumulado": resultado.get("acumulado_1_3", 0),
            "acumulado_desc": resultado.get("acumulado_1_3_desc") if 3 in descuento_anios else None,
        },
        {
            "anio": 5,
            "valor": round(anio_1 * (factor ** 4), 2),
            "acumulado": resultado.get("acumulado_1_5", 0),
            "acumulado_desc": resultado.get("acumulado_1_5_desc") if 5 in descuento_anios else None,
        },
    ]

    sub_total_utilidad = resultado.get("sub_total_utilidad", 0)
    total_final = resultado.get("total_final", 0)

    ctx = {
        "folio": str(cotizacion["id"])[:8].upper(),
        "fecha_emision": fecha_emision,
        "ejecutivo": cotizacion.get("creado_por_nombre") or "Enertika Mexico",
        "nombre_planta": cotizacion.get("nombre_planta") or resultado.get("nombre_planta", ""),
        "cliente": planta.get("cliente") if planta else None,
        "direccion": planta.get("direccion") if planta else None,
        "zona": resultado.get("zona", ""),
        "potencia_kw": resultado.get("potencia_kw", 0),
        "num_paneles": resultado.get("num_paneles", 0),
        "tipo_poliza": resultado.get("tipo_poliza", "premium"),
        "nombre_wattabit": resultado.get("nombre_wattabit", ""),
        "sub_total_utilidad": sub_total_utilidad,
        "total_final": total_final,
        "proyeccion": proyeccion,
        "mostrar_proyeccion": show_projection,
        "descuento_pct": descuento_pct,
        "descuento_anios": descuento_anios,
        "descuento_monto": resultado.get("descuento_monto", 0.0),
    }

    pdf_bytes = await pdf_service.generate("poliza_oym.html", ctx)
    nombre_planta_clean = (cotizacion.get("nombre_planta") or "poliza").replace(" ", "_")
    filename = pdf_service.generate_filename("Propuesta_Poliza", nombre_planta_clean)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
