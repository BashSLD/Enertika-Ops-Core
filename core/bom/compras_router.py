"""
Router de compras BOM: cotizaciones (Fase C) y autorizaciones de compra (Fase D).
Incluido desde core/bom/router.py via router.include_router(compras_router).
"""

from fastapi import APIRouter, Depends, Request, HTTPException, Form, File, UploadFile
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, Response
from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import UUID
from typing import Optional
import asyncpg
import html
import httpx
import jinja2
import json
import logging

from core.database import get_db_connection
from core.security import get_current_user_context
from core.permissions import (
    require_module_access, require_any_module_access, require_authenticated_session,
    user_has_module_access,
)
from core.config import settings
from core.jinja_filters import register_timezone_filters
from modules.shared.utils import content_disposition_header, is_htmx
from .compras_service import ESTATUS_COTIZABLE, cantidad_pendiente_item, item_disponible_cotizacion
from .router import _toast_response
from .schemas import EstatusBOM
from .service import BomService, get_bom_service

logger = logging.getLogger("BOM.ComprasRouter")

templates = Jinja2Templates(directory="templates")
templates.env.globals["DEBUG_MODE"] = settings.DEBUG_MODE
register_timezone_filters(templates.env)

compras_router = APIRouter()


def _js_str(value: str) -> str:
    """Codifica un string para uso seguro como literal JS dentro de un atributo HTML con comillas dobles."""
    return html.escape(json.dumps(value), quote=True)


def _parse_decimal_form(valor: Optional[str]) -> Optional[Decimal]:
    """Parsea `nuevo_total` de un form-field opcional a Decimal.

    Optional[str] en vez de Optional[Decimal] en el parametro del endpoint --
    un input numerico vacio llega como "" via multipart, y Pydantic no lo
    trata como None para un Optional[Decimal] (422 antes de poder manejarlo
    limpio). Levanta ValueError si el valor no es un decimal valido; cada
    caller decide como envolver ese error (toast vs HTTPException) segun si
    su endpoint se invoca via hx-* o via fetch() manual.

    Rechaza explicitamente NaN/Infinity: Decimal("nan")/Decimal("inf") no
    levantan InvalidOperation al parsear (a diferencia de lo que hacia
    Pydantic para el Optional[Decimal] previo, que los rechazaba con 422 via
    su validador finite_number), y un total no finito hace explotar
    _alerta_variacion_costo mas adelante (comparacion/quantize sobre NaN o
    Infinity) con un decimal.InvalidOperation sin capturar."""
    if not valor:
        return None
    try:
        parsed = Decimal(valor)
    except InvalidOperation as exc:
        raise ValueError("Nuevo total inválido.") from exc
    if not parsed.is_finite():
        raise ValueError("Nuevo total inválido.")
    return parsed


async def _exigir_acceso_paquete_o_403(
    service: BomService, conn, context: dict, bom: dict,
    tiene_acceso_modulo: bool, recurso: str,
) -> None:
    """Levanta 403 si el usuario no tiene acceso de modulo NI es coordinador
    de obra del paquete. `tiene_acceso_modulo` viene ya calculado por el
    caller (gate barato temprano, ver compras_paquete_ui/preview_pdf_cotizacion)
    -- se pasa a tiene_acceso_paquete_compras para no recalcularlo. Mismo
    mensaje/status que la rama "no existe" del caller: evita que un usuario
    sin acceso de modulo distinga "no existe" de "existe pero no tengo
    acceso" comparando la respuesta."""
    if tiene_acceso_modulo:
        return
    if await service.tiene_acceso_paquete_compras(
        conn, context, bom, tiene_acceso_modulo=tiene_acceso_modulo,
    ):
        return
    raise HTTPException(status_code=403, detail=f"No tienes acceso a {recurso}.")


async def _exigir_acceso_autorizacion_o_403(
    service: BomService, conn, context: dict, autorizacion_id: UUID, recurso: str,
) -> None:
    """Variante de _exigir_acceso_paquete_o_403 para endpoints que reciben
    autorizacion_id en vez de id_bom/id_paquete (aprobar-obra, rechazar): resuelve
    el BOM de la autorizacion solo cuando hace falta (el usuario no tiene ya
    acceso de modulo) para poder evaluar el OR de coordinador de obra. Si la
    autorizacion no existe, no hace nada -- el metodo de servicio que sigue
    (aprobar_obra/rechazar_autorizacion) ya reporta 'Autorizacion no encontrada'
    con su propio mensaje/status, y no hay BOM que resolver para el OR."""
    if BomService.tiene_acceso_modulo_compras(context):
        return
    aut = await service.db.get_autorizacion_by_id(conn, autorizacion_id)
    if not aut:
        return
    bom = await service.get_bom_by_id(conn, aut["bom_id"])
    await _exigir_acceso_paquete_o_403(service, conn, context, bom, False, recurso)


def _item_cotizacion_json(item: dict, *, cantidad_pendiente=None) -> dict:
    """Proyeccion minima y JSON-safe del item para el selector del modal de cotizacion.

    El dict completo de tb_bom_items trae columnas Decimal/UUID/datetime que
    `tojson` no puede serializar; el JS del modal (cotizacionesBom()) solo lee
    estos 6 campos.

    `cantidad_pendiente`: por default se deriva de `item` con
    `cantidad_pendiente_item()` (items_disponibles, donde `item` SI es una fila
    de tb_bom_items). Al armar items_json para el modal de EDITAR (donde `item`
    es una fila de tb_bom_cotizacion_items -- `cantidad` ahi es lo que ESTA
    cotizacion ya capturo, no el total del item BOM, y no trae
    cantidad_cubierta) hay que pasarlo ya calculado desde el item BOM real; ver
    _render_cotizaciones_tab.
    """
    cantidad = item.get("cantidad")
    precio_unitario = item.get("precio_unitario")
    if cantidad_pendiente is None:
        cantidad_pendiente = cantidad_pendiente_item(item)
    return {
        "id_item": str(item["id_item"]),
        "descripcion": item.get("descripcion"),
        "categoria_nombre": item.get("categoria_nombre"),
        "unidad_medida": item.get("unidad_medida"),
        "cantidad": float(cantidad) if cantidad is not None else None,
        "cantidad_pendiente": float(cantidad_pendiente),
        "precio_unitario": float(precio_unitario) if precio_unitario is not None else None,
    }


def _con_trigger_cotizacion_guardada(resp, cotizacion: dict):
    """Agrega HX-Trigger (mismo patron que core/workflow/router.py) con el id/lock_version
    recien guardados. guardar() en templates/base.html (fetch manual, no htmx-managed)
    lo lee a mano del header de respuesta para encadenar la subida del PDF pendiente
    de captura asistida, sin tener que parsear el partial swapeado."""
    resp.headers["HX-Trigger"] = json.dumps({
        "cotizacion-guardada": {
            "id": str(cotizacion["id"]),
            "lock_version": cotizacion["lock_version"],
        }
    })
    return resp


# ========================================
# COTIZACIONES (Fase C)
# ========================================

def _parse_cotizacion_payload(body: dict) -> dict:
    """Parsea los campos comunes de crear/editar cotización desde el body JSON."""
    proveedor_id_str = body.get("proveedor_id")
    subtotal_externo = body.get("subtotal")
    items_data = []
    for it in body.get("items", []):
        pu = it.get("precio_unitario")
        items_data.append({
            "bom_item_id": UUID(it["bom_item_id"]),
            "precio_unitario": float(pu) if pu else 0,
            "cantidad": float(it.get("cantidad", 1)),
        })
    return {
        "proveedor_id": UUID(proveedor_id_str) if proveedor_id_str else None,
        "nombre_proveedor": (body.get("nombre_proveedor") or "").strip() or None,
        "moneda": body.get("moneda", "MXN"),
        "iva_pct": float(body.get("iva_pct", 16)),
        "notas": (body.get("notas") or "").strip() or None,
        "items_data": items_data,
        "subtotal_externo": float(subtotal_externo) if subtotal_externo is not None else None,
        "folio_proveedor": (body.get("folio_proveedor") or "").strip() or None,
    }


