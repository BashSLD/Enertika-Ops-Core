# Archivo: main.py

import asyncio
import contextlib
import logging
from logging.handlers import RotatingFileHandler

import sentry_sdk
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from starlette.middleware.sessions import SessionMiddleware

from core.config import settings
from core.database import connect_to_db, close_db_connection, get_db_connection
from modules.admin import router as admin_router
from modules.auth import router as auth_router
from modules.comercial import router as comercial_router
from modules.compras import router as compras_router
from modules.proyectos import router as proyectos_router
from modules.proveedores import router as proveedores_router

# Configurar Logging Global
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(), # Consola
        RotatingFileHandler("system_errors.log", maxBytes=5*1024*1024, backupCount=3) # Archivo 5MB
    ]
)
logger = logging.getLogger("Main")

def _sentry_before_send(event, hint):
    if "ASGI callable returned without completing response" in event.get("message", ""):
        return None
    return event

if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        before_send=_sentry_before_send,
        integrations=[FastApiIntegration(), StarletteIntegration()],
        traces_sample_rate=0.05,
        send_default_pii=False,
        enable_logs=True,
        environment="production" if not settings.DEBUG_MODE else "development",
    )

app = FastAPI(title="Enertika Core Ops",on_startup=[connect_to_db],on_shutdown=[close_db_connection])

# Middleware de Sesión (Cookie Segura)
app.add_middleware(
    SessionMiddleware, 
    secret_key=settings.SECRET_KEY,
    max_age=settings.SESSION_MAX_AGE,
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
from modules.docs import router as docs_router
app.include_router(docs_router.router)

app.include_router(proyectos_router.router)
app.include_router(compras_router.router)
app.include_router(proveedores_router.router)
from modules.compras.sat_router import router as sat_router
app.include_router(sat_router)
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

from modules.cfe.router import router as cfe_router
app.include_router(cfe_router)

from modules.calculadora_polizas import router as calculadora_polizas_router
app.include_router(calculadora_polizas_router.router)
app.include_router(calculadora_polizas_router.oym_router)

from modules.finanzas import router as finanzas_router
app.include_router(finanzas_router.router)

# Traspasos de Proyectos (compartido entre modulos)
from core.transfers.router import router as transfers_router
app.include_router(transfers_router)

# Shared — partials compartidos entre módulos (calculadora, etc.)
from modules.shared.router import router as shared_router
app.include_router(shared_router)

# Materiales compartido (subfuncion de Compras)
from core.materials.router import router as materials_router
app.include_router(materials_router)

# BOM - Lista de Materiales (compartido entre modulos)
from core.bom.router import router as bom_router
app.include_router(bom_router)

# PDF Service (reportes compartidos entre modulos)
from core.pdf_service.router import router as pdf_router
app.include_router(pdf_router)

# Integraciones externas (SharePoint folder browser, etc.)
from core.integrations.router import router as integraciones_router
app.include_router(integraciones_router)

# Tipo de Cambio USD/MXN (Banxico)
from core.tipo_cambio.router import router as tipo_cambio_router
app.include_router(tipo_cambio_router)

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
    existing_task = getattr(app.state, "sse_monitor_task", None)
    if existing_task and not existing_task.done():
        return
    app.state.sse_monitor_task = asyncio.create_task(monitor_connection_task())


async def stop_sse_monitor():
    task = getattr(app.state, "sse_monitor_task", None)
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        app.state.sse_monitor_task = None
    await shutdown_notifications()


app.router.on_startup.append(start_sse_monitor)

app.router.on_shutdown.insert(0, stop_sse_monitor)

app.include_router(notifications_router.router)

# Agregar después de los otros routers
from core.projects import router as projects_router
app.include_router(projects_router)

from modules.perfil.router import router as perfil_router
app.include_router(perfil_router)

from modules.vacaciones.router import router as vacaciones_router
app.include_router(vacaciones_router)

from modules.rrhh.router import router as rrhh_router
app.include_router(rrhh_router)

from modules.asistencia.router import router as asistencia_router
app.include_router(asistencia_router)

# --- Background Tasks ---
# Las tareas periódicas (CEO report, tipo cambio, recordatorios, limpieza, etc.)
# corren en el Worker service independiente de Railway (worker.py).
# Aquí solo iniciamos el monitor de SSE que necesita el proceso web.

from core.security import get_current_user_context
from core.navigation.service import NavigationService, get_navigation_service
from fastapi import Depends
from fastapi.responses import RedirectResponse, JSONResponse, FileResponse

# Health check endpoint - simple, no dependencies
@app.get("/health", tags=["Health"])
async def health_check():
    """Endpoint de diagnóstico - no usa templates ni auth."""
    return JSONResponse({"status": "ok", "message": "Enertika Core Ops is running"})

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return RedirectResponse(url="/static/favicon.svg")


@app.get("/manifest.webmanifest", include_in_schema=False)
async def pwa_manifest():
    return FileResponse(
        "static/manifest.webmanifest",
        media_type="application/manifest+json",
        headers={"Cache-Control": "public, max-age=86400"}
    )


@app.get("/sw.js", include_in_schema=False)
async def service_worker():
    return FileResponse(
        "static/sw.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache"}
    )


