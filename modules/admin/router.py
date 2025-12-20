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
    
    return templates.TemplateResponse("admin/dashboard.html", {
        "request": request,
        "users": users,
        "rules": rules,
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
    """Elimina un usuario (Soft delete o Hard delete según política)."""
    # Hard Delete por ahora simple
    await conn.execute("DELETE FROM tb_usuarios WHERE id_usuario = $1", user_id)
    return HTMLResponse("", status_code=200)

@router.delete("/rules/{id}")
async def delete_email_rule(
    request: Request,
    id: int,
    conn = Depends(get_db_connection)
):
    """Elimina una regla."""
    await conn.execute("DELETE FROM tb_config_emails WHERE id = $1", id)
    return HTMLResponse("", status_code=200) # Empty swap removes element
