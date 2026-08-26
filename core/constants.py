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

# Estatus de BOM en los que un paquete deja de mostrarse en el listado
# "pendientes de precio" de Compras (ya no hay items BASE sin costo que
# resolver ahi, o el BOM esta cancelado). Fuente unica para:
# - core/bom/service.py (ESTATUS_FUERA_DE_PRECIOS_PENDIENTES_COMPRAS, que
#   ademas agrega APROBADO_FINAL para bloquear el flujo de items BASE ahi)
# - modules/compras/db_service.py (get_proyectos_bom_pendientes_precio y su
#   _count, como parametro en vez de literal SQL)
# modules/compras no puede importar core/bom/service.py (direccion de capas
# core -> modules), de ahi que el set vaya aqui.
ESTATUS_BOM_OCULTOS_PENDIENTES_PRECIO_COMPRAS = (
    "APROBADO_CONST", "EN_REVISION_FINAL", "CANCELADO",
)
