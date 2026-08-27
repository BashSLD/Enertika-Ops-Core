from __future__ import annotations

ASISTENCIA_ESTADOS = {
    "asistencia",
    "vacaciones",
    "ausencia",
    "sin_registro",
    "falta",
    "incompleto",
    "en_curso",
    "descanso",
    "feriado",
    "he_compensatorio",
    "checada_en_vacaciones",
    "checada_en_ausencia",
    "checada_en_compensatorio",
    "sin_horario",
}

# Deliberadamente explicito (no derivado de tb_cat_tipos_ausencia.justifica_asistencia_dia):
# hoy coincide con los slugs de justifica_asistencia_dia=false, pero son conceptos distintos
# (justifica el dia vs. modalidad informativa con checada). Acoplarlos haria que un tipo de
# ausencia nuevo con justifica_asistencia_dia=false muestre este chip sin decision explicita.
# Al agregar un tipo de ausencia al catalogo, evaluar si debe sumarse aqui tambien.
ASISTENCIA_MODALIDAD_METADATA_SLUGS = frozenset({
    "home_office",
    "permiso_llegar_tarde",
    "permiso_salir_temprano",
})

# Subconjunto curado a mano de ASISTENCIA_ESTADOS: los unicos estados que produce
# calcular_resumen_dia() (logic.py) con checada real en un dia laborable, sin que medie
# vacaciones/ausencia/feriado/descanso/sin_horario. Si logic.py gana un estado nuevo con
# checada real, evaluar si debe sumarse aqui tambien.
ASISTENCIA_ESTADOS_CON_MODALIDAD_METADATA = frozenset({
    "asistencia",
    "incompleto",
    "en_curso",
})

ASISTENCIA_ESTADO_LABELS = {
    "asistencia": "Asistencia",
    "vacaciones": "Vacaciones",
    "ausencia": "Ausencia aprobada",
    "sin_registro": "Sin registro",
    "falta": "Falta",
    "incompleto": "Incompleto",
    "en_curso": "Entrada registrada",
    "descanso": "Descanso",
    "feriado": "Feriado",
    "he_compensatorio": "Horas extra tomadas",
    "checada_en_vacaciones": "Checada en vacaciones",
    "checada_en_ausencia": "Checada en ausencia",
    "checada_en_compensatorio": "Checada en compensatorio",
    "sin_horario": "Sin horario",
}

ASISTENCIA_ESTADO_COLORES: dict[str, str] = {
    "asistencia": "#4ade80",
    "en_curso": "#38bdf8",
    "falta": "#f87171",
    "sin_registro": "#fca5a5",
    "incompleto": "#fdba74",
    "vacaciones": "#00BABB",
    "checada_en_vacaciones": "#5eead4",
    "ausencia": "#7dd3fc",
    "checada_en_ausencia": "#bae6fd",
    "checada_en_compensatorio": "#a5b4fc",
    "descanso": "#d1d5db",
    "feriado": "#e5e7eb",
    "he_compensatorio": "#c7d2fe",
    "sin_horario": "#e9d5ff",
}

ASISTENCIA_ESTADOS_SIN_HUECO_MANUAL = {
    "asistencia",
    "checada_en_vacaciones",
    "checada_en_ausencia",
    "checada_en_compensatorio",
    "en_curso",
    "vacaciones",
    "ausencia",
    "sin_horario",
    "he_compensatorio",
}

def formatear_estado_asistencia_label(estado: str | None, tipo_ausencia_nombre: str | None = None) -> str:
    """Unico formateador de label de estado para Mi Perfil, RRHH y XLSX: en `estado='ausencia'`
    usa el tipo real de la solicitud (o 'Ausencia' sin tipo); el resto de estados conserva su
    label fijo. Reemplaza el chip secundario de tipo -- no debe volver a agregarse en paralelo."""
    if not estado:
        return ""
    if estado == "ausencia":
        return tipo_ausencia_nombre or "Ausencia"
    return ASISTENCIA_ESTADO_LABELS.get(estado, estado.replace("_", " "))


HE_MINIMO_OPCIONES = (10, 15, 30, 60)

# trigger_value en tb_config_emails (Admin > Reglas de correo) para el CC/CCO
# informativo cuando la cadena de jefes de una solicitud de horas extra/compensatorio
# incluye a alguien con rol_organizacional='director'. Compartido por HE y compensatorio
# porque ambos usan el mismo resolver_destinatarios_he_puro.
HE_EVENTO_ESCALACION_DIRECTOR = "HORAS_EXTRA_ESCALACION_DIRECTOR"

BIOTIME_CONFIG_KEYS = {
    "sync_activo": "BIOTIME_SYNC_ACTIVO",
    "base_url": "BIOTIME_BASE_URL",
    "username": "BIOTIME_USERNAME",
    "password": "BIOTIME_PASSWORD",
    "interval_seconds": "BIOTIME_SYNC_INTERVAL_SEG",
    "page_size": "BIOTIME_SYNC_PAGE_SIZE",
    "lookback_hours": "BIOTIME_SYNC_LOOKBACK_HRS",
    "timeout_seconds": "BIOTIME_SYNC_TIMEOUT_SEG",
    "recalc_days": "ASISTENCIA_RECALC_DIAS",
}
