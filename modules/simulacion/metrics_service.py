# modules/simulacion/metrics_service.py
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
    estatus_nombre: str
    tiempo_promedio_dias: float
    cantidad_transiciones: int
    porcentaje_tiempo_total: float


@dataclass
class MetricaCuelloBotella:
    estatus_lento: str
    tiempo_promedio: float
    impacto: str  # "Alto", "Medio", "Bajo"


@dataclass
class MetricaCiclos:
    transicion: str  # "En Proceso ↔ En Revisión"
    promedio_ciclos: float
    maximo_ciclos: int
    oportunidades_afectadas: int


@dataclass
class MetricaTransicion:
    estatus_origen: str
    estatus_destino: str
    cantidad: int
    dias_promedio_en_destino: float
    es_retroceso: bool


@dataclass
class MetricaCicloRevision:
    """Mide el ciclo de revisión de Dirección + retrabajo de Simulación."""
    tiempo_revision_direccion_dias: float
    tiempo_retrabajo_simulacion_dias: float
    oportunidades_con_revision: int
    total_entregadas: int
    pct_con_revision: float
    rondas_promedio: float


# =============================================================================
# SERVICE CLASS
# =============================================================================

class MetricsService:

    async def get_tiempo_por_estatus(
        self,
        conn: asyncpg.Connection,
        fecha_inicio: date,
        fecha_fin: date,
        user_id: UUID = None,
        tipo_solicitud_id: int = None
    ) -> List[MetricaEstatus]:
        """
        Calcula tiempo promedio en cada estatus no-terminal.

        LEAD() se calcula sobre el historial completo de cada oportunidad
        para evitar que el filtro de fecha corte los intervalos en los bordes (A.1).
        Los terminales se excluyen del resultado y del porcentaje (A.2).
        """
        params: list = [fecha_inicio, fecha_fin]
        user_filter = ""
        tipo_filter = ""

        if user_id:
            params.append(user_id)
            user_filter = f"AND o.responsable_simulacion_id = ${len(params)}"

        if tipo_solicitud_id:
            params.append(tipo_solicitud_id)
            tipo_filter = f"AND o.id_tipo_solicitud = ${len(params)}"

        query = f"""
            WITH oportunidades_en_rango AS (
                SELECT DISTINCT h.id_oportunidad
                FROM tb_historial_estatus h
                JOIN tb_oportunidades o ON h.id_oportunidad = o.id_oportunidad
                WHERE (h.fecha_cambio_sla AT TIME ZONE 'America/Mexico_City')::date >= $1
                  AND (h.fecha_cambio_sla AT TIME ZONE 'America/Mexico_City')::date <= $2
                  {user_filter}
                  {tipo_filter}
            ),
            todas_transiciones AS (
                SELECT
                    h.id_oportunidad,
                    e.nombre AS estatus,
                    e.es_estatus_final,
                    h.fecha_cambio_sla AS inicio,
                    LEAD(h.fecha_cambio_sla) OVER (
                        PARTITION BY h.id_oportunidad
                        ORDER BY h.fecha_cambio_sla
                    ) AS fin
                FROM tb_historial_estatus h
                JOIN tb_cat_estatus_oportunidades e ON h.id_estatus_nuevo = e.id
                WHERE h.id_oportunidad IN (SELECT id_oportunidad FROM oportunidades_en_rango)
            ),
            en_rango AS (
                SELECT
                    estatus,
                    EXTRACT(EPOCH FROM (fin - inicio)) / 86400.0 AS dias
                FROM todas_transiciones
                WHERE fin IS NOT NULL
                  AND (inicio AT TIME ZONE 'America/Mexico_City')::date >= $1
                  AND (inicio AT TIME ZONE 'America/Mexico_City')::date <= $2
                  AND es_estatus_final = false
            )
            SELECT
                estatus,
                AVG(dias) AS tiempo_promedio_dias,
                COUNT(*) AS cantidad_transiciones,
                COALESCE(
                    SUM(dias) * 100.0 / NULLIF(SUM(SUM(dias)) OVER (), 0),
                    0
                ) AS porcentaje_tiempo_total
            FROM en_rango
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
        except asyncpg.PostgresError as e:
            logger.error(f"Error de BD obteniendo tiempo por estatus: {e}")
            raise

    def get_cuellos_botella(
        self,
        metricas_estatus: List[MetricaEstatus]
    ) -> List[MetricaCuelloBotella]:
        """
        Identifica cuellos de botella por tiempo promedio alto y % del total.
        Los estatus terminales ya vienen excluidos de metricas_estatus.
        """
        if not metricas_estatus:
            return []

        tiempos = [m.tiempo_promedio_dias for m in metricas_estatus]

        if len(tiempos) >= 4:
            sorted_tiempos = sorted(tiempos)
            p75 = sorted_tiempos[int(len(tiempos) * 0.75)]
        else:
            p75 = max(tiempos) if tiempos else 0

        cuellos = []
        for metrica in metricas_estatus:
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
        fecha_fin: date,
        tipo_solicitud_id: int = None
    ) -> List[MetricaCiclos]:
        """
        Analiza ciclos de retrabajo (ej: En Proceso ↔ En Revisión).

        Usa LAG() por oportunidad para contar retrocesos reales, evitando
        el sobre-conteo cartesiano del self-join anterior (A.3).
        El orden del flujo proviene del catálogo (columna `orden`), no de
        un dict hardcodeado (A.4).
        """
        params: list = [fecha_inicio, fecha_fin]
        tipo_filter = ""
        if tipo_solicitud_id:
            params.append(tipo_solicitud_id)
            tipo_filter = f"AND o.id_tipo_solicitud = ${len(params)}"

        query = f"""
            WITH transiciones_seq AS (
                SELECT
                    h.id_oportunidad,
                    e.nombre AS estatus_nuevo,
                    e.orden AS orden_nuevo,
                    LAG(e.nombre) OVER (
                        PARTITION BY h.id_oportunidad ORDER BY h.fecha_cambio_sla
                    ) AS estatus_prev,
                    LAG(e.orden) OVER (
                        PARTITION BY h.id_oportunidad ORDER BY h.fecha_cambio_sla
                    ) AS orden_prev
                FROM tb_historial_estatus h
                JOIN tb_cat_estatus_oportunidades e ON h.id_estatus_nuevo = e.id
                JOIN tb_oportunidades o ON h.id_oportunidad = o.id_oportunidad
                WHERE (h.fecha_cambio_sla AT TIME ZONE 'America/Mexico_City')::date >= $1
                  AND (h.fecha_cambio_sla AT TIME ZONE 'America/Mexico_City')::date <= $2
                  AND e.es_estatus_final = false
                  {tipo_filter}
            ),
            retrocesos_por_opp AS (
                SELECT
                    id_oportunidad,
                    estatus_nuevo AS estatus_a,
                    estatus_prev AS estatus_b,
                    COUNT(*) AS num_retrocesos
                FROM transiciones_seq
                WHERE estatus_prev IS NOT NULL
                  AND orden_nuevo IS NOT NULL
                  AND orden_prev IS NOT NULL
                  AND orden_nuevo < orden_prev
                GROUP BY id_oportunidad, estatus_nuevo, estatus_prev
            )
            SELECT
                estatus_a || ' ↔ ' || estatus_b AS transicion,
                AVG(num_retrocesos::float) AS promedio_ciclos,
                MAX(num_retrocesos) AS maximo_ciclos,
                COUNT(DISTINCT id_oportunidad) AS oportunidades_afectadas
            FROM retrocesos_por_opp
            GROUP BY estatus_a, estatus_b
            ORDER BY promedio_ciclos DESC
        """

        try:
            rows = await conn.fetch(query, *params)
            return [
                MetricaCiclos(
                    transicion=row['transicion'],
                    promedio_ciclos=round(float(row['promedio_ciclos'] or 0), 1),
                    maximo_ciclos=int(row['maximo_ciclos'] or 0),
                    oportunidades_afectadas=int(row['oportunidades_afectadas'] or 0)
                )
                for row in rows
            ]
        except asyncpg.PostgresError as e:
            logger.error(f"Error de BD obteniendo análisis de ciclos: {e}")
            raise

    async def get_metricas_ciclo_revision(
        self,
        conn: asyncpg.Connection,
        fecha_inicio: date,
        fecha_fin: date,
        user_id: UUID = None,
        tipo_solicitud_id: int = None
    ) -> MetricaCicloRevision:
        """
        Mide el ciclo de revisión de Dirección y retrabajo de Simulación.

        - Tiempo de revisión: duración en 'En Revisión' (Dirección analiza).
        - Tiempo de retrabajo: duración en 'Comentarios Recibidos' (Simulación retrabaja).
        - Rondas: cuántas veces se regresó a 'En Revisión' desde 'Comentarios Recibidos'.
        """
        params: list = [fecha_inicio, fecha_fin]
        user_filter = ""
        tipo_filter = ""

        if user_id:
            params.append(user_id)
            user_filter = f"AND o.responsable_simulacion_id = ${len(params)}"

        if tipo_solicitud_id:
            params.append(tipo_solicitud_id)
            tipo_filter = f"AND o.id_tipo_solicitud = ${len(params)}"

        query = f"""
            WITH transiciones AS (
                SELECT
                    h.id_oportunidad,
                    e.orden,
                    e.es_estatus_final,
                    h.fecha_cambio_sla AS inicio,
                    LEAD(h.fecha_cambio_sla) OVER (
                        PARTITION BY h.id_oportunidad ORDER BY h.fecha_cambio_sla
                    ) AS fin,
                    LAG(e.orden) OVER (
                        PARTITION BY h.id_oportunidad ORDER BY h.fecha_cambio_sla
                    ) AS orden_anterior
                FROM tb_historial_estatus h
                JOIN tb_cat_estatus_oportunidades e ON h.id_estatus_nuevo = e.id
                JOIN tb_oportunidades o ON h.id_oportunidad = o.id_oportunidad
                WHERE (h.fecha_cambio_sla AT TIME ZONE 'America/Mexico_City')::date >= $1
                  AND (h.fecha_cambio_sla AT TIME ZONE 'America/Mexico_City')::date <= $2
                  {user_filter}
                  {tipo_filter}
            ),
            entregadas AS (
                -- orden=5: Entregado (cierre no-cancela y no-perdido del flujo de revisión)
                SELECT DISTINCT id_oportunidad FROM transiciones WHERE orden = 5 AND es_estatus_final = true
            ),
            tiempo_revision AS (
                -- orden=3: En Revisión
                SELECT id_oportunidad,
                       SUM(EXTRACT(EPOCH FROM (fin - inicio)) / 86400.0) AS dias
                FROM transiciones
                WHERE orden = 3 AND fin IS NOT NULL
                GROUP BY id_oportunidad
            ),
            tiempo_retrabajo AS (
                -- orden=4: Comentarios Recibidos
                SELECT id_oportunidad,
                       SUM(EXTRACT(EPOCH FROM (fin - inicio)) / 86400.0) AS dias
                FROM transiciones
                WHERE orden = 4 AND fin IS NOT NULL
                GROUP BY id_oportunidad
            ),
            rondas AS (
                -- Segunda ronda: volver a En Revisión (orden=3) desde Comentarios Recibidos (orden=4)
                SELECT id_oportunidad, COUNT(*) AS num_rondas
                FROM transiciones
                WHERE orden = 3 AND orden_anterior = 4
                GROUP BY id_oportunidad
            )
            SELECT
                COUNT(DISTINCT e.id_oportunidad) AS total_entregadas,
                COUNT(DISTINCT tr.id_oportunidad) AS con_revision,
                COALESCE(AVG(tr.dias), 0) AS tiempo_revision_dias,
                COALESCE(AVG(ret.dias), 0) AS tiempo_retrabajo_dias,
                COALESCE(AVG(r.num_rondas::float), 0) AS rondas_promedio
            FROM entregadas e
            LEFT JOIN tiempo_revision tr ON e.id_oportunidad = tr.id_oportunidad
            LEFT JOIN tiempo_retrabajo ret ON e.id_oportunidad = ret.id_oportunidad
            LEFT JOIN rondas r ON e.id_oportunidad = r.id_oportunidad
        """

        try:
            row = await conn.fetchrow(query, *params)
            total = int(row['total_entregadas'] or 0)
            con_rev = int(row['con_revision'] or 0)
            pct = round(con_rev * 100.0 / total, 1) if total > 0 else 0.0
            return MetricaCicloRevision(
                tiempo_revision_direccion_dias=round(float(row['tiempo_revision_dias'] or 0), 1),
                tiempo_retrabajo_simulacion_dias=round(float(row['tiempo_retrabajo_dias'] or 0), 1),
                oportunidades_con_revision=con_rev,
                total_entregadas=total,
                pct_con_revision=pct,
                rondas_promedio=round(float(row['rondas_promedio'] or 0), 1)
            )
        except asyncpg.PostgresError as e:
            logger.error(f"Error de BD obteniendo métricas de ciclo de revisión: {e}")
            raise

    async def get_oportunidades_por_estatus(
        self,
        conn: asyncpg.Connection,
        estatus_nombre: str,
        fecha_inicio: date,
        fecha_fin: date,
        user_id: UUID = None
    ) -> List[dict]:
        """
        Obtiene detalle de oportunidades en un estatus específico.
        LEAD() calculado antes de filtrar por fecha para no cortar intervalos.
        """
        params: list = [fecha_inicio, fecha_fin, estatus_nombre]
        user_filter = ""
        if user_id:
            params.append(user_id)
            user_filter = f"AND o.responsable_simulacion_id = ${len(params)}"

        query = f"""
            WITH todas_transiciones AS (
                SELECT
                    h.id_oportunidad,
                    h.fecha_cambio_sla as fecha_inicio_estatus,
                    LEAD(h.fecha_cambio_sla) OVER (
                        PARTITION BY h.id_oportunidad
                        ORDER BY h.fecha_cambio_sla
                    ) as fecha_fin_estatus
                FROM tb_historial_estatus h
                JOIN tb_cat_estatus_oportunidades e ON h.id_estatus_nuevo = e.id
                JOIN tb_oportunidades o ON h.id_oportunidad = o.id_oportunidad
                WHERE e.nombre = $3
                  AND (h.fecha_cambio_sla AT TIME ZONE 'America/Mexico_City')::date >= $1
                  AND (h.fecha_cambio_sla AT TIME ZONE 'America/Mexico_City')::date <= $2
                  {user_filter}
            ),
            peor_caso AS (
                SELECT DISTINCT ON (id_oportunidad)
                    id_oportunidad,
                    fecha_inicio_estatus,
                    fecha_fin_estatus
                FROM todas_transiciones
                ORDER BY id_oportunidad,
                         (COALESCE(fecha_fin_estatus, NOW()) - fecha_inicio_estatus) DESC
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
                COALESCE(
                    EXTRACT(EPOCH FROM (
                        COALESCE(pc.fecha_fin_estatus, NOW()) - pc.fecha_inicio_estatus
                    )) / 86400.0,
                    0
                ) as dias_en_estatus
            FROM peor_caso pc
            JOIN tb_oportunidades o ON pc.id_oportunidad = o.id_oportunidad
            LEFT JOIN tb_cat_tecnologias t ON o.id_tecnologia = t.id
            LEFT JOIN tb_cat_tipos_solicitud ts ON o.id_tipo_solicitud = ts.id
            LEFT JOIN tb_usuarios u_sim ON o.responsable_simulacion_id = u_sim.id_usuario
            LEFT JOIN tb_usuarios u_sol ON o.solicitado_por_id = u_sol.id_usuario
            ORDER BY dias_en_estatus DESC
            LIMIT 50
        """

        try:
            rows = await conn.fetch(query, *params)
            return [
                {
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
                }
                for row in rows
            ]
        except asyncpg.PostgresError as e:
            logger.error(f"Error de BD obteniendo oportunidades por estatus: {e}")
            raise

    async def get_transiciones_par_a_par(
        self,
        conn: asyncpg.Connection,
        user_id: UUID = None,
        tipo_solicitud_id: int = None
    ) -> List[MetricaTransicion]:
        """
        Estado actual del pipeline activo por par de transición.
        El orden del flujo proviene del catálogo (A.4), sin dict hardcodeado.
        """
        filters = [
            "o.id_estatus_global NOT IN ("
            "  SELECT id FROM tb_cat_estatus_oportunidades WHERE es_estatus_final = true"
            ")"
        ]
        params: list = []

        if user_id:
            params.append(user_id)
            filters.append(f"o.responsable_simulacion_id = ${len(params)}")

        if tipo_solicitud_id:
            params.append(tipo_solicitud_id)
            filters.append(f"o.id_tipo_solicitud = ${len(params)}")

        where_clause = " AND ".join(filters)

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
                COALESCE(e_ant.nombre, 'Inicio') AS estatus_origen,
                e_nuevo.nombre AS estatus_destino,
                COUNT(*) AS cantidad,
                AVG(
                    EXTRACT(EPOCH FROM (NOW() - ut.fecha_cambio_sla)) / 86400.0
                ) AS dias_promedio_en_destino,
                COALESCE(e_ant.orden, 0) AS orden_origen,
                COALESCE(e_nuevo.orden, 0) AS orden_destino
            FROM ultima_transicion ut
            LEFT JOIN tb_cat_estatus_oportunidades e_ant ON ut.id_estatus_anterior = e_ant.id
            JOIN tb_cat_estatus_oportunidades e_nuevo ON ut.id_estatus_nuevo = e_nuevo.id
            GROUP BY e_ant.nombre, e_nuevo.nombre, e_ant.orden, e_nuevo.orden
            ORDER BY cantidad DESC
        """

        try:
            rows = await conn.fetch(query, *params)
            return [
                MetricaTransicion(
                    estatus_origen=row['estatus_origen'] or 'Inicio',
                    estatus_destino=row['estatus_destino'],
                    cantidad=int(row['cantidad']),
                    dias_promedio_en_destino=round(float(row['dias_promedio_en_destino'] or 0), 1),
                    es_retroceso=(row['orden_destino'] or 0) < (row['orden_origen'] or 0)
                )
                for row in rows
            ]
        except asyncpg.PostgresError as e:
            logger.error(f"Error de BD obteniendo transiciones par a par: {e}")
            raise

    async def get_oportunidades_por_transicion(
        self,
        conn: asyncpg.Connection,
        estatus_origen: str,
        estatus_destino: str,
        user_id: UUID = None
    ) -> List[dict]:
        """Oportunidades cuya última transición fue de origen → destino."""
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
            LEFT JOIN tb_cat_estatus_oportunidades e_ant ON ut.id_estatus_anterior = e_ant.id
            JOIN tb_cat_estatus_oportunidades e_nuevo ON ut.id_estatus_nuevo = e_nuevo.id
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
            return [
                {
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
                }
                for row in rows
            ]
        except asyncpg.PostgresError as e:
            logger.error(f"Error de BD obteniendo oportunidades por transición: {e}")
            raise


# =============================================================================
# DEPENDENCY INJECTION
# =============================================================================

def get_metrics_service() -> MetricsService:
    return MetricsService()
