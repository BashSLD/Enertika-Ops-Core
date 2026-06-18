"""
Router de Métricas Operativas del Módulo Simulación (solo Admin/Manager).
"""
from fastapi import APIRouter, Request, Depends, HTTPException, Query, Form
from fastapi.templating import Jinja2Templates
from datetime import datetime, date
from uuid import UUID
from typing import Optional
import logging
import asyncpg

from core.security import get_current_user_context
from core.permissions import require_module_access, require_manager_access, require_role
from core.config import settings
from core.database import get_db_connection
from core.timezone import now_mx
from core.jinja_filters import register_timezone_filters

from modules.shared.utils import is_htmx
from .db_service import SimulacionDBService, get_db_service
from .metrics_service import MetricsService, get_metrics_service
from .metrics_db_service import MetricsDBService, get_metrics_db_service
from .service import SimulacionService, get_simulacion_service, build_historial_context

templates = Jinja2Templates(directory="templates")
templates.env.globals["DEBUG_MODE"] = settings.DEBUG_MODE
register_timezone_filters(templates.env)
logger = logging.getLogger("SimulacionModule")

router = APIRouter(
    prefix="/simulacion",
    tags=["Módulo Simulación"],
)


def _stats_dias(oportunidades: list) -> dict:
    """Estadísticas (promedio/máx/mín) de 'dias_en_estatus' para el detalle."""
    if not oportunidades:
        return {"promedio_dias": 0, "max_dias": 0, "min_dias": 0}
    dias_list = [op['dias_en_estatus'] for op in oportunidades]
    return {
        "promedio_dias": round(sum(dias_list) / len(dias_list), 1),
        "max_dias": round(max(dias_list), 1),
        "min_dias": round(min(dias_list), 1),
    }


def _rango_por_defecto() -> tuple[date, date]:
    """Ventana por defecto de la sección: últimos 3 meses naturales.

    Del primero del mes hace 2 meses hasta hoy (mes en curso + 2 previos). Se
    refresca solo cada cambio de mes y arranca en datos post-ECO confiables.
    """
    hoy = now_mx().date()
    anio, mes = hoy.year, hoy.month - 2
    if mes <= 0:
        mes += 12
        anio -= 1
    return date(anio, mes, 1), hoy


def _puede_ver_kpis(context: dict) -> bool:
    """Política de visibilidad de los KPIs operativos.

    Solo ADMIN global o MANAGER con rol de módulo viewer-o-superior en
    'simulacion'. Un module-admin sin rol MANAGER global NO ve los KPIs.
    """
    if context.get("role") == "ADMIN":
        return True
    if context.get("role") == "MANAGER":
        return bool(context.get("module_roles", {}).get("simulacion"))
    return False


# ========================================
# MÉTRICAS OPERATIVAS (Solo ADMIN / MANAGER)
# ========================================

@router.api_route("/metricas-operativas", methods=["GET", "HEAD"], include_in_schema=False)
async def get_metricas_operativas(
    request: Request,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    db_service: SimulacionDBService = Depends(get_db_service),
    _=require_module_access("simulacion", "viewer")
):
    """Dashboard de métricas operativas de Simulación (Admins y Managers)."""
    if not _puede_ver_kpis(context):
        raise HTTPException(status_code=403, detail="Acceso denegado")

    usuarios = await db_service.get_responsables_simulacion_con_ops(conn)
    tipos_solicitud = await db_service.get_tipos_solicitud(conn)
    tecnologias = await db_service.get_catalog_tecnologias(conn)
    rango_inicio, rango_fin = _rango_por_defecto()

    if is_htmx(request):
        template = "simulacion/metricas_operativas.html"
    else:
        template = "simulacion/dashboard.html"

    return templates.TemplateResponse(request, template, {
        "usuarios": [dict(r) for r in usuarios],
        "tipos_solicitud": [dict(r) for r in tipos_solicitud],
        "tecnologias": tecnologias,
        "rango_inicio": rango_inicio.isoformat(),
        "rango_fin": rango_fin.isoformat(),
        "inner_template": "simulacion/metricas_operativas.html",
        **context
    })


