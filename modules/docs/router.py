"""
Router del Módulo de Documentación / Ayuda
"""
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

# Imports obligatorios para contexto
from core.security import get_current_user_context
from core.config import settings

router = APIRouter(
    prefix="/docs",
    tags=["Documentación"],
)

templates = Jinja2Templates(directory="templates")
templates.env.globals["DEBUG_MODE"] = settings.DEBUG_MODE

@router.get("/content/{module_name}", response_class=HTMLResponse)
async def get_docs_content(
    request: Request,
    module_name: str,
    context = Depends(get_current_user_context)
):
    """
    Retorna el contenido de documentación específico para un módulo.
    Si no existe documentación específica, retorna la genérica.
    """
    
    # Mapa de plantillas específicas disponibles
    # Si agregas una nueva guía, regístrala aquí
    available_docs = {
        "comercial": "docs/comercial.html",
        "simulacion": "docs/simulacion.html",
        "levantamientos": "docs/levantamientos.html",
        "compras": "docs/compras.html",
        "proyectos": "docs/proyectos.html",
        "oym": "docs/oym.html",
        # "ingenieria": "docs/ingenieria.html", # Futuro
    }
    
    # Determinar qué template usar
    template_name = available_docs.get(module_name, "docs/generic.html")
    
    # Datos de contexto para la plantilla (roles, usuario, etc)
    return templates.TemplateResponse(request, template_name, {        "module_name": module_name,
        "user_name": context.get("user_name"),
        "role": context.get("role"),
        "module_roles": context.get("module_roles", {})
    })

@router.get("/modal/layout", response_class=HTMLResponse)
async def get_docs_layout(request: Request):
    """
    Retorna el layout base del modal (vacío).
    El frontend luego llamará a /content/{module} para llenarlo.
    """
    return templates.TemplateResponse(request, "docs/layout.html", {})
