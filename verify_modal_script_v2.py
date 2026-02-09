import asyncio
import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from core.database import get_db_connection, connect_to_db

async def main():
    try:
        print("Connecting to DB...")
        await connect_to_db()
        async for conn in get_db_connection():
            print("Connected.")
            rows = await conn.fetch("SELECT column_name FROM information_schema.columns WHERE table_name = 'tb_documentos_attachments'")
            print("Columns in tb_documentos_attachments:")
            for r in rows:
                print(f" - {r['column_name']}")
            return
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
