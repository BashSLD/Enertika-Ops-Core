# modules/simulacion/report_service.py
"""
Service Layer para Reportes de Simulación.

Responsabilidades:
- Queries SQL optimizados para métricas
- Cálculos de KPIs y agregaciones
- Lógica de semáforos y clasificaciones
- Preparación de datos para gráficas

NO contiene:
- Lógica HTTP (eso va en router.py)
- Renderizado de templates
- Manejo de requests/responses
"""

from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Any, Tuple
from uuid import UUID
from zoneinfo import ZoneInfo
from dataclasses import dataclass, field
from enum import Enum
import logging

from .constants import (
    UMBRAL_MIN_ENTREGAS,
    UMBRAL_RATIO_LICITACIONES,
    PESO_CUMPLIMIENTO_COMPROMISO,
    PESO_CUMPLIMIENTO_INTERNO,
    PESO_VOLUMEN,
    MULTIPLICADOR_LICITACIONES,
    MULTIPLICADOR_ACTUALIZACIONES,
    PENALIZACION_RETRABAJOS,
    VOLUMEN_MAX_NORMALIZACION
)

import logging
from core.config_service import ConfigService, UmbralesKPI

logger = logging.getLogger("ReportesSimulacion")


# =============================================================================
# CONSTANTES
# =============================================================================

# Umbrales para semáforo
# Umbrales por defecto (fallback)
UMBRAL_VERDE = 90.0
UMBRAL_AMBAR = 85.0
# < 85% = Rojo


# =============================================================================
# DATACLASSES PARA RESPUESTAS TIPADAS
# =============================================================================

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


@dataclass
class MetricasGenerales:
    """Métricas principales del dashboard con KPIs duales."""
    # Configuración dinámica
    umbrales_interno: Optional[UmbralesKPI] = None
    umbrales_compromiso: Optional[UmbralesKPI] = None

    total_solicitudes: int = 0
    total_ofertas: int = 0
    en_espera: int = 0
    canceladas: int = 0
    no_viables: int = 0
    extraordinarias: int = 0
    
    # SEPARACIÓN: Versiones vs Retrabajos
    versiones: int = 0          # parent_id IS NOT NULL
    retrabajos: int = 0         # es_retrabajo=true en sitios
    
    licitaciones: int = 0
    
    # KPI INTERNO (SLA del Sistema)
    entregas_a_tiempo_interno: int = 0
    entregas_tarde_interno: int = 0
    
    # KPI COMPROMISO (SLA del Cliente)
    entregas_a_tiempo_compromiso: int = 0
    entregas_tarde_compromiso: int = 0
    
    # Compatibilidad legacy (mapea a compromiso)
    @property
    def entregas_a_tiempo(self) -> int:
        return self.entregas_a_tiempo_compromiso
    
    @property
    def entregas_tarde(self) -> int:
        return self.entregas_tarde_compromiso
    
    sin_fecha_entrega: int = 0
    tiempo_promedio_horas: Optional[float] = None
    
    # Properties para porcentajes KPI Interno
    @property
    def porcentaje_a_tiempo_interno(self) -> float:
        """% entregas a tiempo según KPI Interno."""
        total_con_kpi = self.entregas_a_tiempo_interno + self.entregas_tarde_interno
        if total_con_kpi == 0:
            return 0.0
        return round((self.entregas_a_tiempo_interno / total_con_kpi) * 100, 1)
    
    @property
    def porcentaje_tarde_interno(self) -> float:
        """% entregas tarde según KPI Interno."""
        total_con_kpi = self.entregas_a_tiempo_interno + self.entregas_tarde_interno
        if total_con_kpi == 0:
            return 0.0
        return round((self.entregas_tarde_interno / total_con_kpi) * 100, 1)
    
    # Properties para porcentajes KPI Compromiso
    @property
    def porcentaje_a_tiempo_compromiso(self) -> float:
        """% entregas a tiempo según KPI Compromiso."""
        total_con_kpi = self.entregas_a_tiempo_compromiso + self.entregas_tarde_compromiso
        if total_con_kpi == 0:
            return 0.0
        return round((self.entregas_a_tiempo_compromiso / total_con_kpi) * 100, 1)
    
    @property
    def porcentaje_tarde_compromiso(self) -> float:
        """% entregas tarde según KPI Compromiso."""
        total_con_kpi = self.entregas_a_tiempo_compromiso + self.entregas_tarde_compromiso
        if total_con_kpi == 0:
            return 0.0
        return round((self.entregas_tarde_compromiso / total_con_kpi) * 100, 1)
    
    # Compatibilidad Legacy
    @property
    def porcentaje_a_tiempo(self) -> float:
        return self.porcentaje_a_tiempo_compromiso
    
    @property
    def porcentaje_tarde(self) -> float:
        return self.porcentaje_tarde_compromiso
    
    @property
    def semaforo_interno(self) -> str:
        pct = self.porcentaje_a_tiempo_interno
        if self.umbrales_interno:
            return self.umbrales_interno.get_color(pct)
        # Fallback
        if pct >= UMBRAL_VERDE:
            return "green"
        elif pct >= UMBRAL_AMBAR:
            return "amber"
        return "red"

    @property
    def semaforo_compromiso(self) -> str:
        pct = self.porcentaje_a_tiempo_compromiso
        if self.umbrales_compromiso:
            return self.umbrales_compromiso.get_color(pct)
        # Fallback
        if pct >= UMBRAL_VERDE:
            return "green"
        elif pct >= UMBRAL_AMBAR:
            return "amber"
        return "red"

    @property
    def tiempo_promedio_dias(self) -> Optional[float]:
        """Convierte horas a días para display."""
        if self.tiempo_promedio_horas is None:
            return None
        return round(self.tiempo_promedio_horas / 24, 1)
    
    @property
    def porcentaje_licitaciones(self) -> float:
        """% de solicitudes que son licitaciones."""
        if self.total_solicitudes == 0:
            return 0.0
        return round((self.licitaciones / self.total_solicitudes) * 100, 1)


@dataclass
class MetricaTecnologia:
    """Métricas para una tecnología específica con KPIs duales."""
    id_tecnologia: int
    nombre: str
    
    # Configuración dinámica
    umbrales_interno: Optional[UmbralesKPI] = None
    umbrales_compromiso: Optional[UmbralesKPI] = None

    total_solicitudes: int = 0
    total_ofertas: int = 0
    
    # KPI Interno
    entregas_a_tiempo_interno: int = 0
    entregas_tarde_interno: int = 0
    
    # KPI Compromiso
    entregas_a_tiempo_compromiso: int = 0
    entregas_tarde_compromiso: int = 0
    
    extraordinarias: int = 0
    versiones: int = 0
    retrabajados: int = 0
    licitaciones: int = 0  # ← Solicitudes que son licitaciones
    tiempo_promedio_horas: Optional[float] = None
    potencia_total_kwp: float = 0.0
    capacidad_total_kwh: float = 0.0
    
    # Compatibilidad legacy
    @property
    def entregas_a_tiempo(self) -> int:
        return self.entregas_a_tiempo_compromiso
    
    @property
    def entregas_tarde(self) -> int:
        return self.entregas_tarde_compromiso
    
    @property
    def porcentaje_a_tiempo(self) -> float:
        return self.porcentaje_a_tiempo_compromiso
        
    @property
    def porcentaje_tarde(self) -> float:
        return self.porcentaje_tarde_compromiso
    
    # Properties KPI Interno
    @property
    def porcentaje_a_tiempo_interno(self) -> float:
        total_con_kpi = self.entregas_a_tiempo_interno + self.entregas_tarde_interno
        if total_con_kpi == 0:
            return 0.0
        return round((self.entregas_a_tiempo_interno / total_con_kpi) * 100, 1)
    
    @property
    def porcentaje_tarde_interno(self) -> float:
        total_con_kpi = self.entregas_a_tiempo_interno + self.entregas_tarde_interno
        if total_con_kpi == 0:
            return 0.0
        return round((self.entregas_tarde_interno / total_con_kpi) * 100, 1)
    
    # Properties KPI Compromiso
    @property
    def porcentaje_a_tiempo_compromiso(self) -> float:
        total_con_kpi = self.entregas_a_tiempo_compromiso + self.entregas_tarde_compromiso
        if total_con_kpi == 0:
            return 0.0
        return round((self.entregas_a_tiempo_compromiso / total_con_kpi) * 100, 1)
    
    @property
    def porcentaje_tarde_compromiso(self) -> float:
        total_con_kpi = self.entregas_a_tiempo_compromiso + self.entregas_tarde_compromiso
        if total_con_kpi == 0:
            return 0.0
        return round((self.entregas_tarde_compromiso / total_con_kpi) * 100, 1)
    
    @property
    def porcentaje_licitaciones(self) -> float:
        """% de solicitudes que son licitaciones."""
        if self.total_solicitudes == 0:
            return 0.0
        return round((self.licitaciones / self.total_solicitudes) * 100, 1)

    @property
    def semaforo_interno(self) -> str:
        pct = self.porcentaje_a_tiempo_interno
        if self.umbrales_interno:
            return self.umbrales_interno.get_color(pct)
        # Fallback
        if pct >= UMBRAL_VERDE:
            return "green"
        elif pct >= UMBRAL_AMBAR:
            return "amber"
        return "red"

    @property
    def semaforo_compromiso(self) -> str:
        pct = self.porcentaje_a_tiempo_compromiso
        if self.umbrales_compromiso:
            return self.umbrales_compromiso.get_color(pct)
        # Fallback
        if pct >= UMBRAL_VERDE:
            return "green"
        elif pct >= UMBRAL_AMBAR:
            return "amber"
        return "red"



