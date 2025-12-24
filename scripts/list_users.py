import asyncio
from core.database import connect_to_db, get_db_connection, close_db_connection

async def list_users():
    await connect_to_db()
    async for conn in get_db_connection():
        rows = await conn.fetch("SELECT * FROM tb_usuarios")
        print(f"Found {len(rows)} users:")
        for row in rows:
            print(dict(row))
        break
    await close_db_connection()

if __name__ == "__main__":
    asyncio.run(list_users())
