"""
Helper para registrar filtros Jinja2 de timezone en todas las instancias de templates.
"""
import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


def _compute_static_version() -> str:
    v = os.environ.get("RAILWAY_GIT_COMMIT_SHA", "")[:7]
    if v:
        return v
    # En dev: usar mtime del CSS compilado — cambia con cada npm run build:css
    css = Path(__file__).parent.parent / "static" / "css" / "tailwind.css"
    try:
        return str(int(css.stat().st_mtime))
    except OSError:
        pass
    try:
        result = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            timeout=2,
        ).decode().strip()
        return result or "dev"
    except Exception:
        logger.warning("cache-busting CSS: no se pudo obtener version, usando 'dev'")
        return "dev"


_STATIC_V = _compute_static_version()

def datetime_mx_format(value, format="%d/%m/%Y %H:%M"):
    """
    Filtro Jinja2 para convertir timestamps UTC a hora de México.
    
    Uso en HTML: {{ op.fecha_solicitud | time_mx }}
    Uso con formato custom: {{ op.fecha_solicitud | time_mx("%Y-%m-%d") }}
    """
    if value is None:
        return ""
    
    # Asegurarnos de que el valor tenga zona horaria
    # Si viene sin zona (naive), asumimos que es UTC
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo("UTC"))
        
    # CONVERSIÓN: De UTC a México
    mx_time = value.astimezone(ZoneInfo("America/Mexico_City"))
    
    return mx_time.strftime(format)

def datetime_input_format(value):
    """
    Filtro Jinja2 para preparar fechas para inputs HTML5 datetime-local.
    
    Uso en HTML: <input type="datetime-local" value="{{ op.fecha_visita | input_date }}">
    """
    if value is None:
        return ""
    
    # 1. Asegurar que sea consciente de zona (si viene de BD UTC)
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo("UTC"))
    
    # 2. Convertir a México
    mx_time = value.astimezone(ZoneInfo("America/Mexico_City"))
    
    # 3. Formato estricto para HTML5 (YYYY-MM-DDTHH:MM)
    return mx_time.strftime("%Y-%m-%dT%H:%M")

def clean_text(value):
    """
    Filtro Jinja2 para limpiar texto de caracteres de control no deseados.
    
    Remueve:
    - Carriage returns (\r)
    - Newlines (\n)
    
    Preserva espacios normales entre palabras.
    Solo elimina espacios al inicio y final.
    
    Uso en HTML: {{ op.titulo_proyecto | clean_text }}
    """
    if value is None:
        return ""
    
    # Convertir a string si no lo es
    text = str(value)
    
    # Eliminar SOLO \r y \n, sin afectar espacios normales
    text = text.replace('\r', '').replace('\n', '')
    
    # Eliminar espacios al inicio y final solamente
    return text.strip()

def dhm(valor_dias) -> str:
    """Convierte días decimales a formato compacto '1D 12h', '12h' o '3D'."""
    if valor_dias is None:
        return "—"
    dias = int(float(valor_dias))
    horas = round((float(valor_dias) - dias) * 24)
    if horas == 24:
        dias += 1
        horas = 0
    if dias == 0:
        return f"{horas}h"
    if horas == 0:
        return f"{dias}D"
    return f"{dias}D {horas}h"


def register_timezone_filters(jinja_env):
    """
    Registra los filtros de timezone en una instancia de Jinja2.

    Uso:
        from core.jinja_filters import register_timezone_filters
        templates = Jinja2Templates(directory="templates")
        register_timezone_filters(templates.env)
    """
    jinja_env.filters["time_mx"] = datetime_mx_format
    jinja_env.filters["input_date"] = datetime_input_format
    jinja_env.filters["clean_text"] = clean_text
    jinja_env.filters["dhm"] = dhm
    jinja_env.globals["static_v"] = _STATIC_V
