import asyncio
import os
import sys
import asyncpg

# Agregar el directorio actual al path para importar core
sys.path.append(os.getcwd())

from core.config import settings

async def verify_catalogs():
    database_url = settings.DB_URL_ASYNC
    
    if not database_url:
        print("Error: DB_URL_ASYNC is empty")
        return

    try:
        conn = await asyncpg.connect(database_url)
        print(" Connected to Database")
        
        print("\n=== tb_cat_estatus_global ===")
        rows = await conn.fetch("SELECT id, nombre, activo FROM tb_cat_estatus_global ORDER BY id")
        for r in rows:
            print(f"[{r['id']}] {r['nombre']} (Activo: {r['activo']})")

        print("\n=== tb_cat_tipos_solicitud ===")
        rows = await conn.fetch("SELECT id, nombre, codigo_interno, activo FROM tb_cat_tipos_solicitud ORDER BY id")
        for r in rows:
            print(f"[{r['id']}] {r['nombre']} | Code: {r['codigo_interno']} (Activo: {r['activo']})")
            
        await conn.close()
    
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(verify_catalogs())
