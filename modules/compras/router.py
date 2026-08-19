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

import json
import logging
import zipfile
from datetime import date
from typing import List, Optional
from uuid import UUID

import asyncpg
import httpx
from fastapi import APIRouter, Depends, Request, Form, File, UploadFile, Query, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse, Response

from core.validation import validate_upload_size
import base64
import binascii
from io import BytesIO
from starlette.datastructures import Headers

# Core imports
from core.database import get_db_connection
from core.security import get_current_user_context
from core.permissions import require_module_access
from core.config import settings
from core.config_service import ConfigService
from core.timezone import now_mx, today_mx

# Module imports
from .service import (
    ComprasService, get_compras_service, parse_exceso_monto_error,
    rango_valido_para_zip, MAX_DIAS_EXPORT_ZIP,
)
from modules.shared.utils import content_disposition_header
from modules.proveedores.service import ProveedoresService, get_proveedores_service, SharePointProveedorError
from modules.proveedores.router import _handle_sharepoint_error
from core.bom.service import FLAG_ACTUALIZACION_PRECIOS_COMPRAS
from .schemas import (
    ComprobanteFilter,
    ComprobanteUpdateForm,
)
from typing import Annotated

logger = logging.getLogger("ComprasModule")
templates = Jinja2Templates(directory="templates")
templates.env.globals["DEBUG_MODE"] = settings.DEBUG_MODE



def _build_xml_manual_retry_context(
    *,
    uuid_factura: str,
    id_comprobante: UUID,
    emisor_rfc: str,
    emisor_nombre: str,
    total: str,
    subtotal: Optional[str],
    moneda: str,
    fecha: str,
    tipo_factura: str,
    tipo_comprobante: Optional[str],
    metodo_pago: Optional[str],
    forma_pago: Optional[str],
    conceptos_json: str,
    relacionados_json: str,
    xml_content_b64: str,
    guardar_relacion: bool,
) -> dict:
    return {
        "uuid_factura": uuid_factura,
        "id_comprobante": str(id_comprobante),
        "emisor_rfc": emisor_rfc,
        "emisor_nombre": emisor_nombre,
        "total": total,
        "subtotal": subtotal or "",
        "moneda": moneda,
        "fecha": fecha,
        "tipo_factura": tipo_factura,
        "tipo_comprobante": tipo_comprobante or "",
        "metodo_pago": metodo_pago or "",
        "forma_pago": forma_pago or "",
        "conceptos_json": conceptos_json or "[]",
        "relacionados_json": relacionados_json or "[]",
        "xml_content_b64": xml_content_b64,
        "guardar_relacion": "true" if guardar_relacion else "false",
    }


def _serialize_xml_result(result):
    """Convierte XmlUploadResult a dict serializable para templates Jinja2.

    Transforma Pydantic models (CfdiData, XmlMatchResult, XmlUploadError) a dicts
    planos, convirtiendo Decimal a float y Enum a string para que Jinja2 pueda
    renderizarlos sin errores de serialización.

    Args:
        result: XmlUploadResult con procesados, duplicados y errores.

    Returns:
        dict con claves 'procesados', 'duplicados', 'errores' como listas de dicts.
    """
    def _serialize_cfdi(cfdi):
        if hasattr(cfdi, 'model_dump'):
            return cfdi.model_dump(mode='json')
        return dict(cfdi)

    serialized = {
        'procesados': [],
        'duplicados': [e.model_dump() if hasattr(e, 'model_dump') else dict(e) for e in result.duplicados],
        'errores': [e.model_dump() if hasattr(e, 'model_dump') else dict(e) for e in result.errores],
    }

    for match in result.procesados:
        item = {
            'cfdi': _serialize_cfdi(match.cfdi),
            'match_type': match.match_type,
            'candidatos': match.candidatos,
            'comprobante_id': str(match.comprobante_id) if match.comprobante_id else None,
            'xml_content_b64': match.xml_content_b64 or '',
            'emisor_rfc': match.cfdi.emisor_rfc,
        }
        serialized['procesados'].append(item)

    return serialized

# Registrar filtros de timezone
from core.jinja_filters import register_timezone_filters
register_timezone_filters(templates.env)

router = APIRouter(
    prefix="/compras",
    tags=["Módulo Compras"],
)


def _usuario_ctx(context: dict) -> tuple:
    """Devuelve (current_user_id, default_usuario, filtro_usuario) según rol."""
    user_db_id = context.get("user_db_id")
    is_admin = context.get("role") == "ADMIN"
    current_user_id = str(user_db_id) if user_db_id else ""
    default_usuario = "" if is_admin else current_user_id
    filtro_usuario = None if is_admin else user_db_id
    return current_user_id, default_usuario, filtro_usuario


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
    catalogos = await service.get_catalogos(conn)
    current_user_id, default_usuario, filtro_usuario = _usuario_ctx(context)
    role = context.get("role")

    # Vista default: comprobantes abiertos
    page = 1
    per_page = 50
    comprobantes, total = await service.get_comprobantes_default_view(conn, user_id=filtro_usuario)

    filtros_stats = {"estatus": "SIN_COMPLETAR"}
    if filtro_usuario:
        filtros_stats["id_usuario"] = filtro_usuario
    estadisticas = await service.get_estadisticas_generales(conn, filtros=filtros_stats)

    pages = (total + per_page - 1) // per_page if total > 0 else 1

    template_context = {
        "user_name": context.get("user_name"),
        "role": role,
        "module_roles": context.get("module_roles", {}),
        "current_module_role": context.get("module_roles", {}).get("compras", "viewer"),
        "comprobantes": comprobantes,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": pages,
        "zonas": catalogos.get("zonas", []),
        "categorias": catalogos.get("categorias", []),
        "proyectos": catalogos.get("proyectos", []),
        "compradores": catalogos.get("compradores", []),
        "current_user_id": current_user_id,
        "default_usuario": default_usuario,
        "filtros": {
            "fecha_inicio": "",
            "fecha_fin": "",
            "estatus": "SIN_COMPLETAR",
            "id_usuario": default_usuario,
        },
        # Vista default no trae fecha_inicio/fecha_fin (siempre vacías arriba) —
        # explícito en vez de dejarlo a la plantilla, para que quede claro que el
        # link de ZIP se habilita solo cuando SÍ hay un rango de fechas real
        # (get_comprobantes_list, tras aplicar filtros).
        "zip_rango_valido": rango_valido_para_zip(None, None),
        "estadisticas": estadisticas,
        "today": today_mx(),
    }
    
    # HTMX Detection
    # HX-History-Restore-Request: HTMX lo envía al restaurar historial (Back/Forward) — retornar full page
    is_htmx = request.headers.get("hx-request")
    is_history_restore = request.headers.get("hx-history-restore-request")
    if is_htmx and not is_history_restore:
        template = "compras/partials/content.html"
    else:
        template = "compras/dashboard.html"
    
    return templates.TemplateResponse(request, template, template_context)


# ========================================
# PROYECTOS CON BOM (Gap 6)
# ========================================

@router.get("/proyectos-bom", include_in_schema=False)
async def get_proyectos_bom(
    request: Request,
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context),
    _ = require_module_access("compras"),
):
    """Shell de tabs (Activos / Actualizacion de precios). Cada tab carga su propio
    contenido via hx-get + intersect once (patron bom/partials/content.html:585-648)."""
    actualizacion_precios_habilitada = await ConfigService.get_global_config(
        conn, FLAG_ACTUALIZACION_PRECIOS_COMPRAS, False, bool
    )
    total_pendientes_precio = 0
    if actualizacion_precios_habilitada:
        from .db_service import get_db_service
        db_svc = get_db_service()
        total_pendientes_precio = await db_svc.get_proyectos_bom_pendientes_precio_count(conn)
    ctx = {
        "user_name": context.get("user_name"),
        "actualizacion_precios_habilitada": actualizacion_precios_habilitada,
        "total_pendientes_precio": total_pendientes_precio,
    }

    is_htmx = request.headers.get("hx-request")
    is_history_restore = request.headers.get("hx-history-restore-request")
    if is_htmx and not is_history_restore:
        return templates.TemplateResponse(request, "compras/partials/proyectos_bom_tabs.html", ctx)
    return templates.TemplateResponse(request, "compras/proyectos_bom.html", ctx)


