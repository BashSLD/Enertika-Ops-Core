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

app = FastAPI(title="Enertika Core Ops",on_startup=[connect_to_db],on_shutdown=[close_db_connection])

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

# Variables Globales para Templates
templates.env.globals["DEBUG_MODE"] = settings.DEBUG_MODE

# Montar directorios estáticos
app.mount("/static", StaticFiles(directory="static"), name="static")

# Registrar Routers Modulares
# El Backlog Priorizado comienza aquí
app.include_router(auth_router.router)
app.include_router(comercial_router.router)
app.include_router(admin_router.router)

app.include_router(proyectos_router.router)
app.include_router(compras_router.router)
from modules.simulacion import router as simulacion_router
app.include_router(simulacion_router.router)
from modules.simulacion.report_router import router as report_router
app.include_router(report_router)
from modules.levantamientos.router import router as levantamientos_router
app.include_router(levantamientos_router)

# --- NUEVOS MÓDULOS REGISTRADOS ---
from modules.construccion import router as construccion_router
app.include_router(construccion_router.router)

from modules.ingenieria import router as ingenieria_router
app.include_router(ingenieria_router.router)

from modules.oym import router as oym_router
app.include_router(oym_router.router)

# Traspasos de Proyectos (compartido entre modulos)
from core.transfers.router import router as transfers_router
app.include_router(transfers_router)

# Materiales compartido (subfuncion de Compras)
from core.materials.router import router as materials_router
app.include_router(materials_router)

# BOM - Lista de Materiales (compartido entre modulos)
from core.bom.router import router as bom_router
app.include_router(bom_router)

# Workflow: Comentarios centralizados
from core.workflow.router import router as workflow_router
app.include_router(workflow_router)

# Notificaciones en Tiempo Real (SSE)
from core.notifications import router as notifications_router
from core.notifications.service import startup_notifications, shutdown_notifications, monitor_connection_task

# Agregar lifecycle hooks para el multiplexer de notificaciones
# Se ejecutan al iniciar y cerrar la app
app.router.on_startup.append(startup_notifications)
# Registrar monitor en background (wrapper para que sea async)
async def start_sse_monitor():
    asyncio.create_task(monitor_connection_task())
app.router.on_startup.append(start_sse_monitor)

app.router.on_shutdown.append(shutdown_notifications)

app.include_router(notifications_router.router)

# Agregar después de los otros routers
from core.projects import router as projects_router
app.include_router(projects_router)

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
from fastapi.responses import RedirectResponse, JSONResponse

# Health check endpoint - simple, no dependencies
@app.get("/health", tags=["Health"])
async def health_check():
    """Endpoint de diagnóstico - no usa templates ni auth."""
    return JSONResponse({"status": "ok", "message": "Enertika Core Ops is running"})

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return RedirectResponse(url="/static/favicon.svg")

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
                    "app_name": "Enertika Core Ops",
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
                "app_name": "Enertika Core Ops",
                "error_message": "Error de configuración. Contacta al administrador."
            }
        )
    
    # NO LOGUEADO -> Mostrar Login
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request, 
            "app_name": "Enertika Core Ops"
        }
    )
    
# Si quisieras levantar el servidor: uvicorn main:app --reload