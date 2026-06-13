# modules/simulacion/metrics_models.py
"""Modelos de datos (dataclasses) de las métricas operativas de Simulación.

Módulo neutral compartido por `metrics_db_service` (los construye desde SQL) y
`metrics_service` (lógica de negocio sin SQL). Evita un import service→db_service.
"""
from dataclasses import dataclass


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
