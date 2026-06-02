# modules/simulacion/report_models.py
"""
Dataclasses y helpers para el módulo de Reportes de Simulación.
Sin dependencias de DB, HTTP, ni infraestructura.
"""

from datetime import date
from typing import List, Dict, Optional, Any
from uuid import UUID
from dataclasses import dataclass, field

from .constants import (
    UMBRAL_MIN_ENTREGAS,
    UMBRAL_RATIO_LICITACIONES,
    PESO_CUMPLIMIENTO_COMPROMISO,
    PESO_CUMPLIMIENTO_INTERNO,
    PESO_VOLUMEN,
    MULTIPLICADOR_LICITACIONES,
    MULTIPLICADOR_ACTUALIZACIONES,
    PENALIZACION_RETRABAJOS,
    VOLUMEN_MAX_NORMALIZACION,
)
from core.config_service import UmbralesKPI

_MESES_ES = ['', 'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
             'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']

UMBRAL_VERDE = 90.0
UMBRAL_AMBAR = 85.0


# =============================================================================
# DATACLASSES PARA RESPUESTAS TIPADAS
# =============================================================================

@dataclass
class KPIMetricsMixin:
    """
    Mixin to centralize KPI percentage and semaphore logic.
    Expected attributes in consuming classes:
    - entregas_a_tiempo_interno: int
    - entregas_tarde_interno: int
    - entregas_a_tiempo_compromiso: int
    - entregas_tarde_compromiso: int
    - umbrales_interno: Optional[UmbralesKPI]
    - umbrales_compromiso: Optional[UmbralesKPI]
    """

    @property
    def porcentaje_a_tiempo_interno(self) -> float:
        """% entregas a tiempo según KPI Interno."""
        # Check for optional override (e.g., FilaContabilizacion)
        if hasattr(self, 'es_levantamiento') and self.es_levantamiento:
            return 0.0

        total_con_kpi = self.entregas_a_tiempo_interno + self.entregas_tarde_interno
        if total_con_kpi == 0:
            return 0.0
        return round((self.entregas_a_tiempo_interno / total_con_kpi) * 100, 1)

    @property
    def porcentaje_tarde_interno(self) -> float:
        """% entregas tarde según KPI Interno."""
        if hasattr(self, 'es_levantamiento') and self.es_levantamiento:
            return 0.0

        total_con_kpi = self.entregas_a_tiempo_interno + self.entregas_tarde_interno
        if total_con_kpi == 0:
            return 0.0
        return round((self.entregas_tarde_interno / total_con_kpi) * 100, 1)

    @property
    def porcentaje_a_tiempo_compromiso(self) -> float:
        """% entregas a tiempo según KPI Compromiso."""
        if hasattr(self, 'es_levantamiento') and self.es_levantamiento:
            return 0.0

        total_con_kpi = self.entregas_a_tiempo_compromiso + self.entregas_tarde_compromiso
        if total_con_kpi == 0:
            return 0.0
        return round((self.entregas_a_tiempo_compromiso / total_con_kpi) * 100, 1)

    @property
    def porcentaje_tarde_compromiso(self) -> float:
        """% entregas tarde según KPI Compromiso."""
        if hasattr(self, 'es_levantamiento') and self.es_levantamiento:
            return 0.0

        total_con_kpi = self.entregas_a_tiempo_compromiso + self.entregas_tarde_compromiso
        if total_con_kpi == 0:
            return 0.0
        return round((self.entregas_tarde_compromiso / total_con_kpi) * 100, 1)

    @property
    def semaforo_interno(self) -> str:
        if hasattr(self, 'es_levantamiento') and self.es_levantamiento:
            return "gray"

        pct = self.porcentaje_a_tiempo_interno
        if self.umbrales_interno:
            return self.umbrales_interno.get_color(pct)
        if pct >= UMBRAL_VERDE:
            return "green"
        elif pct >= UMBRAL_AMBAR:
            return "amber"
        return "red"

    @property
    def semaforo_compromiso(self) -> str:
        if hasattr(self, 'es_levantamiento') and self.es_levantamiento:
            return "gray"

        pct = self.porcentaje_a_tiempo_compromiso
        if self.umbrales_compromiso:
            return self.umbrales_compromiso.get_color(pct)
        if pct >= UMBRAL_VERDE:
            return "green"
        elif pct >= UMBRAL_AMBAR:
            return "amber"
        return "red"

