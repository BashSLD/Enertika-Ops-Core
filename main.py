# Archivo: main.py

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from modules.comercial import router as comercial_router
from core.database import connect_to_db, close_db_connection
from modules.proyectos import router as proyectos_router
from modules.levantamientos import router as levantamientos_router
from modules.compras import router as compras_router

# Inicialización de la app

app = FastAPI(title="Enertika Ops Core",on_startup=[connect_to_db],on_shutdown=[close_db_connection])

# Configuración de Jinja2 Templates (para HTMX/Tailwind)
# Asumimos que tendremos una carpeta 'templates' y 'static' para CSS/JS
templates = Jinja2Templates(directory="templates")

# Montar directorios estáticos
# app.mount("/static", StaticFiles(directory="static"), name="static")

# Registrar Routers Modulares
# El Backlog Priorizado comienza aquí
app.include_router(comercial_router.router)
app.include_router(levantamientos_router.router)
app.include_router(proyectos_router.router)
app.include_router(compras_router.router)

@app.get("/", tags=["Home"])
async def root(request: Request):
    """Endpoint principal que renderizará la vista HTMX/Dashboard inicial."""
    # Ejemplo de renderizado con Jinja2 (para la UI/UX)
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "app_name": "Enertika Ops Core Dashboard"}
    )
    
# Si quisieras levantar el servidor: uvicorn main:app --reload