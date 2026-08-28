# Archivo: core/materials/router.py
"""
Router compartido de Materiales.
Consulta, edicion de clasificacion, analisis de precios y exportacion Excel.
"""

from fastapi import APIRouter, Depends, Request, Query, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, Response
from typing import Annotated, Optional
from uuid import UUID
import asyncpg
import logging

from core.database import get_db_connection
from core.security import get_current_user_context
from core.permissions import (
    require_module_access,
    require_any_module_access,
    user_has_module_access,
    ROLE_HIERARCHY,
)
from core.config import settings
from core.timezone import now_mx
from modules.shared.utils import toast_error
from .service import MaterialsService, get_materials_service
from .schemas import MaterialFilter, MaterialInternoCreate, MaterialInternoFilter

logger = logging.getLogger("MaterialsRouter")

templates = Jinja2Templates(directory="templates")
templates.env.globals["DEBUG_MODE"] = settings.DEBUG_MODE

from core.jinja_filters import register_timezone_filters
register_timezone_filters(templates.env)

router = APIRouter(
    prefix="/materials",
    tags=["Materiales"],
)

# ========================================
# PERMISOS COMPARTIDOS
# ========================================

async def require_materials_view_access(
    context = Depends(get_current_user_context)
):
    """
    Permite acceso si el usuario tiene rol (viewer o superior)
    en alguno de los modulos operativos o compras.
    """
    # 1. Admin Global
    if context.get("role") == "ADMIN":
        return True
        
    module_roles = context.get("module_roles", {})
    
    # Lista de modulos permitidos (Solicitado por Usuario)
    ALLOWED_MODULES = ["compras", "ingenieria", "construccion", "oym"]
    
    has_access = False
    for mod in ALLOWED_MODULES:
        role = module_roles.get(mod)
        if role:
            # Validar nivel minimo viewer (que es el mas bajo, asi que cualquiera sirve)
            # Pero usamos ROLE_HIERARCHY por consistencia
            if ROLE_HIERARCHY.get(role, 0) >= ROLE_HIERARCHY.get("viewer", 1):
                has_access = True
                break
                
    if not has_access:
         raise HTTPException(
            status_code=403,
            detail=f"Requiere acceso a uno de: {', '.join(ALLOWED_MODULES)}"
        )

    return True


# Edicion del catalogo interno: compartida por compras e ingenieria (mas ADMIN global).
MATERIALS_EDIT_MODULES = ["compras", "ingenieria"]
require_materials_edit_access = require_any_module_access(MATERIALS_EDIT_MODULES, "editor")


def _can_edit_internos(context) -> bool:
    """True si el usuario puede crear/editar el catalogo interno:
    ADMIN global o editor+ en compras o ingenieria."""
    if context.get("role") == "ADMIN":
        return True
    return any(user_has_module_access(m, context, "editor") for m in MATERIALS_EDIT_MODULES)


def _puede_editar_costos_internos(context) -> bool:
    """True si el usuario tiene autoridad para fijar/editar precio_referencia y
    moneda del catalogo interno: ADMIN global o editor+ en compras. Tener editor
    en ingenieria (incluso ademas de otros roles) nunca es suficiente por si solo --
    la autoridad de costos requiere compras explicito, para que Ingenieria no evada
    el control registrando o alterando precios (ver QA 2026-08-17, seccion A)."""
    if context.get("role") == "ADMIN":
        return True
    return user_has_module_access("compras", context, "editor")

# ========================================
# UI PRINCIPAL
# ========================================

@router.api_route("/ui", methods=["GET", "HEAD"], include_in_schema=False)
async def get_materials_ui(
    request: Request,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    service: MaterialsService = Depends(get_materials_service),
    _=Depends(require_materials_view_access), # Acceso ampliado
):
    """Dashboard de materiales. Dual render HTMX."""
    catalogos = await service.get_catalogos(conn)
    filtros_dict = {}
    materiales, total = await service.get_materiales(conn, filtros=filtros_dict)
    estadisticas = await service.get_estadisticas(conn, filtros_dict)

    page = 1
    per_page = 50
    pages = (total + per_page - 1) // per_page if total > 0 else 1

    template_context = {
        "user_name": context.get("user_name"),
        "role": context.get("role"),
        "module_roles": context.get("module_roles", {}),
        "current_module_role": context.get("module_roles", {}).get("compras", "viewer"),
        "materiales": materiales,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": pages,
        "categorias": catalogos.get("categorias", []),
        "proveedores": catalogos.get("proveedores", []),
        "proyectos": catalogos.get("proyectos", []),
        "filtros": {},
        "estadisticas": estadisticas,
        "can_edit": _can_edit_internos(context),
    }

    if request.headers.get("hx-request") and not request.headers.get("hx-history-restore-request"):
        template = "materials/partials/content.html"
    else:
        template = "materials/dashboard.html"

    return templates.TemplateResponse(request, template, template_context)


