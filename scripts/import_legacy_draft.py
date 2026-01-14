import asyncio
import os
import sys
import csv
from datetime import datetime
from uuid import UUID

# Add project root to path
sys.path.append(os.getcwd())

from core.config import settings
from modules.comercial.service import ComercialService
from modules.comercial.schemas import OportunidadCreateCompleta, DetalleBessCreate
import asyncpg

CSV_FILE = "Data_Cleaned.csv" # El archivo limpio que tú generarás

async def import_legacy_data():
    print(f"🚀 Iniciando Importación desde {CSV_FILE}...")
    
    try:
        conn = await asyncpg.connect(settings.DB_URL_ASYNC)
        service = ComercialService()
        
        # 1. Cargar Mapeos (Simulados por ahora, en producción se leen de BD)
        # Necesitaremos buscar los IDs reales de Tecnologías y Tipos
        # mapeo_tecnologias = {"FV": 1, "BESS": 2} 
        
        with open(CSV_FILE, mode='r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            count = 0
            
            for row in reader:
                try:
                    # A. Preparar Contexto del Usuario Creador
                    # BUSCAR el ID del usuario en BD basado en el email o nombre del CSV
                    # user_db_id = await service.get_user_id_by_email(conn, row['Created By Email'])
                    
                    # Dummy context por ahora
                    user_context = {
                        "user_db_id": UUID("00000000-0000-0000-0000-000000000000"), # REEMPLAZAR con ID real
                        "user_name": row.get('Created By'),
                        "role": "MIGRATION_BOT"
                    }
                    
                    # B. Preparar Datos
                    # NOTA: 'fecha_manual_str' es la CLAVE. 
                    # Debe venir en formato ISO: "YYYY-MM-DDTHH:MM:SS"
                    # El servicio asumirá que es Hora CDMX.
                    
                    datos = OportunidadCreateCompleta(
                        cliente_nombre=row['cliente'],
                        nombre_proyecto=row['nombre_proyecto'],
                        canal_venta=row['canal_venta'],
                        id_tecnologia=int(row['id_tecnologia']), # Debe ser INT
                        id_tipo_solicitud=int(row['id_tipo_solicitud']), # Debe ser INT
                        cantidad_sitios=int(row.get('cantidad_sitios', 1)),
                        prioridad=row.get('prioridad', 'Normal'),
                        direccion_obra=row.get('direccion', ''),
                        fecha_manual_str=row['fecha_creacion_iso'], # <--- ESTO ES VITAL
                        id_estatus_global=int(row.get('id_estatus_global', 1)) # Nuevo: Mapeo de Estatus
                    )
                    
                    # C. Ejecutar Creación (Esto dispara los cálculos automáticos)
                    new_id, op_id, fuera_horario = await service.crear_oportunidad_transaccional(conn, datos, user_context)
                    
                    print(f"✅ Importado: {op_id} - {datos.nombre_proyecto}")
                    count += 1
                    
                except Exception as e:
                    print(f"❌ Error en fila {count+1}: {e}")

        print(f"\n🏁 Importación Finalizada. Total: {count}")
        await conn.close()
        
    except Exception as e:
        print(f"🔥 Error Crítico: {e}")

if __name__ == "__main__":
    asyncio.run(import_legacy_data())
