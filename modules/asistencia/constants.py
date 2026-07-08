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
    "sin_horario",
}

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
    "descanso": "#d1d5db",
    "feriado": "#e5e7eb",
    "he_compensatorio": "#c7d2fe",
    "sin_horario": "#e9d5ff",
}

ASISTENCIA_ESTADOS_SIN_HUECO_MANUAL = {
    "asistencia",
    "checada_en_vacaciones",
    "checada_en_ausencia",
    "en_curso",
    "vacaciones",
    "ausencia",
    "sin_horario",
    "he_compensatorio",
}

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