# ========================================
# LISTADO FILTRADO (HTMX PARTIAL)
# ========================================

@router.get("/list", response_class=HTMLResponse)
async def get_materials_list(
    request: Request,
    filtros: Annotated[MaterialFilter, Query()],
    conn=Depends(get_db_connection),
    service: MaterialsService = Depends(get_materials_service),
    _=Depends(require_materials_view_access),
):
    """Tabla filtrada de materiales (partial HTMX)."""
    filtro_dict = filtros.model_dump(exclude_none=True)
    # Excluir page/per_page del dict de filtros para stats
    filtro_stats = {k: v for k, v in filtro_dict.items() if k not in ('page', 'per_page')}

    materiales, total = await service.get_materiales(
        conn, filtros=filtro_stats, page=filtros.page, per_page=filtros.per_page
    )
    pages = (total + filtros.per_page - 1) // filtros.per_page if total > 0 else 1
    catalogos = await service.get_catalogos(conn)
    estadisticas = await service.get_estadisticas(conn, filtro_stats)

    return templates.TemplateResponse(
        request, "materials/partials/tabla_materiales.html",
        {            "materiales": materiales,
            "total": total,
            "page": filtros.page,
            "per_page": filtros.per_page,
            "pages": pages,
            "categorias": catalogos.get("categorias", []),
            "estadisticas": estadisticas,
            "filtros": {
                "id_proveedor": str(filtros.id_proveedor) if filtros.id_proveedor else "",
                "id_categoria": filtros.id_categoria,
                "id_proyecto": str(filtros.id_proyecto) if filtros.id_proyecto else "",
                "fecha_inicio": filtros.fecha_inicio.isoformat() if filtros.fecha_inicio else "",
                "fecha_fin": filtros.fecha_fin.isoformat() if filtros.fecha_fin else "",
                "origen": filtros.origen or "",
                "q": filtros.q or "",
            },
        }
    )


# ========================================
# ANALISIS DE PRECIOS
# ========================================

@router.get("/{material_id}/precios", response_class=HTMLResponse)
async def get_material_precios(
    request: Request,
    material_id: UUID,
    conn=Depends(get_db_connection),
    service: MaterialsService = Depends(get_materials_service),
    _=Depends(require_materials_view_access),
):
    """Modal de analisis de precios por material."""
    material, precios, precios_sat = await service.get_material_precios(conn, material_id)
    if not material:
        raise HTTPException(status_code=404, detail="Material no encontrado")

    return templates.TemplateResponse(
        request, "materials/partials/modal_precios.html",
        {            "material": material,
            "precios": precios,
            "precios_sat": precios_sat,
        }
    )


# ========================================
# EDICION DE CLASIFICACION
# ========================================

@router.patch("/{material_id}", response_class=HTMLResponse)
async def update_material(
    request: Request,
    material_id: UUID,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    service: MaterialsService = Depends(get_materials_service),
    _=require_module_access("compras", "editor"),
):
    """Editar descripcion_interna y/o categoria de un material."""
    form = await request.form()
    updates = {}
    if "descripcion_interna" in form:
        val = form["descripcion_interna"]
        updates["descripcion_interna"] = val if val else None
    if "id_categoria" in form:
        val = form["id_categoria"]
        updates["id_categoria"] = int(val) if val else None

    if not updates:
        raise HTTPException(status_code=400, detail="Sin campos para actualizar")

    material = await service.update_material(conn, material_id, updates)
    if not material:
        raise HTTPException(status_code=404, detail="Material no encontrado o sin cambios")

    catalogos = await service.get_catalogos(conn)

    return templates.TemplateResponse(
        request, "materials/partials/row_material.html",
        {            "m": material,
            "categorias": catalogos.get("categorias", []),
            "current_module_role": context.get("module_roles", {}).get("compras", "viewer"),
            "role": context.get("role"),
        }
    )