@dataclass
class FilaContabilizacion:
    """Fila de la tabla de contabilización con KPIs duales."""
    id_tipo_solicitud: int
    nombre: str
    codigo_interno: str

    # Configuración dinámica
    umbrales_interno: Optional[UmbralesKPI] = None
    umbrales_compromiso: Optional[UmbralesKPI] = None

    total: int = 0
    
    # KPI Interno
    en_plazo_interno: int = 0
    fuera_plazo_interno: int = 0
    
    # KPI Compromiso
    en_plazo_compromiso: int = 0
    fuera_plazo_compromiso: int = 0
    
    # Compatibilidad Legacy (apunta a compromiso)
    @property
    def en_plazo(self) -> int:
        return self.en_plazo_compromiso
        
    @property
    def fuera_plazo(self) -> int:
        return self.fuera_plazo_compromiso
    
    sin_fecha: int = 0
    es_levantamiento: bool = False
    licitaciones: int = 0  # ← Solicitudes que son licitaciones
    
    # Properties KPI Interno
    @property
    def porcentaje_en_plazo_interno(self) -> float:
        if self.es_levantamiento:
            return 0.0
        total_con_kpi = self.en_plazo_interno + self.fuera_plazo_interno
        if total_con_kpi == 0:
            return 0.0
        return round((self.en_plazo_interno / total_con_kpi) * 100, 1)
    
    @property
    def semaforo_interno(self) -> str:
        if self.es_levantamiento:
            return "gray"
        pct = self.porcentaje_en_plazo_interno
        
        # Usar config dinámica si existe
        if self.umbrales_interno:
            return self.umbrales_interno.get_color(pct)
            
        # Fallback
        if pct >= UMBRAL_VERDE:
            return "green"
        elif pct >= UMBRAL_AMBAR:
            return "amber"
        return "red"

    @property
    def semaforo_interno_label(self) -> str:
        if self.es_levantamiento:
            return "No aplica"
        pct = self.porcentaje_en_plazo_interno
        if self.umbrales_interno:
            return self.umbrales_interno.get_label(pct)
        return f"{pct}%"
    
    # Properties KPI Compromiso
    @property
    def porcentaje_en_plazo_compromiso(self) -> float:
        if self.es_levantamiento:
            return 0.0
        total_con_kpi = self.en_plazo_compromiso + self.fuera_plazo_compromiso
        if total_con_kpi == 0:
            return 0.0
        return round((self.en_plazo_compromiso / total_con_kpi) * 100, 1)
    
    @property
    def semaforo_compromiso(self) -> str:
        if self.es_levantamiento:
            return "gray"
        pct = self.porcentaje_en_plazo_compromiso
        
        # Usar config dinámica si existe
        if self.umbrales_compromiso:
            return self.umbrales_compromiso.get_color(pct)
            
        # Fallback
        if pct >= UMBRAL_VERDE:
            return "green"
        elif pct >= UMBRAL_AMBAR:
            return "amber"
        return "red"
        
    @property
    def semaforo_compromiso_label(self) -> str:
        if self.es_levantamiento:
            return "No aplica"
        pct = self.porcentaje_en_plazo_compromiso
        if self.umbrales_compromiso:
            return self.umbrales_compromiso.get_label(pct)
        return f"{pct}%"
        
    # Compatibilidad Legacy
    @property
    def porcentaje_en_plazo(self) -> float:
        return self.porcentaje_en_plazo_compromiso
        
    @property
    def semaforo(self) -> str:
        return self.semaforo_compromiso
        
    @property
    def semaforo_label(self) -> str:
        return self.semaforo_compromiso_label
    
    @property
    def porcentaje_licitaciones(self) -> float:
        """% de solicitudes que son licitaciones."""
        if self.total == 0:
            return 0.0
        return round((self.licitaciones / self.total) * 100, 1)


@dataclass
class ResumenUsuario:
    """Datos estructurados para resumen de usuario"""
    nombre: str
    total_ofertas: int
    tecnologia_principal: Optional[Dict[str, Any]]  # {"nombre": "FV", "solicitudes": 30}
    porcentaje_interno: float
    porcentaje_compromiso: float
    tiempo_promedio_por_tipo: List[Dict[str, Any]]  # [{"tipo": "COTIZACIÓN", "dias": 3.5}, ...]
    licitaciones: int
    porcentaje_licitaciones: float
    extraordinarias: int
    versiones: int
    
    # Campos adicionales
    tiempo_promedio_global_dias: float = None
    total_retrabajos: int = 0
    porcentaje_retrabajos: float = 0.0
    motivo_retrabajo_principal: str = None


@dataclass
class DetalleUsuario:
    """Métricas detalladas por usuario responsable."""
    usuario_id: UUID
    nombre: str
    metricas_generales: MetricasGenerales = field(default_factory=MetricasGenerales)
    metricas_por_tecnologia: List[MetricaTecnologia] = field(default_factory=list)
    tabla_contabilizacion: List[FilaContabilizacion] = field(default_factory=list)
    tiempo_promedio_por_tipo: Dict[str, float] = field(default_factory=dict)  # tipo_solicitud -> días promedio
    resumen_texto: str = ""  # Legacy: Texto descriptivo (HTML string) - MANTENER por compatibilidad si es necesario
    resumen_datos: Optional[ResumenUsuario] = None  # Nuevo objeto estructurado


@dataclass
class MetricaUsuario:
    """Métricas individuales mejoradas para reporte de usuario."""
    usuario_id: UUID
    nombre: str
    total_solicitudes: int = 0
    total_ofertas: int = 0
    entregas_a_tiempo_compromiso: int = 0
    entregas_tarde_compromiso: int = 0
    entregas_a_tiempo_interno: int = 0
    entregas_tarde_interno: int = 0
    licitaciones: int = 0  # ← Solicitudes que son licitaciones
    versiones: int = 0  # ← Oportunidades con parent_id
    retrabajados: int = 0  # ← Sitios con es_retrabajo=true
    resumen_texto: str = ""  # ← Texto descriptivo para resumen desplegable
    tiempo_promedio_por_tipo: Dict[str, float] = field(default_factory=dict)  # ← tipo_solicitud -> horas promedio
    score: Optional['ScoreUsuario'] = None  # ← Score calculado
    
    @property
    def porcentaje_a_tiempo(self) -> float:
        """% entregas a tiempo según KPI Compromiso."""
        total_con_kpi = self.entregas_a_tiempo_compromiso + self.entregas_tarde_compromiso
        if total_con_kpi == 0:
            return 0.0
        return round((self.entregas_a_tiempo_compromiso / total_con_kpi) * 100, 1)
    
    @property
    def porcentaje_a_tiempo_compromiso(self) -> float:
        """% entregas a tiempo según KPI Compromiso (alias)."""
        return self.porcentaje_a_tiempo
    
    @property
    def porcentaje_a_tiempo_interno(self) -> float:
        """% entregas a tiempo según KPI Interno."""
        total_con_kpi = self.entregas_a_tiempo_interno + self.entregas_tarde_interno
        if total_con_kpi == 0:
            return 0.0
        return round((self.entregas_a_tiempo_interno / total_con_kpi) * 100, 1)
    
    @property
    def porcentaje_licitaciones(self) -> float:
        """% de solicitudes que son licitaciones."""
        if self.total_solicitudes == 0:
            return 0.0
        return round((self.licitaciones / self.total_solicitudes) * 100, 1)


@dataclass
class ScoreUsuario:
    """Score ponderado de desempeño del usuario"""
    
    # Componentes del score base
    cumplimiento_compromiso: float  # 0.0 - 1.0
    cumplimiento_interno: float     # 0.0 - 1.0
    factor_volumen: float           # 0.0 - 1.0
    
    # Componentes del multiplicador
    ratio_licitaciones: float       # 0.0 - 1.0
    ratio_actualizaciones: float    # 0.0 - 1.0
    ratio_retrabajos: float         # 0.0 - 1.0
    
    # Resultados
    score_base: float = 0.0         # 0.0 - 1.0
    multiplicador: float = 1.0      # 0.8 - 1.3 típico
    score_final: float = 0.0        # 0.0 - 1.0
    
    # Metadata
    entregas_total: int = 0
    licitaciones_total: int = 0
    actualizaciones_total: int = 0
    retrabajos_total: int = 0
    categoria: str = "evaluacion"
    motivo_retrabajo_principal: str = None
    config: Optional['ConfiguracionScore'] = field(default=None, repr=False)
    
    def calcular(self):
        """Calcula score base, multiplicador y score final con config dinámica"""
        
        cfg = self.config or ConfiguracionScore()

        # Score Base
        self.score_base = (
            self.cumplimiento_compromiso * cfg.peso_compromiso +
            self.cumplimiento_interno * cfg.peso_interno +
            self.factor_volumen * cfg.peso_volumen
        )
        
        # Multiplicador de Complejidad
        bonus_licitaciones = self.ratio_licitaciones * cfg.mult_licitaciones
        bonus_actualizaciones = self.ratio_actualizaciones * cfg.mult_actualizaciones
        penalizacion = self.ratio_retrabajos * cfg.penalizacion_retrabajos
        
        self.multiplicador = 1.0 + bonus_licitaciones + bonus_actualizaciones + penalizacion
        
        # Score Final
        self.score_final = self.score_base * self.multiplicador
        
        # Asegurar rango 0-1
        self.score_final = max(0.0, min(1.0, self.score_final))
        
        return self


def categorizar_usuario(entregas: int, ratio_licitaciones: float, config: 'ConfiguracionScore' = None) -> str:
    """
    Categoriza al usuario según sus entregas y ratio de licitaciones.
    """
    cfg = config or ConfiguracionScore()
    
    if entregas < cfg.umbral_min_entregas:
        return "evaluacion"
    elif ratio_licitaciones >= cfg.umbral_ratio_licitaciones:
        return "alta_complejidad"
    else:
        return "eficiencia"


def calcular_score_usuario(usuario: MetricaUsuario, config: 'ConfiguracionScore' = None) -> ScoreUsuario:
    """
    Calcula el score ponderado de un usuario con configuración dinámica.
    """
    cfg = config or ConfiguracionScore()
    
    # Componente 1: Cumplimientos (ya están como % en usuario, normalizar a 0-1)
    cumplimiento_compromiso = usuario.porcentaje_a_tiempo_compromiso / 100.0
    cumplimiento_interno = usuario.porcentaje_a_tiempo_interno / 100.0
    
    # Componente 2: Factor volumen (normalizado 0-1)
    # Usar config max volumen
    factor_volumen = min(usuario.total_ofertas / cfg.volumen_max, 1.0)
    
    # Componente 3: Ratios de complejidad
    ratio_licitaciones = usuario.licitaciones / usuario.total_solicitudes if usuario.total_solicitudes > 0 else 0.0
    ratio_actualizaciones = usuario.versiones / usuario.total_solicitudes if usuario.total_solicitudes > 0 else 0.0
    ratio_retrabajos = usuario.retrabajados / usuario.total_solicitudes if usuario.total_solicitudes > 0 else 0.0
    
    # Categorizar usuario
    categoria = categorizar_usuario(usuario.total_ofertas, ratio_licitaciones, cfg)
    
    # Crear y calcular score
    score = ScoreUsuario(
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
        config=cfg
    ).calcular()
    
    return score


@dataclass
class FilaMensual:
    """Fila del resumen mensual."""
    metrica: str
    valores: Dict[int, Any] = field(default_factory=dict)  # mes -> valor
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
    incluir_levantamientos_en_kpi: bool = False  # Por defecto NO


