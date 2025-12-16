# Archivo: core/config.py

import os
from dotenv import load_dotenv
from pydantic_settings import BaseSettings # Importación correcta para FastAPI

# Cargar variables de entorno desde .env
load_dotenv()

class Settings(BaseSettings):
    # --- Configuración de Base de Datos (Supabase) ---
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "") # No se usa con asyncpg, pero la conservamos
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "")   # <--- CLAVE CRÍTICA
    DB_USER: str = os.getenv("DB_USER", "postgres")
    DB_URL_ASYNC: str = f"postgresql://{DB_USER}:{DB_PASSWORD}@{SUPABASE_URL.replace('https://', '').replace('http://', '')}:5432/postgres"
    
    # --- Configuración de Microsoft Azure AD ---
    GRAPH_CLIENT_ID: str = os.getenv("CLIENT_ID")
    GRAPH_CLIENT_SECRET: str = os.getenv("CLIENT_SECRET")
    GRAPH_TENANT_ID: str = os.getenv("TENANT_ID")
    REDIRECT_URI: str = os.getenv("REDIRECT_URI", "http://localhost:8550")
    
    # URL de autoridad: Usamos tu Tenant ID especifico para mayor seguridad
    AUTHORITY_URL: str = f"https://login.microsoftonline.com/{GRAPH_TENANT_ID}"
    
    # --- AGREGAR ESTA VARIABLE DE SCOPE ---
    GRAPH_SCOPES: str = "User.Read Mail.Send Files.ReadWrite.All Sites.Read.All"
    
    # Añade cualquier otra variable crítica aquí...

settings = Settings()

# Verificación de URLs
print("Configuración cargada. URL de Conexión asíncrona (asyncpg):")
print(settings.DB_URL_ASYNC)
# Nota: La clave se oculta aquí por seguridad en un entorno real.
print(settings.DB_URL_ASYNC.split('@')[0] + '@' + settings.DB_URL_ASYNC.split('@')[1].split(':')[0] + ':...')