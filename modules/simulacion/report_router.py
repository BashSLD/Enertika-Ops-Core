# modules/simulacion/report_router.py
"""
Endpoints para el módulo de Reportes de Simulación.

Este archivo contiene SOLO la orquestación HTTP.
Toda la lógica de negocio está en report_service.py
"""

from fastapi import APIRouter, Request, Depends, Query, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse
from datetime import date, datetime, timedelta
from typing import Optional
from uuid import UUID
import logging

from core.database import get_db_connection
from core.security import get_current_user_context
from core.permissions import require_module_access

from .report_service import (
    ReportesSimulacionService, 
    get_reportes_service,
    FiltrosReporte
)
from core.config_service import ConfigService

logger = logging.getLogger("ReportesSimulacionRouter")
templates = Jinja2Templates(directory="templates")

router = APIRouter(prefix="/simulacion/reportes", tags=["Simulación - Reportes"])


# =============================================================================
# HELPERS
# =============================================================================

def parse_filtros(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    tech_id: Optional[str] = None,
    type_id: Optional[str] = None,
    status_id: Optional[str] = None,
    user_id: Optional[str] = None
) -> FiltrosReporte:
    """
    Parsea y valida los parámetros de filtro del request.
    
    Defaults:
    - fecha_inicio: Primer día del mes actual
    - fecha_fin: Hoy
    """
    today = date.today()
    
    # Fechas con defaults
    if start_date:
        try:
            dt_start = date.fromisoformat(start_date)
        except ValueError:
            dt_start = today.replace(day=1)
    else:
        dt_start = today.replace(day=1)
    
    if end_date:
        try:
            dt_end = date.fromisoformat(end_date)
        except ValueError:
            dt_end = today
    else:
        dt_end = today
    
    # Parsing seguro de enteros (strings vacíos -> None)
    parsed_tech = int(tech_id) if tech_id and tech_id.isdigit() else None
    parsed_type = int(type_id) if type_id and type_id.isdigit() else None
    parsed_status = int(status_id) if status_id and status_id.isdigit() else None
    
    # Usuario UUID
    responsable_uuid = None
    if user_id:
        try:
            responsable_uuid = UUID(user_id)
        except ValueError:
            pass
    
    # Limitación de rango a 1 año (12 meses) para evitar duplicidad en tabla mensual
    # Si el rango es de 365 días o más (toca el mes 13), ajustamos a 364
    dias_diff = (dt_end - dt_start).days
    if dias_diff >= 365:
        dt_end = dt_start + timedelta(days=364)
    
    return FiltrosReporte(
        fecha_inicio=dt_start,
        fecha_fin=dt_end,
        id_tecnologia=parsed_tech,
        id_tipo_solicitud=parsed_type,
        id_estatus=parsed_status,
        responsable_id=responsable_uuid
    )


# =============================================================================
# ENDPOINTS DE UI (Templates HTML)
# =============================================================================

@router.api_route("/ui", methods=["GET", "HEAD"], include_in_schema=False)
async def get_reportes_ui(
    request: Request,
    context = Depends(get_current_user_context),
    conn = Depends(get_db_connection),
    service: ReportesSimulacionService = Depends(get_reportes_service),
    _ = require_module_access("simulacion")
):
    """
    Renderiza el dashboard principal de reportes (SIMPLIFICADO).
    """
    # Obtener catálogos para filtros
    catalogos = await service.get_catalogos_filtros(conn)
    
    # Datos iniciales (mes actual)
    filtros = parse_filtros()
    metricas = await service.get_metricas_generales(conn, filtros)
    graficas = await service.get_datos_graficas(conn, filtros)
    
    # Obtener umbrales dinámicos para inyección en template
    u_interno = await ConfigService.get_umbrales_kpi(conn, "kpi_interno", "SIMULACION")
    u_compromiso = await ConfigService.get_umbrales_kpi(conn, "kpi_compromiso", "SIMULACION")

    template_data = {
        "request": request,
        "user_name": context.get("user_name"),
        "role": context.get("role"),
        "module_roles": context.get("module_roles", {}),
        "current_module_role": context.get("module_roles", {}).get("simulacion", "viewer"),
        "catalogos": catalogos,
        "metricas": metricas,
        "graficas": graficas,
        "filtros_aplicados": {
            "fecha_inicio": filtros.fecha_inicio.isoformat(),
            "fecha_fin": filtros.fecha_fin.isoformat()
        },
        # Inyección de umbrales para evitar hardcodes en templates
        "umbral_verde_interno": u_interno.umbral_excelente,
        "umbral_ambar_interno": u_interno.umbral_bueno,
        "umbral_verde_compromiso": u_compromiso.umbral_excelente,
        "umbral_ambar_compromiso": u_compromiso.umbral_bueno,
    }
    
    # Detección HTMX vs carga directa
    if request.headers.get("hx-request"):
        return templates.TemplateResponse("simulacion/reportes/tabs.html", template_data)
    else:
        return templates.TemplateResponse("simulacion/reportes/dashboard.html", template_data)