@router.get("/api/metricas-operativas/datos", include_in_schema=False)
async def get_datos_metricas(
    request: Request,
    fecha_inicio: str = Query(None),
    fecha_fin: str = Query(None),
    user_id: str = Query(None),
    tipo_solicitud: str = Query(None),
    tecnologia: str = Query(None),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    metrics_service: MetricsService = Depends(get_metrics_service),
    metrics_db: MetricsDBService = Depends(get_metrics_db_service),
    _=require_module_access("simulacion", "viewer")
):
    """API para obtener métricas de estatus con detalle."""
    if not _puede_ver_kpis(context):
        return templates.TemplateResponse(request, "simulacion/partials/messages/error.html", {
            "title": "Acceso denegado",
            "message": "Se requiere ser Admin o Manager con acceso al módulo."
        })
    is_admin = context.get("is_admin")

    # Parsear fechas (últimos 3 meses por defecto)
    rango_inicio, rango_fin = _rango_por_defecto()
    start = datetime.combine(rango_inicio, datetime.min.time())
    end = datetime.combine(rango_fin, datetime.min.time())
    if fecha_inicio and fecha_fin:
        try:
            start = datetime.fromisoformat(fecha_inicio)
            end = datetime.fromisoformat(fecha_fin)
        except ValueError:
            pass  # se conserva el rango por defecto ya asignado arriba

    user_uuid = None
    if user_id:
        try:
            user_uuid = UUID(user_id)
        except ValueError:
            pass

    tipo_int = None
    if tipo_solicitud and tipo_solicitud.isdigit():
        tipo_int = int(tipo_solicitud)

    tecnologia_int = None
    if tecnologia and tecnologia.isdigit():
        tecnologia_int = int(tecnologia)

    # 1. Tiempo por estatus
    metricas_estatus = await metrics_db.get_tiempo_por_estatus(
        conn, start.date(), end.date(), user_id=user_uuid,
        tipo_solicitud_id=tipo_int, tecnologia_id=tecnologia_int
    )

    # 2. Cuellos de botella (lógica en service)
    cuellos = metrics_service.get_cuellos_botella(metricas_estatus)

    # 3. Análisis de ciclos
    ciclos = await metrics_db.get_analisis_ciclos(
        conn, start.date(), end.date(), tipo_solicitud_id=tipo_int, tecnologia_id=tecnologia_int
    )

    # 4. Transiciones par a par (estado actual del pipeline)
    transiciones = await metrics_db.get_transiciones_par_a_par(
        conn, user_id=user_uuid, tipo_solicitud_id=tipo_int, tecnologia_id=tecnologia_int
    )

    # 5. Métricas del ciclo de revisión (Dirección + retrabajo)
    ciclo_revision = await metrics_db.get_metricas_ciclo_revision(
        conn, start.date(), end.date(), user_id=user_uuid,
        tipo_solicitud_id=tipo_int, tecnologia_id=tecnologia_int
    )

    # 6. Comparativo SLA actual vs ajustado sin tiempo en revisión
    comparativo_sla = await metrics_db.get_comparativo_sla_ajustado(
        conn, start.date(), end.date(), user_id=user_uuid,
        tipo_solicitud_id=tipo_int, tecnologia_id=tecnologia_int
    )

    # 7. Tiempo total solicitud -> Entregado, global y por tecnología
    entrega_tecnologia = await metrics_db.get_tiempo_entrega_por_tecnologia(
        conn, start.date(), end.date(), user_id=user_uuid,
        tipo_solicitud_id=tipo_int, tecnologia_id=tecnologia_int
    )

    # 8. Casos especiales (Monitoreo/Montaje): conteo informativo, fuera de KPIs y métricas
    casos_especiales = await metrics_db.get_conteo_casos_especiales(
        conn, start.date(), end.date(), user_id=user_uuid,
        tipo_solicitud_id=tipo_int, tecnologia_id=tecnologia_int
    )

    # 9. Calidad de registro (solo Admin): lag, bloqueos y ráfagas de captura
    calidad_registro = None
    if is_admin:
        calidad_registro = await metrics_db.get_calidad_registro(
            conn, start.date(), end.date(), user_id=user_uuid,
            tipo_solicitud_id=tipo_int, tecnologia_id=tecnologia_int
        )

    return templates.TemplateResponse(request, "simulacion/partials/metricas_datos.html", {
        "metricas_estatus": metricas_estatus,
        "cuellos_botella": cuellos,
        "ciclos": ciclos,
        "transiciones": transiciones,
        "ciclo_revision": ciclo_revision,
        "comparativo_sla": comparativo_sla,
        "entrega_tecnologia": entrega_tecnologia,
        "casos_especiales": casos_especiales,
        "calidad_registro": calidad_registro,
        "fecha_inicio": start.date().isoformat(),
        "fecha_fin": end.date().isoformat(),
        **context
    })


