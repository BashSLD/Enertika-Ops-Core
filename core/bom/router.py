"""
Router compartido de BOM (Lista de Materiales).
Endpoints HTMX para CRUD de items, workflow de aprobaciones y exportacion Excel.
"""

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import Response
from uuid import UUID
from datetime import datetime
import asyncpg
import logging

from core.database import get_db_connection
from core.security import get_current_user_context
from core.permissions import require_module_access, require_manager_access, get_user_module_role
from core.config import settings
from .service import BomService, get_bom_service

logger = logging.getLogger("BOM.Router")

templates = Jinja2Templates(directory="templates")
templates.env.globals["DEBUG_MODE"] = settings.DEBUG_MODE

from core.jinja_filters import register_timezone_filters
register_timezone_filters(templates.env)

router = APIRouter(
    prefix="/bom",
    tags=["BOM - Lista de Materiales"],
)


def _get_area_editor(context: dict) -> str:
    """Determina el area del editor basado en sus roles de modulo."""
    role = context.get("role")
    module_roles = context.get("module_roles", {})

    if role == "ADMIN":
        return "ingenieria"

    # Prioridad: ingenieria > construccion > compras
    if module_roles.get("ingenieria") in ("editor", "admin"):
        return "ingenieria"
    if module_roles.get("construccion") in ("editor", "admin"):
        return "construccion"
    if module_roles.get("compras") in ("editor", "admin"):
        return "compras"

    return "viewer"


def _build_bom_context(request, context, bom, **extra) -> dict:
    """Construye el contexto comun para templates de BOM."""
    area_editor = _get_area_editor(context)
    role = context.get("role")
    module_roles = context.get("module_roles", {})

    # Permisos de accion
    es_ing_editor = area_editor == "ingenieria"
    es_ing_manager = (
        role == "ADMIN"
        or module_roles.get("ingenieria") == "admin"
        or (role == "MANAGER" and module_roles.get("ingenieria") in ("editor", "admin"))
    )
    es_const_manager = (
        role == "ADMIN"
        or module_roles.get("construccion") == "admin"
        or (role == "MANAGER" and module_roles.get("construccion") in ("editor", "admin"))
    )
    es_compras_editor = (
        role == "ADMIN"
        or module_roles.get("compras") in ("editor", "admin")
    )

    ctx = {
        "request": request,
        "bom": bom,
        "area_editor": area_editor,
        "es_ing_editor": es_ing_editor,
        "es_ing_manager": es_ing_manager,
        "es_const_manager": es_const_manager,
        "es_compras_editor": es_compras_editor,
        "role": role,
        "user_id": context.get("user_id"),
        "user_name": context.get("user_name"),
    }
    ctx.update(extra)
    return ctx


# ========================================
# VISTA PRINCIPAL BOM
# ========================================

@router.get("/{id_proyecto}/ui", include_in_schema=False)
async def bom_ui(
    request: Request,
    id_proyecto: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("ingenieria"),
):
    """Vista principal del BOM de un proyecto."""
    bom = await service.get_bom_proyecto(conn, id_proyecto)
    proyecto = await service.db.get_proyecto_info(conn, id_proyecto)

    if not proyecto:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    catalogos = await service.get_catalogos(conn)
    items = []
    estadisticas = {}
    versiones = []

    if bom:
        items = await service.get_items(conn, bom['id_bom'])
        estadisticas = await service.get_estadisticas(conn, bom['id_bom'])
        versiones = await service.db.get_all_bom_versions(conn, id_proyecto)

    ctx = _build_bom_context(
        request, context, bom,
        proyecto=proyecto,
        items=items,
        estadisticas=estadisticas,
        catalogos=catalogos,
        versiones=versiones,
        id_proyecto=id_proyecto,
    )

    is_htmx = request.headers.get("hx-request")
    template = "bom/partials/content.html" if is_htmx else "bom/dashboard.html"
    return templates.TemplateResponse(template, ctx)


# ========================================
# CREAR BOM
# ========================================

