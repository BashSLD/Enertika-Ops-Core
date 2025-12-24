import asyncio
import os
import sys

# Añadir raíz al path para importar core
sys.path.append(os.getcwd())

from core.config import settings
import asyncpg

OUTPUT_FILE = "DB_SCHEMA_SNAPSHOT.md"

async def inspect():
    print(f"🔍 Conectando a Base de Datos...") 
    
    try:
        conn = await asyncpg.connect(settings.DB_URL_ASYNC)
        
        # 1. Obtener Tablas
        tables = await conn.fetch("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            ORDER BY table_name
        """)
        
        md_content = "# 📸 Radiografía de Base de Datos (Snapshot)\n\n"
        md_content += f"**Generado el:** {asyncio.get_event_loop().time()}\n\n"
        
        print(f"✅ Se encontraron {len(tables)} tablas.")

        for t in tables:
            t_name = t['table_name']
            md_content += f"## 📦 Tabla: `{t_name}`\n\n"
            
            # 2. Obtener Columnas
            columns = await conn.fetch("""
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns 
                WHERE table_name = $1 
                ORDER BY ordinal_position
            """, t_name)
            
            md_content += "| Columna | Tipo | Null | Default |\n"
            md_content += "| :--- | :--- | :--- | :--- |\n"
            
            for c in columns:
                default_val = c['column_default'] if c['column_default'] else "-"
                # Limpiar valores largos
                if default_val and len(str(default_val)) > 50:
                    default_val = str(default_val)[:47] + "..."
                    
                md_content += f"| **{c['column_name']}** | `{c['data_type']}` | {c['is_nullable']} | `{default_val}` |\n"
            
            md_content += "\n"
            
        # Guardar archivo
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(md_content)
            
        print(f"🚀 ÉXITO: Esquema guardado en '{OUTPUT_FILE}'")
        await conn.close()
        
    except Exception as e:
        print(f"❌ ERROR: {e}")

if __name__ == "__main__":
    asyncio.run(inspect())