from fastapi import APIRouter, Request, Depends
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse
import random
import asyncio

templates = Jinja2Templates(directory="templates")

router = APIRouter(
    prefix="/simulacion",
    tags=["Módulo Simulación"],
)

# --- ENDPOINTS UI ---

from core.security import get_current_user_context

@router.get("/ui", include_in_schema=False)
async def get_simulacion_ui(
    request: Request,
    context = Depends(get_current_user_context)
):
    """Main Entry: Shows the Tabbed Simulation Module."""
    return templates.TemplateResponse("simulacion/tabs.html", {
        "request": request,
        "user_name": context.get("user_name"),
        "role": context.get("role")
    })

@router.get("/partials/live", include_in_schema=False)
async def get_live_graphs_partial(request: Request):
    """Partial: Real-time Graphs Tab."""
    return templates.TemplateResponse("simulacion/partials/live_graphs.html", {"request": request})

@router.get("/partials/table", include_in_schema=False)
async def get_editable_table_partial(request: Request):
    """Partial: Editable Simulation Table."""
    # Dummy data for now
    simulaciones = [
        {"id": 1, "proyecto": "Proyecto Alpha", "potencia": 120, "ahorro": 15000, "status": "Borrador"},
        {"id": 2, "proyecto": "Sucursal Centro", "potencia": 45, "ahorro": 5400, "status": "Finalizado"},
        {"id": 3, "proyecto": "Planta Industrial", "potencia": 500, "ahorro": 89000, "status": "En Proceso"},
    ]
    return templates.TemplateResponse("simulacion/partials/editable_table.html", {"request": request, "simulaciones": simulaciones})

@router.get("/data/live")
async def get_live_data():
    """Returns random data for live charts."""
    # Simulating real-time data
    return JSONResponse({
        "timestamp": asyncio.get_event_loop().time(),
        "power": random.randint(80, 120),
        "frequency": 60 + random.uniform(-0.1, 0.1),
        "voltage": 127 + random.uniform(-2, 2)
    })