def _ids_en_rfq(rfq_items) -> set:
    """IDs (str) de bom_item vinculados a un RFQ."""
    return {str(i["bom_item_id"]) for i in rfq_items}


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
    cot_ids = [c["id"] for c in cotizaciones]
    items = await service.get_items(conn, bom_id)
    bom_items_map = {str(i["id_item"]): i for i in items}
    cot_items_raw = await service.db.get_items_by_cotizacion_ids(conn, cot_ids) if cot_ids else []
    cot_items_json: dict = {}
    for it in cot_items_raw:
        key = str(it["cotizacion_id"])
        bom_item = bom_items_map.get(str(it["bom_item_id"]))
        # Remanente real del item BOM (cantidad - cantidad_cubierta), no el de
        # `it` (fila de tb_bom_cotizacion_items: sin cantidad_cubierta, y su
        # "cantidad" es lo que esta cotizacion ya capturo) -- ver docstring de
        # _item_cotizacion_json. Si el item BOM ya no esta activo (soft-delete,
        # bom_items_map solo trae activos), no cae a None -- eso reactivaria el
        # bug original (_item_cotizacion_json recalcularia sobre `it`, sin
        # cantidad_cubierta). Pendiente 0: un item inactivo no deberia poder
        # cotizarse mas, el modal lo clampea en vez de mostrar el remanente
        # completo original.
        cot_items_json.setdefault(key, []).append(_item_cotizacion_json(
            it,
            cantidad_pendiente=(
                cantidad_pendiente_item(bom_item) if bom_item else Decimal("0")
            ),
        ))
    for cot in cotizaciones:
        cot["items_json"] = cot_items_json.get(str(cot["id"]), [])
    items_disponibles = [
        _item_cotizacion_json(i) for i in items if item_disponible_cotizacion(i)
    ]
    rfqs = await service.get_rfqs(conn, bom_id)
    role = context.get("role")
    rol_org = context.get("rol_organizacional")
    module_roles = context.get("module_roles", {})
    es_compras_editor = role == "ADMIN" or module_roles.get("compras") in ("editor", "admin")
    user_id = context.get("user_db_id")
    es_aprobador_direccion = await service.es_aprobador_direccion(conn, user_id)
    # Solo aplica cuando existe una cotizacion lista para solicitar aprobacion
    # (mismo gate que el formulario en cotizaciones.html) — evita la consulta
    # en el caso comun (BOM sin cotizaciones o sin ninguna en ese punto exacto).
    puede_solicitar_aprobacion = es_compras_editor and any(
        c.get("estatus") == "SELECCIONADA"
        and c.get("autorizacion_estatus") == "AUTORIZADO_OBRA"
        and c.get("aprobacion_estatus") not in ("PENDIENTE_DIRECCION", "APROBADA")
        for c in cotizaciones
    )
    reemplazables = (
        await service.db.get_cotizacion_aprobaciones_reemplazables(conn, bom_id)
        if puede_solicitar_aprobacion else []
    )
    return templates.TemplateResponse(
        request, "bom/partials/cotizaciones.html",
        {
            **_cotizacion_ctx(request, cotizaciones, bom, es_compras_editor),
            "items_disponibles": items_disponibles,
            "total_rfqs": len(rfqs),
            "es_aprobador_direccion": es_aprobador_direccion,
            "es_admin_o_director": role == "ADMIN" or rol_org == "director",
            "reemplazables": reemplazables,
            **extra,
        }
    )


async def _render_modal_cotizacion_rfq(
    request: Request,
    conn,
    service: BomService,
    bom_id: UUID,
    preset_rfq: dict,
):
    """Modal standalone de 'Pasar a Cotizacion' para una tarjeta de RFQ.

    A diferencia de _render_cotizaciones_tab, no reemplaza la vista de RFQs:
    se swapea aparte en #bom-modal-container para que la comparativa de RFQs
    debajo no se pierda al abrir el modal (ver comparativa.html).
    """
    bom = await service.get_bom_by_id(conn, bom_id)
    if not bom:
        return _toast_response(request, "BOM no encontrado", "error", status_code=404)
    items = await service.get_items(conn, bom_id)
    rfq_items = await service.get_items_rfq(conn, preset_rfq["id"])
    ids_en_rfq = _ids_en_rfq(rfq_items)
    items_disponibles = [
        _item_cotizacion_json(i) for i in items
        if item_disponible_cotizacion(i) and str(i["id_item"]) in ids_en_rfq
    ]
    return templates.TemplateResponse(
        request, "bom/partials/modal_cotizacion_rfq.html",
        {
            "bom": bom,
            "items_disponibles": items_disponibles,
            "preset_rfq": preset_rfq,
        },
    )


# ========================================
# POPUP DE PENDIENTES AL ENTRAR A LA APP (Autorizaciones de Obra)
# ========================================

@compras_router.get("/popup-pendientes-obra", include_in_schema=False)
async def popup_pendientes_obra(
    request: Request,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_authenticated_session(),
):
    """Banner lazy-load montado en base.html, fuera de #main-content: si el
    usuario no tiene autorizaciones de Obra pendientes -- o la consulta falla --
    no se renderiza nada. Unico punto con try/except del flujo: nunca debe
    tumbar el aterrizaje a la app (PLAN_popup_pendientes_autorizacion_obra.md §1)."""
    user_id = context.get("user_db_id")
    if not user_id:
        return HTMLResponse("")
    try:
        autorizaciones = await service.listar_pendientes_popup_coordinador(
            conn, user_id, context.get("rol_organizacional"),
        )
    except asyncpg.PostgresError:
        logger.exception("Error consultando popup de pendientes de Obra")
        return HTMLResponse("")
    if not autorizaciones:
        return HTMLResponse("")
    return templates.TemplateResponse(
        request, "bom/partials/popup_pendientes_obra.html",
        {"autorizaciones": autorizaciones},
    )


# ========================================
# PAGINA "COMPRAS DEL PAQUETE" (Resumen de compra + Cotizaciones + Autorizaciones)
# ========================================

@compras_router.get("/paquetes/{id_paquete}/compras", include_in_schema=False)
async def compras_paquete_ui(
    request: Request,
    id_paquete: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_authenticated_session(),
):
    """Pagina dedicada de Compras para un paquete: resuelve server-side el BOM
    cotizable vigente (cabeza de trabajo, u oficial si hay retrabajo en curso) y
    embebe Resumen de compra/Cotizaciones/Autorizaciones sin depender de un modal."""
    # Gate barato (sin query) primero -- ver mismo patron en preview_pdf_cotizacion:
    # sin acceso de modulo, "el paquete no existe" y "existe pero no tengo
    # acceso" deben responder igual, o el 404/403 distinto filtra que IDs de
    # paquete son validos a quien no tiene ningun acceso de modulo.
    tiene_acceso_modulo = BomService.tiene_acceso_modulo_compras(context)
    try:
        paquete = await service.get_paquete(conn, id_paquete)
        bom = await service.resolver_bom_cotizable(conn, id_paquete)
    except ValueError as exc:
        if tiene_acceso_modulo:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        raise HTTPException(status_code=403, detail="No tienes acceso a este paquete.") from exc
    await _exigir_acceso_paquete_o_403(service, conn, context, bom, tiene_acceso_modulo, "este paquete")
    proyecto = await service.get_proyecto_info(conn, paquete["id_proyecto"])
    if not proyecto:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    ctx = {
        # Guarda obligatoria (doc plan seccion 1.ter): toda pagina completa que
        # extienda base.html debe traer estos 4 campos, o el sidebar desaparece
        # en F5/URL directa (bug ya visto en /bom/direccion/cotizaciones).
        "user_name": context.get("user_name"),
        "role": context.get("role"),
        "module_roles": context.get("module_roles", {}),
        "user_id": context.get("user_db_id"),
        "paquete": paquete,
        "proyecto": proyecto,
        "bom": bom,
        "solo_lectura": not bom.get("es_cabeza_trabajo") and not bom.get("es_cabeza_oficial"),
    }
    template = (
        "bom/partials/compras_paquete.html" if is_htmx(request) else "bom/compras_paquete.html"
    )
    return templates.TemplateResponse(request, template, ctx)


