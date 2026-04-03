# modules/calculadora_polizas/router.py
"""
Router del Módulo Calculadora Pólizas.

Endpoints:
- GET  /calculadora-polizas/ui                    — Dashboard + calculadora
- GET  /calculadora-polizas/api/plantas           — JSON dropdown
- POST /calculadora-polizas/api/calcular          — HTMX → resultado.html
- POST /calculadora-polizas/cotizaciones/guardar  — Guarda cotización
- GET  /calculadora-polizas/cotizaciones/ui       — Historial
- GET  /calculadora-polizas/plantas/ui            — CRUD plantas (editor+)
- POST /calculadora-polizas/plantas/import-excel  — Import .xlsx (editor+)
- POST /calculadora-polizas/plantas               — Crear planta (editor+)
- POST /calculadora-polizas/plantas/{id}/toggle   — Activar/desactivar (editor+)
- GET  /calculadora-polizas/admin/ui              — Editar precios/costos (manager+)
- PATCH /calculadora-polizas/admin/precios-zona/{zona}
- PATCH /calculadora-polizas/admin/wattabit/{id}
- PATCH /calculadora-polizas/admin/costos-fijos/{concepto}
"""

from fastapi import APIRouter, Depends, Request, Form, File, UploadFile, Query, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse
from typing import Optional
import logging

from core.database import get_db_connection
from core.security import get_current_user_context
from core.permissions import require_module_access, require_manager_access
from core.config import settings

from .service import CalculadoraService, get_service
from .schemas import CalcularRequest

logger = logging.getLogger("CalculadoraPolizas.Router")
templates = Jinja2Templates(directory="templates")
templates.env.globals["DEBUG_MODE"] = settings.DEBUG_MODE

from core.jinja_filters import register_timezone_filters
register_timezone_filters(templates.env)

router = APIRouter(prefix="/calculadora-polizas", tags=["Modulo Calculadora Polizas"])

SLUG = "oym"          # sub-herramienta de O&M — hereda permisos del módulo oym
TPL = "calculadora_polizas"


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
    plantas = await service.db.get_plantas_dropdown(conn)
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
    return JSONResponse([
        {"id": p["id"], "nombre": p["nombre"], "zona": p["zona"],
         "potencia_kw": float(p["potencia_kw"]) if p["potencia_kw"] else None,
         "num_paneles": p["num_paneles"]}
        for p in plantas
    ])


# ============================================================
# CALCULAR (HTMX)
# ============================================================

@router.post("/api/calcular", include_in_schema=False)
async def calcular(
    request: Request,
    planta_id: str = Form(...),
    tipo_poliza: str = Form(...),
    utilidad: float = Form(0.30),
    context=Depends(get_current_user_context),
    _=require_module_access(SLUG),
    conn=Depends(get_db_connection),
    service: CalculadoraService = Depends(get_service),
):
    mod_role = context.get("module_roles", {}).get("oym", "viewer")
    try:
        req = CalcularRequest(planta_id=planta_id, tipo_poliza=tipo_poliza, utilidad=utilidad)
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

@router.post("/cotizaciones/guardar", include_in_schema=False)
async def guardar_cotizacion(
    request: Request,
    planta_id: str = Form(...),
    tipo_poliza: str = Form(...),
    utilidad: float = Form(0.30),
    context=Depends(get_current_user_context),
    _=require_module_access(SLUG),
    conn=Depends(get_db_connection),
    service: CalculadoraService = Depends(get_service),
):
    user_id = context.get("user_db_id")
    try:
        req = CalcularRequest(planta_id=planta_id, tipo_poliza=tipo_poliza, utilidad=utilidad)
        resultado = await service.calcular(conn, req)
        await service.guardar_cotizacion(conn, resultado, user_id)
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
# HISTORIAL DE COTIZACIONES
# ============================================================

@router.get("/cotizaciones/ui", include_in_schema=False)
async def cotizaciones_ui(
    request: Request,
    page: int = Query(1, ge=1),
    context=Depends(get_current_user_context),
    _=require_module_access(SLUG),
    conn=Depends(get_db_connection),
    service: CalculadoraService = Depends(get_service),
):
    mod_role = context.get("module_roles", {}).get("oym", "viewer")
    per_page = 50
    offset = (page - 1) * per_page
    cotizaciones = await service.db.get_cotizaciones(conn, limit=per_page, offset=offset)
    total = await service.db.count_cotizaciones(conn)

    ctx = {
        **_base_ctx(context, mod_role),
        "cotizaciones": cotizaciones,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, -(-total // per_page)),
    }

    if request.headers.get("hx-request") and not request.headers.get("hx-history-restore-request"):
        return templates.TemplateResponse(request, f"{TPL}/partials/cotizaciones_tabla.html", ctx)
    return templates.TemplateResponse(request, f"{TPL}/cotizaciones.html", ctx)


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