@dataclass
class ConfiguracionScore:
    """Configuración dinámica para cálculo de scores"""
    umbral_min_entregas: int = UMBRAL_MIN_ENTREGAS
    umbral_ratio_licitaciones: float = UMBRAL_RATIO_LICITACIONES
    umbral_verde: float = UMBRAL_VERDE
    umbral_ambar: float = UMBRAL_AMBAR
    peso_compromiso: float = PESO_CUMPLIMIENTO_COMPROMISO
    peso_interno: float = PESO_CUMPLIMIENTO_INTERNO
    peso_volumen: float = PESO_VOLUMEN
    mult_licitaciones: float = MULTIPLICADOR_LICITACIONES
    mult_actualizaciones: float = MULTIPLICADOR_ACTUALIZACIONES
    penalizacion_retrabajos: float = PENALIZACION_RETRABAJOS
    volumen_max: int = VOLUMEN_MAX_NORMALIZACION
    umbral_carga_alta: float = 1.20


@dataclass
class MetricasGenerales(KPIMetricsMixin):
    """Métricas principales del dashboard con KPIs duales."""
    umbrales_interno: Optional[UmbralesKPI] = None
    umbrales_compromiso: Optional[UmbralesKPI] = None

    total_solicitudes: int = 0
    total_ofertas: int = 0
    en_espera: int = 0
    canceladas: int = 0
    no_viables: int = 0
    extraordinarias: int = 0

    versiones: int = 0
    retrabajos: int = 0

    licitaciones: int = 0

    total_sitios: int = 0
    total_sitios_entregados: int = 0
    oportunidades_multisitio: int = 0

    entregas_a_tiempo_interno: int = 0
    entregas_tarde_interno: int = 0

    entregas_a_tiempo_compromiso: int = 0
    entregas_tarde_compromiso: int = 0

    sin_fecha_entrega: int = 0
    tiempo_promedio_horas: Optional[float] = None
    ganadas: int = 0
    sim_adicionales_count: int = 0

    @property
    def tiempo_promedio_dias(self) -> Optional[float]:
        if self.tiempo_promedio_horas is None:
            return None
        return round(self.tiempo_promedio_horas / 24, 1)

    @property
    def porcentaje_licitaciones(self) -> float:
        if self.total_solicitudes == 0:
            return 0.0
        return round((self.licitaciones / self.total_solicitudes) * 100, 1)

    @property
    def promedio_sitios_por_oportunidad(self) -> float:
        if self.total_solicitudes == 0:
            return 0.0
        return round(self.total_sitios / self.total_solicitudes, 1)


@dataclass
class MetricaTecnologia(KPIMetricsMixin):
    """Métricas para una tecnología específica con KPIs duales."""
    id_tecnologia: int
    nombre: str

    umbrales_interno: Optional[UmbralesKPI] = None
    umbrales_compromiso: Optional[UmbralesKPI] = None

    total_solicitudes: int = 0
    total_ofertas: int = 0

    entregas_a_tiempo_interno: int = 0
    entregas_tarde_interno: int = 0

    entregas_a_tiempo_compromiso: int = 0
    entregas_tarde_compromiso: int = 0

    extraordinarias: int = 0
    versiones: int = 0
    retrabajados: int = 0
    licitaciones: int = 0
    tiempo_promedio_horas: Optional[float] = None
    potencia_total_kwp: float = 0.0
    capacidad_total_kwh: float = 0.0
    total_sitios: int = 0

    @property
    def porcentaje_licitaciones(self) -> float:
        if self.total_solicitudes == 0:
            return 0.0
        return round((self.licitaciones / self.total_solicitudes) * 100, 1)


