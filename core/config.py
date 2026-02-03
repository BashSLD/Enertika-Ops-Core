import os
from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()

class Settings(BaseSettings):
    # --- Configuración de Base de Datos (Supabase/Postgres) ---
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    # Eliminamos SUPABASE_KEY si solo usas asyncpg para SQL directo.
    
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "")
    DB_USER: str = os.getenv("DB_USER", "postgres")
    
    
    # Construcción de URL Async para SQLAlchemy/Asyncpg
    # Puerto principal: 6543 (Transaction Mode) para queries normales - escalable
    DB_PORT: str = os.getenv("DB_PORT", "6543")
    DB_URL_ASYNC: str = f"postgresql://{DB_USER}:{DB_PASSWORD}@{SUPABASE_URL.replace('https://', '').replace('http://', '')}:{DB_PORT}/postgres"
    
    # Puerto SSE: 5432 (Session Mode) para LISTEN/NOTIFY - requerido para notificaciones en tiempo real
    DB_PORT_SSE: str = os.getenv("DB_PORT_SSE", "5432")
    DB_URL_SSE: str = f"postgresql://{DB_USER}:{DB_PASSWORD}@{SUPABASE_URL.replace('https://', '').replace('http://', '')}:{DB_PORT_SSE}/postgres"
    
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

settings = Settings()