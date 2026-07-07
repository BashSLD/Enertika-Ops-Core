import json
import logging
from uuid import UUID
from typing import Optional, List, Dict

logger = logging.getLogger("SharedServices")

class BessService:
    """
    Servicio compartido para manejo de Detalles BESS.
    """

    @staticmethod
    async def create_bess_details(conn, id_oportunidad: UUID, bess_data) -> None:
        """
        Inserta los detalles BESS para una oportunidad, o actualiza si ya existen
        (upsert por id_oportunidad, idempotente ante reintentos).

        Args:
            conn: Conexión BD
            id_oportunidad: UUID de la oportunidad padre
            bess_data: Objeto Pydantic (DetalleBessCreate) o similar con los atributos
        """
        query = """
            INSERT INTO tb_detalles_bess (
                id_oportunidad, uso_sistema_json, cargas_criticas_kw, tiene_motores, potencia_motor_hp,
                tiempo_autonomia, voltaje_operacion, cargas_separadas,
                tiene_planta_emergencia
            ) VALUES ($1, $2::jsonb, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (id_oportunidad) DO UPDATE SET
                uso_sistema_json = EXCLUDED.uso_sistema_json,
                cargas_criticas_kw = EXCLUDED.cargas_criticas_kw,
                tiene_motores = EXCLUDED.tiene_motores,
                potencia_motor_hp = EXCLUDED.potencia_motor_hp,
                tiempo_autonomia = EXCLUDED.tiempo_autonomia,
                voltaje_operacion = EXCLUDED.voltaje_operacion,
                cargas_separadas = EXCLUDED.cargas_separadas,
                tiene_planta_emergencia = EXCLUDED.tiene_planta_emergencia
        """
        
        # Manejo seguro de JSON
        uso_sistema_val = bess_data.uso_sistema_json
        if not isinstance(uso_sistema_val, str):
            uso_sistema_str = json.dumps(uso_sistema_val)
        else:
            uso_sistema_str = uso_sistema_val
        
        await conn.execute(query,
            id_oportunidad,
            uso_sistema_str,
            bess_data.cargas_criticas_kw,
            bess_data.tiene_motores,
            bess_data.potencia_motor_hp,
            bess_data.tiempo_autonomia,
            bess_data.voltaje_operacion,
            bess_data.cargas_separadas,
            bess_data.tiene_planta_emergencia
        )
        logger.debug(f"Detalles BESS creados para oportunidad {id_oportunidad}")

    @staticmethod
    async def get_bess_details(conn, id_oportunidad: UUID) -> Optional[Dict]:
        """
        Recupera detalles BESS.
        """
        row = await conn.fetchrow("""
            SELECT 
                db.uso_sistema_json,
                db.cargas_criticas_kw,
                db.tiene_motores,
                db.potencia_motor_hp,
                db.tiempo_autonomia,
                db.voltaje_operacion,
                db.cargas_separadas,
                db.tiene_planta_emergencia
            FROM tb_detalles_bess db
            WHERE db.id_oportunidad = $1
        """, id_oportunidad)
        
        if not row:
            return None
            
        data = dict(row)
        
        # Parse JSON
        if data.get('uso_sistema_json'):
            try:
                if isinstance(data['uso_sistema_json'], str):
                    data['uso_sistema_json'] = json.loads(data['uso_sistema_json'])
            except (json.JSONDecodeError, TypeError):
                data['uso_sistema_json'] = []
        
        return data
