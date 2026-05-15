from __future__ import annotations

ASISTENCIA_ESTADOS = {
    "asistencia",
    "vacaciones",
    "sin_registro",
    "falta",
    "incompleto",
    "en_curso",
    "descanso",
    "feriado",
    "checada_en_vacaciones",
    "sin_horario",
}

ASISTENCIA_ESTADO_LABELS = {
    "asistencia": "Asistencia",
    "vacaciones": "Vacaciones",
    "sin_registro": "Sin registro",
    "falta": "Falta",
    "incompleto": "Incompleto",
    "en_curso": "Entrada registrada",
    "descanso": "Descanso",
    "feriado": "Feriado",
    "checada_en_vacaciones": "Checada en vacaciones",
    "sin_horario": "Sin horario",
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
