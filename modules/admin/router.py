import logging
from datetime import timedelta
from fastapi import APIRouter, Request, Depends, HTTPException, Form, Header
from fastapi.responses import HTMLResponse, Response
from typing import Optional
from core.database import get_db_connection
from fastapi.templating import Jinja2Templates
from core.security import get_current_user_context
from core.permissions import require_module_access, require_role
from core.timezone import now_mx

from core.config import settings
from core.jinja_filters import register_timezone_filters
from .service import AdminService, get_admin_service
from core.tipo_cambio.service import TipoCambioService
import asyncpg

logger = logging.getLogger("AdminRouter")

from . import endpoints_correos_notif
from .schemas import ConfiguracionGlobalUpdate, TecnologiaCreate
from core.config_service import ConfigService

router = APIRouter(
    prefix="/admin",
    tags=["Admin"]
)

templates = Jinja2Templates(directory="templates")
templates.env.globals["DEBUG_MODE"] = settings.DEBUG_MODE
register_timezone_filters(templates.env)

# --- CONFIG EMAIL ENDPOINTS ---

@router.api_route("/ui", methods=["GET", "HEAD"], include_in_schema=False)
async def admin_dashboard(
    request: Request,
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context),
    service: AdminService = Depends(get_admin_service),
    _ = require_module_access("admin")
):
    """Dashboard principal: Lista usuarios, Reglas, Departamentos y Módulos."""
    tc_service = TipoCambioService()
    users_enriched = await service.get_users_enriched(conn)
    rules = await service.get_email_rules(conn)
    defaults = await service.get_email_defaults(conn)
    departments_dict = await service.get_departments_catalog(conn)
    modules_dict = await service.get_modules_catalog(conn)
    catalogos = await service.get_catalogos_reglas(conn)
    global_config = await service.get_global_config(conn)
    fiel_config = await service.db.fetch_fiel_config(conn)
    reporte = await service.generar_reporte_semanal(conn)
    recordatorios_monitor = await service.get_recordatorios_oportunidad_monitor(conn)
    tc_actual = await tc_service.get_tasa_actual(conn)
    tc_historial = await tc_service.get_historial(conn, limit=30)

    return templates.TemplateResponse(request, "admin/dashboard.html", {"users": users_enriched,
        "rules": rules,
        "defaults": defaults,
        "departments": departments_dict,
        "modules": modules_dict,
        "catalogos": catalogos,
        "config_global": global_config,
        "fiel_config": fiel_config,
        "user_name": context.get("user_name"),
        "role": context.get("role"),
        "module_roles": context.get("module_roles", {}),
        # Datos reporte semanal
        "reporte_datos": reporte["datos"],
        "reporte_fecha_inicio": reporte["fecha_inicio"],
        "reporte_fecha_fin_display": reporte["fecha_fin"] - timedelta(days=1),
        "reporte_destinatarios_configurados": bool(global_config.get("reporte_semanal_destinatarios", "").strip()),
        "recordatorios_monitor": recordatorios_monitor,
        "recordatorios_monitor_updated_at": now_mx(),
        # Tipo de cambio
        "tipo_cambio_actual": tc_actual,
        "tipo_cambio_historial": tc_historial,
    })

@router.post("/users/role")
async def update_user_role(
    request: Request,
    user_id: str = Form(...),
    role: str = Form(...),
    context = Depends(get_current_user_context),
    service: AdminService = Depends(get_admin_service),
    conn = Depends(get_db_connection),
    _ = require_module_access("admin", "admin")
):
    """Actualiza el rol de sistema de un usuario (HTMX)."""
    await service.update_user_role(conn, user_id, role)
    return templates.TemplateResponse(request, "admin/partials/messages/success.html", {"title": "Actualizado", 
        "message": f"Rol cambiado a {role}"
    })

@router.post("/rules/add")
async def add_email_rule(
    request: Request,
    modulo: str = Form(...),
    trigger_field: str = Form(...),
    trigger_value: str = Form(...),
    email_to_add: str = Form(...),
    type: str = Form(...),
    context = Depends(get_current_user_context),
    service: AdminService = Depends(get_admin_service),
    conn = Depends(get_db_connection),
    _ = require_module_access("admin", "admin")
):
    """Agrega una nueva regla de correo."""
    await service.add_email_rule(conn, modulo, trigger_field, trigger_value, email_to_add, type)
    
    # HTMX detecta este header y recarga la página automáticamente
    return Response(status_code=200, headers={"HX-Refresh": "true"})

@router.delete("/users/{user_id}")
async def delete_user(
    request: Request,
    user_id: str,
    context = Depends(get_current_user_context),
    service: AdminService = Depends(get_admin_service),
    conn = Depends(get_db_connection),
    _ = require_module_access("admin", "admin")
):
    """Desactiva un usuario (Soft delete)."""
    user = await service.deactivate_user(conn, user_id)
    
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    # Retornar fila actualizada
    return templates.TemplateResponse(request, "admin/partials/user_row.html", {"u": user
    })

@router.post("/users/{user_id}/restore")
async def restore_user(
    request: Request,
    user_id: str,
    context = Depends(get_current_user_context),
    service: AdminService = Depends(get_admin_service),
    conn = Depends(get_db_connection),
    _ = require_module_access("admin", "admin")
):
    """Reactiva un usuario (Soft delete restore)."""
    user = await service.reactivate_user(conn, user_id)
    
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    # Retornar fila actualizada
    return templates.TemplateResponse(request, "admin/partials/user_row.html", {"u": user
    })

@router.delete("/rules/{id}")
async def delete_email_rule(
    request: Request,
    id: int,
    context = Depends(get_current_user_context),
    service: AdminService = Depends(get_admin_service),
    conn = Depends(get_db_connection),
    _ = require_module_access("admin", "admin")
):
    """Elimina una regla."""
    await service.delete_email_rule(conn, id)
    
    # Retornar template partial con feedback visual
    return templates.TemplateResponse(request, "admin/partials/rule_deleted.html", {"rule_id": id
    })

