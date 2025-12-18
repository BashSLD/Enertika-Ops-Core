import os
from supabase import create_client, Client
from dotenv import load_dotenv

# Cargar secretos del .env
load_dotenv()

url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")

# Validación simple para que no truene si faltan datos
if not url or not key:
    print("ADVERTENCIA: No se encontraron credenciales de Supabase en .env")
    # Usamos valores dummy para que la app no se cierre, pero la conexión fallará
    url = "https://ejemplo.supabase.co"
    key = "dummy"

# Crear la conexión
db: Client = create_client(url, key)

def probar_conexion():
    """Verifica si podemos leer la tabla de clientes"""
    try:
        # Intentamos leer 1 fila de clientes
        response = db.table("tb_clientes").select("*").limit(1).execute()
        print("Conexión a Supabase EXITOSA.")
        return True
    except Exception as e:
        print(f"Error conectando a Supabase: {e}")
        return False