@router.api_route("/analisis-detallado", methods=["GET", "HEAD"], include_in_schema=False)
async def get_analisis_detallado(
    request: Request,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    tech_id: Optional[str] = None,
    type_id: Optional[str] = None,
    status_id: Optional[str] = None,
    user_id: Optional[str] = None,
    context = Depends(get_current_user_context),
    conn = Depends(get_db_connection),
    service: ReportesSimulacionService = Depends(get_reportes_service),
    _ = require_module_access("simulacion")
):
    """Vista de Análisis Detallado con KPIs Duales."""
    
    catalogos = await service.get_catalogos_filtros(conn)
    filtros = parse_filtros(start_date, end_date, tech_id, type_id, status_id, user_id)
    
    # Obtener umbrales dinámicos para inyección en template
    u_interno = await ConfigService.get_umbrales_kpi(conn, "kpi_interno", "SIMULACION")
    u_compromiso = await ConfigService.get_umbrales_kpi(conn, "kpi_compromiso", "SIMULACION")
    
    # Obtener todos los datos
    metricas = await service.get_metricas_generales(conn, filtros)
    metricas_tech = await service.get_metricas_por_tecnologia(conn, filtros)
    tabla_contab = await service.get_tabla_contabilizacion(conn, filtros)
    metricas_usuarios = await service.get_detalle_por_usuario(conn, filtros)
    resumen_mensual = await service.get_resumen_mensual(conn, filtros)
    
    # Obtener motivo de retrabajo principal
    motivo_retrabajo = await service.get_motivo_retrabajo_principal(conn, filtros)
    
    # Generar resumen ejecutivo
    resumen_ejecutivo = await service.generar_resumen_ejecutivo(
        conn,
        metricas=metricas,
        usuarios=metricas_usuarios,
        filas_tipo=tabla_contab,
        filtros=filtros,
        motivo_retrabajo_principal=motivo_retrabajo,
        metricas_tecnologia=metricas_tech,
        resumen_mensual=resumen_mensual
    )
    
    # Generar lista de meses
    meses = []
    current = filtros.fecha_inicio.replace(day=1)
    while current <= filtros.fecha_fin:
        meses.append(current.month)
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)
    
    meses_nombres = ['', 'Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 
                     'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
    
    template_data = {
        "request": request,
        "user_name": context.get("user_name"),
        "role": context.get("role"),
        "module_roles": context.get("module_roles", {}),
        "current_module_role": context.get("module_roles", {}).get("simulacion", "viewer"),
        "catalogos": catalogos,
        "metricas": metricas,
        "tecnologias": metricas_tech,
        "filas": tabla_contab,
        "usuarios": metricas_usuarios,
        "resumen": resumen_mensual,
        "resumen_ejecutivo": resumen_ejecutivo,  # ← Objeto dataclass, NO HTML
        "meses": meses,
        "meses_nombres": meses_nombres,
        "filtros_aplicados": {
            "fecha_inicio": filtros.fecha_inicio.isoformat(),
            "fecha_fin": filtros.fecha_fin.isoformat(),
            "tecnologia": filtros.id_tecnologia,
            "tipo_solicitud": filtros.id_tipo_solicitud,
            "estatus": filtros.id_estatus,
            "estatus": filtros.id_estatus,
            "usuario": str(filtros.responsable_id) if filtros.responsable_id else None
        },
        # Inyección de umbrales para evitar hardcodes en templates
        "umbral_verde_interno": u_interno.umbral_excelente,
        "umbral_ambar_interno": u_interno.umbral_bueno,
        "umbral_verde_compromiso": u_compromiso.umbral_excelente,
        "umbral_ambar_compromiso": u_compromiso.umbral_bueno,
    }
    
    # Detección HTMX vs carga directa
    if request.headers.get("hx-request"):
        # Determinar qué parcial devolver según el target
        hx_target = request.headers.get("hx-target")
        
        if hx_target == "report-content":
            # Caso: Filtrado dentro de la vista (solo contenido interno)
            return templates.TemplateResponse(
                "simulacion/reportes/analisis_detallado_content.html", 
                template_data
            )
        else:
            # Caso: Navegación desde Dashboard (Breadcrumbs + Wrapper + Contenido)
            # Esto asume target="main-content" o similar
            return templates.TemplateResponse(
                "simulacion/reportes/analisis_detallado_inner.html", 
                template_data
            )
    else:
        # Carga completa (F5)
        return templates.TemplateResponse(
            "simulacion/reportes/analisis_detallado.html", 
            template_data
        )


@router.get("/metricas", include_in_schema=False)
async def get_metricas_partial(
    request: Request,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    tech_id: Optional[str] = None,
    type_id: Optional[str] = None,
    status_id: Optional[str] = None,
    user_id: Optional[str] = None,
    conn = Depends(get_db_connection),
    service: ReportesSimulacionService = Depends(get_reportes_service),
    _ = require_module_access("simulacion")
):
    """
    Partial HTMX: Tarjetas de métricas generales (KPIs).
    """
    filtros = parse_filtros(start_date, end_date, tech_id, type_id, status_id, user_id)
    metricas = await service.get_metricas_generales(conn, filtros)
    
    return templates.TemplateResponse("simulacion/reportes/partials/kpis_cards.html", {
        "request": request,
        "metricas": metricas
    })


@router.get("/por-tecnologia", include_in_schema=False)
async def get_tecnologia_partial(
    request: Request,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    tech_id: Optional[str] = None,
    type_id: Optional[str] = None,
    status_id: Optional[str] = None,
    user_id: Optional[str] = None,
    conn = Depends(get_db_connection),
    service: ReportesSimulacionService = Depends(get_reportes_service),
    _ = require_module_access("simulacion")
):
    """
    Partial HTMX: Tablas de métricas por tecnología.
    """
    filtros = parse_filtros(start_date, end_date, tech_id, type_id, status_id, user_id)
    metricas_tech = await service.get_metricas_por_tecnologia(conn, filtros)
    
    return templates.TemplateResponse("simulacion/reportes/partials/tech_tables.html", {
        "request": request,
        "tecnologias": metricas_tech
    })


@router.get("/contabilizacion", include_in_schema=False)
async def get_contabilizacion_partial(
    request: Request,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    tech_id: Optional[str] = None,
    type_id: Optional[str] = None,
    status_id: Optional[str] = None,
    user_id: Optional[str] = None,
    conn = Depends(get_db_connection),
    service: ReportesSimulacionService = Depends(get_reportes_service),
    _ = require_module_access("simulacion")
):
    """
    Partial HTMX: Tabla de contabilización con semáforos.
    """
    filtros = parse_filtros(start_date, end_date, tech_id, type_id, status_id, user_id)
    tabla = await service.get_tabla_contabilizacion(conn, filtros)
    
    # Obtener umbrales dinámicos
    u_interno = await ConfigService.get_umbrales_kpi(conn, "kpi_interno", "SIMULACION")
    u_compromiso = await ConfigService.get_umbrales_kpi(conn, "kpi_compromiso", "SIMULACION")
    
    return templates.TemplateResponse("simulacion/reportes/partials/semaforo_table.html", {
        "request": request,
        "filas": tabla,
        "umbral_verde_interno": u_interno.umbral_excelente,
        "umbral_ambar_interno": u_interno.umbral_bueno,
        "umbral_verde_compromiso": u_compromiso.umbral_excelente,
        "umbral_ambar_compromiso": u_compromiso.umbral_bueno,
    })


@router.get("/por-usuario", include_in_schema=False)
async def get_usuarios_partial(
    request: Request,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    tech_id: Optional[str] = None,
    type_id: Optional[str] = None,
    status_id: Optional[str] = None,
    user_id: Optional[str] = None,
    conn = Depends(get_db_connection),
    service: ReportesSimulacionService = Depends(get_reportes_service),
    _ = require_module_access("simulacion")
):
    """
    Partial HTMX: Detalle de métricas por usuario.
    """
    filtros = parse_filtros(start_date, end_date, tech_id, type_id, status_id, user_id)
    usuarios = await service.get_detalle_por_usuario(conn, filtros)
    
    return templates.TemplateResponse("simulacion/reportes/partials/user_detail.html", {
        "request": request,
        "usuarios": usuarios
    })


@router.get("/mensual", include_in_schema=False)
async def get_mensual_partial(
    request: Request,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    tech_id: Optional[str] = None,
    type_id: Optional[str] = None,
    status_id: Optional[str] = None,
    user_id: Optional[str] = None,
    conn = Depends(get_db_connection),
    service: ReportesSimulacionService = Depends(get_reportes_service),
    _ = require_module_access("simulacion")
):
    """
    Partial HTMX: Resumen mensual (tabla pivot).
    """
    filtros = parse_filtros(start_date, end_date, tech_id, type_id, status_id, user_id)
    resumen = await service.get_resumen_mensual(conn, filtros)
    
    # Obtener umbrales dinámicos
    u_interno = await ConfigService.get_umbrales_kpi(conn, "kpi_interno", "SIMULACION")
    u_compromiso = await ConfigService.get_umbrales_kpi(conn, "kpi_compromiso", "SIMULACION")
    
    # Generar lista de meses en el rango
    meses = []
    current = filtros.fecha_inicio.replace(day=1)
    while current <= filtros.fecha_fin:
        meses.append(current.month)
        # Avanzar al siguiente mes
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)
    
    meses_nombres = ['', 'Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 
                     'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
    
    return templates.TemplateResponse("simulacion/reportes/partials/monthly_pivot.html", {
        "request": request,
        "resumen": resumen,
        "meses": meses,
        "meses_nombres": meses_nombres,
        "umbral_verde_interno": u_interno.umbral_excelente,
        "umbral_ambar_interno": u_interno.umbral_bueno,
        "umbral_verde_compromiso": u_compromiso.umbral_excelente,
        "umbral_ambar_compromiso": u_compromiso.umbral_bueno,
    })


# =============================================================================
# ENDPOINTS DE DATOS (JSON para Gráficas)
# =============================================================================

@router.get("/api/dashboard-data")
async def get_dashboard_data(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    tech_id: Optional[str] = None,
    type_id: Optional[str] = None,
    status_id: Optional[str] = None,
    user_id: Optional[str] = None,
    conn = Depends(get_db_connection),
    service: ReportesSimulacionService = Depends(get_reportes_service),
    _ = require_module_access("simulacion")
):
    """
    API JSON: Datos completos para actualizar gráficas con JavaScript.
    
    Usado por Chart.js para actualización dinámica sin recargar página.
    """
    filtros = parse_filtros(start_date, end_date, tech_id, type_id, status_id, user_id)
    
    try:
        graficas = await service.get_datos_graficas(conn, filtros)
        
        # Convertir dataclasses a dict para JSON
        return JSONResponse(content={
            "success": True,
            "data": {
                nombre: {
                    "tipo": g.tipo,
                    "labels": g.labels,
                    "datasets": g.datasets,
                    "opciones": g.opciones
                }
                for nombre, g in graficas.items()
            },
            "filtros": {
                "fecha_inicio": filtros.fecha_inicio.isoformat(),
                "fecha_fin": filtros.fecha_fin.isoformat(),
                "tecnologia": filtros.id_tecnologia,
                "tipo_solicitud": filtros.id_tipo_solicitud,
                "estatus": filtros.id_estatus,
                "usuario": str(filtros.responsable_id) if filtros.responsable_id else None
            }
        })
    except Exception as e:
        logger.error(f"Error obteniendo datos de dashboard: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@router.get("/api/metricas")
async def get_metricas_api(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    tech_id: Optional[str] = None,
    type_id: Optional[str] = None,
    status_id: Optional[str] = None,
    user_id: Optional[str] = None,
    conn = Depends(get_db_connection),
    service: ReportesSimulacionService = Depends(get_reportes_service),
    _ = require_module_access("simulacion")
):
    """
    API JSON: Métricas generales para consumo externo o actualización JS.
    """
    filtros = parse_filtros(start_date, end_date, tech_id, type_id, status_id, user_id)
    
    try:
        metricas = await service.get_metricas_generales(conn, filtros)
        
        return JSONResponse(content={
            "success": True,
            "data": {
                "total_solicitudes": metricas.total_solicitudes,
                "total_ofertas": metricas.total_ofertas,
                "en_espera": metricas.en_espera,
                "canceladas": metricas.canceladas,
                "no_viables": metricas.no_viables,
                "extraordinarias": metricas.extraordinarias,
                "retrabajadas": metricas.retrabajadas,
                "licitaciones": metricas.licitaciones,
                "entregas_a_tiempo": metricas.entregas_a_tiempo,
                "entregas_tarde": metricas.entregas_tarde,
                "sin_fecha_entrega": metricas.sin_fecha_entrega,
                "tiempo_promedio_horas": metricas.tiempo_promedio_horas,
                "tiempo_promedio_dias": metricas.tiempo_promedio_dias,
                "porcentaje_a_tiempo": metricas.porcentaje_a_tiempo,
                "porcentaje_tarde": metricas.porcentaje_tarde
            }
        })
    except Exception as e:
        logger.error(f"Error obteniendo métricas: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


# =============================================================================
# MODAL DE CONFIGURACIÓN (Reutilizar existente)
# =============================================================================

@router.get("/config-modal", include_in_schema=False)
async def get_config_modal(
    request: Request,
    conn = Depends(get_db_connection),
    service: ReportesSimulacionService = Depends(get_reportes_service),
    context = Depends(get_current_user_context),
    _ = require_module_access("simulacion")
):
    """
    Renderiza el modal de configuración de filtros.
    
    Nota: Puede reutilizar el modal existente en modals/report_config_modal.html
    """
    catalogos = await service.get_catalogos_filtros(conn)
    
    return templates.TemplateResponse("simulacion/reportes/modals/filter_modal.html", {
        "request": request,
        "tecnologias": catalogos["tecnologias"],
        "tipos_solicitud": catalogos["tipos_solicitud"],
        "estatus": catalogos["estatus"],
        "usuarios": catalogos["usuarios"],
        "role": context.get("role")
    })
# =============================================================================
# GENERACIÓN DE PDF
# =============================================================================

from pydantic import BaseModel
from typing import Dict, Any
from fastapi import Response
from .pdf_generator import ReportePDFGenerator

class PDFGenerationRequest(BaseModel):
    filtros: dict
    charts: Dict[str, str]

@router.post("/pdf/generar")
async def generar_reporte_pdf(
    datos_pdf: PDFGenerationRequest,
    conn = Depends(get_db_connection),
    service: ReportesSimulacionService = Depends(get_reportes_service),
    _ = require_module_access("simulacion")
):
    """
    Genera el reporte PDF completo con gráficas y tablas.
    """
    try:
        # 1. Parsear filtros desde el JSON recibido
        filtros_dict = datos_pdf.filtros
        filtros = parse_filtros(
            start_date=filtros_dict.get('fecha_inicio'),
            end_date=filtros_dict.get('fecha_fin'),
            tech_id=str(filtros_dict.get('tecnologia') or ''),
            status_id=str(filtros_dict.get('estatus') or ''),
            user_id=str(filtros_dict.get('usuario') or '')
        )
        
        # 2. Obtener todos los datos concentrados
        datos_reporte = await service.get_all_report_data(conn, filtros)
        
        # 3. Generar PDF
        generator = ReportePDFGenerator(filtros, datos_reporte, datos_pdf.charts)
        pdf_content = generator.generate()
        
        # Asegurar que sea bytes (Starlette no acepta bytearray directamente)
        if isinstance(pdf_content, bytearray):
            pdf_bytes = bytes(pdf_content)
        else:
            pdf_bytes = pdf_content
        
        # 4. Retornar archivo
        filename = f"Reporte_Simulacion_{filtros.fecha_inicio}_{filtros.fecha_fin}.pdf"
        
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )
        
    except Exception as e:
        logger.error(f"Error generando PDF: {str(e)}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )
