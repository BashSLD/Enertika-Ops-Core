"""
Router compartido de BOM (Lista de Materiales).
Endpoints HTMX para CRUD de items, workflow de aprobaciones y exportacion Excel.
"""

from fastapi import APIRouter, Depends, Request, HTTPException, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import Response, HTMLResponse
from uuid import UUID
from typing import Optional
import json
import asyncpg
import logging

from core.database import get_db_connection
from core.security import get_current_user_context
from core.permissions import require_module_access, require_manager_access, require_role, require_any_module_access
from core.config import settings
from core.timezone import now_mx
from core.materials.normalizer import normalizar_descripcion
from .service import (
    BomService,
    get_bom_service,
    ESTATUS_ITEM_CERRADO_COMPRA,
    ESTATUS_COMPRA_BLOQUEA_ADENDA,
    CAMPOS_CONSTRUCCION_BASE,
)

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
    es_const_editor = (
        role == "ADMIN"
        or module_roles.get("construccion") in ("editor", "admin")
    )

    ctx = {
        "bom": bom,
        "area_editor": area_editor,
        "es_ing_editor": es_ing_editor,
        "es_ing_manager": es_ing_manager,
        "es_const_manager": es_const_manager,
        "es_const_editor": es_const_editor,
        "es_compras_editor": es_compras_editor,
        "role": role,
        "user_id": context.get("user_db_id"),
        "user_name": context.get("user_name"),
        "es_aprobador_final": extra.get("es_aprobador_final", False),
        "es_rol_bom": extra.get("es_rol_bom", False),
        "puede_aprobar": extra.get("puede_aprobar", False),
    }
    ctx.update(extra)
    return ctx


def _toast_response(
    request: Request,
    message: str,
    type_: str = "warning",
    title: str = "Aviso",
) -> Response:
    """Retorna toast OOB sin reemplazar el contenido HTMX actual."""
    return templates.TemplateResponse(
        request,
        "shared/toast.html",
        {"message": message, "type": type_, "title": title},
        headers={"HX-Reswap": "none", "HX-Push-Url": "false"},
    )


def _parse_grupo_ids(form) -> list[int]:
    try:
        grupo_ids = [int(g) for g in form.getlist("grupo_ids") if g]
    except (TypeError, ValueError):
        raise ValueError("Grupo BOM invalido") from None
    if not grupo_ids:
        raise ValueError("Selecciona al menos un grupo BOM")
    return grupo_ids


def _parse_bulk_valor(campo: str, raw: Optional[str]):
    """Convierte el valor crudo del form al tipo correcto segun el campo del bulk."""
    from decimal import Decimal
    from datetime import date as date_type
    raw = (raw or "").strip()
    if campo == "id_categoria":
        return int(raw) if raw else None
    if campo == "id_proveedor":
        return UUID(raw) if raw else None
    if campo in ("precio_unitario", "precio_real"):
        return Decimal(raw) if raw else None
    if campo == "entregado":
        return raw in ("true", "True", "1", "on")
    if campo in ("fecha_requerida", "fecha_llegada_real", "fecha_estimada_entrega"):
        return date_type.fromisoformat(raw) if raw else None
    if campo == "origen_precio":
        return raw if raw in ("CATALOGO", "MANUAL") else None
    if campo == "estatus_ejecucion":
        return raw or None
    # Texto: unidad_medida, tipo_entrega, comentarios, tipo_partida, moneda
    return raw or None


def _parse_item_form_data(form) -> tuple[dict, list[int]]:
    """Parsea campos comunes de alta de item/adenda desde FormData."""
    from decimal import Decimal, InvalidOperation

    id_categoria = form.get("id_categoria")
    cantidad_raw = (form.get("cantidad") or "0").strip() or "0"
    precio_unitario_raw = (form.get("precio_unitario") or "").strip()
    id_material_ref_raw = form.get("id_material_ref", "").strip()
    id_material_interno_raw = form.get("id_material_interno", "").strip()
    origen_precio = form.get("origen_precio", "MANUAL").strip() or "MANUAL"

    try:
        cantidad = Decimal(cantidad_raw)
        precio_unitario = Decimal(precio_unitario_raw) if precio_unitario_raw else None
        id_categoria_value = int(id_categoria) if id_categoria else None
        id_material_ref = UUID(id_material_ref_raw) if id_material_ref_raw else None
        id_material_interno = UUID(id_material_interno_raw) if id_material_interno_raw else None
    except (InvalidOperation, ValueError):
        raise ValueError("Cantidad, precio o referencia invalida") from None

    data = {
        "descripcion": form.get("descripcion", "").strip(),
        "cantidad": cantidad,
        "id_categoria": id_categoria_value,
        "unidad_medida": form.get("unidad_medida", "").strip() or None,
        "comentarios": form.get("comentarios", "").strip() or None,
        "precio_unitario": precio_unitario,
        "origen_precio": origen_precio if origen_precio in ("CATALOGO", "MANUAL") else "MANUAL",
        "id_material_ref": id_material_ref,
        "id_material_interno": id_material_interno,
        "tipo_partida": form.get("tipo_partida", "MATERIAL").strip() or "MATERIAL",
        "moneda": form.get("moneda", "MXN").strip() or "MXN",
    }
    return data, _parse_grupo_ids(form)


