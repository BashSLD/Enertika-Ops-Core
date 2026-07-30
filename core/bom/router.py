"""
Router compartido de BOM (Lista de Materiales).
Endpoints HTMX para CRUD de items, workflow de aprobaciones y exportacion Excel.
"""

from fastapi import APIRouter, Depends, Request, HTTPException, Form, Query
from fastapi.templating import Jinja2Templates
from fastapi.responses import Response
from uuid import UUID
from typing import Optional
import json
import asyncpg
import logging

from core.database import get_db_connection
from core.security import get_current_user_context
from core.permissions import require_module_access, require_manager_access, require_role, require_any_module_access, require_authenticated_session
from core.config import settings
from core.timezone import now_mx
from core.materials.normalizer import normalizar_descripcion
from modules.shared.utils import is_htmx
from .compras_service import ESTATUS_COTIZABLE
from .service import (
    BomService,
    get_bom_service,
    CAMPOS_CONSTRUCCION_BASE,
)

_ESTATUS_FASE_COMPRAS = {e.value for e in ESTATUS_COTIZABLE}

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
    fase_compras = bool(bom) and bom.get("estatus") in _ESTATUS_FASE_COMPRAS

    ctx = {
        "bom": bom,
        "fase_compras": fase_compras,
        "area_editor": area_editor,
        "es_ing_editor": es_ing_editor,
        "es_ing_manager": es_ing_manager,
        "es_const_manager": es_const_manager,
        "es_const_editor": es_const_editor,
        "es_compras_editor": es_compras_editor,
        "role": role,
        "module_roles": module_roles,
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
    redirect_url: Optional[str] = None,
    close_modal: bool = False,
    status_code: int = 200,
) -> Response:
    """Retorna toast OOB sin reemplazar el contenido HTMX actual."""
    ctx = {"message": message, "type": type_, "title": title}
    if redirect_url:
        ctx["redirect_url"] = redirect_url
    if close_modal:
        ctx["close_modal"] = True
    return templates.TemplateResponse(
        request,
        "shared/toast.html",
        ctx,
        status_code=status_code,
        headers={"HX-Reswap": "none", "HX-Push-Url": "false"},
    )


def _redirigir_a_bom(id_proyecto: UUID) -> Response:
    """Redirige el navegador al BOM del proyecto (recarga completa via HX-Redirect).

    Usado cuando el panel FV ya esta configurado (o se acaba de guardar): evita
    llamar a bom_ui() directamente (que se saltaria sus propios Depends()) y evita
    reconstruir a mano la respuesta para cerrar el modal de origen — el navegador
    hace una navegacion nueva, entra por el routing normal, y el modal desaparece
    junto con la pagina anterior.
    """
    return Response(status_code=200, headers={"HX-Redirect": f"/bom/{id_proyecto}/ui"})


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
    _=require_authenticated_session(),
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

    proyecto = await service.get_proyecto_info(conn, id_proyecto)
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
        versiones = await service.get_all_bom_versions(conn, id_proyecto)
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

    template = "bom/partials/content.html" if is_htmx(request) else "bom/dashboard.html"
    return templates.TemplateResponse(request, template, ctx)


# ========================================
# GATE DE ACCESO (panel FV del proyecto)
# ========================================

@router.get("/{id_proyecto}/acceso", include_in_schema=False)
async def bom_acceso(
    request: Request,
    id_proyecto: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(
        ["ingenieria", "construccion", "compras", "finanzas"], "viewer", allow_org_roles={"director"}
    ),
):
    """Gate de entrada al BOM: si ya existe un BOM para el proyecto, exige capturar
    el panel FV antes de continuar; si aun no existe BOM, lo sugiere pero permite
    continuar sin configurarlo."""
    proyecto = await service.get_proyecto_info(conn, id_proyecto)
    if not proyecto:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    if await service.paneles_configurados(conn, id_proyecto):
        return _redirigir_a_bom(id_proyecto)

    tiene_bom = await service.get_bom_proyecto(conn, id_proyecto) is not None
    user_id = context.get("user_db_id")
    puede_configurar, jefe_label = await service.get_permiso_configurar_paneles(conn, id_proyecto, user_id)
    return templates.TemplateResponse(request, "bom/partials/modal_gate_paneles.html", {
        "id_proyecto": id_proyecto,
        "bloqueante": tiene_bom,
        "puede_configurar": puede_configurar,
        "jefe_label": jefe_label,
    })


