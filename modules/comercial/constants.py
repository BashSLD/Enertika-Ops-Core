# modules/comercial/constants.py

"""
Centralized constants for the Commercial Module.
Avoids hardcoded magic numbers and strings.
"""

# Status Keys (Must match 'nombre' or 'codigo_interno' in tb_cat_estatus_global if mapped)
# We map these to IDs dynamically in the Service layer.
STATUS_PENDIENTE = "pendiente"
STATUS_ENTREGADO = "entregado"
STATUS_CANCELADO = "cancelado"
STATUS_PERDIDO = "perdido"
STATUS_GANADA = "ganada"
STATUS_EN_REVISION = "en revisión"
STATUS_EN_PROCESO = "en proceso"

# Fallback IDs (Only used if cache/DB lookup strictly fails to avoid crashes)
# WARNING: These should match the seed data.
DEFAULT_STATUS_ID_PENDIENTE = 1