@dataclass
class FilaContabilizacion(KPIMetricsMixin):
    """Fila de la tabla de contabilización con KPIs duales."""
    id_tipo_solicitud: int
    nombre: str
    codigo_interno: str

    umbrales_interno: Optional[UmbralesKPI] = None
    umbrales_compromiso: Optional[UmbralesKPI] = None

    total: int = 0

    entregas_a_tiempo_interno: int = 0
    entregas_tarde_interno: int = 0

    entregas_a_tiempo_compromiso: int = 0
    entregas_tarde_compromiso: int = 0

    @property
    def en_plazo_interno(self) -> int:
        return self.entregas_a_tiempo_interno

    @property
    def fuera_plazo_interno(self) -> int:
        return self.entregas_tarde_interno

    @property
    def en_plazo_compromiso(self) -> int:
        return self.entregas_a_tiempo_compromiso

    @property
    def fuera_plazo_compromiso(self) -> int:
        return self.entregas_tarde_compromiso

    sin_fecha: int = 0
    es_levantamiento: bool = False
    licitaciones: int = 0

    @property
    def semaforo_interno_label(self) -> str:
        if self.es_levantamiento:
            return "No aplica"
        pct = self.porcentaje_a_tiempo_interno
        if self.umbrales_interno:
            return self.umbrales_interno.get_label(pct)
        return f"{pct}%"

    @property
    def semaforo_compromiso_label(self) -> str:
        if self.es_levantamiento:
            return "No aplica"
        pct = self.porcentaje_a_tiempo_compromiso
        if self.umbrales_compromiso:
            return self.umbrales_compromiso.get_label(pct)
        return f"{pct}%"

    @property
    def porcentaje_licitaciones(self) -> float:
        if self.total == 0:
            return 0.0
        return round((self.licitaciones / self.total) * 100, 1)


@dataclass
class ResumenUsuario:
    """Datos estructurados para resumen de usuario"""
    nombre: str
    total_ofertas: int
    tecnologia_principal: Optional[Dict[str, Any]]
    porcentaje_interno: float
    porcentaje_compromiso: float
    tiempo_promedio_por_tipo: List[Dict[str, Any]]
    licitaciones: int
    porcentaje_licitaciones: float
    extraordinarias: int
    versiones: int

    tiempo_promedio_global_dias: float = None
    total_retrabajos: int = 0
    porcentaje_retrabajos: float = 0.0
    motivo_retrabajo_principal: str = None

    total_sitios: int = 0
    total_sitios_entregados: int = 0
    oportunidades_multisitio: int = 0
    promedio_sitios_por_oportunidad: float = 0.0


@dataclass
class DetalleUsuario:
    """Métricas detalladas por usuario responsable."""
    usuario_id: UUID
    nombre: str
    metricas_generales: MetricasGenerales = field(default_factory=MetricasGenerales)
    metricas_por_tecnologia: List[MetricaTecnologia] = field(default_factory=list)
    tabla_contabilizacion: List[FilaContabilizacion] = field(default_factory=list)
    tiempo_promedio_por_tipo: Dict[str, float] = field(default_factory=dict)
    resumen_texto: str = ""
    resumen_datos: Optional[ResumenUsuario] = None
    carga_alta: bool = False
    carga_pct_sobre_promedio: float = 0.0