@compras_router.get("/{id_bom:uuid}/cotizaciones", include_in_schema=False)
async def get_cotizaciones_tab(
    request: Request,
    id_bom: UUID,
    rfq_id: Optional[UUID] = None,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_authenticated_session(),
):
    """Tab de cotizaciones — cargado lazy con HTMX intersect.

    rfq_id (opcional): al llegar desde el boton "Pasar a Cotizacion" de una
    tarjeta RFQ, responde solo el modal standalone (ver _render_modal_cotizacion_rfq)
    en vez de reemplazar el tab completo, para no perder la vista de RFQs debajo.

    Gate: require_any_module_access reemplazado por chequeo imperativo (OR
    coordinador de obra) -- un coordinador sin ningun modulo asignado recibia
    403 al abrir este tab (PLAN 2026-08-31, seccion 5).
    """
    tiene_acceso_modulo = BomService.tiene_acceso_modulo_compras(context)
    if not tiene_acceso_modulo:
        await _exigir_acceso_paquete_o_403(
            service, conn, context, await service.get_bom_by_id(conn, id_bom),
            tiene_acceso_modulo, "este BOM",
        )
    if rfq_id:
        preset_rfq = await service.db.get_rfq_by_id(conn, rfq_id)
        if not preset_rfq:
            return _toast_response(request, "RFQ no encontrado", "error", status_code=404)
        return await _render_modal_cotizacion_rfq(request, conn, service, id_bom, preset_rfq)
    role = context.get("role")
    module_roles = context.get("module_roles", {})
    es_aprobador = (
        role == "ADMIN"
        or module_roles.get("ingenieria") in ("editor", "admin")
        or module_roles.get("construccion") in ("editor", "admin")
    )
    return await _render_cotizaciones_tab(
        request, conn, service, context, id_bom, es_aprobador=es_aprobador,
    )


@compras_router.post("/{id_bom:uuid}/cotizaciones", include_in_schema=False)
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

    body = await request.json()
    parsed = _parse_cotizacion_payload(body)
    rfq_id_str = body.get("rfq_id")
    rfq_id = UUID(rfq_id_str) if rfq_id_str else None
    bom_lock_version_raw = body.get("bom_lock_version")

    try:
        cotizacion = await service.crear_cotizacion(
            conn, id_bom, parsed["proveedor_id"], parsed["nombre_proveedor"], parsed["moneda"],
            parsed["items_data"], parsed["iva_pct"], parsed["notas"], user_id,
            subtotal_externo=parsed["subtotal_externo"],
            bom_lock_version_esperado=(
                int(bom_lock_version_raw) if bom_lock_version_raw is not None else None
            ),
            rfq_id=rfq_id,
            folio_proveedor=parsed["folio_proveedor"],
        )
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    if rfq_id:
        resp = await _render_comparativa(request, conn, service, context, id_bom)
    else:
        resp = await _render_cotizaciones_tab(request, conn, service, context, id_bom)
    return _con_trigger_cotizacion_guardada(resp, cotizacion)


@compras_router.post("/cotizaciones/{cotizacion_id}/editar", include_in_schema=False)
async def editar_cotizacion(
    request: Request,
    cotizacion_id: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("compras", "editor"),
):
    """Edita una cotización existente (BORRADOR/RECIBIDA). Recibe JSON en el body."""
    user_id = context.get("user_db_id")

    body = await request.json()
    parsed = _parse_cotizacion_payload(body)
    lock_version_raw = body.get("lock_version")

    try:
        actualizado = await service.editar_cotizacion(
            conn, cotizacion_id, parsed["proveedor_id"], parsed["nombre_proveedor"], parsed["moneda"],
            parsed["items_data"], parsed["iva_pct"], parsed["notas"], user_id,
            subtotal_externo=parsed["subtotal_externo"],
            lock_version_esperado=(
                int(lock_version_raw) if lock_version_raw is not None else None
            ),
            folio_proveedor=parsed["folio_proveedor"],
        )
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except asyncpg.PostgresError:
        logger.exception("Error de BD al editar cotización %s", cotizacion_id)
        raise HTTPException(status_code=500, detail="Error interno al editar la cotización")

    resp = await _render_cotizaciones_tab(request, conn, service, context, actualizado["bom_id"])
    return _con_trigger_cotizacion_guardada(resp, actualizado)


@compras_router.post("/{id_bom}/rfq-rapido", include_in_schema=False)
async def crear_rfq_rapido(
    request: Request,
    id_bom: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("compras", "editor"),
):
    """Crea un RFQ (tb_bom_rfq, doc 35) con los items seleccionados desde la tabla de items.

    Recibe item_ids como lista de form values. No bloquea items ni cambia su estatus --
    solo selecciona items para generar despues el PDF neutro. Filtra automaticamente items
    en AUTORIZADO/PAGADO/FACTURADO. El RFQ resultante se ve en la pestaña Comparativa.
    """
    user_id = context.get("user_db_id")

    form = await request.form()
    raw_ids = form.getlist("item_ids")
    nombre = (form.get("nombre") or "").strip() or None
    if not raw_ids:
        return _toast_response(
            request, "Selecciona al menos un item para el RFQ", "error",
            status_code=400,
        )

    try:
        item_ids = [UUID(i) for i in raw_ids]
    except ValueError:
        return _toast_response(request, "IDs inválidos", "error", status_code=400)

    try:
        rfq = await service.crear_rfq(conn, id_bom, item_ids, user_id, nombre=nombre)
    except ValueError as e:
        return _toast_response(request, str(e), "error", status_code=400)
    except asyncpg.PostgresError:
        logger.exception("Error de BD al crear RFQ")
        return _toast_response(request, "Error interno al crear el RFQ", "error", status_code=500)

    return _toast_response(
        request,
        f"RFQ creado con {rfq['total_items']} item{'s' if rfq['total_items'] != 1 else ''}. "
        "Consúltalo en Compras del paquete, sección Cotizaciones, para generar el PDF.",
        "success",
        title="RFQ creado",
    )


@compras_router.post("/cotizaciones/{cotizacion_id}/solicitar-aclaracion", include_in_schema=False)
async def solicitar_aclaracion(
    request: Request,
    cotizacion_id: UUID,
    motivo: str = Form(...),
    lock_version: int = Form(...),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(["ingenieria", "construccion"], min_role="editor"),
):
    """Devuelve una cotización a BORRADOR con motivo de aclaración."""
    user_id = context.get("user_db_id")
    try:
        await service.solicitar_aclaracion_cotizacion(
            conn, cotizacion_id, user_id, motivo, lock_version
        )
    except ValueError as e:
        return _toast_response(request, str(e), "error", status_code=400)

    cotizacion = await service.get_cotizacion_by_id(conn, cotizacion_id)
    if not cotizacion:
        return _toast_response(request, "Cotización no encontrada", "error", status_code=404)
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
    return await _render_comparativa(request, conn, service, context, id_bom)