@router.post("/{id_proyecto}/crear", include_in_schema=False)
async def crear_bom(
    request: Request,
    id_proyecto: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("ingenieria", "editor"),
):
    """Crea un nuevo BOM para el proyecto."""
    form = await request.form()
    user_id = context.get("user_db_id")
    responsable_ing = form.get("responsable_ing")
    jefe_construccion = form.get("jefe_construccion")
    coordinador_obra = form.get("coordinador_obra")
    notas = form.get("notas", "").strip() or None

    try:
        bom = await service.crear_bom(
            conn, id_proyecto, user_id,
            responsable_ing=UUID(responsable_ing) if responsable_ing else None,
            jefe_construccion=UUID(jefe_construccion) if jefe_construccion else None,
            coordinador_obra=UUID(coordinador_obra) if coordinador_obra else None,
            notas=notas
        )

        return templates.TemplateResponse("shared/toast.html", {
            "request": request,
            "message": f"BOM v{bom['version']} creado exitosamente",
            "type": "success",
            "redirect_url": f"/bom/{id_proyecto}/ui",
        })

    except ValueError as e:
        return templates.TemplateResponse("shared/toast.html", {
            "request": request,
            "message": str(e),
            "type": "error",
        })
    except asyncpg.PostgresError:
        logger.exception("Error de BD al crear BOM")
        return templates.TemplateResponse("shared/toast.html", {
            "request": request,
            "message": "Error interno al crear el BOM",
            "type": "error",
        })


# ========================================
# ITEMS CRUD
# ========================================

@router.get("/{id_proyecto}/items", include_in_schema=False)
async def get_items(
    request: Request,
    id_proyecto: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("ingenieria"),
):
    """Tabla de items del BOM (partial HTMX)."""
    bom = await service.get_bom_proyecto(conn, id_proyecto)
    items = []
    if bom:
        items = await service.get_items(conn, bom['id_bom'])

    ctx = _build_bom_context(request, context, bom, items=items)
    return templates.TemplateResponse("bom/partials/tabla_items.html", ctx)


@router.post("/{id_proyecto}/items", include_in_schema=False)
async def agregar_item(
    request: Request,
    id_proyecto: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
):
    """Agrega un item al BOM. Permite Ingenieria y Construccion."""
    form = await request.form()
    user_id = context.get("user_db_id")
    area_editor = _get_area_editor(context)

    if area_editor not in ("ingenieria", "construccion"):
        return templates.TemplateResponse("shared/toast.html", {
            "request": request,
            "message": "No tienes permisos para agregar items",
            "type": "error",
        })

    bom = await service.get_bom_proyecto(conn, id_proyecto)
    if not bom:
        return templates.TemplateResponse("shared/toast.html", {
            "request": request,
            "message": "No existe un BOM para este proyecto",
            "type": "error",
        })

    id_categoria = form.get("id_categoria")
    cantidad = form.get("cantidad", "0")
    precio_unitario_raw = form.get("precio_unitario", "").strip()
    origen_precio = form.get("origen_precio", "MANUAL").strip() or "MANUAL"
    id_material_ref_raw = form.get("id_material_ref", "").strip()

    try:
        from decimal import Decimal
        precio_unitario = Decimal(precio_unitario_raw) if precio_unitario_raw else None
        id_material_ref = UUID(id_material_ref_raw) if id_material_ref_raw else None

        await service.agregar_item(
            conn, bom['id_bom'], user_id,
            descripcion=form.get("descripcion", "").strip(),
            cantidad=Decimal(cantidad),
            id_categoria=int(id_categoria) if id_categoria else None,
            unidad_medida=form.get("unidad_medida", "").strip() or None,
            comentarios=form.get("comentarios", "").strip() or None,
            precio_unitario=precio_unitario,
            origen_precio=origen_precio if origen_precio in ('CATALOGO', 'MANUAL') else 'MANUAL',
            id_material_ref=id_material_ref,
            area_editor=area_editor,
        )

        # Retornar tabla actualizada
        items = await service.get_items(conn, bom['id_bom'])
        bom = await service.get_bom(conn, bom['id_bom'])
        estadisticas = await service.get_estadisticas(conn, bom['id_bom'])

        ctx = _build_bom_context(
            request, context, bom,
            items=items, estadisticas=estadisticas
        )
        return templates.TemplateResponse("bom/partials/tabla_items.html", ctx)

    except ValueError as e:
        return templates.TemplateResponse("shared/toast.html", {
            "request": request,
            "message": str(e),
            "type": "error",
        })
    except asyncpg.PostgresError:
        logger.exception("Error de BD al agregar item BOM")
        return templates.TemplateResponse("shared/toast.html", {
            "request": request,
            "message": "Error interno al agregar el item",
            "type": "error",
        })