@router.get("/{id_proyecto}/paneles-modal", include_in_schema=False)
async def paneles_modal(
    request: Request,
    id_proyecto: UUID,
    origen: Optional[str] = Query(None),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(
        ["ingenieria", "construccion", "compras", "finanzas"], "viewer", allow_org_roles={"director"}
    ),
):
    """Modal de captura/edicion del panel FV del proyecto."""
    proyecto = await service.get_proyecto_info(conn, id_proyecto)
    if not proyecto:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    catalogo = await service.get_paneles_fv_activos(conn)
    paneles_actuales = await service.get_paneles_proyecto(conn, id_proyecto)

    # Si un panel ya capturado fue desactivado despues en el catalogo, se agrega
    # igual a las opciones (marcado como inactivo) para que el <select> no quede
    # sin coincidencia y el usuario vea que modelo tiene realmente capturado.
    catalogo_ids = {c["id"] for c in catalogo}
    for p in paneles_actuales:
        if p["id_panel"] not in catalogo_ids:
            catalogo.append({
                "id": p["id_panel"], "marca": p["marca"], "modelo": p["modelo"],
                "potencia_w": p["potencia_w"], "inactivo": True,
            })
            catalogo_ids.add(p["id_panel"])

    user_id = context.get("user_db_id")
    puede_configurar, jefe_label = await service.get_permiso_configurar_paneles(conn, id_proyecto, user_id)

    return templates.TemplateResponse(request, "bom/partials/modal_paneles_fv.html", {
        "id_proyecto": id_proyecto,
        "proyecto": proyecto,
        "catalogo": catalogo,
        "paneles_actuales": paneles_actuales,
        "puede_configurar": puede_configurar,
        "jefe_label": jefe_label,
        "origen": origen,
    })


@router.post("/{id_proyecto}/paneles", include_in_schema=False)
async def guardar_paneles(
    request: Request,
    id_proyecto: UUID,
    id_panel: list[int] = Form(default=[]),
    cantidad: list[int] = Form(default=[]),
    origen: Optional[str] = Form(None),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(
        ["ingenieria", "construccion", "compras", "finanzas"], "viewer", allow_org_roles={"director"}
    ),
):
    """Guarda el set de paneles FV del proyecto. Si se abrio desde el gate de BOM
    (origen=bom) navega directo al BOM; si se abrio desde su propio boton (MFV
    independiente), solo cierra el modal."""
    if len(id_panel) != len(cantidad):
        return _toast_response(
            request, "Datos de paneles incompletos, intenta de nuevo", "error", status_code=400
        )
    if len(set(id_panel)) != len(id_panel):
        return _toast_response(
            request, "No repitas el mismo modelo de panel, ajusta la cantidad en una sola fila",
            "error", status_code=400,
        )

    user_id = context.get("user_db_id")
    paneles = [{"id_panel": p, "cantidad": c} for p, c in zip(id_panel, cantidad)]

    try:
        await service.guardar_paneles_proyecto(conn, id_proyecto, paneles, user_id)
    except ValueError as e:
        return _toast_response(request, str(e), "error", status_code=400)
    except asyncpg.PostgresError:
        logger.exception("Error de BD al guardar paneles FV del proyecto")
        return _toast_response(request, "Error interno al guardar el panel FV", "error", status_code=500)

    if origen == "bom":
        return _toast_response(
            request, "Panel FV guardado correctamente", "success",
            redirect_url=f"/bom/{id_proyecto}/ui",
        )
    return _toast_response(
        request, "Panel FV guardado correctamente", "success",
        close_modal=True,
    )


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

        return _toast_response(
            request, f"BOM v{bom['version']} creado exitosamente", "success",
            redirect_url=f"/bom/{id_proyecto}/ui",
        )

    except ValueError as e:
        return _toast_response(request, str(e), "error", status_code=400)
    except asyncpg.PostgresError:
        logger.exception("Error de BD al crear BOM")
        return _toast_response(request, "Error interno al crear el BOM", "error", status_code=500)


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
    _=require_authenticated_session(),
):
    """Agrega un item al BOM. Permite Ingenieria y Construccion."""
    form = await request.form()
    user_id = context.get("user_db_id")
    area_editor = _get_area_editor(context)

    if area_editor not in ("ingenieria", "construccion"):
        return _toast_response(
            request,
            "Solo Ingenieria y Construccion pueden agregar items al BOM. Compras solo puede editar proveedor y precio de items existentes.",
            "error",
        )

    bom = await service.get_bom_proyecto(conn, id_proyecto)
    if not bom:
        return _toast_response(request, "No existe un BOM para este proyecto", "error")

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

        if service.item_sin_costo(item):
            bulk_toast = {
                "message": service.mensaje_item_sin_costo(),
                "type": "warning",
                "title": "Presupuesto pendiente",
            }
        else:
            bulk_toast = {
                "message": service.mensaje_item_agregado(item),
                "type": "success",
                "title": "Item agregado",
            }

        ctx = _build_bom_context(
            request, context, bom,
            items=items, estadisticas=estadisticas,
            bulk_toast=bulk_toast,
            puede_gestionar_bom_ingenieria=await service.puede_crear_o_retomar_bom(
                conn, bom['id_proyecto'], user_id
            ),
        )
        return templates.TemplateResponse(request, "bom/partials/tabla_items.html", ctx)

    except ValueError as e:
        return _toast_response(request, str(e), "error", status_code=400)
    except asyncpg.PostgresError:
        logger.exception("Error de BD al agregar item BOM")
        return _toast_response(request, "Error interno al agregar el item", "error", status_code=500)


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
        return _toast_response(
            request, "Sin permisos para editar items del BOM", "error",
            status_code=403,
        )

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
        return _toast_response(request, str(e), "error", status_code=400)
    except asyncpg.PostgresError:
        logger.exception("Error de BD al editar item BOM")
        return _toast_response(request, "Error interno al editar el item", "error", status_code=500)


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
        return _toast_response(request, "Error interno al editar los items", "error", "Error", status_code=500)


