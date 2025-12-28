"""
Script para crear índices de optimización en la base de datos
Ejecutar: python -m scripts.create_indexes
"""
import asyncio
import asyncpg
from core.config import settings

async def create_indexes():
    """Crea índices de optimización para el módulo comercial"""
    
    sql_commands = [
        # 1. Índice para status_global (usado en TODAS las pestañas)
        """
        CREATE INDEX IF NOT EXISTS idx_oportunidades_status_lower 
        ON tb_oportunidades(LOWER(status_global));
        """,
        
        # 2. Índice para tipo_solicitud (usado en pestaña Activos y Levantamientos)
        """
        CREATE INDEX IF NOT EXISTS idx_oportunidades_tipo_solicitud_lower 
        ON tb_oportunidades(LOWER(tipo_solicitud));
        """,
        
        # 3. Índice para la columna de fecha (usado en ORDER BY)
        """
        CREATE INDEX IF NOT EXISTS idx_oportunidades_fecha_solicitud 
        ON tb_oportunidades(fecha_solicitud DESC);
        """,
        
        # 4. Índices para las columnas de JOIN
        """
        CREATE INDEX IF NOT EXISTS idx_oportunidades_responsable_sim 
        ON tb_oportunidades(responsable_simulacion_id);
        """,
        
        """
        CREATE INDEX IF NOT EXISTS idx_oportunidades_creado_por 
        ON tb_oportunidades(creado_por_id);
        """,
        
        # 5. Índice compuesto para la pestaña de Levantamientos
        """
        CREATE INDEX IF NOT EXISTS idx_levantamientos_status 
        ON tb_oportunidades(LOWER(tipo_solicitud), LOWER(status_global))
        WHERE LOWER(tipo_solicitud) = 'solicitud de levantamiento';
        """
    ]
    
    try:
        print("🔌 Conectando a la base de datos...")
        conn = await asyncpg.connect(settings.DB_URL_ASYNC)
        
        print("📊 Creando índices de optimización...")
        for i, sql in enumerate(sql_commands, 1):
            try:
                await conn.execute(sql)
                print(f"  ✓ Índice {i}/{len(sql_commands)} creado exitosamente")
            except Exception as e:
                print(f"  ⚠️ Error en índice {i}: {e}")
        
        # Verificar índices creados
        print("\n📋 Verificando índices creados:")
        rows = await conn.fetch("""
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE tablename = 'tb_oportunidades'
            AND indexname LIKE 'idx_%'
            ORDER BY indexname;
        """)
        
        for row in rows:
            print(f"  • {row['indexname']}")
        
        await conn.close()
        print("\n✅ Proceso completado exitosamente")
        
    except Exception as e:
        print(f"\n❌ Error crítico: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(create_indexes())
