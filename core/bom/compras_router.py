"""
Router de compras BOM: cotizaciones (Fase C) y autorizaciones de compra (Fase D).
Incluido desde core/bom/router.py via router.include_router(compras_router).
"""

from fastapi import APIRouter, Depends, Request, HTTPException, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from uuid import UUID
from typing import Optional
import asyncpg
import html
import json
import logging

from core.database import get_db_connection
from core.security import get_current_user_context
from core.permissions import require_module_access, require_any_module_access
from core.config import settings
from core.jinja_filters import register_timezone_filters
from .compras_service import ESTATUS_COTIZABLE
from .schemas import EstatusBOM
from .service import (
    BomService,
    get_bom_service,
    ESTATUS_ITEM_CERRADO_COMPRA,
    ESTATUS_COMPRA_BLOQUEA_ADENDA,
)

logger = logging.getLogger("BOM.ComprasRouter")

templates = Jinja2Templates(directory="templates")
templates.env.globals["DEBUG_MODE"] = settings.DEBUG_MODE
register_timezone_filters(templates.env)

compras_router = APIRouter()


def _js_str(value: str) -> str:
    """Codifica un string para uso seguro como literal JS dentro de un atributo HTML con comillas dobles."""
    return html.escape(json.dumps(value), quote=True)


def _item_disponible_cotizacion(item: dict) -> bool:
    estatus_compra = item.get("estatus_compra", "SIN_COTIZAR")
    estatus_ejecucion = item.get("estatus_ejecucion")
    return (
        estatus_compra not in ESTATUS_COMPRA_BLOQUEA_ADENDA
        and estatus_ejecucion not in ESTATUS_ITEM_CERRADO_COMPRA
    )


# ========================================
# COTIZACIONES (Fase C)
# ========================================

def _cotizacion_ctx(request, cotizaciones, bom, es_compras_editor: bool) -> dict:
    return {
        "cotizaciones": cotizaciones,
        "bom": bom,
        "es_compras_editor": es_compras_editor,
        "bom_cotizable": EstatusBOM(bom['estatus']) in ESTATUS_COTIZABLE,
    }


async def _render_cotizaciones_tab(
    request: Request,
    conn,
    service: BomService,
    context: dict,
    bom_id: UUID,
    **extra,
):
    bom = await service.get_bom_by_id(conn, bom_id)
    if not bom:
        raise HTTPException(status_code=404, detail="BOM no encontrado")
    cotizaciones = await service.listar_cotizaciones(conn, bom_id)
    items = await service.get_items(conn, bom_id)
    items_disponibles = [i for i in items if _item_disponible_cotizacion(i)]
    role = context.get("role")
    module_roles = context.get("module_roles", {})
    es_compras_editor = role == "ADMIN" or module_roles.get("compras") in ("editor", "admin")
    return templates.TemplateResponse(
        request, "bom/partials/cotizaciones.html",
        {
            **_cotizacion_ctx(request, cotizaciones, bom, es_compras_editor),
            "items_disponibles": items_disponibles,
            **extra,
        }
    )


@compras_router.get("/{id_bom}/cotizaciones", include_in_schema=False)
async def get_cotizaciones_tab(
    request: Request,
    id_bom: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(
        ["ingenieria", "construccion", "compras", "finanzas"], allow_org_roles={"director"}
    ),
):
    """Tab de cotizaciones — cargado lazy con HTMX intersect."""
    role = context.get("role")
    module_roles = context.get("module_roles", {})
    es_aprobador = (
        role == "ADMIN"
        or module_roles.get("ingenieria") in ("editor", "admin")
        or module_roles.get("construccion") in ("editor", "admin")
    )
    return await _render_cotizaciones_tab(request, conn, service, context, id_bom, es_aprobador=es_aprobador)


