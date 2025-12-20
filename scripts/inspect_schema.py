import asyncio
import os
import sys

# Add root to sys.path
sys.path.append(os.getcwd())

from core.database import _connection_pool
from core.config import settings
import asyncpg

ARTIFACTS_DIR = r"C:\Users\SISTEMAS\.gemini\antigravity\brain\a9b1fbe0-a3ee-4ea0-a901-5ef3a64530c0"
OUTPUT_FILE = os.path.join(ARTIFACTS_DIR, "DB_SCHEMA_REALTIME.md")

async def inspect():
    print(f"Connecting to: {settings.DB_URL_ASYNC.split('@')[1]}...") # Hide auth
    
    try:
        conn = await asyncpg.connect(settings.DB_URL_ASYNC)
        
        # 1. Fetch Tables
        tables = await conn.fetch("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            ORDER BY table_name
        """)
        
        md_content = "# Radiografía de Base de Datos (Supabase)\n\n"
        md_content += f"**Fecha:** {asyncio.get_event_loop().time()}\n\n"
        
        for t in tables:
            t_name = t['table_name']
            md_content += f"## Tabla: `{t_name}`\n\n"
            
            # 2. Fetch Columns
            columns = await conn.fetch("""
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns 
                WHERE table_name = $1 
                ORDER BY ordinal_position
            """, t_name)
            
            md_content += "| Columna | Tipo | Nullable | Default |\n"
            md_content += "| :--- | :--- | :--- | :--- |\n"
            
            for c in columns:
                default_val = c['column_default'] if c['column_default'] else "-"
                # Clean up long default values if needed
                if default_val and len(str(default_val)) > 50:
                    default_val = str(default_val)[:47] + "..."
                    
                md_content += f"| **{c['column_name']}** | `{c['data_type']}` | {c['is_nullable']} | `{default_val}` |\n"
            
            md_content += "\n"
            
        # Write to file
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(md_content)
            
        print(f"SUCCESS: Schema dumped to {OUTPUT_FILE}")
        await conn.close()
        
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    asyncio.run(inspect())
