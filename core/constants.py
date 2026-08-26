"""
Constantes compartidas entre core/ y modules/ que no encajan en un submodulo
especifico. Vive en core/ (nunca en core/projects/ u otro paquete con
__init__.py pesado) para que importarla no arrastre routers/services enteros.
"""

# Mapeo area -> rol operativo de proyecto. Fuente unica para:
# - core/transfers/db_service.py (arma un CASE SQL)
# - modules/proyectos/service.py (ROLES_EQUIPO)
# core/transfers/db_service.py no puede importar modules/proyectos/service.py
# (direccion de capas core -> modules), de ahi que el mapeo viva aqui.
ROL_OPERATIVO_POR_AREA = {
    "INGENIERIA": "ingeniero_asignado",
    "CONSTRUCCION": "coordinador_obra",
    "OYM": "encargado",
    "COMPRAS": "comprador_asignado",
}