@app.get("/offline", include_in_schema=False)
async def offline_page():
    return FileResponse(
        "static/offline.html",
        media_type="text/html",
        headers={"Cache-Control": "public, max-age=3600"}
    )

@app.get("/", tags=["Home"])
async def root(
    request: Request,
    context = Depends(get_current_user_context),
    conn = Depends(get_db_connection),
    navigation_service: NavigationService = Depends(get_navigation_service),
):
    """Endpoint principal: login si no hay sesion; redireccion por catalogo si hay sesion."""
    user_name = context.get("user_name") # Será None si no hay login
    
    if user_name and user_name != "Usuario":
        # USUARIO LOGUEADO → Redirección Inteligente por Módulos
        role = context.get("role")
        module_roles = context.get("module_roles", {})
        modulo_preferido = context.get("modulo_preferido")

        # 1. Admins → Admin UI (siempre tienen acceso total)
        if role == 'ADMIN':
            admin_route = await navigation_service.get_module_route(conn, "admin")
            if admin_route:
                return RedirectResponse(url=admin_route)

            logger.error("Ruta de modulo admin no configurada en tb_cat_modulos")
            return templates.TemplateResponse(
                request, "index.html",
                {
                    "app_name": "Enertika Core Ops",
                    "error_message": "Error de configuracion. Contacta al administrador."
                }
            )

        # 2. Sin módulo preferido o sin módulos asignados → Mi Perfil
        if not modulo_preferido or not module_roles:
            return RedirectResponse(url="/perfil/ui")
        
        # 3. Si tiene modulo preferido y tiene acceso, ir ahi
        if modulo_preferido and modulo_preferido in module_roles:
            ruta = await navigation_service.get_module_route(conn, modulo_preferido)
            if ruta:
                return RedirectResponse(url=ruta)
        
        # 4. Ir al primer modulo disponible con ruta configurada en catalogo
        ruta = await navigation_service.get_first_accessible_module_route(
            conn,
            module_roles.keys(),
        )
        if ruta:
            return RedirectResponse(url=ruta)
        
        # 5. Fallback final (no deberia llegar aqui)
        return templates.TemplateResponse(
            request, "index.html",
            {
                "app_name": "Enertika Core Ops",
                "error_message": "Error de configuracion. Contacta al administrador."
            }
        )
    
    # NO LOGUEADO -> Mostrar Login
    return templates.TemplateResponse(
        request, "index.html",
        {
            "app_name": "Enertika Core Ops"
        }
    )
    
# Si quisieras levantar el servidor: uvicorn main:app --reload
