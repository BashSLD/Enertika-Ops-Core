# ==============================================================
# modules/levantamientos/db_service_analytics.py
# Queries de analytics/reportes para el módulo Levantamientos.
# Consumido por router_vistas.py (partials/graficas).
# ==============================================================

import logging
from typing import List

logger = logging.getLogger("Levantamientos.AnalyticsDBService")


class LevantamientosAnalyticsDBService:
    """
    Queries de agregación para las gráficas del módulo levantamientos.
    Separado de LevantamientosDBService para mantener responsabilidades claras.
    """

    async def get_distribucion_estatus(self, conn) -> List[dict]:
        """
        Conteo de levantamientos por estatus para gráfica de dona.
        Incluye todos los estados activos del módulo levantamientos.
        """
        rows = await conn.fetch("""
            SELECT
                est.nombre     AS estatus,
                est.color_hex  AS color,
                COUNT(*)       AS total
            FROM tb_levantamientos l
            INNER JOIN tb_oportunidades o ON l.id_oportunidad = o.id_oportunidad
            INNER JOIN tb_cat_estatus_levantamiento est ON l.id_estatus_global = est.id
            WHERE est.activo = TRUE
              AND o.email_enviado = true
            GROUP BY est.id, est.nombre, est.color_hex
            ORDER BY est.orden_kanban
        """)
        return [dict(r) for r in rows]

    async def get_carga_tecnicos(self, conn) -> List[dict]:
        """
        Conteo de levantamientos activos por técnico asignado para gráfica de barras.
        """
        rows = await conn.fetch("""
            SELECT
                u.nombre   AS tecnico,
                COUNT(*)   AS total
            FROM tb_levantamiento_asignaciones la
            INNER JOIN tb_usuarios u ON la.tecnico_id = u.id_usuario
            INNER JOIN tb_levantamientos l ON la.id_levantamiento = l.id_levantamiento
            INNER JOIN tb_oportunidades o ON l.id_oportunidad = o.id_oportunidad
            WHERE l.id_estatus_global IN (
                    SELECT id FROM tb_cat_estatus_levantamiento
                    WHERE grupo_kanban = 'activo' AND activo = TRUE
                )
              AND o.email_enviado = true
            GROUP BY u.id_usuario, u.nombre
            ORDER BY total DESC
            LIMIT 15
        """)
        return [dict(r) for r in rows]

    async def get_tendencia_semanal(self, conn) -> List[dict]:
        """
        Tendencia semanal de levantamientos creados vs completados/entregados.
        Últimas 12 semanas.
        """
        rows = await conn.fetch("""
            WITH semanas AS (
                SELECT generate_series(
                    date_trunc('week', NOW() AT TIME ZONE 'America/Mexico_City') - INTERVAL '11 weeks',
                    date_trunc('week', NOW() AT TIME ZONE 'America/Mexico_City'),
                    INTERVAL '1 week'
                ) AS semana
            ),
            creados AS (
                SELECT
                    date_trunc('week', l.created_at AT TIME ZONE 'America/Mexico_City') AS semana,
                    COUNT(*) AS total
                FROM tb_levantamientos l
                INNER JOIN tb_oportunidades o ON l.id_oportunidad = o.id_oportunidad
                WHERE l.created_at >= NOW() - INTERVAL '12 weeks'
                  AND o.email_enviado = true
                GROUP BY 1
            ),
            terminados AS (
                SELECT
                    date_trunc('week', lh.fecha_transicion AT TIME ZONE 'America/Mexico_City') AS semana,
                    COUNT(*) AS total
                FROM tb_levantamientos_historial lh
                INNER JOIN tb_levantamientos l ON lh.id_levantamiento = l.id_levantamiento
                INNER JOIN tb_oportunidades o ON l.id_oportunidad = o.id_oportunidad
                WHERE lh.id_estatus_nuevo IN (
                    SELECT id FROM tb_cat_estatus_levantamiento
                    WHERE grupo_kanban = 'terminado' AND activo = TRUE
                )
                  AND lh.fecha_transicion >= NOW() - INTERVAL '12 weeks'
                  AND o.email_enviado = true
                GROUP BY 1
            )
            SELECT
                to_char(s.semana, 'DD/MM') AS semana_label,
                COALESCE(c.total, 0)       AS creados,
                COALESCE(t.total, 0)       AS terminados
            FROM semanas s
            LEFT JOIN creados   c ON s.semana = c.semana
            LEFT JOIN terminados t ON s.semana = t.semana
            ORDER BY s.semana
        """)
        return [dict(r) for r in rows]

    async def get_tiempos_y_costos(self, conn) -> dict:
        """
        KPIs: tiempo promedio en cada estado y costo promedio de viáticos.
        """
        tiempos = await conn.fetch("""
            SELECT
                est.nombre AS estatus,
                ROUND(AVG(
                    EXTRACT(EPOCH FROM (NOW() - COALESCE(te.ultima_transicion, l.created_at))) / 3600
                )::numeric, 1) AS avg_horas
            FROM tb_levantamientos l
            INNER JOIN tb_oportunidades o ON l.id_oportunidad = o.id_oportunidad
            INNER JOIN tb_cat_estatus_levantamiento est ON l.id_estatus_global = est.id
            LEFT JOIN LATERAL (
                SELECT MAX(fecha_transicion) AS ultima_transicion
                FROM tb_levantamientos_historial
                WHERE id_levantamiento = l.id_levantamiento
                  AND id_estatus_nuevo = l.id_estatus_global
            ) te ON true
            WHERE est.activo = TRUE
              AND o.email_enviado = true
            GROUP BY est.id, est.nombre
            ORDER BY est.id
        """)

        avg_viaticos = await conn.fetchval("""
            SELECT ROUND(COALESCE(AVG(totales.monto_total), 0)::numeric, 2)
            FROM (
                SELECT id_levantamiento, SUM(monto) AS monto_total
                FROM tb_levantamiento_viaticos
                GROUP BY id_levantamiento
            ) totales
        """)

        total_levantamientos = await conn.fetchval("""
            SELECT COUNT(*) FROM tb_levantamientos l
            INNER JOIN tb_oportunidades o ON l.id_oportunidad = o.id_oportunidad
            INNER JOIN tb_cat_estatus_levantamiento est ON l.id_estatus_global = est.id
            WHERE est.activo = TRUE
              AND o.email_enviado = true
        """)

        return {
            "tiempos_por_estado": [
                {**dict(r), "avg_horas": float(r["avg_horas"] or 0)}
                for r in tiempos
            ],
            "avg_viaticos": float(avg_viaticos or 0),
            "total_levantamientos": int(total_levantamientos or 0),
        }


# --------------------------------------------------------------
# Singleton para inyección de dependencias
# --------------------------------------------------------------
_analytics_db_svc = LevantamientosAnalyticsDBService()


def get_analytics_db_service() -> LevantamientosAnalyticsDBService:
    return _analytics_db_svc
