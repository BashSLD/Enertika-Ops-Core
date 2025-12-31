from fastapi import APIRouter, Request, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse
from core.database import get_db_connection
from fastapi.templating import Jinja2Templates
from core.security import get_current_user_context
from core.permissions import require_module_access
from .service import AdminService, get_admin_service
from .schemas import ConfiguracionGlobalUpdate, TecnologiaCreate

router = APIRouter(
    prefix="/admin",
    tags=["Admin"]
)

templates = Jinja2Templates(directory="templates")

# --- CONFIG EMAIL ENDPOINTS ---

@router.get("/ui", include_in_schema=False)
async def admin_dashboard(
    request: Request,
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context),
    service: AdminService = Depends(get_admin_service),  # OK - NUEVO: Inyectar service
    _ = require_module_access("admin")
):
    """Dashboard principal: Lista usuarios, Reglas, Departamentos y Módulos."""
    
    # OK - REFACTORIZADO: Usar service layer en lugar de queries directas
    users_enriched = await service.get_users_enriched(conn)
    rules = await service.get_email_rules(conn)
    defaults = await service.get_email_defaults(conn)
    departments_dict = await service.get_departments_catalog(conn)
    modules_dict = await service.get_modules_catalog(conn)
    catalogos = await service.get_catalogos_reglas(conn)
    global_config = await service.get_global_config(conn)  # OK - NUEVO: Configuración Global
    import logging
    logging.getLogger("AdminRouter").info(f"Dashboard Config Loaded: {global_config}")
    
    return templates.TemplateResponse("admin/dashboard.html", {
        "request": request,
        "users": users_enriched,
        "rules": rules,
        "defaults": defaults,
        "departments": departments_dict,
        "modules": modules_dict,
        "catalogos": catalogos,
        "config_global": global_config,  # OK - NUEVO: Pasar config al template
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
    if context.get("role") not in ["ADMIN", "MANAGER"]:
        return HTMLResponse("<span class='text-red-600 font-bold'>ERROR: Acceso denegado</span>", status_code=403)
    
    # OK - REFACTORIZADO: Usar service
    await service.update_user_role(conn, user_id, role)
    return HTMLResponse(f"<span class='text-green-600 font-bold'>Rol actualizado a {role}</span>", status_code=200)

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
    if context.get("role") not in ["ADMIN", "MANAGER"]:
        return HTMLResponse("<div class='bg-red-100 p-2 rounded'>ERROR: Acceso denegado</div>", status_code=403)
    
    # OK - REFACTORIZADO: Usar service
    await service.add_email_rule(conn, modulo, trigger_field, trigger_value, email_to_add, type)
    
    return HTMLResponse(f"""
        <div class='bg-green-100 p-2 rounded'>Regla agregada</div>
        <script>window.location.reload()</script>
    """, status_code=200)

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
    if context.get("role") not in ["ADMIN", "MANAGER"]:
        raise HTTPException(status_code=403, detail="Acceso denegado")
    
    # OK - REFACTORIZADO: Delegar al service
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
    if context.get("role") not in ["ADMIN", "MANAGER"]:
        raise HTTPException(status_code=403, detail="Acceso denegado")
    
    # OK - REFACTORIZADO: Delegar al service
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
    if context.get("role") not in ["ADMIN", "MANAGER"]:
        return HTMLResponse("", status_code=403)
    
    # OK - REFACTORIZADO: Usar service
    await service.delete_email_rule(conn, id)
    return HTMLResponse("", status_code=200)

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
    if context.get("role") not in ["ADMIN", "MANAGER"]:
        return HTMLResponse("<div class='bg-red-100 p-2 rounded'>ERROR: Acceso denegado</div>", status_code=403)
    
    # OK - REFACTORIZADO: Usar service
    await service.update_email_defaults(conn, default_to, default_cc, default_cco)
    
    return HTMLResponse(f"""
        <div class="bg-green-100 border-l-4 border-green-500 text-green-700 p-2 mb-4 animate-fade-in-down" id="defaults-msg">
            <p class="font-bold">✓ Configuración Actualizada</p>
        </div>
        <script>
            setTimeout(() => document.getElementById('defaults-msg').remove(), 3000);
        </script>
    """, status_code=200)

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
        return HTMLResponse("""
            <input type="text" name="trigger_value" required placeholder="Valor exacto..."
                   class="w-full rounded-lg border-gray-300 focus:ring-[#00BABB] focus:border-[#00BABB]" />
        """)

@router.post("/config/global")
async def update_global_config_endpoint(
    request: Request,
    hora_corte_l_v: str = Form(...),
    dias_sla_default: int = Form(...),
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
    if context.get("role") not in ["ADMIN", "MANAGER"]:
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
            dias_fin_semana=dias_fin_semana
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
        "message": f"Las reglas de negocio se han aplicado correctamente. SLA: {dias_sla_default} días, Hora corte: {hora_corte_l_v}"
    })

# --- USER MANAGEMENT ENDPOINTS ---

from uuid import UUID
from typing import List


@router.post("/users/{user_id}/department")
async def update_user_department(
    user_id: UUID,
    department_slug: str = Form(...),
    context = Depends(get_current_user_context),
    service: AdminService = Depends(get_admin_service),
    conn = Depends(get_db_connection)
):
    """Asigna un departamento a un usuario."""
    # Validación: Solo ADMIN/MANAGER
    if context.get("role") not in ["ADMIN", "MANAGER"]:
        return HTMLResponse("<span class='text-red-600 font-bold'>ERROR: Acceso denegado</span>", status_code=403)
    
    try:
        # OK - REFACTORIZADO: Usar service
        dept_nombre = await service.update_user_department(conn, user_id, department_slug)
        return HTMLResponse(
            f"<span class='text-green-600 font-bold'>Departamento actualizado a {dept_nombre}</span>",
            status_code=200
        )
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
    if context.get("role") not in ["ADMIN", "MANAGER"]:
        return HTMLResponse("<span class='text-red-600 font-bold'>ERROR: Acceso denegado</span>", status_code=403)
    
    form_data = await request.form()
    
    # Extraer módulos del form data
    module_roles = {}
    for key, value in form_data.items():
        if key.startswith("modulo_"):
            module_slug = key.replace("modulo_", "")
            if value:  # Solo si hay un rol seleccionado
                module_roles[module_slug] = value
    
    # OK - REFACTORIZADO: Usar service
    await service.update_user_modules(conn, user_id, module_roles)
    
    return HTMLResponse(
        "<span class='text-green-600 font-bold'>Módulos actualizados correctamente</span>",
        status_code=200
    )

@router.post("/users/{user_id}/preferred-module")
async def update_preferred_module(
    user_id: UUID,
    modulo_slug: str = Form(...),
    context = Depends(get_current_user_context),
    service: AdminService = Depends(get_admin_service),
    conn = Depends(get_db_connection)
):
    """Establece el módulo preferido del usuario (a dónde va al login)."""
    # Validación: Solo ADMIN/MANAGER
    if context.get("role") not in ["ADMIN", "MANAGER"]:
        return HTMLResponse("<span class='text-red-600 font-bold'>ERROR: Acceso denegado</span>", status_code=403)
    
    # OK - REFACTORIZADO: Usar service
    await service.update_preferred_module(conn, user_id, modulo_slug if modulo_slug else None)
    
    return HTMLResponse(
        "<span class='text-green-600 font-bold'>Módulo preferido actualizado</span>",
        status_code=200
    )

@router.get("/users/{user_id}/modules")
async def get_user_modules(
    user_id: UUID, 
    service: AdminService = Depends(get_admin_service),
    conn = Depends(get_db_connection)
):
    """Obtiene los módulos asignados a un usuario."""
    # OK - REFACTORIZADO: Usar service
    return await service.get_user_modules(conn, user_id)


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
    if context.get("role") not in ["ADMIN", "MANAGER"]:
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
    if context.get("role") not in ["ADMIN", "MANAGER"]:
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
    except Exception as e:
        return templates.TemplateResponse("admin/partials/messages/error.html", {
            "request": request,
            "title": "Error",
            "message": f"No se pudo crear: {str(e)}"
        }, status_code=400)

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
    if context.get("role") not in ["ADMIN", "MANAGER"]:
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
    except Exception as e:
        return templates.TemplateResponse("admin/partials/messages/error.html", {
            "request": request,
            "title": "Error",
            "message": f"No se pudo crear: {str(e)}"
        }, status_code=400)
