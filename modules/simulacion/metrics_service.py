# modules/simulacion/metrics_service.py
"""
Servicio de Métricas Operativas para Simulación.

Proporciona análisis de tiempos entre estatus, cuellos de botella
y ciclos de retrabajo para el dashboard de administradores.
"""

from dataclasses import dataclass
from typing import List, Optional
from uuid import UUID
from datetime import date
import asyncpg
import logging

logger = logging.getLogger("MetricsService")


# =============================================================================
# DATACLASSES
# =============================================================================

@dataclass
class MetricaEstatus:
    """Métrica de tiempo por estatus"""
    estatus_nombre: str
    tiempo_promedio_dias: float
    cantidad_transiciones: int
    porcentaje_tiempo_total: float


@dataclass
class MetricaCuelloBotella:
    """Análisis de cuellos de botella"""
    estatus_lento: str
    tiempo_promedio: float
    impacto: str  # "Alto", "Medio", "Bajo"



@dataclass
class MetricaCiclos:
    """Análisis de ciclos de retrabajo"""
    transicion: str  # "En Proceso ↔ En Revisión"
    promedio_ciclos: float
    maximo_ciclos: int
    oportunidades_afectadas: int


@dataclass
class MetricaTransicion:
    """Métrica de transición entre pares de estatus"""
    estatus_origen: str
    estatus_destino: str
    cantidad: int
    dias_promedio_en_destino: float
    es_retroceso: bool


# Orden del flujo "feliz" para detectar retrocesos
ORDEN_FLUJO = {
    "Pendiente": 1,
    "En Proceso": 2,
    "En Revisión": 3,
    "Entregado": 4,
    "Cancelado": 4,
    "Perdido": 4,
    "Ganada": 4
}


# =============================================================================
# SERVICE CLASS
# =============================================================================

