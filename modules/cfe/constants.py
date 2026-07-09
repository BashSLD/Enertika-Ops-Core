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

# Umbral de duracion de una busqueda de periodos: minimo 300s, +90s por cada
# periodo solicitado. Lo usan tanto el asyncio.wait_for() en procesar_pendientes
# como el reaper SQL que rescata busquedas colgadas — deben coincidir.
CFE_BUSQUEDA_TIMEOUT_MIN_SEGUNDOS = 300
CFE_BUSQUEDA_TIMEOUT_SEGUNDOS_POR_PERIODO = 90

# Marcador interno guardado en miespacio_error mientras un servicio esta en
# 'pendiente'/'registrando' por auto-recuperacion (CFE dejo de reconocerlo).
# Nunca se muestra al usuario (ese estatus no expone miespacio_error en la UI);
# permite distinguir en get_all_servicios una recuperacion real de una primera
# alta normal, sin depender de miespacio_verificado_en (que el reaper tambien
# sella en cada intento, exitoso o no).
CFE_MARCADOR_RECUPERANDO_MIESPACIO = "__cfe_recuperando_registro_miespacio__"
