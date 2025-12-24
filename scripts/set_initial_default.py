import asyncio
import os
import sys

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import connect_to_db, close_db_connection, _connection_pool
import core.database

async def set_default_email():
    await connect_to_db()
    pool = core.database._connection_pool
    
    if not pool:
        print("Failed to pool.")
        return

    try:
        async with pool.acquire() as conn:
            print("Setting default_to = ''...")
            # Upsert logic just in case
            await conn.execute("""
                INSERT INTO tb_email_defaults (id, default_to, default_cc, default_cco) 
                VALUES (1, '', '', '')
                ON CONFLICT (id) DO UPDATE 
                SET default_to = ''
                WHERE tb_email_defaults.default_to = '' OR tb_email_defaults.default_to IS NULL;
            """)
            print("Done.")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await close_db_connection()

if __name__ == "__main__":
    asyncio.run(set_default_email())
