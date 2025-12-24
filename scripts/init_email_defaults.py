import asyncio
import os
import sys

# Add parent directory to path to import core
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import get_db_connection

from core.database import connect_to_db, close_db_connection, _connection_pool
import core.database

async def init_db():
    await connect_to_db()
    
    # Access the pool from the module where it was defined/imported
    pool = core.database._connection_pool
    if not pool:
        print("Failed to initialize pool.")
        return

    try:
        async with pool.acquire() as conn:
            print("Creating table tb_email_defaults...")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS tb_email_defaults (
                    id SERIAL PRIMARY KEY,
                    default_to TEXT DEFAULT '',
                    default_cc TEXT DEFAULT '',
                    default_cco TEXT DEFAULT ''
                );
            """)
            
            # Check if row exists
            count = await conn.fetchval("SELECT COUNT(*) FROM tb_email_defaults")
            if count == 0:
                print("Inserting initial row...")
                await conn.execute("INSERT INTO tb_email_defaults (id, default_to, default_cc, default_cco) VALUES (1, '', '', '')")
            else:
                print("Table already has data.")
            
            print("Done.")
    finally:
        await close_db_connection()

if __name__ == "__main__":
    asyncio.run(init_db())
