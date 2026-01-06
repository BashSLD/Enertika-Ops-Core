# Archivo: main.py

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from modules.comercial import router as comercial_router
from core.database import connect_to_db, close_db_connection
from modules.proyectos import router as proyectos_router

from starlette.middleware.sessions import SessionMiddleware
from core.config import settings
from modules.compras import router as compras_router
from modules.auth import router as auth_router
from modules.admin import router as admin_router

# Inicialización de la app
import logging
from logging.handlers import RotatingFileHandler

# Configurar Logging Global
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(), # Consola
        RotatingFileHandler("system_errors.log", maxBytes=5*1024*1024, backupCount=3) # Archivo 5MB
    ]
)

app = FastAPI(title="Enertika Ops Core",on_startup=[connect_to_db],on_shutdown=[close_db_connection])

# Middleware de Sesión (Cookie Segura)
app.add_middleware(
    SessionMiddleware, 
    secret_key=settings.SECRET_KEY,
    max_age=86400,  # 24 horas en segundos
    same_site="lax",  # Permite cookies en redirects
    # Si DEBUG_MODE es True (Localhost) -> https_only = False (Funciona con HTTP)
    # Si DEBUG_MODE es False (Producción) -> https_only = True (Obliga HTTPS)
    https_only=not settings.DEBUG_MODE
)

# Configuración de Jinja2 Templates (para HTMX/Tailwind)
templates = Jinja2Templates(directory="templates")

# Registrar filtros de timezone (México)
from core.jinja_filters import register_timezone_filters
register_timezone_filters(templates.env)

# Montar directorios estáticos
# app.mount("/static", StaticFiles(directory="static"), name="static")

# Registrar Routers Modulares
# El Backlog Priorizado comienza aquí
app.include_router(auth_router.router)
app.include_router(comercial_router.router)
app.include_router(admin_router.router)

app.include_router(proyectos_router.router)
app.include_router(compras_router.router)
from modules.simulacion import router as simulacion_router
app.include_router(simulacion_router.router)
from modules.levantamientos.router import router as levantamientos_router
app.include_router(levantamientos_router)

# --- Background Tasks ---
import asyncio
from core.tasks import cleanup_temp_uploads_periodically

async def start_background_tasks():
    """Lanza tareas en segundo plano al inicio."""
    asyncio.create_task(cleanup_temp_uploads_periodically())
    
# Actualizamos el on_startup
app.router.on_startup.append(start_background_tasks)

from core.security import get_current_user_context
from fastapi import Depends
from fastapi.responses import RedirectResponse

@app.get("/", tags=["Home"])
async def root(
    request: Request,
    context = Depends(get_current_user_context)
):
    """Endpoint principal: Login si no hay sesión, Redirect a Comercial si hay sesión."""
    user_name = context.get("user_name") # Será None si no hay login
    
    if user_name and user_name != "Usuario":
        # USUARIO LOGUEADO → Redirección Inteligente por Módulos
        role = context.get("role")
        module_roles = context.get("module_roles", {})
        modulo_preferido = context.get("modulo_preferido")
        
        # 1. Admins → Admin UI (siempre tienen acceso total)
        if role == 'ADMIN':
             return RedirectResponse(url="/admin/ui")
        
        # 2. Usuarios sin módulos asignados → Mostrar mensaje
        if not module_roles:
            return templates.TemplateResponse(
                "index.html",
                {
                    "request": request,
                    "app_name": "Enertika Ops Core",
                    "error_message": "No tienes módulos asignados. Contacta al administrador para obtener acceso."
                }
            )
        
        # 3. Función para generar rutas de módulos dinámicamente
        def get_module_route(slug: str) -> str:
            """
            Genera la ruta del módulo basado en su slug.
            
            Patrón estándar: /{slug}/ui
            Valida contra lista de módulos conocidos para evitar rutas inválidas.
            """
            # Lista de módulos válidos (actualizar al agregar nuevos módulos)
            VALID_MODULES = {
                "comercial", "simulacion", "levantamientos", "proyectos",
                "construccion", "compras", "oym", "admin", "ingenieria"
            }
            
            if slug not in VALID_MODULES:
                return None
            
            return f"/{slug}/ui"
        
        # 4. Si tiene módulo preferido y tiene acceso, ir ahí
        if modulo_preferido and modulo_preferido in module_roles:
            ruta = get_module_route(modulo_preferido)
            if ruta:
                return RedirectResponse(url=ruta)
        
        # 5. Ir al primer módulo disponible (en orden alfabético de slug)
        primer_slug = sorted(module_roles.keys())[0]
        ruta = get_module_route(primer_slug)
        if ruta:
            return RedirectResponse(url=ruta)
        
        # 6. Fallback final (no debería llegar aquí)
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "app_name": "Enertika Ops Core",
                "error_message": "Error de configuración. Contacta al administrador."
            }
        )
    
    # NO LOGUEADO -> Mostrar Login
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request, 
            "app_name": "Enertika Ops Core"
        }
    )
    
# Si quisieras levantar el servidor: uvicorn main:app --reload