@router.get("/api/metricas-operativas/detalle-estatus", include_in_schema=False)
async def get_detalle_estatus(
    request: Request,
    estatus: str = Query(...),
    fecha_inicio: str = Query(...),
    fecha_fin: str = Query(...),
    user_id: str = Query(None),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    metrics_db: MetricsDBService = Depends(get_metrics_db_service),
    _=require_module_access("simulacion", "viewer")
):
    """Obtiene detalle de oportunidades en un estatus específico."""
    if not _puede_ver_kpis(context):
        return templates.TemplateResponse(request, "simulacion/partials/messages/error.html", {"title": "Acceso denegado", "message": "No tienes permisos para esta sección."})

    try:
        start = datetime.fromisoformat(fecha_inicio).date()
        end = datetime.fromisoformat(fecha_fin).date()
    except ValueError:
        return templates.TemplateResponse(request, "simulacion/partials/messages/error.html", {"title": "Fechas inválidas", "message": "El rango de fechas no es válido."})

    user_uuid = None
    if user_id:
        try:
            user_uuid = UUID(user_id)
        except ValueError:
            pass

    oportunidades = await metrics_db.get_oportunidades_por_estatus(
        conn, estatus, start, end, user_id=user_uuid
    )

    return templates.TemplateResponse(request, "simulacion/partials/detalle_oportunidades_estatus.html", {
        "oportunidades": oportunidades,
        **_stats_dias(oportunidades),
        **context
    })


@router.get("/api/metricas-operativas/detalle-transicion", include_in_schema=False)
async def get_detalle_transicion(
    request: Request,
    estatus_origen: str = Query(...),
    estatus_destino: str = Query(...),
    user_id: str = Query(None),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    metrics_db: MetricsDBService = Depends(get_metrics_db_service),
    _=require_module_access("simulacion", "viewer")
):
    """Obtiene detalle de oportunidades para una transición específica (origen → destino)."""
    if not _puede_ver_kpis(context):
        return templates.TemplateResponse(request, "simulacion/partials/messages/error.html", {"title": "Acceso denegado", "message": "No tienes permisos para esta sección."})

    user_uuid = None
    if user_id:
        try:
            user_uuid = UUID(user_id)
        except ValueError:
            pass

    oportunidades = await metrics_db.get_oportunidades_por_transicion(
        conn, estatus_origen, estatus_destino, user_id=user_uuid
    )

    return templates.TemplateResponse(request, "simulacion/partials/detalle_oportunidades_transicion.html", {
        "oportunidades": oportunidades,
        "estatus_origen": estatus_origen,
        "estatus_destino": estatus_destino,
        **_stats_dias(oportunidades),
        **context
    })


@router.get("/api/metricas-operativas/detalle-entrega", include_in_schema=False)
async def get_detalle_entrega(
    request: Request,
    fecha_inicio: str = Query(...),
    fecha_fin: str = Query(...),
    user_id: str = Query(None),
    tipo_solicitud: str = Query(None),
    tecnologia: str = Query(None),
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    metrics_db: MetricsDBService = Depends(get_metrics_db_service),
    _=require_module_access("simulacion", "viewer")
):
    """Detalle por oportunidad del lead time solicitud->Entregado (neto de Monitoreo)."""
    if not _puede_ver_kpis(context):
        return templates.TemplateResponse(request, "simulacion/partials/messages/error.html", {"title": "Acceso denegado", "message": "No tienes permisos para esta sección."})

    try:
        start = datetime.fromisoformat(fecha_inicio).date()
        end = datetime.fromisoformat(fecha_fin).date()
    except ValueError:
        return templates.TemplateResponse(request, "simulacion/partials/messages/error.html", {"title": "Fechas inválidas", "message": "El rango de fechas no es válido."})

    user_uuid = None
    if user_id:
        try:
            user_uuid = UUID(user_id)
        except ValueError:
            pass

    tipo_int = int(tipo_solicitud) if tipo_solicitud and tipo_solicitud.isdigit() else None
    tecnologia_int = int(tecnologia) if tecnologia and tecnologia.isdigit() else None

    oportunidades = await metrics_db.get_detalle_entrega(
        conn, start, end, user_id=user_uuid,
        tipo_solicitud_id=tipo_int, tecnologia_id=tecnologia_int
    )

    return templates.TemplateResponse(request, "simulacion/partials/detalle_oportunidades_entrega.html", {
        "oportunidades": oportunidades,
        **context
    })


