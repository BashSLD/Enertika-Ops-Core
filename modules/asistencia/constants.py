from __future__ import annotations

ASISTENCIA_ESTADOS = {
    "asistencia",
    "vacaciones",
    "sin_registro",
    "falta",
    "incompleto",
    "descanso",
    "feriado",
    "checada_en_vacaciones",
    "sin_horario",
}

BIOTIME_CONFIG_KEYS = {
    "sync_activo": "BIOTIME_SYNC_ACTIVO",
    "base_url": "BIOTIME_BASE_URL",
    "access_key": "BIOTIME_ACCESS_KEY",
    "interval_seconds": "BIOTIME_SYNC_INTERVAL_SEG",
    "page_size": "BIOTIME_SYNC_PAGE_SIZE",
    "lookback_hours": "BIOTIME_SYNC_LOOKBACK_HRS",
    "timeout_seconds": "BIOTIME_SYNC_TIMEOUT_SEG",
    "recalc_days": "ASISTENCIA_RECALC_DIAS",
}
