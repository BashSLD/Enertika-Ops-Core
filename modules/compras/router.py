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
from fastapi.responses import HTMLResponse, Response
from typing import List, Optional
from uuid import UUID
from datetime import date, datetime
import logging
import json

from core.validation import validate_upload_size
import base64
from io import BytesIO
from starlette.datastructures import Headers

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
    ComprobanteUpdateForm,
    CfdiData,
)
from typing import Annotated

logger = logging.getLogger("ComprasModule")
templates = Jinja2Templates(directory="templates")
templates.env.globals["DEBUG_MODE"] = settings.DEBUG_MODE


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
    from decimal import Decimal

    def _serialize_cfdi(cfdi):
        """Convierte CfdiData Pydantic a dict plano."""
        d = cfdi.model_dump() if hasattr(cfdi, 'model_dump') else dict(cfdi)
        # Convertir enums a string
        if 'tipo_factura' in d and hasattr(d['tipo_factura'], 'value'):
            d['tipo_factura'] = d['tipo_factura'].value
        # Convertir Decimal a float/str
        for key in ('total', 'subtotal'):
            if key in d and isinstance(d[key], Decimal):
                d[key] = float(d[key])
        # Convertir conceptos Decimal
        for c in d.get('conceptos', []):
            for k in ('cantidad', 'valor_unitario', 'importe'):
                if k in c and isinstance(c[k], Decimal):
                    c[k] = float(c[k])
        return d

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

    # Vista default (PENDIENTE + mes actual)
    page = 1
    per_page = 50
    comprobantes, total = await service.get_comprobantes_default_view(conn)

    estadisticas = await service.get_estadisticas_generales(
        conn,
        estatus="PENDIENTE"
    )

    pages = (total + per_page - 1) // per_page if total > 0 else 1
    
    template_context = {
        "user_name": context.get("user_name"),
        "role": context.get("role"),
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
        "filtros": {
            "fecha_inicio": "",
            "fecha_fin": "",
            "estatus": "SIN_COMPLETAR"
        },
        "estadisticas": estadisticas
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
    _ = require_module_access("compras")
):
    """
    Lista comprobantes con filtros (HTMX partial).
    """
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
            "filtros": {
                "fecha_inicio": filtros.fecha_inicio.isoformat() if filtros.fecha_inicio else "",
                "fecha_fin": filtros.fecha_fin.isoformat() if filtros.fecha_fin else "",
                "estatus": filtros.estatus if filtros.estatus is not None else "TODOS",
                "id_zona": filtros.id_zona or "",
                "id_proyecto": str(filtros.id_proyecto) if filtros.id_proyecto else "",
                "id_categoria": filtros.id_categoria or "",
            }
        }
    )

    # Renderizar stats OOB
    stats_html = templates.TemplateResponse(request,
        "compras/partials/estadisticas.html",
        {"estadisticas": estadisticas}
    ).body.decode("utf-8")
    
    # Injectar OOB en la respuesta explícitamente
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
    
    return templates.TemplateResponse(request,
         "compras/partials/modal_editar.html",
        {            "comprobante": comprobante,
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
    updates = form.model_dump(exclude_none=True)
    
    comprobante = await service.update_comprobante(conn, id_comprobante, updates, user_context=context)
    catalogos = await service.get_catalogos(conn)
    
    return templates.TemplateResponse(request,
         "compras/partials/row_comprobante.html",
        {            "comprobante": comprobante,
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
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"comprobantes_pago_{timestamp}.xlsx"
    
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
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
    if not user_id:
        raise HTTPException(status_code=401, detail="Usuario no identificado")

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
    if not user_id:
        raise HTTPException(status_code=401, detail="Usuario no identificado")

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

    try:
        async with conn.transaction():
            resultado = await service.confirmar_match_xml(
                conn, cfdi_data, id_comprobante, user_id,
                guardar_relacion=guardar_relacion
            )
    except ValueError as e:
        return templates.TemplateResponse(request,
             "shared/toast.html",
            {                "message": str(e),
                "type": "error",
            }
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

            now = datetime.now()
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
    if not user_id:
        raise HTTPException(status_code=401, detail="Usuario no identificado")

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