@router.patch("/items/{id_item}", include_in_schema=False)
async def editar_item(
    request: Request,
    id_item: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("ingenieria"),
):
    """Edita un item del BOM."""
    form = await request.form()
    user_id = context.get("user_db_id")
    area_editor = _get_area_editor(context)

    # Construir campos desde el form
    campos = {}
    for key in form.keys():
        val = form.get(key)
        if key == "id_categoria":
            campos[key] = int(val) if val else None
        elif key == "cantidad":
            from decimal import Decimal
            campos[key] = Decimal(val) if val else None
        elif key == "id_proveedor":
            campos[key] = UUID(val) if val else None
        elif key == "entregado":
            campos[key] = val in ("true", "True", "1", "on")
        elif key in ("fecha_requerida", "fecha_llegada_real", "fecha_estimada_entrega"):
            from datetime import date as date_type
            campos[key] = date_type.fromisoformat(val) if val else None
        elif key == "precio_unitario":
            from decimal import Decimal as Dec
            campos[key] = Dec(val) if val and val.strip() else None
        elif key == "origen_precio":
            if val and val.strip() in ('CATALOGO', 'MANUAL'):
                campos[key] = val.strip()
        elif key in ("descripcion", "unidad_medida", "tipo_entrega", "comentarios"):
            campos[key] = val.strip() if val else None

    try:
        await service.editar_item(
            conn, id_item, user_id, area_editor, **campos
        )

        # Retornar fila actualizada
        item = await service.get_item(conn, id_item)
        bom = await service.get_bom(conn, item['id_bom'])

        ctx = _build_bom_context(request, context, bom, item=item)
        return templates.TemplateResponse("bom/partials/row_item.html", ctx)

    except ValueError as e:
        return templates.TemplateResponse("shared/toast.html", {
            "request": request,
            "message": str(e),
            "type": "error",
        })
    except asyncpg.PostgresError:
        logger.exception("Error de BD al editar item BOM")
        return templates.TemplateResponse("shared/toast.html", {
            "request": request,
            "message": "Error interno al editar el item",
            "type": "error",
        })


@router.delete("/items/{id_item}", include_in_schema=False)
async def eliminar_item(
    request: Request,
    id_item: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
):
    """Elimina (soft) un item del BOM. Permite Ingenieria y Construccion."""
    user_id = context.get("user_db_id")
    area_editor = _get_area_editor(context)

    if area_editor not in ("ingenieria", "construccion"):
        return templates.TemplateResponse("shared/toast.html", {
            "request": request,
            "message": "No tienes permisos para eliminar items",
            "type": "error",
        })

    try:
        item = await service.get_item(conn, id_item)
        await service.eliminar_item(conn, id_item, user_id, area_editor=area_editor)

        # Retornar tabla actualizada
        bom = await service.get_bom(conn, item['id_bom'])
        items = await service.get_items(conn, bom['id_bom'])
        estadisticas = await service.get_estadisticas(conn, bom['id_bom'])

        ctx = _build_bom_context(
            request, context, bom,
            items=items, estadisticas=estadisticas
        )
        return templates.TemplateResponse("bom/partials/tabla_items.html", ctx)

    except ValueError as e:
        return templates.TemplateResponse("shared/toast.html", {
            "request": request,
            "message": str(e),
            "type": "error",
        })
    except asyncpg.PostgresError:
        logger.exception("Error de BD al eliminar item BOM")
        return templates.TemplateResponse("shared/toast.html", {
            "request": request,
            "message": "Error interno al eliminar el item",
            "type": "error",
        })