# --- CONFIG DEFAULT EMAILS (GLOBAL) ---
@router.post("/defaults/update")
async def update_email_defaults(
    request: Request,
    default_to: str = Form(""),
    default_cc: str = Form(""),
    default_cco: str = Form(""),
    context = Depends(get_current_user_context),
    service: AdminService = Depends(get_admin_service),
    conn = Depends(get_db_connection),
    _ = require_module_access("admin", "admin")
):
    """Actualiza configuracion global de correos (TO, CC, CCO)."""
    await service.update_email_defaults(conn, default_to, default_cc, default_cco)
    
    return templates.TemplateResponse(request, "admin/partials/messages/success.html", {"title": "Configuración Actualizada",
        "message": "Los correos por defecto se han guardado."
    })

# --- CONFIGURACIÓN GLOBAL Y REGLAS DINÁMICAS ---

@router.get("/partials/trigger-options")
async def get_trigger_options(
    request: Request,
    trigger_field: str,  # Viene del select name="trigger_field"
    service: AdminService = Depends(get_admin_service),
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context),
    _ = require_module_access("admin")
):
    """
    Endpoint HTMX para opciones dinámicas de reglas de correo.
    Devuelve un partial HTML:
    - Un <select> si el campo requiere catálogo (Tecnología, Tipo Solicitud, Estatus).
    - Un <input text> si es campo libre (Cliente, etc.).
    
    Patrón recomendado por GUIA_MAESTRA líneas 110-173 (Partials).
    """
    options = await service.get_options_for_trigger(conn, trigger_field)
    
    if options:
        # Renderizar como Select con opciones del catálogo
        return templates.TemplateResponse(request, "admin/partials/dynamic_trigger_select.html", {"options": options
        })
    else:
        # Renderizar como Input Text libre
        return templates.TemplateResponse(request, "admin/partials/dynamic_trigger_input.html", {})

from .schemas import OrigenAdjuntoCreate

@router.post("/config/global")
async def update_global_config_endpoint(
    request: Request,
    hora_corte_l_v: str = Form(...),
    dias_sla_default: int = Form(...),
    # SharePoint Params (Optional but processed)
    sharepoint_site_id: str = Form(""),
    sharepoint_drive_id: str = Form(""),
    sharepoint_base_folder: str = Form(""),
    max_upload_size_mb: int = Form(500),
    sp_visitas_site_id: str = Form(""),
    sp_visitas_drive_id: str = Form(""),
    # SAT Inbox SharePoint
    sp_sat_site_id: str = Form(""),
    sp_sat_drive_id: str = Form(""),
    sp_sat_base_folder: str = Form("SAT-Inbox"),
    # Simulation KPI Config (Defaults match constants.py)
    sim_peso_compromiso: float = Form(0.50),
    sim_peso_interno: float = Form(0.35),
    sim_peso_volumen: float = Form(0.15),
    sim_umbral_min_entregas: int = Form(10),
    sim_umbral_ratio_licitaciones: float = Form(0.10),
    sim_umbral_verde: float = Form(90.0),
    sim_umbral_ambar: float = Form(85.0),
    sim_mult_licitaciones: float = Form(0.20),
    sim_mult_actualizaciones: float = Form(0.10),
    sim_penalizacion_retrabajos: float = Form(-0.15),
    sim_volumen_max: int = Form(100),
    # Comercial Config
    comercial_popup_targets: str = Form(""),
    # Reporte Semanal
    reporte_semanal_destinatarios: str = Form(""),
    # Visita a Obra
    visita_obra_destinatarios: str = Form(""),
    service: AdminService = Depends(get_admin_service),
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context),
    _ = require_module_access("admin")
):
    """
    Actualiza la configuración global del sistema.
    Valida datos con Pydantic antes de guardar.
    
    Args:
        hora_corte_l_v: Hora de corte L-V en formato HH:MM
        dias_sla_default: Días de SLA por defecto (1-30)
        dias_fin_semana: Lista de enteros para días de fin de semana
    """
    # Obtener dias de fin de semana desde form (checkboxes)
    form_data = await request.form()
    dias_fin_semana = []
    
    # Los checkboxes envían valores como "dia_0", "dia_1", etc.
    for key in form_data.keys():
        if key.startswith("dia_"):
            dia_num = int(key.replace("dia_", ""))
            if 0 <= dia_num <= 6:  # Validar rango 0-6 (Lunes-Domingo)
                dias_fin_semana.append(dia_num)
    
    # Si no se seleccionó ningún checkbox, usar default
    if not dias_fin_semana:
        dias_fin_semana = [5, 6]  # Sábado y Domingo por defecto
    
    # 1. Validar con Schema (Pydantic v2)
    try:
        datos = ConfiguracionGlobalUpdate(
            hora_corte_l_v=hora_corte_l_v,
            dias_sla_default=dias_sla_default,
            dias_fin_semana=dias_fin_semana,
            sharepoint_site_id=sharepoint_site_id,
            sharepoint_drive_id=sharepoint_drive_id,
            sharepoint_base_folder=sharepoint_base_folder,
            max_upload_size_mb=max_upload_size_mb,
            sp_visitas_site_id=sp_visitas_site_id,
            sp_visitas_drive_id=sp_visitas_drive_id,
            sp_sat_site_id=sp_sat_site_id,
            sp_sat_drive_id=sp_sat_drive_id,
            sp_sat_base_folder=sp_sat_base_folder,
            # Simulation KPIS
            sim_peso_compromiso=sim_peso_compromiso,
            sim_peso_interno=sim_peso_interno,
            sim_peso_volumen=sim_peso_volumen,
            sim_umbral_min_entregas=sim_umbral_min_entregas,
            sim_umbral_ratio_licitaciones=sim_umbral_ratio_licitaciones,
            sim_umbral_verde=sim_umbral_verde,
            sim_umbral_ambar=sim_umbral_ambar,
            sim_mult_licitaciones=sim_mult_licitaciones,
            sim_mult_actualizaciones=sim_mult_actualizaciones,
            sim_penalizacion_retrabajos=sim_penalizacion_retrabajos,
            sim_volumen_max=sim_volumen_max,
            comercial_popup_targets=comercial_popup_targets,
            reporte_semanal_destinatarios=reporte_semanal_destinatarios,
            visita_obra_destinatarios=visita_obra_destinatarios
        )
    except ValueError as e:
        return templates.TemplateResponse(request, "admin/partials/messages/error.html", {"title": "Error de Validación",
            "message": str(e)
        }, status_code=400)
    
    # 2. Guardar en base de datos
    await service.update_global_config(conn, datos)
    
    # 3. Retornar mensaje de éxito
    return templates.TemplateResponse(request, "admin/partials/messages/success.html", {"title": "Configuración Actualizada",
        "message": f"Reglas de negocio y parámetros de SharePoint actualizados correctamente."
    })