@compras_router.post("/{id_bom}/cotizaciones", include_in_schema=False)
async def crear_cotizacion(
    request: Request,
    id_bom: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("compras", "editor"),
):
    """Crea una nueva cotización (RFQ, simplificada o completa). Recibe JSON en el body."""
    user_id = context.get("user_db_id")
    if not user_id:
        raise HTTPException(status_code=401)

    body = await request.json()
    proveedor_id_str = body.get("proveedor_id")
    proveedor_id = UUID(proveedor_id_str) if proveedor_id_str else None
    nombre_proveedor = body.get("nombre_proveedor", "").strip() or None
    moneda = body.get("moneda", "MXN")
    iva_pct = float(body.get("iva_pct", 16))
    notas = body.get("notas", "").strip() or None
    items_raw = body.get("items", [])
    es_rfq = body.get("es_rfq", False)
    rfq_origen_id_str = body.get("rfq_origen_id")
    rfq_origen_id = UUID(rfq_origen_id_str) if rfq_origen_id_str else None
    subtotal_externo = body.get("subtotal")  # modo simplificado: el usuario ingresa subtotal

    items_data = []
    for it in items_raw:
        pu = it.get("precio_unitario")
        items_data.append({
            "bom_item_id": UUID(it["bom_item_id"]),
            "precio_unitario": float(pu) if pu else 0,
            "cantidad": float(it.get("cantidad", 1)),
        })

    try:
        await service.crear_cotizacion(
            conn, id_bom, proveedor_id, nombre_proveedor, moneda,
            items_data, iva_pct, notas, user_id,
            es_rfq=es_rfq,
            rfq_origen_id=rfq_origen_id,
            subtotal_externo=float(subtotal_externo) if subtotal_externo is not None else None
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return await _render_cotizaciones_tab(request, conn, service, context, id_bom)


@compras_router.post("/{id_bom}/rfq-rapido", include_in_schema=False)
async def crear_rfq_rapido(
    request: Request,
    id_bom: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("compras", "editor"),
):
    """Crea un RFQ con los items seleccionados desde la tabla de items.

    Recibe item_ids como lista de form values. No requiere proveedor ni precios.
    Usa tb_bom_items.descripcion (descripcion interna) como referencia para el proveedor.
    Filtra automaticamente items en AUTORIZADO/PAGADO/FACTURADO.
    """
    user_id = context.get("user_db_id")
    if not user_id:
        raise HTTPException(status_code=401)

    form = await request.form()
    raw_ids = form.getlist("item_ids")
    if not raw_ids:
        return templates.TemplateResponse(
            request, "shared/toast.html",
            {"message": "Selecciona al menos un item para cotizar", "type": "error"},
            status_code=400,
            headers={"HX-Reswap": "none"},
        )

    try:
        item_ids = [UUID(i) for i in raw_ids]
    except ValueError:
        raise HTTPException(status_code=400, detail="IDs inválidos")

    items_bd = await service.get_items_by_ids(conn, item_ids)
    items_data = [
        {
            "bom_item_id": i["id_item"],
            "precio_unitario": 0,
            "cantidad": float(i["cantidad"]),
        }
        for i in items_bd
        if _item_disponible_cotizacion(i)
    ]

    if not items_data:
        return templates.TemplateResponse(
            request, "shared/toast.html",
            {"message": "Todos los items seleccionados ya están autorizados o facturados", "type": "error"},
            status_code=400,
            headers={"HX-Reswap": "none"},
        )

    try:
        await service.crear_cotizacion(
            conn, id_bom,
            None, None, "MXN",
            items_data, 16, None, user_id,
            es_rfq=True,
        )
    except ValueError as e:
        return templates.TemplateResponse(
            request, "shared/toast.html",
            {"message": str(e), "type": "error"},
            status_code=400,
            headers={"HX-Reswap": "none"},
        )
    except asyncpg.PostgresError:
        logger.exception("Error de BD al crear RFQ rápido")
        return templates.TemplateResponse(
            request, "shared/toast.html",
            {"message": "Error interno al crear el RFQ", "type": "error"},
            status_code=500,
            headers={"HX-Reswap": "none"},
        )

    return await _render_cotizaciones_tab(
        request, conn, service, context, id_bom,
        rfq_creado=True, rfq_items_count=len(items_data),
    )


@compras_router.post("/cotizaciones/{cotizacion_id}/solicitar-aclaracion", include_in_schema=False)
async def solicitar_aclaracion(
    request: Request,
    cotizacion_id: UUID,
    motivo: str = Form(...),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(["ingenieria", "construccion"], min_role="editor"),
):
    """Devuelve una cotización a BORRADOR con motivo de aclaración."""
    user_id = context.get("user_db_id")
    if not user_id:
        raise HTTPException(status_code=401)
    try:
        await service.solicitar_aclaracion_cotizacion(conn, cotizacion_id, user_id, motivo)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    cotizacion = await service.get_cotizacion_by_id(conn, cotizacion_id)
    if not cotizacion:
        raise HTTPException(status_code=404, detail="Cotización no encontrada")
    return await _render_cotizaciones_tab(request, conn, service, context, cotizacion['bom_id'])


@compras_router.get("/{id_bom}/cotizaciones/comparativa", include_in_schema=False)
async def get_comparativa(
    request: Request,
    id_bom: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("compras"),
):
    """Vista comparativa: items del BOM × proveedores que respondieron al RFQ."""
    rfqs = await service.get_rfqs(conn, id_bom)
    comparativas = []
    for rfq in rfqs:
        responses = await service.get_rfq_responses(conn, rfq['id'])
        rfq_items = await service.get_items_cotizacion(conn, rfq['id'])
        resp_items = {}
        for resp in responses:
            resp_items[str(resp['id'])] = await service.get_items_cotizacion(conn, resp['id'])
        comparativas.append({
            'rfq': rfq,
            'items': rfq_items,
            'responses': responses,
            'resp_items': resp_items,
        })

    items_bom = await service.get_items(conn, id_bom)
    return templates.TemplateResponse(
        request, "bom/partials/comparativa.html",
        {"comparativas": comparativas, "items_bom": items_bom, "id_bom": id_bom}
    )


@compras_router.post("/cotizaciones/{cotizacion_id}/bulk-asignar", include_in_schema=False)
async def bulk_asignar_items(
    request: Request,
    cotizacion_id: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("compras", "editor"),
):
    """Asigna items a una cotización de proveedor en lote."""
    body = await request.json()
    item_ids = body.get("item_ids", [])

    try:
        await service.bulk_asignar_items(
            conn, cotizacion_id, item_ids
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"ok": True, "asignados": len(item_ids)}


@compras_router.post("/cotizaciones/{cotizacion_id}/seleccionar", include_in_schema=False)
async def seleccionar_cotizacion(
    request: Request,
    cotizacion_id: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("compras", "editor"),
):
    user_id = context.get("user_db_id")
    try:
        cotizacion = await service.seleccionar_cotizacion(conn, cotizacion_id, user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not cotizacion:
        raise HTTPException(status_code=404, detail="Cotización no encontrada")
    return await _render_cotizaciones_tab(request, conn, service, context, cotizacion['bom_id'])


@compras_router.post("/cotizaciones/{cotizacion_id}/rechazar", include_in_schema=False)
async def rechazar_cotizacion(
    request: Request,
    cotizacion_id: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("compras", "editor"),
):
    user_id = context.get("user_db_id")
    try:
        cotizacion = await service.rechazar_cotizacion(conn, cotizacion_id, user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not cotizacion:
        raise HTTPException(status_code=404, detail="Cotización no encontrada")
    return await _render_cotizaciones_tab(request, conn, service, context, cotizacion['bom_id'])


@compras_router.post("/cotizaciones/{cotizacion_id}/pdf", include_in_schema=False)
async def subir_pdf_cotizacion(
    request: Request,
    cotizacion_id: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("compras", "editor"),
):
    """Sube PDF de cotización (URL). Actualiza estatus a RECIBIDA."""
    form = await request.form()
    pdf_url = form.get("pdf_url", "").strip()
    if not pdf_url:
        raise HTTPException(status_code=400, detail="URL del PDF es requerida")
    try:
        await service.actualizar_pdf_cotizacion(conn, cotizacion_id, pdf_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except asyncpg.PostgresError:
        raise HTTPException(status_code=500, detail="Error al actualizar PDF")

    cotizacion = await service.get_cotizacion_by_id(conn, cotizacion_id)
    if not cotizacion:
        raise HTTPException(status_code=404, detail="Cotización no encontrada")
    return await _render_cotizaciones_tab(request, conn, service, context, cotizacion['bom_id'])


# ========================================
# APROBACIONES DE COTIZACION (post-BOM)
# ========================================

@compras_router.post("/cotizaciones/{cotizacion_id}/solicitar-aprobacion", include_in_schema=False)
async def solicitar_aprobacion_cotizacion(
    request: Request,
    cotizacion_id: UUID,
    comentarios: Optional[str] = Form(None),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("compras", "editor"),
):
    """Solicita aprobación de Dirección para una cotización seleccionada (post-BOM)."""
    user_id = context.get("user_db_id")
    if not user_id:
        raise HTTPException(status_code=401)
    try:
        aprobacion = await service.solicitar_aprobacion_cotizacion(conn, cotizacion_id, user_id, comentarios)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except asyncpg.PostgresError:
        logger.exception("Error de BD al solicitar aprobación de cotización")
        raise HTTPException(status_code=500, detail="Error al solicitar la aprobación.")

    return await _render_cotizaciones_tab(request, conn, service, context, aprobacion['bom_id'])


@compras_router.post("/cotizaciones/{cotizacion_id}/aprobar-direccion", include_in_schema=False)
async def aprobar_cotizacion_direccion(
    request: Request,
    cotizacion_id: UUID,
    comentarios: Optional[str] = Form(None),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(["ingenieria", "compras", "finanzas"], allow_org_roles={"director"}),
):
    """Dirección aprueba la cotización; auto-avanza la autorización Fase D si aplica."""
    user_id = context.get("user_db_id")
    if not user_id:
        raise HTTPException(status_code=401)
    user_role = context.get("role")
    rol_org = context.get("rol_organizacional")
    try:
        aprobacion = await service.aprobar_cotizacion_direccion(
            conn, cotizacion_id, user_id, user_role, rol_org, comentarios
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except asyncpg.PostgresError:
        logger.exception("Error de BD al aprobar cotización por Dirección")
        raise HTTPException(status_code=500, detail="Error al aprobar la cotización.")

    return await _render_cotizaciones_tab(request, conn, service, context, aprobacion['bom_id'])


@compras_router.post("/cotizaciones/{cotizacion_id}/rechazar-direccion", include_in_schema=False)
async def rechazar_cotizacion_direccion(
    request: Request,
    cotizacion_id: UUID,
    motivo: str = Form(...),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(["ingenieria", "compras", "finanzas"], allow_org_roles={"director"}),
):
    """Dirección rechaza la cotización; cancela en cascada la autorización Fase D."""
    user_id = context.get("user_db_id")
    if not user_id:
        raise HTTPException(status_code=401)
    user_role = context.get("role")
    rol_org = context.get("rol_organizacional")
    try:
        aprobacion = await service.rechazar_cotizacion_direccion(
            conn, cotizacion_id, user_id, motivo, user_role, rol_org
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except asyncpg.PostgresError:
        logger.exception("Error de BD al rechazar cotización por Dirección")
        raise HTTPException(status_code=500, detail="Error al rechazar la cotización.")

    return await _render_cotizaciones_tab(request, conn, service, context, aprobacion['bom_id'])


# ========================================
# AUTORIZACIONES (Fase D)
# ========================================

def _autorizacion_ctx(request, autorizaciones, bom, context) -> dict:
    role = context.get("role")
    module_roles = context.get("module_roles", {})
    user_id = context.get("user_db_id")
    rol_org = context.get("rol_organizacional")
    finanzas_role = module_roles.get("finanzas")

    es_admin = role == "ADMIN"
    es_director = rol_org == "director"
    es_coordinador_obra = bom.get("coordinador_obra") == user_id if bom else False
    es_finanzas = finanzas_role in ("editor", "admin")
    es_compras_editor = es_admin or module_roles.get("compras") in ("editor", "admin")

    return {
        "autorizaciones": autorizaciones,
        "bom": bom,
        "user_id": user_id,
        "es_admin": es_admin,
        "es_director": es_director,
        "es_coordinador_obra": es_coordinador_obra,
        "es_finanzas": es_finanzas,
        "es_compras_editor": es_compras_editor,
    }


@compras_router.get("/{id_bom}/autorizaciones", include_in_schema=False)
async def get_autorizaciones_tab(
    request: Request,
    id_bom: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(["ingenieria", "construccion", "compras", "finanzas"], allow_org_roles={"director"}),
):
    bom = await service.get_bom_by_id(conn, id_bom)  # autorizaciones tab
    if not bom:
        raise HTTPException(status_code=404, detail="BOM no encontrado")
    autorizaciones = await service.listar_autorizaciones(conn, id_bom)
    return templates.TemplateResponse(
        request, "bom/partials/autorizaciones.html",
        _autorizacion_ctx(request, autorizaciones, bom, context),
    )


@compras_router.get("/{id_bom}/resumen-compra", include_in_schema=False)
async def get_resumen_compra_tab(
    request: Request,
    id_bom: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(["ingenieria", "construccion", "compras", "finanzas"], allow_org_roles={"director"}),
):
    """Tab Resumen de compra — comparativo Presupuesto vs Facturado vs Pagado, lazy HTMX."""
    bom = await service.get_bom_by_id(conn, id_bom)
    if not bom:
        raise HTTPException(status_code=404, detail="BOM no encontrado")
    resumen = await service.get_resumen_compra(conn, id_bom)
    return templates.TemplateResponse(
        request, "bom/partials/resumen_compra.html",
        {"bom": bom, "resumen": resumen},
    )


def _conciliacion_ctx(request, autorizacion_id, data):
    return {
        "request": request,
        "autorizacion_id": autorizacion_id,
        "conceptos": data["conceptos"],
        "items": data["items"],
    }


@compras_router.get("/autorizaciones/{autorizacion_id}/conciliacion", include_in_schema=False)
async def get_conciliacion_factura(
    request: Request,
    autorizacion_id: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("compras", "editor"),
):
    """Vista de conciliación factura↔ítem BOM de una autorización (2 columnas)."""
    data = await service.get_conciliacion(conn, autorizacion_id)
    return templates.TemplateResponse(
        request, "bom/partials/conciliacion.html",
        _conciliacion_ctx(request, autorizacion_id, data),
    )


@compras_router.post(
    "/autorizaciones/{autorizacion_id}/conciliacion/{historial_id}/asignar",
    include_in_schema=False,
)
async def asignar_match_concepto(
    request: Request,
    autorizacion_id: UUID,
    historial_id: UUID,
    id_bom_item: Optional[str] = Form(None),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("compras", "editor"),
):
    """Confirma o desasigna el match de un concepto. id_bom_item vacío = desasignar."""
    data = await service.get_conciliacion(conn, autorizacion_id)

    item_uuid = None
    valor = (id_bom_item or "").strip()
    if valor:
        try:
            item_uuid = UUID(valor)
        except ValueError:
            raise HTTPException(status_code=400, detail="Ítem inválido.")
        if not any(it["id_item"] == item_uuid for it in data["items"]):
            raise HTTPException(status_code=400, detail="El ítem no pertenece a esta autorización.")
    if not any(c["historial_id"] == historial_id for c in data["conceptos"]):
        raise HTTPException(status_code=404, detail="Concepto no encontrado en esta autorización.")

    try:
        await service.confirmar_match_concepto(conn, historial_id, item_uuid)
    except asyncpg.PostgresError:
        raise HTTPException(status_code=500, detail="Error al guardar la conciliación.")

    data = await service.get_conciliacion(conn, autorizacion_id)
    return templates.TemplateResponse(
        request, "bom/partials/conciliacion.html",
        _conciliacion_ctx(request, autorizacion_id, data),
    )


@compras_router.post("/autorizaciones/{autorizacion_id}/aprobar-obra", include_in_schema=False)
async def aprobar_autorizacion_obra(
    request: Request,
    autorizacion_id: UUID,
    nota: Optional[str] = Form(None),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(["ingenieria", "compras", "finanzas"]),
):
    user_id = context.get("user_db_id")
    user_role = context.get("role")
    try:
        aut = await service.aprobar_obra(conn, autorizacion_id, user_id, nota, user_role)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except asyncpg.PostgresError:
        raise HTTPException(status_code=500, detail="Error al aprobar la autorización.")

    bom = await service.get_bom_by_id(conn, aut['bom_id'])
    autorizaciones = await service.listar_autorizaciones(conn, aut['bom_id'])
    return templates.TemplateResponse(
        request, "bom/partials/autorizaciones.html",
        _autorizacion_ctx(request, autorizaciones, bom, context),
    )


@compras_router.post("/autorizaciones/{autorizacion_id}/aprobar-direccion", include_in_schema=False)
async def aprobar_autorizacion_direccion(
    request: Request,
    autorizacion_id: UUID,
    nota: Optional[str] = Form(None),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(["ingenieria", "compras", "finanzas"], allow_org_roles={"director"}),
):
    user_id = context.get("user_db_id")
    user_role = context.get("role")
    rol_org = context.get("rol_organizacional")
    try:
        aut = await service.aprobar_direccion(conn, autorizacion_id, user_id, nota, user_role, rol_org)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except asyncpg.PostgresError:
        raise HTTPException(status_code=500, detail="Error al aprobar la autorización.")

    bom = await service.get_bom_by_id(conn, aut['bom_id'])
    autorizaciones = await service.listar_autorizaciones(conn, aut['bom_id'])
    return templates.TemplateResponse(
        request, "bom/partials/autorizaciones.html",
        _autorizacion_ctx(request, autorizaciones, bom, context),
    )


@compras_router.post("/autorizaciones/{autorizacion_id}/aprobar-finanzas", include_in_schema=False)
async def aprobar_autorizacion_finanzas(
    request: Request,
    autorizacion_id: UUID,
    nota: Optional[str] = Form(None),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(["ingenieria", "compras", "finanzas"]),
):
    user_id = context.get("user_db_id")
    user_role = context.get("role")
    finanzas_role = context.get("module_roles", {}).get("finanzas")
    if user_role != "ADMIN" and finanzas_role not in ("editor", "admin"):
        raise HTTPException(status_code=403, detail="Requiere rol editor o admin en Finanzas")
    try:
        aut = await service.aprobar_finanzas(conn, autorizacion_id, user_id, nota, user_role, finanzas_role)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except asyncpg.PostgresError:
        raise HTTPException(status_code=500, detail="Error al aprobar la autorización.")

    bom = await service.get_bom_by_id(conn, aut['bom_id'])
    autorizaciones = await service.listar_autorizaciones(conn, aut['bom_id'])
    return templates.TemplateResponse(
        request, "bom/partials/autorizaciones.html",
        _autorizacion_ctx(request, autorizaciones, bom, context),
    )


@compras_router.post("/autorizaciones/{autorizacion_id}/rechazar", include_in_schema=False)
async def rechazar_autorizacion(
    request: Request,
    autorizacion_id: UUID,
    motivo: str = Form(...),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(["ingenieria", "compras", "finanzas"], allow_org_roles={"director"}),
):
    user_id = context.get("user_db_id")
    user_role = context.get("role")
    rol_org = context.get("rol_organizacional")
    finanzas_role = context.get("module_roles", {}).get("finanzas")
    try:
        aut = await service.rechazar_autorizacion(conn, autorizacion_id, user_id, motivo, user_role, rol_org, finanzas_role)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except asyncpg.PostgresError:
        raise HTTPException(status_code=500, detail="Error al rechazar la autorización.")

    bom = await service.get_bom_by_id(conn, aut['bom_id'])
    autorizaciones = await service.listar_autorizaciones(conn, aut['bom_id'])
    return templates.TemplateResponse(
        request, "bom/partials/autorizaciones.html",
        _autorizacion_ctx(request, autorizaciones, bom, context),
    )


@compras_router.get("/proveedores/buscar", include_in_schema=False)
async def buscar_proveedores_bom(
    request: Request,
    q: str = "",
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("compras"),
):
    """Autocomplete de proveedores para el modal de cotización."""
    if len(q) < 2:
        return HTMLResponse("")
    proveedores = await service.get_proveedores_buscar(conn, q)
    items_html = "".join(
        f'<button type="button" '
        f'onclick="seleccionarProveedor({_js_str(str(p["id_proveedor"]))}, '
        f'{_js_str(p["nombre_comercial"] or p["razon_social"] or "")}); '
        f'document.getElementById(\'resultados-proveedores-bom\').innerHTML=\'\'"'
        f' class="w-full text-left px-3 py-2 text-sm hover:bg-blue-50 border-b border-gray-100 last:border-0">'
        f'<span class="font-medium">{html.escape(p["nombre_comercial"] or p["razon_social"] or "")}</span>'
        f'<span class="text-xs text-gray-400 ml-2">{html.escape(p["rfc"] or "")}</span>'
        f'</button>'
        for p in proveedores
    )
    if not items_html:
        items_html = '<p class="px-3 py-2 text-sm text-gray-400 italic">Sin resultados</p>'
    return HTMLResponse(
        f'<div class="bg-white border border-gray-200 rounded-lg shadow-lg overflow-hidden">{items_html}</div>'
    )