@router.get("/proyectos-bom/activos", include_in_schema=False)
async def get_proyectos_bom_activos(
    request: Request,
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context),
    _ = require_module_access("compras"),
):
    """Partial: tab 'Activos' (BOM en estatus visible para Compras, APROBADO_CONST+)."""
    from .db_service import get_db_service
    db_svc = get_db_service()
    proyectos = await db_svc.get_proyectos_con_bom(conn)

    return templates.TemplateResponse(
        request, "compras/partials/proyectos_bom.html",
        {"proyectos": proyectos, "user_name": context.get("user_name")}
    )


@router.get("/proyectos-bom/pendientes-precio", include_in_schema=False)
async def get_proyectos_bom_pendientes_precio(
    request: Request,
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context),
    _ = require_module_access("compras"),
):
    """Partial: tab 'Actualizacion de precios' (BOM activo previo a APROBADO_CONST con items base sin costo)."""
    habilitada = await ConfigService.get_global_config(
        conn, FLAG_ACTUALIZACION_PRECIOS_COMPRAS, False, bool
    )
    if not habilitada:
        return templates.TemplateResponse(
            request, "compras/partials/precios_pendientes.html",
            {"proyectos": [], "deshabilitada": True, "user_name": context.get("user_name")}
        )

    from .db_service import get_db_service
    db_svc = get_db_service()
    proyectos = await db_svc.get_proyectos_bom_pendientes_precio(conn)

    return templates.TemplateResponse(
        request, "compras/partials/precios_pendientes.html",
        {"proyectos": proyectos, "deshabilitada": False, "user_name": context.get("user_name")}
    )


