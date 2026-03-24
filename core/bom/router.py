"""
Router compartido de BOM (Lista de Materiales).
Endpoints HTMX para CRUD de items, workflow de aprobaciones y exportacion Excel.
"""

from fastapi import APIRouter, Depends, Request, HTTPException, Form, UploadFile, File
from fastapi.templating import Jinja2Templates
from fastapi.responses import Response, HTMLResponse
from uuid import UUID
from datetime import datetime
from typing import List, Optional
import asyncpg
import logging
import json

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
    """Construye el contexto comun para templates de BOM.

    Calcula flags de permisos por area (ingenieria, construccion, compras) a partir
    del contexto de usuario, y los empaqueta junto con datos del BOM en un dict
    listo para pasar a TemplateResponse.

    Args:
        request: FastAPI Request.
        context: Dict de get_current_user_context (role, module_roles, user_db_id, etc).
        bom: Dict con los datos del BOM actual.
        **extra: Claves adicionales que se mezclan al contexto final.

    Returns:
        dict con request, bom, flags de permisos y cualquier clave extra.
    """
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
        "bom": bom,
        "area_editor": area_editor,
        "es_ing_editor": es_ing_editor,
        "es_ing_manager": es_ing_manager,
        "es_const_manager": es_const_manager,
        "es_compras_editor": es_compras_editor,
        "role": role,
        "user_id": context.get("user_db_id"),
        "user_name": context.get("user_name"),
        "es_aprobador_final": extra.get("es_aprobador_final", False),
        "es_rol_bom": extra.get("es_rol_bom", False),
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
    ultimo_rechazo = None

    es_aprobador_final = False
    es_rol_bom = False

    if bom:
        items = await service.get_items(conn, bom['id_bom'])
        estadisticas = await service.get_estadisticas(conn, bom['id_bom'])
        versiones = await service.db.get_all_bom_versions(conn, id_proyecto)
        if bom['estatus'] == 'BORRADOR':
            ultimo_rechazo = await service.get_ultimo_rechazo(conn, bom['id_bom'])
        aprobador_final_id = await service.get_aprobador_final_id(conn)
        user_id_ctx = context.get("user_db_id")
        if aprobador_final_id and str(user_id_ctx) == str(aprobador_final_id):
            es_aprobador_final = True
        es_rol_bom = await service.es_bom_role(conn, bom, user_id_ctx)

    ctx = _build_bom_context(
        request, context, bom,
        proyecto=proyecto,
        items=items,
        estadisticas=estadisticas,
        catalogos=catalogos,
        versiones=versiones,
        id_proyecto=id_proyecto,
        ultimo_rechazo=ultimo_rechazo,
        es_aprobador_final=es_aprobador_final,
        es_rol_bom=es_rol_bom,
    )

    is_htmx = request.headers.get("hx-request")
    template = "bom/partials/content.html" if is_htmx else "bom/dashboard.html"
    return templates.TemplateResponse(request, template, ctx)


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

        return templates.TemplateResponse(request, "shared/toast.html", {"message": f"BOM v{bom['version']} creado exitosamente",
            "type": "success",
            "redirect_url": f"/bom/{id_proyecto}/ui",
        })

    except ValueError as e:
        return templates.TemplateResponse(request, "shared/toast.html", {"message": str(e),
            "type": "error",
        })
    except asyncpg.PostgresError:
        logger.exception("Error de BD al crear BOM")
        return templates.TemplateResponse(request, "shared/toast.html", {"message": "Error interno al crear el BOM",
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
    return templates.TemplateResponse(request, "bom/partials/tabla_items.html", ctx)


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
        return templates.TemplateResponse(request, "shared/toast.html", {"message": "Solo Ingenieria y Construccion pueden agregar items al BOM. Compras solo puede editar proveedor y precio de items existentes.",
            "type": "error",
        })

    bom = await service.get_bom_proyecto(conn, id_proyecto)
    if not bom:
        return templates.TemplateResponse(request, "shared/toast.html", {"message": "No existe un BOM para este proyecto",
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
        return templates.TemplateResponse(request, "bom/partials/tabla_items.html", ctx)

    except ValueError as e:
        return templates.TemplateResponse(request, "shared/toast.html", {"message": str(e),
            "type": "error",
        })
    except asyncpg.PostgresError:
        logger.exception("Error de BD al agregar item BOM")
        return templates.TemplateResponse(request, "shared/toast.html", {"message": "Error interno al agregar el item",
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
        elif key == "cantidad_recibida":
            from decimal import Decimal as Dec
            campos[key] = Dec(val) if val and val.strip() else None
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

    # Extract grupo_ids before passing campos to editar_item (not a regular item field)
    grupo_ids_raw = form.getlist("grupo_ids")

    try:
        if campos:
            await service.editar_item(
                conn, id_item, user_id, area_editor, **campos
            )

        # Update grupos (empty list = remove all groups)
        grupo_ids = [int(g) for g in grupo_ids_raw if g]
        await service.set_item_grupos(conn, id_item, user_id, grupo_ids)

        # Retornar fila actualizada
        item = await service.get_item(conn, id_item)
        item['grupos'] = await service.db.get_grupos_por_item(conn, id_item)
        bom = await service.get_bom(conn, item['id_bom'])

        ctx = _build_bom_context(request, context, bom, item=item)
        return templates.TemplateResponse(request, "bom/partials/row_item.html", ctx)

    except ValueError as e:
        return templates.TemplateResponse(request, "shared/toast.html", {"message": str(e),
            "type": "error",
        })
    except asyncpg.PostgresError:
        logger.exception("Error de BD al editar item BOM")
        return templates.TemplateResponse(request, "shared/toast.html", {"message": "Error interno al editar el item",
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
        return templates.TemplateResponse(request, "shared/toast.html", {"message": "No tienes permisos para eliminar items",
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
        return templates.TemplateResponse(request, "bom/partials/tabla_items.html", ctx)

    except ValueError as e:
        return templates.TemplateResponse(request, "shared/toast.html", {"message": str(e),
            "type": "error",
        })
    except asyncpg.PostgresError:
        logger.exception("Error de BD al eliminar item BOM")
        return templates.TemplateResponse(request, "shared/toast.html", {"message": "Error interno al eliminar el item",
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
    return templates.TemplateResponse(request, "bom/partials/modal_item.html", ctx)


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

    return templates.TemplateResponse(request, "bom/partials/buscar_materiales.html", {"resultados": resultados,
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

        return templates.TemplateResponse(request, "shared/toast.html", {"message": "BOM enviado a revision de ingenieria",
            "type": "success",
            "redirect_url": f"/bom/{bom['id_proyecto']}/ui",
        })

    except ValueError as e:
        return templates.TemplateResponse(request, "shared/toast.html", {"message": str(e),
            "type": "error",
        })
    except asyncpg.PostgresError:
        logger.exception("Error de BD al enviar BOM a revision")
        return templates.TemplateResponse(request, "shared/toast.html", {"message": "Error interno al enviar a revision",
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

        return templates.TemplateResponse(request, "shared/toast.html", {"message": "BOM aprobado por ingenieria",
            "type": "success",
            "redirect_url": f"/bom/{bom['id_proyecto']}/ui",
        })

    except ValueError as e:
        return templates.TemplateResponse(request, "shared/toast.html", {"message": str(e),
            "type": "error",
        })
    except asyncpg.PostgresError:
        logger.exception("Error de BD al aprobar BOM")
        return templates.TemplateResponse(request, "shared/toast.html", {"message": "Error interno al aprobar",
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

        return templates.TemplateResponse(request, "shared/toast.html", {"message": "BOM rechazado. Se devolvio a borrador.",
            "type": "warning",
            "redirect_url": f"/bom/{bom['id_proyecto']}/ui",
        })

    except ValueError as e:
        return templates.TemplateResponse(request, "shared/toast.html", {"message": str(e),
            "type": "error",
        })
    except asyncpg.PostgresError:
        logger.exception("Error de BD al rechazar BOM")
        return templates.TemplateResponse(request, "shared/toast.html", {"message": "Error interno al rechazar",
            "type": "error",
        })


@router.post("/{id_bom}/enviar-const", include_in_schema=False)
async def enviar_const(
    request: Request,
    id_bom: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_manager_access("ingenieria"),
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

        return templates.TemplateResponse(request, "shared/toast.html", {"message": "BOM enviado a revision de construccion",
            "type": "success",
            "redirect_url": f"/bom/{bom['id_proyecto']}/ui",
        })

    except ValueError as e:
        return templates.TemplateResponse(request, "shared/toast.html", {"message": str(e),
            "type": "error",
        })
    except asyncpg.PostgresError:
        logger.exception("Error de BD al enviar BOM a construccion")
        return templates.TemplateResponse(request, "shared/toast.html", {"message": "Error interno al enviar a construccion",
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

        return templates.TemplateResponse(request, "shared/toast.html", {"message": "BOM aprobado por construccion. Listo para compras.",
            "type": "success",
            "redirect_url": f"/bom/{bom['id_proyecto']}/ui",
        })

    except ValueError as e:
        return templates.TemplateResponse(request, "shared/toast.html", {"message": str(e),
            "type": "error",
        })
    except asyncpg.PostgresError:
        logger.exception("Error de BD al aprobar BOM por construccion")
        return templates.TemplateResponse(request, "shared/toast.html", {"message": "Error interno al aprobar",
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

        return templates.TemplateResponse(request, "shared/toast.html", {"message": "BOM rechazado por construccion. Devuelto a ingenieria.",
            "type": "warning",
            "redirect_url": f"/bom/{bom['id_proyecto']}/ui",
        })

    except ValueError as e:
        return templates.TemplateResponse(request, "shared/toast.html", {"message": str(e),
            "type": "error",
        })
    except asyncpg.PostgresError:
        logger.exception("Error de BD al rechazar BOM por construccion")
        return templates.TemplateResponse(request, "shared/toast.html", {"message": "Error interno al rechazar",
            "type": "error",
        })


@router.post("/{id_bom}/devolver-borrador", include_in_schema=False)
async def devolver_borrador(
    request: Request,
    id_bom: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_manager_access("ingenieria"),
):
    """Devuelve BOM de APROBADO_ING a BORRADOR para correccion."""
    form = await request.form()
    user_id = context.get("user_db_id")
    comentarios = form.get("comentarios", "").strip() or None

    try:
        bom = await service.devolver_a_borrador(conn, id_bom, user_id, comentarios)

        return templates.TemplateResponse(request, "shared/toast.html", {"message": "BOM devuelto a borrador para correccion",
            "type": "warning",
            "redirect_url": f"/bom/{bom['id_proyecto']}/ui",
        })

    except ValueError as e:
        return templates.TemplateResponse(request, "shared/toast.html", {"message": str(e),
            "type": "error",
        })
    except asyncpg.PostgresError:
        logger.exception("Error de BD al devolver BOM a borrador")
        return templates.TemplateResponse(request, "shared/toast.html", {"message": "Error interno al devolver a borrador",
            "type": "error",
        })


@router.post("/{id_bom}/cancelar", include_in_schema=False)
async def cancelar_bom(
    request: Request,
    id_bom: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_manager_access("ingenieria"),
):
    """Cancela un BOM en BORRADOR."""
    form = await request.form()
    user_id = context.get("user_db_id")
    comentarios = form.get("comentarios", "").strip() or None

    try:
        bom = await service.cancelar_bom(conn, id_bom, user_id, comentarios)

        return templates.TemplateResponse(request, "shared/toast.html", {"message": "BOM cancelado",
            "type": "warning",
            "redirect_url": f"/bom/{bom['id_proyecto']}/ui",
        })

    except ValueError as e:
        return templates.TemplateResponse(request, "shared/toast.html", {"message": str(e),
            "type": "error",
        })
    except asyncpg.PostgresError:
        logger.exception("Error de BD al cancelar BOM")
        return templates.TemplateResponse(request, "shared/toast.html", {"message": "Error interno al cancelar el BOM",
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

        return templates.TemplateResponse(request, "shared/toast.html", {"message": f"Nueva version v{nuevo_bom['version']} creada en borrador",
            "type": "success",
            "redirect_url": f"/bom/{nuevo_bom['id_proyecto']}/ui",
        })

    except ValueError as e:
        return templates.TemplateResponse(request, "shared/toast.html", {"message": str(e),
            "type": "error",
        })
    except asyncpg.PostgresError:
        logger.exception("Error de BD al solicitar modificacion BOM")
        return templates.TemplateResponse(request, "shared/toast.html", {"message": "Error interno al solicitar modificacion",
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

    return templates.TemplateResponse(request, "bom/partials/historial.html", {"historial": historial,
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

    return templates.TemplateResponse(request, "bom/partials/aprobaciones.html", {"aprobaciones": aprobaciones,
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

    return templates.TemplateResponse(request, "bom/partials/modal_aprobar.html", {"bom": bom,
        "accion": accion,
        "catalogos": catalogos,
    })


# ========================================
# GRUPOS DE ITEM
# ========================================

@router.post("/items/{id_item}/grupos", include_in_schema=False)
async def set_item_grupos(
    request: Request,
    id_item: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("ingenieria"),
):
    """Asigna grupos BOM (AC/DC/CM/OC/TE) a un item."""
    form = await request.form()
    user_id = context.get("user_db_id")
    grupo_ids_raw = form.getlist("grupo_ids")

    try:
        grupo_ids = [int(g) for g in grupo_ids_raw if g]
        await service.set_item_grupos(conn, id_item, user_id, grupo_ids)

        item = await service.get_item(conn, id_item)
        item['grupos'] = await service.db.get_grupos_por_item(conn, id_item)
        bom = await service.get_bom(conn, item['id_bom'])
        ctx = _build_bom_context(request, context, bom, item=item)
        return templates.TemplateResponse(request, "bom/partials/row_item.html", ctx)

    except ValueError as e:
        return templates.TemplateResponse(request, "shared/toast.html", {"message": str(e), "type": "error"
        })
    except asyncpg.PostgresError:
        logger.exception("Error de BD al asignar grupos BOM")
        return templates.TemplateResponse(request, "shared/toast.html", {"message": "Error interno al asignar grupos", "type": "error"
        })


# ========================================
# SUPLENCIAS
# ========================================

@router.get("/suplencia/modal", include_in_schema=False)
async def get_modal_suplencia(
    request: Request,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("ingenieria"),
):
    """Modal para configurar suplente del usuario actual."""
    user_id = context.get("user_db_id")
    suplencia_activa = await service.get_suplencia_activa(conn, user_id)
    usuarios = await service.db.get_usuarios_por_area(conn, 'ingenieria', solo_jefes=False)
    const_usuarios = await service.db.get_usuarios_por_area(conn, 'construccion', solo_jefes=False)
    todos_usuarios = {str(u['id_usuario']): u for u in usuarios + const_usuarios}
    return templates.TemplateResponse(request, "bom/partials/modal_suplencia.html", {"suplencia_activa": suplencia_activa,
        "usuarios": list(todos_usuarios.values()),
        "user_id": user_id,
    })


@router.post("/suplencia", include_in_schema=False)
async def configurar_suplencia(
    request: Request,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("ingenieria"),
):
    """Configura suplente para el usuario actual."""
    form = await request.form()
    user_id = context.get("user_db_id")
    suplente_id_raw = form.get("suplente_id", "").strip()
    fecha_fin_raw = form.get("fecha_fin", "").strip()

    try:
        from uuid import UUID as _UUID
        from datetime import date as date_type
        suplente_id = _UUID(suplente_id_raw)
        fecha_fin = date_type.fromisoformat(fecha_fin_raw)
        await service.configurar_suplente(conn, user_id, suplente_id, fecha_fin)
        return templates.TemplateResponse(request, "shared/toast.html", {"message": "Suplencia configurada exitosamente",
            "type": "success",
        })
    except ValueError as e:
        return templates.TemplateResponse(request, "shared/toast.html", {"message": str(e), "type": "error"
        })
    except asyncpg.PostgresError:
        logger.exception("Error de BD al configurar suplencia")
        return templates.TemplateResponse(request, "shared/toast.html", {"message": "Error interno al configurar suplencia", "type": "error"
        })


@router.delete("/suplencia", include_in_schema=False)
async def eliminar_suplencia(
    request: Request,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("ingenieria"),
):
    """Elimina la suplencia activa del usuario actual."""
    user_id = context.get("user_db_id")
    try:
        await service.eliminar_suplencia(conn, user_id)
        return templates.TemplateResponse(request, "shared/toast.html", {"message": "Suplencia eliminada", "type": "success"
        })
    except asyncpg.PostgresError:
        logger.exception("Error de BD al eliminar suplencia")
        return templates.TemplateResponse(request, "shared/toast.html", {"message": "Error interno al eliminar suplencia", "type": "error"
        })


# ========================================
# WORKFLOW OBRA (coordinador_obra)
# ========================================

@router.post("/{id_bom}/enviar-obra", include_in_schema=False)
async def enviar_revision_obra(
    request: Request,
    id_bom: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("ingenieria"),
):
    """Envia BOM aprobado por ing a revision del coordinador de obra."""
    user_id = context.get("user_db_id")
    try:
        bom = await service.enviar_revision_obra(conn, id_bom, user_id)
        return templates.TemplateResponse(request, "shared/toast.html", {"message": "BOM enviado a revision de Obra",
            "type": "success",
            "redirect_url": f"/bom/{bom['id_proyecto']}/ui",
        })
    except ValueError as e:
        return templates.TemplateResponse(request, "shared/toast.html", {"message": str(e), "type": "error"
        })
    except asyncpg.PostgresError:
        logger.exception("Error de BD al enviar BOM a obra")
        return templates.TemplateResponse(request, "shared/toast.html", {"message": "Error interno", "type": "error"
        })


@router.post("/{id_bom}/aprobar-obra", include_in_schema=False)
async def aprobar_obra(
    request: Request,
    id_bom: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_manager_access("construccion"),
):
    """Aprueba BOM por coordinador de obra. Avanza automaticamente a EN_REVISION_CONST."""
    form = await request.form()
    user_id = context.get("user_db_id")
    comentarios = form.get("comentarios", "").strip() or None
    try:
        bom = await service.aprobar_obra(conn, id_bom, user_id, comentarios)
        return templates.TemplateResponse(request, "shared/toast.html", {"message": "BOM aprobado por Obra y enviado a Construccion",
            "type": "success",
            "redirect_url": f"/bom/{bom['id_proyecto']}/ui",
        })
    except ValueError as e:
        return templates.TemplateResponse(request, "shared/toast.html", {"message": str(e), "type": "error"
        })
    except asyncpg.PostgresError:
        logger.exception("Error de BD en aprobacion obra BOM")
        return templates.TemplateResponse(request, "shared/toast.html", {"message": "Error interno", "type": "error"
        })


@router.post("/{id_bom}/rechazar-obra", include_in_schema=False)
async def rechazar_obra(
    request: Request,
    id_bom: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_manager_access("construccion"),
):
    """Rechaza BOM por coordinador de obra. Vuelve a APROBADO_ING."""
    form = await request.form()
    user_id = context.get("user_db_id")
    comentarios = form.get("comentarios", "").strip() or None
    try:
        bom = await service.rechazar_obra(conn, id_bom, user_id, comentarios)
        return templates.TemplateResponse(request, "shared/toast.html", {"message": "BOM devuelto a Ingenieria para revision.",
            "type": "warning",
            "redirect_url": f"/bom/{bom['id_proyecto']}/ui",
        })
    except ValueError as e:
        return templates.TemplateResponse(request, "shared/toast.html", {"message": str(e), "type": "error"
        })
    except asyncpg.PostgresError:
        logger.exception("Error de BD en rechazo obra BOM")
        return templates.TemplateResponse(request, "shared/toast.html", {"message": "Error interno", "type": "error"
        })


# ========================================
# WORKFLOW APROBADOR FINAL
# ========================================

@router.post("/{id_bom}/enviar-final", include_in_schema=False)
async def enviar_revision_final(
    request: Request,
    id_bom: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_manager_access("construccion"),
):
    """Envia BOM aprobado por construccion al aprobador final."""
    user_id = context.get("user_db_id")
    try:
        bom = await service.enviar_revision_final(conn, id_bom, user_id)
        return templates.TemplateResponse(request, "shared/toast.html", {"message": "BOM enviado al aprobador final",
            "type": "success",
            "redirect_url": f"/bom/{bom['id_proyecto']}/ui",
        })
    except ValueError as e:
        return templates.TemplateResponse(request, "shared/toast.html", {"message": str(e), "type": "error"
        })
    except asyncpg.PostgresError:
        logger.exception("Error de BD al enviar BOM a revision final")
        return templates.TemplateResponse(request, "shared/toast.html", {"message": "Error interno", "type": "error"
        })


@router.post("/{id_bom}/aprobar-final", include_in_schema=False)
async def aprobar_final(
    request: Request,
    id_bom: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("ingenieria"),
):
    """Aprobacion final del BOM."""
    form = await request.form()
    user_id = context.get("user_db_id")
    comentarios = form.get("comentarios", "").strip() or None
    try:
        bom = await service.aprobar_final(conn, id_bom, user_id, comentarios)
        return templates.TemplateResponse(request, "shared/toast.html", {"message": "BOM aprobado de forma definitiva",
            "type": "success",
            "redirect_url": f"/bom/{bom['id_proyecto']}/ui",
        })
    except ValueError as e:
        return templates.TemplateResponse(request, "shared/toast.html", {"message": str(e), "type": "error"
        })
    except asyncpg.PostgresError:
        logger.exception("Error de BD en aprobacion final BOM")
        return templates.TemplateResponse(request, "shared/toast.html", {"message": "Error interno", "type": "error"
        })


@router.post("/{id_bom}/rechazar-final", include_in_schema=False)
async def rechazar_final(
    request: Request,
    id_bom: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("ingenieria"),
):
    """Rechazo por aprobador final. Vuelve a APROBADO."""
    form = await request.form()
    user_id = context.get("user_db_id")
    comentarios = form.get("comentarios", "").strip() or None
    try:
        bom = await service.rechazar_final(conn, id_bom, user_id, comentarios)
        return templates.TemplateResponse(request, "shared/toast.html", {"message": "BOM devuelto a construccion para revision.",
            "type": "warning",
            "redirect_url": f"/bom/{bom['id_proyecto']}/ui",
        })
    except ValueError as e:
        return templates.TemplateResponse(request, "shared/toast.html", {"message": str(e), "type": "error"
        })
    except asyncpg.PostgresError:
        logger.exception("Error de BD en rechazo final BOM")
        return templates.TemplateResponse(request, "shared/toast.html", {"message": "Error interno", "type": "error"
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


# ========================================
# COTIZACIONES (Fase C)
# ========================================

def _cotizacion_ctx(request, cotizaciones, bom, es_compras_editor: bool) -> dict:
    return {
        "cotizaciones": cotizaciones,
        "bom": bom,
        "es_compras_editor": es_compras_editor,
    }


@router.get("/{id_bom}/cotizaciones", include_in_schema=False)
async def get_cotizaciones_tab(
    request: Request,
    id_bom: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("ingenieria"),
):
    """Tab de cotizaciones — cargado lazy con HTMX intersect."""
    bom = await service.db.get_bom_by_id(conn, id_bom)
    if not bom:
        raise HTTPException(status_code=404, detail="BOM no encontrado")

    role = context.get("role")
    module_roles = context.get("module_roles", {})
    es_compras_editor = (
        role == "ADMIN"
        or module_roles.get("compras") in ("editor", "admin")
    )

    cotizaciones = await service.listar_cotizaciones(conn, id_bom)
    items = await service.get_items(conn, id_bom)
    items_disponibles = [i for i in items if i.get('estatus_compra', 'SIN_COTIZAR') not in ('AUTORIZADO', 'PAGADO')]

    return templates.TemplateResponse(
        request, "bom/partials/cotizaciones.html",
        {
            **_cotizacion_ctx(request, cotizaciones, bom, es_compras_editor),
            "items_disponibles": items_disponibles,
        }
    )


@router.post("/{id_bom}/cotizaciones", include_in_schema=False)
async def crear_cotizacion(
    request: Request,
    id_bom: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("compras"),
):
    """Crea una nueva cotización para el BOM. Recibe JSON en el body."""
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

    items_data = []
    for it in items_raw:
        items_data.append({
            "bom_item_id": UUID(it["bom_item_id"]),
            "precio_unitario": float(it["precio_unitario"]),
            "cantidad": float(it["cantidad"]),
        })

    try:
        await service.crear_cotizacion(
            conn, id_bom, proveedor_id, nombre_proveedor, moneda,
            items_data, iva_pct, notas, user_id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Retornar tab actualizado
    bom = await service.db.get_bom_by_id(conn, id_bom)
    cotizaciones = await service.listar_cotizaciones(conn, id_bom)
    items = await service.get_items(conn, id_bom)
    items_disponibles = [i for i in items if i.get('estatus_compra', 'SIN_COTIZAR') not in ('AUTORIZADO', 'PAGADO')]

    role = context.get("role")
    module_roles = context.get("module_roles", {})
    es_compras_editor = role == "ADMIN" or module_roles.get("compras") in ("editor", "admin")

    return templates.TemplateResponse(
        request, "bom/partials/cotizaciones.html",
        {
            **_cotizacion_ctx(request, cotizaciones, bom, es_compras_editor),
            "items_disponibles": items_disponibles,
        }
    )


@router.post("/cotizaciones/{cotizacion_id}/seleccionar", include_in_schema=False)
async def seleccionar_cotizacion(
    request: Request,
    cotizacion_id: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("compras"),
):
    user_id = context.get("user_db_id")
    try:
        cotizacion = await service.seleccionar_cotizacion(conn, cotizacion_id, user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    bom = await service.db.get_bom_by_id(conn, cotizacion['bom_id'])
    cotizaciones = await service.listar_cotizaciones(conn, cotizacion['bom_id'])
    items = await service.get_items(conn, cotizacion['bom_id'])
    items_disponibles = [i for i in items if i.get('estatus_compra', 'SIN_COTIZAR') not in ('AUTORIZADO', 'PAGADO')]

    role = context.get("role")
    module_roles = context.get("module_roles", {})
    es_compras_editor = role == "ADMIN" or module_roles.get("compras") in ("editor", "admin")

    return templates.TemplateResponse(
        request, "bom/partials/cotizaciones.html",
        {
            **_cotizacion_ctx(request, cotizaciones, bom, es_compras_editor),
            "items_disponibles": items_disponibles,
        }
    )


@router.post("/cotizaciones/{cotizacion_id}/rechazar", include_in_schema=False)
async def rechazar_cotizacion(
    request: Request,
    cotizacion_id: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("compras"),
):
    user_id = context.get("user_db_id")
    try:
        cotizacion = await service.rechazar_cotizacion(conn, cotizacion_id, user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    bom = await service.db.get_bom_by_id(conn, cotizacion['bom_id'])
    cotizaciones = await service.listar_cotizaciones(conn, cotizacion['bom_id'])
    items = await service.get_items(conn, cotizacion['bom_id'])
    items_disponibles = [i for i in items if i.get('estatus_compra', 'SIN_COTIZAR') not in ('AUTORIZADO', 'PAGADO')]

    role = context.get("role")
    module_roles = context.get("module_roles", {})
    es_compras_editor = role == "ADMIN" or module_roles.get("compras") in ("editor", "admin")

    return templates.TemplateResponse(
        request, "bom/partials/cotizaciones.html",
        {
            **_cotizacion_ctx(request, cotizaciones, bom, es_compras_editor),
            "items_disponibles": items_disponibles,
        }
    )


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

    return {
        "autorizaciones": autorizaciones,
        "bom": bom,
        "user_id": user_id,
        "es_admin": es_admin,
        "es_director": es_director,
        "es_coordinador_obra": es_coordinador_obra,
        "es_finanzas": es_finanzas,
    }


@router.get("/{id_bom}/autorizaciones", include_in_schema=False)
async def get_autorizaciones_tab(
    request: Request,
    id_bom: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("ingenieria"),
):
    bom = await service.db.get_bom_by_id(conn, id_bom)
    if not bom:
        raise HTTPException(status_code=404, detail="BOM no encontrado")
    autorizaciones = await service.listar_autorizaciones(conn, id_bom)
    return templates.TemplateResponse(
        request, "bom/partials/autorizaciones.html",
        _autorizacion_ctx(request, autorizaciones, bom, context),
    )


@router.post("/autorizaciones/{autorizacion_id}/aprobar-obra", include_in_schema=False)
async def aprobar_autorizacion_obra(
    request: Request,
    autorizacion_id: UUID,
    nota: Optional[str] = Form(None),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("ingenieria"),
):
    user_id = context.get("user_db_id")
    user_role = context.get("role")
    try:
        aut = await service.aprobar_obra(conn, autorizacion_id, user_id, nota, user_role)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except asyncpg.PostgresError:
        raise HTTPException(status_code=500, detail="Error al aprobar la autorización.")

    bom = await service.db.get_bom_by_id(conn, aut['bom_id'])
    autorizaciones = await service.listar_autorizaciones(conn, aut['bom_id'])
    return templates.TemplateResponse(
        request, "bom/partials/autorizaciones.html",
        _autorizacion_ctx(request, autorizaciones, bom, context),
    )


@router.post("/autorizaciones/{autorizacion_id}/aprobar-direccion", include_in_schema=False)
async def aprobar_autorizacion_direccion(
    request: Request,
    autorizacion_id: UUID,
    nota: Optional[str] = Form(None),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("ingenieria"),
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

    bom = await service.db.get_bom_by_id(conn, aut['bom_id'])
    autorizaciones = await service.listar_autorizaciones(conn, aut['bom_id'])
    return templates.TemplateResponse(
        request, "bom/partials/autorizaciones.html",
        _autorizacion_ctx(request, autorizaciones, bom, context),
    )


@router.post("/autorizaciones/{autorizacion_id}/aprobar-finanzas", include_in_schema=False)
async def aprobar_autorizacion_finanzas(
    request: Request,
    autorizacion_id: UUID,
    nota: Optional[str] = Form(None),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("ingenieria"),
):
    user_id = context.get("user_db_id")
    user_role = context.get("role")
    finanzas_role = context.get("module_roles", {}).get("finanzas")
    try:
        aut = await service.aprobar_finanzas(conn, autorizacion_id, user_id, nota, user_role, finanzas_role)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except asyncpg.PostgresError:
        raise HTTPException(status_code=500, detail="Error al aprobar la autorización.")

    bom = await service.db.get_bom_by_id(conn, aut['bom_id'])
    autorizaciones = await service.listar_autorizaciones(conn, aut['bom_id'])
    return templates.TemplateResponse(
        request, "bom/partials/autorizaciones.html",
        _autorizacion_ctx(request, autorizaciones, bom, context),
    )


@router.post("/autorizaciones/{autorizacion_id}/rechazar", include_in_schema=False)
async def rechazar_autorizacion(
    request: Request,
    autorizacion_id: UUID,
    motivo: str = Form(...),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("ingenieria"),
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

    bom = await service.db.get_bom_by_id(conn, aut['bom_id'])
    autorizaciones = await service.listar_autorizaciones(conn, aut['bom_id'])
    return templates.TemplateResponse(
        request, "bom/partials/autorizaciones.html",
        _autorizacion_ctx(request, autorizaciones, bom, context),
    )


@router.get("/proveedores/buscar", include_in_schema=False)
async def buscar_proveedores_bom(
    request: Request,
    q: str = "",
    conn=Depends(get_db_connection),
    _=require_module_access("compras"),
):
    """Autocomplete de proveedores para el modal de cotización."""
    if len(q) < 2:
        return HTMLResponse("")
    proveedores = await BomService().db.get_proveedores_buscar(conn, q)
    items_html = "".join(
        f'<button type="button" '
        f'onclick="seleccionarProveedor(\'{p["id_proveedor"]}\', \'{(p["nombre_comercial"] or p["razon_social"] or "").replace(chr(39), "")}\'); document.getElementById(\'resultados-proveedores-bom\').innerHTML=\'\'"'
        f' class="w-full text-left px-3 py-2 text-sm hover:bg-blue-50 border-b border-gray-100 last:border-0">'
        f'<span class="font-medium">{p["nombre_comercial"] or p["razon_social"]}</span>'
        f'<span class="text-xs text-gray-400 ml-2">{p["rfc"] or ""}</span>'
        f'</button>'
        for p in proveedores
    )
    if not items_html:
        items_html = '<p class="px-3 py-2 text-sm text-gray-400 italic">Sin resultados</p>'
    return HTMLResponse(
        f'<div class="bg-white border border-gray-200 rounded-lg shadow-lg overflow-hidden">{items_html}</div>'
    )