def _item_disponible_cotizacion(item: dict) -> bool:
    estatus_compra = item.get("estatus_compra", "SIN_COTIZAR")
    estatus_ejecucion = item.get("estatus_ejecucion")
    return (
        estatus_compra not in ESTATUS_COMPRA_BLOQUEA_ADENDA
        and estatus_ejecucion not in ESTATUS_ITEM_CERRADO_COMPRA
    )


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
):
    """Vista principal del BOM de un proyecto."""
    module_roles = context.get("module_roles", {})
    role = context.get("role")
    is_admin = role == "ADMIN"
    tiene_ingenieria = is_admin or bool(module_roles.get("ingenieria"))
    tiene_construccion = is_admin or bool(module_roles.get("construccion"))
    tiene_compras = is_admin or bool(module_roles.get("compras"))
    tiene_finanzas = is_admin or bool(module_roles.get("finanzas"))
    es_director = context.get("rol_organizacional") == "director"
    tiene_acceso_bom = any([tiene_ingenieria, tiene_construccion, tiene_compras, tiene_finanzas]) or es_director

    if not tiene_acceso_bom:
        return _toast_response(
            request,
            "El BOM solo lo pueden abrir Ingeniería, Construcción, Compras o Finanzas.",
        )

    proyecto = await service.db.get_proyecto_info(conn, id_proyecto)
    if not proyecto:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    bom = await service.get_bom_proyecto(conn, id_proyecto)

    user_id_ctx = context.get("user_db_id")
    ingeniero_asignado = None
    if not bom:
        ingeniero_asignado = await service.get_ingeniero_asignado(conn, id_proyecto)
    puede_gestionar_bom_ingenieria = await service.puede_crear_o_retomar_bom(
        conn, id_proyecto, user_id_ctx, ingeniero_asignado=ingeniero_asignado
    )

    if not bom:
        if es_director and not is_admin:
            return _toast_response(
                request,
                "El BOM no ha sido iniciado para este proyecto.",
            )
        if not tiene_ingenieria:
            return _toast_response(
                request,
                "El BOM no ha sido iniciado. Solo lo puede crear el departamento de Ingeniería.",
            )
        if not puede_gestionar_bom_ingenieria:
            jefe_label = await service.get_jefe_ingenieria_label(conn)
            return _toast_response(
                request,
                f"No tienes este proyecto asignado como ingeniero. Solicita a {jefe_label} que te asigne o que cree el BOM.",
            )
        if not ingeniero_asignado:
            return _toast_response(
                request,
                "Asigna un Ingeniero de Diseño al proyecto antes de crear el BOM. Puedes asignarte a ti mismo desde el Equipo del Proyecto.",
            )

    # Si el usuario solo tiene acceso por compras/finanzas, validar que el BOM este aprobado.
    is_downstream_only = (
        not is_admin
        and not es_director
        and not module_roles.get("ingenieria")
        and not module_roles.get("construccion")
        and (module_roles.get("compras") or module_roles.get("finanzas"))
    )
    if is_downstream_only:
        if not bom or bom['estatus'] not in [
            'APROBADO_CONST', 'EN_REVISION_FINAL', 'APROBADO_FINAL'
        ]:
            return _toast_response(
                request,
                "El BOM aún no está disponible para Compras o Finanzas. Espera a que sea aprobado por Construcción.",
            )

    is_construccion_only = (
        not is_admin
        and not module_roles.get("ingenieria")
        and module_roles.get("construccion")
    )
    if is_construccion_only and bom and bom['estatus'] not in [
        'EN_REVISION_OBRA', 'EN_REVISION_CONST',
        'APROBADO_CONST', 'EN_REVISION_FINAL', 'APROBADO_FINAL'
    ]:
        return _toast_response(
            request,
            "El BOM aún no está disponible para Construcción. Ingeniería debe enviarlo a revisión de Obra.",
        )

    catalogos = await service.get_catalogos(conn)
    items = []
    estadisticas = {}
    versiones = []
    ultimo_rechazo = None

    es_aprobador_final = False
    es_rol_bom = False
    puede_aprobar = False

    if bom:
        items = await service.get_items(conn, bom['id_bom'])
        estadisticas = await service.get_estadisticas(conn, bom['id_bom'])
        versiones = await service.db.get_all_bom_versions(conn, id_proyecto)
        if bom['estatus'] == 'BORRADOR':
            ultimo_rechazo = await service.get_ultimo_rechazo(conn, bom['id_bom'])
        aprobador_final_id = await service.get_aprobador_final_id(conn)
        if (
            aprobador_final_id
            and str(user_id_ctx) == str(aprobador_final_id)
            and context.get("rol_organizacional") == "director"
        ):
            es_aprobador_final = True
        # Suplencias del usuario: se calcula una vez y se reusa en ambas validaciones.
        representados = await service.get_titulares_que_representa(conn, user_id_ctx)
        es_rol_bom = await service.es_bom_role(conn, bom, user_id_ctx, representados=representados)

        # Flag para mostrar los botones de accion del responsable del rol solo a quien
        # el service aceptaria (propietario del rol, su suplente o ADMIN).
        # Incluye APROBADO_CONST: enviar a final lo hace el jefe de construccion.
        aprob_map = {
            'EN_REVISION_ING': (bom.get('responsable_ing'), 'jefe_ingenieria'),
            'EN_REVISION_OBRA': (bom.get('coordinador_obra'), 'jefe_construccion'),
            'EN_REVISION_CONST': (bom.get('jefe_construccion'), 'jefe_construccion'),
            'APROBADO_CONST': (bom.get('jefe_construccion'), 'jefe_construccion'),
        }
        if bom['estatus'] in aprob_map:
            responsable_id, fallback_rol_org = aprob_map[bom['estatus']]
            puede_aprobar = await service.puede_aprobar_bom(
                conn, user_id_ctx, context.get("role"),
                context.get("rol_organizacional"), responsable_id, fallback_rol_org,
                representados=representados
            )

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
        puede_aprobar=puede_aprobar,
        puede_gestionar_bom_ingenieria=puede_gestionar_bom_ingenieria,
    )

    is_htmx = request.headers.get("hx-request") and not request.headers.get("hx-history-restore-request")
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
    _=require_module_access("ingenieria"),
):
    """Crea un nuevo BOM para el proyecto."""
    form = await request.form()
    user_id = context.get("user_db_id")
    notas = form.get("notas", "").strip() or None

    try:
        bom = await service.crear_bom(
            conn, id_proyecto, user_id,
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
    _=require_any_module_access(["ingenieria", "construccion", "compras", "finanzas"]),
):
    """Tabla de items del BOM (partial HTMX)."""
    bom = await service.get_bom_proyecto(conn, id_proyecto)
    items = []
    if bom:
        items = await service.get_items(conn, bom['id_bom'])
    puede_gestionar_bom_ingenieria = await service.puede_crear_o_retomar_bom(
        conn, id_proyecto, context.get("user_db_id")
    )

    ctx = _build_bom_context(
        request, context, bom,
        items=items,
        puede_gestionar_bom_ingenieria=puede_gestionar_bom_ingenieria,
    )
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
    id_material_interno_raw = form.get("id_material_interno", "").strip()

    try:
        from decimal import Decimal
        grupo_ids = _parse_grupo_ids(form)
        precio_unitario = Decimal(precio_unitario_raw) if precio_unitario_raw else None
        id_material_ref = UUID(id_material_ref_raw) if id_material_ref_raw else None
        id_material_interno = UUID(id_material_interno_raw) if id_material_interno_raw else None
        item_data = {
            "descripcion": form.get("descripcion", "").strip(),
            "cantidad": Decimal(cantidad),
            "id_categoria": int(id_categoria) if id_categoria else None,
            "unidad_medida": form.get("unidad_medida", "").strip() or None,
            "comentarios": form.get("comentarios", "").strip() or None,
            "precio_unitario": precio_unitario,
            "origen_precio": origen_precio if origen_precio in ('CATALOGO', 'MANUAL') else 'MANUAL',
            "id_material_ref": id_material_ref,
            "id_material_interno": id_material_interno,
            "tipo_partida": form.get("tipo_partida", "MATERIAL").strip() or "MATERIAL",
            "moneda": form.get("moneda", "MXN").strip() or "MXN",
        }

        if service.requiere_propuesta_construccion(bom, area_editor):
            descripcion = item_data["descripcion"] or "item"
            motivo = (
                form.get("motivo")
                or item_data.get("comentarios")
                or f"Solicitud de Construccion para agregar {descripcion}"
            )
            await service.registrar_propuesta_auto(
                conn,
                bom["id_bom"],
                user_id,
                context,
                motivo,
                [{"accion": "AGREGAR", "datos": item_data, "grupo_ids": grupo_ids}],
            )
            return _toast_response(
                request,
                "Propuesta enviada a revision de Ingenieria",
                "success",
                "Propuesta registrada",
            )
        if service.base_construccion_bloqueada(bom, area_editor):
            return _toast_response(
                request,
                "Los cambios de alcance deben regresar por el flujo de aprobacion",
                "error",
                "Cambio bloqueado",
            )

        item = await service.agregar_item(
            conn, bom['id_bom'], user_id,
            **item_data,
            area_editor=area_editor,
        )

        await service.set_item_grupos(conn, item['id_item'], user_id, grupo_ids, area_editor)

        # Retornar tabla actualizada
        items = await service.get_items(conn, bom['id_bom'])
        bom = await service.get_bom(conn, bom['id_bom'])
        estadisticas = await service.get_estadisticas(conn, bom['id_bom'])

        ctx = _build_bom_context(
            request, context, bom,
            items=items, estadisticas=estadisticas,
            bulk_toast={
                "message": service.mensaje_item_sin_costo(),
                "type": "warning",
                "title": "Presupuesto pendiente",
            } if service.item_sin_costo(item) else None,
            puede_gestionar_bom_ingenieria=await service.puede_crear_o_retomar_bom(
                conn, bom['id_proyecto'], user_id
            ),
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
    _=require_any_module_access(["ingenieria", "construccion", "compras"]),
):
    """Edita un item del BOM."""
    form = await request.form()
    user_id = context.get("user_db_id")
    area_editor = _get_area_editor(context)

    if area_editor == "viewer":
        return templates.TemplateResponse(request, "shared/toast.html",
            {"message": "Sin permisos para editar items del BOM", "type": "error"},
            status_code=403)

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
        elif key in ("precio_unitario", "precio_real"):
            from decimal import Decimal as Dec
            campos[key] = Dec(val) if val and val.strip() else None
        elif key == "origen_precio":
            if val and val.strip() in ('CATALOGO', 'MANUAL'):
                campos[key] = val.strip()
        elif key in (
            "descripcion", "unidad_medida", "tipo_entrega", "comentarios",
            "comentarios_operativos", "tipo_partida", "moneda", "moneda_real",
            "estatus_ejecucion"
        ):
            campos[key] = val.strip() if val else None

    try:
        item_actual = await service.get_item(conn, id_item)
        bom_actual = await service.get_bom(conn, item_actual['id_bom'])
        actualiza_grupos = (
            (area_editor == "ingenieria" and bom_actual["estatus"] != "APROBADO_FINAL")
            or (
                area_editor == "construccion"
                and bom_actual["estatus"] in {"EN_REVISION_OBRA", "EN_REVISION_CONST", "APROBADO_FINAL"}
            )
        )
        grupo_ids = _parse_grupo_ids(form) if actualiza_grupos else None
        propuesta_creada = False
        if service.requiere_propuesta_construccion(bom_actual, area_editor):
            campos_propuesta = {
                key: campos.pop(key)
                for key in list(campos.keys())
                if key in CAMPOS_CONSTRUCCION_BASE
            }
            if campos_propuesta or grupo_ids is not None:
                await service.registrar_propuesta_auto(
                    conn,
                    bom_actual["id_bom"],
                    user_id,
                    context,
                    form.get("motivo")
                    or form.get("comentarios")
                    or "Solicitud de Construccion para ajustar item",
                    [{
                        "accion": "EDITAR",
                        "id_item": id_item,
                        "datos": campos_propuesta,
                        "grupo_ids": grupo_ids or [],
                    }],
                )
                propuesta_creada = True
                grupo_ids = None
        if campos:
            await service.editar_item(
                conn, id_item, user_id, area_editor, **campos
            )

        if grupo_ids is not None:
            await service.set_item_grupos(conn, id_item, user_id, grupo_ids, area_editor)

        if propuesta_creada and not campos:
            return _toast_response(
                request,
                "Propuesta enviada a revision de Ingenieria",
                "success",
                "Propuesta registrada",
            )

        # Retornar fila actualizada
        item = await service.get_item(conn, id_item)
        item['grupos'], item['grupos_operativos'] = await service.get_item_grupos(conn, id_item)
        bom = await service.get_bom(conn, item['id_bom'])

        ctx = _build_bom_context(
            request, context, bom,
            item=item,
            warning_message=service.mensaje_item_sin_costo() if service.item_sin_costo(item) else None,
            puede_gestionar_bom_ingenieria=await service.puede_crear_o_retomar_bom(
                conn, bom['id_proyecto'], user_id
            ),
        )
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


