import os
from dotenv import load_dotenv

# Cargar variables del archivo .env
load_dotenv()

class Config:
    # --- MICROSOFT AZURE AD ---
    CLIENT_ID = os.getenv("CLIENT_ID")
    CLIENT_SECRET = os.getenv("CLIENT_SECRET")
    TENANT_ID = os.getenv("TENANT_ID")
    
    # URL de autoridad: Usamos tu Tenant ID especifico para mayor seguridad
    AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
    
    # IMPORTANTE: Esta URL debe ser EXACTAMENTE igual a la registrada en Azure Portal > Authentication
    REDIRECT_URI = os.getenv("REDIRECT_URI", "http://localhost:8550")
    
    # Permisos que pediremos al usuario (Delegados)
    # User.Read: Leer perfil
    # Mail.Send: Enviar correos
    # Files.ReadWrite.All: Subir archivos a SharePoint
    # Sites.Read.All: Buscar sitios de SharePoint
    SCOPE = ["User.Read", "Mail.Send", "Files.ReadWrite.All", "Sites.Read.All"]
    
    # --- SUPABASE ---
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")