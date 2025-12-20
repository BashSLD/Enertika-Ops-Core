import asyncio
import os
import sys

sys.path.append(os.getcwd())

from core.config import settings
import asyncpg

async def migrate():
    print(f"Connecting to DB...")
    try:
        conn = await asyncpg.connect(settings.DB_URL_ASYNC)
        
        # Check if column exists
        check = await conn.fetchval("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='tb_usuarios' AND column_name='department'
        """)
        
        if not check:
            print("Adding 'department' column to tb_usuarios...")
            await conn.execute("ALTER TABLE tb_usuarios ADD COLUMN department TEXT")
            print("✅ Column added successfully.")
        else:
            print("ℹ️ Column 'department' already exists.")
            
        await conn.close()
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(migrate())