@compras_router.get("/rfq/{rfq_id}/pdf", include_in_schema=False)
async def descargar_pdf_rfq(
    rfq_id: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(["compras", "finanzas"], allow_org_roles={"director"}),
):
    """Genera y descarga el PDF neutro del RFQ (doc 35) para enviarlo a proveedores."""
    user_id = context.get("user_db_id")
    try:
        pdf_bytes, filename = await service.generar_pdf_rfq(conn, rfq_id, user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (jinja2.TemplateError, OSError, RuntimeError):
        logger.exception("Error generando PDF de RFQ %s", rfq_id)
        raise HTTPException(status_code=500, detail="Error generando el PDF del RFQ")

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@compras_router.get("/rfq/{rfq_id}/historial", include_in_schema=False)
async def historial_rfq(
    request: Request,
    rfq_id: UUID,
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("compras"),
):
    """Bitácora de un RFQ (quién agregó/quitó items o regeneró el PDF) — vista bajo demanda."""
    historial = await service.listar_historial_rfq(conn, rfq_id)
    return templates.TemplateResponse(
        request, "bom/partials/rfq_historial.html", {"historial": historial, "rfq_id": rfq_id}
    )


async def _render_comparativa(request, conn, service, context, id_bom: UUID):
    rfqs = await service.get_rfqs(conn, id_bom)
    items_bom = await service.get_items(conn, id_bom)
    items_bom_json = [
        {
            "id_item": str(i["id_item"]),
            "descripcion": i.get("descripcion") or "",
            "cantidad": float(i["cantidad"]) if i.get("cantidad") is not None else None,
            "unidad_medida": i.get("unidad_medida") or "",
        }
        for i in items_bom
    ]
    comparativas = []
    for rfq in rfqs:
        responses = await service.get_rfq_responses(conn, rfq['id'])
        rfq_items = await service.get_items_rfq(conn, rfq['id'])
        resp_items = {}
        for resp in responses:
            resp_items[str(resp['id'])] = await service.get_items_cotizacion(conn, resp['id'])
        ids_en_rfq = _ids_en_rfq(rfq_items)
        comparativas.append({
            'rfq': rfq, 'items': rfq_items, 'responses': responses, 'resp_items': resp_items,
            'items_disponibles_json': [it for it in items_bom_json if it["id_item"] not in ids_en_rfq],
            'tiene_pago_asignado': rfq.get('tiene_pago_asignado', False),
        })
    es_compras_editor = user_has_module_access("compras", context, "editor")
    catalogos = await service.get_catalogos(conn)
    return templates.TemplateResponse(
        request, "bom/partials/comparativa.html",
        {
            "comparativas": comparativas, "items_bom": items_bom, "id_bom": id_bom,
            "es_compras_editor": es_compras_editor, "catalogos": catalogos,
        }
    )


@compras_router.post("/rfq/{rfq_id}/items", include_in_schema=False)
async def agregar_item_rfq(
    request: Request,
    rfq_id: UUID,
    bom_item_id: UUID = Form(...),
    cantidad: float = Form(...),
    unidad_override: Optional[str] = Form(None),
    lock_version: int = Form(...),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("compras", "editor"),
):
    """Agrega un item a un RFQ existente. No bloquea el item ni cambia su estatus."""
    user_id = context.get("user_db_id")
    try:
        actualizado = await service.agregar_item_rfq(
            conn, rfq_id, bom_item_id, cantidad, unidad_override, user_id,
            lock_version_esperado=lock_version,
        )
    except ValueError as e:
        return _toast_response(request, str(e), "error", status_code=400)
    except asyncpg.PostgresError:
        logger.exception("Error de BD al agregar item al RFQ %s", rfq_id)
        return _toast_response(request, "Error interno al agregar el item", "error", status_code=500)

    return await _render_comparativa(request, conn, service, context, actualizado["bom_id"])


@compras_router.post("/rfq/{rfq_id}/items/{bom_item_id}/quitar", include_in_schema=False)
async def quitar_item_rfq(
    request: Request,
    rfq_id: UUID,
    bom_item_id: UUID,
    lock_version: int = Form(...),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("compras", "editor"),
):
    """Quita un item de un RFQ existente."""
    user_id = context.get("user_db_id")
    try:
        actualizado = await service.quitar_item_rfq(
            conn, rfq_id, bom_item_id, user_id, lock_version_esperado=lock_version,
        )
    except ValueError as e:
        return _toast_response(request, str(e), "error", status_code=400)
    except asyncpg.PostgresError:
        logger.exception("Error de BD al quitar item del RFQ %s", rfq_id)
        return _toast_response(request, "Error interno al quitar el item", "error", status_code=500)

    return await _render_comparativa(request, conn, service, context, actualizado["bom_id"])


@compras_router.post("/rfq/{rfq_id}/items/{bom_item_id}/unidad", include_in_schema=False)
async def actualizar_unidad_item_rfq(
    request: Request,
    rfq_id: UUID,
    bom_item_id: UUID,
    lock_version: int = Form(...),
    unidad_override: str = Form(""),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("compras", "editor"),
):
    """Actualiza la unidad mostrada al proveedor para un item ya agregado al RFQ."""
    user_id = context.get("user_db_id")
    try:
        actualizado = await service.actualizar_unidad_item_rfq(
            conn, rfq_id, bom_item_id, unidad_override, user_id, lock_version_esperado=lock_version,
        )
    except ValueError as e:
        return _toast_response(request, str(e), "error", status_code=400)
    except asyncpg.PostgresError:
        logger.exception("Error de BD al actualizar unidad del item del RFQ %s", rfq_id)
        return _toast_response(request, "Error interno al actualizar la unidad", "error", status_code=500)

    return await _render_comparativa(request, conn, service, context, actualizado["bom_id"])


@compras_router.post("/rfq/{rfq_id}/nombre", include_in_schema=False)
async def renombrar_rfq(
    request: Request,
    rfq_id: UUID,
    nombre: str = Form(...),
    lock_version: int = Form(...),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("compras", "editor"),
):
    """Renombra un RFQ existente (Compras)."""
    try:
        actualizado = await service.renombrar_rfq(
            conn, rfq_id, nombre, lock_version_esperado=lock_version,
        )
    except ValueError as e:
        return _toast_response(request, str(e), "error", status_code=400)
    except asyncpg.PostgresError:
        logger.exception("Error de BD al renombrar RFQ %s", rfq_id)
        return _toast_response(request, "Error interno al renombrar el RFQ", "error", status_code=500)

    return await _render_comparativa(request, conn, service, context, actualizado["bom_id"])


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
    lock_version = body.get("lock_version")

    try:
        await service.bulk_asignar_items(
            conn, cotizacion_id, item_ids,
            lock_version_esperado=int(lock_version),
        )
    except (TypeError, ValueError) as e:
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
    form = await request.form()
    try:
        cotizacion = await service.seleccionar_cotizacion(
            conn, cotizacion_id, user_id,
            int(form.get("lock_version", "")),
        )
    except (TypeError, ValueError) as e:
        return _toast_response(request, str(e), "error", status_code=400)
    except asyncpg.PostgresError:
        logger.exception("Error de BD al seleccionar cotización %s", cotizacion_id)
        return _toast_response(
            request, "Error al adjudicar la cotización.", "error", status_code=500
        )
    if not cotizacion:
        return _toast_response(request, "Cotización no encontrada", "error", status_code=404)
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
    form = await request.form()
    try:
        cotizacion = await service.rechazar_cotizacion(
            conn, cotizacion_id, user_id, int(form.get("lock_version", ""))
        )
    except (TypeError, ValueError) as e:
        return _toast_response(request, str(e), "error", status_code=400)
    if not cotizacion:
        return _toast_response(request, "Cotización no encontrada", "error", status_code=404)
    return await _render_cotizaciones_tab(request, conn, service, context, cotizacion['bom_id'])


@compras_router.post("/cotizaciones/extraer-pdf-costos", include_in_schema=False)
async def extraer_pdf_costos_cotizacion(
    archivo: UploadFile = File(...),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("compras", "editor"),
):
    """Extrae precios candidatos de un PDF de cotizacion de proveedor (captura
    asistida, sin match automatico). No persiste nada ni sube a SharePoint --
    eso ocurre aparte al guardar, via /cotizaciones/{id}/pdf."""
    try:
        return await service.extraer_costos_pdf_cotizacion(archivo)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@compras_router.post("/cotizaciones/{cotizacion_id}/pdf", include_in_schema=False)
async def subir_pdf_cotizacion(
    request: Request,
    cotizacion_id: UUID,
    archivo: UploadFile = File(...),
    lock_version: int = Form(...),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("compras", "editor"),
):
    """Sube el PDF real de la cotización a SharePoint. Actualiza estatus a RECIBIDA."""
    user_id = context.get("user_db_id")
    try:
        await service.subir_pdf_cotizacion(
            conn, cotizacion_id, archivo, user_id, lock_version
        )
    except (TypeError, ValueError) as e:
        return _toast_response(request, str(e), "error", status_code=400)
    except asyncpg.PostgresError:
        return _toast_response(request, "Error al actualizar PDF", "error", status_code=500)

    cotizacion = await service.get_cotizacion_by_id(conn, cotizacion_id)
    if not cotizacion:
        return _toast_response(request, "Cotización no encontrada", "error", status_code=404)
    return await _render_cotizaciones_tab(
        request, conn, service, context, cotizacion['bom_id'],
        bulk_toast={
            "message": "PDF actualizado correctamente",
            "type": "success",
            "title": "Listo",
        },
    )


@compras_router.get("/cotizaciones/{cotizacion_id}/preview", include_in_schema=False)
async def preview_pdf_cotizacion(
    cotizacion_id: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_authenticated_session(),
):
    """Streamea el PDF mas reciente de la cotización para verlo inline en el navegador."""
    # Gate barato (sin query) primero: usuarios con acceso de modulo/Direccion/
    # ADMIN nunca filtran nada. Solo quien no lo tiene depende del fetch para
    # saber si califica como coordinador de obra -- para ese grupo, "no existe"
    # y "existe pero sin acceso" deben verse identicos (mismo 403) para no
    # filtrar que IDs de cotizacion son validos.
    tiene_acceso_modulo = BomService.tiene_acceso_modulo_compras(context)
    cotizacion = await service.get_cotizacion_by_id(conn, cotizacion_id)
    if not cotizacion:
        if tiene_acceso_modulo:
            raise HTTPException(status_code=404, detail="Cotización no encontrada")
        raise HTTPException(status_code=403, detail="No tienes acceso a esta cotización.")
    bom = await service.get_bom_by_id(conn, cotizacion["bom_id"])
    await _exigir_acceso_paquete_o_403(
        service, conn, context, bom, tiene_acceso_modulo, "esta cotización",
    )
    try:
        nombre_archivo, _media_type, contenido = await service.get_pdf_cotizacion_bytes(
            conn, cotizacion_id
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Error descargando el PDF desde SharePoint")

    # media_type fijo: este endpoint solo sirve PDFs. Nunca confiar en el tipo
    # de contenido guardado en BD (viene del content-type que mandó el cliente
    # al subir el archivo) para evitar servir HTML/SVG inline (XSS almacenado).
    return Response(
        content=contenido,
        media_type="application/pdf",
        headers={
            "Content-Disposition": content_disposition_header(
                "inline", nombre_archivo or "cotizacion.pdf"
            )
        },
    )


# ========================================
# APROBACIONES DE COTIZACION (post-BOM)
# ========================================

async def _subir_pdf_vigencia_opcional(
    conn, service: BomService, archivo: Optional[UploadFile], cotizacion_id: UUID, user_id: UUID,
) -> Optional[dict]:
    """Sube a SharePoint el PDF opcional del gate de vigencia (Puntos A y B) via
    BomService._subir_pdf_sharepoint_o_raise (misma orquestacion que
    subir_pdf_cotizacion -- el router no reimplementa la llamada a
    ComprasService), o None si no se adjuntó archivo."""
    if archivo is None or not archivo.filename:
        return None
    return await service._subir_pdf_sharepoint_o_raise(conn, archivo, user_id, cotizacion_id)


async def _sin_pdf_huerfano(conn, service: BomService, upload_result: Optional[dict], coro):
    """Delega en BomService._con_cleanup_pdf_huerfano (misma limpieza que usa
    subir_pdf_cotizacion). Compartido por los Puntos A y B."""
    return await service._con_cleanup_pdf_huerfano(conn, upload_result, coro)


@compras_router.post("/cotizaciones/{cotizacion_id}/solicitar-aprobacion", include_in_schema=False)
async def solicitar_aprobacion_cotizacion(
    request: Request,
    cotizacion_id: UUID,
    comentarios: Optional[str] = Form(None),
    cotizacion_lock_version: int = Form(...),
    autorizacion_lock_version: int = Form(...),
    reemplaza_aprobacion_id: Optional[str] = Form(None),
    vigente: bool = Form(True),
    motivo_no_vigente: Optional[str] = Form(None),
    nuevo_total: Optional[str] = Form(None),
    archivo_vigencia: Optional[UploadFile] = File(None),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("compras", "editor"),
):
    """Solicita aprobación de Dirección para una cotización seleccionada (post-BOM).

    Punto A del gate de vigencia: si `vigente=False`, no se crea aprobación --
    se rechaza la autorización Fase D directamente (RECHAZO_VIGENCIA).
    """
    user_id = context.get("user_db_id")
    try:
        reemplaza_id = UUID(reemplaza_aprobacion_id) if reemplaza_aprobacion_id else None
    except ValueError:
        return _toast_response(request, "reemplaza_aprobacion_id inválido", "error", status_code=400)
    try:
        nuevo_total_dec = _parse_decimal_form(nuevo_total)
    except ValueError:
        return _toast_response(request, "Nuevo total inválido.", "error", status_code=400)
    try:
        # Si no vigente, el archivo (si vino) se descarta -- evita el upload a
        # SharePoint de un PDF que nunca se va a referenciar.
        upload_result = await _subir_pdf_vigencia_opcional(
            conn, service, archivo_vigencia if vigente else None, cotizacion_id, user_id,
        )
        nuevo_pdf_url = upload_result['url_sharepoint'] if upload_result else None
        aprobacion = await _sin_pdf_huerfano(
            conn, service, upload_result,
            service.solicitar_aprobacion_cotizacion(
                conn, cotizacion_id, user_id, comentarios,
                cotizacion_lock_version, autorizacion_lock_version,
                reemplaza_aprobacion_id=reemplaza_id,
                vigente=vigente, motivo_no_vigente=motivo_no_vigente,
                nuevo_total=nuevo_total_dec, nuevo_pdf_url=nuevo_pdf_url,
            ),
        )
    except ValueError as e:
        return _toast_response(request, str(e), "error", status_code=400)
    except asyncpg.PostgresError:
        logger.exception("Error de BD al solicitar aprobación de cotización")
        return _toast_response(request, "Error al solicitar la aprobación.", "error", status_code=500)

    return await _render_cotizaciones_tab(
        request, conn, service, context, aprobacion['bom_id'],
        bulk_toast=service.bulk_toast_variacion_costo(aprobacion),
    )


@compras_router.post("/cotizaciones/{cotizacion_id}/aprobar-direccion", include_in_schema=False)
async def aprobar_cotizacion_direccion(
    request: Request,
    cotizacion_id: UUID,
    comentarios: Optional[str] = Form(None),
    aprobacion_lock_version: int = Form(...),
    autorizacion_lock_version: int = Form(...),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(["ingenieria", "compras", "finanzas"], allow_org_roles={"director"}),
):
    """Dirección aprueba la cotización; auto-avanza la autorización Fase D si aplica."""
    user_id = context.get("user_db_id")
    user_role = context.get("role")
    rol_org = context.get("rol_organizacional")
    try:
        aprobacion = await service.aprobar_cotizacion_direccion(
            conn, cotizacion_id, user_id, user_role, rol_org, comentarios,
            aprobacion_lock_version, autorizacion_lock_version,
        )
    except ValueError as e:
        return _toast_response(request, str(e), "error", status_code=400)
    except asyncpg.PostgresError:
        logger.exception("Error de BD al aprobar cotización por Dirección")
        return _toast_response(request, "Error al aprobar la cotización.", "error", status_code=500)

    return await _render_cotizaciones_tab(request, conn, service, context, aprobacion['bom_id'])


@compras_router.post("/cotizaciones/{cotizacion_id}/rechazar-direccion", include_in_schema=False)
async def rechazar_cotizacion_direccion(
    request: Request,
    cotizacion_id: UUID,
    motivo: str = Form(...),
    aprobacion_lock_version: int = Form(...),
    autorizacion_lock_version: int = Form(...),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(["ingenieria", "compras", "finanzas"], allow_org_roles={"director"}),
):
    """Dirección rechaza la cotización; cancela en cascada la autorización Fase D."""
    user_id = context.get("user_db_id")
    user_role = context.get("role")
    rol_org = context.get("rol_organizacional")
    try:
        aprobacion = await service.rechazar_cotizacion_direccion(
            conn, cotizacion_id, user_id, motivo, user_role, rol_org,
            aprobacion_lock_version, autorizacion_lock_version,
        )
    except ValueError as e:
        return _toast_response(request, str(e), "error", status_code=400)
    except asyncpg.PostgresError:
        logger.exception("Error de BD al rechazar cotización por Dirección")
        return _toast_response(request, "Error al rechazar la cotización.", "error", status_code=500)

    return await _render_cotizaciones_tab(request, conn, service, context, aprobacion['bom_id'])


@compras_router.post("/cotizaciones/{cotizacion_id}/standby-direccion", include_in_schema=False)
async def standby_cotizacion_direccion(
    request: Request,
    cotizacion_id: UUID,
    motivo: str = Form(...),
    fecha_recordatorio: date = Form(...),
    aprobacion_lock_version: int = Form(...),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(["ingenieria", "compras", "finanzas"], allow_org_roles={"director"}),
):
    """Dirección pone en espera ("standby") una cotización pendiente de su aprobación.

    Invocado via fetch() manual (modal de cotizacionesBom()) -- errores como
    HTTPException con detail, no _toast_response (el caller ya lee err.detail).
    """
    user_id = context.get("user_db_id")
    try:
        aprobacion = await service.standby_cotizacion_direccion(
            conn, cotizacion_id, user_id, motivo, fecha_recordatorio,
            aprobacion_lock_version,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except asyncpg.PostgresError:
        logger.exception("Error de BD al poner en standby la cotización")
        raise HTTPException(status_code=500, detail="Error al poner en standby la cotización.")

    return await _render_cotizaciones_tab(request, conn, service, context, aprobacion['bom_id'])


@compras_router.post("/cotizaciones/{cotizacion_id}/reprogramar-standby", include_in_schema=False)
async def reprogramar_standby_cotizacion(
    request: Request,
    cotizacion_id: UUID,
    motivo: str = Form(...),
    fecha_recordatorio: date = Form(...),
    aprobacion_lock_version: int = Form(...),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(["ingenieria", "compras", "finanzas"], allow_org_roles={"director"}),
):
    """Reprograma un standby ya activo (nuevo motivo/fecha). Invocado via fetch()
    manual -- errores como HTTPException, no _toast_response."""
    user_id = context.get("user_db_id")
    try:
        aprobacion = await service.reprogramar_standby_direccion(
            conn, cotizacion_id, user_id, motivo, fecha_recordatorio,
            aprobacion_lock_version,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except asyncpg.PostgresError:
        logger.exception("Error de BD al reprogramar el standby de la cotización")
        raise HTTPException(status_code=500, detail="Error al reprogramar el standby.")

    return await _render_cotizaciones_tab(request, conn, service, context, aprobacion['bom_id'])


@compras_router.post("/cotizaciones/{cotizacion_id}/confirmar-vigencia", include_in_schema=False)
async def confirmar_vigencia_cotizacion(
    request: Request,
    cotizacion_id: UUID,
    vigente: bool = Form(...),
    motivo: Optional[str] = Form(None),
    nuevo_total: Optional[str] = Form(None),
    archivo_vigencia: Optional[UploadFile] = File(None),
    aprobacion_lock_version: int = Form(...),
    autorizacion_lock_version: int = Form(...),
    cotizacion_lock_version: Optional[int] = Form(None),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("compras", "editor"),
):
    """Compras confirma vigencia tras la reactivación del standby (Punto B).
    Invocado via fetch() manual -- errores como HTTPException, no _toast_response."""
    user_id = context.get("user_db_id")
    try:
        nuevo_total_dec = _parse_decimal_form(nuevo_total)
    except ValueError:
        raise HTTPException(status_code=400, detail="Nuevo total inválido.")
    try:
        # Si no vigente, el archivo (si vino) se descarta -- evita el upload a
        # SharePoint de un PDF que nunca se va a referenciar.
        upload_result = await _subir_pdf_vigencia_opcional(
            conn, service, archivo_vigencia if vigente else None, cotizacion_id, user_id,
        )
        nuevo_pdf_url = upload_result['url_sharepoint'] if upload_result else None
        aprobacion = await _sin_pdf_huerfano(
            conn, service, upload_result,
            service.confirmar_vigencia_reactivacion(
                conn, cotizacion_id, user_id, vigente, motivo,
                nuevo_total_dec, nuevo_pdf_url,
                aprobacion_lock_version, autorizacion_lock_version, cotizacion_lock_version,
            ),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except asyncpg.PostgresError:
        logger.exception("Error de BD al confirmar vigencia de cotización")
        raise HTTPException(status_code=500, detail="Error al confirmar vigencia.")

    return await _render_cotizaciones_tab(
        request, conn, service, context, aprobacion['bom_id'],
        bulk_toast=service.bulk_toast_variacion_costo(aprobacion),
    )


# ========================================
# DASHBOARD DIRECCION (Fase 3, doc 33)
# ========================================

async def _dashboard_direccion_ctx(
    conn, service: BomService, context: dict,
    estatus: Optional[str], id_proyecto: Optional[UUID], proveedor: Optional[str],
) -> dict:
    aprobaciones = await service.get_cotizacion_aprobaciones_direccion(
        conn, estatus=estatus or None, id_proyecto=id_proyecto, nombre_proveedor=proveedor,
    )
    user_id = context.get("user_db_id")
    es_aprobador_direccion = await service.es_aprobador_direccion(conn, user_id)
    return {
        "aprobaciones": aprobaciones,
        "estatus_filtro": estatus or "",
        "id_proyecto_filtro": str(id_proyecto) if id_proyecto else "",
        "proveedor_filtro": proveedor or "",
        "es_aprobador_direccion": es_aprobador_direccion,
    }


@compras_router.api_route("/direccion/cotizaciones", methods=["GET", "HEAD"], include_in_schema=False)
async def dashboard_direccion_cotizaciones(
    request: Request,
    estatus: str = "PENDIENTE_DIRECCION",
    id_proyecto: Optional[UUID] = None,
    proveedor: Optional[str] = None,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(
        ["ingenieria", "construccion", "compras", "finanzas"], allow_org_roles={"director"}
    ),
):
    """Dashboard de Dirección: cotizaciones pendientes/aprobadas/rechazadas de todos los proyectos."""
    ctx = await _dashboard_direccion_ctx(conn, service, context, estatus, id_proyecto, proveedor)
    ctx.update({
        "user_name": context.get("user_name"),
        "role": context.get("role"),
        "module_roles": context.get("module_roles", {}),
    })
    is_htmx = request.headers.get("hx-request")
    is_history_restore = request.headers.get("hx-history-restore-request")
    if is_htmx and not is_history_restore:
        return templates.TemplateResponse(
            request, "bom/partials/direccion_cotizaciones.html", ctx
        )
    return templates.TemplateResponse(request, "bom/direccion_cotizaciones.html", ctx)


def _parse_id_proyecto_filtro(id_proyecto: Optional[str]) -> Optional[UUID]:
    if not id_proyecto:
        return None
    try:
        return UUID(id_proyecto)
    except ValueError:
        return None


@compras_router.post("/direccion/cotizaciones/{cotizacion_id}/aprobar", include_in_schema=False)
async def dashboard_aprobar_cotizacion(
    request: Request,
    cotizacion_id: UUID,
    comentarios: Optional[str] = Form(None),
    aprobacion_lock_version: int = Form(...),
    autorizacion_lock_version: int = Form(...),
    estatus: Optional[str] = Form(None),
    id_proyecto: Optional[str] = Form(None),
    proveedor: Optional[str] = Form(None),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(["ingenieria", "compras", "finanzas"], allow_org_roles={"director"}),
):
    user_id = context.get("user_db_id")
    user_role = context.get("role")
    rol_org = context.get("rol_organizacional")
    try:
        await service.aprobar_cotizacion_direccion(
            conn, cotizacion_id, user_id, user_role, rol_org, comentarios,
            aprobacion_lock_version, autorizacion_lock_version,
        )
    except ValueError as e:
        return _toast_response(request, str(e), "error", status_code=400)
    except asyncpg.PostgresError:
        logger.exception("Error de BD al aprobar cotización desde el dashboard de Dirección")
        return _toast_response(request, "Error al aprobar la cotización.", "error", status_code=500)
    ctx = await _dashboard_direccion_ctx(
        conn, service, context, estatus, _parse_id_proyecto_filtro(id_proyecto), proveedor
    )
    return templates.TemplateResponse(request, "bom/partials/direccion_cotizaciones.html", ctx)


@compras_router.post("/direccion/cotizaciones/{cotizacion_id}/rechazar", include_in_schema=False)
async def dashboard_rechazar_cotizacion(
    request: Request,
    cotizacion_id: UUID,
    motivo: str = Form(...),
    aprobacion_lock_version: int = Form(...),
    autorizacion_lock_version: int = Form(...),
    estatus: Optional[str] = Form(None),
    id_proyecto: Optional[str] = Form(None),
    proveedor: Optional[str] = Form(None),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(["ingenieria", "compras", "finanzas"], allow_org_roles={"director"}),
):
    user_id = context.get("user_db_id")
    user_role = context.get("role")
    rol_org = context.get("rol_organizacional")
    try:
        await service.rechazar_cotizacion_direccion(
            conn, cotizacion_id, user_id, motivo, user_role, rol_org,
            aprobacion_lock_version, autorizacion_lock_version,
        )
    except ValueError as e:
        return _toast_response(request, str(e), "error", status_code=400)
    except asyncpg.PostgresError:
        logger.exception("Error de BD al rechazar cotización desde el dashboard de Dirección")
        return _toast_response(request, "Error al rechazar la cotización.", "error", status_code=500)
    ctx = await _dashboard_direccion_ctx(
        conn, service, context, estatus, _parse_id_proyecto_filtro(id_proyecto), proveedor
    )
    return templates.TemplateResponse(request, "bom/partials/direccion_cotizaciones.html", ctx)


@compras_router.post("/direccion/cotizaciones/{cotizacion_id}/standby", include_in_schema=False)
async def dashboard_standby_cotizacion(
    request: Request,
    cotizacion_id: UUID,
    motivo: str = Form(...),
    fecha_recordatorio: date = Form(...),
    aprobacion_lock_version: int = Form(...),
    estatus: Optional[str] = Form(None),
    id_proyecto: Optional[str] = Form(None),
    proveedor: Optional[str] = Form(None),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(["ingenieria", "compras", "finanzas"], allow_org_roles={"director"}),
):
    user_id = context.get("user_db_id")
    try:
        await service.standby_cotizacion_direccion(
            conn, cotizacion_id, user_id, motivo, fecha_recordatorio,
            aprobacion_lock_version,
        )
    except ValueError as e:
        return _toast_response(request, str(e), "error", status_code=400)
    except asyncpg.PostgresError:
        logger.exception("Error de BD al poner en standby desde el dashboard de Dirección")
        return _toast_response(request, "Error al poner en standby la cotización.", "error", status_code=500)
    ctx = await _dashboard_direccion_ctx(
        conn, service, context, estatus, _parse_id_proyecto_filtro(id_proyecto), proveedor
    )
    return templates.TemplateResponse(request, "bom/partials/direccion_cotizaciones.html", ctx)


@compras_router.post("/direccion/cotizaciones/{cotizacion_id}/reprogramar-standby", include_in_schema=False)
async def dashboard_reprogramar_standby_cotizacion(
    request: Request,
    cotizacion_id: UUID,
    motivo: str = Form(...),
    fecha_recordatorio: date = Form(...),
    aprobacion_lock_version: int = Form(...),
    estatus: Optional[str] = Form(None),
    id_proyecto: Optional[str] = Form(None),
    proveedor: Optional[str] = Form(None),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(["ingenieria", "compras", "finanzas"], allow_org_roles={"director"}),
):
    user_id = context.get("user_db_id")
    try:
        await service.reprogramar_standby_direccion(
            conn, cotizacion_id, user_id, motivo, fecha_recordatorio,
            aprobacion_lock_version,
        )
    except ValueError as e:
        return _toast_response(request, str(e), "error", status_code=400)
    except asyncpg.PostgresError:
        logger.exception("Error de BD al reprogramar standby desde el dashboard de Dirección")
        return _toast_response(request, "Error al reprogramar el standby.", "error", status_code=500)
    ctx = await _dashboard_direccion_ctx(
        conn, service, context, estatus, _parse_id_proyecto_filtro(id_proyecto), proveedor
    )
    return templates.TemplateResponse(request, "bom/partials/direccion_cotizaciones.html", ctx)


@compras_router.post("/cotizaciones/{cotizacion_id}/reemplazar", include_in_schema=False)
async def reemplazar_cotizacion_proveedor(
    request: Request,
    cotizacion_id: UUID,
    motivo: str = Form(...),
    aprobacion_lock_version: int = Form(...),
    autorizacion_lock_version: int = Form(...),
    es_override: bool = Form(False),
    cancelar_definitivo: bool = Form(False),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("compras", "editor"),
):
    """Reemplaza una cotización aprobada por proveedor incumplido (plan ## 7.4)."""
    user_id = context.get("user_db_id")
    user_role = context.get("role")
    rol_org = context.get("rol_organizacional")
    if es_override and not (user_role == "ADMIN" or rol_org == "director"):
        raise HTTPException(
            status_code=403,
            detail="Solo ADMIN o Dirección pueden autorizar la excepción de reemplazo.",
        )
    try:
        aprobacion = await service.reemplazar_cotizacion_proveedor(
            conn, cotizacion_id, motivo, user_id, user_role, rol_org,
            aprobacion_lock_version, autorizacion_lock_version,
            es_override=es_override, cancelar_definitivo=cancelar_definitivo,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except asyncpg.PostgresError:
        logger.exception("Error de BD al reemplazar cotización por proveedor incumplido")
        raise HTTPException(status_code=500, detail="Error al reemplazar la cotización.")

    return await _render_cotizaciones_tab(request, conn, service, context, aprobacion['bom_id'])


# ========================================
# AUTORIZACIONES (Fase D)
# ========================================

async def _autorizacion_ctx(request, autorizaciones, bom, context, conn, service) -> dict:
    role = context.get("role")
    module_roles = context.get("module_roles", {})
    user_id = context.get("user_db_id")
    rol_org = context.get("rol_organizacional")
    finanzas_role = module_roles.get("finanzas")

    es_admin = role == "ADMIN"
    representados = (
        await service.get_titulares_que_representa(conn, user_id) if user_id else set()
    )
    coordinador_obra = bom.get("coordinador_obra") if bom else None
    es_coordinador_obra = (
        coordinador_obra in representados
        if coordinador_obra
        else rol_org == "jefe_construccion"
    )
    es_finanzas = finanzas_role in ("editor", "admin")
    es_compras_editor = es_admin or module_roles.get("compras") in ("editor", "admin")
    # `representados` ya se calculo arriba para es_coordinador_obra -- se reusa
    # aqui en vez de llamar service.es_aprobador_direccion() para no repetir esa
    # consulta (tb_bom_suplencias) dos veces en la misma request.
    aprobador_direccion = await service.db.get_aprobador_final_id(conn)
    es_aprobador_direccion = bool(aprobador_direccion and aprobador_direccion in representados)

    return {
        "autorizaciones": autorizaciones,
        "bom": bom,
        "user_id": user_id,
        "es_admin": es_admin,
        "es_coordinador_obra": es_coordinador_obra,
        "es_finanzas": es_finanzas,
        "es_compras_editor": es_compras_editor,
        "es_aprobador_direccion": es_aprobador_direccion,
    }


@compras_router.get("/{id_bom}/autorizaciones", include_in_schema=False)
async def get_autorizaciones_tab(
    request: Request,
    id_bom: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_authenticated_session(),
):
    # Gate: require_any_module_access reemplazado por chequeo imperativo (OR
    # coordinador de obra) -- ver PLAN 2026-08-31, seccion 5.
    tiene_acceso_modulo = BomService.tiene_acceso_modulo_compras(context)
    bom = await service.get_bom_by_id(conn, id_bom)  # autorizaciones tab
    if not bom:
        raise HTTPException(status_code=404, detail="BOM no encontrado")
    await _exigir_acceso_paquete_o_403(service, conn, context, bom, tiene_acceso_modulo, "este BOM")
    autorizaciones = await service.listar_autorizaciones(conn, id_bom)
    return templates.TemplateResponse(
        request, "bom/partials/autorizaciones.html",
        await _autorizacion_ctx(request, autorizaciones, bom, context, conn, service),
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
    if EstatusBOM(bom["estatus"]) not in ESTATUS_COTIZABLE:
        resumen = {"sin_datos": True}
    else:
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
    id_bom_item_anterior: Optional[str] = Form(None),
    concepto_lock_version: int = Form(...),
    id_grupo: Optional[int] = Form(None),
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
            return _toast_response(request, "Ítem inválido.", "error", status_code=400)
        item_seleccionado = next(
            (it for it in data["items"] if it["id_item"] == item_uuid), None
        )
        if not item_seleccionado:
            return _toast_response(request, "El ítem no pertenece a esta autorización.", "error", status_code=400)
        grupos_validos = {
            grupo["id"] for grupo in item_seleccionado.get("grupos_conciliacion", [])
        }
        if id_grupo is not None and id_grupo not in grupos_validos:
            return _toast_response(request, "El grupo no pertenece al ítem seleccionado.", "error", status_code=400)
        if len(grupos_validos) > 1 and id_grupo is None:
            return _toast_response(request, "Selecciona el grupo al que se asignará el importe del concepto.", "error", status_code=400)
    elif id_grupo is not None:
        return _toast_response(request, "No puedes asignar un grupo sin un ítem.", "error", status_code=400)
    if not any(c["historial_id"] == historial_id for c in data["conceptos"]):
        return _toast_response(request, "Concepto no encontrado en esta autorización.", "error", status_code=404)

    anterior_uuid = None
    anterior_valor = (id_bom_item_anterior or "").strip()
    if anterior_valor:
        try:
            anterior_uuid = UUID(anterior_valor)
        except ValueError:
            return _toast_response(request, "Match anterior invalido.", "error", status_code=400)

    try:
        await service.confirmar_match_concepto(
            conn, historial_id, item_uuid, anterior_uuid,
            concepto_lock_version, id_grupo,
        )
    except ValueError as exc:
        return _toast_response(request, str(exc), "error", status_code=409)
    except asyncpg.PostgresError:
        return _toast_response(request, "Error al guardar la conciliación.", "error", status_code=500)

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
    lock_version: int = Form(...),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_authenticated_session(),
):
    # Gate: require_any_module_access reemplazado por chequeo imperativo (OR
    # coordinador de obra) -- ver PLAN 2026-08-31, seccion 5. service.aprobar_obra
    # ya revalida identidad de coordinador con datos frescos (_exigir_coordinador_obra).
    await _exigir_acceso_autorizacion_o_403(service, conn, context, autorizacion_id, "esta autorización")
    user_id = context.get("user_db_id")
    user_role = context.get("role")
    try:
        aut = await service.aprobar_obra(
            conn, autorizacion_id, user_id, nota, user_role, lock_version,
            rol_organizacional=context.get("rol_organizacional"),
        )
    except ValueError as e:
        return _toast_response(request, str(e), "error", status_code=400)
    except asyncpg.PostgresError:
        return _toast_response(request, "Error al aprobar la autorización.", "error", status_code=500)

    bom = await service.get_bom_by_id(conn, aut['bom_id'])
    autorizaciones = await service.listar_autorizaciones(conn, aut['bom_id'])
    return templates.TemplateResponse(
        request, "bom/partials/autorizaciones.html",
        await _autorizacion_ctx(request, autorizaciones, bom, context, conn, service),
    )


@compras_router.post("/autorizaciones/{autorizacion_id}/aprobar-finanzas", include_in_schema=False)
async def aprobar_autorizacion_finanzas(
    request: Request,
    autorizacion_id: UUID,
    nota: Optional[str] = Form(None),
    lock_version: int = Form(...),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(["ingenieria", "compras", "finanzas"]),
):
    user_id = context.get("user_db_id")
    user_role = context.get("role")
    finanzas_role = context.get("module_roles", {}).get("finanzas")
    if user_role != "ADMIN" and finanzas_role not in ("editor", "admin"):
        return _toast_response(request, "Requiere rol editor o admin en Finanzas", "error", status_code=403)
    try:
        aut = await service.aprobar_finanzas(
            conn, autorizacion_id, user_id, nota, user_role, finanzas_role,
            lock_version,
        )
    except ValueError as e:
        return _toast_response(request, str(e), "error", status_code=400)
    except asyncpg.PostgresError:
        return _toast_response(request, "Error al aprobar la autorización.", "error", status_code=500)

    bom = await service.get_bom_by_id(conn, aut['bom_id'])
    autorizaciones = await service.listar_autorizaciones(conn, aut['bom_id'])
    return templates.TemplateResponse(
        request, "bom/partials/autorizaciones.html",
        await _autorizacion_ctx(request, autorizaciones, bom, context, conn, service),
    )


@compras_router.post("/autorizaciones/{autorizacion_id}/rechazar", include_in_schema=False)
async def rechazar_autorizacion(
    request: Request,
    autorizacion_id: UUID,
    motivo: str = Form(...),
    lock_version: int = Form(...),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_authenticated_session(),
):
    # Gate: require_any_module_access reemplazado por chequeo imperativo (OR
    # coordinador de obra) -- ver PLAN 2026-08-31, seccion 5. Ruta compartida por
    # los 3 pasos (Obra/Direccion/Finanzas): el OR solo abre la puerta de entrada,
    # service.rechazar_autorizacion revalida el paso exacto (PENDIENTE -> exige
    # coordinador; AUTORIZADO_OBRA -> exige titular Direccion; AUTORIZADO_DIRECCION
    # -> exige rol Finanzas) con datos frescos, asi que un coordinador de obra sin
    # modulo no puede rechazar los pasos de Direccion/Finanzas via este OR.
    await _exigir_acceso_autorizacion_o_403(service, conn, context, autorizacion_id, "esta autorización")
    user_id = context.get("user_db_id")
    user_role = context.get("role")
    rol_org = context.get("rol_organizacional")
    finanzas_role = context.get("module_roles", {}).get("finanzas")
    try:
        aut = await service.rechazar_autorizacion(
            conn, autorizacion_id, user_id, motivo, user_role, rol_org,
            finanzas_role, lock_version,
        )
    except ValueError as e:
        return _toast_response(request, str(e), "error", status_code=400)
    except asyncpg.PostgresError:
        return _toast_response(request, "Error al rechazar la autorización.", "error", status_code=500)

    bom = await service.get_bom_by_id(conn, aut['bom_id'])
    autorizaciones = await service.listar_autorizaciones(conn, aut['bom_id'])
    return templates.TemplateResponse(
        request, "bom/partials/autorizaciones.html",
        await _autorizacion_ctx(request, autorizaciones, bom, context, conn, service),
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
        f'onclick="seleccionarProveedor(this, {_js_str(str(p["id_proveedor"]))}, '
        f'{_js_str(p["nombre_comercial"] or p["razon_social"] or "")})"'
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
