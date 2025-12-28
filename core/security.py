from fastapi import Request, Depends, HTTPException, status
from core.database import get_db_connection
from core.config import settings
from core.microsoft import get_ms_auth  # Para renovación de tokens
import logging
import time

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

    # 3. Consultar DB para obtener ID interno, ROL, DEPARTAMENTO Y MÓDULO PREFERIDO
    row = await conn.fetchrow(
        "SELECT id_usuario, nombre, rol_sistema, department, modulo_preferido FROM tb_usuarios WHERE email = $1", 
        final_email
    )
    
    
    user_db_id = None
    role = "USER" 
    db_dept = None
    db_name = None
    modulo_preferido = None
    
    if row:
        user_db_id = row['id_usuario']
        role = row['rol_sistema'] or "USER"
        db_dept = row['department']
        db_name = row['nombre']
        modulo_preferido = row['modulo_preferido']
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

    # Trust database for role assignment
    # No hardcoded overrides - all roles managed via tb_usuarios.rol_sistema
    
    # Priority for Department: DB > Session/Hardcoded
    final_department = db_dept if db_dept else department_overan

    # Fix User Name priority: DB Name > Session Name > Email fallback
    if db_name:
        user_name = db_name
    elif user_name == "Usuario" and final_email:
        user_name = final_email.split("@")[0] # Fallback to part of email
    
    # 4. NUEVA LÓGICA: Obtener módulos y roles asignados del usuario
    module_roles = {}
    
    if user_db_id:
        # Consultar módulos asignados desde tb_permisos_modulos
        permisos = await conn.fetch(
            "SELECT modulo_slug, rol_modulo FROM tb_permisos_modulos WHERE usuario_id = $1",
            user_db_id
        )
        
        module_roles = {p['modulo_slug']: p['rol_modulo'] for p in permisos}
        
        # Si no tiene módulos asignados, asignar por defecto según departamento
        if not module_roles and final_department:
            # Obtener slug del departamento
            dept_slug = await conn.fetchval(
                "SELECT slug FROM tb_departamentos_catalogo WHERE nombre = $1",
                final_department
            )
            
            if dept_slug:
                # Obtener módulos por defecto del departamento
                defaults = await conn.fetch(
                    """SELECT modulo_slug, rol_default 
                       FROM tb_departamento_modulos 
                       WHERE departamento_slug = $1""",
                    dept_slug
                )
                
                # Insertar módulos por defecto
                for d in defaults:
                    try:
                        await conn.execute(
                            """INSERT INTO tb_permisos_modulos (usuario_id, modulo_slug, rol_modulo)
                               VALUES ($1, $2, $3)
                               ON CONFLICT (usuario_id, modulo_slug) DO NOTHING""",
                            user_db_id, d['modulo_slug'], d['rol_default']
                        )
                    except Exception as e:
                        logging.warning(f"No se pudo asignar módulo {d['modulo_slug']}: {e}")
                
                # Recargar permisos
                permisos = await conn.fetch(
                    "SELECT modulo_slug, rol_modulo FROM tb_permisos_modulos WHERE usuario_id = $1",
                    user_db_id
                )
                module_roles = {p['modulo_slug']: p['rol_modulo'] for p in permisos}


    return {
        "user_name": user_name,
        "email": final_email,
        "is_admin": (role == 'ADMIN'),
        "role": role,
        "access_token": access_token,
        "department": final_department,
        "modulo_preferido": modulo_preferido,
        "module_roles": module_roles,  # Nueva: Dict {slug: rol}
        "user_db_id": user_db_id
    }

async def get_valid_graph_token(request: Request):
    """
    Versión Híbrida: Lee tokens desde BD para evitar cookies gigantes.
    """
    # 1. Obtener email de la cookie ligera
    user_email = request.session.get("user_email")
    if not user_email:
        return None

    # 2. Conectar a BD para buscar los tokens reales
    # Nota: Instanciamos la conexión manualmente porque esto no es un endpoint
    import asyncpg
    from core.config import settings
    
    try:
        # Conexión rápida solo para verificar token
        conn = await asyncpg.connect(settings.DB_URL_ASYNC)
        
        row = await conn.fetchrow("""
            SELECT access_token, refresh_token, token_expires_at 
            FROM tb_usuarios WHERE email = $1
        """, user_email)
        
        await conn.close()
        
        if not row:
            return None
            
        access_token = row['access_token']
        refresh_token = row['refresh_token']
        expires_at = row['token_expires_at'] or 0
        
        # 3. Lógica de Renovación (Igual que antes)
        now = time.time()
        margin = 300 
        
        if now >= (expires_at - margin):
            if not refresh_token: return None
            
            ms_auth = get_ms_auth()
            new_data = ms_auth.refresh_access_token(refresh_token)
            
            if new_data and "access_token" in new_data:
                # Guardar nuevos tokens en BD
                new_access = new_data["access_token"]
                new_refresh = new_data.get("refresh_token", refresh_token) # A veces no cambia
                new_expires = int(time.time() + new_data.get("expires_in", 3600))
                
                conn = await asyncpg.connect(settings.DB_URL_ASYNC)
                await conn.execute("""
                    UPDATE tb_usuarios 
                    SET access_token = $1, refresh_token = $2, token_expires_at = $3
                    WHERE email = $4
                """, new_access, new_refresh, new_expires, user_email)
                await conn.close()
                
                return new_access
            else:
                return None
                
        return access_token

    except Exception as e:
        print(f"Error en seguridad DB: {e}")
        return None