@router.delete("/items/{id_item}", include_in_schema=False)
async def eliminar_item(
    request: Request,
    id_item: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_authenticated_session(),
):
    """Elimina (soft) un item del BOM. Permite Ingenieria y Construccion."""
    user_id = context.get("user_db_id")
    area_editor = _get_area_editor(context)

    if area_editor not in ("ingenieria", "construccion"):
        return _toast_response(request, "No tienes permisos para eliminar items", "error")

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
        return _toast_response(request, str(e), "error", status_code=400)
    except asyncpg.PostgresError:
        logger.exception("Error de BD al eliminar item BOM")
        return _toast_response(request, "Error interno al eliminar el item", "error", status_code=500)


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
        await service.restaurar_item(conn, id_item)

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
        return _toast_response(request, str(e), "error", status_code=400)
    except asyncpg.PostgresError:
        logger.exception("Error de BD al restaurar item BOM")
        return _toast_response(request, "Error interno al restaurar el item", "error", status_code=500)


@router.post("/{id_bom}/refrescar-costos", include_in_schema=False)
async def refrescar_costos_catalogo(
    request: Request,
    id_bom: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_module_access("ingenieria", "editor"),
):
    """Ingenieria sincroniza precio_unitario de items sin costo desde el catalogo interno."""
    user_id = context.get("user_db_id")
    try:
        resultado = await service.refrescar_costos_catalogo(conn, id_bom, user_id)
        bom = resultado["bom"]
        items = await service.get_items(conn, id_bom)

        n = resultado["sincronizados"]
        pendientes_sin_costo = [i for i in items if service.item_sin_costo(i)]
        if n and not pendientes_sin_costo:
            toast = {
                "message": f"{n} item(s) actualizados desde el catalogo. Ya puedes enviar el BOM a revision.",
                "type": "success", "title": "Costos refrescados",
            }
        elif n:
            toast = {
                "message": f"{n} item(s) actualizados. Aun quedan {len(pendientes_sin_costo)} sin costo en el catalogo interno.",
                "type": "warning", "title": "Costos refrescados",
            }
        else:
            toast = {
                "message": "Ningun item tiene un precio disponible en el catalogo interno todavia.",
                "type": "warning", "title": "Sin cambios",
            }

        ctx = _build_bom_context(
            request, context, bom,
            items=items,
            bulk_toast=toast,
            estadisticas=await service.get_estadisticas(conn, id_bom),
            oob_estadisticas=True,
            puede_gestionar_bom_ingenieria=await service.puede_crear_o_retomar_bom(
                conn, bom['id_proyecto'], user_id
            ),
        )
        return templates.TemplateResponse(request, "bom/partials/tabla_items.html", ctx)
    except ValueError as e:
        return _toast_response(request, str(e), "error", "Error")
    except asyncpg.PostgresError:
        logger.exception("Error de BD al refrescar costos de catalogo en BOM")
        return _toast_response(request, "Error interno al refrescar costos", "error", "Error", status_code=500)