@dataclass
class ResumenEjecutivo:
    """Datos estructurados para el resumen ejecutivo"""
    # Fechas
    fecha_inicio_formatted: str
    fecha_fin_formatted: str
    
    # Solicitudes
    total_solicitudes: int
    total_ofertas: int
    
    # Top tipos
    top_tipos: List[Dict[str, Any]]  # [{"nombre": "COTIZACIÓN", "total": 150, "porcentaje": 39.0}, ...]
    
    # KPIs
    porcentaje_cumplimiento_interno: float
    entregas_a_tiempo_interno: int
    total_entregas_interno: int
    
    porcentaje_cumplimiento_compromiso: float
    entregas_a_tiempo_compromiso: int
    total_entregas_compromiso: int
    
    # Mejor usuario
    mejor_usuario: Optional[Dict[str, Any]]  # {"nombre": "Juan", "ofertas": 45, ...}
    
    # Métricas adicionales
    licitaciones: int
    porcentaje_licitaciones: float
    extraordinarias: int
    porcentaje_extraordinarias: float
    versiones: int
    porcentaje_versiones: float
    
    # Retrabajos
    total_retrabajos: int = 0
    porcentaje_retrabajos: float = 0.0
    motivo_retrabajo_principal: str = None
    conteo_motivo_principal: int = 0
    
    # Categorías de usuarios por desempeño
    categorias_usuarios: Dict[str, List[MetricaUsuario]] = field(default_factory=dict)
    mostrar_nota_alta_complejidad: bool = False
    ratio_licitaciones_global: float = 0.0
    umbral_licitaciones_pct: float = 10.0  # Default 10%





# =============================================================================
# SERVICE CLASS
# =============================================================================