# ========================================
# EXPORTACION EXCEL
# ========================================

@router.get("/export-excel")
async def export_materials_excel(
    request: Request,
    filtros: Annotated[MaterialFilter, Query()],
    conn=Depends(get_db_connection),
    service: MaterialsService = Depends(get_materials_service),
    _=Depends(require_materials_view_access),
):
    """Exporta materiales a Excel con filtros aplicados."""
    filtro_dict = filtros.model_dump(exclude_none=True)
    filtro_dict.pop('page', None)
    filtro_dict.pop('per_page', None)

    excel_bytes = await service.export_to_excel(conn, filtros=filtro_dict)

    timestamp = now_mx().strftime("%Y%m%d_%H%M%S")
    filename = f"materiales_{timestamp}.xlsx"

    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )


# ========================================
# BUSQUEDA FUZZY
# ========================================

@router.get("/similar", response_class=HTMLResponse)
async def buscar_materiales_similares(
    request: Request,
    q: str = Query(..., min_length=3, description="Texto de busqueda"),
    threshold: float = Query(0.3, ge=0.1, le=1.0),
    conn=Depends(get_db_connection),
    service: MaterialsService = Depends(get_materials_service),
    _=Depends(require_materials_view_access),
):
    """Busqueda fuzzy de materiales por descripcion con pg_trgm."""
    resultados = await service.buscar_materiales_similares(
        conn, q, threshold=threshold, limit=20
    )

    return templates.TemplateResponse(
        request, "materials/partials/similar_results.html",
        {            "resultados": resultados,
            "query": q,
        }
    )


@router.get("/similares-internos", response_class=HTMLResponse)
async def buscar_internos_similares(
    request: Request,
    q: str = Query(..., min_length=3, description="Texto de busqueda"),
    threshold: float = Query(0.3, ge=0.1, le=1.0),
    conn=Depends(get_db_connection),
    service: MaterialsService = Depends(get_materials_service),
    _=Depends(require_materials_view_access),
):
    """Homologacion/anti-duplicados: posibles coincidencias en el catalogo interno
    (tb_cat_materiales) antes de dar de alta un material nuevo. Distinto de /similar,
    que busca en el historial XML de proveedor, no en el catalogo."""
    resultados = await service.buscar_internos_similares(conn, q, threshold=threshold, limit=10)

    return templates.TemplateResponse(
        request, "materials/partials/similar_internos_results.html",
        {"resultados": resultados, "query": q}
    )


# ========================================
# CATALOGOS
# ========================================

@router.get("/catalogos")
async def get_catalogos(
    conn=Depends(get_db_connection),
    service: MaterialsService = Depends(get_materials_service),
    _=Depends(require_materials_view_access),
):
    """Catalogos para dropdowns de materiales."""
    return await service.get_catalogos(conn)


# ========================================
# CATALOGO INTERNO DE MATERIALES
# ========================================