# ── Mini-forms: endpoints dedicados por sección ──────────────────────

@router.post("/config/reglas-negocio", include_in_schema=False)
async def update_config_reglas_negocio(
    request: Request,
    hora_corte_l_v: str = Form(...),
    dias_sla_default: int = Form(...),
    service: AdminService = Depends(get_admin_service),
    conn = Depends(get_db_connection),
    _ = require_module_access("admin"),
):
    """Guarda hora de corte, días SLA y días fin de semana."""
    form_data = await request.form()
    dias_fin_semana = [int(v) for v in form_data.getlist("dias_fin_semana") if v.isdigit() and 0 <= int(v) <= 6]
    if not dias_fin_semana:
        dias_fin_semana = [5, 6]

    try:
        if not hora_corte_l_v or len(hora_corte_l_v) != 5:
            raise ValueError("Hora de corte inválida")
        if dias_sla_default < 1 or dias_sla_default > 30:
            raise ValueError("Días SLA debe ser entre 1 y 30")
    except (ValueError, TypeError) as e:
        return templates.TemplateResponse(
            request, "shared/toast.html",
            {"message": f"Error de validación: {e}", "type": "error"},
            headers={"HX-Reswap": "none"},
        )

    await service.db.upsert_global_config(conn, "HORA_CORTE_L_V", hora_corte_l_v)
    await service.db.upsert_global_config(conn, "DIAS_SLA_DEFAULT", str(dias_sla_default))
    await service.db.upsert_global_config(conn, "DIAS_FIN_SEMANA", str(dias_fin_semana))
    ConfigService.invalidar_cache()

    return templates.TemplateResponse(
        request, "shared/toast.html",
        {"message": "Reglas de negocio guardadas correctamente", "type": "success"},
        headers={"HX-Reswap": "none"},
    )


@router.post("/config/sharepoint", include_in_schema=False)
async def update_config_sharepoint(
    request: Request,
    sharepoint_site_id: str = Form(""),
    sharepoint_drive_id: str = Form(""),
    sharepoint_base_folder: str = Form(""),
    max_upload_size_mb: int = Form(500),
    sp_visitas_site_id: str = Form(""),
    sp_visitas_drive_id: str = Form(""),
    service: AdminService = Depends(get_admin_service),
    conn = Depends(get_db_connection),
    _ = require_module_access("admin"),
):
    """Guarda toda la configuración de SharePoint (principal + visitas)."""
    await service.db.upsert_global_config(conn, "SHAREPOINT_SITE_ID", sharepoint_site_id.strip())
    await service.db.upsert_global_config(conn, "SHAREPOINT_DRIVE_ID", sharepoint_drive_id.strip())
    await service.db.upsert_global_config(conn, "SHAREPOINT_BASE_FOLDER", sharepoint_base_folder.strip())
    await service.db.upsert_global_config(conn, "MAX_UPLOAD_SIZE_MB", str(max_upload_size_mb))
    await service.db.upsert_global_config(conn, "SP_VISITAS_SITE_ID", sp_visitas_site_id.strip())
    await service.db.upsert_global_config(conn, "SP_VISITAS_DRIVE_ID", sp_visitas_drive_id.strip())
    ConfigService.invalidar_cache()

    return templates.TemplateResponse(
        request, "shared/toast.html",
        {"message": "Configuración SharePoint guardada correctamente", "type": "success"},
        headers={"HX-Reswap": "none"},
    )


@router.post("/config/simulacion-kpis", include_in_schema=False)
async def update_config_simulacion_kpis(
    request: Request,
    sim_peso_compromiso: float = Form(0.50),
    sim_peso_interno: float = Form(0.35),
    sim_peso_volumen: float = Form(0.15),
    sim_umbral_min_entregas: int = Form(10),
    sim_umbral_ratio_licitaciones: float = Form(0.10),
    sim_mult_licitaciones: float = Form(0.20),
    sim_mult_actualizaciones: float = Form(0.10),
    sim_penalizacion_retrabajos: float = Form(-0.15),
    sim_volumen_max: int = Form(100),
    service: AdminService = Depends(get_admin_service),
    conn = Depends(get_db_connection),
    _ = require_module_access("admin"),
):
    """Guarda los pesos y umbrales de KPIs de simulación."""
    kpi_pairs = [
        ("sim_peso_compromiso", str(sim_peso_compromiso)),
        ("sim_peso_interno", str(sim_peso_interno)),
        ("sim_peso_volumen", str(sim_peso_volumen)),
        ("sim_umbral_min_entregas", str(sim_umbral_min_entregas)),
        ("sim_umbral_ratio_licitaciones", str(sim_umbral_ratio_licitaciones)),
        ("sim_mult_licitaciones", str(sim_mult_licitaciones)),
        ("sim_mult_actualizaciones", str(sim_mult_actualizaciones)),
        ("sim_penalizacion_retrabajos", str(sim_penalizacion_retrabajos)),
        ("sim_volumen_max", str(sim_volumen_max)),
    ]
    for clave, valor in kpi_pairs:
        await service.db.upsert_global_config(conn, clave, valor)
    ConfigService.invalidar_cache()

    return templates.TemplateResponse(
        request, "shared/toast.html",
        {"message": "KPIs de simulación guardados correctamente", "type": "success"},
        headers={"HX-Reswap": "none"},
    )


