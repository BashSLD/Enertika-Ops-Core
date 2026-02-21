import os
from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()

class Settings(BaseSettings):
    # --- Configuración de Base de Datos ---
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "")
    
    # Transaction Pooler: queries normales (SELECT, INSERT, UPDATE)
    # Escalable, comparte conexiones entre usuarios
    DB_HOST: str = os.getenv("DB_HOST", "")
    DB_PORT: str = os.getenv("DB_PORT", "6543")
    DB_USER: str = os.getenv("DB_USER", "postgres")
    DB_URL_ASYNC: str = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/postgres"
    
    # Session Pooler: LISTEN/NOTIFY para notificaciones en tiempo real (SSE)
    # Mantiene la conexión abierta durante toda la sesión
    DB_HOST_SSE: str = os.getenv("DB_HOST_SSE", "")
    DB_PORT_SSE: str = os.getenv("DB_PORT_SSE", "5432")
    DB_USER_SSE: str = os.getenv("DB_USER_SSE", "")
    DB_URL_SSE: str = f"postgresql://{DB_USER_SSE}:{DB_PASSWORD}@{DB_HOST_SSE}:{DB_PORT_SSE}/postgres"
    
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
    REDIRECT_URI: str = os.getenv("REDIRECT_URI", "http://localhost:8000/auth/callback")
    
    AUTHORITY_URL: str = f"https://login.microsoftonline.com/{GRAPH_TENANT_ID}"
    GRAPH_SCOPES: str = "email User.Read Mail.Send Mail.ReadWrite Files.ReadWrite.All Sites.Read.All"
    
    SHAREPOINT_SITE_ID: str = os.getenv("SHAREPOINT_SITE_ID", "")
    SHAREPOINT_DRIVE_ID: str = os.getenv("SHAREPOINT_DRIVE_ID", "")
    
    # --- URL Base de la Aplicación (para emails y links externos) ---
    APP_BASE_URL: str = os.getenv("APP_BASE_URL", "http://localhost:8000")

    # --- Configuración de Permisos (RBAC) ---
    # Departamentos que tienen acceso GLOBAL por defecto
    MANAGER_DEPARTMENTS: list = ["Dirección", "Gerencia", "Ventas", "Gerencia General"]

    # --- Constantes operacionales (extraidas de magic numbers) ---
    SESSION_MAX_AGE: int = int(os.getenv("SESSION_MAX_AGE", "86400"))  # 24h en segundos
    TOKEN_REFRESH_MARGIN_SECONDS: int = int(os.getenv("TOKEN_REFRESH_MARGIN", "300"))  # 5 min
    DB_POOL_MAX_SIZE: int = int(os.getenv("DB_POOL_MAX_SIZE", "20"))
    DB_POOL_TIMEOUT: int = int(os.getenv("DB_POOL_TIMEOUT", "30"))

settings = Settings()