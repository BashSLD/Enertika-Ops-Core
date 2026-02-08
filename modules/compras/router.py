# Archivo: modules/compras/router.py
"""
Router del Módulo Compras - Sistema de Comprobantes de Pago.

Endpoints:
- /compras/ui - Dashboard principal
- /compras/upload - Carga de PDFs
- /compras/comprobantes - CRUD de comprobantes
- /compras/export-excel - Exportación
- /compras/catalogos - Catálogos para dropdowns
"""

from fastapi import APIRouter, Depends, Request, Form, File, UploadFile, Query, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, StreamingResponse, Response
from typing import List, Optional
from uuid import UUID
from datetime import date, datetime
import logging
import json
from io import BytesIO

# Core imports
from core.database import get_db_connection
from core.security import get_current_user_context
from core.permissions import require_module_access
from core.config import settings

# Module imports
from .service import ComprasService, get_compras_service
from .schemas import (
    ComprobanteUpdate, 
    ComprobanteBulkUpdate,
    ComprobanteFilter,
    ComprobanteUpdateForm
)
from typing import Annotated

logger = logging.getLogger("ComprasModule")
templates = Jinja2Templates(directory="templates")
templates.env.globals["DEBUG_MODE"] = settings.DEBUG_MODE

# Registrar filtros de timezone
from core.jinja_filters import register_timezone_filters
register_timezone_filters(templates.env)

router = APIRouter(
    prefix="/compras",
    tags=["Módulo Compras"],
)


# ========================================
# ENDPOINT PRINCIPAL (UI)
# ========================================

@router.api_route("/ui", methods=["GET", "HEAD"], include_in_schema=False)
async def get_compras_ui(
    request: Request,
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context),
    service: ComprasService = Depends(get_compras_service),
    _ = require_module_access("compras")
):
    """
    Dashboard principal del módulo compras.
    
    HTMX Detection:
    - Si viene desde sidebar (HTMX): retorna solo contenido
    - Si es carga directa (F5/URL): retorna dashboard completo
    """
    # Obtener catálogos para los filtros
    catalogos = await service.get_catalogos(conn)
    
    # Obtener comprobantes con vista default (PENDIENTE + mes actual)
    comprobantes, total = await service.get_comprobantes_default_view(conn)
    
    # Obtener estadísticas (Global pendientes por defecto)
    estadisticas = await service.get_estadisticas_generales(
        conn,
        estatus="PENDIENTE"
    )
    
    # Calcular paginación
    page = 1
    per_page = 50
    pages = (total + per_page - 1) // per_page if total > 0 else 1
    
    # Fechas default para filtros (Vacio para ver global pendientes)
    # today = date.today()
    # fecha_inicio_default = today.replace(day=1)
    # fecha_fin_default = today
    
    template_context = {
        "request": request,
        "user_name": context.get("user_name"),
        "role": context.get("role"),
        "module_roles": context.get("module_roles", {}),
        "current_module_role": context.get("module_roles", {}).get("compras", "viewer"),
        # Datos
        "comprobantes": comprobantes,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": pages,
        # Catálogos
        "zonas": catalogos.get("zonas", []),
        "categorias": catalogos.get("categorias", []),
        "proyectos": catalogos.get("proyectos", []),
        # Filtros aplicados (defaults)
        "filtros": {
            "fecha_inicio": "",
            "fecha_fin": "",
            "estatus": "PENDIENTE"
        },
        # Estadísticas
        "estadisticas": estadisticas
    }
    
    # HTMX Detection
    if request.headers.get("hx-request"):
        template = "compras/partials/content.html"
    else:
        template = "compras/dashboard.html"
    
    return templates.TemplateResponse(template, template_context)


# ========================================
# CARGA DE PDFs
# ========================================

@router.post("/upload", response_class=HTMLResponse)
async def upload_comprobantes(
    request: Request,
    files: List[UploadFile] = File(...),
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context),
    service: ComprasService = Depends(get_compras_service),
    _ = require_module_access("compras", "editor")
):
    """
    Carga y procesa múltiples PDFs de comprobantes BBVA.
    
    - Extrae automáticamente: fecha, beneficiario, monto, moneda
    - Detecta duplicados por (fecha + beneficiario + monto)
    - Guarda directamente en BD
    
    Returns:
        HTML con resultado de la carga (toast + tabla actualizada)
    """
    user_id = context.get("user_db_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Usuario no identificado")
    
    # Filtrar solo PDFs
    pdf_files = [f for f in files if f.filename.lower().endswith('.pdf')]
    
    if not pdf_files:
        return templates.TemplateResponse(
            "compras/partials/upload_result.html",
            {
                "request": request,
                "success": False,
                "message": "No se encontraron archivos PDF válidos",
                "insertados": 0,
                "duplicados": [],
                "errores": []
            }
        )
    
    logger.info(f"Procesando {len(pdf_files)} PDFs por usuario {user_id}")
    
    # Procesar PDFs
    result = await service.process_and_save_pdfs(conn, pdf_files, user_id)
    
    # Obtener tabla actualizada
    comprobantes, total = await service.get_comprobantes_default_view(conn)
    catalogos = await service.get_catalogos(conn)
    
    return templates.TemplateResponse(
        "compras/partials/upload_result.html",
        {
            "request": request,
            "success": result["insertados"] > 0,
            "message": f"{result['insertados']} comprobante(s) cargado(s) exitosamente",
            "insertados": result["insertados"],
            "duplicados": result["duplicados"],
            "errores": result["errores"],
            # Datos para refrescar tabla
            "comprobantes": comprobantes,
            "total": total,
            "zonas": catalogos.get("zonas", []),
            "categorias": catalogos.get("categorias", []),
            "proyectos": catalogos.get("proyectos", [])
        }
    )


