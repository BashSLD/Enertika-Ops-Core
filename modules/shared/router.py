# modules/shared/router.py
"""
Endpoints compartidos entre módulos (sin prefijo de módulo específico).
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.templating import Jinja2Templates

from core.database import get_db_connection
from core.security import get_current_user_context
from core.tipo_cambio.service import TipoCambioService

logger = logging.getLogger("SharedRouter")

templates = Jinja2Templates(directory="templates")

router = APIRouter(
    prefix="/shared",
    tags=["Shared"],
)


@router.get("/partials/calculadora-ventas", include_in_schema=False)
async def get_calculadora_ventas(
    request: Request,
    modulo: Optional[str] = Query(default=None),
    conn=Depends(get_db_connection),
    context=Depends(get_current_user_context),
):
    """Modal calculadora de ventas con estimacion de sistema FV y tipo de cambio.
    Accesible desde cualquier módulo autenticado. Acepta ?modulo=xxx para evaluar
    el rol de módulo al determinar si se muestran las constantes editables.
    """
    tc_service = TipoCambioService()
    tc_data = await tc_service.get_tasa_actual(conn)
    tc_valor = float(tc_data["tasa_mxn"]) if tc_data else 20.0
    tc_efectivo = max(tc_valor, 20.0)

    role = context.get("role", "USER")
    module_roles = context.get("module_roles", {})
    module_role = module_roles.get(modulo, "viewer") if modulo else "viewer"

    can_edit = (role == "ADMIN") or (module_role in ["editor", "admin"])
    is_admin_or_manager = (role == "ADMIN") or (role == "MANAGER")
    can_edit_constants = is_admin_or_manager and can_edit

    return templates.TemplateResponse(
        request, "shared/modals/calculadora_ventas.html",
        {            "tc_valor": round(tc_valor, 4),
            "tc_efectivo": round(tc_efectivo, 4),
            "can_edit_constants": can_edit_constants,
        },
    )