# ========================================
# PDF UPLOAD# ========================================
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

    pdf_files = [f for f in files if f.filename.lower().endswith('.pdf')]

    # Validar tamano de cada archivo (max 50MB por PDF)
    for f in pdf_files:
        try:
            await validate_upload_size(f, max_bytes=50 * 1024 * 1024)
        except ValueError as e:
            return templates.TemplateResponse(request,
                 "compras/partials/upload_result.html",
                {                    "success": False,
                    "message": f"Archivo {f.filename}: {e}",
                    "insertados": 0,
                    "duplicados": [],
                    "errores": []
                }
            )

    if not pdf_files:
        return templates.TemplateResponse(request,
             "compras/partials/upload_result.html",
            {                "success": False,
                "message": "No se encontraron archivos PDF válidos",
                "insertados": 0,
                "duplicados": [],
                "errores": []
            }
        )
    
    logger.info(f"Procesando {len(pdf_files)} PDFs por usuario {user_id}")
    
    result = await service.process_and_save_pdfs(conn, pdf_files, user_id)
    
    comprobantes, total = await service.get_comprobantes_default_view(conn)
    catalogos = await service.get_catalogos(conn)
    
    return templates.TemplateResponse(request,
         "compras/partials/upload_result.html",
        {            "success": result["insertados"] > 0,
            "message": f"{result['insertados']} comprobante(s) cargado(s) exitosamente",
            "insertados": result["insertados"],
            "duplicados": result["duplicados"],
            "errores": result["errores"],
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
    context = Depends(get_current_user_context),
    _ = require_module_access("compras")
):
    """
    Lista comprobantes con filtros (HTMX partial).
    """
    filtro_dict = filtros.model_dump(exclude_none=True)
    # Solo se consulta si hay rango de fechas: rango_valido_para_zip ya es False
    # sin fechas, así que el valor sería descartado — evita un lookup de config
    # (aunque cacheado) en cada render de la vista default sin filtro de fecha.
    max_dias_zip = (
        await service.get_max_dias_export_zip(conn)
        if filtros.fecha_inicio and filtros.fecha_fin else MAX_DIAS_EXPORT_ZIP
    )

    comprobantes, total = await service.get_comprobantes(
        conn,
        filtros=filtro_dict,
        page=filtros.page,
        per_page=filtros.per_page
    )

    pages = (total + filtros.per_page - 1) // filtros.per_page if total > 0 else 1
    catalogos = await service.get_catalogos(conn)

    estadisticas = await service.get_estadisticas_generales(conn, filtros=filtro_dict)
    current_user_id, default_usuario, _ = _usuario_ctx(context)

    response = templates.TemplateResponse(request,
        "compras/partials/tabla_comprobantes.html",
        {
            "comprobantes": comprobantes,
            "total": total,
            "page": filtros.page,
            "per_page": filtros.per_page,
            "pages": pages,
            "zonas": catalogos.get("zonas", []),
            "categorias": catalogos.get("categorias", []),
            "proyectos": catalogos.get("proyectos", []),
            "compradores": catalogos.get("compradores", []),
            "current_user_id": current_user_id,
            "default_usuario": default_usuario,
            "role": context.get("role"),
            "current_module_role": context.get("module_roles", {}).get("compras", "viewer"),
            "filtros": {
                "fecha_inicio": filtros.fecha_inicio.isoformat() if filtros.fecha_inicio else "",
                "fecha_fin": filtros.fecha_fin.isoformat() if filtros.fecha_fin else "",
                "estatus": filtros.estatus if filtros.estatus is not None else "TODOS",
                "id_zona": filtros.id_zona or "",
                "id_proyecto": str(filtros.id_proyecto) if filtros.id_proyecto else "",
                "id_categoria": filtros.id_categoria or "",
                "id_usuario": str(filtros.id_usuario) if filtros.id_usuario else "",
            },
            "zip_rango_valido": rango_valido_para_zip(filtros.fecha_inicio, filtros.fecha_fin, max_dias_zip),
            "max_dias_zip": max_dias_zip,
            "today": today_mx(),
        }
    )

    stats_html = templates.TemplateResponse(request,
        "compras/partials/estadisticas.html",
        {"estadisticas": estadisticas}
    ).body.decode("utf-8")
    oob_content = stats_html.replace('<div id="stats-container"', '<div id="stats-container" hx-swap-oob="true"', 1)
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
    
    return templates.TemplateResponse(request,
         "compras/partials/modal_editar.html",
        {            "comprobante": comprobante,
            "zonas": catalogos.get("zonas", []),
            "categorias": catalogos.get("categorias", []),
            "proyectos": catalogos.get("proyectos", []),
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
    updates = form.model_dump(exclude_none=True)
    
    comprobante = await service.update_comprobante(conn, id_comprobante, updates, user_context=context)
    catalogos = await service.get_catalogos(conn)
    
    return templates.TemplateResponse(request,
         "compras/partials/row_comprobante.html",
        {            "comprobante": comprobante,
            "zonas": catalogos.get("zonas", []),
            "categorias": catalogos.get("categorias", []),
            "proyectos": catalogos.get("proyectos", []),
            "role": context.get("role"),
            "current_module_role": context.get("module_roles", {}).get("compras", "viewer"),
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
    try:
        id_list = json.loads(ids)
        uuid_list = [UUID(id_str) for id_str in id_list]
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"IDs inválidos: {e}")
    
    if not uuid_list:
        raise HTTPException(status_code=400, detail="No se proporcionaron IDs")
    
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
    
    if estatus == "PENDIENTE":
        updates["estatus"] = estatus
    
    count = await service.bulk_update_comprobantes(conn, uuid_list, updates, user_context=context)
    
    return templates.TemplateResponse(request,
         "compras/partials/bulk_result.html",
        {            "count": count
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
    excel_bytes = await service.export_to_excel(
        conn,
        filtros=filtros.model_dump(exclude_none=True)
    )
    
    timestamp = now_mx().strftime("%Y%m%d_%H%M%S")
    filename = f"comprobantes_pago_{timestamp}.xlsx"
    
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": content_disposition_header("attachment", filename)
        }
    )


@router.get("/export-zip")
async def export_zip(
    request: Request,
    filtros: Annotated[ComprobanteFilter, Query()],
    conn = Depends(get_db_connection),
    service: ComprasService = Depends(get_compras_service),
    _ = require_module_access("compras")
):
    """
    Descarga un ZIP con los PDF de comprobante de pago y XML de facturas
    vinculadas de los comprobantes que cumplan los filtros (agrupados por
    proveedor -> comprobante). Requiere fecha_inicio/fecha_fin acotados.
    """
    try:
        zip_bytes, filename = await service.generar_zip_periodo(
            conn,
            filtros=filtros.model_dump(exclude_none=True)
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SharePointProveedorError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except asyncpg.PostgresError as exc:
        logger.exception("Error consultando comprobantes para ZIP")
        raise HTTPException(status_code=500, detail="Error consultando comprobantes") from exc
    except httpx.HTTPError as exc:
        logger.exception("Error descargando archivos del ZIP desde SharePoint")
        raise _handle_sharepoint_error(exc) from exc
    except (RuntimeError, OSError, zipfile.BadZipFile) as exc:
        logger.exception("Error generando ZIP de comprobantes")
        raise HTTPException(status_code=502, detail="Error generando ZIP") from exc

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": content_disposition_header("attachment", filename)
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
    
    return templates.TemplateResponse(request,
         "compras/partials/proveedores_search_results.html",
        {            "proveedores": proveedores
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

    return templates.TemplateResponse(request,
         "compras/partials/estadisticas.html",
        {            "estadisticas": stats
        }
    )


# ========================================
# CARGA Y PROCESAMIENTO DE XMLs
# ========================================

@router.post("/upload-xml", response_class=HTMLResponse)
async def upload_xmls(
    request: Request,
    files: List[UploadFile] = File(...),
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context),
    service: ComprasService = Depends(get_compras_service),
    _ = require_module_access("compras", "editor")
):
    """
    Carga y procesa multiples XMLs CFDI.

    Flujo:
    1. Filtra solo archivos .xml
    2. Parsea cada XML (UUID, RFC, monto, conceptos, CFDI relacionados)
    3. Detecta tipo de factura (NORMAL, ANTICIPO, CIERRE_ANTICIPO)
    4. Busca/crea proveedor por RFC
    5. Busca coincidencias con comprobantes pendientes (3 niveles)
    6. Sube XMLs a SharePoint
    7. Retorna resultado con matches encontrados

    Returns:
        HTML con resultado de procesamiento y matches pendientes
    """
    user_id = context.get("user_db_id")

    xml_files = [f for f in files if f.filename and f.filename.lower().endswith('.xml')]

    # Validar tamano de cada archivo (max 10MB por XML)
    for f in xml_files:
        try:
            await validate_upload_size(f, max_bytes=10 * 1024 * 1024)
        except ValueError as e:
            return templates.TemplateResponse(request,
                 "compras/partials/xml_upload_result.html",
                {                    "result": None,
                    "error_msg": f"Archivo {f.filename}: {e}",
                }
            )

    if not xml_files:
        return templates.TemplateResponse(request,
             "compras/partials/xml_upload_result.html",
            {                "result": None,
                "error_msg": "No se encontraron archivos XML validos",
            }
        )

    logger.info("Procesando %d XMLs por usuario %s", len(xml_files), user_id)

    # Procesar XMLs (parseo + matching)
    result = await service.procesar_xmls(conn, xml_files, user_id)

    # Serializar resultado para Jinja2 (Pydantic -> dict plano)
    # NOTA: El upload a SharePoint se hace al confirmar el match, no aqui
    result_data = _serialize_xml_result(result)

    return templates.TemplateResponse(request,
         "compras/partials/xml_upload_result.html",
        {            "result": result_data,
            "error_msg": None,
        }
    )


@router.post("/xml-confirm-match", response_class=HTMLResponse)
async def confirm_xml_match(
    request: Request,
    uuid_factura: str = Form(...),
    id_comprobante: UUID = Form(...),
    emisor_rfc: str = Form(...),
    emisor_nombre: str = Form(...),
    total: str = Form(...),
    moneda: str = Form("MXN"),
    fecha: str = Form(""),
    tipo_factura: str = Form("NORMAL"),
    tipo_comprobante: Optional[str] = Form(None),
    metodo_pago: Optional[str] = Form(None),
    forma_pago: Optional[str] = Form(None),
    subtotal: Optional[str] = Form(None),
    conceptos_json: str = Form("[]"),
    relacionados_json: str = Form("[]"),
    xml_content_b64: str = Form(""),
    guardar_relacion: bool = Form(True),
    forzar_match: bool = Form(False),
    monto_aplicado: Optional[str] = Form(None),
    origen_match: Optional[str] = Form(None),
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context),
    service: ComprasService = Depends(get_compras_service),
    _ = require_module_access("compras", "editor")
):
    """
    Confirma el match entre un XML y un comprobante de pago.

    Recibe los datos del CFDI via form fields (serializados desde el modal).
    Actualiza comprobante, guarda relacion beneficiario-proveedor,
    almacena conceptos en historial y CFDI relacionados.

    Returns:
        HTML con resultado de confirmacion + toast OOB
    """
    user_id = context.get("user_db_id")

    # Reconstruir cfdi_data como dict
    try:
        conceptos = json.loads(conceptos_json) if conceptos_json else []
    except json.JSONDecodeError as e:
        logger.warning("Error parsing conceptos_json: %s (primeros 100 chars: %s)", e, (conceptos_json or "")[:100])
        conceptos = []

    try:
        relacionados = json.loads(relacionados_json) if relacionados_json else []
    except json.JSONDecodeError as e:
        logger.warning("Error parsing relacionados_json: %s (primeros 100 chars: %s)", e, (relacionados_json or "")[:100])
        relacionados = []

    cfdi_data = {
        "uuid": uuid_factura,
        "emisor_rfc": emisor_rfc,
        "emisor_nombre": emisor_nombre,
        "total": total,
        "subtotal": subtotal,
        "moneda": moneda,
        "fecha": fecha,
        "tipo_factura": tipo_factura,
        "tipo_comprobante": tipo_comprobante,
        "metodo_pago": metodo_pago,
        "forma_pago": forma_pago,
        "conceptos": conceptos,
        "relacionados": relacionados,
    }
    if monto_aplicado not in (None, ""):
        cfdi_data["monto_aplicado"] = monto_aplicado

    try:
        async with conn.transaction():
            resultado = await service.confirmar_match_xml(
                conn, cfdi_data, id_comprobante, user_id,
                guardar_relacion=guardar_relacion,
                forzar_match=forzar_match,
            )
    except ValueError as e:
        msg = str(e)
        exceso_monto = None
        monto_aplicado_sugerido = None
        manual_retry = None
        if msg.startswith("EXCESO_MONTO|"):
            exceso_monto, monto_aplicado_sugerido, msg = parse_exceso_monto_error(msg)
            manual_retry = _build_xml_manual_retry_context(
                uuid_factura=uuid_factura,
                id_comprobante=id_comprobante,
                emisor_rfc=emisor_rfc,
                emisor_nombre=emisor_nombre,
                total=total,
                subtotal=subtotal,
                moneda=moneda,
                fecha=fecha,
                tipo_factura=tipo_factura,
                tipo_comprobante=tipo_comprobante,
                metodo_pago=metodo_pago,
                forma_pago=forma_pago,
                conceptos_json=conceptos_json,
                relacionados_json=relacionados_json,
                xml_content_b64=xml_content_b64,
                guardar_relacion=guardar_relacion,
            )
        return templates.TemplateResponse(request,
             "compras/partials/xml_match_error.html",
            {                "message": msg,
                "exceso_monto": exceso_monto,
                "monto_aplicado": monto_aplicado_sugerido,
                "manual_retry": manual_retry,
                "modal_manual": origen_match == "modal_manual",
            },
            status_code=400,
        )

    # Subir XML a SharePoint DESPUES de confirmar el match
    sp_url = None
    if xml_content_b64:
        try:
            xml_bytes = base64.b64decode(xml_content_b64)
            xml_file = UploadFile(
                filename=f"{uuid_factura[:8]}_factura.xml",
                file=BytesIO(xml_bytes),
                headers=Headers({"content-type": "application/xml"}),
            )

            now = now_mx()
            subcarpeta = f"compras/facturas_xml/{now.strftime('%Y-%m')}"

            sp_result = await service.upload_archivo_sharepoint(
                conn, xml_file, subcarpeta,
                id_comprobante, "factura_xml", user_id,
                metadata_extra={
                    "uuid_factura": uuid_factura,
                    "emisor_rfc": emisor_rfc,
                    "tipo_factura": tipo_factura,
                }
            )
            if sp_result:
                sp_url = sp_result.get("url_sharepoint")
                logger.info("XML subido a SharePoint: %s", sp_url)
        except Exception as e:
            logger.error("Error subiendo XML a SharePoint post-confirm: %s", e)

    # Construir mensaje de exito
    items_msg = f", {resultado['conceptos_guardados']} items guardados"
    validacion_msg = ""
    if not resultado.get('validacion_ok', True):
        validacion_msg = " (advertencia: validacion de montos difiere)"

    es_parcial = resultado.get('es_parcial', False)
    if es_parcial:
        saldo = resultado.get('saldo_pendiente', 0)
        toast_msg = f"Pago parcial registrado. Saldo pendiente: ${saldo:,.2f}{validacion_msg}"
        toast_type = "warning" if not resultado.get('validacion_ok', True) else "success"
    else:
        toast_msg = f"Factura {uuid_factura[:8]}... vinculada correctamente ({tipo_factura}{items_msg}{validacion_msg})"
        toast_type = "success" if resultado.get('validacion_ok', True) else "warning"

    toast_html = templates.TemplateResponse(request,
         "shared/toast.html",
        {            "message": toast_msg,
            "type": toast_type,
        }
    ).body.decode("utf-8")

    # Resultado de confirmacion con OOB toast
    result_html = templates.TemplateResponse(request,
         "compras/partials/xml_confirm_result.html",
        {            "resultado": resultado,
        }
    ).body.decode("utf-8")

    return HTMLResponse(content=result_html + toast_html)


@router.get("/comprobantes-pendientes", response_class=HTMLResponse)
async def search_comprobantes_pendientes(
    request: Request,
    q: str = Query("", min_length=0),
    limit: int = Query(20, ge=1, le=100),
    conn = Depends(get_db_connection),
    service: ComprasService = Depends(get_compras_service),
    _ = require_module_access("compras")
):
    """
    Busqueda HTMX de comprobantes pendientes para match manual.

    Usado desde el modal de matching cuando el usuario necesita
    buscar manualmente un comprobante para vincular con el XML.

    Returns:
        HTML con filas de comprobantes candidatos
    """
    candidatos = await service.buscar_comprobantes_pendientes(
        conn, q=q if q else None, limit=limit
    )

    return templates.TemplateResponse(request,
         "compras/partials/xml_match_rows.html",
        {            "candidatos": candidatos,
        }
    )


@router.get("/comprobantes-pendientes-json")
async def get_comprobantes_pendientes_json(
    request: Request,
    q: str = Query("", min_length=0),
    moneda: str = Query("MXN"),
    limit: int = Query(30, ge=1, le=100),
    conn = Depends(get_db_connection),
    service: ComprasService = Depends(get_compras_service),
    _ = require_module_access("compras")
):
    """JSON de comprobantes pendientes para el panel de vinculacion en grupo."""
    candidatos = await service.buscar_comprobantes_para_grupo(
        conn, q=q if q else None, moneda=moneda, limit=limit
    )
    for c in candidatos:
        c['id_comprobante'] = str(c['id_comprobante'])
        c.pop('fecha_pago', None)
    return candidatos


@router.post("/xml-confirm-match-grupo")
async def confirm_xml_match_grupo(
    request: Request,
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context),
    service: ComprasService = Depends(get_compras_service),
    _ = require_module_access("compras", "editor")
):
    """Confirma la vinculacion en grupo: N facturas XML a M comprobantes de pago."""
    user_id = context.get("user_db_id")

    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Cuerpo JSON invalido") from exc

    facturas_raw = body.get("facturas", [])
    comprobante_ids_raw = body.get("comprobante_ids", [])
    forzar_excepcion = bool(body.get("forzar_excepcion", False))
    motivo_excepcion = (body.get("motivo_excepcion") or "").strip()

    if not facturas_raw or not comprobante_ids_raw:
        raise HTTPException(status_code=400, detail="Datos incompletos")

    try:
        comprobante_ids = [UUID(str(id)) for id in comprobante_ids_raw]
    except ValueError:
        raise HTTPException(status_code=400, detail="IDs de comprobante invalidos")

    try:
        async with conn.transaction():
            resultado = await service.confirmar_match_grupo(
                conn, facturas_raw, comprobante_ids, user_id,
                forzar_excepcion=forzar_excepcion,
                motivo_excepcion=motivo_excepcion,
            )
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    facturas_by_uuid = {
        str(factura.get('uuid', '')).upper(): factura
        for factura in facturas_raw
        if factura.get('uuid')
    }

    # Subir XMLs a SharePoint (no critico), con el comprobante real de cada asignacion.
    for asignacion in resultado.get('asignaciones', []):
        uuid_factura = asignacion.get('uuid_factura', '')
        factura = facturas_by_uuid.get(str(uuid_factura).upper(), {})
        xml_b64 = factura.get('xml_content_b64', '')
        id_comprobante_raw = asignacion.get('id_comprobante')
        if xml_b64 and uuid_factura:
            try:
                id_comprobante = UUID(str(id_comprobante_raw))
                xml_bytes = base64.b64decode(xml_b64)
                xml_file = UploadFile(
                    filename=f"{uuid_factura[:8]}_factura.xml",
                    file=BytesIO(xml_bytes),
                    headers=Headers({"content-type": "application/xml"}),
                )
                now = now_mx()
                subcarpeta = f"compras/facturas_xml/{now.strftime('%Y-%m')}"
                metadata = {
                    "uuid_factura": uuid_factura,
                    "monto_aplicado": asignacion.get('monto_aplicado'),
                    "origen_match": "grupo",
                }
                if motivo_excepcion:
                    metadata["motivo_excepcion"] = motivo_excepcion

                await service.upload_archivo_sharepoint(
                    conn, xml_file, subcarpeta,
                    id_comprobante, "factura_xml", user_id,
                    metadata_extra=metadata,
                )
            except (ValueError, binascii.Error, OSError, asyncpg.PostgresError) as e:
                logger.error("Error subiendo XML (grupo) a SharePoint: %s", e)

    n_f = resultado['total_facturas']
    n_p = resultado['total_comprobantes']
    cerrados = len(resultado.get('comprobantes_cerrados', []))
    cierre_msg = f". {cerrados} pago{'s' if cerrados != 1 else ''} cerrado{'s' if cerrados != 1 else ''} por tolerancia/excepcion" if cerrados else ""
    toast_html = templates.TemplateResponse(request, "shared/toast.html", {
        "message": (
            f"Grupo vinculado: {n_f} factura{'s' if n_f != 1 else ''} "
            f"en {n_p} pago{'s' if n_p != 1 else ''}{cierre_msg}"
        ),
        "type": "success",
    }).body.decode("utf-8")
    return JSONResponse({"toast_html": toast_html, "resultado": resultado})


# ========================================
# RELACIONES BENEFICIARIO-PROVEEDOR
# ========================================

@router.get("/relaciones", response_class=HTMLResponse)
async def get_relaciones(
    request: Request,
    q: str = Query("", min_length=0),
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context),
    service: ComprasService = Depends(get_compras_service),
    _ = require_module_access("compras")
):
    """
    Vista de relaciones beneficiario-proveedor aprendidas.
    Permite buscar y gestionar las asociaciones.
    """
    relaciones = await service.get_relaciones(conn, q=q if q else None)

    return templates.TemplateResponse(request,
         "compras/partials/relaciones_beneficiario.html",
        {            "relaciones": relaciones,
            "q": q,
            "role": context.get("role"),
            "current_module_role": context.get("module_roles", {}).get("compras", "viewer"),
        }
    )


@router.delete("/relaciones/{relacion_id}", response_class=HTMLResponse)
async def delete_relacion(
    request: Request,
    relacion_id: int,
    conn = Depends(get_db_connection),
    service: ComprasService = Depends(get_compras_service),
    _ = require_module_access("compras", "editor")
):
    """Elimina una relacion beneficiario-proveedor."""
    success = await service.delete_relacion(conn, relacion_id)
    if not success:
        return templates.TemplateResponse(request,
             "shared/toast.html",
            {                "message": "Relacion no encontrada",
                "type": "error",
            }
        )

    return templates.TemplateResponse(request,
         "shared/toast.html",
        {            "message": "Relacion eliminada correctamente",
            "type": "success",
        }
    )


@router.get("/comprobante/{id_comprobante}/archivos", response_class=HTMLResponse)
async def get_comprobante_archivos(
    request: Request,
    id_comprobante: UUID,
    tipo: Optional[str] = None,
    conn = Depends(get_db_connection),
    service: ComprasService = Depends(get_compras_service),
    _ = require_module_access("compras")
):
    """
    Lista los archivos (PDF y/o XML) asociados a un comprobante.
    tipo: 'pdf' | 'xml' | None (todos)
    """
    archivos = await service.get_archivos_comprobante(conn, id_comprobante)

    origen_map = {"pdf": "comprobante_pago", "xml": "factura_xml"}
    if tipo and tipo in origen_map:
        archivos = [a for a in archivos if a.get("origen_slug") == origen_map[tipo]]

    return templates.TemplateResponse(request,
         "compras/partials/comprobante_archivos.html",
        {            "archivos": archivos,
            "tipo": tipo,
            "id_comprobante": id_comprobante,
        }
    )


# ========================================
# FACTURAS PARCIALES Y REMANENTES
# ========================================

@router.get("/comprobante/{id_comprobante}/facturas-vinculadas", response_class=HTMLResponse)
async def get_facturas_vinculadas(
    request: Request,
    id_comprobante: UUID,
    conn=Depends(get_db_connection),
    service: ComprasService = Depends(get_compras_service),
    _=require_module_access("compras"),
):
    """
    Lista las facturas vinculadas a un comprobante con barra de progreso.
    Incluye botones para cerrar remanente o desvincular facturas.
    """
    comprobante = await service.get_comprobante_by_id(conn, id_comprobante)
    if not comprobante:
        raise HTTPException(status_code=404, detail="Comprobante no encontrado")

    facturas = await service.get_facturas_vinculadas(conn, id_comprobante)

    monto_total = float(comprobante.get('monto') or 0)
    monto_facturado = float(comprobante.get('monto_facturado') or 0)
    saldo_pendiente = monto_total - monto_facturado
    porcentaje = round((monto_facturado / monto_total * 100), 1) if monto_total > 0 else 0

    return templates.TemplateResponse(request,
         "compras/partials/comprobante_facturas_vinculadas.html",
        {            "comprobante": comprobante,
            "facturas": facturas,
            "monto_total": monto_total,
            "monto_facturado": monto_facturado,
            "saldo_pendiente": saldo_pendiente,
            "porcentaje": porcentaje,
        },
    )


@router.delete("/comprobante/{id_comprobante}/factura/{uuid_factura}", response_class=HTMLResponse)
async def desvincular_factura(
    request: Request,
    id_comprobante: UUID,
    uuid_factura: str,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    service: ComprasService = Depends(get_compras_service),
    _=require_module_access("compras", "editor"),
):
    """Desvincula una factura de un comprobante y recalcula su estado."""
    try:
        resultado = await service.desvincular_factura(conn, id_comprobante, uuid_factura)
    except ValueError as e:
        return templates.TemplateResponse(request,
             "shared/toast.html",
            {"message": str(e), "type": "error"},
        )

    # Retornar panel actualizado + toast
    comprobante = await service.get_comprobante_by_id(conn, id_comprobante)
    facturas = await service.get_facturas_vinculadas(conn, id_comprobante)

    monto_total = float(comprobante.get('monto') or 0)
    monto_facturado = float(comprobante.get('monto_facturado') or 0)
    saldo_pendiente = monto_total - monto_facturado
    porcentaje = round((monto_facturado / monto_total * 100), 1) if monto_total > 0 else 0

    panel_html = templates.TemplateResponse(request,
         "compras/partials/comprobante_facturas_vinculadas.html",
        {            "comprobante": comprobante,
            "facturas": facturas,
            "monto_total": monto_total,
            "monto_facturado": monto_facturado,
            "saldo_pendiente": saldo_pendiente,
            "porcentaje": porcentaje,
        },
    ).body.decode("utf-8")

    toast_html = templates.TemplateResponse(request,
         "shared/toast.html",
        {"message": "Factura desvinculada correctamente", "type": "success"},
    ).body.decode("utf-8")

    return HTMLResponse(content=panel_html + toast_html)


@router.post("/comprobante/{id_comprobante}/cerrar-remanente", response_class=HTMLResponse)
async def cerrar_remanente(
    request: Request,
    id_comprobante: UUID,
    motivo: str = Form(...),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    service: ComprasService = Depends(get_compras_service),
    _=require_module_access("compras", "editor"),
):
    """Cierra un comprobante indicando que no habrá más facturas (remanente)."""
    user_id = context.get("user_db_id")

    try:
        await service.cerrar_remanente(conn, id_comprobante, motivo, user_id)
    except ValueError as e:
        return templates.TemplateResponse(request,
             "shared/toast.html",
            {"message": str(e), "type": "error"},
        )

    # Retornar panel actualizado + toast
    comprobante = await service.get_comprobante_by_id(conn, id_comprobante)
    facturas = await service.get_facturas_vinculadas(conn, id_comprobante)

    monto_total = float(comprobante.get('monto') or 0)
    monto_facturado = float(comprobante.get('monto_facturado') or 0)
    saldo_pendiente = monto_total - monto_facturado
    porcentaje = round((monto_facturado / monto_total * 100), 1) if monto_total > 0 else 0

    panel_html = templates.TemplateResponse(request,
         "compras/partials/comprobante_facturas_vinculadas.html",
        {            "comprobante": comprobante,
            "facturas": facturas,
            "monto_total": monto_total,
            "monto_facturado": monto_facturado,
            "saldo_pendiente": saldo_pendiente,
            "porcentaje": porcentaje,
        },
    ).body.decode("utf-8")

    toast_html = templates.TemplateResponse(request,
         "shared/toast.html",
        {            "message": f"Comprobante cerrado. Remanente: ${saldo_pendiente:,.2f}",
            "type": "success",
        },
    ).body.decode("utf-8")

    return HTMLResponse(content=panel_html + toast_html)


@router.post("/comprobante/{id_comprobante}/reabrir", response_class=HTMLResponse)
async def reabrir_comprobante(
    request: Request,
    id_comprobante: UUID,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    service: ComprasService = Depends(get_compras_service),
    _=require_module_access("compras", "editor"),
):
    """Reabre un comprobante CERRADO."""
    try:
        await service.reabrir_comprobante(conn, id_comprobante)
    except ValueError as e:
        return templates.TemplateResponse(request,
             "shared/toast.html",
            {"message": str(e), "type": "error"},
        )

    # Retornar panel actualizado + toast
    comprobante = await service.get_comprobante_by_id(conn, id_comprobante)
    facturas = await service.get_facturas_vinculadas(conn, id_comprobante)

    monto_total = float(comprobante.get('monto') or 0)
    monto_facturado = float(comprobante.get('monto_facturado') or 0)
    saldo_pendiente = monto_total - monto_facturado
    porcentaje = round((monto_facturado / monto_total * 100), 1) if monto_total > 0 else 0

    panel_html = templates.TemplateResponse(request,
         "compras/partials/comprobante_facturas_vinculadas.html",
        {            "comprobante": comprobante,
            "facturas": facturas,
            "monto_total": monto_total,
            "monto_facturado": monto_facturado,
            "saldo_pendiente": saldo_pendiente,
            "porcentaje": porcentaje,
        },
    ).body.decode("utf-8")

    toast_html = templates.TemplateResponse(request,
         "shared/toast.html",
        {"message": "Comprobante reabierto correctamente", "type": "success"},
    ).body.decode("utf-8")

    return HTMLResponse(content=panel_html + toast_html)


# ========================================
# ADMIN — BACKFILL TIPO CAMBIO MATERIALES
# ========================================

@router.post("/admin/backfill-tc-materiales")
async def backfill_tc_materiales(
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context),
    service: ComprasService = Depends(get_compras_service),
    _ = require_module_access("compras", "admin")
):
    """
    Backfill de tipo_cambio_xml en tb_materiales_historial desde XMLs en SharePoint.

    Para cada factura XML ya confirmada que tenga historial de materiales sin TC,
    descarga el XML de SharePoint, re-parsea el TipoCambio y actualiza los registros.

    Returns:
        JSON con resumen: actualizados, sin_tc_en_xml, errores
    """
    from .db_service import get_db_service
    from core.integrations.sharepoint import get_sharepoint_service
    from core.microsoft import get_ms_auth
    from .xml_extractor import parse_cfdi_xml

    db_svc = get_db_service()

    rows = await db_svc.get_xml_attachments_for_backfill(conn)
    if not rows:
        return {"actualizados": 0, "sin_tc_en_xml": 0, "errores": 0, "mensaje": "No hay registros pendientes de backfill"}

    # Obtener token de acceso para SharePoint
    ms_auth = get_ms_auth()
    try:
        access_token = await ms_auth.get_application_token()
        if not access_token:
            raise ValueError("Token vacío")
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"No se pudo obtener token MS: {e}")

    sp = get_sharepoint_service(access_token)
    config = await sp._resolve_config(conn)
    sp.site_id = config.get("site_id")
    sp.drive_id = config.get("drive_id")

    actualizados = 0
    sin_tc = 0
    errores = 0

    for row in rows:
        drive_item_id = row.get("drive_item_id")
        nombre_archivo = row.get("nombre_archivo") or "unknown.xml"
        uuid_factura = row.get("uuid_factura")

        if not drive_item_id or not uuid_factura:
            errores += 1
            continue

        try:
            xml_bytes = await sp.download_file_by_item_id(conn, drive_item_id)
            cfdi = parse_cfdi_xml(xml_bytes, nombre_archivo)

            if cfdi.tipo_cambio_xml:
                updated = await db_svc.update_tc_materiales(conn, uuid_factura, cfdi.tipo_cambio_xml)
                if updated > 0:
                    actualizados += updated
                    logger.info("TC backfill: %s -> %s (%d filas)", uuid_factura[:8], cfdi.tipo_cambio_xml, updated)
                else:
                    sin_tc += 1
            else:
                sin_tc += 1

        except Exception as e:
            logger.error("Error en backfill TC para %s (%s): %s", uuid_factura, nombre_archivo, e)
            errores += 1

    return {
        "actualizados": actualizados,
        "sin_tc_en_xml": sin_tc,
        "errores": errores,
        "total_procesados": len(rows),
    }


# ========================================
# XML STAGING — PENDIENTES
# ========================================

@router.get("/xml-staging/pendientes", response_class=HTMLResponse)
async def get_xml_staging_pendientes(
    request: Request,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    service: ComprasService = Depends(get_compras_service),
    _=require_module_access("compras", "editor"),
):
    """Lista XMLs en staging con estado PENDIENTE para el modal."""
    pendientes = await service.get_xml_staging_pendientes(conn)
    return templates.TemplateResponse(
        request,
        "compras/partials/xml_staging_modal.html",
        {
            "pendientes": pendientes,
            "role": context.get("role"),
        },
    )


@router.delete("/xml-staging/{uuid_factura}", response_class=HTMLResponse)
async def delete_xml_staging(
    request: Request,
    uuid_factura: str,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    service: ComprasService = Depends(get_compras_service),
    _=require_module_access("compras", "editor"),
):
    """Elimina un XML pendiente de staging."""
    eliminado = await service.eliminar_xml_staging(conn, uuid_factura)
    if not eliminado:
        return templates.TemplateResponse(
            request,
            "shared/toast.html",
            {"message": "XML no encontrado o ya confirmado", "type": "error"},
        )
    pendientes = await service.get_xml_staging_pendientes(conn)
    lista_html = templates.TemplateResponse(
        request,
        "compras/partials/xml_staging_lista.html",
        {"pendientes": pendientes},
    ).body.decode("utf-8")
    toast_html = templates.TemplateResponse(
        request,
        "shared/toast.html",
        {"message": "XML eliminado del staging", "type": "success"},
    ).body.decode("utf-8")
    return HTMLResponse(content=lista_html + toast_html)


# ========================================
# PROVEEDOR DOCUMENTOS (Gap 8)
# ========================================

def _clean_optional_text(value: Optional[str]) -> Optional[str]:
    return (value.strip() or None) if value else None


def _parse_optional_iso_date(value: Optional[str], label: str) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{label} invalida") from exc


def _parse_periodo(value: Optional[str]) -> Optional[str]:
    periodo = _clean_optional_text(value)
    if not periodo:
        return None
    try:
        if len(periodo) != 7:
            raise ValueError("longitud incorrecta")
        date.fromisoformat(f"{periodo}-01")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Periodo invalido") from exc
    return periodo


def _proveedor_docs_ctx(documentos: list[dict], id_proveedor: UUID) -> dict:
    return {
        "documentos": documentos,
        "id_proveedor": id_proveedor,
        "today": today_mx(),
    }


@router.get("/proveedores/{id_proveedor}/documentos", include_in_schema=False)
async def get_proveedor_documentos(
    request: Request,
    id_proveedor: UUID,
    conn = Depends(get_db_connection),
    proveedores_service: ProveedoresService = Depends(get_proveedores_service),
    _ = require_module_access("compras"),
):
    """Lista documentos de un proveedor (modal partial)."""
    docs = await proveedores_service.get_documentos_proveedor(conn, id_proveedor)
    proveedor = await proveedores_service.get_proveedor_detalle(conn, id_proveedor)
    return templates.TemplateResponse(
        request, "compras/partials/modal_proveedor_docs.html",
        {**_proveedor_docs_ctx(docs, id_proveedor), "proveedor": proveedor}
    )


@router.post("/proveedores/{id_proveedor}/documentos", include_in_schema=False)
async def subir_documento_proveedor(
    request: Request,
    id_proveedor: UUID,
    tipo_documento: str = Form(...),
    tipo_persona: str = Form("MORAL"),
    fecha_documento: Optional[str] = Form(None),
    fecha_vencimiento: Optional[str] = Form(None),
    periodo: Optional[str] = Form(None),
    nombre_documento_personalizado: Optional[str] = Form(None),
    notas: Optional[str] = Form(None),
    archivo: UploadFile = File(...),
    context = Depends(get_current_user_context),
    conn = Depends(get_db_connection),
    compras_service: ComprasService = Depends(get_compras_service),
    proveedores_service: ProveedoresService = Depends(get_proveedores_service),
    _ = require_module_access("compras", "editor"),
):
    """Sube un documento de proveedor a SharePoint y registra en BD."""
    user_id = context.get("user_db_id")
    fecha_doc = _parse_optional_iso_date(fecha_documento, "Fecha de documento")
    venc = _parse_optional_iso_date(fecha_vencimiento, "Fecha de vencimiento")
    periodo_clean = _parse_periodo(periodo)
    nombre_personalizado = _clean_optional_text(nombre_documento_personalizado)
    notas_clean = _clean_optional_text(notas)
    proveedor = await proveedores_service.get_proveedor_detalle(conn, id_proveedor)
    if not proveedor:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")

    subcarpeta = proveedores_service.build_sharepoint_subcarpeta(
        proveedor,
        tipo_documento,
    )

    try:
        result = await compras_service.upload_archivo_sharepoint(
            conn, archivo,
            subcarpeta=subcarpeta,
            id_comprobante=None,
            origen_slug="proveedor_documento",
            user_id=user_id,
            metadata_extra={
                "tipo_documento": tipo_documento,
                "tipo_persona": tipo_persona,
                "periodo": periodo_clean,
                "nombre_documento_personalizado": nombre_personalizado,
            }
        )
    except (ValueError, RuntimeError, OSError) as e:
        logger.exception("Error subiendo documento a SharePoint")
        raise HTTPException(status_code=500, detail=f"Error al subir a SharePoint: {e}") from e

    if not result or not result.get("url_sharepoint"):
        raise HTTPException(status_code=500, detail="No se pudo obtener URL de SharePoint")

    try:
        id_attachment = (
            UUID(result["id_documento_attachment"])
            if result.get("id_documento_attachment")
            else None
        )
        await proveedores_service.registrar_documento_proveedor(
            conn, id_proveedor, tipo_documento, tipo_persona,
            result["url_sharepoint"],
            fecha_documento=fecha_doc,
            fecha_vencimiento=venc,
            subido_por=user_id,
            notas=notas_clean,
            id_documento_attachment=id_attachment,
            nombre_archivo=result.get("nombre"),
            tipo_contenido=result.get("tipo_contenido"),
            tamano_bytes=result.get("tamano_bytes"),
            drive_item_id=result.get("drive_item_id"),
            parent_drive_id=result.get("parent_drive_id"),
            folder_path=result.get("folder_path"),
            periodo=periodo_clean,
            nombre_documento_personalizado=nombre_personalizado,
        )
    except asyncpg.PostgresError as exc:
        logger.exception("Error registrando documento de proveedor")
        raise HTTPException(status_code=500, detail="Error al registrar documento de proveedor") from exc

    docs = await proveedores_service.get_documentos_proveedor(conn, id_proveedor)
    return templates.TemplateResponse(
        request, "compras/partials/modal_proveedor_docs.html",
        {**_proveedor_docs_ctx(docs, id_proveedor), "proveedor": proveedor}
    )


@router.delete("/proveedores/{id_proveedor}/documentos/{doc_id}", include_in_schema=False)
async def eliminar_documento_proveedor(
    request: Request,
    id_proveedor: UUID,
    doc_id: UUID,
    conn = Depends(get_db_connection),
    proveedores_service: ProveedoresService = Depends(get_proveedores_service),
    _ = require_module_access("compras", "editor"),
):
    """Elimina un documento de proveedor."""
    deleted = await proveedores_service.eliminar_documento_proveedor(conn, doc_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    docs = await proveedores_service.get_documentos_proveedor(conn, id_proveedor)
    proveedor = await proveedores_service.get_proveedor_detalle(conn, id_proveedor)
    return templates.TemplateResponse(
        request, "compras/partials/modal_proveedor_docs.html",
        {**_proveedor_docs_ctx(docs, id_proveedor), "proveedor": proveedor}
    )


# ========================================
# MINI ALMACÉN (Gap 9)
# ========================================

@router.get("/inventario", include_in_schema=False)
async def get_inventario(
    request: Request,
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context),
    _ = require_module_access("compras"),
):
    """Lista de inventario (mini almacén)."""
    from .db_service import get_db_service
    db_svc = get_db_service()
    items = await db_svc.get_inventario(conn)
    proveedores = await db_svc.get_proveedores_activos(conn)
    unidades = await db_svc.get_unidades_medida(conn)
    return templates.TemplateResponse(
        request, "compras/partials/inventario.html", {
            "items": items,
            "proveedores": proveedores,
            "unidades": unidades,
            "role": context.get("role"),
            "current_module_role": context.get("module_roles", {}).get("compras", "viewer"),
        }
    )


@router.post("/inventario", include_in_schema=False)
async def registrar_inventario(
    request: Request,
    descripcion: str = Form(...),
    cantidad: float = Form(...),
    unidad_medida: str = Form(None),
    ubicacion: str = Form(None),
    id_proveedor: str = Form(None),
    notas: str = Form(None),
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context),
    _ = require_module_access("compras", "editor"),
):
    """Registra entrada de material al inventario."""
    from .db_service import get_db_service
    db_svc = get_db_service()
    prov = UUID(id_proveedor) if id_proveedor else None
    await db_svc.insert_inventario(
        conn, descripcion, cantidad, unidad_medida, ubicacion, prov, None, notas
    )
    items = await db_svc.get_inventario(conn)
    proveedores = await db_svc.get_proveedores_activos(conn)
    unidades = await db_svc.get_unidades_medida(conn)
    return templates.TemplateResponse(
        request, "compras/partials/inventario.html", {
            "items": items,
            "proveedores": proveedores,
            "unidades": unidades,
            "role": context.get("role"),
            "current_module_role": context.get("module_roles", {}).get("compras", "viewer"),
        }
    )


