# modules/admin/endpoints_correos_not.py
"""
Endpoints CRUD para gestión de correos de notificaciones.
Separado por claridad, se importa en router.py principal.
"""
from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from uuid import UUID, uuid4
from typing import Optional

from core.database import get_db_connection
from core.security import get_current_user_context
from core.permissions import require_module_access

templates = Jinja2Templates(directory="templates")

router = APIRouter()


@router.get("/config-correos-notificaciones/list", include_in_schema=False)
async def list_config_correos(
    request: Request,
    conn = Depends(get_db_connection),
    _ = require_module_access("admin", "owner")
):
    """Lista todas las configuraciones de correos de notificaciones."""
    configs = await conn.fetch("""
        SELECT id, departamento, email_remitente, nombre_remitente, 
               descripcion, activo, updated_at, updated_by
        FROM tb_correos_notificaciones
        ORDER BY 
            CASE WHEN departamento = 'DEFAULT' THEN 0 ELSE 1 END,
            departamento, 
            activo DESC
    """)
    
    return templates.TemplateResponse("admin/partials/config_correos_list.html", {
        "request": request,
        "configs": configs
    })


@router.get("/config-correos-notificaciones/form", include_in_schema=False)
async def new_config_correo_form(
    request: Request,
    _ = require_module_access("admin", "owner")
):
    """Formulario para nueva configuración de correo."""
    return templates.TemplateResponse("admin/partials/config_correos_form.html", {
        "request": request,
        "config": None
    })


@router.get("/config-correos-notificaciones/edit/{config_id}", include_in_schema=False)
async def edit_config_correo_form(
    request: Request,
    config_id: UUID,
    conn = Depends(get_db_connection),
    _ = require_module_access("admin", "owner")
):
    """Formulario para editar configuración de correo."""
    config = await conn.fetchrow(
        "SELECT * FROM tb_correos_notificaciones WHERE id = $1",
        config_id
    )
    
    if not config:
        return HTMLResponse("Configuración no encontrada", status_code=404)
    
    return templates.TemplateResponse("admin/partials/config_correos_form.html", {
        "request": request,
        "config": config
    })


@router.post("/config-correos-notificaciones/save")
async def save_config_correo(
    request: Request,
    id: Optional[str] = Form(None),
    departamento: str = Form(...),
    email_remitente: str = Form(...),
    nombre_remitente: str = Form(...),
    descripcion: Optional[str] = Form(None),
    activo: Optional[str] = Form(None),  # Checkbox viene como string o None
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context),
    _ = require_module_access("admin", "owner")
):
    """Guarda o actualiza configuración de correo de notificaciones."""
    
    # Validar email
    if '@' not in email_remitente or '.' not in email_remitente:
        return HTMLResponse(
            "<div class='text-red-600'>Email inválido. Debe ser un correo válido.</div>",
            status_code=400
        )
    
    # Convertir checkbox a boolean
    activo_bool = activo == 'true' if activo else False
    
    async with conn.transaction():
        # Si se activa, desactivar otras del mismo departamento
        if activo_bool:
            config_id = UUID(id) if id else uuid4()
            await conn.execute("""
                UPDATE tb_correos_notificaciones 
                SET activo = false 
                WHERE departamento = $1 AND id != $2
            """, departamento.upper(), config_id)
        
        if id:
            # Actualizar existente
            await conn.execute("""
                UPDATE tb_correos_notificaciones
                SET departamento = $1,
                    email_remitente = $2,
                    nombre_remitente = $3,
                    descripcion = $4,
                    activo = $5,
                    updated_at = NOW(),
                    updated_by = $6
                WHERE id = $7
            """, departamento.upper(), email_remitente, nombre_remitente, 
                 descripcion, activo_bool, context['user_db_id'], UUID(id))
        else:
            # Crear nueva
            await conn.execute("""
                INSERT INTO tb_correos_notificaciones
                    (departamento, email_remitente, nombre_remitente, descripcion, activo, updated_by)
                VALUES ($1, $2, $3, $4, $5, $6)
            """, departamento.upper(), email_remitente, nombre_remitente, 
                 descripcion, activo_bool, context['user_db_id'])
    
    return HTMLResponse("OK", status_code=200)


@router.post("/config-correos-notificaciones/activate/{config_id}")
async def activate_config_correo(
    config_id: UUID,
    conn = Depends(get_db_connection),
    _ = require_module_access("admin", "owner")
):
    """Activa una configuración de correo (desactivando otras del mismo departamento)."""
    
    async with conn.transaction():
        # Obtener departamento de la config a activar
        config = await conn.fetchrow(
            "SELECT departamento FROM tb_correos_notificaciones WHERE id = $1",
            config_id
        )
        
        if not config:
            return HTMLResponse("Configuración no encontrada", status_code=404)
        
        # Desactivar todas las del mismo departamento
        await conn.execute("""
            UPDATE tb_correos_notificaciones 
            SET activo = false 
            WHERE departamento = $1
        """, config['departamento'])
        
        # Activar la seleccionada
        await conn.execute("""
            UPDATE tb_correos_notificaciones 
            SET activo = true, updated_at = NOW()
            WHERE id = $1
        """, config_id)
    
    return HTMLResponse("OK", status_code=200)
