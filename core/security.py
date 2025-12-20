from fastapi import Request, Depends, HTTPException, status
from core.database import get_db_connection
from core.config import settings
import logging

# Reutilizamos la lógica que estaba en comercial/router.py
async def get_current_user_context(
    request: Request, 
    conn = Depends(get_db_connection)
):
    """
    Dependency to get the current logged-in user context.
    Returns a dict with user_name, email, access_token, department, role, etc.
    """
    # 1. Recuperar sesión (cookie)
    access_token = request.session.get("access_token")
    user_email = request.session.get("user_email")
    user_name = request.session.get("user_name", "Usuario")
    
    # Debug/Dev Override
    department_overan = "Ventas" # Default
    if settings.DEBUG_MODE:
        # Mock department logic based on email if needed for testing
        pass
        
    final_email = user_email
    
    # Admin Override (Legacy)
    if user_email == "sistemas@enertika.mx":
        department_overan = "Sistemas"

    # 2. Si no hay email en sesión (no logueado), retornamos contexto mínimo
    # para que la UI decida si muestra Login o no.
    if not final_email:
        return {
            "user_name": None,
            "email": None,
            "is_admin": False,
            "role": None,
            "access_token": None,
            "department": None,
            "user_db_id": None
        }

    # 3. Consultar DB para obtener ID interno, ROL y DEPARTAMENTO REAL
    row = await conn.fetchrow("SELECT id_usuario, nombre, rol_sistema, department FROM tb_usuarios WHERE email = $1", final_email)
    
    user_db_id = None
    role = "USER" 
    db_dept = None
    db_name = None
    
    if row:
        user_db_id = row['id_usuario']
        role = row['rol_sistema'] or "USER"
        db_dept = row['department']
        db_name = row['nombre']
    else:
        # Auto-create user on the fly if not exists (First Login)
        try:
             # Default role USER
             user_db_id = await conn.fetchval(
                 "INSERT INTO tb_usuarios (nombre, email, rol_sistema) VALUES ($1, $2, 'USER') RETURNING id_usuario",
                 user_name, final_email
             )
        except Exception as e:
            logging.error(f"Error auto-creating user: {e}")

    # Admin Override (Force ADMIN role for specific email if needed, or trust DB)
    if user_email == "sistemas@enertika.mx":
        department_overan = "Sistemas" # Legacy fallback
        if role != 'ADMIN':
             role = 'ADMIN' # Force Admin for superuser legacy
    
    # Priority for Department: DB > Session/Hardcoded
    final_department = db_dept if db_dept else department_overan

    # Fix User Name priority: DB Name > Session Name > Email fallback
    if db_name:
        user_name = db_name
    elif user_name == "Usuario" and final_email:
        user_name = final_email.split("@")[0] # Fallback to part of email

    return {
        "user_name": user_name,
        "email": final_email,
        "is_admin": (role == 'ADMIN'),
        "role": role,
        "access_token": access_token,
        "department": final_department,
        "user_db_id": user_db_id
    }