class MetricsService:
    """Servicio de métricas operativas para simulación."""
    
    async def get_tiempo_por_estatus(
        self,
        conn: asyncpg.Connection,
        fecha_inicio: date,
        fecha_fin: date,
        user_id: UUID = None,
        tipo_solicitud_id: int = None
    ) -> List[MetricaEstatus]:
        """
        Calcula tiempo promedio en cada estatus.
        
        Lógica:
        - Para cada oportunidad, calcula tiempo entre cambios de estatus
        - Agrupa por estatus y promedia
        """
        
        filters = ["h1.fecha_cambio_sla >= $1", "h1.fecha_cambio_sla <= $2"]
        params: list = [fecha_inicio, fecha_fin]
        
        if user_id:
            filters.append(f"o.responsable_simulacion_id = ${len(params) + 1}")
            params.append(user_id)
        
        if tipo_solicitud_id:
            filters.append(f"o.id_tipo_solicitud = ${len(params) + 1}")
            params.append(tipo_solicitud_id)
        
        where_clause = " AND ".join(filters)
        
        query = f"""
            WITH transiciones AS (
                SELECT 
                    h1.id_oportunidad,
                    e.nombre as estatus,
                    h1.fecha_cambio_sla as inicio,
                    LEAD(h1.fecha_cambio_sla) OVER (
                        PARTITION BY h1.id_oportunidad 
                        ORDER BY h1.fecha_cambio_sla
                    ) as fin
                FROM tb_historial_estatus h1
                JOIN tb_cat_estatus_global e ON h1.id_estatus_nuevo = e.id
                JOIN tb_oportunidades o ON h1.id_oportunidad = o.id_oportunidad
                WHERE {where_clause}
            ),
            tiempos_por_estatus AS (
                SELECT 
                    estatus,
                    EXTRACT(EPOCH FROM (fin - inicio)) / 86400.0 as dias,
                    COUNT(*) OVER (PARTITION BY estatus) as cantidad
                FROM transiciones
                WHERE fin IS NOT NULL  -- Excluir estatus actual (sin fin)
            )
            SELECT 
                estatus,
                AVG(dias) as tiempo_promedio_dias,
                MAX(cantidad) as cantidad_transiciones,
                COALESCE(
                    SUM(dias) * 100.0 / NULLIF(SUM(SUM(dias)) OVER (), 0),
                    0
                ) as porcentaje_tiempo_total
            FROM tiempos_por_estatus
            GROUP BY estatus
            ORDER BY tiempo_promedio_dias DESC
        """
        
        try:
            rows = await conn.fetch(query, *params)
            
            return [
                MetricaEstatus(
                    estatus_nombre=row['estatus'],
                    tiempo_promedio_dias=round(float(row['tiempo_promedio_dias'] or 0), 1),
                    cantidad_transiciones=int(row['cantidad_transiciones'] or 0),
                    porcentaje_tiempo_total=round(float(row['porcentaje_tiempo_total'] or 0), 1)
                )
                for row in rows
            ]
        except Exception as e:
            logger.error(f"Error obteniendo tiempo por estatus: {e}")
            return []
    
    async def get_cuellos_botella(
        self,
        metricas_estatus: List[MetricaEstatus]
    ) -> List[MetricaCuelloBotella]:
        """
        Identifica cuellos de botella basándose en:
        1. Tiempo promedio alto
        2. Alto % del tiempo total
        """
        
        if not metricas_estatus:
            return []
        
        # Calcular percentiles
        tiempos = [m.tiempo_promedio_dias for m in metricas_estatus]
        
        if len(tiempos) >= 4:
            sorted_tiempos = sorted(tiempos)
            p75 = sorted_tiempos[int(len(tiempos) * 0.75)]
        else:
            p75 = max(tiempos) if tiempos else 0
        
        cuellos = []
        for metrica in metricas_estatus:
            # Criterio: >75% percentil Y >20% del tiempo total
            if metrica.tiempo_promedio_dias >= p75 and metrica.porcentaje_tiempo_total > 20:
                impacto = "Alto"
            elif metrica.tiempo_promedio_dias >= p75 or metrica.porcentaje_tiempo_total > 15:
                impacto = "Medio"
            else:
                continue
            
            cuellos.append(MetricaCuelloBotella(
                estatus_lento=metrica.estatus_nombre,
                tiempo_promedio=metrica.tiempo_promedio_dias,
                impacto=impacto
            ))
        
        return sorted(cuellos, key=lambda x: x.tiempo_promedio, reverse=True)
    
    async def get_analisis_ciclos(
        self,
        conn: asyncpg.Connection,
        fecha_inicio: date,
        fecha_fin: date
    ) -> List[MetricaCiclos]:
        """
        Analiza ciclos de retrabajo (ej: En Proceso ↔ En Revisión).
        """
        
        query = """
            WITH cambios_ida_vuelta AS (
                SELECT 
                    h1.id_oportunidad,
                    e1.nombre as estatus_a,
                    e2.nombre as estatus_b,
                    COUNT(*) as veces
                FROM tb_historial_estatus h1
                JOIN tb_historial_estatus h2 ON (
                    h1.id_oportunidad = h2.id_oportunidad
                    AND h1.fecha_cambio_sla < h2.fecha_cambio_sla
                    AND h1.id_estatus_nuevo = h2.id_estatus_anterior
                    AND h1.id_estatus_anterior = h2.id_estatus_nuevo
                )
                JOIN tb_cat_estatus_global e1 ON h1.id_estatus_nuevo = e1.id
                JOIN tb_cat_estatus_global e2 ON h2.id_estatus_nuevo = e2.id
                WHERE h1.fecha_cambio_sla >= $1
                  AND h1.fecha_cambio_sla <= $2
                GROUP BY h1.id_oportunidad, estatus_a, estatus_b
            )
            SELECT 
                estatus_a || ' ↔ ' || estatus_b as transicion,
                AVG(veces) as promedio_ciclos,
                MAX(veces) as maximo_ciclos,
                COUNT(DISTINCT id_oportunidad) as oportunidades_afectadas
            FROM cambios_ida_vuelta
            WHERE veces >= 2  -- Solo considerar ciclos reales (≥2 vueltas)
            GROUP BY estatus_a, estatus_b
            ORDER BY promedio_ciclos DESC
        """
        
        try:
            rows = await conn.fetch(query, fecha_inicio, fecha_fin)
            
            return [
                MetricaCiclos(
                    transicion=row['transicion'],
                    promedio_ciclos=round(float(row['promedio_ciclos'] or 0), 1),
                    maximo_ciclos=int(row['maximo_ciclos'] or 0),
                    oportunidades_afectadas=int(row['oportunidades_afectadas'] or 0)
                )
                for row in rows
            ]
        except Exception as e:
            logger.error(f"Error obteniendo análisis de ciclos: {e}")
            return []

    async def get_oportunidades_por_estatus(
        self,
        conn: asyncpg.Connection,
        estatus_nombre: str,
        fecha_inicio: date,
        fecha_fin: date,
        user_id: UUID = None
    ) -> List[dict]:
        """
        Obtiene detalle de oportunidades que están/estuvieron en un estatus específico.
        
        Returns:
            Lista de oportunidades con información completa para análisis
        """
        
        filters = ["h.fecha_cambio_sla >= $1", "h.fecha_cambio_sla <= $2", "e.nombre = $3"]
        params = [fecha_inicio, fecha_fin, estatus_nombre]
        
        if user_id:
            filters.append(f"o.responsable_simulacion_id = ${len(params) + 1}")
            params.append(user_id)
        
        where_clause = " AND ".join(filters)
        
        query = f"""
            WITH oportunidades_estatus AS (
                SELECT DISTINCT ON (h.id_oportunidad)
                    h.id_oportunidad,
                    h.fecha_cambio_sla as fecha_inicio_estatus,
                    LEAD(h.fecha_cambio_sla) OVER (
                        PARTITION BY h.id_oportunidad 
                        ORDER BY h.fecha_cambio_sla
                    ) as fecha_fin_estatus
                FROM tb_historial_estatus h
                JOIN tb_cat_estatus_global e ON h.id_estatus_nuevo = e.id
                WHERE {where_clause}
                ORDER BY h.id_oportunidad, h.fecha_cambio_sla DESC
            )
            SELECT 
                o.id_oportunidad,
                o.op_id_estandar,
                o.cliente_nombre,
                o.titulo_proyecto,
                t.nombre as tecnologia,
                ts.nombre as tipo_solicitud,
                o.es_licitacion,
                o.clasificacion_solicitud as clasificacion,
                u_sim.nombre as responsable_simulacion,
                u_sol.nombre as solicitado_por,
                oe.fecha_inicio_estatus,
                oe.fecha_fin_estatus,
                COALESCE(
                    EXTRACT(EPOCH FROM (
                        COALESCE(oe.fecha_fin_estatus, NOW()) - oe.fecha_inicio_estatus
                    )) / 86400.0,
                    0
                ) as dias_en_estatus
            FROM oportunidades_estatus oe
            JOIN tb_oportunidades o ON oe.id_oportunidad = o.id_oportunidad
            LEFT JOIN tb_cat_tecnologias t ON o.id_tecnologia = t.id
            LEFT JOIN tb_cat_tipos_solicitud ts ON o.id_tipo_solicitud = ts.id
            LEFT JOIN tb_usuarios u_sim ON o.responsable_simulacion_id = u_sim.id_usuario
            LEFT JOIN tb_usuarios u_sol ON o.solicitado_por_id = u_sol.id_usuario
            ORDER BY dias_en_estatus DESC
            LIMIT 50
        """
        
        try:
            rows = await conn.fetch(query, *params)
            
            oportunidades = []
            for row in rows:
                oportunidades.append({
                    'id_oportunidad': str(row['id_oportunidad']),
                    'op_id_estandar': row['op_id_estandar'],
                    'cliente_nombre': row['cliente_nombre'] or 'N/A',
                    'titulo_proyecto': row['titulo_proyecto'],
                    'tecnologia': row['tecnologia'] or 'N/A',
                    'tipo_solicitud': row['tipo_solicitud'] or 'N/A',
                    'es_licitacion': row['es_licitacion'],
                    'clasificacion': row['clasificacion'],
                    'responsable_simulacion': row['responsable_simulacion'] or 'Sin asignar',
                    'solicitado_por': row['solicitado_por'] or 'N/A',
                    'dias_en_estatus': round(float(row['dias_en_estatus']), 1)
                })
            
            return oportunidades
        
        except Exception as e:
            logger.error(f"Error obteniendo oportunidades por estatus: {e}")
            return []

    async def get_transiciones_par_a_par(
        self,
        conn: asyncpg.Connection,
        user_id: UUID = None,
        tipo_solicitud_id: int = None
    ) -> List[MetricaTransicion]:
        """
        Obtiene métricas de transiciones agrupadas por par (origen → destino).
        
        Muestra el estado ACTUAL del pipeline: para cada oportunidad activa,
        identifica su última transición y agrupa por par de estatus.
        """
        
        filters = ["o.id_estatus_global NOT IN (SELECT id FROM tb_cat_estatus_global WHERE nombre IN ('Entregado', 'Cancelado', 'Perdido', 'Ganada'))"]
        params: list = []
        
        if user_id:
            filters.append(f"o.responsable_simulacion_id = ${len(params) + 1}")
            params.append(user_id)
        
        if tipo_solicitud_id:
            filters.append(f"o.id_tipo_solicitud = ${len(params) + 1}")
            params.append(tipo_solicitud_id)
        
        where_clause = " AND ".join(filters) if filters else "TRUE"
        
        query = f"""
            WITH ultima_transicion AS (
                SELECT DISTINCT ON (h.id_oportunidad)
                    h.id_oportunidad,
                    h.id_estatus_anterior,
                    h.id_estatus_nuevo,
                    h.fecha_cambio_sla
                FROM tb_historial_estatus h
                JOIN tb_oportunidades o ON h.id_oportunidad = o.id_oportunidad
                WHERE {where_clause}
                  AND h.id_estatus_anterior IS NOT NULL
                ORDER BY h.id_oportunidad, h.fecha_cambio_sla DESC
            )
            SELECT 
                COALESCE(e_ant.nombre, 'Inicio') as estatus_origen,
                e_nuevo.nombre as estatus_destino,
                COUNT(*) as cantidad,
                AVG(
                    EXTRACT(EPOCH FROM (NOW() - ut.fecha_cambio_sla)) / 86400.0
                ) as dias_promedio_en_destino
            FROM ultima_transicion ut
            LEFT JOIN tb_cat_estatus_global e_ant ON ut.id_estatus_anterior = e_ant.id
            JOIN tb_cat_estatus_global e_nuevo ON ut.id_estatus_nuevo = e_nuevo.id
            GROUP BY e_ant.nombre, e_nuevo.nombre
            ORDER BY cantidad DESC
        """
        
        try:
            rows = await conn.fetch(query, *params)
            
            transiciones = []
            for row in rows:
                origen = row['estatus_origen'] or 'Inicio'
                destino = row['estatus_destino']
                
                # Detectar retroceso
                orden_origen = ORDEN_FLUJO.get(origen, 0)
                orden_destino = ORDEN_FLUJO.get(destino, 0)
                es_retroceso = orden_destino < orden_origen
                
                transiciones.append(MetricaTransicion(
                    estatus_origen=origen,
                    estatus_destino=destino,
                    cantidad=int(row['cantidad']),
                    dias_promedio_en_destino=round(float(row['dias_promedio_en_destino'] or 0), 1),
                    es_retroceso=es_retroceso
                ))
            
            return transiciones
        
        except Exception as e:
            logger.error(f"Error obteniendo transiciones par a par: {e}")
            return []

    async def get_oportunidades_por_transicion(
        self,
        conn: asyncpg.Connection,
        estatus_origen: str,
        estatus_destino: str,
        user_id: UUID = None
    ) -> List[dict]:
        """
        Obtiene oportunidades cuya última transición fue de origen → destino.
        
        Returns:
            Lista de oportunidades actualmente en estatus_destino que vinieron de estatus_origen
        """
        
        params = [estatus_origen, estatus_destino]
        user_filter = ""
        
        if user_id:
            user_filter = "AND o.responsable_simulacion_id = $3"
            params.append(user_id)
        
        query = f"""
            WITH ultima_transicion AS (
                SELECT DISTINCT ON (h.id_oportunidad)
                    h.id_oportunidad,
                    h.id_estatus_anterior,
                    h.id_estatus_nuevo,
                    h.fecha_cambio_sla as fecha_transicion
                FROM tb_historial_estatus h
                WHERE h.id_estatus_anterior IS NOT NULL
                ORDER BY h.id_oportunidad, h.fecha_cambio_sla DESC
            )
            SELECT 
                o.id_oportunidad,
                o.op_id_estandar,
                o.cliente_nombre,
                o.titulo_proyecto,
                t.nombre as tecnologia,
                ts.nombre as tipo_solicitud,
                o.es_licitacion,
                o.clasificacion_solicitud as clasificacion,
                u_sim.nombre as responsable_simulacion,
                u_sol.nombre as solicitado_por,
                ut.fecha_transicion,
                COALESCE(
                    EXTRACT(EPOCH FROM (NOW() - ut.fecha_transicion)) / 86400.0,
                    0
                ) as dias_en_estatus
            FROM ultima_transicion ut
            JOIN tb_oportunidades o ON ut.id_oportunidad = o.id_oportunidad
            LEFT JOIN tb_cat_estatus_global e_ant ON ut.id_estatus_anterior = e_ant.id
            JOIN tb_cat_estatus_global e_nuevo ON ut.id_estatus_nuevo = e_nuevo.id
            LEFT JOIN tb_cat_tecnologias t ON o.id_tecnologia = t.id
            LEFT JOIN tb_cat_tipos_solicitud ts ON o.id_tipo_solicitud = ts.id
            LEFT JOIN tb_usuarios u_sim ON o.responsable_simulacion_id = u_sim.id_usuario
            LEFT JOIN tb_usuarios u_sol ON o.solicitado_por_id = u_sol.id_usuario
            WHERE COALESCE(e_ant.nombre, 'Inicio') = $1
              AND e_nuevo.nombre = $2
              {user_filter}
            ORDER BY dias_en_estatus DESC
            LIMIT 50
        """
        
        try:
            rows = await conn.fetch(query, *params)
            
            oportunidades = []
            for row in rows:
                oportunidades.append({
                    'id_oportunidad': str(row['id_oportunidad']),
                    'op_id_estandar': row['op_id_estandar'],
                    'cliente_nombre': row['cliente_nombre'] or 'N/A',
                    'titulo_proyecto': row['titulo_proyecto'],
                    'tecnologia': row['tecnologia'] or 'N/A',
                    'tipo_solicitud': row['tipo_solicitud'] or 'N/A',
                    'es_licitacion': row['es_licitacion'],
                    'clasificacion': row['clasificacion'],
                    'responsable_simulacion': row['responsable_simulacion'] or 'Sin asignar',
                    'solicitado_por': row['solicitado_por'] or 'N/A',
                    'dias_en_estatus': round(float(row['dias_en_estatus']), 1)
                })
            
            return oportunidades
        
        except Exception as e:
            logger.error(f"Error obteniendo oportunidades por transición: {e}")
            return []


# =============================================================================
# DEPENDENCY INJECTION
# =============================================================================

def get_metrics_service() -> MetricsService:
    """Factory para inyección de dependencias."""
    return MetricsService()
