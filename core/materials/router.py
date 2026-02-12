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
from datetime import datetime
import logging

from core.database import get_db_connection
from core.security import get_current_user_context
from core.permissions import require_module_access, ROLE_HIERARCHY
from core.config import settings
from .service import MaterialsService, get_materials_service
from .schemas import MaterialFilter, MaterialUpdate

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
        "request": request,
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

    if request.headers.get("hx-request"):
        template = "materials/partials/content.html"
    else:
        template = "materials/dashboard.html"

    return templates.TemplateResponse(template, template_context)


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
        "materials/partials/tabla_materiales.html",
        {
            "request": request,
            "materiales": materiales,
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
        "materials/partials/modal_precios.html",
        {
            "request": request,
            "material": material,
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
        "materials/partials/row_material.html",
        {
            "request": request,
            "m": material,
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

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
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
        "materials/partials/similar_results.html",
        {
            "request": request,
            "resultados": resultados,
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
