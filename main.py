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
app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY)

# Configuración de Jinja2 Templates (para HTMX/Tailwind)
# Asumimos que tendremos una carpeta 'templates' y 'static' para CSS/JS
templates = Jinja2Templates(directory="templates")

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
        # 🟢 USUARIO LOGUEADO -> Redirección Directa
        # 🟢 USUARIO LOGUEADO -> Redirección Inteligente por Departamento
        role = context.get("role")
        department = (context.get("department") or "").lower() # Normalize to lowercase
        
        # 1. Admins -> Admin UI
        if role == 'ADMIN':
             return RedirectResponse(url="/admin/ui")
        
        # 2. Department Dispatch
        if any(keyword in department for keyword in ["ventas", "comercial"]):
             return RedirectResponse(url="/comercial/ui")
             
        elif any(keyword in department for keyword in ["simulación", "simulacion"]):
             return RedirectResponse(url="/simulacion/ui")
             
        elif any(keyword in department for keyword in ["ingeniería", "ingenieria", "construccion", "construcción", "levantamientos"]):
             return RedirectResponse(url="/levantamientos/ui")
             
        # 3. Fallback Default
        return RedirectResponse(url="/comercial/ui")
    
    # 🔴 NO LOGUEADO -> Mostrar Login
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request, 
            "app_name": "Enertika Ops Core"
        }
    )
    
# Si quisieras levantar el servidor: uvicorn main:app --reload