# ========================================
# LISTADO Y FILTROS
# ========================================

@router.get("/comprobantes", response_class=HTMLResponse)
async def get_comprobantes_list(
    request: Request,
    filtros: Annotated[ComprobanteFilter, Query()],
    conn = Depends(get_db_connection),
    service: ComprasService = Depends(get_compras_service),
    _ = require_module_access("compras")
):
    """
    Lista comprobantes con filtros (HTMX partial).
    """
    # Convertir filtros a dict para el servicio
    filtro_dict = filtros.model_dump(exclude_none=True)

    comprobantes, total = await service.get_comprobantes(
        conn,
        filtros=filtro_dict,
        page=filtros.page,
        per_page=filtros.per_page
    )
    
    pages = (total + filtros.per_page - 1) // filtros.per_page if total > 0 else 1
    catalogos = await service.get_catalogos(conn)
    
    # Calcular estadísticas filtradas para OOB swap
    estadisticas = await service.get_estadisticas_generales(
        conn,
        filtros=filtro_dict
    )
    
    # Renderizar tabla
    response = templates.TemplateResponse(
        "compras/partials/tabla_comprobantes.html",
        {
            "request": request,
            "comprobantes": comprobantes,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": pages,
            "zonas": catalogos.get("zonas", []),
            "categorias": catalogos.get("categorias", []),
            "proyectos": catalogos.get("proyectos", []),
            "filtros": {
                "fecha_inicio": filtros.fecha_inicio.isoformat() if filtros.fecha_inicio else "",
                "fecha_fin": filtros.fecha_fin.isoformat() if filtros.fecha_fin else "",
                "estatus": filtros.estatus or "",
                "id_zona": filtros.id_zona,
                "id_proyecto": str(filtros.id_proyecto) if filtros.id_proyecto else "",
                "id_categoria": filtros.id_categoria
            }
        }
    )
    
    # Renderizar stats OOB
    stats_html = templates.TemplateResponse(
        "compras/partials/estadisticas.html",
        {"request": request, "estadisticas": estadisticas}
    ).body.decode("utf-8")
    
    # Injectar OOB en la respuesta
    # Necesitamos agregar hx-swap-oob="true" al div principal del string renderizado si no lo tiene,
    # pero es mas seguro agregarlo manualmente o asegurar que el template lo soporte.
    # Como modificamos estadisticas.html para tener ID, HTMX lo reemplazará si ponemos <div hx-swap-oob="true" id="stats-container">...</div>
    # Vamos a envolver el contenido en una etiqueta OOB explicita para asegurar
    
    oob_content = f'<div id="stats-container" hx-swap-oob="true">{stats_html}</div>'
    
    # Combinar
    final_content = response.body.decode("utf-8") + oob_content
    
    return HTMLResponse(content=final_content)


# ========================================
# EDICIÓN INDIVIDUAL
# ========================================

@router.get("/comprobantes/{id_comprobante}/modal", response_class=HTMLResponse)
async def get_comprobante_edit_modal(
    request: Request,
    id_comprobante: UUID,
    conn = Depends(get_db_connection),
    service: ComprasService = Depends(get_compras_service),
    _ = require_module_access("compras")
):
    """
    Obtiene el modal de edición para un comprobante.
    """
    comprobante = await service.get_comprobante_by_id(conn, id_comprobante)
    if not comprobante:
        raise HTTPException(status_code=404, detail="Comprobante no encontrado")
    
    catalogos = await service.get_catalogos(conn)
    
    return templates.TemplateResponse(
        "compras/partials/modal_editar.html",
        {
            "request": request,
            "comprobante": comprobante,
            "zonas": catalogos.get("zonas", []),
            "categorias": catalogos.get("categorias", []),
            "proyectos": catalogos.get("proyectos", [])
        }
    )


