# modules/cfe/constants.py

CFE_CONFIG_KEYS = {
    "mi_user":          "CFE_MIESPACIO_USER",
    "mi_pass":          "CFE_MIESPACIO_PASS",
    "session_json":     "CFE_MIESPACIO_SESSION_JSON",
    "upload_token":     "CFE_SESSION_UPLOAD_TOKEN",
    "session_invalida": "CFE_MIESPACIO_SESSION_INVALIDA",
    "lanzador_item_id": "CFE_LANZADOR_ITEM_ID",
    "lanzador_version": "CFE_LANZADOR_VERSION",
}

CFE_PUBLIC_FORM_DEFAULTS = {
    "lada": "55",
    "telefono": "12345678",
    "email": "correo@dominio.com",
}

# SharePoint: Recibos CFE/{numero_servicio}/{periodo}/
SHAREPOINT_CFE_ROOT = "Recibos CFE"
SHAREPOINT_CFE_STAGING_ROOT = f"{SHAREPOINT_CFE_ROOT}/_staging"
SHAREPOINT_CFE_TOOLS_FOLDER = "herramientas"

# Módulos con acceso a esta funcionalidad
CFE_MODULE_SLUGS = ["oym", "simulacion"]
