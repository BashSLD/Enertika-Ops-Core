from fastapi import APIRouter, Request, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse
from core.database import get_db_connection
from fastapi.templating import Jinja2Templates

router = APIRouter(
    prefix="/admin",
    tags=["Admin"]
)

templates = Jinja2Templates(directory="templates")

# --- DEPENDENCY: Admin Check (Placeholder) ---
# En el futuro, aquí validaremos ms_auth y el rol 'ADMIN' o 'MANAGER'
async def admin_required(request: Request):
    # Por ahora simple check de session
    user = request.session.get("user_name")
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True

# --- CONFIG EMAIL ENDPOINTS ---

from core.security import get_current_user_context

@router.get("/ui", include_in_schema=False)
async def admin_dashboard(
    request: Request,
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context)
):
    """Dashboard principal: Lista usuarios y Reglas."""
    # 1. Usuarios
    users = await conn.fetch("SELECT * FROM tb_usuarios ORDER BY nombre")
    
    # 2. Reglas
    rules = await conn.fetch("SELECT * FROM tb_config_emails ORDER BY modulo, trigger_field")
    
    # 3. Defaults Globales
    defaults = await conn.fetchrow("SELECT * FROM tb_email_defaults WHERE id = 1")
    if not defaults:
        # Fallback in memory object if table empty (shouldn't happen if initialized)
        defaults = {"default_to": "", "default_cc": "", "default_cco": ""}
    
    return templates.TemplateResponse("admin/dashboard.html", {
        "request": request,
        "users": users,
        "rules": rules,
        "defaults": defaults,
        "user_name": context.get("user_name"),
        "role": context.get("role")
    })

@router.post("/users/role")
async def update_user_role(
    request: Request,
    user_id: str = Form(...),
    role: str = Form(...),
    conn = Depends(get_db_connection)
):
    """Actualiza el rol de sistema de un usuario (HTMX)."""
    # En producción validariamos permisos de quien solicita
    await conn.execute("UPDATE tb_usuarios SET rol_sistema = $1 WHERE id_usuario = $2", role, user_id)
    return HTMLResponse(f"<span class='text-green-600 font-bold'>Rol actualizado a {role}</span>", status_code=200)

@router.post("/rules/add")
async def add_email_rule(
    request: Request,
    modulo: str = Form(...),
    trigger_field: str = Form(...),
    trigger_value: str = Form(...),
    email_to_add: str = Form(...),
    type: str = Form(...),
    conn = Depends(get_db_connection)
):
    """Agrega una nueva regla de correo."""
    await conn.execute(
        """INSERT INTO tb_config_emails 
           (modulo, trigger_field, trigger_value, email_to_add, type) 
           VALUES ($1, $2, $3, $4, $5)""",
        modulo, trigger_field, trigger_value, email_to_add, type
    )
    # Retornamos a la UI para recargar la tabla (simplificado)
    return HTMLResponse(f"""
        <div class='bg-green-100 p-2 rounded'>Regla agregada</div>
        <script>window.location.reload()</script>
    """, status_code=200)

@router.delete("/users/{user_id}")
async def delete_user(
    request: Request,
    user_id: str,
    conn = Depends(get_db_connection)
):
    """Desactiva un usuario (Soft delete)."""
    # Soft Delete: Update is_active to False
    await conn.execute("UPDATE tb_usuarios SET is_active = FALSE WHERE id_usuario = $1", user_id)
    
    # Fetch updated user to render row
    user = await conn.fetchrow("SELECT * FROM tb_usuarios WHERE id_usuario = $1", user_id)
    
    # Return the updated row HTML
    return templates.TemplateResponse("admin/partials/user_row.html", {
        "request": request,
        "u": user
    })

@router.post("/users/{user_id}/restore")
async def restore_user(
    request: Request,
    user_id: str,
    conn = Depends(get_db_connection)
):
    """Reactiva un usuario (Soft delete restore)."""
    # Restore: Update is_active to True
    await conn.execute("UPDATE tb_usuarios SET is_active = TRUE WHERE id_usuario = $1", user_id)
    
    # Fetch updated user to render row
    user = await conn.fetchrow("SELECT * FROM tb_usuarios WHERE id_usuario = $1", user_id)
    
    # Return the updated row HTML
    return templates.TemplateResponse("admin/partials/user_row.html", {
        "request": request,
        "u": user
    })

@router.delete("/rules/{id}")
async def delete_email_rule(
    request: Request,
    id: int,
    conn = Depends(get_db_connection)
):
    """Elimina una regla."""
    return HTMLResponse("", status_code=200) # Empty swap removes element

# --- CONFIG DEFAULT EMAILS (GLOBAL) ---
@router.post("/defaults/update")
async def update_email_defaults(
    request: Request,
    default_to: str = Form(""),
    default_cc: str = Form(""),
    default_cco: str = Form(""),
    conn = Depends(get_db_connection)
):
    """Actualiza configuración global de correos (TO, CC, CCO)."""
    # Validamos que existe row ID 1 (creado por script init_email_defaults.py)
    # Si no existe, lo creamos
    row = await conn.fetchrow("SELECT id FROM tb_email_defaults WHERE id = 1")
    if not row:
         await conn.execute("INSERT INTO tb_email_defaults (id, default_to, default_cc, default_cco) VALUES (1, '', '', '')")

    await conn.execute(
        """UPDATE tb_email_defaults 
           SET default_to = $1, default_cc = $2, default_cco = $3 
           WHERE id = 1""",
        default_to, default_cc, default_cco
    )
    
    return HTMLResponse(f"""
        <div class="bg-green-100 border-l-4 border-green-500 text-green-700 p-2 mb-4 animate-fade-in-down" id="defaults-msg">
            <p class="font-bold">✓ Configuración Actualizada</p>
        </div>
        <script>
            setTimeout(() => document.getElementById('defaults-msg').remove(), 3000);
        </script>
    """, status_code=200)
