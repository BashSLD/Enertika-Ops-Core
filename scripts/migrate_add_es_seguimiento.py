"""
Script de migración usando el pool existente de la aplicación
Fecha: 2025-12-27
"""
import asyncio
from core.database import _connection_pool, connect_to_db

async def run_migration():
    """Ejecuta la migración usando el pool de la app."""
    
    # Asegurarnos de que hay conexión
    if not _connection_pool:
        print("⚠️ Pool no inicializado, inicializando...")
        await connect_to_db()
    
    async with _connection_pool.acquire() as conn:
        print("✅ Conexión obtenida del pool")
        
        # 1. Agregar columna
        print("\n📊 Agregando columna es_seguimiento...")
        await conn.execute("""
            ALTER TABLE tb_cat_tipos_solicitud 
            ADD COLUMN IF NOT EXISTS es_seguimiento BOOLEAN DEFAULT FALSE
        """)
        print("✅ Columna agregada correctamente")
        
        # 2. Configurar seguimientos
        print("\n🔧 Configurando tipos de seguimiento...")
        result = await conn.execute("""
            UPDATE tb_cat_tipos_solicitud 
            SET es_seguimiento = TRUE 
            WHERE codigo_interno IN ('COTIZACION', 'ACTUALIZACION', 'LEVANTAMIENTO')
        """)
        print(f"✅ Registros actualizados")
        
        # 3. Verificar resultados
        print("\n📋 Verificando configuración:")
        print("-" * 80)
        rows = await conn.fetch("""
            SELECT nombre, codigo_interno, es_seguimiento,
                   CASE 
                       WHEN es_seguimiento = TRUE THEN '✅ Editable (Seguimiento)'
                       ELSE '❌ No Editable (Inicial)'
                   END as comportamiento
            FROM tb_cat_tipos_solicitud 
            WHERE activo = TRUE
            ORDER BY es_seguimiento DESC, nombre
        """)
        
        for row in rows:
            print(f"{row['nombre']:30} | {row['codigo_interno']:20} | {row['comportamiento']}")
        
        print("-" * 80)
        print(f"\n✅ Migración completada exitosamente!")
        print(f"   - Tipos editables (seguimientos): {sum(1 for r in rows if r['es_seguimiento'])}")
        print(f"   - Tipos no editables (iniciales): {sum(1 for r in rows if not r['es_seguimiento'])}")

if __name__ == "__main__":
    asyncio.run(run_migration())
