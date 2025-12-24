import asyncio
from core.database import connect_to_db, get_db_connection, close_db_connection

async def add_active_col():
    await connect_to_db()
    async for conn in get_db_connection():
        # Check if column exists
        try:
            # Attempt to add the column. If it exists, this might fail or we can use IF NOT EXISTS if postgres supports it for columns (PG 9.6+ supports IF NOT EXISTS)
            # Standard SQL: ALTER TABLE table ADD COLUMN IF NOT EXISTS col ...
            await conn.execute("ALTER TABLE tb_usuarios ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE")
            print("Column 'is_active' checked/added to tb_usuarios.")
            
            # Update existing NULLs if any (though default handles new ones, old ones might need update if column was just added without default affecting existing rows depending on PG version, but DEFAULT usually fills it)
            # Let's ensure all are true by default
            await conn.execute("UPDATE tb_usuarios SET is_active = TRUE WHERE is_active IS NULL")
            print("Ensured all users are active by default.")
            
        except Exception as e:
            print(f"Error: {e}")
        break
    await close_db_connection()

if __name__ == "__main__":
    asyncio.run(add_active_col())
