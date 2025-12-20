import asyncio
import os
from dotenv import load_dotenv
import asyncpg

load_dotenv()

async def inspect_db():
    print("Conectando a BD...")
    try:
        conn = await asyncpg.connect(os.getenv("DATABASE_URL"))
        print("Conectado.")
        
        # 1. Listar columnas de tb_oportunidades
        rows = await conn.fetch("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'tb_oportunidades'
        """)
        
        print("\nColumnas en tb_oportunidades:")
        found = False
        for r in rows:
            print(f"- {r['column_name']} ({r['data_type']})")
            if r['column_name'] == 'titulo_proyecto':
                found = True
                
        if not found:
            print("\n❌ ALERTA: La columna 'titulo_proyecto' NO existe en la tabla.")
            
            # Check duplicates/similar
            print("\nBancando columnas similares o codigo_generado:")
            for r in rows:
                if 'titulo' in r['column_name'] or 'generado' in r['column_name']:
                    print(f"-> {r['column_name']}")
        else:
            print("\n✅ La columna 'titulo_proyecto' EXISTE.")

        await conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(inspect_db())
