from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import RedirectResponse
from core.microsoft import get_ms_auth, MicrosoftAuth
from core.config import settings
from core.database import get_db_connection
import time

router = APIRouter(
    prefix="/auth",
    tags=["Autenticación"]
)

@router.get("/login")
async def login(ms_auth: MicrosoftAuth = Depends(get_ms_auth)):
    """Inicia el flujo de autenticación con Microsoft."""
    auth_url = ms_auth.get_auth_url()
    return RedirectResponse(auth_url)

@router.get("/callback")
async def callback(
    request: Request, 
    code: str, 
    ms_auth: MicrosoftAuth = Depends(get_ms_auth),
    conn = Depends(get_db_connection)
):
    """Callback tras el login en Microsoft. Guarda tokens en BD y sesión ligera."""
    try:
        # 1. Canjear código por token
        token_result = await ms_auth.get_token_from_code(code)
        
        if "error" in token_result:
            return f"Error en login: {token_result.get('error_description')}"
            
        # 2. Extraer datos
        access_token = token_result.get("access_token")
        refresh_token = token_result.get("refresh_token")
        expires_in = token_result.get("expires_in", 3600)
        expires_at = int(time.time() + expires_in)
        
        claims = token_result.get("id_token_claims", {})
        user_email = claims.get("preferred_username") or claims.get("email") or claims.get("upn")
        
        if not user_email:
            return "Error: No se pudo obtener el email del usuario."
            
        user_email = user_email.lower()
        
        # 3. GUARDAR EN BASE DE DATOS (UPSERT: Insertar o Actualizar)
        # Esto maneja tanto usuarios nuevos como recurrentes en una sola consulta atómica
        await conn.execute("""
            INSERT INTO tb_usuarios (nombre, email, access_token, refresh_token, token_expires_at, rol_sistema, ultimo_login, is_active) 
            VALUES ($1, $2, $3, $4, $5, 'USER', NOW(), TRUE)
            ON CONFLICT (email) DO UPDATE 
            SET access_token = EXCLUDED.access_token,
                refresh_token = EXCLUDED.refresh_token,
                token_expires_at = EXCLUDED.token_expires_at,
                ultimo_login = NOW(),
                nombre = COALESCE(tb_usuarios.nombre, EXCLUDED.nombre)
        """, claims.get("name", "Usuario"), user_email, access_token, refresh_token, expires_at)
        
        # 4. GUARDAR EN SESIÓN (Solo lo ligero)
        # Limpiamos la sesión vieja para evitar basura
        request.session.clear()
        request.session["user_email"] = user_email
        request.session["user_name"] = claims.get("name", "Usuario")
        
        # Esto pesa muy poco, el navegador lo aceptará felizmente
        return RedirectResponse(url="/")
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"Excepción interna: {str(e)}"

@router.get("/logout")
async def logout(request: Request):
    """
    Cierra sesión local y remota (Microsoft).
    """
    # 1. Limpiar sesión de FastAPI (Mata cookies locales)
    request.session.clear()
    
    # --- PUNTO B: Lógica de Microsoft Logout ---
    
    # Detectar la URL base actual (ej. http://localhost:8000 o https://tu-dominio.com)
    # .rstrip("/") quita la barra final si existe para evitar dobles barras
    base_url = str(request.base_url).rstrip("/")
    
    # Definimos a dónde queremos que Microsoft nos regrese después de salir
    post_logout_redirect_uri = f"{base_url}/auth/login"
    # O si prefieres la raíz: f"{base_url}/"
    
    # Construimos la URL oficial de logout de Microsoft
    # "common" sirve para multi-tenant. Si usas un tenant específico, cámbialo aquí.
    ms_logout_url = (
        f"https://login.microsoftonline.com/common/oauth2/v2.0/logout"
        f"?post_logout_redirect_uri={post_logout_redirect_uri}"
    )
    
    # Redirigimos al usuario a esa URL externa
    return RedirectResponse(url=ms_logout_url)