@router.patch("/comprobantes/{id_comprobante}", response_class=HTMLResponse)
async def update_comprobante(
    request: Request,
    id_comprobante: UUID,
    form: Annotated[ComprobanteUpdateForm, Form()],
    conn = Depends(get_db_connection),
    service: ComprasService = Depends(get_compras_service),
    context = Depends(get_current_user_context),
    _ = require_module_access("compras", "editor")
):
    """
    Actualiza un comprobante individual.
    
    Returns:
        HTML de la fila actualizada (HTMX swap)
    """
    # Construir updates
    updates = form.model_dump(exclude_none=True)
    
    # Actualizar
    comprobante = await service.update_comprobante(conn, id_comprobante, updates, user_context=context)
    catalogos = await service.get_catalogos(conn)
    
    return templates.TemplateResponse(
        "compras/partials/row_comprobante.html",
        {
            "request": request,
            "comprobante": comprobante,
            "zonas": catalogos.get("zonas", []),
            "categorias": catalogos.get("categorias", []),
            "proyectos": catalogos.get("proyectos", [])
        }
    )


# ========================================
# EDICIÓN MASIVA (BULK)
# ========================================

@router.post("/comprobantes/bulk-update", response_class=HTMLResponse)
async def bulk_update_comprobantes(
    request: Request,
    ids: str = Form(...),  # JSON array de UUIDs
    id_zona: Optional[int] = Form(None),
    id_proyecto: Optional[str] = Form(None),
    id_categoria: Optional[int] = Form(None),
    estatus: Optional[str] = Form(None),
    conn = Depends(get_db_connection),
    service: ComprasService = Depends(get_compras_service),
    context = Depends(get_current_user_context),
    _ = require_module_access("compras", "editor")
):
    """
    Actualización masiva de múltiples comprobantes.
    """
    # Parsear IDs
    try:
        id_list = json.loads(ids)
        uuid_list = [UUID(id_str) for id_str in id_list]
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"IDs inválidos: {e}")
    
    if not uuid_list:
        raise HTTPException(status_code=400, detail="No se proporcionaron IDs")
    
    # Construir updates
    updates = {}
    
    if id_zona is not None and id_zona > 0:
        updates["id_zona"] = id_zona
    
    if id_proyecto:
        try:
            updates["id_proyecto"] = UUID(id_proyecto)
        except ValueError:
            pass
    
    if id_categoria is not None and id_categoria > 0:
        updates["id_categoria"] = id_categoria
    
    if estatus and estatus in ["PENDIENTE", "FACTURADO"]:
        updates["estatus"] = estatus
    
    # Ejecutar bulk update
    count = await service.bulk_update_comprobantes(conn, uuid_list, updates, user_context=context)
    
    return templates.TemplateResponse(
        "compras/partials/bulk_result.html",
        {
            "request": request,
            "count": count
        }
    )


# ========================================
# EXPORTACIÓN EXCEL
# ========================================

@router.get("/export-excel")
async def export_excel(
    request: Request,
    filtros: Annotated[ComprobanteFilter, Query()],
    conn = Depends(get_db_connection),
    service: ComprasService = Depends(get_compras_service),
    _ = require_module_access("compras")
):
    """
    Exporta comprobantes a Excel con los filtros aplicados.
    """
    # Generar Excel
    excel_bytes = await service.export_to_excel(
        conn,
        filtros=filtros.model_dump(exclude_none=True)
    )
    
    # Generar nombre de archivo
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"comprobantes_pago_{timestamp}.xlsx"
    
    return StreamingResponse(
        BytesIO(excel_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
        }
    )


# ========================================
# CATÁLOGOS
# ========================================

@router.get("/catalogos")
async def get_catalogos(
    conn = Depends(get_db_connection),
    service: ComprasService = Depends(get_compras_service),
    _ = require_module_access("compras")
):
    """
    Obtiene todos los catálogos para dropdowns.
    """
    return await service.get_catalogos(conn)


@router.get("/proveedores/search", response_class=HTMLResponse)
async def search_proveedores(
    request: Request,
    q: str = Query(..., min_length=2),
    conn = Depends(get_db_connection),
    service: ComprasService = Depends(get_compras_service),
    _ = require_module_access("compras")
):
    """
    Búsqueda de proveedores (para autocompletado).
    """
    proveedores = await service.get_proveedores_search(conn, q)
    
    return templates.TemplateResponse(
        "compras/partials/proveedores_search_results.html",
        {
            "request": request,
            "proveedores": proveedores
        }
    )


# ========================================
# ESTADÍSTICAS
# ========================================

@router.get("/estadisticas", response_class=HTMLResponse)
async def get_estadisticas(
    request: Request,
    conn = Depends(get_db_connection),
    service: ComprasService = Depends(get_compras_service),
    _ = require_module_access("compras")
):
    """
    Obtiene estadísticas del mes actual (HTMX partial).
    """
    stats = await service.get_estadisticas_generales(conn, estatus="PENDIENTE")
    
    return templates.TemplateResponse(
        "compras/partials/estadisticas.html",
        {
            "request": request,
            "estadisticas": stats
        }
    )