@dataclass
class MetricaUsuario(KPIMetricsMixin):
    """Métricas individuales mejoradas para reporte de usuario."""
    usuario_id: UUID
    nombre: str
    total_solicitudes: int = 0
    total_ofertas: int = 0
    entregas_a_tiempo_compromiso: int = 0
    entregas_tarde_compromiso: int = 0
    entregas_a_tiempo_interno: int = 0
    entregas_tarde_interno: int = 0
    licitaciones: int = 0
    versiones: int = 0
    retrabajados: int = 0
    resumen_texto: str = ""
    tiempo_promedio_por_tipo: Dict[str, float] = field(default_factory=dict)
    score: Optional['ScoreUsuario'] = None

    total_sitios: int = 0
    total_sitios_entregados: int = 0
    oportunidades_multisitio: int = 0

    umbrales_interno: Optional[UmbralesKPI] = None
    umbrales_compromiso: Optional[UmbralesKPI] = None

    @property
    def promedio_sitios_por_oportunidad(self) -> float:
        if self.total_solicitudes == 0:
            return 0.0
        return round(self.total_sitios / self.total_solicitudes, 1)

    @property
    def porcentaje_licitaciones(self) -> float:
        if self.total_solicitudes == 0:
            return 0.0
        return round((self.licitaciones / self.total_solicitudes) * 100, 1)


@dataclass
class ScoreUsuario:
    """Score ponderado de desempeño del usuario.

    Capa 1 — Base (suma 100%): compromiso×0.50 + interno×0.25 + carga×0.25
    Capa 2 — Multiplicador: × (1 + licitaciones×0.20 + actualizaciones×0.10 + retrabajos×(-0.15))
    score_final = max(0, base × multiplicador)

    factor_volumen: normalización relativa al período (usuario con más entregas = 1.00).
    Métrica de carga = sitios entregados (total_ofertas; estatus 4,6,7; excl. cancelado).
    Distinto de total_solicitudes (oportunidades). Ver calcular_score_usuario().
    """

    cumplimiento_compromiso: float
    cumplimiento_interno: float
    factor_volumen: float

    ratio_licitaciones: float
    ratio_actualizaciones: float
    ratio_retrabajos: float

    score_base: float = 0.0
    multiplicador: float = 1.0
    score_final: float = 0.0

    entregas_total: int = 0
    licitaciones_total: int = 0
    actualizaciones_total: int = 0
    retrabajos_total: int = 0
    categoria: str = "evaluacion"
    motivo_retrabajo_principal: str = None
    config: Optional['ConfiguracionScore'] = field(default=None, repr=False)

    def calcular(self):
        cfg = self.config or ConfiguracionScore()

        self.score_base = (
            self.cumplimiento_compromiso * cfg.peso_compromiso +
            self.cumplimiento_interno * cfg.peso_interno +
            self.factor_volumen * cfg.peso_volumen
        )

        bonus_licitaciones = self.ratio_licitaciones * cfg.mult_licitaciones
        bonus_actualizaciones = self.ratio_actualizaciones * cfg.mult_actualizaciones
        penalizacion = self.ratio_retrabajos * cfg.penalizacion_retrabajos

        self.multiplicador = 1.0 + bonus_licitaciones + bonus_actualizaciones + penalizacion
        self.score_final = max(0.0, self.score_base * self.multiplicador)

        return self


@dataclass
class FilaMensual:
    """Fila del resumen mensual."""
    metrica: str
    valores: Dict[int, Any] = field(default_factory=dict)
    total: Any = 0


@dataclass
class DatosGrafica:
    """Datos estructurados para Chart.js."""
    tipo: str  # 'pie', 'bar', 'line', 'doughnut'
    labels: List[str] = field(default_factory=list)
    datasets: List[Dict] = field(default_factory=list)
    opciones: Dict = field(default_factory=dict)


@dataclass
class FiltrosReporte:
    """Filtros aplicables al reporte."""
    fecha_inicio: date
    fecha_fin: date
    id_tecnologia: Optional[int] = None
    id_tipo_solicitud: Optional[int] = None
    id_estatus: Optional[int] = None
    responsable_id: Optional[UUID] = None
    incluir_levantamientos_en_kpi: bool = False


