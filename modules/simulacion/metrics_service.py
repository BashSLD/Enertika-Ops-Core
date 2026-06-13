# modules/simulacion/metrics_service.py
"""Lógica de negocio (sin SQL) de las métricas operativas.

Los modelos viven en `metrics_models`; el acceso a datos en
`metrics_db_service.MetricsDBService`.
"""
from typing import List

from .metrics_models import MetricaEstatus, MetricaCuelloBotella


# =============================================================================
# SERVICE CLASS (lógica de negocio sin SQL)
# =============================================================================

class MetricsService:

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

        # Umbral heuristico tipo percentil-75 por nearest-rank (sin interpolacion).
        # No es un KPI: solo separa los estatus mas lentos como candidatos a cuello.
        # Con pocos estatus (p.ej. 4) el umbral coincide con el maximo.
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


# =============================================================================
# DEPENDENCY INJECTION
# =============================================================================

def get_metrics_service() -> MetricsService:
    return MetricsService()
