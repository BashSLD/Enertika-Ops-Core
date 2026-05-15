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

import asyncpg

from dataclasses import asdict

from core.database import get_db_connection
from core.security import get_current_user_context
from core.permissions import require_module_access
from core.timezone import today_mx

from .report_service import (
    ReportesSimulacionService,
    get_reportes_service,
    FiltrosReporte
)
from core.charts.service import generar_charts_simulacion
from core.config_service import ConfigService
from core.config import settings

logger = logging.getLogger("ReportesSimulacionRouter")
templates = Jinja2Templates(directory="templates")
templates.env.globals["DEBUG_MODE"] = settings.DEBUG_MODE

# Registrar filtros de timezone (México)
from core.jinja_filters import register_timezone_filters
register_timezone_filters(templates.env)

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
    today = today_mx()
    
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
    graficas = await service.get_datos_graficas(conn, filtros, metricas=metricas)
    
    # Convertir dataclasses a dict para serialización JSON segura en template
    graficas_dict = {k: asdict(v) for k, v in graficas.items()}

    # Obtener umbrales dinámicos para inyección en template
    u_interno = await ConfigService.get_umbrales_kpi(conn, "kpi_interno", "SIMULACION")
    u_compromiso = await ConfigService.get_umbrales_kpi(conn, "kpi_compromiso", "SIMULACION")

    template_data = {
        "user_name": context.get("user_name"),
        "role": context.get("role"),
        "module_roles": context.get("module_roles", {}),
        "current_module_role": context.get("module_roles", {}).get("simulacion", "viewer"),
        "catalogos": catalogos,
        "metricas": metricas,
        "graficas": graficas_dict,
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
    if request.headers.get("hx-request") and not request.headers.get("hx-history-restore-request"):
        return templates.TemplateResponse(request, "simulacion/reportes/tabs.html", template_data)
    else:
        return templates.TemplateResponse(request, "simulacion/reportes/dashboard.html", template_data)


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
    
    # Graficas para canvas PDF ocultos (best-effort)
    try:
        graficas_raw = await service.get_datos_graficas(conn, filtros, metricas=metricas)
        graficas_dict = {k: asdict(v) for k, v in graficas_raw.items()}
    except Exception as exc:
        logger.warning("get_datos_graficas fallo en analisis detallado: %s", exc)
        graficas_dict = {}

    # Obtener motivo de retrabajo principal y motivos de cierre
    motivo_retrabajo = await service.get_motivo_retrabajo_principal(conn, filtros)
    motivos_cierre = await service.db.get_chart_motivos_cierre(conn, asdict(filtros))

    # Generar resumen ejecutivo
    resumen_ejecutivo = await service.generar_resumen_ejecutivo(
        conn,
        metricas=metricas,
        usuarios=metricas_usuarios,
        filas_tipo=tabla_contab,
        filtros=filtros,
        motivo_retrabajo_principal=motivo_retrabajo,
        metricas_tecnologia=metricas_tech,
        resumen_mensual=resumen_mensual,
        motivos_cierre=motivos_cierre,
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
            "usuario": str(filtros.responsable_id) if filtros.responsable_id else None
        },
        # Inyección de umbrales para evitar hardcodes en templates
        "umbral_verde_interno": u_interno.umbral_excelente,
        "umbral_ambar_interno": u_interno.umbral_bueno,
        "umbral_verde_compromiso": u_compromiso.umbral_excelente,
        "umbral_ambar_compromiso": u_compromiso.umbral_bueno,
        "graficas": graficas_dict,
    }

    # Detección HTMX vs carga directa
    is_htmx = request.headers.get("hx-request")
    is_history_restore = request.headers.get("hx-history-restore-request")
    if is_htmx and not is_history_restore:
        hx_target = request.headers.get("hx-target")
        if hx_target == "report-content":
            return templates.TemplateResponse(request,
                "simulacion/reportes/analisis_detallado_content.html",
                template_data
            )
        return templates.TemplateResponse(request,
            "simulacion/reportes/analisis_detallado_inner.html",
            template_data
        )
    return templates.TemplateResponse(request,
        "simulacion/reportes/analisis_detallado.html",
        template_data
    )


# =============================================================================
# MODAL: OPORTUNIDADES POR USUARIO
# =============================================================================

@router.get("/usuario/{usuario_id}/oportunidades", include_in_schema=False)
async def get_oportunidades_usuario_modal(
    request: Request,
    usuario_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    tech_id: Optional[str] = None,
    type_id: Optional[str] = None,
    status_id: Optional[str] = None,
    context = Depends(get_current_user_context),
    conn = Depends(get_db_connection),
    service: ReportesSimulacionService = Depends(get_reportes_service),
    _ = require_module_access("simulacion")
):
    """Modal con listado de oportunidades trabajadas por un usuario en el período."""
    try:
        uid = UUID(usuario_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="usuario_id inválido")

    filtros = parse_filtros(start_date, end_date, tech_id, type_id, status_id)
    oportunidades = await service.get_oportunidades_usuario_reporte(conn, uid, filtros)
    nombre_param = request.query_params.get("nombre", "Usuario")

    return templates.TemplateResponse(request,
        "simulacion/reportes/modals/oportunidades_usuario_modal.html",
        {
            "oportunidades": oportunidades,
            "nombre_usuario": nombre_param,
            "filtros_aplicados": {
                "fecha_inicio": filtros.fecha_inicio.isoformat(),
                "fecha_fin": filtros.fecha_fin.isoformat(),
            },
        }
    )


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
                "entregas_a_tiempo_compromiso": metricas.entregas_a_tiempo_compromiso,
                "entregas_tarde_compromiso": metricas.entregas_tarde_compromiso,
                "sin_fecha_entrega": metricas.sin_fecha_entrega,
                "tiempo_promedio_horas": metricas.tiempo_promedio_horas,
                "tiempo_promedio_dias": metricas.tiempo_promedio_dias,
                "porcentaje_a_tiempo_compromiso": metricas.porcentaje_a_tiempo_compromiso,
                "porcentaje_tarde_compromiso": metricas.porcentaje_tarde_compromiso
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
    
    return templates.TemplateResponse(request, "simulacion/reportes/modals/filter_modal.html", {"tecnologias": catalogos["tecnologias"],
        "tipos_solicitud": catalogos["tipos_solicitud"],
        "estatus": catalogos["estatus"],
        "usuarios": catalogos["usuarios"],
        "role": context.get("role")
    })