@router.patch("/{id_bom}/items/bulk-edit", include_in_schema=False)
async def bulk_editar_items(
    request: Request,
    id_bom: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(["ingenieria", "construccion", "compras"]),
):
    """Aplica un mismo cambio a varios items del BOM (edicion masiva)."""
    form = await request.form()
    user_id = context.get("user_db_id")
    area_editor = _get_area_editor(context)

    if area_editor == "viewer":
        return _toast_response(request, "Sin permisos para editar items del BOM", "error", "Error")

    campo = (form.get("campo") or "").strip()

    try:
        try:
            item_ids = [UUID(x) for x in form.getlist("item_ids") if x]
        except ValueError:
            raise ValueError("Seleccion de items invalida")
        if not item_ids:
            raise ValueError("Selecciona al menos un item")
        if not campo:
            raise ValueError("Selecciona un campo a editar")

        bom = await service.get_bom(conn, id_bom)
        if service.requiere_propuesta_construccion(bom, area_editor) and (
            campo == "grupos" or campo in CAMPOS_CONSTRUCCION_BASE
        ):
            if campo == "grupos":
                grupo_ids = _parse_grupo_ids(form)
                lineas = [
                    {
                        "accion": "EDITAR",
                        "id_item": item_id,
                        "datos": {},
                        "grupo_ids": grupo_ids,
                    }
                    for item_id in item_ids
                ]
            else:
                valor = _parse_bulk_valor(campo, form.get("valor"))
                lineas = [
                    {
                        "accion": "EDITAR",
                        "id_item": item_id,
                        "datos": {campo: valor},
                        "grupo_ids": [],
                    }
                    for item_id in item_ids
                ]
            await service.registrar_propuesta_auto(
                conn,
                id_bom,
                user_id,
                context,
                form.get("motivo") or "Solicitud masiva de Construccion",
                lineas,
            )
            return _toast_response(
                request,
                "Propuesta enviada a revision de Ingenieria",
                "success",
                "Propuesta registrada",
            )

        if campo == "grupos":
            resultado = await service.editar_items_bulk(
                conn, id_bom, item_ids, user_id, area_editor, campo,
                grupo_ids=_parse_grupo_ids(form),
            )
        else:
            valor = _parse_bulk_valor(campo, form.get("valor"))
            resultado = await service.editar_items_bulk(
                conn, id_bom, item_ids, user_id, area_editor, campo, valor=valor
            )

        items = await service.get_items(conn, id_bom)

        n = resultado["actualizados"]
        m = len(resultado["omitidos"])
        pendientes_sin_costo = await service.get_items_sin_costo(conn, id_bom)
        aviso_costo = (
            f"Hay {len(pendientes_sin_costo)} item(s) sin presupuesto base. Captura el presupuesto antes de avanzar el BOM."
            if pendientes_sin_costo else None
        )

        if aviso_costo:
            toast = {"message": aviso_costo, "type": "warning", "title": "Presupuesto pendiente"}
        elif n and m:
            toast = {"message": f"{n} items actualizados, {m} omitidos", "type": "warning", "title": "Edicion masiva"}
        elif n:
            toast = {"message": f"{n} items actualizados", "type": "success", "title": "Edicion masiva"}
        elif m:
            toast = {"message": f"0 items actualizados, {m} omitidos", "type": "error", "title": "Edicion masiva"}
        else:
            toast = {"message": "Ningun item se pudo actualizar", "type": "error", "title": "Edicion masiva"}

        # La respuesta solo reswapea #tabla-bom-items (tabla_items.html/row_item.html),
        # que no usa catalogos ni estadisticas; se omiten para evitar I/O desperdiciado.
        ctx = _build_bom_context(
            request, context, bom,
            items=items,
            bulk_toast=toast,
            puede_gestionar_bom_ingenieria=await service.puede_crear_o_retomar_bom(
                conn, bom['id_proyecto'], user_id
            ),
        )
        return templates.TemplateResponse(request, "bom/partials/tabla_items.html", ctx)

    except ValueError as e:
        return _toast_response(request, str(e), "error", "Error")
    except asyncpg.PostgresError:
        logger.exception("Error de BD en bulk edit BOM")
        return _toast_response(request, "Error interno al editar los items", "error", "Error")


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
        bom = await service.get_bom(conn, item['id_bom'])
        if service.requiere_propuesta_construccion(bom, area_editor):
            await service.registrar_propuesta_auto(
                conn,
                bom["id_bom"],
                user_id,
                context,
                f"Solicitud de Construccion para eliminar {item.get('descripcion') or 'item'}",
                [{"accion": "ELIMINAR", "id_item": id_item, "datos": {}, "grupo_ids": []}],
            )
            return _toast_response(
                request,
                "Propuesta enviada a revision de Ingenieria",
                "success",
                "Propuesta registrada",
            )
        await service.eliminar_item(conn, id_item, user_id, area_editor=area_editor)

        # Retornar tabla actualizada
        items = await service.get_items(conn, bom['id_bom'])
        estadisticas = await service.get_estadisticas(conn, bom['id_bom'])

        ctx = _build_bom_context(
            request, context, bom,
            items=items, estadisticas=estadisticas,
            puede_gestionar_bom_ingenieria=await service.puede_crear_o_retomar_bom(
                conn, bom['id_proyecto'], user_id
            ),
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


@router.post("/items/{id_item}/restaurar", include_in_schema=False)
async def restaurar_item(
    request: Request,
    id_item: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("ingenieria", "editor"),
):
    """Restaura un item eliminado (soft delete)."""
    user_id = context.get("user_db_id")
    try:
        item = await service.get_item(conn, id_item)
        await service.db.restaurar_item(conn, id_item)

        bom = await service.get_bom(conn, item['id_bom'])
        items = await service.get_items(conn, bom['id_bom'])
        estadisticas = await service.get_estadisticas(conn, bom['id_bom'])

        ctx = _build_bom_context(
            request, context, bom,
            items=items, estadisticas=estadisticas,
            puede_gestionar_bom_ingenieria=await service.puede_crear_o_retomar_bom(
                conn, bom['id_proyecto'], user_id
            ),
        )
        return templates.TemplateResponse(request, "bom/partials/tabla_items.html", ctx)
    except ValueError as e:
        return templates.TemplateResponse(request, "shared/toast.html", {"message": str(e), "type": "error"
        })
    except asyncpg.PostgresError:
        logger.exception("Error de BD al restaurar item BOM")
        return templates.TemplateResponse(request, "shared/toast.html", {"message": "Error interno al restaurar el item", "type": "error"
        })


@router.get("/items/{id_item}/modal", include_in_schema=False)
async def get_modal_editar_item(
    request: Request,
    id_item: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(["ingenieria", "construccion", "compras"], "viewer"),
):
    """Modal para editar un item."""
    item = await service.get_item(conn, id_item)
    item["grupos"], item["grupos_operativos"] = await service.get_item_grupos(conn, id_item)
    bom = await service.get_bom(conn, item['id_bom'])
    catalogos = await service.get_catalogos(conn)

    ctx = _build_bom_context(
        request, context, bom,
        item=item, catalogos=catalogos
    )
    return templates.TemplateResponse(request, "bom/partials/modal_item.html", ctx)


@router.get("/items/{id_item}/adenda-modal", include_in_schema=False)
async def get_modal_adenda_item(
    request: Request,
    id_item: UUID,
    accion: str = "reemplazo",
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(["construccion", "compras"], "editor"),
):
    """Modal para reemplazar o cerrar sin compra un item base."""
    if accion not in ("reemplazo", "cerrar"):
        raise HTTPException(status_code=400, detail="Accion invalida")
    item = await service.get_item(conn, id_item)
    item["grupos"] = await service.get_item_grupos_base(conn, id_item)
    bom = await service.get_bom(conn, item["id_bom"])
    catalogos = await service.get_catalogos(conn)
    ctx = _build_bom_context(
        request, context, bom,
        item=item,
        accion=accion,
        catalogos=catalogos,
    )
    return templates.TemplateResponse(request, "bom/partials/modal_adenda.html", ctx)


@router.get("/{id_bom}/adenda-modal", include_in_schema=False)
async def get_modal_adenda_bom(
    request: Request,
    id_bom: UUID,
    accion: str = "fuera_scope",
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(["construccion", "compras"], "editor"),
):
    """Modal para agregar una linea fuera de alcance al BOM aprobado."""
    if accion != "fuera_scope":
        raise HTTPException(status_code=400, detail="Accion invalida")
    bom = await service.get_bom(conn, id_bom)
    catalogos = await service.get_catalogos(conn)
    ctx = _build_bom_context(
        request, context, bom,
        item=None,
        accion=accion,
        catalogos=catalogos,
    )
    return templates.TemplateResponse(request, "bom/partials/modal_adenda.html", ctx)


async def _tabla_items_bom_ctx(
    request: Request,
    context: dict,
    conn,
    service: BomService,
    id_bom: UUID,
    user_id: UUID,
    bulk_toast: Optional[dict] = None,
) -> dict:
    bom = await service.get_bom(conn, id_bom)
    items = await service.get_items(conn, id_bom)
    estadisticas = await service.get_estadisticas(conn, id_bom)
    return _build_bom_context(
        request, context, bom,
        items=items,
        estadisticas=estadisticas,
        bulk_toast=bulk_toast,
        puede_gestionar_bom_ingenieria=await service.puede_crear_o_retomar_bom(
            conn, bom["id_proyecto"], user_id
        ),
    )


@router.post("/items/{id_item}/cerrar-sin-compra", include_in_schema=False)
async def cerrar_item_sin_compra(
    request: Request,
    id_item: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(["construccion", "compras"], "editor"),
):
    """Cierra un item base sin compra mediante adenda."""
    form = await request.form()
    user_id = context.get("user_db_id")
    try:
        adenda = await service.cerrar_item_sin_compra(
            conn, id_item, user_id, form.get("motivo", "")
        )
        ctx = await _tabla_items_bom_ctx(
            request, context, conn, service, adenda["id_bom"], user_id,
            bulk_toast={
                "message": "Adenda enviada a aprobacion de Construccion",
                "type": "success",
                "title": "Adenda pendiente",
            },
        )
        return templates.TemplateResponse(request, "bom/partials/tabla_items.html", ctx)
    except ValueError as e:
        return _toast_response(request, str(e), "error", "Error")
    except asyncpg.PostgresError:
        logger.exception("Error de BD al cerrar item sin compra")
        return _toast_response(request, "Error interno al registrar la adenda", "error", "Error")


@router.post("/items/{id_item}/reemplazo", include_in_schema=False)
async def crear_reemplazo_item(
    request: Request,
    id_item: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(["construccion", "compras"], "editor"),
):
    """Crea un reemplazo cotizable para un item base."""
    form = await request.form()
    user_id = context.get("user_db_id")
    try:
        item_data, grupo_ids = _parse_item_form_data(form)
        adenda = await service.crear_reemplazo_item(
            conn, id_item, user_id,
            grupo_ids=grupo_ids,
            motivo=form.get("motivo", ""),
            **item_data,
        )
        ctx = await _tabla_items_bom_ctx(
            request, context, conn, service, adenda["id_bom"], user_id,
            bulk_toast={
                "message": "Reemplazo enviado a aprobacion de Construccion",
                "type": "success",
                "title": "Adenda pendiente",
            },
        )
        return templates.TemplateResponse(request, "bom/partials/tabla_items.html", ctx)
    except ValueError as e:
        return _toast_response(request, str(e), "error", "Error")
    except asyncpg.PostgresError:
        logger.exception("Error de BD al crear reemplazo BOM")
        return _toast_response(request, "Error interno al registrar el reemplazo", "error", "Error")


@router.post("/{id_bom}/fuera-scope", include_in_schema=False)
async def agregar_fuera_scope(
    request: Request,
    id_bom: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(["construccion", "compras"], "editor"),
):
    """Agrega un item fuera de alcance principal mediante adenda."""
    form = await request.form()
    user_id = context.get("user_db_id")
    try:
        item_data, grupo_ids = _parse_item_form_data(form)
        await service.agregar_fuera_scope(
            conn, id_bom, user_id,
            grupo_ids=grupo_ids,
            motivo=form.get("motivo", ""),
            **item_data,
        )
        ctx = await _tabla_items_bom_ctx(
            request, context, conn, service, id_bom, user_id,
            bulk_toast={
                "message": "Item fuera de alcance enviado a aprobacion de Construccion",
                "type": "success",
                "title": "Adenda pendiente",
            },
        )
        return templates.TemplateResponse(request, "bom/partials/tabla_items.html", ctx)
    except ValueError as e:
        return _toast_response(request, str(e), "error", "Error")
    except asyncpg.PostgresError:
        logger.exception("Error de BD al agregar fuera de alcance BOM")
        return _toast_response(request, "Error interno al registrar la adenda", "error", "Error")


@router.get("/{id_bom}/adendas", include_in_schema=False)
async def get_adendas_tab(
    request: Request,
    id_bom: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(["ingenieria", "construccion", "compras", "finanzas"], allow_org_roles={"director"}),
):
    """Tab de adendas registradas en el BOM."""
    return await _adendas_tab_response(request, context, conn, service, id_bom)


async def _adendas_tab_response(
    request: Request,
    context: dict,
    conn,
    service: BomService,
    id_bom: UUID,
):
    bom = await service.get_bom(conn, id_bom)
    adendas = await service.get_adendas(conn, id_bom)
    comentarios = await service.get_adenda_comentarios_by_bom(conn, id_bom)
    return templates.TemplateResponse(
        request,
        "bom/partials/adendas.html",
        _build_bom_context(
            request, context, bom,
            adendas=adendas,
            comentarios_adendas=comentarios,
        ),
    )


@router.post("/adendas/{id_adenda}/aprobar-construccion", include_in_schema=False)
async def aprobar_adenda_construccion(
    request: Request,
    id_adenda: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("construccion", "editor"),
):
    """Aprueba una adenda desde Construccion."""
    form = await request.form()
    user_id = context.get("user_db_id")
    requiere_ingenieria = form.get("requiere_ingenieria") in ("on", "true", "1", "True")
    try:
        adenda = await service.aprobar_adenda_construccion(
            conn,
            id_adenda,
            user_id,
            context.get("role"),
            context.get("rol_organizacional"),
            requiere_ingenieria=requiere_ingenieria,
        )
        return await _adendas_tab_response(
            request, context, conn, service, adenda["id_bom_base"]
        )
    except ValueError as e:
        return _toast_response(request, str(e), "error", "Error")
    except asyncpg.PostgresError:
        logger.exception("Error de BD al aprobar adenda por Construccion")
        return _toast_response(request, "Error interno al aprobar la adenda", "error", "Error")


@router.post("/adendas/{id_adenda}/aprobar-ingenieria", include_in_schema=False)
async def aprobar_adenda_ingenieria(
    request: Request,
    id_adenda: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("ingenieria", "editor"),
):
    """Aprueba tecnicamente una adenda desde Ingenieria."""
    user_id = context.get("user_db_id")
    try:
        adenda = await service.aprobar_adenda_ingenieria(
            conn,
            id_adenda,
            user_id,
            context.get("role"),
            context.get("rol_organizacional"),
        )
        return await _adendas_tab_response(
            request, context, conn, service, adenda["id_bom_base"]
        )
    except ValueError as e:
        return _toast_response(request, str(e), "error", "Error")
    except asyncpg.PostgresError:
        logger.exception("Error de BD al aprobar adenda por Ingenieria")
        return _toast_response(request, "Error interno al aprobar la adenda", "error", "Error")


@router.post("/adendas/{id_adenda}/rechazar", include_in_schema=False)
async def rechazar_adenda(
    request: Request,
    id_adenda: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(["ingenieria", "construccion"], "editor"),
):
    """Rechaza una adenda pendiente."""
    form = await request.form()
    user_id = context.get("user_db_id")
    try:
        adenda = await service.rechazar_adenda(
            conn,
            id_adenda,
            user_id,
            context.get("role"),
            context.get("rol_organizacional"),
            form.get("motivo_rechazo", ""),
        )
        return await _adendas_tab_response(
            request, context, conn, service, adenda["id_bom_base"]
        )
    except ValueError as e:
        return _toast_response(request, str(e), "error", "Error")
    except asyncpg.PostgresError:
        logger.exception("Error de BD al rechazar adenda")
        return _toast_response(request, "Error interno al rechazar la adenda", "error", "Error")


@router.post("/adendas/{id_adenda}/cancelar", include_in_schema=False)
async def cancelar_adenda(
    request: Request,
    id_adenda: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("construccion", "editor"),
):
    """Cancela una adenda pendiente de Construccion."""
    user_id = context.get("user_db_id")
    try:
        adenda = await service.cancelar_adenda(
            conn,
            id_adenda,
            user_id,
            context.get("role"),
            context.get("rol_organizacional"),
        )
        return await _adendas_tab_response(
            request, context, conn, service, adenda["id_bom_base"]
        )
    except ValueError as e:
        return _toast_response(request, str(e), "error", "Error")
    except asyncpg.PostgresError:
        logger.exception("Error de BD al cancelar adenda")
        return _toast_response(request, "Error interno al cancelar la adenda", "error", "Error")


@router.post("/adendas/{id_adenda}/comentarios", include_in_schema=False)
async def comentar_adenda(
    request: Request,
    id_adenda: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(["ingenieria", "construccion", "compras", "finanzas"], "viewer", allow_org_roles={"director"}),
):
    """Agrega comentario a una adenda."""
    form = await request.form()
    user_id = context.get("user_db_id")
    try:
        await service.comentar_adenda(conn, id_adenda, user_id, form.get("comentario", ""))
        adenda = await service.get_adenda(conn, id_adenda)
        return await _adendas_tab_response(
            request, context, conn, service, adenda["id_bom_base"]
        )
    except ValueError as e:
        return _toast_response(request, str(e), "error", "Error")
    except asyncpg.PostgresError:
        logger.exception("Error de BD al comentar adenda")
        return _toast_response(request, "Error interno al comentar la adenda", "error", "Error")


@router.get("/{id_bom}/propuestas-cambio", include_in_schema=False)
async def get_propuestas_cambio_tab(
    request: Request,
    id_bom: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(["ingenieria", "construccion"], "viewer"),
):
    """Tab de propuestas de cambio pre-final del BOM."""
    return await _propuestas_tab_response(request, context, conn, service, id_bom)


async def _propuestas_tab_response(
    request: Request,
    context: dict,
    conn,
    service: BomService,
    id_bom: UUID,
):
    bom = await service.get_bom(conn, id_bom)
    propuestas = await service.get_propuestas_cambio(conn, id_bom)
    return templates.TemplateResponse(
        request,
        "bom/partials/propuestas_cambio.html",
        _build_bom_context(request, context, bom, propuestas=propuestas),
    )


@router.post("/{id_bom}/propuestas-cambio", include_in_schema=False)
async def crear_propuesta_cambio(
    request: Request,
    id_bom: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(["construccion"], "editor"),
):
    """Crea una propuesta pre-final para revision de Ingenieria."""
    form = await request.form()
    user_id = context.get("user_db_id")
    try:
        await service.crear_propuesta_cambio(
            conn,
            id_bom,
            user_id,
            form.get("tipo_solicitante", "CONSTRUCCION"),
            form.get("motivo", ""),
            form.get("lineas_json", "[]"),
            context.get("role"),
            context.get("rol_organizacional"),
        )
        return await _propuestas_tab_response(request, context, conn, service, id_bom)
    except (ValueError, json.JSONDecodeError) as e:
        return _toast_response(request, str(e), "error", "Error")
    except asyncpg.PostgresError:
        logger.exception("Error de BD al crear propuesta de cambio BOM")
        return _toast_response(request, "Error interno al crear la propuesta", "error", "Error")


@router.post("/propuestas-cambio/{id_propuesta}/aprobar", include_in_schema=False)
async def aprobar_propuesta_cambio(
    request: Request,
    id_propuesta: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("ingenieria", "editor"),
):
    """Aprueba y aplica una propuesta pre-final."""
    form = await request.form()
    user_id = context.get("user_db_id")
    lineas_revision = form.get("lineas_json") or None
    ingenieria_modifico = form.get("ingenieria_modifico") in ("on", "true", "1", "True")
    try:
        propuesta = await service.aprobar_propuesta_cambio(
            conn,
            id_propuesta,
            user_id,
            context.get("role"),
            context.get("rol_organizacional"),
            lineas_revision=lineas_revision,
            ingenieria_modifico=ingenieria_modifico,
            comentario_revision=form.get("comentario_revision"),
        )
        return await _propuestas_tab_response(
            request, context, conn, service, propuesta["id_bom"]
        )
    except (ValueError, json.JSONDecodeError) as e:
        return _toast_response(request, str(e), "error", "Error")
    except asyncpg.PostgresError:
        logger.exception("Error de BD al aprobar propuesta de cambio BOM")
        return _toast_response(request, "Error interno al aprobar la propuesta", "error", "Error")


@router.post("/propuestas-cambio/{id_propuesta}/rechazar", include_in_schema=False)
async def rechazar_propuesta_cambio(
    request: Request,
    id_propuesta: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("ingenieria", "editor"),
):
    """Rechaza una propuesta pre-final."""
    form = await request.form()
    user_id = context.get("user_db_id")
    try:
        propuesta = await service.rechazar_propuesta_cambio(
            conn,
            id_propuesta,
            user_id,
            context.get("role"),
            context.get("rol_organizacional"),
            form.get("comentario_revision", ""),
        )
        return await _propuestas_tab_response(
            request, context, conn, service, propuesta["id_bom"]
        )
    except ValueError as e:
        return _toast_response(request, str(e), "error", "Error")
    except asyncpg.PostgresError:
        logger.exception("Error de BD al rechazar propuesta de cambio BOM")
        return _toast_response(request, "Error interno al rechazar la propuesta", "error", "Error")


# ========================================
# BUSQUEDA DE MATERIALES
# ========================================

@router.get("/materiales/buscar", include_in_schema=False)
async def buscar_materiales(
    request: Request,
    q: str = "",
    limit: int = 20,
    offset: int = 0,
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(["ingenieria", "construccion"], "editor"),
):
    """Busqueda fuzzy de materiales en historial para agregar al BOM."""
    q = q.strip()
    limit = min(max(limit, 10), 50)
    offset = max(offset, 0)
    resultado_busqueda = {"items": [], "total": 0, "limit": limit}
    if len(q) >= 3:
        resultado_busqueda = await service.db.buscar_materiales_para_bom(
            conn, q, query_norm=normalizar_descripcion(q), limite=limit, offset=offset
        )
    else:
        # Sin query: mostrar materiales recientes como dropdown inicial
        resultado_busqueda = await service.db.get_materiales_recientes(
            conn, limite=limit, offset=offset
        )

    resultados = resultado_busqueda["items"]
    total = resultado_busqueda["total"]
    current_limit = resultado_busqueda["limit"]
    current_offset = resultado_busqueda["offset"]
    mostrados = min(current_offset + len(resultados), total)
    return templates.TemplateResponse(request, "bom/partials/buscar_materiales.html", {"resultados": resultados,
        "query": q,
        "total": total,
        "limit": current_limit,
        "offset": current_offset,
        "mostrados": mostrados,
        "has_more": mostrados < total,
        "next_offset": mostrados,
        "append_mode": current_offset > 0,
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
    user_id = context.get("user_db_id")

    try:
        bom = await service.enviar_revision_ing(
            conn, id_bom, user_id
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
    _=require_any_module_access(["ingenieria"], "editor"),
):
    form = await request.form()
    user_id = context.get("user_db_id")
    user_role = context.get("role")
    rol_org = context.get("rol_organizacional")
    comentarios = form.get("comentarios", "").strip() or None

    try:
        bom = await service.aprobar_ing(conn, id_bom, user_id, user_role, rol_org, comentarios)
        return templates.TemplateResponse(request, "shared/toast.html", {
            "message": "BOM aprobado por ingenieria",
            "type": "success",
            "redirect_url": f"/bom/{bom['id_proyecto']}/ui",
        })
    except ValueError as e:
        return templates.TemplateResponse(request, "shared/toast.html", {"message": str(e), "type": "error"})
    except asyncpg.PostgresError:
        logger.exception("Error de BD al aprobar BOM")
        return templates.TemplateResponse(request, "shared/toast.html", {"message": "Error interno al aprobar", "type": "error"})


@router.post("/{id_bom}/rechazar-ing", include_in_schema=False)
async def rechazar_ing(
    request: Request,
    id_bom: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(["ingenieria"], "editor"),
):
    form = await request.form()
    user_id = context.get("user_db_id")
    user_role = context.get("role")
    rol_org = context.get("rol_organizacional")
    comentarios = form.get("comentarios", "").strip() or None

    try:
        bom = await service.rechazar_ing(conn, id_bom, user_id, user_role, rol_org, comentarios)
        return templates.TemplateResponse(request, "shared/toast.html", {
            "message": "BOM rechazado. Se devolvio a borrador.",
            "type": "warning",
            "redirect_url": f"/bom/{bom['id_proyecto']}/ui",
        })
    except ValueError as e:
        return templates.TemplateResponse(request, "shared/toast.html", {"message": str(e), "type": "error"})
    except asyncpg.PostgresError:
        logger.exception("Error de BD al rechazar BOM")
        return templates.TemplateResponse(request, "shared/toast.html", {"message": "Error interno al rechazar", "type": "error"})


@router.post("/{id_bom}/aprobar-const", include_in_schema=False)
async def aprobar_const(
    request: Request,
    id_bom: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(["construccion"], "editor"),
):
    form = await request.form()
    user_id = context.get("user_db_id")
    user_role = context.get("role")
    rol_org = context.get("rol_organizacional")
    comentarios = form.get("comentarios", "").strip() or None

    try:
        bom = await service.aprobar_const(conn, id_bom, user_id, user_role, rol_org, comentarios)
        return templates.TemplateResponse(request, "shared/toast.html", {
            "message": "BOM aprobado por construccion. Listo para compras.",
            "type": "success",
            "redirect_url": f"/bom/{bom['id_proyecto']}/ui",
        })
    except ValueError as e:
        return templates.TemplateResponse(request, "shared/toast.html", {"message": str(e), "type": "error"})
    except asyncpg.PostgresError:
        logger.exception("Error de BD al aprobar BOM por construccion")
        return templates.TemplateResponse(request, "shared/toast.html", {"message": "Error interno al aprobar", "type": "error"})


@router.post("/{id_bom}/rechazar-const", include_in_schema=False)
async def rechazar_const(
    request: Request,
    id_bom: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(["construccion"], "editor"),
):
    form = await request.form()
    user_id = context.get("user_db_id")
    user_role = context.get("role")
    rol_org = context.get("rol_organizacional")
    comentarios = form.get("comentarios", "").strip() or None
    destino_rechazo = form.get("destino_rechazo", "").strip()

    try:
        if destino_rechazo not in {"obra", "ingenieria"}:
            raise ValueError("Selecciona a donde debe regresar el BOM")

        bom = await service.rechazar_const(
            conn, id_bom, user_id, user_role, rol_org, comentarios,
            destino_rechazo=destino_rechazo
        )
        message = (
            "BOM devuelto a revision de Obra."
            if destino_rechazo == "obra"
            else "BOM devuelto a borrador para correccion de Disenio."
        )
        return templates.TemplateResponse(request, "shared/toast.html", {
            "message": message,
            "type": "warning",
            "redirect_url": f"/bom/{bom['id_proyecto']}/ui",
        })
    except ValueError as e:
        return templates.TemplateResponse(request, "shared/toast.html", {"message": str(e), "type": "error"})
    except asyncpg.PostgresError:
        logger.exception("Error de BD al rechazar BOM por construccion")
        return templates.TemplateResponse(request, "shared/toast.html", {"message": "Error interno al rechazar", "type": "error"})


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
    _=require_any_module_access(["ingenieria", "compras", "finanzas"]),
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
    _=require_any_module_access(["ingenieria", "compras", "finanzas"]),
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
    _=require_any_module_access(["ingenieria", "construccion"], "viewer", allow_org_roles={"director"}),
):
    """Modal de aprobacion/rechazo con campo de comentarios."""
    acciones_validas = {
        "enviar-revision", "aprobar-ing", "rechazar-ing", "enviar-obra",
        "aprobar-obra", "rechazar-obra", "aprobar-const", "rechazar-const",
        "devolver-borrador", "cancelar", "solicitar-modificacion",
        "enviar-final", "aprobar-final", "rechazar-final",
    }
    if accion not in acciones_validas:
        return _toast_response(request, "Acción de BOM no disponible", "error", "Acción inválida")

    bom = await service.get_bom(conn, id_bom)
    if (
        context.get("rol_organizacional") == "director"
        and context.get("role") != "ADMIN"
    ):
        aprobador_final_id = await service.get_aprobador_final_id(conn)
        puede_modal_final = (
            accion in {"aprobar-final", "rechazar-final"}
            and bom["estatus"] == "EN_REVISION_FINAL"
            and aprobador_final_id
            and str(context.get("user_db_id")) == str(aprobador_final_id)
        )
        if not puede_modal_final:
            return _toast_response(
                request,
                "Dirección solo puede aprobar o rechazar cuando el BOM llegue a revisión final.",
                "error",
                "Acción no disponible",
            )

    catalogos = await service.get_catalogos(conn)
    acciones_con_stop_costos = {
        "enviar-revision", "aprobar-ing", "enviar-obra",
        "aprobar-obra", "aprobar-const", "enviar-final", "aprobar-final",
    }
    items_sin_costo = (
        await service.get_items_sin_costo(conn, id_bom)
        if accion in acciones_con_stop_costos else []
    )

    return templates.TemplateResponse(request, "bom/partials/modal_aprobar.html", {"bom": bom,
        "accion": accion,
        "catalogos": catalogos,
        "items_sin_costo": items_sin_costo,
    })


@router.post("/{id_bom}/notificar-costos-pendientes", include_in_schema=False)
async def notificar_costos_pendientes(
    request: Request,
    id_bom: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(["ingenieria", "construccion"], "viewer", allow_org_roles={"director"}),
):
    """Notifica a Compras los items del BOM que siguen sin presupuesto base."""
    user_id = context.get("user_db_id")
    try:
        resultado = await service.notificar_items_sin_costo_compras(conn, id_bom, user_id)
        return _toast_response(
            request,
            (
                f"Notificacion enviada a Compras con {resultado['items_sin_costo']} "
                f"item(s) sin presupuesto base."
            ),
            "success",
            "Compras notificado",
        )
    except ValueError as e:
        return _toast_response(request, str(e), "error", "Error")
    except asyncpg.PostgresError:
        logger.exception("Error de BD al notificar items BOM sin costo")
        return _toast_response(request, "Error interno al notificar a Compras", "error", "Error")


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
    _=require_any_module_access(["ingenieria", "construccion"], "editor"),
):
    """Asigna grupos BOM (AC/DC/CM/OC/TE) a un item."""
    form = await request.form()
    user_id = context.get("user_db_id")

    try:
        grupo_ids = _parse_grupo_ids(form)
        area_editor = _get_area_editor(context)
        item = await service.get_item(conn, id_item)
        bom = await service.get_bom(conn, item['id_bom'])
        if service.requiere_propuesta_construccion(bom, area_editor):
            await service.registrar_propuesta_auto(
                conn,
                bom["id_bom"],
                user_id,
                context,
                "Solicitud de Construccion para ajustar grupos",
                [{
                    "accion": "EDITAR",
                    "id_item": id_item,
                    "datos": {},
                    "grupo_ids": grupo_ids,
                }],
            )
            return _toast_response(
                request,
                "Propuesta enviada a revision de Ingenieria",
                "success",
                "Propuesta registrada",
            )
        await service.set_item_grupos(conn, id_item, user_id, grupo_ids, area_editor)

        item['grupos'], item['grupos_operativos'] = await service.get_item_grupos(conn, id_item)
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
    _=require_any_module_access(["construccion"], "editor"),
):
    form = await request.form()
    user_id = context.get("user_db_id")
    user_role = context.get("role")
    rol_org = context.get("rol_organizacional")
    comentarios = form.get("comentarios", "").strip() or None
    try:
        bom = await service.aprobar_revision_obra(conn, id_bom, user_id, user_role, rol_org, comentarios)
        return templates.TemplateResponse(request, "shared/toast.html", {
            "message": "BOM aprobado por Obra y enviado a Construccion",
            "type": "success",
            "redirect_url": f"/bom/{bom['id_proyecto']}/ui",
        })
    except ValueError as e:
        return templates.TemplateResponse(request, "shared/toast.html", {"message": str(e), "type": "error"})
    except asyncpg.PostgresError:
        logger.exception("Error de BD en aprobacion obra BOM")
        return templates.TemplateResponse(request, "shared/toast.html", {"message": "Error interno", "type": "error"})