@router.get("/historial/{id_oportunidad}/modal", include_in_schema=False)
async def get_historial_modal(
    request: Request,
    id_oportunidad: UUID,
    context=Depends(get_current_user_context),
    conn=Depends(get_db_connection),
    service: SimulacionService = Depends(get_simulacion_service),
    db_service: SimulacionDBService = Depends(get_db_service),
    _=require_module_access("simulacion", "viewer")
):
    """Modal de solo lectura con el historial de transiciones de una oportunidad."""
    if not _puede_ver_kpis(context):
        return templates.TemplateResponse(request, "simulacion/partials/messages/error.html", {"title": "Acceso denegado", "message": "No tienes permisos para esta sección."})

    ctx = await build_historial_context(conn, id_oportunidad, service, db_service, context)
    if not ctx:
        raise HTTPException(status_code=404, detail="Oportunidad no encontrada")

    return templates.TemplateResponse(request, "simulacion/modals/historial_modal.html", ctx)


async def _render_historial_timeline_partial(
    request: Request,
    conn,
    id_oportunidad: UUID,
    service: SimulacionService,
    db_service: SimulacionDBService,
    context: dict,
    historial_message: Optional[str] = None,
    historial_error: Optional[str] = None,
):
    ctx = await build_historial_context(
        conn, id_oportunidad, service, db_service, context,
        historial_message=historial_message,
        historial_error=historial_error,
    )
    if not ctx:
        raise HTTPException(status_code=404, detail="Oportunidad no encontrada")
    return templates.TemplateResponse(request, "simulacion/partials/historial_timeline.html", ctx)


@router.post("/historial/{id_oportunidad}/insertar-transicion", include_in_schema=False)
async def insertar_transicion_historica(
    request: Request,
    id_oportunidad: UUID,
    id_estatus: int = Form(...),
    fecha_cambio_real: str = Form(...),
    service: SimulacionService = Depends(get_simulacion_service),
    db_service: SimulacionDBService = Depends(get_db_service),
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context),
    _ = require_manager_access("simulacion"),
):
    try:
        try:
            fecha_real = datetime.fromisoformat(fecha_cambio_real)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="Formato de fecha inválido. Use el selector de fecha del formulario.",
            ) from exc

        await service.insertar_transicion_historica(
            conn,
            id_oportunidad,
            id_estatus,
            fecha_real,
            context,
        )
        return await _render_historial_timeline_partial(
            request,
            conn,
            id_oportunidad,
            service,
            db_service,
            context,
            historial_message="Evento histórico insertado correctamente.",
        )
    except HTTPException as exc:
        return await _render_historial_timeline_partial(
            request,
            conn,
            id_oportunidad,
            service,
            db_service,
            context,
            historial_error=str(exc.detail),
        )
    except asyncpg.PostgresError:
        logger.exception("Error de base de datos insertando transición histórica %s", id_oportunidad)
        return await _render_historial_timeline_partial(
            request,
            conn,
            id_oportunidad,
            service,
            db_service,
            context,
            historial_error="Error de base de datos al insertar el evento histórico.",
        )


@router.post("/historial/{id_oportunidad}/revertir-cierre", include_in_schema=False)
async def revertir_cierre_admin(
    request: Request,
    id_oportunidad: UUID,
    id_estatus_destino: int = Form(...),
    confirmar_reversion: Optional[str] = Form(None),
    service: SimulacionService = Depends(get_simulacion_service),
    db_service: SimulacionDBService = Depends(get_db_service),
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context),
    _ = require_role(["ADMIN"]),
):
    try:
        if confirmar_reversion != "on":
            raise HTTPException(
                status_code=400,
                detail="Debe confirmar explícitamente la reversión del cierre.",
            )

        await service.revertir_cierre_admin(
            conn,
            id_oportunidad,
            id_estatus_destino,
            context,
        )
        return await _render_historial_timeline_partial(
            request,
            conn,
            id_oportunidad,
            service,
            db_service,
            context,
            historial_message="Cierre revertido correctamente.",
        )
    except HTTPException as exc:
        return await _render_historial_timeline_partial(
            request,
            conn,
            id_oportunidad,
            service,
            db_service,
            context,
            historial_error=str(exc.detail),
        )
    except asyncpg.PostgresError:
        logger.exception("Error de base de datos revirtiendo cierre %s", id_oportunidad)
        return await _render_historial_timeline_partial(
            request,
            conn,
            id_oportunidad,
            service,
            db_service,
            context,
            historial_error="Error de base de datos al revertir el cierre.",
        )