class ReportesSimulacionService:
    """
    Servicio para generación de reportes analíticos de Simulación.
    
    Principios:
    - Queries optimizados con CTEs
    - Cálculos centralizados
    - Tipado estricto con dataclasses
    - Sin lógica HTTP
    """
    
    def __init__(self):
        self.zona_mx = ZoneInfo("America/Mexico_City")
    
    # =========================================================================
    # MÉTODOS AUXILIARES
    # =========================================================================
    
    def get_current_datetime_mx(self) -> datetime:
        """Obtiene hora actual en México."""
        return datetime.now(self.zona_mx)
        
    async def _get_score_config(self, conn) -> ConfiguracionScore:
        """Obtiene configuración de scoring desde DB o defaults"""
        return ConfiguracionScore(
            umbral_min_entregas=await ConfigService.get_global_config(conn, "sim_umbral_min_entregas", UMBRAL_MIN_ENTREGAS, int),
            umbral_ratio_licitaciones=await ConfigService.get_global_config(conn, "sim_umbral_ratio_licitaciones", UMBRAL_RATIO_LICITACIONES, float),
            peso_compromiso=await ConfigService.get_global_config(conn, "sim_peso_compromiso", PESO_CUMPLIMIENTO_COMPROMISO, float),
            peso_interno=await ConfigService.get_global_config(conn, "sim_peso_interno", PESO_CUMPLIMIENTO_INTERNO, float),
            peso_volumen=await ConfigService.get_global_config(conn, "sim_peso_volumen", PESO_VOLUMEN, float),
            mult_licitaciones=await ConfigService.get_global_config(conn, "sim_mult_licitaciones", MULTIPLICADOR_LICITACIONES, float),
            mult_actualizaciones=await ConfigService.get_global_config(conn, "sim_mult_actualizaciones", MULTIPLICADOR_ACTUALIZACIONES, float),
            penalizacion_retrabajos=await ConfigService.get_global_config(conn, "sim_penalizacion_retrabajos", PENALIZACION_RETRABAJOS, float),
            volumen_max=await ConfigService.get_global_config(conn, "sim_volumen_max", VOLUMEN_MAX_NORMALIZACION, int),
            umbral_verde=await ConfigService.get_global_config(conn, "sim_umbral_verde", UMBRAL_VERDE, float),
            umbral_ambar=await ConfigService.get_global_config(conn, "sim_umbral_ambar", UMBRAL_AMBAR, float)
        )
    
    def _build_where_clause(self, filtros: FiltrosReporte, param_offset: int = 0) -> Tuple[str, List]:
        """
        Construye cláusula WHERE dinámica con parámetros posicionales.
        
        Returns:
            Tuple[str, List]: (where_clause, params)
        """
        conditions = [
            "e.modulo_aplicable = 'SIMULACION'",
            f"o.fecha_solicitud >= ${param_offset + 1}::timestamptz",
            f"o.fecha_solicitud < ${param_offset + 2}::timestamptz + INTERVAL '1 day'"
        ]
        params = [filtros.fecha_inicio, filtros.fecha_fin]
        
        if filtros.id_tecnologia:
            conditions.append(f"o.id_tecnologia = ${param_offset + len(params) + 1}")
            params.append(filtros.id_tecnologia)
        
        if filtros.id_tipo_solicitud:
            conditions.append(f"o.id_tipo_solicitud = ${param_offset + len(params) + 1}")
            params.append(filtros.id_tipo_solicitud)
        
        if filtros.id_estatus:
            conditions.append(f"o.id_estatus_global = ${param_offset + len(params) + 1}")
            params.append(filtros.id_estatus)
        
        if filtros.responsable_id:
            conditions.append(f"o.responsable_simulacion_id = ${param_offset + len(params) + 1}")
            params.append(filtros.responsable_id)
        
        where_clause = " AND ".join(conditions)
        return f"WHERE {where_clause}", params
    
    async def _get_catalog_ids(self, conn) -> dict:
        """
        Carga IDs de catálogos dinámicamente desde BD con caché de 5 min.
        """
        import time
        
        if not hasattr(self.__class__, '_catalog_cache'):
            self.__class__._catalog_cache = None
            self.__class__._cache_timestamp = None
            self.__class__._CACHE_TTL_SECONDS = 300
        
        now = time.time()
        
        if (self.__class__._catalog_cache is not None and 
            self.__class__._cache_timestamp is not None and 
            (now - self.__class__._cache_timestamp) < self.__class__._CACHE_TTL_SECONDS):
            return self.__class__._catalog_cache
        
        estatus = await conn.fetch(
            "SELECT id, LOWER(nombre) as nombre FROM tb_cat_estatus_global WHERE activo = true"
        )
        tipos = await conn.fetch(
            "SELECT id, LOWER(codigo_interno) as codigo FROM tb_cat_tipos_solicitud WHERE activo = true"
        )
        
        result = {
            "estatus": {row['nombre']: row['id'] for row in estatus},
            "tipos": {row['codigo']: row['id'] for row in tipos}
        }
        
        self.__class__._catalog_cache = result
        self.__class__._cache_timestamp = now
        
        return result

    def calcular_semaforo(self, porcentaje: float, config: ConfiguracionScore = None) -> str:
        """Determina color del semáforo según porcentaje."""
        u_verde = config.umbral_verde if config else UMBRAL_VERDE
        u_ambar = config.umbral_ambar if config else UMBRAL_AMBAR
        
        if porcentaje >= u_verde:
            return "green"
        elif porcentaje >= u_ambar:
            return "amber"
        return "red"
    
    # =========================================================================
    # QUERIES PRINCIPALES
    # =========================================================================
    
    async def get_metricas_generales(self, conn, filtros: FiltrosReporte) -> MetricasGenerales:
        """
        Obtiene métricas agregadas principales CON KPIs DUALES.
        
        Query optimizado que:
        1. JOIN con tb_sitios_oportunidad para obtener KPIs a nivel sitio
        2. Calcula ambos KPIs (Interno + Compromiso)
        3. Separa Versiones (parent_id) de Retrabajos (es_retrabajo)
        """
        where_clause, params = self._build_where_clause(filtros)
        
        # IDs de catálogos dinámicos
        cats = await self._get_catalog_ids(conn)
        
        id_entregado = cats['estatus'].get('entregado')
        id_perdido = cats['estatus'].get('perdido')
        id_cancelado = cats['estatus'].get('cancelado')
        id_levantamiento = cats['tipos'].get('levantamiento')
        
        # IDs para estatus "en espera"
        id_pendiente = cats['estatus'].get('pendiente')
        id_en_proceso = cats['estatus'].get('en proceso')
        id_en_revision = cats['estatus'].get('en revisión')
        
        # Agregar parámetros adicionales
        params.extend([
            id_entregado, id_perdido, id_cancelado, id_levantamiento, 
            id_pendiente, id_en_proceso, id_en_revision
        ])
        
        # Calcular índices de parámetros
        idx_entregado = len(params) - 6
        idx_perdido = len(params) - 5
        idx_cancelado = len(params) - 4
        idx_levantamiento = len(params) - 3
        idx_pendiente = len(params) - 2
        idx_proceso = len(params) - 1
        idx_revision = len(params)
        
        query = f"""
            WITH sitios_kpis AS (
                -- Obtener KPIs de todos los sitios
                SELECT 
                    s.id_oportunidad,
                    s.id_sitio,
                    s.kpi_status_interno,
                    s.kpi_status_compromiso,
                    s.es_retrabajo,
                    o.parent_id,
                    o.clasificacion_solicitud,
                    o.es_licitacion,
                    o.id_tipo_solicitud,
                    o.id_estatus_global,
                    o.id_motivo_cierre,
                    o.tiempo_elaboracion_horas,
                    o.fecha_entrega_simulacion
                FROM tb_sitios_oportunidad s
                JOIN tb_oportunidades o ON s.id_oportunidad = o.id_oportunidad
                JOIN tb_cat_estatus_global e ON o.id_estatus_global = e.id
                {where_clause}
            )
            SELECT 
                -- Totales básicos (contar oportunidades únicas, no sitios)
                COUNT(DISTINCT id_oportunidad) as total_solicitudes,
                
                -- Ofertas generadas (Entregado + Perdido) - contar oportunidades
                COUNT(DISTINCT CASE 
                    WHEN id_estatus_global IN (${idx_entregado}, ${idx_perdido}) 
                    THEN id_oportunidad 
                END) as total_ofertas,
                
                -- En espera
                COUNT(DISTINCT CASE 
                    WHEN id_estatus_global IN (${idx_pendiente}, ${idx_proceso}, ${idx_revision})
                    THEN id_oportunidad 
                END) as en_espera,
                
                -- Canceladas
                COUNT(DISTINCT CASE 
                    WHEN id_estatus_global = ${idx_cancelado} 
                    THEN id_oportunidad 
                END) as canceladas,
                
                -- No viables (motivo técnico: IDs 1-8)
                COUNT(DISTINCT CASE 
                    WHEN id_estatus_global = ${idx_cancelado} 
                    AND id_motivo_cierre BETWEEN 1 AND 8
                    THEN id_oportunidad 
                END) as no_viables,
                
                -- Extraordinarias
                COUNT(DISTINCT CASE 
                    WHEN clasificacion_solicitud = 'EXTRAORDINARIO' 
                    THEN id_oportunidad 
                END) as extraordinarias,
                
                -- VERSIONES: Oportunidades con parent_id
                COUNT(DISTINCT CASE 
                    WHEN parent_id IS NOT NULL 
                    THEN id_oportunidad 
                END) as versiones,
                
                -- RETRABAJOS: SITIOS con es_retrabajo=true (NO CONTAR OPORTUNIDADES)
                COUNT(CASE 
                    WHEN es_retrabajo = TRUE 
                    THEN id_sitio 
                END) as retrabajos,
                
                -- Licitaciones
                COUNT(DISTINCT CASE 
                    WHEN es_licitacion = TRUE 
                    THEN id_oportunidad 
                END) as licitaciones,
                
                -- ============================================
                -- KPI INTERNO (SLA del Sistema)
                -- ============================================
                COUNT(CASE 
                    WHEN kpi_status_interno = 'Entrega a tiempo'
                    AND id_estatus_global IN (${idx_entregado}, ${idx_perdido})
                    AND id_tipo_solicitud != ${idx_levantamiento}
                    THEN id_sitio 
                END) as entregas_a_tiempo_interno,
                
                COUNT(CASE 
                    WHEN kpi_status_interno = 'Entrega tarde'
                    AND id_estatus_global IN (${idx_entregado}, ${idx_perdido})
                    AND id_tipo_solicitud != ${idx_levantamiento}
                    THEN id_sitio 
                END) as entregas_tarde_interno,
                
                -- ============================================
                -- KPI COMPROMISO (SLA del Cliente)
                -- ============================================
                COUNT(CASE 
                    WHEN kpi_status_compromiso = 'Entrega a tiempo'
                    AND id_estatus_global IN (${idx_entregado}, ${idx_perdido})
                    AND id_tipo_solicitud != ${idx_levantamiento}
                    THEN id_sitio 
                END) as entregas_a_tiempo_compromiso,
                
                COUNT(CASE 
                    WHEN kpi_status_compromiso = 'Entrega tarde'
                    AND id_estatus_global IN (${idx_entregado}, ${idx_perdido})
                    AND id_tipo_solicitud != ${idx_levantamiento}
                    THEN id_sitio 
                END) as entregas_tarde_compromiso,
                
                -- Sin fecha de entrega
                COUNT(DISTINCT CASE 
                    WHEN id_estatus_global IN (${idx_entregado}, ${idx_perdido})
                    AND fecha_entrega_simulacion IS NULL
                    THEN id_oportunidad 
                END) as sin_fecha_entrega,
                
                -- Tiempo promedio (de oportunidades, no sitios)
                AVG(CASE 
                    WHEN tiempo_elaboracion_horas IS NOT NULL
                    AND id_estatus_global IN (${idx_entregado}, ${idx_perdido})
                    THEN tiempo_elaboracion_horas 
                END) as tiempo_promedio_horas
                
            FROM sitios_kpis
        """
        
        row = await conn.fetchrow(query, *params)
        
        # Cargar umbrales dinámicos
        u_interno = await ConfigService.get_umbrales_kpi(conn, "kpi_interno")
        u_compromiso = await ConfigService.get_umbrales_kpi(conn, "kpi_compromiso")
        
        if not row:
            return MetricasGenerales(
                umbrales_interno=u_interno,
                umbrales_compromiso=u_compromiso
            )
        
        return MetricasGenerales(
            umbrales_interno=u_interno,
            umbrales_compromiso=u_compromiso,
            total_solicitudes=row['total_solicitudes'] or 0,
            total_ofertas=row['total_ofertas'] or 0,
            en_espera=row['en_espera'] or 0,
            canceladas=row['canceladas'] or 0,
            no_viables=row['no_viables'] or 0,
            extraordinarias=row['extraordinarias'] or 0,
            versiones=row['versiones'] or 0,
            retrabajos=row['retrabajos'] or 0,
            licitaciones=row['licitaciones'] or 0,
            entregas_a_tiempo_interno=row['entregas_a_tiempo_interno'] or 0,
            entregas_tarde_interno=row['entregas_tarde_interno'] or 0,
            entregas_a_tiempo_compromiso=row['entregas_a_tiempo_compromiso'] or 0,
            entregas_tarde_compromiso=row['entregas_tarde_compromiso'] or 0,
            sin_fecha_entrega=row['sin_fecha_entrega'] or 0,
            tiempo_promedio_horas=row['tiempo_promedio_horas']
        )
    
    async def get_motivo_retrabajo_principal(
        self, 
        conn, 
        filtros: FiltrosReporte,
        user_id: UUID = None
    ) -> tuple:
        """Obtiene el motivo de retrabajo más común"""
        where_clause, params = self._build_where_clause(filtros)
        
        if user_id:
            where_clause += f" AND o.responsable_simulacion_id = ${len(params) + 1}"
            params.append(user_id)
        
        query = f"""
            SELECT 
                mr.nombre as motivo,
                COUNT(*) as conteo
            FROM tb_sitios_oportunidad s
            JOIN tb_oportunidades o ON s.id_oportunidad = o.id_oportunidad
            JOIN tb_cat_estatus_global e ON o.id_estatus_global = e.id
            LEFT JOIN tb_cat_motivos_retrabajo mr ON s.id_motivo_retrabajo = mr.id
            {where_clause}
            AND s.es_retrabajo = TRUE
            AND s.id_motivo_retrabajo IS NOT NULL
            GROUP BY mr.nombre
            ORDER BY conteo DESC
            LIMIT 1
        """
        
        row = await conn.fetchrow(query, *params)
        
        if row:
            return row['motivo'], row['conteo']
        else:
            return None, 0
    
    async def get_tiempo_promedio_global_usuario(
        self, 
        conn, 
        user_id: UUID, 
        filtros: FiltrosReporte
    ) -> float:
        """Calcula tiempo promedio global del usuario"""
        where_clause, params = self._build_where_clause(filtros)
        
        where_clause += f" AND o.responsable_simulacion_id = ${len(params) + 1}"
        params.append(user_id)
        
        query = f"""
            WITH tiempos AS (
                SELECT tiempo_elaboracion_horas / 24 as dias
                FROM tb_oportunidades o
                JOIN tb_cat_estatus_global e ON o.id_estatus_global = e.id
                {where_clause}
                AND o.tiempo_elaboracion_horas IS NOT NULL
                AND o.id_estatus_global IN (
                    SELECT id FROM tb_cat_estatus_global 
                    WHERE LOWER(nombre) IN ('entregado', 'perdido')
                )
                AND o.id_tipo_solicitud != (
                    SELECT id FROM tb_cat_tipos_solicitud 
                    WHERE LOWER(nombre) = 'levantamiento'
                )
            )
            SELECT AVG(dias) as dias_promedio
            FROM tiempos
            WHERE dias <= (
                SELECT PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY dias) 
                FROM tiempos
            )
        """
        
        row = await conn.fetchrow(query, *params)
        return round(row['dias_promedio'], 1) if row and row['dias_promedio'] else None
    
    async def get_metricas_por_tecnologia(self, conn, filtros: FiltrosReporte) -> List[MetricaTecnologia]:
        """
        Obtiene métricas desglosadas por cada tecnología con KPIs duales.
        Usa CTE con join a tb_sitios_oportunidad para KPIs a nivel sitio.
        """
        where_clause, params = self._build_where_clause(filtros)
        
        # IDs de catálogos dinámicos
        cats = await self._get_catalog_ids(conn)
        
        id_entregado = cats['estatus'].get('entregado')
        id_perdido = cats['estatus'].get('perdido')
        id_levantamiento = cats['tipos'].get('levantamiento')
        
        params.extend([id_entregado, id_perdido, id_levantamiento])
        idx_entregado = len(params) - 2
        idx_perdido = len(params) - 1
        idx_levantamiento = len(params)
        
        query = f"""
            WITH sitios_tech AS (
                SELECT 
                    o.id_tecnologia,
                    s.id_oportunidad,
                    s.kpi_status_interno,
                    s.kpi_status_compromiso,
                    s.es_retrabajo,
                    o.parent_id,
                    o.clasificacion_solicitud,
                    o.es_licitacion,
                    o.id_estatus_global,
                    o.id_tipo_solicitud,
                    o.tiempo_elaboracion_horas,
                    o.potencia_cierre_fv_kwp,
                    o.capacidad_cierre_bess_kwh
                FROM tb_sitios_oportunidad s
                JOIN tb_oportunidades o ON s.id_oportunidad = o.id_oportunidad
                JOIN tb_cat_estatus_global e ON o.id_estatus_global = e.id
                {where_clause}
            )
            SELECT 
                t.id as id_tecnologia,
                t.nombre,
                
                -- Conteos a nivel oportunidad (DISTINCT)
                COUNT(DISTINCT st.id_oportunidad) as total_solicitudes,
                COUNT(DISTINCT st.id_oportunidad) FILTER (
                    WHERE st.id_estatus_global IN (${idx_entregado}, ${idx_perdido})
                ) as total_ofertas,
                
                -- KPIs DUALES a nivel sitio (COUNT sin DISTINCT)
                COUNT(*) FILTER (
                    WHERE st.kpi_status_interno = 'Entrega a tiempo'
                    AND st.id_estatus_global IN (${idx_entregado}, ${idx_perdido})
                    AND st.id_tipo_solicitud != ${idx_levantamiento}
                ) as entregas_a_tiempo_interno,
                
                COUNT(*) FILTER (
                    WHERE st.kpi_status_interno = 'Entrega tarde'
                    AND st.id_estatus_global IN (${idx_entregado}, ${idx_perdido})
                    AND st.id_tipo_solicitud != ${idx_levantamiento}
                ) as entregas_tarde_interno,
                
                COUNT(*) FILTER (
                    WHERE st.kpi_status_compromiso = 'Entrega a tiempo'
                    AND st.id_estatus_global IN (${idx_entregado}, ${idx_perdido})
                    AND st.id_tipo_solicitud != ${idx_levantamiento}
                ) as entregas_a_tiempo_compromiso,
                
                COUNT(*) FILTER (
                    WHERE st.kpi_status_compromiso = 'Entrega tarde'
                    AND st.id_estatus_global IN (${idx_entregado}, ${idx_perdido})
                    AND st.id_tipo_solicitud != ${idx_levantamiento}
                ) as entregas_tarde_compromiso,
                
                -- Clasificaciones
                COUNT(DISTINCT st.id_oportunidad) FILTER (
                    WHERE st.clasificacion_solicitud = 'EXTRAORDINARIO'
                ) as extraordinarias,
                
                COUNT(DISTINCT st.id_oportunidad) FILTER (
                    WHERE st.parent_id IS NOT NULL
                ) as versiones,
                
                COUNT(*) FILTER (
                    WHERE st.es_retrabajo = TRUE
                ) as retrabajos,
                
                -- Licitaciones
                COUNT(DISTINCT st.id_oportunidad) FILTER (
                    WHERE st.es_licitacion = TRUE
                ) as licitaciones,
                
                -- Agregados
                AVG(st.tiempo_elaboracion_horas) FILTER (
                    WHERE st.tiempo_elaboracion_horas IS NOT NULL
                ) as tiempo_promedio_horas,
                
                COALESCE(SUM(DISTINCT st.potencia_cierre_fv_kwp), 0) as potencia_total_kwp,
                COALESCE(SUM(DISTINCT st.capacidad_cierre_bess_kwh), 0) as capacidad_total_kwh
                
            FROM tb_cat_tecnologias t
            LEFT JOIN sitios_tech st ON st.id_tecnologia = t.id
            WHERE t.activo = true
            GROUP BY t.id, t.nombre
            ORDER BY t.id
        """
        
        rows = await conn.fetch(query, *params)
        
        # Cargar umbrales dinámicos
        u_interno = await ConfigService.get_umbrales_kpi(conn, "kpi_interno")
        u_compromiso = await ConfigService.get_umbrales_kpi(conn, "kpi_compromiso")

        return [
            MetricaTecnologia(
                id_tecnologia=row['id_tecnologia'],
                nombre=row['nombre'],
                umbrales_interno=u_interno,
                umbrales_compromiso=u_compromiso,
                total_solicitudes=row['total_solicitudes'] or 0,
                total_ofertas=row['total_ofertas'] or 0,
                entregas_a_tiempo_interno=row['entregas_a_tiempo_interno'] or 0,
                entregas_tarde_interno=row['entregas_tarde_interno'] or 0,
                entregas_a_tiempo_compromiso=row['entregas_a_tiempo_compromiso'] or 0,
                entregas_tarde_compromiso=row['entregas_tarde_compromiso'] or 0,
                extraordinarias=row['extraordinarias'] or 0,
                versiones=row['versiones'] or 0,
                retrabajados=row['retrabajos'] or 0,
                licitaciones=row['licitaciones'] or 0,
                tiempo_promedio_horas=float(row['tiempo_promedio_horas']) if row['tiempo_promedio_horas'] else None,
                potencia_total_kwp=float(row['potencia_total_kwp'] or 0),
                capacidad_total_kwh=float(row['capacidad_total_kwh'] or 0)
            )
            for row in rows
        ]
    
    async def get_tabla_contabilizacion(self, conn, filtros: FiltrosReporte) -> List[FilaContabilizacion]:
        """
        Genera la tabla de contabilización por tipo de solicitud con semáforos.
        """
        where_clause, params = self._build_where_clause(filtros)
        
        # IDs de catálogos dinámicos
        cats = await self._get_catalog_ids(conn)
        
        id_entregado = cats['estatus'].get('entregado')
        id_perdido = cats['estatus'].get('perdido')
        id_levantamiento = cats['tipos'].get('levantamiento')
        
        params.extend([id_entregado, id_perdido, id_levantamiento])
        idx_entregado = len(params) - 2
        idx_perdido = len(params) - 1
        idx_levantamiento = len(params)
        
        query = f"""
            SELECT 
                ts.id as id_tipo,
                ts.nombre,
                ts.codigo_interno,
                (ts.id = ${idx_levantamiento}) as es_levantamiento,
                
                -- Total de oportunidades
                COUNT(DISTINCT o.id_oportunidad) as total,
                
                -- KPI INTERNO (contar SITIOS)
                COUNT(CASE 
                    WHEN s.kpi_status_interno = 'Entrega a tiempo'
                    AND o.id_estatus_global IN (${idx_entregado}, ${idx_perdido})
                    THEN s.id_sitio 
                END) as en_plazo_interno,
                
                COUNT(CASE 
                    WHEN s.kpi_status_interno = 'Entrega tarde'
                    AND o.id_estatus_global IN (${idx_entregado}, ${idx_perdido})
                    THEN s.id_sitio 
                END) as fuera_plazo_interno,
                
                -- KPI COMPROMISO (contar SITIOS)
                COUNT(CASE 
                    WHEN s.kpi_status_compromiso = 'Entrega a tiempo'
                    AND o.id_estatus_global IN (${idx_entregado}, ${idx_perdido})
                    THEN s.id_sitio 
                END) as en_plazo_compromiso,
                
                COUNT(CASE 
                    WHEN s.kpi_status_compromiso = 'Entrega tarde'
                    AND o.id_estatus_global IN (${idx_entregado}, ${idx_perdido})
                    THEN s.id_sitio 
                END) as fuera_plazo_compromiso,
                
                -- Sin fecha
                COUNT(DISTINCT CASE 
                    WHEN o.id_estatus_global IN (${idx_entregado}, ${idx_perdido})
                    AND o.fecha_entrega_simulacion IS NULL
                    THEN o.id_oportunidad 
                END) as sin_fecha
                
            FROM tb_cat_tipos_solicitud ts
            LEFT JOIN tb_oportunidades o ON ts.id = o.id_tipo_solicitud 
                AND o.id_estatus_global >= 1 -- Simple placeholder, the CTE filters logic is in WHERE
            LEFT JOIN tb_sitios_oportunidad s ON o.id_oportunidad = s.id_oportunidad
            LEFT JOIN tb_cat_estatus_global e ON o.id_estatus_global = e.id
            {where_clause}
            GROUP BY ts.id, ts.nombre, ts.codigo_interno
            HAVING COUNT(DISTINCT o.id_oportunidad) > 0 OR ts.id IS NOT NULL
            ORDER BY ts.id
        """
        # Note: Previous query had slightly different logic with filtered_ops. 
        # To strictly follow instructions, I should use the one provided in the instructions file
        # which uses direct joins. Re-implementing strictly from instruction block.
        
        query = f"""
            SELECT 
                ts.id as id_tipo_solicitud,
                ts.nombre,
                ts.codigo_interno,
                
                COUNT(DISTINCT o.id_oportunidad) as total,
                
                -- KPI INTERNO
                COUNT(CASE 
                    WHEN s.kpi_status_interno = 'Entrega a tiempo'
                    AND o.id_estatus_global IN (${idx_entregado}, ${idx_perdido})
                    THEN s.id_sitio 
                END) as en_plazo_interno,
                
                COUNT(CASE 
                    WHEN s.kpi_status_interno = 'Entrega tarde'
                    AND o.id_estatus_global IN (${idx_entregado}, ${idx_perdido})
                    THEN s.id_sitio 
                END) as fuera_plazo_interno,
                
                -- KPI COMPROMISO
                COUNT(CASE 
                    WHEN s.kpi_status_compromiso = 'Entrega a tiempo'
                    AND o.id_estatus_global IN (${idx_entregado}, ${idx_perdido})
                    THEN s.id_sitio 
                END) as en_plazo_compromiso,
                
                COUNT(CASE 
                    WHEN s.kpi_status_compromiso = 'Entrega tarde'
                    AND o.id_estatus_global IN (${idx_entregado}, ${idx_perdido})
                    THEN s.id_sitio 
                END) as fuera_plazo_compromiso,
                
                -- Sin fecha
                COUNT(DISTINCT CASE 
                    WHEN o.id_estatus_global IN (${idx_entregado}, ${idx_perdido})
                    AND o.fecha_entrega_simulacion IS NULL
                    THEN o.id_oportunidad 
                END) as sin_fecha,
                
                -- Licitaciones
                COUNT(DISTINCT CASE 
                    WHEN o.es_licitacion = TRUE 
                    THEN o.id_oportunidad 
                END) as licitaciones,
                
                (ts.id = ${idx_levantamiento}) as es_levantamiento
                
            FROM tb_cat_tipos_solicitud ts
            LEFT JOIN tb_oportunidades o ON ts.id = o.id_tipo_solicitud
            LEFT JOIN tb_sitios_oportunidad s ON o.id_oportunidad = s.id_oportunidad
            LEFT JOIN tb_cat_estatus_global e ON o.id_estatus_global = e.id
            {where_clause}
            GROUP BY ts.id, ts.nombre, ts.codigo_interno
            HAVING COUNT(DISTINCT o.id_oportunidad) > 0
            ORDER BY ts.id
        """
        
        rows = await conn.fetch(query, *params)
        
        # Cargar umbrales dinámicos
        u_interno = await ConfigService.get_umbrales_kpi(conn, "kpi_interno")
        u_compromiso = await ConfigService.get_umbrales_kpi(conn, "kpi_compromiso")

        return [
            FilaContabilizacion(
                id_tipo_solicitud=row['id_tipo_solicitud'],
                nombre=row['nombre'],
                codigo_interno=row['codigo_interno'],
                umbrales_interno=u_interno,
                umbrales_compromiso=u_compromiso,
                total=row['total'] or 0,
                en_plazo_interno=row['en_plazo_interno'] or 0,
                fuera_plazo_interno=row['fuera_plazo_interno'] or 0,
                en_plazo_compromiso=row['en_plazo_compromiso'] or 0,
                fuera_plazo_compromiso=row['fuera_plazo_compromiso'] or 0,
                sin_fecha=row['sin_fecha'] or 0,
                licitaciones=row['licitaciones'] or 0,
                es_levantamiento=row['es_levantamiento'] or False
            )
            for row in rows
        ]
    
    async def get_detalle_por_usuario(self, conn, filtros: FiltrosReporte) -> List[DetalleUsuario]:
        """
        Obtiene métricas detalladas por cada usuario responsable.
        
        Incluye:
        - Métricas generales del usuario
        - Métricas por tecnología
        - Tabla de contabilización personal
        """
        # Primero obtener lista de usuarios con actividad en el período
        where_clause, base_params = self._build_where_clause(filtros)
        
        query_usuarios = f"""
            SELECT DISTINCT 
                u.id_usuario,
                u.nombre
            FROM tb_usuarios u
            INNER JOIN tb_oportunidades o ON o.responsable_simulacion_id = u.id_usuario
            INNER JOIN tb_cat_estatus_global e ON o.id_estatus_global = e.id
            {where_clause}
            ORDER BY u.nombre
        """
        
        usuarios = await conn.fetch(query_usuarios, *base_params)
        
        if not usuarios:
            return []
        
        resultados = []
        
        for usuario in usuarios:
            # Crear filtro específico para este usuario
            filtros_usuario = FiltrosReporte(
                fecha_inicio=filtros.fecha_inicio,
                fecha_fin=filtros.fecha_fin,
                id_tecnologia=filtros.id_tecnologia,
                id_tipo_solicitud=filtros.id_tipo_solicitud,
                id_estatus=filtros.id_estatus,
                responsable_id=usuario['id_usuario']
            )
            
            # Reutilizar métodos existentes con filtro de usuario
            metricas_gen = await self.get_metricas_generales(conn, filtros_usuario)
            metricas_tech = await self.get_metricas_por_tecnologia(conn, filtros_usuario)
            tabla_cont = await self.get_tabla_contabilizacion(conn, filtros_usuario)
            
            # Obtener tiempo promedio por tipo de solicitud
            tiempo_por_tipo = await self.get_tiempo_promedio_por_tipo(
                conn, usuario['id_usuario'], filtros
            )
            
            # Crear objeto DetalleUsuario primero (sin resumen)
            detalle_usuario = DetalleUsuario(
                usuario_id=usuario['id_usuario'],
                nombre=usuario['nombre'],
                metricas_generales=metricas_gen,
                metricas_por_tecnologia=metricas_tech,
                tabla_contabilizacion=tabla_cont,
                tiempo_promedio_por_tipo=tiempo_por_tipo,
                resumen_texto="",  # Se actualiza después
                resumen_datos=None  # Se actualiza después
            )
            
            # Obtener tiempo promedio global del usuario
            tiempo_promedio_global = await self.get_tiempo_promedio_global_usuario(
                conn, usuario['id_usuario'], filtros
            )
            
            # Obtener motivo de retrabajo principal del usuario
            motivo_principal, _ = await self.get_motivo_retrabajo_principal(
                conn, filtros, user_id=usuario['id_usuario']
            )
            
            # Generar resumen de datos estructurado
            detalle_usuario.resumen_datos = self.generar_resumen_usuario(
                detalle_usuario, 
                filtros,
                motivo_retrabajo_principal=motivo_principal,
                tiempo_promedio_global_dias=tiempo_promedio_global
            )
            # Legacy/Fallback (opcional, si queremos mantener el string)
            # detalle_usuario.resumen_texto = self._render_resumen_usuario_legacy(detalle_usuario) # No longer needed based on requirements
            
            resultados.append(detalle_usuario)
        
        return resultados
    
    async def get_tiempo_promedio_por_tipo(
        self, 
        conn, 
        user_id: UUID, 
        filtros: FiltrosReporte
    ) -> Dict[str, float]:
        """
        Obtiene tiempo promedio de elaboración agrupado por tipo de solicitud.
        
        Args:
            conn: Conexión a base de datos
            user_id: ID del usuario responsable
            filtros: Filtros de fecha y otros criterios
            
        Returns:
            Dict con nombre_tipo -> días promedio
        """
        where_clause, params = self._build_where_clause(filtros)
        
        # Agregar filtro de usuario
        idx_user = len(params) + 1
        params.append(user_id)
        
        # IDs de catálogos dinámicos
        cats = await self._get_catalog_ids(conn)
        id_entregado = cats['estatus'].get('entregado')
        id_perdido = cats['estatus'].get('perdido')
        
        params.extend([id_entregado, id_perdido])
        idx_entregado = len(params) - 1
        idx_perdido = len(params)
        
        query = f"""
            SELECT 
                ts.nombre as tipo,
                AVG(o.tiempo_elaboracion_horas) / 24 as dias_promedio
            FROM tb_oportunidades o
            JOIN tb_cat_tipos_solicitud ts ON o.id_tipo_solicitud = ts.id
            JOIN tb_cat_estatus_global e ON o.id_estatus_global = e.id
            {where_clause}
            AND o.responsable_simulacion_id = ${idx_user}
            AND o.tiempo_elaboracion_horas IS NOT NULL
            AND o.id_estatus_global IN (${idx_entregado}, ${idx_perdido})
            AND o.id_tipo_solicitud != (
                SELECT id FROM tb_cat_tipos_solicitud 
                WHERE LOWER(nombre) = 'levantamiento'
            )
            GROUP BY ts.nombre
            HAVING AVG(o.tiempo_elaboracion_horas) IS NOT NULL
        """
        
        rows = await conn.fetch(query, *params)
        return {row['tipo']: round(float(row['dias_promedio']), 1) for row in rows}
    
    def generar_resumen_usuario(
        self, 
        usuario: 'DetalleUsuario',
        filtros: FiltrosReporte,
        motivo_retrabajo_principal: str = None,  # ← AGREGADO
        tiempo_promedio_global_dias: float = None  # ← AGREGADO
    ) -> ResumenUsuario:
        """Genera datos estructurados para resumen de usuario"""
        
        # Tecnología principal
        tech_principal = None
        if usuario.metricas_por_tecnologia:
            # Filtrar techs con > 0 solicitudes
            techs_activas = [t for t in usuario.metricas_por_tecnologia if t.total_solicitudes > 0]
            if techs_activas:
                tech = max(techs_activas, key=lambda x: x.total_solicitudes)
                tech_principal = {
                    "nombre": tech.nombre,
                    "solicitudes": tech.total_solicitudes
                }
        
        # Tiempo promedio por tipo (lista ordenada)
        tiempo_por_tipo = []
        if usuario.tiempo_promedio_por_tipo:
            tiempo_por_tipo = [
                {
                    "tipo": tipo,
                    "dias": dias
                }
                for tipo, dias in sorted(usuario.tiempo_promedio_por_tipo.items(), key=lambda x: x[1])
            ]
        
        # Métricas generales shortcuts
        m = usuario.metricas_generales
        
        return ResumenUsuario(
            nombre=usuario.nombre,
            total_ofertas=m.total_ofertas,
            tecnologia_principal=tech_principal,
            porcentaje_interno=m.porcentaje_a_tiempo_interno,
            porcentaje_compromiso=m.porcentaje_a_tiempo_compromiso,
            tiempo_promedio_por_tipo=tiempo_por_tipo,
            licitaciones=m.licitaciones,
            porcentaje_licitaciones=round((m.licitaciones / m.total_solicitudes) * 100, 1) if m.total_solicitudes > 0 else 0,
            extraordinarias=m.extraordinarias,
            versiones=m.versiones,
            # Campos adicionales de retrabajos
            tiempo_promedio_global_dias=tiempo_promedio_global_dias,
            total_retrabajos=m.retrabajos,
            porcentaje_retrabajos=round((m.retrabajos / m.total_solicitudes) * 100, 1) if m.total_solicitudes > 0 else 0,
            motivo_retrabajo_principal=motivo_retrabajo_principal
        )
    
    async def generar_resumen_ejecutivo(
        self,
        conn,
        metricas: MetricasGenerales,
        usuarios: List['DetalleUsuario'],
        filas_tipo: List[FilaContabilizacion],
        filtros: FiltrosReporte,
        motivo_retrabajo_principal: tuple = (None, 0)
    ) -> ResumenEjecutivo:
        """
        Genera SOLO DATOS para el resumen ejecutivo.
        El renderizado HTML se hace en el template.
        """
        import locale
        
        # Configurar locale para fechas en español
        try:
            locale.setlocale(locale.LC_TIME, 'es_ES.UTF-8')
        except:
            pass  # Fallback si no está disponible
        
        # Formatear fechas
        fecha_inicio = filtros.fecha_inicio.strftime("%d de %B de %Y")
        fecha_fin = filtros.fecha_fin.strftime("%d de %B de %Y")
        
        # Top 3 tipos
        top_tipos = []
        if filas_tipo and metricas.total_solicitudes > 0:
            top_tipos_sorted = sorted(filas_tipo, key=lambda x: x.total, reverse=True)[:3]
            top_tipos = [
                {
                    "nombre": t.nombre,
                    "total": t.total,
                    "porcentaje": round((t.total / metricas.total_solicitudes) * 100, 1) if metricas.total_solicitudes > 0 else 0
                }
                for t in top_tipos_sorted
            ]
        
        # Mejor usuario (por KPI Compromiso)
        mejor_usuario_data = None
        if usuarios:
            # Filtrar usuarios con actividad en KPI compromiso
            usuarios_con_kpi = [u for u in usuarios if (u.metricas_generales.entregas_a_tiempo_compromiso + u.metricas_generales.entregas_tarde_compromiso) > 0]
            
            if usuarios_con_kpi:
                # Encontrar el mejor usuario basado en porcentaje de compromiso
                mejor_user = max(usuarios_con_kpi, key=lambda u: u.metricas_generales.porcentaje_a_tiempo_compromiso)
                mejor_usuario_data = {
                    "nombre": mejor_user.nombre,
                    "ofertas": mejor_user.metricas_generales.total_ofertas,
                    "porcentaje_interno": mejor_user.metricas_generales.porcentaje_a_tiempo_interno,
                    "porcentaje_compromiso": mejor_user.metricas_generales.porcentaje_a_tiempo_compromiso
                }
        
        # Calcular totales de entregas
        total_entregas_interno = metricas.entregas_a_tiempo_interno + metricas.entregas_tarde_interno
        total_entregas_compromiso = metricas.entregas_a_tiempo_compromiso + metricas.entregas_tarde_compromiso
        
        # =====================================================================
        # NUEVO: Calcular scores y categorizar usuarios
        # =====================================================================
        score_config = await self._get_score_config(conn)
        
        usuarios_con_score = []
        for usuario in usuarios:
            # Crear MetricaUsuario a partir de DetalleUsuario para calcular score
            metrica_usuario = MetricaUsuario(
                usuario_id=usuario.usuario_id,
                nombre=usuario.nombre,
                total_solicitudes=usuario.metricas_generales.total_solicitudes,
                total_ofertas=usuario.metricas_generales.total_ofertas,
                entregas_a_tiempo_compromiso=usuario.metricas_generales.entregas_a_tiempo_compromiso,
                entregas_tarde_compromiso=usuario.metricas_generales.entregas_tarde_compromiso,
                entregas_a_tiempo_interno=usuario.metricas_generales.entregas_a_tiempo_interno,
                entregas_tarde_interno=usuario.metricas_generales.entregas_tarde_interno,
                licitaciones=usuario.metricas_generales.licitaciones,
                versiones=usuario.metricas_generales.versiones,
                retrabajados=usuario.metricas_generales.retrabajos,
            )
            
            # Calcular score
            score = calcular_score_usuario(metrica_usuario, score_config)
            metrica_usuario.score = score
            
            # Obtener motivo de retrabajo principal del usuario
            if metrica_usuario.retrabajados > 0:
                motivo_usuario, _ = await self.get_motivo_retrabajo_principal(
                    conn, filtros, user_id=metrica_usuario.usuario_id
                )
                score.motivo_retrabajo_principal = motivo_usuario
            
            usuarios_con_score.append(metrica_usuario)
        
        # Categorizar usuarios
        categorias = {
            "alta_complejidad": [u for u in usuarios_con_score if u.score and u.score.categoria == "alta_complejidad"],
            "eficiencia": [u for u in usuarios_con_score if u.score and u.score.categoria == "eficiencia"],
            "evaluacion": [u for u in usuarios_con_score if u.score and u.score.categoria == "evaluacion"]
        }
        
        # Ordenar por score dentro de cada categoría
        for cat in categorias.values():
            cat.sort(key=lambda u: u.score.score_final if u.score else 0, reverse=True)
        
        # Construir objeto de datos
        return ResumenEjecutivo(
            fecha_inicio_formatted=fecha_inicio,
            fecha_fin_formatted=fecha_fin,
            total_solicitudes=metricas.total_solicitudes,
            total_ofertas=metricas.total_ofertas,
            top_tipos=top_tipos,
            porcentaje_cumplimiento_interno=metricas.porcentaje_a_tiempo_interno,
            entregas_a_tiempo_interno=metricas.entregas_a_tiempo_interno,
            total_entregas_interno=total_entregas_interno,
            porcentaje_cumplimiento_compromiso=metricas.porcentaje_a_tiempo_compromiso,
            entregas_a_tiempo_compromiso=metricas.entregas_a_tiempo_compromiso,
            total_entregas_compromiso=total_entregas_compromiso,
            mejor_usuario=mejor_usuario_data,
            licitaciones=metricas.licitaciones,
            porcentaje_licitaciones=metricas.porcentaje_licitaciones,
            extraordinarias=metricas.extraordinarias,
            porcentaje_extraordinarias=round((metricas.extraordinarias / metricas.total_solicitudes) * 100, 1) if metricas.total_solicitudes > 0 else 0,
            versiones=metricas.versiones,
            porcentaje_versiones=round((metricas.versiones / metricas.total_solicitudes) * 100, 1) if metricas.total_solicitudes > 0 else 0,
            # Retrabajos
            total_retrabajos=metricas.retrabajos,
            porcentaje_retrabajos=round((metricas.retrabajos / metricas.total_solicitudes) * 100, 1) if metricas.total_solicitudes > 0 else 0,
            motivo_retrabajo_principal=motivo_retrabajo_principal[0],
            conteo_motivo_principal=motivo_retrabajo_principal[1],
            categorias_usuarios=categorias,
            mostrar_nota_alta_complejidad=len(categorias["alta_complejidad"]) > 0,
            ratio_licitaciones_global=round((metricas.licitaciones / metricas.total_solicitudes * 100) if metricas.total_solicitudes > 0 else 0, 1),
            umbral_licitaciones_pct=score_config.umbral_ratio_licitaciones * 100
        )
    
    async def get_resumen_mensual(self, conn, filtros: FiltrosReporte) -> Dict[str, FilaMensual]:
        """
        Genera el resumen mensual tipo pivot con KPIs duales.
        
        Returns:
            Dict con métricas como keys y FilaMensual como values
        """
        where_clause, params = self._build_where_clause(filtros)
        
        # IDs de catálogos dinámicos
        cats = await self._get_catalog_ids(conn)
        
        id_entregado = cats['estatus'].get('entregado')
        id_perdido = cats['estatus'].get('perdido')
        id_cancelado = cats['estatus'].get('cancelado')
        id_levantamiento = cats['tipos'].get('levantamiento')
        
        # IDs para estatus "en espera"
        id_pendiente = cats['estatus'].get('pendiente')
        id_en_proceso = cats['estatus'].get('en proceso')
        id_en_revision = cats['estatus'].get('en revisión')
        
        params.extend([id_entregado, id_perdido, id_cancelado, id_levantamiento, id_pendiente, id_en_proceso, id_en_revision])
        idx_entregado = len(params) - 6
        idx_perdido = len(params) - 5
        idx_cancelado = len(params) - 4
        idx_levantamiento = len(params) - 3
        idx_pendiente = len(params) - 2
        idx_proceso = len(params) - 1
        idx_revision = len(params)
        
        # Query con CTE para incluir KPIs de sitios
        query = f"""
            WITH sitios_mensual AS (
                SELECT 
                    EXTRACT(MONTH FROM o.fecha_solicitud AT TIME ZONE 'America/Mexico_City')::int as mes,
                    s.id_oportunidad,
                    s.kpi_status_interno,
                    s.kpi_status_compromiso,
                    s.es_retrabajo,
                    o.parent_id,
                    o.clasificacion_solicitud,
                    o.id_estatus_global,
                    o.id_tipo_solicitud,
                    o.tiempo_elaboracion_horas,
                    o.id_motivo_cierre
                FROM tb_sitios_oportunidad s
                JOIN tb_oportunidades o ON s.id_oportunidad = o.id_oportunidad
                JOIN tb_cat_estatus_global e ON o.id_estatus_global = e.id
                {where_clause}
            )
            SELECT 
                mes,
                
                COUNT(DISTINCT id_oportunidad) as solicitudes_recibidas,
                
                COUNT(DISTINCT id_oportunidad) FILTER (
                    WHERE id_estatus_global IN (${idx_entregado}, ${idx_perdido})
                ) as ofertas_generadas,
                
                -- KPI INTERNO
                COUNT(*) FILTER (
                    WHERE kpi_status_interno = 'Entrega a tiempo'
                    AND id_estatus_global IN (${idx_entregado}, ${idx_perdido})
                    AND id_tipo_solicitud != ${idx_levantamiento}
                ) as entregas_a_tiempo_interno,
                
                COUNT(*) FILTER (
                    WHERE kpi_status_interno = 'Entrega tarde'
                    AND id_estatus_global IN (${idx_entregado}, ${idx_perdido})
                    AND id_tipo_solicitud != ${idx_levantamiento}
                ) as entregas_tarde_interno,
                
                -- KPI COMPROMISO
                COUNT(*) FILTER (
                    WHERE kpi_status_compromiso = 'Entrega a tiempo'
                    AND id_estatus_global IN (${idx_entregado}, ${idx_perdido})
                    AND id_tipo_solicitud != ${idx_levantamiento}
                ) as entregas_a_tiempo_compromiso,
                
                COUNT(*) FILTER (
                    WHERE kpi_status_compromiso = 'Entrega tarde'
                    AND id_estatus_global IN (${idx_entregado}, ${idx_perdido})
                    AND id_tipo_solicitud != ${idx_levantamiento}
                ) as entregas_tarde_compromiso,
                
                AVG(tiempo_elaboracion_horas) FILTER (
                    WHERE tiempo_elaboracion_horas IS NOT NULL
                ) as tiempo_promedio,
                
                COUNT(DISTINCT id_oportunidad) FILTER (
                    WHERE id_estatus_global IN (${idx_pendiente}, ${idx_proceso}, ${idx_revision})
                ) as en_espera,
                
                COUNT(DISTINCT id_oportunidad) FILTER (
                    WHERE id_estatus_global = ${idx_cancelado}
                ) as canceladas,
                
                COUNT(DISTINCT id_oportunidad) FILTER (
                    WHERE id_estatus_global = ${idx_cancelado}
                    AND id_motivo_cierre BETWEEN 1 AND 8
                ) as no_viables,
                
                COUNT(DISTINCT id_oportunidad) FILTER (
                    WHERE id_estatus_global = ${idx_perdido}
                ) as perdidas,
                
                COUNT(DISTINCT id_oportunidad) FILTER (
                    WHERE clasificacion_solicitud = 'EXTRAORDINARIO'
                ) as extraordinarias,
                
                COUNT(DISTINCT id_oportunidad) FILTER (
                    WHERE parent_id IS NOT NULL
                ) as versiones,
                
                COUNT(*) FILTER (
                    WHERE es_retrabajo = TRUE
                ) as retrabajos
                
            FROM sitios_mensual
            GROUP BY mes
            ORDER BY mes
        """
        
        rows = await conn.fetch(query, *params)
        
        # Inicializar estructura de respuesta con nuevas métricas
        metricas_nombres = [
            'solicitudes_recibidas',
            'ofertas_generadas', 
            'porcentaje_en_plazo_interno',
            'porcentaje_fuera_plazo_interno',
            'entregas_a_tiempo_interno',
            'entregas_tarde_interno',
            'porcentaje_en_plazo_compromiso',
            'porcentaje_fuera_plazo_compromiso',
            'entregas_a_tiempo_compromiso',
            'entregas_tarde_compromiso',
            'porcentaje_en_plazo',  # Legacy - mapea a compromiso
            'porcentaje_fuera_plazo',
            'tiempo_promedio',
            'en_espera',
            'canceladas',
            'no_viables',
            'perdidas',
            'extraordinarias',
            'versiones',
            'retrabajos'
        ]
        
        resultado = {nombre: FilaMensual(metrica=nombre) for nombre in metricas_nombres}
        
        # Procesar filas
        for row in rows:
            mes = row['mes']
            
            # Calcular porcentajes KPI INTERNO
            total_kpi_interno = (row['entregas_a_tiempo_interno'] or 0) + (row['entregas_tarde_interno'] or 0)
            pct_interno = round((row['entregas_a_tiempo_interno'] or 0) / total_kpi_interno * 100, 1) if total_kpi_interno > 0 else 0
            
            # Calcular porcentajes KPI COMPROMISO
            total_kpi_compromiso = (row['entregas_a_tiempo_compromiso'] or 0) + (row['entregas_tarde_compromiso'] or 0)
            pct_compromiso = round((row['entregas_a_tiempo_compromiso'] or 0) / total_kpi_compromiso * 100, 1) if total_kpi_compromiso > 0 else 0
            pct_tarde = round((row['entregas_tarde_compromiso'] or 0) / total_kpi_compromiso * 100, 1) if total_kpi_compromiso > 0 else 0
            
            resultado['solicitudes_recibidas'].valores[mes] = row['solicitudes_recibidas'] or 0
            resultado['ofertas_generadas'].valores[mes] = row['ofertas_generadas'] or 0
            
            # KPIs Internos (Porcentajes y Conteos)
            resultado['porcentaje_en_plazo_interno'].valores[mes] = pct_interno
            resultado['porcentaje_fuera_plazo_interno'].valores[mes] = round(100 - pct_interno, 1) if total_kpi_interno > 0 else 0
            resultado['entregas_a_tiempo_interno'].valores[mes] = row['entregas_a_tiempo_interno'] or 0
            resultado['entregas_tarde_interno'].valores[mes] = row['entregas_tarde_interno'] or 0
            
            # KPIs Compromiso (Porcentajes y Conteos)
            resultado['porcentaje_en_plazo_compromiso'].valores[mes] = pct_compromiso
            resultado['porcentaje_fuera_plazo_compromiso'].valores[mes] = pct_tarde
            resultado['entregas_a_tiempo_compromiso'].valores[mes] = row['entregas_a_tiempo_compromiso'] or 0
            resultado['entregas_tarde_compromiso'].valores[mes] = row['entregas_tarde_compromiso'] or 0
            
            # Legacy fields
            resultado['porcentaje_en_plazo'].valores[mes] = pct_compromiso  
            resultado['porcentaje_fuera_plazo'].valores[mes] = pct_tarde
            
            resultado['tiempo_promedio'].valores[mes] = round(float(row['tiempo_promedio'] or 0) / 24, 1)  # A días
            resultado['en_espera'].valores[mes] = row['en_espera'] or 0
            resultado['canceladas'].valores[mes] = row['canceladas'] or 0
            resultado['no_viables'].valores[mes] = row['no_viables'] or 0
            resultado['perdidas'].valores[mes] = row['perdidas'] or 0
            resultado['extraordinarias'].valores[mes] = row['extraordinarias'] or 0
            resultado['versiones'].valores[mes] = row['versiones'] or 0
            resultado['retrabajos'].valores[mes] = row['retrabajos'] or 0
        
        # Calcular totales
        for nombre, fila in resultado.items():
            if nombre in ['porcentaje_en_plazo', 'porcentaje_en_plazo_interno', 'porcentaje_fuera_plazo_interno', 'porcentaje_en_plazo_compromiso', 'porcentaje_fuera_plazo_compromiso', 'porcentaje_fuera_plazo', 'tiempo_promedio']:
                # Promedios
                valores = [v for v in fila.valores.values() if v > 0]
                fila.total = round(sum(valores) / len(valores), 1) if valores else 0
            else:
                # Sumas
                fila.total = sum(fila.valores.values())
        
        return resultado
    
    # =========================================================================
    # DATOS PARA GRÁFICAS
    # =========================================================================
    
    async def get_all_report_data(self, conn, filtros: FiltrosReporte) -> dict:
        """Obtiene TODOS los datos necesarios para el PDF en una sola llamada."""
        return {
            'metricas': await self.get_metricas_generales(conn, filtros),
            'tecnologias': await self.get_metricas_por_tecnologia(conn, filtros),
            'contabilizacion': await self.get_tabla_contabilizacion(conn, filtros),
            'usuarios': await self.get_detalle_por_usuario(conn, filtros),
            'mensual': await self.get_resumen_mensual(conn, filtros)
        }

    async def get_datos_graficas(self, conn, filtros: FiltrosReporte) -> Dict[str, DatosGrafica]:
        """
        Prepara datos estructurados para todas las gráficas del dashboard.
        
        Returns:
            Dict con identificadores de gráfica y sus datos
        """
        graficas = {}
        
        # 1. Gráfica de Pie: Distribución por Estatus
        graficas['estatus_pie'] = await self._get_grafica_estatus(conn, filtros)
        
        # 2. Gráfica de Barras: Solicitudes por Mes
        graficas['mensual_bar'] = await self._get_grafica_mensual(conn, filtros)
        
        # 3. Gráfica de Pie: Distribución por Tecnología
        graficas['tecnologia_pie'] = await self._get_grafica_tecnologia(conn, filtros)
        
        # 4. Gráfica de Barras Horizontal: A Tiempo vs Tarde
        graficas['kpi_bar'] = await self._get_grafica_kpi(conn, filtros)
        
        # 5. Gráfica de Motivos de Cierre
        graficas['motivos_bar'] = await self._get_grafica_motivos(conn, filtros)
        
        return graficas
    
    async def _get_grafica_estatus(self, conn, filtros: FiltrosReporte) -> DatosGrafica:
        """Distribución por estatus."""
        where_clause, params = self._build_where_clause(filtros)
        
        query = f"""
            SELECT 
                e.nombre,
                e.color_hex,
                COUNT(*) as total
            FROM tb_oportunidades o
            JOIN tb_cat_estatus_global e ON o.id_estatus_global = e.id
            {where_clause}
            GROUP BY e.id, e.nombre, e.color_hex
            ORDER BY total DESC
        """
        
        rows = await conn.fetch(query, *params)
        
        return DatosGrafica(
            tipo='doughnut',
            labels=[r['nombre'] for r in rows],
            datasets=[{
                'data': [r['total'] for r in rows],
                'backgroundColor': [r['color_hex'] or '#6B7280' for r in rows]
            }]
        )
    
    async def _get_grafica_mensual(self, conn, filtros: FiltrosReporte) -> DatosGrafica:
        """Solicitudes por mes."""
        where_clause, params = self._build_where_clause(filtros)
        
        query = f"""
            SELECT 
                EXTRACT(MONTH FROM o.fecha_solicitud AT TIME ZONE 'America/Mexico_City')::int as mes,
                COUNT(*) as total
            FROM tb_oportunidades o
            JOIN tb_cat_estatus_global e ON o.id_estatus_global = e.id
            {where_clause}
            GROUP BY mes
            ORDER BY mes
        """
        
        rows = await conn.fetch(query, *params)
        
        meses_nombres = ['', 'Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 
                         'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
        
        return DatosGrafica(
            tipo='bar',
            labels=[meses_nombres[r['mes']] for r in rows],
            datasets=[{
                'label': 'Solicitudes',
                'data': [r['total'] for r in rows],
                'backgroundColor': '#00BABB'
            }]
        )
    
    async def _get_grafica_tecnologia(self, conn, filtros: FiltrosReporte) -> DatosGrafica:
        """Distribución por tecnología."""
        where_clause, params = self._build_where_clause(filtros)
        
        query = f"""
            SELECT 
                t.nombre,
                COUNT(*) as total
            FROM tb_oportunidades o
            JOIN tb_cat_estatus_global e ON o.id_estatus_global = e.id
            JOIN tb_cat_tecnologias t ON o.id_tecnologia = t.id
            {where_clause}
            GROUP BY t.id, t.nombre
            ORDER BY total DESC
        """
        
        rows = await conn.fetch(query, *params)
        
        # Colores predefinidos para tecnologías
        colores = ['#00BABB', '#3B82F6', '#10B981', '#F59E0B', '#8B5CF6']
        
        return DatosGrafica(
            tipo='pie',
            labels=[r['nombre'] for r in rows],
            datasets=[{
                'data': [r['total'] for r in rows],
                'backgroundColor': colores[:len(rows)]
            }]
        )
    
    async def _get_grafica_kpi(self, conn, filtros: FiltrosReporte) -> DatosGrafica:
        """Comparativa A Tiempo vs Tarde."""
        metricas = await self.get_metricas_generales(conn, filtros)
        
        return DatosGrafica(
            tipo='bar',
            labels=['Entregas'],
            datasets=[
                {
                    'label': 'A Tiempo',
                    'data': [metricas.entregas_a_tiempo],
                    'backgroundColor': '#10B981'
                },
                {
                    'label': 'Fuera de Plazo',
                    'data': [metricas.entregas_tarde],
                    'backgroundColor': '#EF4444'
                }
            ],
            opciones={'indexAxis': 'y'}  # Horizontal
        )
    
    async def _get_grafica_motivos(self, conn, filtros: FiltrosReporte) -> DatosGrafica:
        """Distribución de motivos de cierre."""
        where_clause, params = self._build_where_clause(filtros)
        
        query = f"""
            SELECT 
                m.motivo,
                m.categoria,
                COUNT(*) as total
            FROM tb_oportunidades o
            JOIN tb_cat_estatus_global e ON o.id_estatus_global = e.id
            JOIN tb_cat_motivos_cierre m ON o.id_motivo_cierre = m.id
            {where_clause}
            AND o.id_motivo_cierre IS NOT NULL
            GROUP BY m.id, m.motivo, m.categoria
            ORDER BY total DESC
            LIMIT 10
        """
        
        rows = await conn.fetch(query, *params)
        
        # Colores por categoría
        colores_categoria = {
            'Técnico': '#3B82F6',
            'Regulatorio': '#8B5CF6', 
            'Económico': '#F59E0B',
            'Competencia': '#EF4444',
            'Otros': '#6B7280'
        }
        
        return DatosGrafica(
            tipo='bar',
            labels=[r['motivo'][:30] + '...' if len(r['motivo']) > 30 else r['motivo'] for r in rows],
            datasets=[{
                'label': 'Cantidad',
                'data': [r['total'] for r in rows],
                'backgroundColor': [colores_categoria.get(r['categoria'], '#6B7280') for r in rows]
            }],
            opciones={'indexAxis': 'y'}
        )
    
    # =========================================================================
    # UTILIDADES
    # =========================================================================
    
    async def get_catalogos_filtros(self, conn) -> Dict[str, List[Dict]]:
        """
        Obtiene catálogos para poblar los filtros del reporte.
        """
        tecnologias = await conn.fetch(
            "SELECT id, nombre FROM tb_cat_tecnologias WHERE activo = true ORDER BY nombre"
        )
        tipos = await conn.fetch(
            "SELECT id, nombre, codigo_interno FROM tb_cat_tipos_solicitud WHERE activo = true ORDER BY nombre"
        )
        estatus = await conn.fetch(
            "SELECT id, nombre FROM tb_cat_estatus_global WHERE activo = true AND modulo_aplicable = 'SIMULACION' ORDER BY id"
        )
        usuarios = await conn.fetch("""
            SELECT id_usuario, nombre 
            FROM tb_usuarios 
            WHERE is_active = true 
            AND LOWER(department) = 'simulación'
            ORDER BY nombre
        """)
        
        return {
            "tecnologias": [dict(t) for t in tecnologias],
            "tipos_solicitud": [dict(t) for t in tipos],
            "estatus": [dict(e) for e in estatus],
            "usuarios": [dict(u) for u in usuarios]
        }


# =============================================================================
# HELPER PARA INYECCIÓN DE DEPENDENCIAS
# =============================================================================

def get_reportes_service() -> ReportesSimulacionService:
    """Factory para inyección de dependencias en FastAPI."""
    return ReportesSimulacionService()