@router.api_route("/internos/ui", methods=["GET", "HEAD"], include_in_schema=False)
async def get_internos_ui(
    request: Request,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    service: MaterialsService = Depends(get_materials_service),
    _=Depends(require_materials_view_access),
):
    internos, total = await service.get_internos(conn, {})
    per_page = 50
    ctx = {
        "user_name": context.get("user_name"),
        "role": context.get("role"),
        "module_roles": context.get("module_roles", {}),
        "can_edit": _can_edit_internos(context),
        "puede_editar_costos": _puede_editar_costos_internos(context),
        "internos": internos,
        "total": total,
        "page": 1,
        "per_page": per_page,
        "pages": max((total + per_page - 1) // per_page, 1),
        "estadisticas": await service.get_estadisticas_internos(conn),
        "categorias": (await service.get_catalogos(conn)).get("categorias", []),
        "unidades": await service.get_cat_unidades(conn),
        "filtros": {},
    }
    if request.headers.get("hx-request") and not request.headers.get("hx-history-restore-request"):
        template = "materials/partials/internos_content.html"
    else:
        template = "materials/internos.html"
    return templates.TemplateResponse(request, template, ctx)


@router.get("/internos", response_class=HTMLResponse)
async def get_internos_list(
    request: Request,
    filtros: Annotated[MaterialInternoFilter, Query()],
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    service: MaterialsService = Depends(get_materials_service),
    _=Depends(require_materials_view_access),
):
    filtro_dict = filtros.model_dump(exclude_none=True)
    filtro_dict.pop('page', None)
    filtro_dict.pop('per_page', None)
    internos, total = await service.get_internos(conn, filtro_dict, filtros.page, filtros.per_page)
    catalogos = await service.get_catalogos(conn)
    return templates.TemplateResponse(
        request, "materials/partials/tabla_internos.html",
        {
            "internos": internos,
            "total": total,
            "page": filtros.page,
            "per_page": filtros.per_page,
            "pages": max((total + filtros.per_page - 1) // filtros.per_page, 1),
            "estadisticas": await service.get_estadisticas_internos(conn),
            "categorias": catalogos.get("categorias", []),
            "unidades": await service.get_cat_unidades(conn),
            "filtros": {
                "q": filtros.q or "",
                "id_unidad_medida": filtros.id_unidad_medida or "",
                "id_categoria": filtros.id_categoria or "",
            },
            "can_edit": _can_edit_internos(context),
        }
    )


@router.post("/internos", response_class=HTMLResponse)
async def crear_interno(
    request: Request,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    service: MaterialsService = Depends(get_materials_service),
    _=require_materials_edit_access,
):
    form = await request.form()
    try:
        data = MaterialInternoCreate(
            descripcion_canonica=form.get("descripcion_canonica", ""),
            id_unidad_medida=int(form["id_unidad_medida"]) if form.get("id_unidad_medida") else None,
            id_categoria=int(form["id_categoria"]) if form.get("id_categoria") else None,
            clave_prod_serv=form.get("clave_prod_serv") or None,
            precio_referencia=float(form["precio_referencia"]) if form.get("precio_referencia") else None,
            notas=form.get("notas") or None,
            material=form.get("material") or None,
            tipo=form.get("tipo") or None,
            acabado=form.get("acabado") or None,
            marca=form.get("marca") or None,
            adicional=form.get("adicional") or None,
            medida=form.get("medida") or None,
            moneda=form.get("moneda") or "MXN",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    payload = data.model_dump()
    uid = context.get("user_db_id")
    payload["creado_por"] = uid
    payload["actualizado_por"] = uid
    try:
        interno = await service.crear_interno(
            conn, payload, puede_editar_costos=_puede_editar_costos_internos(context)
        )
    except ValueError as e:
        return toast_error(request, str(e))
    catalogos = await service.get_catalogos(conn)
    return templates.TemplateResponse(
        request, "materials/partials/row_interno.html",
        {
            "m": interno,
            "categorias": catalogos.get("categorias", []),
            "unidades": await service.get_cat_unidades(conn),
            "can_edit": _can_edit_internos(context),
        },
        headers={"HX-Trigger": "interno-creado"},
    )


@router.patch("/internos/{interno_id}", response_class=HTMLResponse)
async def actualizar_interno(
    request: Request,
    interno_id: UUID,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    service: MaterialsService = Depends(get_materials_service),
    _=require_materials_edit_access,
):
    form = await request.form()
    data = {}
    for field in ['descripcion_canonica', 'clave_prod_serv', 'notas',
                  'material', 'tipo', 'acabado', 'marca', 'adicional', 'medida', 'moneda']:
        if field in form:
            data[field] = form[field] or None
    for field in ['id_unidad_medida', 'id_categoria']:
        if field in form:
            data[field] = int(form[field]) if form.get(field) else None
    if 'precio_referencia' in form:
        val = form['precio_referencia']
        data['precio_referencia'] = float(val) if val else None

    data['actualizado_por'] = context.get("user_db_id")
    try:
        interno = await service.actualizar_interno(
            conn, interno_id, data,
            puede_editar_costos=_puede_editar_costos_internos(context),
        )
    except ValueError as e:
        return toast_error(request, str(e))
    if not interno:
        raise HTTPException(status_code=404, detail="Material no encontrado")
    catalogos = await service.get_catalogos(conn)
    return templates.TemplateResponse(
        request, "materials/partials/row_interno.html",
        {
            "m": interno,
            "categorias": catalogos.get("categorias", []),
            "unidades": await service.get_cat_unidades(conn),
            "can_edit": _can_edit_internos(context),
        }
    )


@router.delete("/internos/{interno_id}", response_class=HTMLResponse)
async def desactivar_interno(
    request: Request,
    interno_id: UUID,
    conn=Depends(get_db_connection),
    service: MaterialsService = Depends(get_materials_service),
    _=require_materials_edit_access,
):
    ok = await service.desactivar_interno(conn, interno_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Material no encontrado")
    return HTMLResponse("")


@router.get("/internos/plantilla")
async def descargar_plantilla_internos(
    conn=Depends(get_db_connection),
    service: MaterialsService = Depends(get_materials_service),
    _=require_materials_edit_access,
):
    """Descarga la plantilla .xlsx de carga masiva del catalogo interno."""
    excel_bytes = await service.generar_plantilla_internos(conn)
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="plantilla_catalogo_interno.xlsx"'},
    )


@router.post("/internos/importar", response_class=HTMLResponse)
async def importar_internos(
    request: Request,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    service: MaterialsService = Depends(get_materials_service),
    _=require_materials_edit_access,
):
    """Carga masiva en 2 fases. Sin 'confirmar': valida y previsualiza (no escribe).
    Con confirmar=true: inserta solo las filas validas."""
    form = await request.form()
    archivo = form.get("archivo")
    if not archivo or not getattr(archivo, 'filename', None):
        raise HTTPException(status_code=400, detail="Archivo requerido")
    confirmar = str(form.get("confirmar", "")).lower() == "true"
    contenido = await archivo.read()
    puede_editar_costos = _puede_editar_costos_internos(context)
    try:
        if confirmar:
            resultado = await service.cargar_internos_excel(
                conn, contenido, puede_editar_costos,
                creado_por=context.get("user_db_id"),
            )
        else:
            resultado = await service.validar_internos_excel(conn, contenido, puede_editar_costos)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except asyncpg.PostgresError as e:
        logger.exception("Error de BD al importar materiales internos")
        raise HTTPException(
            status_code=500,
            detail="Error de base de datos al importar materiales",
        ) from e
    headers = {"HX-Trigger": "internos-importados"} if confirmar else {}
    return templates.TemplateResponse(
        request, "materials/partials/importar_resultado.html",
        {"resultado": resultado},
        headers=headers,
    )


@router.get("/internos/plantilla-precios")
async def descargar_plantilla_precios(
    conn=Depends(get_db_connection),
    service: MaterialsService = Depends(get_materials_service),
    _=require_module_access("compras", "editor"),
):
    """Descarga el .xlsx de actualizacion masiva de precios."""
    excel_bytes = await service.generar_plantilla_precios(conn)
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="actualizar_precios_catalogo.xlsx"'},
    )


@router.post("/internos/actualizar-precios", response_class=HTMLResponse)
async def actualizar_precios_internos(
    request: Request,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    service: MaterialsService = Depends(get_materials_service),
    _=require_module_access("compras", "editor"),
):
    """Actualizacion masiva de precios en 2 fases. Compras/ADMIN unicamente --
    a diferencia del resto del catalogo interno, Ingenieria no tiene acceso aqui
    ni en lote (ver _puede_editar_costos_internos)."""
    form = await request.form()
    archivo = form.get("archivo")
    if not archivo or not getattr(archivo, 'filename', None):
        raise HTTPException(status_code=400, detail="Archivo requerido")

    confirmar = str(form.get("confirmar", "")).lower() == "true"
    contenido = await archivo.read()
    try:
        if confirmar:
            resultado = await service.actualizar_precios_excel(
                conn,
                contenido,
                actualizado_por=context.get("user_db_id"),
            )
        else:
            resultado = await service.validar_actualizacion_precios(conn, contenido)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except asyncpg.PostgresError as e:
        logger.exception("Error de BD al actualizar precios internos")
        raise HTTPException(
            status_code=500,
            detail="Error de base de datos al actualizar precios",
        ) from e

    headers = {"HX-Trigger": "internos-importados"} if confirmar else {}
    return templates.TemplateResponse(
        request,
        "materials/partials/actualizar_precios_resultado.html",
        {"resultado": resultado},
        headers=headers,
    )


@router.get("/internos/{interno_id}/vincular-xml", response_class=HTMLResponse)
async def modal_vincular_xml(
    request: Request,
    interno_id: UUID,
    q: str = Query(default=""),
    origen_item_id: Optional[UUID] = Query(default=None),
    conn=Depends(get_db_connection),
    service: MaterialsService = Depends(get_materials_service),
    _=Depends(require_materials_view_access),
):
    """origen_item_id: presente solo cuando el modal se abre desde el modal de
    precios pendientes de Compras (bom/partials/modal_precios_pendientes_compras.html)
    para un item ya vinculado a catalogo interno -- habilita, del lado del frontend,
    la opcion de usar el precio/moneda del XML vinculado para ese item pendiente."""
    es_partial = request.headers.get("hx-target") == "vincular-modal-content"
    interno, resultados = await service.resolver_xml_para_vincular(
        conn, interno_id, q, incluir_ancla=not es_partial
    )

    if es_partial:
        return templates.TemplateResponse(
            request, "materials/partials/vincular_xml_resultados.html",
            {"interno_id": str(interno_id), "resultados": resultados, "q": q, "origen_item_id": origen_item_id}
        )

    vinculos = await service.get_vinculos_xml(conn, interno_id)
    return templates.TemplateResponse(
        request, "materials/partials/modal_vincular_xml.html",
        {
            "interno_id": str(interno_id), "resultados": resultados, "vinculos": vinculos,
            "q": q, "interno": interno, "origen_item_id": origen_item_id,
        }
    )


@router.post("/internos/{interno_id}/vincular-xml", response_class=HTMLResponse)
async def crear_vinculo_xml(
    request: Request,
    interno_id: UUID,
    conn=Depends(get_db_connection),
    service: MaterialsService = Depends(get_materials_service),
    _=require_materials_edit_access,
):
    form = await request.form()
    try:
        id_xml = UUID(str(form["id_xml"]))
    except (KeyError, ValueError):
        raise HTTPException(status_code=400, detail="id_xml inválido")
    await service.crear_vinculo_xml(conn, interno_id, id_xml)
    vinculos = await service.get_vinculos_xml(conn, interno_id)
    return templates.TemplateResponse(
        request, "materials/partials/vinculos_xml_list.html",
        {"interno_id": str(interno_id), "vinculos": vinculos}
    )


@router.delete("/internos/{interno_id}/vincular-xml/{id_xml}", response_class=HTMLResponse)
async def eliminar_vinculo_xml(
    request: Request,
    interno_id: UUID,
    id_xml: UUID,
    conn=Depends(get_db_connection),
    service: MaterialsService = Depends(get_materials_service),
    _=require_materials_edit_access,
):
    await service.eliminar_vinculo_xml(conn, interno_id, id_xml)
    vinculos = await service.get_vinculos_xml(conn, interno_id)
    return templates.TemplateResponse(
        request, "materials/partials/vinculos_xml_list.html",
        {"interno_id": str(interno_id), "vinculos": vinculos}
    )


@router.get("/{material_id}/vincular-interno", response_class=HTMLResponse)
async def modal_vincular_interno(
    request: Request,
    material_id: UUID,
    q: str = Query(default=""),
    conn=Depends(get_db_connection),
    service: MaterialsService = Depends(get_materials_service),
    _=Depends(require_materials_view_access),
):
    es_partial = request.headers.get("hx-target") == "vincular-interno-modal-content"
    material, resultados = await service.resolver_internos_para_vincular(
        conn, material_id, q, incluir_ancla=not es_partial
    )

    if es_partial:
        return templates.TemplateResponse(
            request, "materials/partials/vincular_interno_resultados.html",
            {"material_id": str(material_id), "resultados": resultados, "q": q}
        )

    vinculos = await service.get_vinculos_interno_por_xml(conn, material_id)
    return templates.TemplateResponse(
        request, "materials/partials/modal_vincular_interno.html",
        {"material_id": str(material_id), "resultados": resultados, "vinculos": vinculos, "q": q, "material": material}
    )


@router.post("/{material_id}/vincular-interno", response_class=HTMLResponse)
async def crear_vinculo_interno(
    request: Request,
    material_id: UUID,
    conn=Depends(get_db_connection),
    service: MaterialsService = Depends(get_materials_service),
    _=require_materials_edit_access,
):
    form = await request.form()
    try:
        id_interno = UUID(str(form["id_interno"]))
    except (KeyError, ValueError):
        raise HTTPException(status_code=400, detail="id_interno inválido")
    await service.vincular_interno_a_xml(conn, material_id, id_interno)
    vinculos = await service.get_vinculos_interno_por_xml(conn, material_id)
    return templates.TemplateResponse(
        request, "materials/partials/vinculos_interno_list.html",
        {"material_id": str(material_id), "vinculos": vinculos}
    )


@router.delete("/{material_id}/vincular-interno/{id_interno}", response_class=HTMLResponse)
async def eliminar_vinculo_interno(
    request: Request,
    material_id: UUID,
    id_interno: UUID,
    conn=Depends(get_db_connection),
    service: MaterialsService = Depends(get_materials_service),
    _=require_materials_edit_access,
):
    await service.eliminar_vinculo_interno(conn, material_id, id_interno)
    vinculos = await service.get_vinculos_interno_por_xml(conn, material_id)
    return templates.TemplateResponse(
        request, "materials/partials/vinculos_interno_list.html",
        {"material_id": str(material_id), "vinculos": vinculos}
    )


# ========================================
# CONCILIACION: MATCHER AUTOMATICO CATALOGO INTERNO <-> XML (doc 39, punto 6.2)
# ========================================

@router.get("/conciliacion-xml", response_class=HTMLResponse)
async def get_conciliacion_xml(
    request: Request,
    conn=Depends(get_db_connection),
    service: MaterialsService = Depends(get_materials_service),
    _=require_materials_edit_access,
):
    """Sugerencias del matcher automatico (CLAVE_SAT/MEMORIA/TEXTO) pendientes
    de revision humana. Mismo permiso que los endpoints manuales de vinculo
    del modulo materials (compras O ingenieria, editor) -- doc 39, decision A."""
    conceptos = await service.get_conceptos_para_conciliacion_interno(conn)
    return templates.TemplateResponse(
        request, "materials/partials/conciliacion_xml.html",
        {"conceptos": conceptos}
    )


@router.post("/conciliacion-xml/{historial_id}/confirmar", response_class=HTMLResponse)
async def post_confirmar_match_interno(
    request: Request,
    historial_id: UUID,
    conn=Depends(get_db_connection),
    service: MaterialsService = Depends(get_materials_service),
    _=require_materials_edit_access,
):
    """Confirma la sugerencia tal cual la dejo el matcher, o la sustituye por
    otro item si el usuario eligio uno distinto en el selector. id_material_interno
    vacio en el form => rechaza (limpia la sugerencia sin vincular nada)."""
    form = await request.form()
    try:
        lock_version = int(form["concepto_lock_version"])
    except (KeyError, ValueError):
        raise HTTPException(status_code=400, detail="concepto_lock_version inválido")

    id_material_interno = None
    valor = (form.get("id_material_interno") or "").strip()
    if valor:
        try:
            id_material_interno = UUID(valor)
        except ValueError:
            raise HTTPException(status_code=400, detail="Ítem inválido")

    try:
        await service.confirmar_match_interno(
            conn, historial_id, id_material_interno, lock_version
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except asyncpg.PostgresError:
        logger.exception("Error de BD al confirmar match interno<->XML")
        raise HTTPException(status_code=500, detail="Error al guardar la conciliación")

    conceptos = await service.get_conceptos_para_conciliacion_interno(conn)
    return templates.TemplateResponse(
        request, "materials/partials/conciliacion_xml_lista.html",
        {"conceptos": conceptos}
    )


# Captura asistida por PDF de precios del catalogo interno (submodulo propio,
# ver core/materials/pdf_captura.py -- router.py/service.py ya superan el
# umbral de refactor y esta logica es una unidad cohesiva separable).
from .pdf_captura import pdf_captura_router
router.include_router(pdf_captura_router)
