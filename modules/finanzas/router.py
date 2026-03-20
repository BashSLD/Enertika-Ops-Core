"""
Router del Módulo Finanzas.

Endpoints:
- /finanzas/ui                              - Dashboard principal
- /finanzas/partials/pendientes             - Lista autorizaciones pendientes de pago
- /finanzas/partials/historial              - Historial de pagos registrados
- /finanzas/autorizaciones/{id}/modal-pago  - Modal para registrar pago
- /finanzas/autorizaciones/{id}/pago        - POST: registrar pago
"""

from fastapi import APIRouter, Depends, Request, Form, HTTPException, Query
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from typing import Optional
from uuid import UUID
from datetime import date
from decimal import Decimal
import logging
import asyncpg

from core.database import get_db_connection
from core.security import get_current_user_context
from core.permissions import require_module_access
from core.config import settings
from core.jinja_filters import register_timezone_filters

from .service import FinanzasService, get_finanzas_service

logger = logging.getLogger("FinanzasModule")
templates = Jinja2Templates(directory="templates")
templates.env.globals["DEBUG_MODE"] = settings.DEBUG_MODE
register_timezone_filters(templates.env)

router = APIRouter(
    prefix="/finanzas",
    tags=["Modulo Finanzas"],
)


def _base_ctx(request: Request, context: dict) -> dict:
    module_roles = context.get("module_roles", {})
    mod_role = module_roles.get("finanzas", "viewer")
    return {
        "request": request,
        "user_name": context.get("user_name"),
        "role": context.get("role"),
        "module_roles": module_roles,
        "current_module_role": mod_role,
        "puede_registrar_pago": mod_role in ("editor", "admin") or context.get("role") == "ADMIN",
    }


@router.api_route("/ui", methods=["GET", "HEAD"], include_in_schema=False)
async def get_finanzas_ui(
    request: Request,
    context=Depends(get_current_user_context),
    _=require_module_access("finanzas"),
    conn=Depends(get_db_connection),
    service: FinanzasService = Depends(get_finanzas_service),
):
    data = await service.get_dashboard_data(conn)
    ctx = {
        **_base_ctx(request, context),
        **data,
    }
    if request.headers.get("hx-request") and not request.headers.get("hx-history-restore-request"):
        return templates.TemplateResponse("finanzas/partials/content.html", ctx)
    return templates.TemplateResponse("finanzas/dashboard.html", ctx)


@router.get("/partials/pendientes", include_in_schema=False)
async def get_pendientes_partial(
    request: Request,
    context=Depends(get_current_user_context),
    _=require_module_access("finanzas"),
    conn=Depends(get_db_connection),
    service: FinanzasService = Depends(get_finanzas_service),
):
    pendientes = await service.get_pendientes(conn)
    return templates.TemplateResponse("finanzas/partials/lista_pendientes.html", {
        **_base_ctx(request, context),
        "pendientes": pendientes,
    })


@router.get("/partials/historial", include_in_schema=False)
async def get_historial_partial(
    request: Request,
    context=Depends(get_current_user_context),
    _=require_module_access("finanzas"),
    conn=Depends(get_db_connection),
    service: FinanzasService = Depends(get_finanzas_service),
):
    historial = await service.get_historial(conn)
    return templates.TemplateResponse("finanzas/partials/lista_historial.html", {
        **_base_ctx(request, context),
        "historial": historial,
    })


@router.get("/autorizaciones/{autorizacion_id}/modal-pago", include_in_schema=False)
async def modal_registrar_pago(
    request: Request,
    autorizacion_id: UUID,
    context=Depends(get_current_user_context),
    _=require_module_access("finanzas", "editor"),
    conn=Depends(get_db_connection),
    service: FinanzasService = Depends(get_finanzas_service),
):
    try:
        aut = await service.get_modal_registrar_pago(conn, autorizacion_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return templates.TemplateResponse("finanzas/partials/modal_registrar_pago.html", {
        "request": request,
        "autorizacion": aut,
    })


@router.post("/autorizaciones/{autorizacion_id}/pago", include_in_schema=False)
async def registrar_pago(
    request: Request,
    autorizacion_id: UUID,
    monto_pagado: Decimal = Form(...),
    moneda: str = Form("MXN"),
    tipo_cambio_usado: Optional[Decimal] = Form(None),
    fecha_pago: date = Form(...),
    referencia_bancaria: Optional[str] = Form(None),
    context=Depends(get_current_user_context),
    _=require_module_access("finanzas", "editor"),
    conn=Depends(get_db_connection),
    service: FinanzasService = Depends(get_finanzas_service),
):
    user_id = context.get("user_db_id")
    try:
        await service.registrar_pago(
            conn,
            autorizacion_id=autorizacion_id,
            monto_pagado=monto_pagado,
            moneda=moneda,
            tipo_cambio_usado=tipo_cambio_usado,
            fecha_pago=fecha_pago,
            referencia_bancaria=referencia_bancaria,
            comprobante_url=None,
            registrado_por=user_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except asyncpg.UniqueViolationError:
        raise HTTPException(status_code=400, detail="Esta autorización ya tiene un pago registrado.")
    except asyncpg.PostgresError:
        raise HTTPException(status_code=500, detail="Error al registrar el pago.")

    # Recargar lista de pendientes y pasar a historial
    data = await service.get_dashboard_data(conn)
    return templates.TemplateResponse("finanzas/partials/content.html", {
        **_base_ctx(request, context),
        **data,
    })