@router.post("/config/global/reset-simulation")
async def reset_simulation_config_endpoint(
    request: Request,
    service: AdminService = Depends(get_admin_service),
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context),
    _ = require_module_access("admin")
):
    """
    Restaura los valores por defecto de la configuración de simulación.
    Elimina los registros de tb_configuracion_global para que el sistema use los defaults del código.
    """
    await service.reset_simulation_defaults(conn)
    
    return templates.TemplateResponse(request, "admin/partials/messages/success.html", {"title": "Valores Restaurados",
        "message": "Se han restablecido los valores por defecto para Simulación."
    })

# --- CONFIGURACION DE BUZONES (mini-forms individuales) ---

@router.post("/config/comercial", include_in_schema=False)
async def update_config_comercial(
    request: Request,
    comercial_popup_targets: str = Form(""),
    service: AdminService = Depends(get_admin_service),
    conn = Depends(get_db_connection),
    _ = require_module_access("admin"),
):
    """Guarda solo la configuracion de popup comercial."""
    await service.db.upsert_global_config(conn, "COMERCIAL_POPUP_TARGETS", comercial_popup_targets)
    ConfigService.invalidar_cache()
    return templates.TemplateResponse(request, "admin/partials/messages/success.html", {
        "title": "Guardado", "message": "Configuracion comercial actualizada."
    })


@router.post("/config/reporte-semanal", include_in_schema=False)
async def update_config_reporte_semanal(
    request: Request,
    reporte_semanal_destinatarios: str = Form(""),
    service: AdminService = Depends(get_admin_service),
    conn = Depends(get_db_connection),
    _ = require_module_access("admin"),
):
    """Guarda solo los destinatarios del reporte semanal."""
    await service.db.upsert_global_config(conn, "reporte_semanal_destinatarios", reporte_semanal_destinatarios)
    ConfigService.invalidar_cache()
    return templates.TemplateResponse(request, "admin/partials/messages/success.html", {
        "title": "Guardado", "message": "Destinatarios del reporte semanal actualizados."
    })


@router.post("/config/reporte-semanal-activo", include_in_schema=False)
async def toggle_reporte_semanal_activo(
    request: Request,
    service: AdminService = Depends(get_admin_service),
    conn=Depends(get_db_connection),
    _=require_module_access("admin"),
):
    """Alterna la habilitacion del envio automatico del reporte semanal."""
    actual = await ConfigService.get_global_config(conn, "reporte_semanal_activo", "true", str)
    nuevo = "false" if actual.lower() == "true" else "true"
    await service.db.upsert_global_config(conn, "reporte_semanal_activo", nuevo)
    ConfigService.invalidar_cache()
    activo = nuevo == "true"
    return templates.TemplateResponse(
        request, "admin/partials/reporte_semanal_toggle.html", {"reporte_semanal_activo": activo}
    )


@router.post("/config/sat-inbox", include_in_schema=False)
async def update_config_sat_inbox(
    request: Request,
    sp_sat_site_id: str = Form(""),
    sp_sat_drive_id: str = Form(""),
    sp_sat_base_folder: str = Form("SAT-Inbox"),
    service: AdminService = Depends(get_admin_service),
    conn = Depends(get_db_connection),
    _ = require_role(["ADMIN"]),
):
    """Guarda la configuración SharePoint SAT Inbox (Site ID, Drive ID, Carpeta)."""
    await service.db.upsert_global_config(conn, "SP_SAT_SITE_ID", sp_sat_site_id.strip())
    await service.db.upsert_global_config(conn, "SP_SAT_DRIVE_ID", sp_sat_drive_id.strip())
    await service.db.upsert_global_config(conn, "SP_SAT_BASE_FOLDER", (sp_sat_base_folder.strip() or "SAT-Inbox"))
    ConfigService.invalidar_cache()
    return templates.TemplateResponse(
        request,
        "shared/toast.html",
        {"message": "Configuración SAT Inbox guardada correctamente", "type": "success"},
        headers={"HX-Reswap": "none"},
    )


@router.post("/config/visita-obra", include_in_schema=False)
async def update_config_visita_obra(
    request: Request,
    visita_obra_destinatarios: str = Form(""),
    service: AdminService = Depends(get_admin_service),
    conn = Depends(get_db_connection),
    _ = require_module_access("admin"),
):
    """Guarda los destinatarios del email de Visita a Obra."""
    await service.db.upsert_global_config(conn, "visita_obra_destinatarios", visita_obra_destinatarios)
    ConfigService.invalidar_cache()
    return templates.TemplateResponse(request, "admin/partials/messages/success.html", {
        "title": "Guardado", "message": "Destinatarios de Visita a Obra actualizados."
    })


@router.post("/reportes/enviar-desarrollo-ceo", include_in_schema=False)
async def enviar_reporte_desarrollo_ceo_manual(
    request: Request,
    fecha_desde: str = Form(...),
    fecha_hasta: str = Form(...),
    service: AdminService = Depends(get_admin_service),
    conn = Depends(get_db_connection),
    _ = require_module_access("admin"),
):
    """Envía el reporte de desarrollo CEO para un rango de fechas dado."""
    from datetime import date as date_type
    from core.microsoft import MicrosoftAuth
    from core.config_service import ConfigService
    from core.weekly_report.service import generar_y_enviar_reporte_ceo, parse_ceo_recipients

    def _error(msg: str, title: str = "Error"):
        return templates.TemplateResponse(
            request, "admin/partials/messages/error.html", {"title": title, "message": msg}
        )

    try:
        since = date_type.fromisoformat(fecha_desde)
        until = date_type.fromisoformat(fecha_hasta)
        if until < since:
            return _error("La fecha hasta debe ser igual o posterior a la fecha desde.", "Fechas inválidas")
        from datetime import timedelta
        until_exclusive = until + timedelta(days=1)
    except ValueError:
        return _error("Formato de fecha inválido.")

    ceo_recipients_raw = await ConfigService.get_global_config(conn, "reporte_desarrollo_ceo_email", "", str)
    ceo_recipients = parse_ceo_recipients(ceo_recipients_raw)
    if not ceo_recipients:
        return _error("Configura al menos un destinatario valido antes de enviar.", "Sin destinatario")

    sender_email = await service.db.fetch_email_remitente_default(conn)
    if not sender_email:
        return _error("No hay buzón DEFAULT activo configurado.", "Sin remitente")

    ms_auth = MicrosoftAuth()
    try:
        enviado = await generar_y_enviar_reporte_ceo(
            ms_auth=ms_auth,
            sender_email=sender_email,
            ceo_recipients=ceo_recipients,
            since=since,
            until=until_exclusive,
        )
    except RuntimeError as e:
        return _error(str(e), "Entorno no compatible")

    if enviado:
        return templates.TemplateResponse(request, "admin/partials/messages/success.html", {
            "title": "Enviado",
            "message": (
                f"Reporte enviado a {', '.join(ceo_recipients)} "
                f"({fecha_desde} al {fecha_hasta})."
            )
        })
    return _error("No hay commits en el rango seleccionado. No se envió ningún reporte.", "Sin actividad")


@router.post("/config/reporte-desarrollo-ceo", include_in_schema=False)
async def update_config_reporte_desarrollo_ceo(
    request: Request,
    reporte_desarrollo_ceo_email: str = Form(""),
    service: AdminService = Depends(get_admin_service),
    conn = Depends(get_db_connection),
    _ = require_module_access("admin"),
):
    """Guarda uno o varios destinatarios del reporte de desarrollo semanal."""
    await service.db.upsert_global_config(conn, "reporte_desarrollo_ceo_email", reporte_desarrollo_ceo_email.strip())
    ConfigService.invalidar_cache()
    return templates.TemplateResponse(request, "admin/partials/messages/success.html", {
        "title": "Guardado", "message": "Destinatarios del reporte CEO actualizados."
    })


@router.post("/config/reporte-desarrollo-ceo-activo", include_in_schema=False)
async def toggle_reporte_ceo_activo(
    request: Request,
    service: AdminService = Depends(get_admin_service),
    conn=Depends(get_db_connection),
    _=require_module_access("admin"),
):
    """Alterna la habilitacion del envio automatico del reporte de desarrollo CEO."""
    actual = await ConfigService.get_global_config(conn, "reporte_desarrollo_ceo_activo", "true", str)
    nuevo = "false" if actual.lower() == "true" else "true"
    await service.db.upsert_global_config(conn, "reporte_desarrollo_ceo_activo", nuevo)
    ConfigService.invalidar_cache()
    activo = nuevo == "true"
    return templates.TemplateResponse(
        request, "admin/partials/reporte_ceo_toggle.html", {"reporte_ceo_activo": activo}
    )


# --- USER MANAGEMENT ENDPOINTS ---

from uuid import UUID
from typing import List


@router.post("/users/{user_id}/department")
async def update_user_department(
    request: Request,
    user_id: UUID,
    department_slug: Optional[str] = Form(None),
    context = Depends(get_current_user_context),
    service: AdminService = Depends(get_admin_service),
    conn = Depends(get_db_connection),
    _ = require_module_access("admin", "admin")
):
    """Asigna o limpia el departamento de un usuario."""
    try:
        dept_nombre = await service.update_user_department(conn, user_id, department_slug or None)
        msg = f"Depto: {dept_nombre}" if dept_nombre else "Departamento removido"
        return templates.TemplateResponse(request, "admin/partials/messages/success.html", {"title": "Actualizado", "message": msg
        })
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/users/{user_id}/modules")
async def update_user_modules(
    request: Request,
    user_id: UUID,
    context = Depends(get_current_user_context),
    service: AdminService = Depends(get_admin_service),
    conn = Depends(get_db_connection),
    _ = require_module_access("admin", "admin")
):
    """Actualiza los modulos y roles asignados a un usuario."""
    form_data = await request.form()
    
    # Extraer módulos del form data
    module_roles = {}
    for key, value in form_data.items():
        if key.startswith("modulo_"):
            module_slug = key.replace("modulo_", "")
            if value:  # Solo si hay un rol seleccionado
                module_roles[module_slug] = value
    
    await service.update_user_modules(conn, user_id, module_roles)
    
    return templates.TemplateResponse(request, "admin/partials/messages/success.html", {"title": "Guardado", "message": "Permisos actualizados"
    })

@router.post("/users/{user_id}/preferred-module")
async def update_preferred_module(
    request: Request,
    user_id: UUID,
    modulo_slug: Optional[str] = Form(None),
    context = Depends(get_current_user_context),
    service: AdminService = Depends(get_admin_service),
    conn = Depends(get_db_connection),
    _ = require_module_access("admin", "admin")
):
    """Establece el modulo preferido del usuario."""
    await service.update_preferred_module(conn, user_id, modulo_slug if modulo_slug else None)
    
    return templates.TemplateResponse(request, "admin/partials/messages/success.html", {"title": "OK", "message": "Módulo preferido guardado"
    })

@router.get("/users/{user_id}/modules")
async def get_user_modules(
    user_id: UUID,
    _context = Depends(get_current_user_context),
    service: AdminService = Depends(get_admin_service),
    conn = Depends(get_db_connection),
    _ = require_module_access("admin", "admin")
):
    """Obtiene los módulos asignados a un usuario."""
    return await service.get_user_modules(conn, user_id)


@router.post("/users/{user_id}/simulation-flag")
async def update_simulation_flag(
    request: Request,
    user_id: UUID,
    puede_asignarse_simulacion: bool = Form(False),
    context = Depends(get_current_user_context),
    service: AdminService = Depends(get_admin_service),
    conn = Depends(get_db_connection),
    _ = require_module_access("admin", "admin")
):
    """Actualiza el flag que permite a un usuario ser asignado como responsable de simulacion."""
    await service.update_user_simulation_flag(conn, user_id, puede_asignarse_simulacion)

    return templates.TemplateResponse(request, "admin/partials/messages/success.html", {"title": "OK",
        "message": f"Flag simulación {'activado' if puede_asignarse_simulacion else 'desactivado'}"
    })


@router.post("/users/{user_id}/levantamiento-flag")
async def update_levantamiento_flag(
    request: Request,
    user_id: UUID,
    puede_asignarse_levantamientos: bool = Form(False),
    context = Depends(get_current_user_context),
    service: AdminService = Depends(get_admin_service),
    conn = Depends(get_db_connection),
    _ = require_module_access("admin", "admin")
):
    """Actualiza el flag que permite a un usuario ser asignado en levantamientos."""
    await service.update_user_levantamiento_flag(conn, user_id, puede_asignarse_levantamientos)

    return templates.TemplateResponse(request, "admin/partials/messages/success.html", {"title": "OK",
        "message": f"Flag levantamientos {'activado' if puede_asignarse_levantamientos else 'desactivado'}"
    })


@router.post("/users/{user_id}/rol-organizacional")
async def update_rol_organizacional(
    request: Request,
    user_id: UUID,
    rol_organizacional: str = Form(""),
    context = Depends(get_current_user_context),
    service: AdminService = Depends(get_admin_service),
    conn = Depends(get_db_connection),
    _ = require_module_access("admin", "admin")
):
    """Actualiza el rol organizacional del usuario (jefe_comercial, jefe_ingenieria, jefe_construccion, director, o ninguno)."""
    try:
        await service.update_user_rol_organizacional(conn, user_id, rol_organizacional)
        return templates.TemplateResponse(request, "admin/partials/messages/success.html", {"title": "OK",
            "message": "Rol organizacional actualizado"
        })
    except ValueError as e:
        return templates.TemplateResponse(request, "admin/partials/messages/error.html", {"title": "Error",
            "message": str(e)
        }, status_code=400)


# --- ABM DE CATÁLOGOS ---

@router.post("/catalogs/tecnologias")
async def create_tecnologia(
    request: Request,
    nombre: str = Form(...),
    service: AdminService = Depends(get_admin_service),
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context),
    _ = require_module_access("admin", "admin")
):
    """Crea una nueva tecnologia en el catalogo."""
    try:
        await service.create_tecnologia(conn, nombre)
        return templates.TemplateResponse(request, "admin/partials/messages/success.html", {"title": "Tecnología Creada",
            "message": f"La tecnología '{nombre}' fue creada exitosamente."
        })
    except ValueError as e:
        return templates.TemplateResponse(request, "admin/partials/messages/error.html", {"title": "Error de Validación",
            "message": str(e)
        }, status_code=400)

@router.post("/catalogs/tipos")
async def create_tipo_solicitud(
    request: Request,
    nombre: str = Form(...),
    codigo_interno: str = Form(...),
    service: AdminService = Depends(get_admin_service),
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context),
    _ = require_module_access("admin", "admin")
):
    """Crea un nuevo tipo de solicitud."""
    try:
        await service.create_tipo_solicitud(conn, nombre, codigo_interno)
        return templates.TemplateResponse(request, "admin/partials/messages/success.html", {"title": "Tipo Creado",
            "message": f"El tipo '{nombre}' fue creado exitosamente."
        })
    except ValueError as e:
        return templates.TemplateResponse(request, "admin/partials/messages/error.html", {"title": "Error de Validación",
            "message": str(e)
        }, status_code=400)
    except asyncpg.PostgresError as e:
        return templates.TemplateResponse(request, "admin/partials/messages/error.html", {"title": "Error de Base de Datos",
            "message": "No se pudo guardar en la base de datos. Intente nuevamente."
        }, status_code=500)

@router.post("/catalogs/estatus")
async def create_estatus(
    request: Request,
    nombre: str = Form(...),
    descripcion: str = Form(""),
    color_hex: str = Form(...),
    service: AdminService = Depends(get_admin_service),
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context),
    _ = require_module_access("admin", "admin")
):
    """Crea un nuevo estatus global con color."""
    try:
        await service.create_estatus(conn, nombre, descripcion, color_hex)
        return templates.TemplateResponse(request, "admin/partials/messages/success.html", {"title": "Estatus Creado",
            "message": f"El estatus '{nombre}' fue creado exitosamente."
        })
    except ValueError as e:
        return templates.TemplateResponse(request, "admin/partials/messages/error.html", {"title": "Error de Validación",
            "message": str(e)
        }, status_code=400)
    except asyncpg.PostgresError as e:
        return templates.TemplateResponse(request, "admin/partials/messages/error.html", {"title": "Error de Base de Datos",
            "message": "No se pudo guardar en la base de datos. Intente nuevamente."
        }, status_code=500)


@router.post("/catalogs/origenes")
async def create_origen_adjunto(
    request: Request,
    slug: str = Form(...),
    descripcion: str = Form(""),
    service: AdminService = Depends(get_admin_service),
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context),
    _ = require_module_access("admin", "admin")
):
    """Crea un nuevo origen de adjunto."""
    try:
        await service.create_origen_adjunto(conn, slug, descripcion)
        return templates.TemplateResponse(request, "admin/partials/messages/success.html", {"title": "Origen Creado",
            "message": f"El origen '{slug}' fue creado exitosamente."
        })
    except ValueError as e:
        return templates.TemplateResponse(request, "admin/partials/messages/error.html", {"title": "Error de Validación",
            "message": str(e)
        }, status_code=400)
    except asyncpg.PostgresError as e:
        return templates.TemplateResponse(request, "admin/partials/messages/error.html", {"title": "Error de Base de Datos",
            "message": "No se pudo guardar en la base de datos. Intente nuevamente."
        }, status_code=500)


# Include sub-routers
router.include_router(endpoints_correos_notif.router, tags=["Admin - Correos Notificaciones"])


# --- CONFIGURACIÓN UMBRALES KPI ---

@router.get("/config-umbrales", include_in_schema=False)
async def get_config_umbrales(
    request: Request,
    conn = Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("admin")
):
    """Página de configuración de umbrales KPI"""
    
    # Obtener configuración actual (Defaults a SIMULACION)
    umbrales_interno = await ConfigService.get_umbrales_kpi(conn, "kpi_interno", "SIMULACION")
    umbrales_compromiso = await ConfigService.get_umbrales_kpi(conn, "kpi_compromiso", "SIMULACION")
    
    if request.headers.get("hx-request"):
        template = "admin/config_umbrales.html"
    else:
        # Si no es HTMX, renderizar dentro del dashboard (necesitamos un wrapper si dashboard.html no soporta block content dinámico aparte de partials)
        # O simplemente renderizar la vista completa si existe un layout
        # Asumiremos que el dashboard carga esto vía HTMX o es una vista standalone que extiende base
        template = "admin/config_umbrales_dashboard.html"
        # FIX: Por simplicidad y consistencia con el dashboard admin, usaremos el mismo template
        # pero inyectando el contenido si el dashboard lo soporta, o simplemente retornando el partial
        # si la navegación es full SPA.
        # En este proyecto, admin usa dashboard.html como base.
        # Crearemos config_umbrales.html como extensión de base o partial.
        # Si es full GET, retornamos una página completa que incluye el partial.
        template = "admin/config_umbrales_full.html" 

    # Revisitando la estructura del proyecto en admin/dashboard.html (step 36 file view):
    # El dashboard admin parece ser una vista única.
    # Para simplificar, usaremos config_umbrales.html (partial) y si es full load, redirigir al dashboard O renderizar wrapper.
    # La propuesta del usuario dice: "config_umbrales_dashboard.html" para full load.
    
    return templates.TemplateResponse(request, template, {"umbrales_interno": umbrales_interno,
        "umbrales_compromiso": umbrales_compromiso,
        **context
    })


# --- REPORTE SEMANAL ---

@router.api_route("/ui/reporte-semanal", methods=["GET", "HEAD"], include_in_schema=False)
async def reporte_semanal_page(
    request: Request,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    service: AdminService = Depends(get_admin_service),
    _=require_module_access("admin"),
):
    """Página de reporte semanal de actividad en ECO."""
    reporte = await service.generar_reporte_semanal(conn)
    destinatarios_raw = await ConfigService.get_global_config(
        conn, "reporte_semanal_destinatarios", "", str
    )
    destinatarios_configurados = bool(destinatarios_raw.strip())
    activo_raw = await ConfigService.get_global_config(conn, "reporte_semanal_activo", "true", str)
    reporte_semanal_activo = activo_raw.lower() == "true"

    from datetime import timedelta
    ctx = {
        "datos": reporte["datos"],
        "fecha_inicio": reporte["fecha_inicio"],
        "fecha_fin_display": reporte["fecha_fin"] - timedelta(days=1),
        "destinatarios_configurados": destinatarios_configurados,
        "reporte_semanal_activo": reporte_semanal_activo,
        **context,
    }

    if request.headers.get("hx-request"):
        return templates.TemplateResponse(request, "admin/partials/reporte_semanal.html", ctx)
    return templates.TemplateResponse(request, "admin/reporte_semanal_full.html", ctx)


@router.post("/reportes/enviar-semanal", include_in_schema=False)
async def enviar_reporte_semanal(
    request: Request,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    service: AdminService = Depends(get_admin_service),
    _=require_module_access("admin"),
):
    """Envía el reporte semanal por correo de forma manual desde el panel admin."""
    enviado = await service.enviar_reporte_semanal(conn)
    if enviado:
        return templates.TemplateResponse(request, "admin/partials/messages/success.html", {"title": "Correo enviado",
            "message": "El reporte semanal fue enviado correctamente.",
        })
    return templates.TemplateResponse(request, "admin/partials/messages/error.html", {"title": "Sin destinatarios",
        "message": "Configura los destinatarios en Configuracion Global antes de enviar.",
    }, status_code=400)


@router.post("/reportes/cron/reporte-semanal", include_in_schema=False)
async def enviar_reporte_semanal_cron(
    request: Request,
    conn=Depends(get_db_connection),
    service: AdminService = Depends(get_admin_service),
    x_cron_secret: Optional[str] = Header(default=None),
):
    """
    Endpoint para el Cron Job de Railway.
    Protegido exclusivamente con el header X-Cron-Secret.
    No requiere sesión de usuario.
    """
    if not settings.CRON_SECRET or x_cron_secret != settings.CRON_SECRET:
        raise HTTPException(status_code=401, detail="No autorizado")

    activo_raw = await ConfigService.get_global_config(conn, "reporte_semanal_activo", "true", str)
    if activo_raw.lower() != "true":
        return {"enviado": False, "motivo": "desactivado"}

    enviado = await service.enviar_reporte_semanal(conn)
    return {"enviado": enviado}


# ========================================
# BOM — Aprobador Final
# ========================================

@router.get("/bom-config", include_in_schema=False)
async def bom_config_ui(
    request: Request,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    service: AdminService = Depends(get_admin_service),
    _=require_module_access("admin"),
):
    """Partial HTMX: configuracion del aprobador final del BOM."""
    from core.bom.service import BomService
    bom_service = BomService()
    aprobador_id = await bom_service.get_aprobador_final_id(conn)
    users = await service.db.fetch_all_users(conn)
    activos = [u for u in users if u.get('is_active')]
    return templates.TemplateResponse(request, "admin/partials/bom_aprobador_final.html", {"aprobador_id": str(aprobador_id) if aprobador_id else None,
        "usuarios": activos,
    })


@router.post("/bom-config/aprobador-final", include_in_schema=False)
async def set_aprobador_final(
    request: Request,
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("admin"),
):
    """Actualiza el aprobador final del BOM en configuracion global."""
    form = await request.form()
    user_id_raw = form.get("aprobador_final_id", "").strip()
    try:
        from uuid import UUID as _UUID
        from core.bom.db_service import BomDBService
        bom_db = BomDBService()
        user_id = _UUID(user_id_raw)
        await bom_db.set_aprobador_final_id(conn, user_id)
        ConfigService.invalidar_cache()
        return templates.TemplateResponse(request, "shared/toast.html", {"message": "Aprobador final del BOM actualizado",
            "type": "success",
        })
    except (ValueError, AttributeError) as e:
        return templates.TemplateResponse(request, "shared/toast.html", {"message": f"Error: {e}", "type": "error"
        })
    except asyncpg.PostgresError:
        import logging
        logging.getLogger("AdminRouter").exception("Error al actualizar aprobador final BOM")
        return templates.TemplateResponse(request, "shared/toast.html", {"message": "Error interno al guardar", "type": "error"
        })


@router.post("/api/config-umbrales/guardar", include_in_schema=False)
async def guardar_umbrales(
    request: Request,
    tipo_kpi: str = Form(...),
    umbral_excelente: float = Form(...),
    umbral_bueno: float = Form(...),
    departamento: str = Form("SIMULACION"), # Default a SIMULACION si no viene
    conn = Depends(get_db_connection),
    service: AdminService = Depends(get_admin_service),
    context=Depends(get_current_user_context),
    _=require_module_access("admin")
):
    """Guarda nueva configuración de umbrales"""
    
    # Validaciones
    if umbral_excelente <= umbral_bueno:
        return templates.TemplateResponse(request, "admin/partials/messages/error.html", {"title": "Error",
            "message": "El umbral excelente debe ser mayor que el bueno"
        })
    
    if umbral_bueno <= 0 or umbral_excelente > 100:
        return templates.TemplateResponse(request, "admin/partials/messages/error.html", {"title": "Error",
            "message": "Los umbrales deben estar entre 0 y 100"
        })
    
    await service.db.update_umbrales_kpi(
        conn, tipo_kpi, departamento, umbral_excelente, umbral_bueno, context.get("user_id")
    )
    
    # Invalidar cache
    ConfigService.invalidar_cache()
    
    return templates.TemplateResponse(request, "admin/partials/messages/success.html", {"title": "Guardado",
        "message": f"Umbrales de {tipo_kpi} actualizados correctamente"
    })


@router.post("/sat/fiel", response_class=HTMLResponse)
async def guardar_fiel_config(
    request: Request,
    conn=Depends(get_db_connection),
    service: AdminService = Depends(get_admin_service),
    _=Depends(get_current_user_context),
    __=require_role(["ADMIN"]),
):
    form = await request.form()
    sp_path_cer = form.get("sp_path_cer", "").strip()
    sp_path_key = form.get("sp_path_key", "").strip()
    password_fiel = form.get("password_fiel", "").strip()

    if not sp_path_cer or not sp_path_key:
        return templates.TemplateResponse(
            request,
            "shared/toast.html",
            {"message": "Las rutas .cer y .key son obligatorias", "type": "error"},
            headers={"HX-Reswap": "none"},
        )

    # Si no se envió password, verificar si ya existe una configuración previa
    if not password_fiel:
        existing_config = await service.db.fetch_fiel_config(conn)
        existing_password = existing_config.get("password_fiel")
        if not existing_password:
            return templates.TemplateResponse(
                request,
                "shared/toast.html",
                {"message": "La contraseña FIEL es obligatoria en la primera configuración", "type": "error"},
                headers={"HX-Reswap": "none"},
            )
        password_fiel = existing_password

    try:
        # TODO: cifrar password_fiel en BD (pgcrypto o Key Vault) — actualmente texto plano
        await service.db.guardar_fiel_config(conn, sp_path_cer, sp_path_key, password_fiel)
    except asyncpg.PostgresError:
        logger.exception("Error guardando config FIEL")
        return templates.TemplateResponse(
            request,
            "shared/toast.html",
            {"message": "Error de base de datos al guardar FIEL", "type": "error"},
            headers={"HX-Reswap": "none"},
        )

    return templates.TemplateResponse(
        request,
        "shared/toast.html",
        {"message": "Configuración FIEL guardada correctamente", "type": "success"},
        headers={"HX-Reswap": "none"},
    )


@router.post("/sat/fiel/probar", response_class=HTMLResponse)
async def probar_fiel(
    request: Request,
    conn=Depends(get_db_connection),
    _=Depends(get_current_user_context),
    __=require_role(["ADMIN"]),
):
    from core.sat.fiel_loader import probar_conexion_fiel

    svc = AdminService()
    config = await svc.get_global_config(conn)
    sat_site_id = config.get("sp_sat_site_id") or settings.SP_SAT_SITE_ID
    sat_drive_id = config.get("sp_sat_drive_id") or settings.SP_SAT_DRIVE_ID

    if not sat_site_id or not sat_drive_id:
        return templates.TemplateResponse(
            request,
            "shared/toast.html",
            {"message": "Configura SP_SAT_SITE_ID y SP_SAT_DRIVE_ID antes de probar la FIEL", "type": "error"},
            headers={"HX-Reswap": "none"},
        )

    try:
        rfc = await probar_conexion_fiel(conn, sat_site_id, sat_drive_id)
        message = f"FIEL cargada correctamente - RFC: {rfc}"
        type_ = "success"
    except ValueError as e:
        message = f"Error: {e}"
        type_ = "error"
    except asyncpg.PostgresError:
        logger.exception("Error de BD al probar FIEL")
        message = "Error de base de datos al leer config FIEL"
        type_ = "error"

    return templates.TemplateResponse(
        request,
        "shared/toast.html",
        {"message": message, "type": type_},
        headers={"HX-Reswap": "none"},
    )
