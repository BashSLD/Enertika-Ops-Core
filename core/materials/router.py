# Archivo: core/materials/router.py
"""
Router compartido de Materiales.
Consulta, edicion de clasificacion, analisis de precios y exportacion Excel.
"""

from fastapi import APIRouter, Depends, Request, Query, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, Response
from typing import Optional, Annotated
from uuid import UUID
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
from .service import MaterialsService, get_materials_service
from .schemas import MaterialFilter, MaterialUpdate, MaterialInternoCreate, MaterialInternoFilter

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
    interno = await service.crear_interno(conn, payload)
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
    interno = await service.actualizar_interno(conn, interno_id, data)
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
    try:
        if confirmar:
            resultado = await service.cargar_internos_excel(
                conn, contenido, creado_por=context.get("user_db_id")
            )
        else:
            resultado = await service.validar_internos_excel(conn, contenido)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error al leer archivo: {e}")
    headers = {"HX-Trigger": "internos-importados"} if confirmar else {}
    return templates.TemplateResponse(
        request, "materials/partials/importar_resultado.html",
        {"resultado": resultado},
        headers=headers,
    )


@router.get("/internos/{interno_id}/vincular-xml", response_class=HTMLResponse)
async def modal_vincular_xml(
    request: Request,
    interno_id: UUID,
    q: str = Query(default=""),
    conn=Depends(get_db_connection),
    service: MaterialsService = Depends(get_materials_service),
    _=Depends(require_materials_view_access),
):
    resultados = await service.buscar_xml_para_vincular(conn, interno_id, q) if len(q) >= 3 else []
    vinculos = await service.get_vinculos_xml(conn, interno_id)
    return templates.TemplateResponse(
        request, "materials/partials/modal_vincular_xml.html",
        {"interno_id": str(interno_id), "resultados": resultados, "vinculos": vinculos, "q": q}
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
