import asyncio
import asyncpg
from core.config import settings

# Diccionarios de mapeo manual para casos que no coincidan exacto (Typos comunes)
# Formato: "texto_en_bd_viejo": "nombre_en_catalogo_nuevo"
NORMALIZACIONES = {
    "Pre-Oferta": "Pre Oferta",
    "pre oferta": "Pre Oferta",
    "Pre oferta": "Pre Oferta",
    "Licitacion": "Licitación",
    "FV+BESS": "FV + BESS",
    "fv": "FV",
    "bess": "BESS",
    "En revision": "En Revisión",
    "En proceso": "En Proceso",
    "Cancelado trabajado": "Cancelado" # Mapeamos tu estatus viejo al estándar nuevo
}

async def migrar_datos():
    print("🚀 Iniciando migración de datos...")
    
    try:
        # 1. Conexión directa (Standalone)
        conn = await asyncpg.connect(settings.DB_URL_ASYNC)
        print("✅ Conexión exitosa a Base de Datos.")

        # 2. Cargar Catálogos en Memoria (Dict: Nombre -> ID)
        print("📂 Cargando catálogos...")
        
        # Tecnologías
        rows = await conn.fetch("SELECT id, nombre FROM tb_cat_tecnologias")
        cat_tecnologias = {r['nombre'].upper(): r['id'] for r in rows}
        
        # Tipos Solicitud
        rows = await conn.fetch("SELECT id, nombre FROM tb_cat_tipos_solicitud")
        cat_solicitud = {r['nombre'].upper(): r['id'] for r in rows}
        
        # Estatus Global
        rows = await conn.fetch("SELECT id, nombre FROM tb_cat_estatus_global")
        cat_estatus = {r['nombre'].upper(): r['id'] for r in rows}

        print(f"   - Tecnologías cargadas: {len(cat_tecnologias)}")
        print(f"   - Tipos Solicitud cargados: {len(cat_solicitud)}")
        print(f"   - Estatus cargados: {len(cat_estatus)}")

        # 3. Leer Oportunidades Viejas
        oportunidades = await conn.fetch("""
            SELECT id_oportunidad, tipo_tecnologia, tipo_solicitud, status_global 
            FROM tb_oportunidades
        """)
        
        print(f"🔄 Procesando {len(oportunidades)} oportunidades...")
        
        updates = 0
        errores = 0

        for op in oportunidades:
            op_id = op['id_oportunidad']
            
            # --- Lógica de Mapeo ---
            
            # 1. Tecnología
            txt_tec = (op['tipo_tecnologia'] or "").strip()
            # Aplicar corrección manual si existe, sino usar el texto original
            txt_tec = NORMALIZACIONES.get(txt_tec, txt_tec).upper()
            id_tec = cat_tecnologias.get(txt_tec)

            # 2. Tipo Solicitud
            txt_sol = (op['tipo_solicitud'] or "").strip()
            txt_sol = NORMALIZACIONES.get(txt_sol, txt_sol).upper()
            id_sol = cat_solicitud.get(txt_sol)

            # 3. Estatus
            txt_stat = (op['status_global'] or "").strip()
            txt_stat = NORMALIZACIONES.get(txt_stat, txt_stat).upper()
            id_stat = cat_estatus.get(txt_stat)

            # --- Ejecutar Update ---
            if id_tec or id_sol or id_stat:
                await conn.execute("""
                    UPDATE tb_oportunidades 
                    SET id_tecnologia = $1, 
                        id_tipo_solicitud = $2, 
                        id_estatus_global = $3
                    WHERE id_oportunidad = $4
                """, id_tec, id_sol, id_stat, op_id)
                updates += 1
            else:
                # Si no pudimos mapear nada, es un dato muy sucio o vacío
                # print(f"⚠️ Op {op_id}: No se pudo mapear nada. Datos: {op['tipo_tecnologia']}, {op['tipo_solicitud']}, {op['status_global']}")
                pass
                
            # Log de errores específicos (opcional para depurar)
            if txt_tec and not id_tec: print(f"⚠️ Tecnología desconocida: '{op['tipo_tecnologia']}'")
            if txt_sol and not id_sol: print(f"⚠️ Solicitud desconocida: '{op['tipo_solicitud']}'")
            if txt_stat and not id_stat: print(f"⚠️ Estatus desconocido: '{op['status_global']}'")

        print(f"✅ Migración finalizada.")
        print(f"   - Filas actualizadas: {updates}")
        
        await conn.close()

    except Exception as e:
        print(f"❌ Error crítico: {e}")

if __name__ == "__main__":
    asyncio.run(migrar_datos())