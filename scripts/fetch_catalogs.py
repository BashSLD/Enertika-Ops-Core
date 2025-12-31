import asyncio
import os
import sys
import json

# Add project root to path
sys.path.append(os.getcwd())

from core.config import settings
import asyncpg

class UUIDEncoder(json.JSONEncoder):
    def default(self, obj):
        if hasattr(obj, 'hex'):
            return str(obj)
        return super().default(obj)

async def fetch_catalogs():
    try:
        conn = await asyncpg.connect(settings.DB_URL_ASYNC)
        
        catalogs = {}

        # 1. Tecnologias
        catalogs['tecnologias'] = [dict(r) for r in await conn.fetch("SELECT id, nombre, activo FROM tb_cat_tecnologias")]
        
        # 2. Tipos Solicitud
        catalogs['tipos_solicitud'] = [dict(r) for r in await conn.fetch("SELECT id, nombre, codigo_interno, activo FROM tb_cat_tipos_solicitud")]
        
        # 3. Usuarios (Solo activos para mapping)
        catalogs['usuarios'] = [dict(r) for r in await conn.fetch("SELECT id_usuario, nombre, email FROM tb_usuarios WHERE is_active = true")]

        print(json.dumps(catalogs, indent=2, cls=UUIDEncoder))
        
        await conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(fetch_catalogs())
