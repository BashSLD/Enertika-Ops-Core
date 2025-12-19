from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import RedirectResponse
from core.microsoft import get_ms_auth, MicrosoftAuth
from core.config import settings

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
async def callback(request: Request, code: str, ms_auth: MicrosoftAuth = Depends(get_ms_auth)):
    """Callback tras el login en Microsoft. Obtiene token y lo guarda en sesión."""
    try:
        # 1. Canjear código por token
        token_result = ms_auth.get_token_from_code(code)
        
        if "error" in token_result:
            return f"Error en login: {token_result.get('error_description')}"
            
        # 2. Guardar en SESIÓN (Cookie segura)
        # request.session requiere SessionMiddleware configurado en main.py
        request.session["access_token"] = token_result["access_token"]
        
        # 3. Extraer información del Usuario (ID Token)
        # MSAL procesa automáticamente el id_token si se piden scopes openid/profile
        claims = token_result.get("id_token_claims", {})
        
        # Prioridad: preferred_username > email > upn
        user_email = claims.get("preferred_username") or claims.get("email") or claims.get("upn")
        
        if user_email:
            # Normalizamos a minúsculas para consistencia en BD
            request.session["user_email"] = user_email.lower()
            request.session["user_name"] = claims.get("name", "Usuario Desconocido")
        else:
            # Fallback si no hay claims (raro si scope está bien)
            request.session["user_email"] = "unknown@domain.com"
        
        # 4. Redirigir al Dashboard Comercial
        return RedirectResponse(url="/comercial/ui")
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"Excepción interna: {str(e)}"

@router.get("/logout")
async def logout(request: Request):
    """Cierra la sesión del usuario."""
    request.session.clear()
    return RedirectResponse(url="/")