@router.patch("/inventario/{inventario_id}", include_in_schema=False)
async def actualizar_inventario(
    request: Request,
    inventario_id: UUID,
    conn = Depends(get_db_connection),
    _ = require_module_access("compras", "editor"),
):
    """Actualiza cantidad, ubicación o notas del inventario."""
    form = await request.form()
    campos = {}
    for key in ('cantidad_disponible', 'ubicacion', 'notas'):
        val = form.get(key)
        if val is not None and val != '':
            if key == 'cantidad_disponible':
                campos[key] = float(val)
            else:
                campos[key] = val.strip()
    activo_val = form.get('activo')
    if activo_val is not None and activo_val != '':
        campos['activo'] = activo_val in ('true', 'True', '1', 'on')

    from .db_service import get_db_service
    db_svc = get_db_service()
    await db_svc.update_inventario(conn, inventario_id, **campos)
    items = await db_svc.get_inventario(conn)
    unidades = await db_svc.get_unidades_medida(conn)
    return templates.TemplateResponse(
        request, "compras/partials/inventario.html", {"items": items, "unidades": unidades}
    )


# ========================================
# CRUD PROVEEDORES
# ========================================

def _prov_ctx(context: dict, current_module_role: str = None) -> dict:
    """Contexto compartido de permisos para vistas de proveedor."""
    return {
        "role": context.get("role"),
        "current_module_role": current_module_role or context.get("module_roles", {}).get("compras", "viewer"),
    }


