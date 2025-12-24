import asyncio
import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.database import connect_to_db, close_db_connection, _connection_pool
import core.database

async def check_defaults():
    await connect_to_db()
    pool = core.database._connection_pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM tb_email_defaults WHERE id = 1")
        print(f"Row: {dict(row) if row else 'None'}")
    await close_db_connection()

if __name__ == "__main__":
    asyncio.run(check_defaults())