@router.post("/{id_bom}/rechazar-obra", include_in_schema=False)
async def rechazar_obra(
    request: Request,
    id_bom: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(["construccion"], "editor"),
):
    form = await request.form()
    user_id = context.get("user_db_id")
    user_role = context.get("role")
    rol_org = context.get("rol_organizacional")
    comentarios = form.get("comentarios", "").strip() or None
    try:
        bom = await service.rechazar_obra(conn, id_bom, user_id, user_role, rol_org, comentarios)
        return templates.TemplateResponse(request, "shared/toast.html", {
            "message": "BOM devuelto a borrador para correccion de Disenio.",
            "type": "warning",
            "redirect_url": f"/bom/{bom['id_proyecto']}/ui",
        })
    except ValueError as e:
        return templates.TemplateResponse(request, "shared/toast.html", {"message": str(e), "type": "error"})
    except asyncpg.PostgresError:
        logger.exception("Error de BD en rechazo obra BOM")
        return templates.TemplateResponse(request, "shared/toast.html", {"message": "Error interno", "type": "error"})


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
    _=require_any_module_access(["construccion"], "editor"),
):
    """Envia BOM aprobado por construccion al aprobador final."""
    user_id = context.get("user_db_id")
    user_role = context.get("role")
    rol_org = context.get("rol_organizacional")
    try:
        bom = await service.enviar_revision_final(conn, id_bom, user_id, user_role, rol_org)
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
    _=require_any_module_access(["ingenieria", "construccion"], "viewer", allow_org_roles={"director"}),
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
    _=require_any_module_access(["ingenieria", "construccion"], "viewer", allow_org_roles={"director"}),
):
    """Rechazo por aprobador final. Vuelve a BORRADOR."""
    form = await request.form()
    user_id = context.get("user_db_id")
    comentarios = form.get("comentarios", "").strip() or None
    try:
        bom = await service.rechazar_final(conn, id_bom, user_id, comentarios)
        return templates.TemplateResponse(request, "shared/toast.html", {"message": "BOM devuelto a borrador por Direccion.",
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
    _=require_any_module_access(["ingenieria", "compras"]),
):
    """Descarga Excel del BOM del proyecto."""
    bom = await service.get_bom_proyecto(conn, id_proyecto)
    if not bom:
        raise HTTPException(status_code=404, detail="No existe BOM para este proyecto")

    excel_bytes = await service.export_to_excel(conn, bom['id_bom'])

    timestamp = now_mx().strftime("%Y%m%d_%H%M%S")
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
    _=require_any_module_access(["ingenieria", "compras"]),
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
    es_aprobador = (
        role == "ADMIN"
        or module_roles.get("ingenieria") in ("editor", "admin")
        or module_roles.get("construccion") in ("editor", "admin")
    )

    cotizaciones = await service.listar_cotizaciones(conn, id_bom)
    items = await service.get_items(conn, id_bom)
    items_disponibles = [i for i in items if _item_disponible_cotizacion(i)]

    return templates.TemplateResponse(
        request, "bom/partials/cotizaciones.html",
        {
            **_cotizacion_ctx(request, cotizaciones, bom, es_compras_editor),
            "items_disponibles": items_disponibles,
            "es_aprobador": es_aprobador,
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
            subtotal_externo=float(subtotal_externo) if subtotal_externo else None
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Retornar tab actualizado
    bom = await service.db.get_bom_by_id(conn, id_bom)
    cotizaciones = await service.listar_cotizaciones(conn, id_bom)
    items = await service.get_items(conn, id_bom)
    items_disponibles = [i for i in items if _item_disponible_cotizacion(i)]

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


@router.post("/{id_bom}/rfq-rapido", include_in_schema=False)
async def crear_rfq_rapido(
    request: Request,
    id_bom: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("compras"),
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

    items_bd = await service.db.get_items_by_ids(conn, item_ids)
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

    bom = await service.db.get_bom_by_id(conn, id_bom)
    cotizaciones = await service.listar_cotizaciones(conn, id_bom)
    items = await service.get_items(conn, id_bom)
    items_disponibles = [
        i for i in items
        if _item_disponible_cotizacion(i)
    ]
    role = context.get("role")
    module_roles = context.get("module_roles", {})
    es_compras_editor = role == "ADMIN" or module_roles.get("compras") in ("editor", "admin")

    return templates.TemplateResponse(
        request, "bom/partials/cotizaciones.html",
        {
            **_cotizacion_ctx(request, cotizaciones, bom, es_compras_editor),
            "items_disponibles": items_disponibles,
            "rfq_creado": True,
            "rfq_items_count": len(items_data),
        }
    )


@router.post("/cotizaciones/{cotizacion_id}/solicitar-aclaracion", include_in_schema=False)
async def solicitar_aclaracion(
    request: Request,
    cotizacion_id: UUID,
    motivo: str = Form(...),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(["ingenieria", "construccion"]),
):
    """Devuelve una cotización a BORRADOR con motivo de aclaración."""
    user_id = context.get("user_db_id")
    try:
        await service.solicitar_aclaracion_cotizacion(conn, cotizacion_id, user_id, motivo)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    cotizacion = await service.db.get_cotizacion_by_id(conn, cotizacion_id)
    bom = await service.db.get_bom_by_id(conn, cotizacion['bom_id'])
    cotizaciones = await service.listar_cotizaciones(conn, cotizacion['bom_id'])
    items = await service.get_items(conn, cotizacion['bom_id'])
    items_disponibles = [i for i in items if _item_disponible_cotizacion(i)]

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


@router.get("/{id_bom}/cotizaciones/comparativa", include_in_schema=False)
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
        rfq_items = await service.db.get_items_cotizacion(conn, rfq['id'])
        resp_items = {}
        for resp in responses:
            resp_items[str(resp['id'])] = await service.db.get_items_cotizacion(conn, resp['id'])
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


@router.post("/cotizaciones/{cotizacion_id}/bulk-asignar", include_in_schema=False)
async def bulk_asignar_items(
    request: Request,
    cotizacion_id: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("compras"),
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
    items_disponibles = [i for i in items if _item_disponible_cotizacion(i)]

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
    items_disponibles = [i for i in items if _item_disponible_cotizacion(i)]

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


@router.post("/cotizaciones/{cotizacion_id}/pdf", include_in_schema=False)
async def subir_pdf_cotizacion(
    request: Request,
    cotizacion_id: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("compras"),
):
    """Sube PDF de cotización (URL). Actualiza estatus a RECIBIDA."""
    form = await request.form()
    pdf_url = form.get("pdf_url", "").strip()
    if not pdf_url:
        raise HTTPException(status_code=400, detail="URL del PDF es requerida")
    try:
        await service.db.actualizar_pdf_cotizacion(conn, cotizacion_id, pdf_url)
    except asyncpg.PostgresError:
        raise HTTPException(status_code=500, detail="Error al actualizar PDF")

    cotizacion = await service.db.get_cotizacion_by_id(conn, cotizacion_id)
    if not cotizacion:
        raise HTTPException(status_code=404, detail="Cotización no encontrada")
    bom = await service.db.get_bom_by_id(conn, cotizacion['bom_id'])
    cotizaciones = await service.listar_cotizaciones(conn, cotizacion['bom_id'])
    items = await service.get_items(conn, cotizacion['bom_id'])
    items_disponibles = [i for i in items if _item_disponible_cotizacion(i)]

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


@router.get("/{id_bom}/autorizaciones", include_in_schema=False)
async def get_autorizaciones_tab(
    request: Request,
    id_bom: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(["ingenieria", "construccion", "compras", "finanzas"], allow_org_roles={"director"}),
):
    bom = await service.db.get_bom_by_id(conn, id_bom)  # autorizaciones tab
    if not bom:
        raise HTTPException(status_code=404, detail="BOM no encontrado")
    autorizaciones = await service.listar_autorizaciones(conn, id_bom)
    return templates.TemplateResponse(
        request, "bom/partials/autorizaciones.html",
        _autorizacion_ctx(request, autorizaciones, bom, context),
    )


@router.get("/{id_bom}/resumen-compra", include_in_schema=False)
async def get_resumen_compra_tab(
    request: Request,
    id_bom: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(["ingenieria", "construccion", "compras", "finanzas"], allow_org_roles={"director"}),
):
    """Tab Resumen de compra — comparativo Presupuesto vs Facturado vs Pagado, lazy HTMX."""
    bom = await service.db.get_bom_by_id(conn, id_bom)
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


@router.get("/autorizaciones/{autorizacion_id}/conciliacion", include_in_schema=False)
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


@router.post(
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


@router.post("/autorizaciones/{autorizacion_id}/aprobar-obra", include_in_schema=False)
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


# ========================================
# ADMIN
# ========================================

@router.post("/admin/aprobador-final", include_in_schema=False)
async def set_aprobador_final(
    request: Request,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_role("ADMIN"),
):
    """Configura el usuario aprobador final del BOM. Solo ADMIN."""
    form = await request.form()
    user_id_raw = form.get("user_id", "").strip()
    try:
        user_id = UUID(user_id_raw) if user_id_raw else None
        await service.configurar_aprobador_final(conn, user_id)
        message = "Aprobador final configurado" if user_id else "Aprobador final sin configurar"
        return templates.TemplateResponse(request, "shared/toast.html", {"message": message, "type": "success"
        })
    except ValueError as e:
        return templates.TemplateResponse(request, "shared/toast.html", {
            "message": str(e),
            "type": "error",
        })
    except asyncpg.PostgresError:
        raise HTTPException(status_code=500, detail="Error interno")