@router.get("/items/{id_item}/modal", include_in_schema=False)
async def get_modal_editar_item(
    request: Request,
    id_item: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("ingenieria"),
):
    """Modal para editar un item."""
    item = await service.get_item(conn, id_item)
    bom = await service.get_bom(conn, item['id_bom'])
    catalogos = await service.get_catalogos(conn)

    ctx = _build_bom_context(
        request, context, bom,
        item=item, catalogos=catalogos
    )
    return templates.TemplateResponse("bom/partials/modal_item.html", ctx)


# ========================================
# BUSQUEDA DE MATERIALES
# ========================================

@router.get("/materiales/buscar", include_in_schema=False)
async def buscar_materiales(
    request: Request,
    q: str = "",
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("ingenieria", "editor"),
):
    """Busqueda fuzzy de materiales en historial para agregar al BOM."""
    q = q.strip()
    resultados = []
    if len(q) >= 3:
        resultados = await service.db.buscar_materiales_para_bom(conn, q)
    else:
        # Sin query: mostrar materiales recientes como dropdown inicial
        resultados = await service.db.get_materiales_recientes(conn, limite=10)

    return templates.TemplateResponse("bom/partials/buscar_materiales.html", {
        "request": request,
        "resultados": resultados,
        "query": q,
    })


# ========================================
# WORKFLOW DE APROBACION
# ========================================

@router.post("/{id_bom}/enviar-revision", include_in_schema=False)
async def enviar_revision(
    request: Request,
    id_bom: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("ingenieria", "editor"),
):
    """Envia BOM a revision de responsable de ingenieria."""
    form = await request.form()
    user_id = context.get("user_db_id")
    responsable_ing = form.get("responsable_ing")

    try:
        bom = await service.enviar_revision_ing(
            conn, id_bom, user_id,
            responsable_ing=UUID(responsable_ing) if responsable_ing else None
        )

        return templates.TemplateResponse("shared/toast.html", {
            "request": request,
            "message": "BOM enviado a revision de ingenieria",
            "type": "success",
            "redirect_url": f"/bom/{bom['id_proyecto']}/ui",
        })

    except ValueError as e:
        return templates.TemplateResponse("shared/toast.html", {
            "request": request,
            "message": str(e),
            "type": "error",
        })
    except asyncpg.PostgresError:
        logger.exception("Error de BD al enviar BOM a revision")
        return templates.TemplateResponse("shared/toast.html", {
            "request": request,
            "message": "Error interno al enviar a revision",
            "type": "error",
        })


@router.post("/{id_bom}/aprobar-ing", include_in_schema=False)
async def aprobar_ing(
    request: Request,
    id_bom: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_manager_access("ingenieria"),
):
    """Aprueba BOM por responsable de ingenieria."""
    form = await request.form()
    user_id = context.get("user_db_id")
    comentarios = form.get("comentarios", "").strip() or None

    try:
        bom = await service.aprobar_ing(conn, id_bom, user_id, comentarios)

        return templates.TemplateResponse("shared/toast.html", {
            "request": request,
            "message": "BOM aprobado por ingenieria",
            "type": "success",
            "redirect_url": f"/bom/{bom['id_proyecto']}/ui",
        })

    except ValueError as e:
        return templates.TemplateResponse("shared/toast.html", {
            "request": request,
            "message": str(e),
            "type": "error",
        })
    except asyncpg.PostgresError:
        logger.exception("Error de BD al aprobar BOM")
        return templates.TemplateResponse("shared/toast.html", {
            "request": request,
            "message": "Error interno al aprobar",
            "type": "error",
        })


