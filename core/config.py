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
    DB_URL_ASYNC: str = f"postgresql://{DB_USER}:{DB_PASSWORD}@{SUPABASE_URL.replace('https://', '').replace('http://', '')}:5432/postgres"
    
    # --- Configuración de Seguridad y Sesión ---
    SECRET_KEY: str = os.getenv("SECRET_KEY", "tu_super_secret_key_temporal_dev")

    # --- Configuración de Microsoft Azure AD ---
    GRAPH_CLIENT_ID: str = os.getenv("CLIENT_ID")
    GRAPH_CLIENT_SECRET: str = os.getenv("CLIENT_SECRET")
    GRAPH_TENANT_ID: str = os.getenv("TENANT_ID")
    
    # CORRECCIÓN CRÍTICA: Puerto 8000 y ruta completa al callback
    REDIRECT_URI: str = os.getenv("REDIRECT_URI", "http://localhost:8000/auth/callback")
    
    AUTHORITY_URL: str = f"https://login.microsoftonline.com/{GRAPH_TENANT_ID}"
    GRAPH_SCOPES: str = "User.Read Mail.Send Files.ReadWrite.All Sites.Read.All"

settings = Settings()