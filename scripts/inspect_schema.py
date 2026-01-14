import asyncio
import os
import sys
from datetime import datetime

# Añadir raíz al path para importar core
sys.path.append(os.getcwd())

from core.config import settings
import asyncpg

OUTPUT_FILE = "DB_SCHEMA_SNAPSHOT.md"

async def inspect():
    print("Conectando a Base de Datos...") 
    
    try:
        conn = await asyncpg.connect(settings.DB_URL_ASYNC)
        
        # 1. Obtener Tablas
        tables = await conn.fetch("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            ORDER BY table_name
        """)
        
        md_content = "# Radiografia de Base de Datos (Snapshot)\n\n"
        md_content += f"**Generado:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        md_content += f"**Total de tablas:** {len(tables)}\n\n"
        md_content += "---\n\n"
        
        # Tabla de contenidos
        md_content += "## Indice de Tablas\n\n"
        for t in tables:
            t_name = t['table_name']
            md_content += f"- [{t_name}](#{t_name.replace('_', '-')})\n"
        md_content += "\n---\n\n"
        
        print(f"Se encontraron {len(tables)} tablas.")

        for t in tables:
            t_name = t['table_name']
            print(f"Procesando tabla: {t_name}")
            
            md_content += f"## Tabla: `{t_name}`\n\n"
            
            # 2. Obtener información de la tabla
            table_info = await conn.fetchrow("""
                SELECT 
                    obj_description(c.oid) as table_comment
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relname = $1 AND n.nspname = 'public'
            """, t_name)
            
            if table_info and table_info['table_comment']:
                md_content += f"**Descripcion:** {table_info['table_comment']}\n\n"
            
            # 3. Obtener Columnas
            columns = await conn.fetch("""
                SELECT 
                    column_name, 
                    data_type, 
                    character_maximum_length,
                    is_nullable, 
                    column_default
                FROM information_schema.columns 
                WHERE table_name = $1 
                ORDER BY ordinal_position
            """, t_name)
            
            md_content += "### Columnas\n\n"
            md_content += "| Columna | Tipo | Null | Default |\n"
            md_content += "| :--- | :--- | :--- | :--- |\n"
            
            for c in columns:
                dtype = c['data_type']
                if c['character_maximum_length']:
                    dtype = f"{dtype}({c['character_maximum_length']})"
                    
                default_val = c['column_default'] if c['column_default'] else "-"
                if default_val and len(str(default_val)) > 50:
                    default_val = str(default_val)[:47] + "..."
                    
                md_content += f"| **{c['column_name']}** | `{dtype}` | {c['is_nullable']} | `{default_val}` |\n"
            
            md_content += "\n"
            
            # 4. Obtener Primary Keys
            pk_info = await conn.fetch("""
                SELECT kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                WHERE tc.constraint_type = 'PRIMARY KEY'
                    AND tc.table_name = $1
                ORDER BY kcu.ordinal_position
            """, t_name)
            
            if pk_info:
                pk_cols = [pk['column_name'] for pk in pk_info]
                md_content += f"**Primary Key:** `{', '.join(pk_cols)}`\n\n"
            
            # 5. Obtener Foreign Keys
            fk_info = await conn.fetch("""
                SELECT
                    tc.constraint_name,
                    kcu.column_name,
                    ccu.table_name AS foreign_table_name,
                    ccu.column_name AS foreign_column_name,
                    rc.delete_rule,
                    rc.update_rule
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage AS ccu
                    ON ccu.constraint_name = tc.constraint_name
                    AND ccu.table_schema = tc.table_schema
                JOIN information_schema.referential_constraints AS rc
                    ON rc.constraint_name = tc.constraint_name
                WHERE tc.constraint_type = 'FOREIGN KEY'
                    AND tc.table_name = $1
                ORDER BY kcu.ordinal_position
            """, t_name)
            
            if fk_info:
                md_content += "### Foreign Keys (Relaciones)\n\n"
                md_content += "| Columna Local | Tabla Referenciada | Columna Ref | Delete | Update |\n"
                md_content += "| :--- | :--- | :--- | :--- | :--- |\n"
                for fk in fk_info:
                    md_content += f"| `{fk['column_name']}` | `{fk['foreign_table_name']}` | `{fk['foreign_column_name']}` | {fk['delete_rule']} | {fk['update_rule']} |\n"
                md_content += "\n"
            
            # 6. Obtener Índices
            indexes = await conn.fetch("""
                SELECT
                    i.relname as index_name,
                    a.attname as column_name,
                    ix.indisunique as is_unique,
                    ix.indisprimary as is_primary
                FROM pg_class t
                JOIN pg_index ix ON t.oid = ix.indrelid
                JOIN pg_class i ON i.oid = ix.indexrelid
                JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey)
                WHERE t.relname = $1
                    AND t.relkind = 'r'
                    AND NOT ix.indisprimary
                ORDER BY i.relname, a.attnum
            """, t_name)
            
            if indexes:
                md_content += "### Indices\n\n"
                md_content += "| Nombre Indice | Columna | Unique |\n"
                md_content += "| :--- | :--- | :--- |\n"
                for idx in indexes:
                    unique_flag = "Si" if idx['is_unique'] else "No"
                    md_content += f"| `{idx['index_name']}` | `{idx['column_name']}` | {unique_flag} |\n"
                md_content += "\n"
            
            # 7. Obtener Constraints (UNIQUE, CHECK)
            constraints = await conn.fetch("""
                SELECT
                    tc.constraint_name,
                    tc.constraint_type,
                    kcu.column_name,
                    cc.check_clause
                FROM information_schema.table_constraints tc
                LEFT JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                LEFT JOIN information_schema.check_constraints cc
                    ON tc.constraint_name = cc.constraint_name
                WHERE tc.table_name = $1
                    AND tc.constraint_type IN ('UNIQUE', 'CHECK')
                ORDER BY tc.constraint_type, tc.constraint_name
            """, t_name)
            
            if constraints:
                md_content += "### Constraints Adicionales\n\n"
                for const in constraints:
                    if const['constraint_type'] == 'UNIQUE':
                        md_content += f"- **UNIQUE:** `{const['column_name']}`\n"
                    elif const['constraint_type'] == 'CHECK':
                        check_clause = const['check_clause'][:100] + "..." if len(const['check_clause']) > 100 else const['check_clause']
                        md_content += f"- **CHECK:** `{check_clause}`\n"
                md_content += "\n"
            
            # 8. Estadísticas de la tabla
            stats = await conn.fetchrow("""
                SELECT 
                    n_live_tup as row_count,
                    pg_size_pretty(pg_total_relation_size(quote_ident($1)::regclass)) as total_size
                FROM pg_stat_user_tables
                WHERE relname = $1
            """, t_name)
            
            if stats and stats['row_count'] is not None:
                md_content += f"**Estadisticas:** {stats['row_count']} filas | Tamano: {stats['total_size']}\n\n"
            
            md_content += "---\n\n"
        
        # Resumen de relaciones al final
        md_content += "## Mapa de Relaciones\n\n"
        md_content += "Diagrama de Foreign Keys (quien apunta a quien):\n\n"
        
        all_fks = await conn.fetch("""
            SELECT
                tc.table_name,
                kcu.column_name,
                ccu.table_name AS foreign_table_name,
                ccu.column_name AS foreign_column_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
                ON tc.constraint_name = kcu.constraint_name
            JOIN information_schema.constraint_column_usage AS ccu
                ON ccu.constraint_name = tc.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY'
            ORDER BY tc.table_name, kcu.column_name
        """)
        
        if all_fks:
            md_content += "```mermaid\nerDiagram\n"
            for fk in all_fks:
                md_content += f"    {fk['table_name']} ||--o{{ {fk['foreign_table_name']} : {fk['column_name']}\n"
            md_content += "```\n\n"
        
        # Guardar archivo
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(md_content)
            
        print(f"EXITO: Esquema guardado en '{OUTPUT_FILE}'")
        print(f"Total de tablas procesadas: {len(tables)}")
        await conn.close()
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(inspect())