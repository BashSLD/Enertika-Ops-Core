# ==============================================================
# modules/levantamientos/router_levantamientos_nuevos.py
#
# Orquestador — registra los tres sub-routers en el APIRouter
# principal del módulo (modules/levantamientos/router.py).
#
# CÓMO INTEGRAR (ya hecho en router.py):
#
#     from .router_levantamientos_nuevos import register_nuevos_endpoints
#     register_nuevos_endpoints(router)
#
# Sub-routers:
#   - router_modales.py      → 6 GETs de modales
#   - router_operaciones.py  → POSTs de operaciones + helper _render_kanban
#   - router_vistas.py       → partials/lista + partials/graficas
# ==============================================================

from fastapi import APIRouter

from .router_modales import register_modal_endpoints
from .router_operaciones import register_operaciones_endpoints
from .router_vistas import register_vistas_endpoints


def register_nuevos_endpoints(router: APIRouter):
    """
    Registra todos los endpoints nuevos en el router existente.
    Llamar una sola vez desde router.py.
    """
    register_modal_endpoints(router)
    register_operaciones_endpoints(router)
    register_vistas_endpoints(router)