@router.post("/{id_bom}/rechazar-ing", include_in_schema=False)
async def rechazar_ing(
    request: Request,
    id_bom: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_manager_access("ingenieria"),
):
    """Rechaza BOM por responsable de ingenieria."""
    form = await request.form()
    user_id = context.get("user_db_id")
    comentarios = form.get("comentarios", "").strip() or None

    try:
        bom = await service.rechazar_ing(conn, id_bom, user_id, comentarios)

        return templates.TemplateResponse("shared/toast.html", {
            "request": request,
            "message": "BOM rechazado. Se devolvio a borrador.",
            "type": "warning",
            "redirect_url": f"/bom/{bom['id_proyecto']}/ui",
        })

    except ValueError as e:
        return templates.TemplateResponse("shared/toast.html", {
            "request": request,
            "message": str(e),
            "type": "error",
        })
    except asyncpg.PostgresError:
        logger.exception("Error de BD al rechazar BOM")
        return templates.TemplateResponse("shared/toast.html", {
            "request": request,
            "message": "Error interno al rechazar",
            "type": "error",
        })


@router.post("/{id_bom}/enviar-const", include_in_schema=False)
async def enviar_const(
    request: Request,
    id_bom: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("ingenieria", "editor"),
):
    """Envia BOM aprobado por ing a revision de construccion."""
    form = await request.form()
    user_id = context.get("user_db_id")
    coordinador_obra = form.get("coordinador_obra")

    try:
        bom = await service.enviar_revision_const(
            conn, id_bom, user_id,
            coordinador_obra=UUID(coordinador_obra) if coordinador_obra else None
        )

        return templates.TemplateResponse("shared/toast.html", {
            "request": request,
            "message": "BOM enviado a revision de construccion",
            "type": "success",
            "redirect_url": f"/bom/{bom['id_proyecto']}/ui",
        })

    except ValueError as e:
        return templates.TemplateResponse("shared/toast.html", {
            "request": request,
            "message": str(e),
            "type": "error",
        })
    except asyncpg.PostgresError:
        logger.exception("Error de BD al enviar BOM a construccion")
        return templates.TemplateResponse("shared/toast.html", {
            "request": request,
            "message": "Error interno al enviar a construccion",
            "type": "error",
        })


@router.post("/{id_bom}/aprobar-const", include_in_schema=False)
async def aprobar_const(
    request: Request,
    id_bom: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_manager_access("construccion"),
):
    """Aprueba BOM por coordinador de construccion."""
    form = await request.form()
    user_id = context.get("user_db_id")
    comentarios = form.get("comentarios", "").strip() or None

    try:
        bom = await service.aprobar_const(conn, id_bom, user_id, comentarios)

        return templates.TemplateResponse("shared/toast.html", {
            "request": request,
            "message": "BOM aprobado por construccion. Listo para compras.",
            "type": "success",
            "redirect_url": f"/bom/{bom['id_proyecto']}/ui",
        })

    except ValueError as e:
        return templates.TemplateResponse("shared/toast.html", {
            "request": request,
            "message": str(e),
            "type": "error",
        })
    except asyncpg.PostgresError:
        logger.exception("Error de BD al aprobar BOM por construccion")
        return templates.TemplateResponse("shared/toast.html", {
            "request": request,
            "message": "Error interno al aprobar",
            "type": "error",
        })


@router.post("/{id_bom}/rechazar-const", include_in_schema=False)
async def rechazar_const(
    request: Request,
    id_bom: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_manager_access("construccion"),
):
    """Rechaza BOM por construccion. Vuelve a APROBADO_ING."""
    form = await request.form()
    user_id = context.get("user_db_id")
    comentarios = form.get("comentarios", "").strip() or None

    try:
        bom = await service.rechazar_const(conn, id_bom, user_id, comentarios)

        return templates.TemplateResponse("shared/toast.html", {
            "request": request,
            "message": "BOM rechazado por construccion. Devuelto a ingenieria.",
            "type": "warning",
            "redirect_url": f"/bom/{bom['id_proyecto']}/ui",
        })

    except ValueError as e:
        return templates.TemplateResponse("shared/toast.html", {
            "request": request,
            "message": str(e),
            "type": "error",
        })
    except asyncpg.PostgresError:
        logger.exception("Error de BD al rechazar BOM por construccion")
        return templates.TemplateResponse("shared/toast.html", {
            "request": request,
            "message": "Error interno al rechazar",
            "type": "error",
        })


