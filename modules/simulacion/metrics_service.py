# modules/simulacion/metrics_service.py
from dataclasses import dataclass
from typing import List
from uuid import UUID
from datetime import date
import asyncpg
import logging

from core.config_service import ConfigService

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


@dataclass
class MetricaComparativoSLA:
    """Compara el ciclo completo contra el ciclo sin tiempo en revision."""
    total_oportunidades: int
    tiempo_actual_promedio_dias: float
    tiempo_ajustado_promedio_dias: float
    tiempo_revision_descontado_dias: float
    reduccion_promedio_dias: float
    reduccion_pct: float
    descuento_sla_activo: bool


@dataclass
class MetricaCalidadRegistro:
    """Mide disciplina de captura entre fecha real y registro en sistema."""
    total_transiciones: int
    pct_registrado_a_tiempo: float
    lag_promedio_horas: float
    lag_p95_horas: float
    transiciones_tarde: int
    oportunidades_en_bloque: int
    rafagas_usuario: int
    max_oportunidades_por_rafaga: int
    transiciones_sin_usuario: int
    umbral_lag_horas: float
    ventana_bloque_min: int
    ventana_rafaga_min: int
    umbral_rafaga_usuario: int


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
        user_filter, tipo_filter = self._build_filters(params, user_id, tipo_solicitud_id)

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
                        ORDER BY h.fecha_cambio_sla, h.fecha_creacion, h.id
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

    def _build_filters(self, params: list, user_id=None, tipo_solicitud_id=None) -> tuple[str, str]:
        user_filter = ""
        tipo_filter = ""
        if user_id:
            params.append(user_id)
            user_filter = f"AND o.responsable_simulacion_id = ${len(params)}"
        if tipo_solicitud_id:
            params.append(tipo_solicitud_id)
            tipo_filter = f"AND o.id_tipo_solicitud = ${len(params)}"
        return user_filter, tipo_filter

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
        _, tipo_filter = self._build_filters(params, tipo_solicitud_id=tipo_solicitud_id)

        query = f"""
            WITH oportunidades_en_rango AS (
                SELECT DISTINCT h.id_oportunidad
                FROM tb_historial_estatus h
                JOIN tb_oportunidades o ON h.id_oportunidad = o.id_oportunidad
                WHERE (h.fecha_cambio_sla AT TIME ZONE 'America/Mexico_City')::date >= $1
                  AND (h.fecha_cambio_sla AT TIME ZONE 'America/Mexico_City')::date <= $2
                  {tipo_filter}
            ),
            transiciones_seq AS (
                SELECT
                    h.id_oportunidad,
                    e.nombre AS estatus_nuevo,
                    e.orden AS orden_nuevo,
                    e.es_estatus_final,
                    h.fecha_cambio_sla,
                    LAG(e.nombre) OVER (
                        PARTITION BY h.id_oportunidad ORDER BY h.fecha_cambio_sla, h.fecha_creacion, h.id
                    ) AS estatus_prev,
                    LAG(e.orden) OVER (
                        PARTITION BY h.id_oportunidad ORDER BY h.fecha_cambio_sla, h.fecha_creacion, h.id
                    ) AS orden_prev
                FROM tb_historial_estatus h
                JOIN tb_cat_estatus_oportunidades e ON h.id_estatus_nuevo = e.id
                WHERE h.id_oportunidad IN (SELECT id_oportunidad FROM oportunidades_en_rango)
            ),
            retrocesos_por_opp AS (
                SELECT
                    id_oportunidad,
                    estatus_nuevo AS estatus_a,
                    estatus_prev AS estatus_b,
                    COUNT(*) AS num_retrocesos
                FROM transiciones_seq
                WHERE estatus_prev IS NOT NULL
                  AND (fecha_cambio_sla AT TIME ZONE 'America/Mexico_City')::date >= $1
                  AND (fecha_cambio_sla AT TIME ZONE 'America/Mexico_City')::date <= $2
                  AND es_estatus_final = false
                  AND orden_nuevo IS NOT NULL
                  AND orden_prev IS NOT NULL
                  AND orden_nuevo BETWEEN 1 AND 4
                  AND orden_prev BETWEEN 1 AND 4
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
        user_filter, tipo_filter = self._build_filters(params, user_id, tipo_solicitud_id)

        query = f"""
            WITH oportunidades_entregadas AS (
                SELECT DISTINCT h.id_oportunidad
                FROM tb_historial_estatus h
                JOIN tb_cat_estatus_oportunidades e ON h.id_estatus_nuevo = e.id
                JOIN tb_oportunidades o ON h.id_oportunidad = o.id_oportunidad
                WHERE (h.fecha_cambio_sla AT TIME ZONE 'America/Mexico_City')::date >= $1
                  AND (h.fecha_cambio_sla AT TIME ZONE 'America/Mexico_City')::date <= $2
                  AND e.orden = 5
                  AND e.es_estatus_final = true
                  {user_filter}
                  {tipo_filter}
            ),
            transiciones AS (
                SELECT
                    h.id_oportunidad,
                    e.orden,
                    e.es_estatus_final,
                    h.fecha_cambio_sla AS inicio,
                    LEAD(h.fecha_cambio_sla) OVER (
                        PARTITION BY h.id_oportunidad ORDER BY h.fecha_cambio_sla, h.fecha_creacion, h.id
                    ) AS fin,
                    LAG(e.orden) OVER (
                        PARTITION BY h.id_oportunidad ORDER BY h.fecha_cambio_sla, h.fecha_creacion, h.id
                    ) AS orden_anterior
                FROM tb_historial_estatus h
                JOIN tb_cat_estatus_oportunidades e ON h.id_estatus_nuevo = e.id
                WHERE h.id_oportunidad IN (SELECT id_oportunidad FROM oportunidades_entregadas)
            ),
            entregadas AS (
                -- orden=5: Entregado (cierre no-cancela y no-perdido del flujo de revisión)
                SELECT DISTINCT id_oportunidad
                FROM transiciones
                WHERE orden = 5
                  AND es_estatus_final = true
                  AND (inicio AT TIME ZONE 'America/Mexico_City')::date >= $1
                  AND (inicio AT TIME ZONE 'America/Mexico_City')::date <= $2
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

    async def get_comparativo_sla_ajustado(
        self,
        conn: asyncpg.Connection,
        fecha_inicio: date,
        fecha_fin: date,
        user_id: UUID = None,
        tipo_solicitud_id: int = None
    ) -> MetricaComparativoSLA:
        """
        Compara el SLA actual contra una lectura ajustada.

        El KPI oficial no se modifica: el ajuste descuenta el tiempo
        en el estatus de orden 3 antes de la entrega.
        """
        descuento_activo = await ConfigService.get_global_config(
            conn,
            "DESCONTAR_TIEMPO_REVISION_SLA",
            False,
            bool,
        )

        params: list = [fecha_inicio, fecha_fin]
        user_filter, tipo_filter = self._build_filters(params, user_id, tipo_solicitud_id)

        query = f"""
            WITH entregas_en_rango AS (
                SELECT DISTINCT ON (h.id_oportunidad)
                    h.id_oportunidad,
                    h.fecha_cambio_sla AS fecha_entrega_sla
                FROM tb_historial_estatus h
                JOIN tb_cat_estatus_oportunidades e ON h.id_estatus_nuevo = e.id
                JOIN tb_oportunidades o ON h.id_oportunidad = o.id_oportunidad
                WHERE (h.fecha_cambio_sla AT TIME ZONE 'America/Mexico_City')::date >= $1
                  AND (h.fecha_cambio_sla AT TIME ZONE 'America/Mexico_City')::date <= $2
                  AND e.orden = 5
                  AND e.es_estatus_final = true
                  AND o.fecha_solicitud IS NOT NULL
                  {user_filter}
                  {tipo_filter}
                ORDER BY h.id_oportunidad, h.fecha_cambio_sla DESC, h.fecha_creacion DESC, h.id DESC
            ),
            transiciones AS (
                SELECT
                    h.id_oportunidad,
                    e.orden,
                    h.fecha_cambio_sla AS inicio,
                    LEAD(h.fecha_cambio_sla) OVER (
                        PARTITION BY h.id_oportunidad
                        ORDER BY h.fecha_cambio_sla, h.fecha_creacion, h.id
                    ) AS fin
                FROM tb_historial_estatus h
                JOIN tb_cat_estatus_oportunidades e ON h.id_estatus_nuevo = e.id
                WHERE h.id_oportunidad IN (SELECT id_oportunidad FROM entregas_en_rango)
            ),
            tiempo_revision AS (
                SELECT
                    t.id_oportunidad,
                    SUM(
                        EXTRACT(EPOCH FROM (
                            LEAST(t.fin, er.fecha_entrega_sla) - t.inicio
                        )) / 86400.0
                    ) AS dias_revision
                FROM transiciones t
                JOIN entregas_en_rango er ON t.id_oportunidad = er.id_oportunidad
                WHERE t.orden = 3
                  AND t.fin IS NOT NULL
                  AND t.inicio < er.fecha_entrega_sla
                  AND t.fin > t.inicio
                GROUP BY t.id_oportunidad
            ),
            base AS (
                SELECT
                    o.id_oportunidad,
                    EXTRACT(EPOCH FROM (
                        COALESCE(o.fecha_entrega_simulacion, er.fecha_entrega_sla) - o.fecha_solicitud
                    )) / 86400.0 AS dias_actuales,
                    COALESCE(tr.dias_revision, 0) AS dias_revision
                FROM entregas_en_rango er
                JOIN tb_oportunidades o ON er.id_oportunidad = o.id_oportunidad
                LEFT JOIN tiempo_revision tr ON er.id_oportunidad = tr.id_oportunidad
                WHERE COALESCE(o.fecha_entrega_simulacion, er.fecha_entrega_sla) > o.fecha_solicitud
            )
            SELECT
                COUNT(*) AS total_oportunidades,
                COALESCE(AVG(dias_actuales), 0) AS dias_actuales_promedio,
                COALESCE(AVG(GREATEST(dias_actuales - dias_revision, 0)), 0) AS dias_ajustados_promedio,
                COALESCE(AVG(dias_revision), 0) AS dias_revision_promedio
            FROM base
        """

        try:
            row = await conn.fetchrow(query, *params)
            total = int(row["total_oportunidades"] or 0)
            actual = float(row["dias_actuales_promedio"] or 0)
            ajustado = float(row["dias_ajustados_promedio"] or 0)
            revision = float(row["dias_revision_promedio"] or 0)
            reduccion = max(actual - ajustado, 0)
            reduccion_pct = round(reduccion * 100.0 / actual, 1) if actual > 0 else 0.0

            return MetricaComparativoSLA(
                total_oportunidades=total,
                tiempo_actual_promedio_dias=round(actual, 1),
                tiempo_ajustado_promedio_dias=round(ajustado, 1),
                tiempo_revision_descontado_dias=round(revision, 1),
                reduccion_promedio_dias=round(reduccion, 1),
                reduccion_pct=reduccion_pct,
                descuento_sla_activo=bool(descuento_activo),
            )
        except asyncpg.PostgresError as e:
            logger.error(f"Error de BD obteniendo comparativo SLA ajustado: {e}")
            raise

    async def get_calidad_registro(
        self,
        conn: asyncpg.Connection,
        fecha_inicio: date,
        fecha_fin: date,
        user_id: UUID = None,
        tipo_solicitud_id: int = None
    ) -> MetricaCalidadRegistro:
        """
        Reporta calidad de captura usando fecha_creacion como verdad de sistema.

        - Lag de registro: fecha_creacion - fecha_cambio_real.
        - Registro en bloque: varias transiciones de una oportunidad capturadas en ventana corta.
        - Rafagas por usuario: muchas oportunidades distintas capturadas en cubetas cortas.
        """
        configs = await ConfigService.get_global_configs_bulk(conn, {
            "UMBRAL_LAG_NOTIFICACION": (1440, int),
            "VENTANA_BLOQUE_REGISTRO_MIN": (2, int),
            "VENTANA_RAFAGA_USUARIO_MIN": (10, int),
            "UMBRAL_RAFAGA_USUARIO_OPS": (10, int),
        })
        umbral_lag_min = configs["UMBRAL_LAG_NOTIFICACION"]
        ventana_bloque_min = configs["VENTANA_BLOQUE_REGISTRO_MIN"]
        ventana_rafaga_min = configs["VENTANA_RAFAGA_USUARIO_MIN"]
        umbral_rafaga_usuario = configs["UMBRAL_RAFAGA_USUARIO_OPS"]

        params: list = [
            fecha_inicio,
            fecha_fin,
            umbral_lag_min,
            ventana_bloque_min,
            ventana_rafaga_min,
            umbral_rafaga_usuario,
        ]
        user_filter, tipo_filter = self._build_filters(params, user_id, tipo_solicitud_id)

        query = f"""
            WITH base AS (
                SELECT
                    h.id,
                    h.id_oportunidad,
                    h.cambiado_por_id,
                    h.fecha_creacion,
                    h.fecha_cambio_real,
                    GREATEST(
                        EXTRACT(EPOCH FROM (h.fecha_creacion - h.fecha_cambio_real)) / 60.0,
                        0
                    ) AS lag_minutos
                FROM tb_historial_estatus h
                JOIN tb_oportunidades o ON h.id_oportunidad = o.id_oportunidad
                WHERE (h.fecha_creacion AT TIME ZONE 'America/Mexico_City')::date >= $1
                  AND (h.fecha_creacion AT TIME ZONE 'America/Mexico_City')::date <= $2
                  {user_filter}
                  {tipo_filter}
            ),
            resumen AS (
                SELECT
                    COUNT(*) AS total_transiciones,
                    COUNT(*) FILTER (WHERE lag_minutos <= $3) AS transiciones_a_tiempo,
                    COUNT(*) FILTER (WHERE lag_minutos > $3) AS transiciones_tarde,
                    COUNT(*) FILTER (WHERE cambiado_por_id IS NULL) AS transiciones_sin_usuario,
                    COALESCE(AVG(lag_minutos), 0) AS lag_promedio_min,
                    COALESCE(
                        percentile_cont(0.95) WITHIN GROUP (ORDER BY lag_minutos),
                        0
                    ) AS lag_p95_min
                FROM base
            ),
            bloque AS (
                SELECT COUNT(*) AS oportunidades_en_bloque
                FROM (
                    SELECT id_oportunidad
                    FROM base
                    GROUP BY id_oportunidad
                    HAVING COUNT(*) >= 2
                       AND EXTRACT(EPOCH FROM (MAX(fecha_creacion) - MIN(fecha_creacion))) / 60.0 <= $4
                ) x
            ),
            rafagas AS (
                SELECT
                    COUNT(*) AS rafagas_usuario,
                    COALESCE(MAX(oportunidades), 0) AS max_oportunidades_por_rafaga
                FROM (
                    SELECT
                        cambiado_por_id,
                        FLOOR(EXTRACT(EPOCH FROM fecha_creacion) / ($5::int * 60)) AS bucket,
                        COUNT(DISTINCT id_oportunidad) AS oportunidades
                    FROM base
                    WHERE cambiado_por_id IS NOT NULL
                    GROUP BY cambiado_por_id, bucket
                    HAVING COUNT(DISTINCT id_oportunidad) >= $6
                ) y
            )
            SELECT
                r.total_transiciones,
                r.transiciones_a_tiempo,
                r.transiciones_tarde,
                r.transiciones_sin_usuario,
                r.lag_promedio_min,
                r.lag_p95_min,
                b.oportunidades_en_bloque,
                ra.rafagas_usuario,
                ra.max_oportunidades_por_rafaga
            FROM resumen r
            CROSS JOIN bloque b
            CROSS JOIN rafagas ra
        """

        try:
            row = await conn.fetchrow(query, *params)
            total = int(row["total_transiciones"] or 0)
            a_tiempo = int(row["transiciones_a_tiempo"] or 0)
            pct_a_tiempo = round(a_tiempo * 100.0 / total, 1) if total > 0 else 0.0

            return MetricaCalidadRegistro(
                total_transiciones=total,
                pct_registrado_a_tiempo=pct_a_tiempo,
                lag_promedio_horas=round(float(row["lag_promedio_min"] or 0) / 60.0, 1),
                lag_p95_horas=round(float(row["lag_p95_min"] or 0) / 60.0, 1),
                transiciones_tarde=int(row["transiciones_tarde"] or 0),
                oportunidades_en_bloque=int(row["oportunidades_en_bloque"] or 0),
                rafagas_usuario=int(row["rafagas_usuario"] or 0),
                max_oportunidades_por_rafaga=int(row["max_oportunidades_por_rafaga"] or 0),
                transiciones_sin_usuario=int(row["transiciones_sin_usuario"] or 0),
                umbral_lag_horas=round(float(umbral_lag_min) / 60.0, 1),
                ventana_bloque_min=int(ventana_bloque_min),
                ventana_rafaga_min=int(ventana_rafaga_min),
                umbral_rafaga_usuario=int(umbral_rafaga_usuario),
            )
        except asyncpg.PostgresError as e:
            logger.error(f"Error de BD obteniendo calidad de registro: {e}")
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
            WITH oportunidades_en_rango AS (
                SELECT DISTINCT h.id_oportunidad
                FROM tb_historial_estatus h
                JOIN tb_cat_estatus_oportunidades e ON h.id_estatus_nuevo = e.id
                JOIN tb_oportunidades o ON h.id_oportunidad = o.id_oportunidad
                WHERE e.nombre = $3
                  AND (h.fecha_cambio_sla AT TIME ZONE 'America/Mexico_City')::date >= $1
                  AND (h.fecha_cambio_sla AT TIME ZONE 'America/Mexico_City')::date <= $2
                  {user_filter}
            ),
            todas_transiciones AS (
                SELECT
                    h.id_oportunidad,
                    e.nombre AS estatus,
                    h.fecha_cambio_sla as fecha_inicio_estatus,
                    LEAD(h.fecha_cambio_sla) OVER (
                        PARTITION BY h.id_oportunidad
                        ORDER BY h.fecha_cambio_sla, h.fecha_creacion, h.id
                    ) as fecha_fin_estatus
                FROM tb_historial_estatus h
                JOIN tb_cat_estatus_oportunidades e ON h.id_estatus_nuevo = e.id
                WHERE h.id_oportunidad IN (SELECT id_oportunidad FROM oportunidades_en_rango)
            ),
            peor_caso AS (
                SELECT DISTINCT ON (id_oportunidad)
                    id_oportunidad,
                    fecha_inicio_estatus,
                    fecha_fin_estatus
                FROM todas_transiciones
                WHERE estatus = $3
                  AND (fecha_inicio_estatus AT TIME ZONE 'America/Mexico_City')::date >= $1
                  AND (fecha_inicio_estatus AT TIME ZONE 'America/Mexico_City')::date <= $2
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
            WITH historial_ordenado AS (
                SELECT
                    h.id_oportunidad,
                    e.nombre AS estatus_destino,
                    e.orden AS orden_destino,
                    h.fecha_cambio_sla,
                    h.fecha_creacion,
                    h.id,
                    LAG(e.nombre) OVER (
                        PARTITION BY h.id_oportunidad ORDER BY h.fecha_cambio_sla, h.fecha_creacion, h.id
                    ) AS estatus_origen,
                    LAG(e.orden) OVER (
                        PARTITION BY h.id_oportunidad ORDER BY h.fecha_cambio_sla, h.fecha_creacion, h.id
                    ) AS orden_origen
                FROM tb_historial_estatus h
                JOIN tb_cat_estatus_oportunidades e ON h.id_estatus_nuevo = e.id
            ),
            ultima_transicion AS (
                SELECT DISTINCT ON (ho.id_oportunidad)
                    ho.id_oportunidad,
                    ho.estatus_origen,
                    ho.estatus_destino,
                    ho.orden_origen,
                    ho.orden_destino,
                    ho.fecha_cambio_sla
                FROM historial_ordenado ho
                JOIN tb_oportunidades o ON ho.id_oportunidad = o.id_oportunidad
                WHERE {where_clause}
                  AND ho.estatus_origen IS NOT NULL
                ORDER BY ho.id_oportunidad, ho.fecha_cambio_sla DESC, ho.fecha_creacion DESC, ho.id DESC
            )
            SELECT
                COALESCE(ut.estatus_origen, 'Inicio') AS estatus_origen,
                ut.estatus_destino,
                COUNT(*) AS cantidad,
                AVG(
                    EXTRACT(EPOCH FROM (NOW() - ut.fecha_cambio_sla)) / 86400.0
                ) AS dias_promedio_en_destino,
                COALESCE(ut.orden_origen, 0) AS orden_origen,
                COALESCE(ut.orden_destino, 0) AS orden_destino
            FROM ultima_transicion ut
            GROUP BY ut.estatus_origen, ut.estatus_destino, ut.orden_origen, ut.orden_destino
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
            WITH historial_ordenado AS (
                SELECT
                    h.id_oportunidad,
                    e.nombre AS estatus_destino,
                    h.fecha_cambio_sla AS fecha_transicion,
                    h.fecha_creacion,
                    h.id,
                    LAG(e.nombre) OVER (
                        PARTITION BY h.id_oportunidad ORDER BY h.fecha_cambio_sla, h.fecha_creacion, h.id
                    ) AS estatus_origen
                FROM tb_historial_estatus h
                JOIN tb_cat_estatus_oportunidades e ON h.id_estatus_nuevo = e.id
            ),
            ultima_transicion AS (
                SELECT DISTINCT ON (id_oportunidad)
                    id_oportunidad,
                    estatus_origen,
                    estatus_destino,
                    fecha_transicion
                FROM historial_ordenado
                WHERE estatus_origen IS NOT NULL
                ORDER BY id_oportunidad, fecha_transicion DESC, fecha_creacion DESC, id DESC
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
            LEFT JOIN tb_cat_tecnologias t ON o.id_tecnologia = t.id
            LEFT JOIN tb_cat_tipos_solicitud ts ON o.id_tipo_solicitud = ts.id
            LEFT JOIN tb_usuarios u_sim ON o.responsable_simulacion_id = u_sim.id_usuario
            LEFT JOIN tb_usuarios u_sol ON o.solicitado_por_id = u_sol.id_usuario
            WHERE COALESCE(ut.estatus_origen, 'Inicio') = $1
              AND ut.estatus_destino = $2
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