@router.get("/items/{id_item}/modal", include_in_schema=False)
async def get_modal_editar_item(
    request: Request,
    id_item: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(["ingenieria", "construccion", "compras", "finanzas"], "viewer", allow_org_roles={"director"}),
):
    """Modal para editar un item."""
    item = await service.get_item(conn, id_item)
    item["grupos"], item["grupos_operativos"] = await service.get_item_grupos(conn, id_item)
    bom = await service.get_bom(conn, item['id_bom'])
    catalogos = await service.get_catalogos(conn)

    # id_item puede no estar en la lista si el item esta inactivo (eliminado por
    # otro usuario mientras este modal estaba abierto): sin navegacion en ese caso.
    ids_ordenados = await service.db.get_item_ids_by_bom(conn, item['id_bom'])
    idx = ids_ordenados.index(id_item) if id_item in ids_ordenados else None
    prev_id = ids_ordenados[idx - 1] if idx is not None and idx > 0 else None
    next_id = ids_ordenados[idx + 1] if idx is not None and idx < len(ids_ordenados) - 1 else None

    ctx = _build_bom_context(
        request, context, bom,
        item=item, catalogos=catalogos,
        prev_id=prev_id, next_id=next_id,
        posicion_item=(idx + 1) if idx is not None else None,
        total_items=len(ids_ordenados),
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
        return _toast_response(request, "Error interno al registrar la adenda", "error", "Error", status_code=500)


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
        return _toast_response(request, "Error interno al registrar el reemplazo", "error", "Error", status_code=500)


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
        return _toast_response(request, "Error interno al registrar la adenda", "error", "Error", status_code=500)


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
        return _toast_response(request, "Error interno al aprobar la adenda", "error", "Error", status_code=500)


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
        return _toast_response(request, "Error interno al aprobar la adenda", "error", "Error", status_code=500)


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
        return _toast_response(request, "Error interno al rechazar la adenda", "error", "Error", status_code=500)


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
        return _toast_response(request, "Error interno al cancelar la adenda", "error", "Error", status_code=500)


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
        return _toast_response(request, "Error interno al comentar la adenda", "error", "Error", status_code=500)


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
        return _toast_response(request, "Error interno al crear la propuesta", "error", "Error", status_code=500)


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
        return _toast_response(request, "Error interno al aprobar la propuesta", "error", "Error", status_code=500)


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
        return _toast_response(request, "Error interno al rechazar la propuesta", "error", "Error", status_code=500)


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
        resultado_busqueda = await service.buscar_materiales_para_bom(
            conn, q, query_norm=normalizar_descripcion(q), limite=limit, offset=offset
        )
    else:
        # Sin query: mostrar materiales recientes como dropdown inicial
        resultado_busqueda = await service.get_materiales_recientes(
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

        return _toast_response(
            request, "BOM enviado a revision de ingenieria", "success",
            redirect_url=f"/bom/{bom['id_proyecto']}/ui",
        )

    except ValueError as e:
        return _toast_response(request, str(e), "error", status_code=400)
    except asyncpg.PostgresError:
        logger.exception("Error de BD al enviar BOM a revision")
        return _toast_response(request, "Error interno al enviar a revision", "error", status_code=500)


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
        return _toast_response(
            request, "BOM aprobado por ingenieria", "success",
            redirect_url=f"/bom/{bom['id_proyecto']}/ui",
        )
    except ValueError as e:
        return _toast_response(request, str(e), "error", status_code=400)
    except asyncpg.PostgresError:
        logger.exception("Error de BD al aprobar BOM")
        return _toast_response(request, "Error interno al aprobar", "error", status_code=500)


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
        return _toast_response(
            request, "BOM rechazado. Se devolvio a borrador.", "warning",
            redirect_url=f"/bom/{bom['id_proyecto']}/ui",
        )
    except ValueError as e:
        return _toast_response(request, str(e), "error", status_code=400)
    except asyncpg.PostgresError:
        logger.exception("Error de BD al rechazar BOM")
        return _toast_response(request, "Error interno al rechazar", "error", status_code=500)


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
        return _toast_response(
            request, "BOM aprobado por construccion. Listo para compras.", "success",
            redirect_url=f"/bom/{bom['id_proyecto']}/ui",
        )
    except ValueError as e:
        return _toast_response(request, str(e), "error", status_code=400)
    except asyncpg.PostgresError:
        logger.exception("Error de BD al aprobar BOM por construccion")
        return _toast_response(request, "Error interno al aprobar", "error", status_code=500)


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
        return _toast_response(
            request, message, "warning",
            redirect_url=f"/bom/{bom['id_proyecto']}/ui",
        )
    except ValueError as e:
        return _toast_response(request, str(e), "error", status_code=400)
    except asyncpg.PostgresError:
        logger.exception("Error de BD al rechazar BOM por construccion")
        return _toast_response(request, "Error interno al rechazar", "error", status_code=500)


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

        return _toast_response(
            request, "BOM devuelto a borrador para correccion", "warning",
            redirect_url=f"/bom/{bom['id_proyecto']}/ui",
        )

    except ValueError as e:
        return _toast_response(request, str(e), "error", status_code=400)
    except asyncpg.PostgresError:
        logger.exception("Error de BD al devolver BOM a borrador")
        return _toast_response(request, "Error interno al devolver a borrador", "error", status_code=500)


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

        return _toast_response(
            request, "BOM cancelado", "warning",
            redirect_url=f"/bom/{bom['id_proyecto']}/ui",
        )

    except ValueError as e:
        return _toast_response(request, str(e), "error", status_code=400)
    except asyncpg.PostgresError:
        logger.exception("Error de BD al cancelar BOM")
        return _toast_response(request, "Error interno al cancelar el BOM", "error", status_code=500)


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

        return _toast_response(
            request, f"Nueva version v{nuevo_bom['version']} creada en borrador", "success",
            redirect_url=f"/bom/{nuevo_bom['id_proyecto']}/ui",
        )

    except ValueError as e:
        return _toast_response(request, str(e), "error", status_code=400)
    except asyncpg.PostgresError:
        logger.exception("Error de BD al solicitar modificacion BOM")
        return _toast_response(request, "Error interno al solicitar modificacion", "error", status_code=500)


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
    _=require_any_module_access(["ingenieria", "construccion", "compras", "finanzas"], allow_org_roles={"director"}),
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
    _=require_any_module_access(["ingenieria", "construccion", "compras", "finanzas"], allow_org_roles={"director"}),
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
        canales = []
        if resultado.get("sse"):
            canales.append("aviso interno")
        if resultado.get("correo_enviado"):
            canales.append("correo")
        canal_txt = " y ".join(canales) if canales else "Compras"
        return _toast_response(
            request,
            (
                f"Notificado por {canal_txt} con {resultado['items_sin_costo']} "
                f"item(s) sin presupuesto base."
            ),
            "success",
            "Compras notificado",
        )
    except ValueError as e:
        return _toast_response(request, str(e), "error", "Error")
    except asyncpg.PostgresError:
        logger.exception("Error de BD al notificar items BOM sin costo")
        return _toast_response(request, "Error interno al notificar a Compras", "error", "Error", status_code=500)


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
        return _toast_response(request, str(e), "error", status_code=400)
    except asyncpg.PostgresError:
        logger.exception("Error de BD al asignar grupos BOM")
        return _toast_response(request, "Error interno al asignar grupos", "error", status_code=500)


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
    usuarios = await service.get_usuarios_por_area(conn, 'ingenieria', solo_jefes=False)
    const_usuarios = await service.get_usuarios_por_area(conn, 'construccion', solo_jefes=False)
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
        return _toast_response(request, "Suplencia configurada exitosamente", "success")
    except ValueError as e:
        return _toast_response(request, str(e), "error", status_code=400)
    except asyncpg.PostgresError:
        logger.exception("Error de BD al configurar suplencia")
        return _toast_response(request, "Error interno al configurar suplencia", "error", status_code=500)


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
        return _toast_response(request, "Suplencia eliminada", "success")
    except asyncpg.PostgresError:
        logger.exception("Error de BD al eliminar suplencia")
        return _toast_response(request, "Error interno al eliminar suplencia", "error", status_code=500)


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
        return _toast_response(
            request, "BOM enviado a revision de Obra", "success",
            redirect_url=f"/bom/{bom['id_proyecto']}/ui",
        )
    except ValueError as e:
        return _toast_response(request, str(e), "error", status_code=400)
    except asyncpg.PostgresError:
        logger.exception("Error de BD al enviar BOM a obra")
        return _toast_response(request, "Error interno", "error", status_code=500)


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
        return _toast_response(
            request, "BOM aprobado por Obra y enviado a Construccion", "success",
            redirect_url=f"/bom/{bom['id_proyecto']}/ui",
        )
    except ValueError as e:
        return _toast_response(request, str(e), "error", status_code=400)
    except asyncpg.PostgresError:
        logger.exception("Error de BD en aprobacion obra BOM")
        return _toast_response(request, "Error interno", "error", status_code=500)


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
        return _toast_response(
            request, "BOM devuelto a borrador para correccion de Disenio.", "warning",
            redirect_url=f"/bom/{bom['id_proyecto']}/ui",
        )
    except ValueError as e:
        return _toast_response(request, str(e), "error", status_code=400)
    except asyncpg.PostgresError:
        logger.exception("Error de BD en rechazo obra BOM")
        return _toast_response(request, "Error interno", "error", status_code=500)


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
        return _toast_response(
            request, "BOM enviado al aprobador final", "success",
            redirect_url=f"/bom/{bom['id_proyecto']}/ui",
        )
    except ValueError as e:
        return _toast_response(request, str(e), "error", status_code=400)
    except asyncpg.PostgresError:
        logger.exception("Error de BD al enviar BOM a revision final")
        return _toast_response(request, "Error interno", "error", status_code=500)


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
        return _toast_response(
            request, "BOM aprobado de forma definitiva", "success",
            redirect_url=f"/bom/{bom['id_proyecto']}/ui",
        )
    except ValueError as e:
        return _toast_response(request, str(e), "error", status_code=400)
    except asyncpg.PostgresError:
        logger.exception("Error de BD en aprobacion final BOM")
        return _toast_response(request, "Error interno", "error", status_code=500)


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
        return _toast_response(
            request, "BOM devuelto a borrador por Direccion.", "warning",
            redirect_url=f"/bom/{bom['id_proyecto']}/ui",
        )
    except ValueError as e:
        return _toast_response(request, str(e), "error", status_code=400)
    except asyncpg.PostgresError:
        logger.exception("Error de BD en rechazo final BOM")
        return _toast_response(request, "Error interno", "error", status_code=500)


# ========================================
# EXPORT EXCEL
# ========================================

@router.get("/{id_proyecto}/export-excel", include_in_schema=False)
async def export_excel(
    request: Request,
    id_proyecto: UUID,
    conn=Depends(get_db_connection),
    service: BomService = Depends(get_bom_service),
    _=require_any_module_access(["ingenieria", "construccion", "compras", "finanzas"], allow_org_roles={"director"}),
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
# COMPRAS (cotizaciones + autorizaciones)
# Rutas definidas en compras_router, incluido al final de este archivo.
# ========================================



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
        return _toast_response(request, message, "success")
    except ValueError as e:
        return _toast_response(request, str(e), "error", status_code=400)
    except asyncpg.PostgresError:
        raise HTTPException(status_code=500, detail="Error interno")


from .compras_router import compras_router
router.include_router(compras_router)