@router.post("/{id_bom}/solicitar-modificacion", include_in_schema=False)
async def solicitar_modificacion(
    request: Request,
    id_bom: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_manager_access("ingenieria"),
):
    """Solicita modificacion post-aprobacion. Crea nueva version."""
    form = await request.form()
    user_id = context.get("user_db_id")
    comentarios = form.get("comentarios", "").strip() or None

    try:
        nuevo_bom = await service.solicitar_modificacion(
            conn, id_bom, user_id, comentarios
        )

        return templates.TemplateResponse("shared/toast.html", {
            "request": request,
            "message": f"Nueva version v{nuevo_bom['version']} creada en borrador",
            "type": "success",
            "redirect_url": f"/bom/{nuevo_bom['id_proyecto']}/ui",
        })

    except ValueError as e:
        return templates.TemplateResponse("shared/toast.html", {
            "request": request,
            "message": str(e),
            "type": "error",
        })
    except asyncpg.PostgresError:
        logger.exception("Error de BD al solicitar modificacion BOM")
        return templates.TemplateResponse("shared/toast.html", {
            "request": request,
            "message": "Error interno al solicitar modificacion",
            "type": "error",
        })


# ========================================
# HISTORIAL Y APROBACIONES
# ========================================

@router.get("/{id_bom}/historial", include_in_schema=False)
async def get_historial(
    request: Request,
    id_bom: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("ingenieria"),
):
    """Historial de cambios del BOM."""
    historial = await service.get_historial(conn, id_bom)
    bom = await service.get_bom(conn, id_bom)

    return templates.TemplateResponse("bom/partials/historial.html", {
        "request": request,
        "historial": historial,
        "bom": bom,
    })


@router.get("/{id_bom}/aprobaciones", include_in_schema=False)
async def get_aprobaciones(
    request: Request,
    id_bom: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("ingenieria"),
):
    """Timeline de aprobaciones del BOM."""
    aprobaciones = await service.get_aprobaciones(conn, id_bom)
    bom = await service.get_bom(conn, id_bom)

    return templates.TemplateResponse("bom/partials/aprobaciones.html", {
        "request": request,
        "aprobaciones": aprobaciones,
        "bom": bom,
    })


# ========================================
# MODAL APROBACION
# ========================================

@router.get("/{id_bom}/modal-aprobar/{accion}", include_in_schema=False)
async def get_modal_aprobar(
    request: Request,
    id_bom: UUID,
    accion: str,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("ingenieria"),
):
    """Modal de aprobacion/rechazo con campo de comentarios."""
    bom = await service.get_bom(conn, id_bom)
    catalogos = await service.get_catalogos(conn)

    return templates.TemplateResponse("bom/partials/modal_aprobar.html", {
        "request": request,
        "bom": bom,
        "accion": accion,
        "catalogos": catalogos,
    })


# ========================================
# EXPORT EXCEL
# ========================================

@router.get("/{id_proyecto}/export-excel", include_in_schema=False)
async def export_excel(
    request: Request,
    id_proyecto: UUID,
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("ingenieria"),
):
    """Descarga Excel del BOM del proyecto."""
    bom = await service.get_bom_proyecto(conn, id_proyecto)
    if not bom:
        raise HTTPException(status_code=404, detail="No existe BOM para este proyecto")

    excel_bytes = await service.export_to_excel(conn, bom['id_bom'])

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    proyecto_id = bom.get('proyecto_id_estandar', 'BOM')
    filename = f"BOM_{proyecto_id}_v{bom['version']}_{timestamp}.xlsx"

    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )
