from fastapi import APIRouter, Request, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse, Response
from core.database import get_db_connection
from fastapi.templating import Jinja2Templates
from core.security import get_current_user_context
from core.permissions import require_module_access

from core.config import settings
from .service import AdminService, get_admin_service
import asyncpg

# Import endpoints separados
from . import endpoints_correos_notif
from . import endpoints_correos_notif
from .schemas import ConfiguracionGlobalUpdate, TecnologiaCreate
from core.config_service import ConfigService

router = APIRouter(
    prefix="/admin",
    tags=["Admin"]
)

templates = Jinja2Templates(directory="templates")
templates.env.globals["DEBUG_MODE"] = settings.DEBUG_MODE

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
    users_enriched = await service.get_users_enriched(conn)
    rules = await service.get_email_rules(conn)
    defaults = await service.get_email_defaults(conn)
    departments_dict = await service.get_departments_catalog(conn)
    modules_dict = await service.get_modules_catalog(conn)
    catalogos = await service.get_catalogos_reglas(conn)
    global_config = await service.get_global_config(conn)
    import logging
    logging.getLogger("AdminRouter").debug(f"Dashboard Config Loaded: {global_config}")
    
    return templates.TemplateResponse("admin/dashboard.html", {
        "request": request,
        "users": users_enriched,
        "rules": rules,
        "defaults": defaults,
        "departments": departments_dict,
        "modules": modules_dict,
        "catalogos": catalogos,
        "config_global": global_config,
        "user_name": context.get("user_name"),
        "role": context.get("role"),
        "module_roles": context.get("module_roles", {})
    })

@router.post("/users/role")
async def update_user_role(
    request: Request,
    user_id: str = Form(...),
    role: str = Form(...),
    context = Depends(get_current_user_context),
    service: AdminService = Depends(get_admin_service),
    conn = Depends(get_db_connection)
):
    """Actualiza el rol de sistema de un usuario (HTMX)."""
    # Validación: Solo ADMIN/MANAGER pueden cambiar roles
    if context.get("role") not in ["ADMIN"]:
        return templates.TemplateResponse("admin/partials/messages/error.html", {
            "request": request,
            "title": "Acceso Denegado",
            "message": "No tienes permisos para realizar esta acción."
        }, status_code=403)
    
    await service.update_user_role(conn, user_id, role)
    return templates.TemplateResponse("admin/partials/messages/success.html", {
        "request": request,
        "title": "Actualizado", 
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
    conn = Depends(get_db_connection)
):
    """Agrega una nueva regla de correo."""
    # Validación: Solo ADMIN/MANAGER
    if context.get("role") not in ["ADMIN"]:
        return templates.TemplateResponse("admin/partials/messages/error.html", {
            "request": request,
            "title": "Acceso Denegado",
            "message": "No tienes permisos para realizar esta acción."
        }, status_code=403)
    
    await service.add_email_rule(conn, modulo, trigger_field, trigger_value, email_to_add, type)
    
    # HTMX detecta este header y recarga la página automáticamente
    return Response(status_code=200, headers={"HX-Refresh": "true"})

@router.delete("/users/{user_id}")
async def delete_user(
    request: Request,
    user_id: str,
    context = Depends(get_current_user_context),
    service: AdminService = Depends(get_admin_service),
    conn = Depends(get_db_connection)
):
    """Desactiva un usuario (Soft delete)."""
    # Validación: Solo ADMIN/MANAGER
    if context.get("role") not in ["ADMIN"]:
        raise HTTPException(status_code=403, detail="Acceso denegado")    
    user = await service.deactivate_user(conn, user_id)
    
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    # Retornar fila actualizada
    return templates.TemplateResponse("admin/partials/user_row.html", {
        "request": request,
        "u": user
    })

@router.post("/users/{user_id}/restore")
async def restore_user(
    request: Request,
    user_id: str,
    context = Depends(get_current_user_context),
    service: AdminService = Depends(get_admin_service),
    conn = Depends(get_db_connection)
):
    """Reactiva un usuario (Soft delete restore)."""
    # Validación: Solo ADMIN/MANAGER
    if context.get("role") not in ["ADMIN"]:
        raise HTTPException(status_code=403, detail="Acceso denegado")
    user = await service.reactivate_user(conn, user_id)
    
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    # Retornar fila actualizada
    return templates.TemplateResponse("admin/partials/user_row.html", {
        "request": request,
        "u": user
    })

@router.delete("/rules/{id}")
async def delete_email_rule(
    request: Request,
    id: int,
    context = Depends(get_current_user_context),
    service: AdminService = Depends(get_admin_service),
    conn = Depends(get_db_connection)
):
    """Elimina una regla."""
    # Validación: Solo ADMIN/MANAGER
    if context.get("role") not in ["ADMIN"]:
        return Response(status_code=403)
    await service.delete_email_rule(conn, id)
    
    # Retornar template partial con feedback visual
    return templates.TemplateResponse("admin/partials/rule_deleted.html", {
        "request": request,
        "rule_id": id
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
    conn = Depends(get_db_connection)
):
    """Actualiza configuración global de correos (TO, CC, CCO)."""
    # Validación: Solo ADMIN/MANAGER
    if context.get("role") not in ["ADMIN"]:
        return templates.TemplateResponse("admin/partials/messages/error.html", {
            "request": request,
            "title": "Acceso Denegado",
            "message": "No tienes permisos para realizar esta acción."
        }, status_code=403)
    await service.update_email_defaults(conn, default_to, default_cc, default_cco)
    
    return templates.TemplateResponse("admin/partials/messages/success.html", {
        "request": request,
        "title": "Configuración Actualizada",
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
        return templates.TemplateResponse("admin/partials/dynamic_trigger_select.html", {
            "request": request,
            "options": options
        })
    else:
        # Renderizar como Input Text libre
        return templates.TemplateResponse("admin/partials/dynamic_trigger_input.html", {"request": request})

from . import endpoints_correos_notif
from .schemas import ConfiguracionGlobalUpdate, TecnologiaCreate, OrigenAdjuntoCreate

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
    # Validación: Solo ADMIN/MANAGER pueden cambiar configuración global
    if context.get("role") not in ["ADMIN"]:
        return templates.TemplateResponse("admin/partials/messages/error.html", {
            "request": request,
            "title": "Acceso Denegado",
            "message": "No tienes permisos para modificar la configuración global."
        }, status_code=403)
    
    # Obtener días de fin de semana desde form (checkboxes)
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
            sim_volumen_max=sim_volumen_max
        )
    except ValueError as e:
        return templates.TemplateResponse("admin/partials/messages/error.html", {
            "request": request,
            "title": "Error de Validación",
            "message": str(e)
        }, status_code=400)
    
    # 2. Guardar en base de datos
    await service.update_global_config(conn, datos)
    
    # 3. Retornar mensaje de éxito
    return templates.TemplateResponse("admin/partials/messages/success.html", {
        "request": request,
        "title": "Configuración Actualizada",
        "message": f"Reglas de negocio y parámetros de SharePoint actualizados correctamente."
    })

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
    if context.get("role") not in ["ADMIN"]:
        return templates.TemplateResponse("admin/partials/messages/error.html", {
            "request": request,
            "title": "Acceso Denegado",
            "message": "No tienes permisos para realizar esta acción."
        }, status_code=403)
        
    await service.reset_simulation_defaults(conn)
    
    return templates.TemplateResponse("admin/partials/messages/success.html", {
        "request": request,
        "title": "Valores Restaurados",
        "message": "Se han restablecido los valores por defecto para Simulación."
    })

# --- USER MANAGEMENT ENDPOINTS ---

from uuid import UUID
from typing import List


@router.post("/users/{user_id}/department")
async def update_user_department(
    request: Request,
    user_id: UUID,
    department_slug: str = Form(...),
    context = Depends(get_current_user_context),
    service: AdminService = Depends(get_admin_service),
    conn = Depends(get_db_connection)
):
    """Asigna un departamento a un usuario."""
    # Validación: Solo ADMIN/MANAGER
    if context.get("role") not in ["ADMIN"]:
        return templates.TemplateResponse("admin/partials/messages/error.html", {
            "request": request,
            "title": "Acceso Denegado",
            "message": "No tienes permisos para realizar esta acción."
        }, status_code=403)
    
    try:
        dept_nombre = await service.update_user_department(conn, user_id, department_slug)
        return templates.TemplateResponse("admin/partials/messages/success.html", {
            "request": request, "title": "Actualizado", "message": f"Depto: {dept_nombre}"
        })
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/users/{user_id}/modules")
async def update_user_modules(
    request: Request,
    user_id: UUID,
    context = Depends(get_current_user_context),
    service: AdminService = Depends(get_admin_service),
    conn = Depends(get_db_connection)
):
    """Actualiza los módulos y roles asignados a un usuario."""
    # Validación: Solo ADMIN/MANAGER
    if context.get("role") not in ["ADMIN"]:
        return templates.TemplateResponse("admin/partials/messages/error.html", {
            "request": request,
            "title": "Acceso Denegado",
            "message": "No tienes permisos para realizar esta acción."
        }, status_code=403)
    
    form_data = await request.form()
    
    # Extraer módulos del form data
    module_roles = {}
    for key, value in form_data.items():
        if key.startswith("modulo_"):
            module_slug = key.replace("modulo_", "")
            if value:  # Solo si hay un rol seleccionado
                module_roles[module_slug] = value
    
    await service.update_user_modules(conn, user_id, module_roles)
    
    return templates.TemplateResponse("admin/partials/messages/success.html", {
        "request": request, "title": "Guardado", "message": "Permisos actualizados"
    })

@router.post("/users/{user_id}/preferred-module")
async def update_preferred_module(
    request: Request,
    user_id: UUID,
    modulo_slug: str = Form(...),
    context = Depends(get_current_user_context),
    service: AdminService = Depends(get_admin_service),
    conn = Depends(get_db_connection)
):
    """Establece el módulo preferido del usuario (a dónde va al login)."""
    # Validación: Solo ADMIN/MANAGER
    if context.get("role") not in ["ADMIN"]:
        return templates.TemplateResponse("admin/partials/messages/error.html", {
            "request": request,
            "title": "Acceso Denegado",
            "message": "No tienes permisos para realizar esta acción."
        }, status_code=403)
    
    await service.update_preferred_module(conn, user_id, modulo_slug if modulo_slug else None)
    
    return templates.TemplateResponse("admin/partials/messages/success.html", {
        "request": request, "title": "OK", "message": "Módulo preferido guardado"
    })

@router.get("/users/{user_id}/modules")
async def get_user_modules(
    user_id: UUID, 
    service: AdminService = Depends(get_admin_service),
    conn = Depends(get_db_connection)
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
    conn = Depends(get_db_connection)
):
    """Actualiza el flag que permite a un usuario ser asignado como responsable de simulación."""
    if context.get("role") not in ["ADMIN"]:
        return templates.TemplateResponse("admin/partials/messages/error.html", {
            "request": request,
            "title": "Acceso Denegado",
            "message": "No tienes permisos para realizar esta acción."
        }, status_code=403)
    
    await service.update_user_simulation_flag(conn, user_id, puede_asignarse_simulacion)
    
    return templates.TemplateResponse("admin/partials/messages/success.html", {
        "request": request, 
        "title": "OK", 
        "message": f"Flag simulación {'activado' if puede_asignarse_simulacion else 'desactivado'}"
    })


# --- ABM DE CATÁLOGOS ---

@router.post("/catalogs/tecnologias")
async def create_tecnologia(
    request: Request,
    nombre: str = Form(...),
    service: AdminService = Depends(get_admin_service),
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context),
    _ = require_module_access("admin")
):
    """Crea una nueva tecnología en el catálogo."""
    if context.get("role") not in ["ADMIN"]:
        return templates.TemplateResponse("admin/partials/messages/error.html", {
            "request": request,
            "title": "Acceso Denegado",
            "message": "No tienes permisos para modificar catálogos."
        }, status_code=403)
    
    try:
        await service.create_tecnologia(conn, nombre)
        return templates.TemplateResponse("admin/partials/messages/success.html", {
            "request": request,
            "title": "Tecnología Creada",
            "message": f"La tecnología '{nombre}' fue creada exitosamente."
        })
    except ValueError as e:
        return templates.TemplateResponse("admin/partials/messages/error.html", {
            "request": request,
            "title": "Error de Validación",
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
    _ = require_module_access("admin")
):
    """Crea un nuevo tipo de solicitud."""
    if context.get("role") not in ["ADMIN"]:
        return templates.TemplateResponse("admin/partials/messages/error.html", {
            "request": request,
            "title": "Acceso Denegado",
            "message": "No tienes permisos para modificar catálogos."
        }, status_code=403)
    
    try:
        await service.create_tipo_solicitud(conn, nombre, codigo_interno)
        return templates.TemplateResponse("admin/partials/messages/success.html", {
            "request": request,
            "title": "Tipo Creado",
            "message": f"El tipo '{nombre}' fue creado exitosamente."
        })
    except ValueError as e:
        return templates.TemplateResponse("admin/partials/messages/error.html", {
            "request": request,
            "title": "Error de Validación",
            "message": str(e)
        }, status_code=400)
    except asyncpg.PostgresError as e:
        return templates.TemplateResponse("admin/partials/messages/error.html", {
            "request": request,
            "title": "Error de Base de Datos",
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
    _ = require_module_access("admin")
):
    """Crea un nuevo estatus global con color."""
    if context.get("role") not in ["ADMIN"]:
        return templates.TemplateResponse("admin/partials/messages/error.html", {
            "request": request,
            "title": "Acceso Denegado",
            "message": "No tienes permisos para modificar catálogos."
        }, status_code=403)
    
    try:
        await service.create_estatus(conn, nombre, descripcion, color_hex)
        return templates.TemplateResponse("admin/partials/messages/success.html", {
            "request": request,
            "title": "Estatus Creado",
            "message": f"El estatus '{nombre}' fue creado exitosamente."
        })
    except ValueError as e:
        return templates.TemplateResponse("admin/partials/messages/error.html", {
            "request": request,
            "title": "Error de Validación",
            "message": str(e)
        }, status_code=400)
    except asyncpg.PostgresError as e:
        return templates.TemplateResponse("admin/partials/messages/error.html", {
            "request": request,
            "title": "Error de Base de Datos",
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
    _ = require_module_access("admin")
):
    """Crea un nuevo origen de adjunto (Catalog)."""
    if context.get("role") not in ["ADMIN"]:
        return templates.TemplateResponse("admin/partials/messages/error.html", {
            "request": request,
            "title": "Acceso Denegado",
            "message": "No tienes permisos para modificar catálogos."
        }, status_code=403)
    
    try:
        await service.create_origen_adjunto(conn, slug, descripcion)
        return templates.TemplateResponse("admin/partials/messages/success.html", {
            "request": request,
            "title": "Origen Creado",
            "message": f"El origen '{slug}' fue creado exitosamente."
        })
    except ValueError as e:
        return templates.TemplateResponse("admin/partials/messages/error.html", {
            "request": request,
            "title": "Error de Validación",
            "message": str(e)
        }, status_code=400)
    except asyncpg.PostgresError as e:
        return templates.TemplateResponse("admin/partials/messages/error.html", {
            "request": request,
            "title": "Error de Base de Datos",
            "message": "No se pudo guardar en la base de datos. Intente nuevamente."
        }, status_code=500)


# Include sub-routers
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
    
    return templates.TemplateResponse(template, {
        "request": request,
        "umbrales_interno": umbrales_interno,
        "umbrales_compromiso": umbrales_compromiso,
        **context
    })


@router.post("/api/config-umbrales/guardar", include_in_schema=False)
async def guardar_umbrales(
    request: Request,
    tipo_kpi: str = Form(...),
    umbral_excelente: float = Form(...),
    umbral_bueno: float = Form(...),
    departamento: str = Form("SIMULACION"), # Default a SIMULACION si no viene
    conn = Depends(get_db_connection),
    context=Depends(get_current_user_context),
    _=require_module_access("admin")
):
    """Guarda nueva configuración de umbrales"""
    
    # Validaciones
    if umbral_excelente <= umbral_bueno:
        return templates.TemplateResponse("admin/partials/messages/error.html", {
            "request": request,
            "title": "Error",
            "message": "El umbral excelente debe ser mayor que el bueno"
        })
    
    if umbral_bueno <= 0 or umbral_excelente > 100:
        return templates.TemplateResponse("admin/partials/messages/error.html", {
            "request": request,
            "title": "Error",
            "message": "Los umbrales deben estar entre 0 y 100"
        })
    
    # Desactivar configuración anterior del mismo departamento
    await conn.execute("""
        UPDATE tb_config_umbrales_kpi
        SET activo = FALSE
        WHERE tipo_kpi = $1 
          AND activo = TRUE
          AND departamento = $2
    """, tipo_kpi, departamento)
    
    # Insertar nueva configuración
    await conn.execute("""
        INSERT INTO tb_config_umbrales_kpi (
            tipo_kpi,
            departamento,
            umbral_excelente,
            umbral_bueno,
            modificado_por_id,
            fecha_modificacion
        ) VALUES ($1, $2, $3, $4, $5, NOW())
    """, tipo_kpi, departamento, umbral_excelente, umbral_bueno, context.get("user_id"))
    
    # Invalidar cache
    ConfigService.invalidar_cache()
    
    return templates.TemplateResponse("admin/partials/messages/success.html", {
        "request": request,
        "title": "Guardado",
        "message": f"Umbrales de {tipo_kpi} actualizados correctamente"
    })