@router.get("/proveedores/ui", include_in_schema=False)
async def get_proveedores_ui(
    request: Request,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    proveedores_service: ProveedoresService = Depends(get_proveedores_service),
    _=require_module_access("compras"),
    q: str = Query(""),
    solo_activos: bool = Query(False),
    page: int = Query(1, ge=1),
):
    """Vista principal de proveedores (full-page o partial según HTMX)."""
    is_htmx = request.headers.get("hx-request")
    is_restore = request.headers.get("hx-history-restore-request")

    per_page = 50
    proveedores = await proveedores_service.get_proveedores_lista(conn, busqueda=q, solo_activos=solo_activos, page=page, per_page=per_page)
    total = await proveedores_service.count_proveedores(conn, busqueda=q, solo_activos=solo_activos)
    total_pages = max(1, -(-total // per_page))

    mod_role = context.get("module_roles", {}).get("compras", "viewer")
    ctx = {
        **_prov_ctx(context, mod_role),
        "proveedores": proveedores,
        "total": total,
        "total_pages": total_pages,
        "page": page,
        "busqueda": q,
        "solo_activos": solo_activos,
    }

    if is_htmx and not is_restore:
        return templates.TemplateResponse(request, "compras/partials/proveedores_content.html", ctx)
    return templates.TemplateResponse(request, "compras/proveedores.html", ctx)


@router.get("/proveedores/lista", include_in_schema=False)
async def get_proveedores_lista(
    request: Request,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    proveedores_service: ProveedoresService = Depends(get_proveedores_service),
    _=require_module_access("compras"),
    q: str = Query(""),
    solo_activos: bool = Query(False),
    page: int = Query(1, ge=1),
):
    """Partial: tabla paginada de proveedores (reemplazada vía HTMX)."""
    per_page = 50
    proveedores = await proveedores_service.get_proveedores_lista(conn, busqueda=q, solo_activos=solo_activos, page=page, per_page=per_page)
    total = await proveedores_service.count_proveedores(conn, busqueda=q, solo_activos=solo_activos)
    total_pages = max(1, -(-total // per_page))

    mod_role = context.get("module_roles", {}).get("compras", "viewer")
    return templates.TemplateResponse(request, "compras/partials/proveedores_tabla.html", {
        **_prov_ctx(context, mod_role),
        "proveedores": proveedores,
        "total": total,
        "total_pages": total_pages,
        "page": page,
        "busqueda": q,
        "solo_activos": solo_activos,
    })


@router.get("/proveedores/check-rfc", include_in_schema=False)
async def check_rfc_proveedor(
    request: Request,
    conn=Depends(get_db_connection),
    proveedores_service: ProveedoresService = Depends(get_proveedores_service),
    _=require_module_access("compras", "editor"),
    rfc: str = Query(""),
    excluir_id: str = Query(""),
):
    """Valida en tiempo real si un RFC ya está registrado."""
    if not rfc or len(rfc) < 12:
        return HTMLResponse("")
    excluir_uuid = UUID(excluir_id) if excluir_id else None
    duplicado = await proveedores_service.check_rfc_duplicado(conn, rfc.upper().strip(), excluir_id=excluir_uuid)
    if duplicado:
        return HTMLResponse(
            '<span class="text-red-600 font-medium">Este RFC ya está registrado.</span>'
        )
    return HTMLResponse(
        '<span class="text-green-600 font-medium">RFC disponible.</span>'
    )


@router.get("/proveedores/modal", include_in_schema=False)
async def get_modal_nuevo_proveedor(
    request: Request,
    _=require_module_access("compras", "editor"),
):
    """Partial: modal para crear un nuevo proveedor."""
    return templates.TemplateResponse(request, "compras/partials/modal_proveedor_form.html", {})


@router.get("/proveedores/{id_proveedor}/modal", include_in_schema=False)
async def get_modal_editar_proveedor(
    request: Request,
    id_proveedor: UUID,
    conn=Depends(get_db_connection),
    proveedores_service: ProveedoresService = Depends(get_proveedores_service),
    _=require_module_access("compras", "editor"),
):
    """Partial: modal para editar un proveedor existente."""
    proveedor = await proveedores_service.get_proveedor_detalle(conn, id_proveedor)
    if not proveedor:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")
    return templates.TemplateResponse(
        request, "compras/partials/modal_proveedor_form.html", {"proveedor": proveedor}
    )


@router.post("/proveedores", include_in_schema=False)
async def crear_proveedor(
    request: Request,
    rfc: str = Form(...),
    razon_social: str = Form(...),
    nombre_comercial: str = Form(""),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    proveedores_service: ProveedoresService = Depends(get_proveedores_service),
    _=require_module_access("compras", "editor"),
):
    """Crea un nuevo proveedor y retorna la tabla actualizada."""
    if not rfc or not razon_social:
        raise HTTPException(status_code=400, detail="RFC y Razón Social son obligatorios")

    duplicado = await proveedores_service.check_rfc_duplicado(conn, rfc.upper().strip())
    if duplicado:
        raise HTTPException(status_code=400, detail=f"El RFC {rfc.upper()} ya está registrado")

    await proveedores_service.crear_proveedor(conn, rfc, razon_social, nombre_comercial or None)

    mod_role = context.get("module_roles", {}).get("compras", "viewer")
    proveedores = await proveedores_service.get_proveedores_lista(conn, per_page=50)
    total = await proveedores_service.count_proveedores(conn)
    return templates.TemplateResponse(request, "compras/partials/proveedores_tabla.html", {
        **_prov_ctx(context, mod_role),
        "proveedores": proveedores,
        "total": total,
        "total_pages": max(1, -(-total // 50)),
        "page": 1,
        "busqueda": "",
        "solo_activos": False,
    })


@router.patch("/proveedores/{id_proveedor}", include_in_schema=False)
async def actualizar_proveedor(
    request: Request,
    id_proveedor: UUID,
    rfc: str = Form(...),
    razon_social: str = Form(...),
    nombre_comercial: str = Form(""),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    proveedores_service: ProveedoresService = Depends(get_proveedores_service),
    _=require_module_access("compras", "editor"),
):
    """Actualiza datos de un proveedor y retorna la tabla actualizada."""
    duplicado = await proveedores_service.check_rfc_duplicado(conn, rfc.upper().strip(), excluir_id=id_proveedor)
    if duplicado:
        raise HTTPException(status_code=400, detail=f"El RFC {rfc.upper()} ya está registrado en otro proveedor")

    updated = await proveedores_service.actualizar_proveedor(conn, id_proveedor, rfc, razon_social, nombre_comercial or None)
    if not updated:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")

    mod_role = context.get("module_roles", {}).get("compras", "viewer")
    proveedores = await proveedores_service.get_proveedores_lista(conn, per_page=50)
    total = await proveedores_service.count_proveedores(conn)
    return templates.TemplateResponse(request, "compras/partials/proveedores_tabla.html", {
        **_prov_ctx(context, mod_role),
        "proveedores": proveedores,
        "total": total,
        "total_pages": max(1, -(-total // 50)),
        "page": 1,
        "busqueda": "",
        "solo_activos": False,
    })


@router.patch("/proveedores/{id_proveedor}/toggle", include_in_schema=False)
async def toggle_proveedor(
    request: Request,
    id_proveedor: UUID,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    proveedores_service: ProveedoresService = Depends(get_proveedores_service),
    _=require_module_access("compras", "editor"),
):
    """Alterna el estado activo/inactivo de un proveedor — retorna solo la fila."""
    proveedor = await proveedores_service.toggle_proveedor_activo(conn, id_proveedor)
    if not proveedor:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")

    mod_role = context.get("module_roles", {}).get("compras", "viewer")
    return templates.TemplateResponse(
        request, "compras/partials/proveedores_fila.html",
        {**_prov_ctx(context, mod_role), "p": proveedor}
    )
