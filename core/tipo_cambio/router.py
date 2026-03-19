# core/tipo_cambio/router.py
"""
Endpoints para tipo de cambio USD/MXN.
GET  /tipo-cambio/actual     — tasa más reciente (cualquier módulo autenticado)
POST /tipo-cambio/refrescar  — fuerza consulta a Banxico (solo admin)
GET  /tipo-cambio/historial  — últimas 30 tasas (solo admin)
"""
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, HTMLResponse
import asyncpg

from core.database import get_db_connection
from core.security import get_current_user_context
from core.permissions import require_module_access
from core.config import settings
from .service import TipoCambioService

logger = logging.getLogger("TipoCambio.Router")

router = APIRouter(prefix="/tipo-cambio", tags=["Tipo de Cambio"])

_service = TipoCambioService()


@router.get("/actual")
async def get_tasa_actual(
    conn=Depends(get_db_connection),
    _context=Depends(get_current_user_context),
):
    """Retorna la tasa USD/MXN más reciente registrada en BD."""
    tasa = await _service.get_tasa_actual(conn)
    if not tasa:
        return JSONResponse({"tasa_mxn": None, "fecha": None, "mensaje": "Sin datos — usa /refrescar"})
    return {
        "tasa_mxn": float(tasa["tasa_mxn"]),
        "fecha": tasa["fecha"].isoformat(),
        "fuente": tasa["fuente"],
        "dias_antiguedad": tasa["dias_antiguedad"],
    }


@router.post("/refrescar")
async def refrescar_tasa(
    request: Request,
    conn=Depends(get_db_connection),
    _context=Depends(get_current_user_context),
    _=require_module_access("admin"),
):
    """Fuerza actualización de la tasa desde Banxico API. Solo admin.
    Devuelve HTML snippet para HTMX o JSON si no es HTMX."""
    is_htmx = request.headers.get("hx-request")
    try:
        resultado = await _service.refresh_tasa(conn, settings.BANXICO_TOKEN)
        if is_htmx:
            tasa = resultado["tasa_mxn"]
            fecha = resultado["fecha"].strftime("%d/%m/%Y") if hasattr(resultado["fecha"], "strftime") else str(resultado["fecha"])
            return HTMLResponse(
                f'<span class="text-sm text-emerald-700 font-medium">'
                f'Actualizado: ${tasa:.4f} MXN ({fecha})'
                f'</span>'
            )
        return resultado
    except ValueError as exc:
        if is_htmx:
            return HTMLResponse(f'<span class="text-sm text-red-600">{exc}</span>', status_code=502)
        return JSONResponse({"error": str(exc)}, status_code=502)
    except asyncpg.PostgresError:
        logger.exception("Error BD al refrescar tasa")
        if is_htmx:
            return HTMLResponse('<span class="text-sm text-red-600">Error interno al guardar la tasa</span>', status_code=500)
        return JSONResponse({"error": "Error interno al guardar la tasa"}, status_code=500)


@router.get("/historial")
async def get_historial(
    conn=Depends(get_db_connection),
    _context=Depends(get_current_user_context),
    _=require_module_access("admin"),
):
    """Retorna las últimas 30 tasas registradas."""
    registros = await _service.get_historial(conn)
    return [
        {"fecha": r["fecha"].isoformat(), "tasa_mxn": float(r["tasa_mxn"]), "fuente": r["fuente"]}
        for r in registros
    ]