@dataclass
class ResumenEjecutivo:
    """Datos estructurados para el resumen ejecutivo"""
    fecha_inicio_formatted: str
    fecha_fin_formatted: str

    total_solicitudes: int
    clasificadas: int
    en_espera: int
    total_ofertas: int

    top_tipos: List[Dict[str, Any]]

    porcentaje_cumplimiento_interno: float
    entregas_a_tiempo_interno: int
    total_entregas_interno: int

    porcentaje_cumplimiento_compromiso: float
    entregas_a_tiempo_compromiso: int
    total_entregas_compromiso: int

    mejor_usuario: Optional[Dict[str, Any]]

    licitaciones: int
    porcentaje_licitaciones: float
    extraordinarias: int
    porcentaje_extraordinarias: float
    versiones: int
    porcentaje_versiones: float

    total_retrabajos: int = 0
    porcentaje_retrabajos: float = 0.0
    motivo_retrabajo_principal: str = None
    conteo_motivo_principal: int = 0

    categorias_usuarios: Dict[str, List[MetricaUsuario]] = field(default_factory=dict)
    mostrar_nota_alta_complejidad: bool = False
    ratio_licitaciones_global: float = 0.0
    umbral_licitaciones_pct: float = 10.0

    sin_fecha_sistema: int = 0
    diferencia_explicacion: str = ""

    tecnologias_detalle: List[Dict[str, Any]] = field(default_factory=list)

    mejor_tecnologia: Optional[Dict[str, Any]] = None
    peor_tecnologia: Optional[Dict[str, Any]] = None

    mostrar_estacionalidad: bool = False
    mejor_mes: Optional[Dict[str, Any]] = None
    peor_mes: Optional[Dict[str, Any]] = None

    meses_en_rango: int = 0

    total_sitios_global: int = 0
    oportunidades_multisitio_global: int = 0

    ganadas: int = 0
    sim_adicionales_count: int = 0
    levantamiento_info: Optional[Dict[str, Any]] = None

    motivos_cierre: List[Dict[str, Any]] = field(default_factory=list)


# =============================================================================
# HELPERS
# =============================================================================

def categorizar_usuario(entregas: int, ratio_licitaciones: float, config: 'ConfiguracionScore' = None) -> str:
    cfg = config or ConfiguracionScore()
    if entregas < cfg.umbral_min_entregas:
        return "evaluacion"
    elif ratio_licitaciones >= cfg.umbral_ratio_licitaciones:
        return "alta_complejidad"
    return "eficiencia"


def calcular_score_usuario(
    usuario: MetricaUsuario,
    config: 'ConfiguracionScore' = None,
    volumen_referencia: int = 0,
) -> ScoreUsuario:
    # denom = max(referencia_período, piso_mínimo, 1) para normalización relativa de carga.
    cfg = config or ConfiguracionScore()

    cumplimiento_compromiso = usuario.porcentaje_a_tiempo_compromiso / 100.0
    cumplimiento_interno = usuario.porcentaje_a_tiempo_interno / 100.0
    denom = max(volumen_referencia, cfg.volumen_max, 1)
    factor_volumen = min(usuario.total_ofertas / denom, 1.0)

    ratio_licitaciones = usuario.licitaciones / usuario.total_solicitudes if usuario.total_solicitudes > 0 else 0.0
    ratio_actualizaciones = usuario.versiones / usuario.total_solicitudes if usuario.total_solicitudes > 0 else 0.0
    ratio_retrabajos = usuario.retrabajados / usuario.total_sitios if usuario.total_sitios > 0 else 0.0

    categoria = categorizar_usuario(usuario.total_ofertas, ratio_licitaciones, cfg)

    return ScoreUsuario(
        cumplimiento_compromiso=cumplimiento_compromiso,
        cumplimiento_interno=cumplimiento_interno,
        factor_volumen=factor_volumen,
        ratio_licitaciones=ratio_licitaciones,
        ratio_actualizaciones=ratio_actualizaciones,
        ratio_retrabajos=ratio_retrabajos,
        entregas_total=usuario.total_ofertas,
        licitaciones_total=usuario.licitaciones,
        actualizaciones_total=usuario.versiones,
        retrabajos_total=usuario.retrabajados,
        categoria=categoria,
        config=cfg,
    ).calcular()
