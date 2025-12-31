
import asyncio
import os
import sys
import json
sys.path.append(os.getcwd())
from core.config import settings
import asyncpg

async def fetch_status():
    try:
        conn = await asyncpg.connect(settings.DB_URL_ASYNC)
        rows = await conn.fetch("SELECT * FROM tb_cat_estatus_global ORDER BY id")
        print(json.dumps([dict(r) for r in rows], indent=2, default=str))
        await conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(fetch_status())