# =============================================================================
# GENERACIÓN DE PDF (WeasyPrint + charts cliente Chart.js)
# =============================================================================

import json as _json
from fastapi import Form as _Form, Response as _Response
from core.pdf_service.service import PDFService, get_pdf_service


async def _generar_pdf_response(
    filtros: "FiltrosReporte",
    charts: dict,
    generado_por: str,
    filename_prefix: str,
    conn,
    service: "ReportesSimulacionService",
    pdf_service: "PDFService",
) -> _Response:
    datos = await service.get_all_report_data(conn, filtros)
    filtros_ctx = {
        "fecha_inicio": str(filtros.fecha_inicio),
        "fecha_fin": str(filtros.fecha_fin),
        "id_tecnologia": filtros.id_tecnologia,
        "responsable_id": getattr(filtros, "responsable_id", None),
    }
    pdf_bytes = await pdf_service.generate(
        "simulacion/reporte_analitica.html",
        {
            "filtros": filtros_ctx,
            "kpis": datos.get("metricas"),
            "charts": charts,
            "tablas": datos,
            "generado_por": generado_por,
        },
    )
    filename = pdf_service.generate_filename(
        filename_prefix,
        f"{filtros.fecha_inicio}_{filtros.fecha_fin}",
    )
    return _Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/pdf/generar")
async def generar_reporte_pdf(
    filtros_json: str = _Form(...),
    charts_json: str = _Form(default="{}"),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    service: ReportesSimulacionService = Depends(get_reportes_service),
    pdf_service: PDFService = Depends(get_pdf_service),
    _=require_module_access("simulacion"),
):
    """
    Genera el reporte PDF de simulacion.

    Body (multipart/form-data):
        filtros_json: JSON con fecha_inicio, fecha_fin, tecnologia, usuario.
        charts_json:  Dict de data URIs base64 capturados desde Chart.js canvas.
    """
    try:
        filtros_dict = _json.loads(filtros_json)
    except _json.JSONDecodeError as exc:
        return JSONResponse(status_code=400, content={"error": f"filtros_json invalido: {exc}"})

    try:
        charts = _json.loads(charts_json or "{}")
    except _json.JSONDecodeError:
        charts = {}

    filtros = parse_filtros(
        start_date=filtros_dict.get("fecha_inicio"),
        end_date=filtros_dict.get("fecha_fin"),
        tech_id=str(filtros_dict.get("tecnologia") or ""),
        status_id=str(filtros_dict.get("estatus") or ""),
        user_id=str(filtros_dict.get("usuario") or ""),
    )

    try:
        return await _generar_pdf_response(
            filtros=filtros,
            charts=charts,
            generado_por=context.get("user_name", ""),
            filename_prefix="reporte_simulacion",
            conn=conn,
            service=service,
            pdf_service=pdf_service,
        )
    except asyncpg.PostgresError as exc:
        logger.error("DB error generando PDF simulacion: %s", exc)
        return JSONResponse(status_code=500, content={"success": False, "error": "Error de base de datos"})
    except ValueError as exc:
        logger.error("Error generando PDF simulacion: %s", exc)
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})


@router.post("/pdf/generar-automatico")
async def generar_reporte_pdf_automatico(
    fecha_inicio: str = _Form(...),
    fecha_fin: str = _Form(default=""),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    service: ReportesSimulacionService = Depends(get_reportes_service),
    pdf_service: PDFService = Depends(get_pdf_service),
    _=require_module_access("simulacion"),
):
    """Genera el PDF de simulación server-side con gráficas via QuickChart."""
    filtros = parse_filtros(
        start_date=fecha_inicio,
        end_date=fecha_fin or None,
        tech_id="",
        status_id="",
        user_id="",
    )
    try:
        graficas = await service.get_datos_graficas(conn, filtros)
        charts = await generar_charts_simulacion(graficas)
        return await _generar_pdf_response(
            filtros=filtros,
            charts=charts,
            generado_por="Automatico",
            filename_prefix="reporte_simulacion_auto",
            conn=conn,
            service=service,
            pdf_service=pdf_service,
        )
    except asyncpg.PostgresError as exc:
        logger.error("DB error generando PDF automatico: %s", exc)
        return JSONResponse(status_code=500, content={"error": "Error de base de datos"})
    except ValueError as exc:
        logger.error("Error generando PDF automatico: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})
