import os
from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()

class Settings(BaseSettings):
    # --- Configuración de Base de Datos ---
    # Un solo host (Session Pooler IPv4) para ambas conexiones
    # El puerto determina el modo: 6543=Transaction, 5432=Session
    DB_HOST: str = os.getenv("DB_HOST", "")
    DB_USER: str = os.getenv("DB_USER", "")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "")
    
    # Transaction Mode (puerto 6543): queries normales - escalable
    DB_PORT: str = os.getenv("DB_PORT", "6543")
    DB_URL_ASYNC: str = f"postgresql://{os.getenv('DB_USER', '')}:{os.getenv('DB_PASSWORD', '')}@{os.getenv('DB_HOST', '')}:{os.getenv('DB_PORT', '6543')}/postgres"
    
    # Session Mode (puerto 5432): LISTEN/NOTIFY para notificaciones SSE
    DB_PORT_SSE: str = os.getenv("DB_PORT_SSE", "5432")
    DB_URL_SSE: str = f"postgresql://{os.getenv('DB_USER', '')}:{os.getenv('DB_PASSWORD', '')}@{os.getenv('DB_HOST', '')}:{os.getenv('DB_PORT_SSE', '5432')}/postgres"
    
    # NOTA: Transaction Mode (6543) NO soporta LISTEN/NOTIFY ni prepared statements
    # Por eso se usa configuración híbrida: queries en 6543, SSE en 5432
    
    # --- Configuración de Seguridad y Sesión ---
    SECRET_KEY: str = os.getenv("SECRET_KEY")
    DEBUG_MODE: bool = os.getenv("DEBUG_MODE", "True").lower() == "true"
    
    # Validación crítica: SECRET_KEY debe estar definida
    if not SECRET_KEY:
        raise ValueError("CRÍTICO: SECRET_KEY no definida en el entorno.")

    # --- Configuración de Microsoft Azure AD ---
    GRAPH_CLIENT_ID: str = os.getenv("CLIENT_ID")
    GRAPH_CLIENT_SECRET: str = os.getenv("CLIENT_SECRET")
    GRAPH_TENANT_ID: str = os.getenv("TENANT_ID")
    
    # CORRECCIÓN CRÍTICA: Puerto 8000 y ruta completa al callback
    REDIRECT_URI: str = os.getenv("REDIRECT_URI", "http://localhost:8001/auth/callback")
    
    AUTHORITY_URL: str = f"https://login.microsoftonline.com/{GRAPH_TENANT_ID}"
    GRAPH_SCOPES: str = "email User.Read Mail.Send Mail.ReadWrite Files.ReadWrite.All Sites.Read.All"
    
    SHAREPOINT_SITE_ID: str = os.getenv("SHAREPOINT_SITE_ID", "")
    SHAREPOINT_DRIVE_ID: str = os.getenv("SHAREPOINT_DRIVE_ID", "")

    # --- SAT Inbox (site SharePoint privado para XMLs SAT) ---
    SP_SAT_SITE_ID: str = os.getenv("SP_SAT_SITE_ID", "")
    SP_SAT_DRIVE_ID: str = os.getenv("SP_SAT_DRIVE_ID", "")
    SP_SAT_BASE_FOLDER: str = os.getenv("SP_SAT_BASE_FOLDER", "SAT-Inbox")

    # --- URL Base de la Aplicación (para emails y links externos) ---
    APP_BASE_URL: str = os.getenv("APP_BASE_URL", "http://localhost:8001")

    # --- Configuración de Permisos (RBAC) ---
    # Departamentos que tienen acceso GLOBAL por defecto
    MANAGER_DEPARTMENTS: list = ["Dirección", "Gerencia", "Ventas", "Gerencia General"]

    # --- Constantes operacionales (extraidas de magic numbers) ---
    SESSION_MAX_AGE: int = int(os.getenv("SESSION_MAX_AGE", "86400"))  # 24h en segundos
    TOKEN_REFRESH_MARGIN_SECONDS: int = int(os.getenv("TOKEN_REFRESH_MARGIN", "300"))  # 5 min
    DB_POOL_MAX_SIZE: int = int(os.getenv("DB_POOL_MAX_SIZE", "20"))
    DB_POOL_TIMEOUT: int = int(os.getenv("DB_POOL_TIMEOUT", "30"))
    DB_COMMAND_TIMEOUT: int = int(os.getenv("DB_COMMAND_TIMEOUT", "120"))  # iguala statement_timeout de Supabase

    # --- OAuth: correlación de intento (state/nonce) y reconexión ---
    OAUTH_ATTEMPT_TTL_SECONDS: int = int(os.getenv("OAUTH_ATTEMPT_TTL_SECONDS", "600"))  # 10 min
    TOKEN_REFRESH_LOCK_TTL_SECONDS: int = int(os.getenv("TOKEN_REFRESH_LOCK_TTL_SECONDS", "20"))

    # --- CFE: autorizaciones efimeras del lanzador local ---
    CFE_LAUNCHER_TICKET_TTL_SECONDS: int = int(
        os.getenv("CFE_LAUNCHER_TICKET_TTL_SECONDS", "600")
    )
    CFE_LAUNCHER_UPLOAD_GRANT_TTL_SECONDS: int = int(
        os.getenv("CFE_LAUNCHER_UPLOAD_GRANT_TTL_SECONDS", "900")
    )
    CFE_LAUNCHER_PUBLISH_LOCK_TTL_SECONDS: int = int(
        os.getenv("CFE_LAUNCHER_PUBLISH_LOCK_TTL_SECONDS", "3600")
    )

    # --- Cron Jobs ---
    CRON_SECRET: str = os.getenv("CRON_SECRET", "")

    # --- Tipo de Cambio Banxico ---
    BANXICO_TOKEN: str = os.getenv("BANXICO_TOKEN", "")

    # --- GitHub API (reporte CEO en entornos sin .git) ---
    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")
    GITHUB_REPO: str = os.getenv("GITHUB_REPO", "")
    GITHUB_BRANCH: str = os.getenv("GITHUB_BRANCH", "main")

    # --- PDF Generation ---
    PDF_MAX_IMAGE_WIDTH: int = int(os.getenv("PDF_MAX_IMAGE_WIDTH", "800"))
    PDF_IMAGE_QUALITY: int = int(os.getenv("PDF_IMAGE_QUALITY", "85"))
    PDF_MAX_UPLOAD_SIZE_MB: int = int(os.getenv("PDF_MAX_UPLOAD_SIZE_MB", "50"))

    # --- QuickChart (chart rendering server-side) ---
    QUICKCHART_URL: str = os.getenv("QUICKCHART_URL", "http://localhost:3400")

    # --- Redis (caché compartida entre workers Gunicorn) ---
    REDIS_URL: str = os.getenv("REDIS_URL", "")

    # --- Sentry (error monitoring) ---
    SENTRY_DSN: str = os.getenv("SENTRY_DSN", "")

    # --- Claude API (status IA módulo Operación, bajo demanda) ---
    # Vacío = IA deshabilitada, cae al fallback determinista (ver fase-3-ia-benchmark.md)
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

settings = Settings()
