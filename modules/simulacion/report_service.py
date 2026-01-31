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
from dataclasses import dataclass, field, asdict
from enum import Enum
import logging
from dateutil.relativedelta import relativedelta

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

from .db_service import SimulacionDBService
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
        # Fallback
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
        # Fallback
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


@dataclass
class MetricasGenerales(KPIMetricsMixin):
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
    
    # Properties para porcentajes KPI Interno (Managed by Mixin)
    
    # Properties para porcentajes KPI Compromiso (Managed by Mixin)
    
    # Compatibilidad Legacy
    @property
    def porcentaje_a_tiempo(self) -> float:
        return self.porcentaje_a_tiempo_compromiso
    
    @property
    def porcentaje_tarde(self) -> float:
        return self.porcentaje_tarde_compromiso


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
class MetricaTecnologia(KPIMetricsMixin):
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
    
    # Properties KPI Interno (Managed by Mixin)
        
    # Properties KPI Compromiso (Managed by Mixin)
    
    @property
    def porcentaje_licitaciones(self) -> float:
        """% de solicitudes que son licitaciones."""
        if self.total_solicitudes == 0:
            return 0.0
        return round((self.licitaciones / self.total_solicitudes) * 100, 1)



@dataclass
class FilaContabilizacion(KPIMetricsMixin):
    """Fila de la tabla de contabilización con KPIs duales."""
    id_tipo_solicitud: int
    nombre: str
    codigo_interno: str

    # Configuración dinámica
    umbrales_interno: Optional[UmbralesKPI] = None
    umbrales_compromiso: Optional[UmbralesKPI] = None

    total: int = 0
    
    # KPI Interno (Renamed to match Mixin)
    entregas_a_tiempo_interno: int = 0
    entregas_tarde_interno: int = 0
    
    # KPI Compromiso (Renamed to match Mixin)
    entregas_a_tiempo_compromiso: int = 0
    entregas_tarde_compromiso: int = 0
    
    # Compatibilidad Legacy (apunta a compromiso)
    @property
    def en_plazo(self) -> int:
        return self.entregas_a_tiempo_compromiso
        
    @property
    def fuera_plazo(self) -> int:
        return self.entregas_tarde_compromiso
    
    sin_fecha: int = 0
    es_levantamiento: bool = False
    licitaciones: int = 0  # ← Solicitudes que son licitaciones
    
    # Properties KPI Interno (Managed by Mixin)
    
    @property
    def semaforo_interno_label(self) -> str:
        if self.es_levantamiento:
            return "No aplica"
        pct = self.porcentaje_a_tiempo_interno
        if self.umbrales_interno:
            return self.umbrales_interno.get_label(pct)
        return f"{pct}%"
    
    # Properties KPI Compromiso (Managed by Mixin)
        
    @property
    def semaforo_compromiso_label(self) -> str:
        if self.es_levantamiento:
            return "No aplica"
        pct = self.porcentaje_a_tiempo_compromiso
        if self.umbrales_compromiso:
            return self.umbrales_compromiso.get_label(pct)
        return f"{pct}%"
        
    # Compatibilidad Legacy
    @property
    def porcentaje_en_plazo(self) -> float:
        return self.porcentaje_a_tiempo_compromiso
        
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
    licitaciones: int = 0  # ← Solicitudes que son licitaciones
    versiones: int = 0  # ← Oportunidades con parent_id
    retrabajados: int = 0  # ← Sitios con es_retrabajo=true
    resumen_texto: str = ""  # ← Texto descriptivo para resumen desplegable
    tiempo_promedio_por_tipo: Dict[str, float] = field(default_factory=dict)  # ← tipo_solicitud -> horas promedio
    score: Optional['ScoreUsuario'] = None  # ← Score calculado
    
    # Configuración dinámica (Added for Mixin support if needed later, but MetricaUsuario wasn't using it directly for semaphores in code, but properties use it)
    # Wait, MetricaUsuario didn't have umbrales fields in definition!
    # But semaforo_interno used self.umbrales_interno in Mixin.
    # MetricaUsuario needs these fields if it's going to use the Mixin fully.
    # Let's check original code.
    
    # Original code:
    # @property
    # def porcentaje_a_tiempo_interno(self) -> float:
    # ... logic internal only ...
    
    # It didn't have semaforo_interno property! It only had percent properties.
    # My Mixin ADDS semaforo properties. This is fine, extra functionality.
    # BUT, the Mixin expects self.umbrales_interno to exist.
    # If MetricaUsuario doesn't have it, accessing semaforo_interno will crash if I don't handle it.
    
    # However, looking at the code I'm removing:
    # It ONLY had percentage properties. It did NOT have semaphores.
    # So I can just inherit the percentage logic.
    # But the mixin defines semaphores too.
    # If I use the mixin, I get semaphores. 
    # If I access them, I need umbrales.
    # If I don't access them, I'm fine?
    
    # Wait, the Mixin implementation of semaforo_interno:
    # if self.umbrales_interno:
    
    # This implies self has attribute umbrales_interno.
    # If MetricaUsuario doesn't have it, it will raise AttributeError.
    
    # So I MUST add these fields to MetricaUsuario, defaulting to None.
    
    umbrales_interno: Optional[UmbralesKPI] = None
    umbrales_compromiso: Optional[UmbralesKPI] = None

    @property
    def porcentaje_a_tiempo(self) -> float:
        """% entregas a tiempo según KPI Compromiso."""
        return self.porcentaje_a_tiempo_compromiso
    
    @property
    def porcentaje_a_tiempo_compromiso(self) -> float:
        """% entregas a tiempo según KPI Compromiso (alias)."""
        return super().porcentaje_a_tiempo_compromiso

    # Mixin handles: porcentaje_a_tiempo_interno, porcentaje_a_tiempo_compromiso (Wait, I need to check MRO)
    # The Mixin has porcentaje_a_tiempo_compromiso.
    # I can just remove the manual definition if it matches.
    # Original:
    # return round((self.entregas_a_tiempo_compromiso / total_con_kpi) * 100, 1)
    # Mixin:
    # Same logic.
    
    # So I can remove them all.
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
    clasificadas: int  # Total - En Espera
    en_espera: int
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

    # === NUEVOS CAMPOS ===

    # Gestión de demanda - desglose de diferencia
    sin_fecha_sistema: int = 0
    diferencia_explicacion: str = ""  # Ej: "14 canceladas, 3 no viables, 3 sin fecha"

    # Análisis por tecnología (lista completa)
    tecnologias_detalle: List[Dict[str, Any]] = field(default_factory=list)
    # Estructura: [{"nombre": "FV", "solicitudes": 100, "pct_interno": 45.2, "pct_compromiso": 62.1}, ...]

    mejor_tecnologia: Optional[Dict[str, Any]] = None  # {"nombre": "X", "pct_compromiso": Y}
    peor_tecnologia: Optional[Dict[str, Any]] = None   # {"nombre": "X", "pct_compromiso": Y}

    # Estacionalidad (solo se llena si hay >6 meses en el rango)
    mostrar_estacionalidad: bool = False
    mejor_mes: Optional[Dict[str, Any]] = None  # {"nombre": "Marzo", "pct_interno": X, "pct_compromiso": Y}
    peor_mes: Optional[Dict[str, Any]] = None   # {"nombre": "Octubre", "pct_interno": X, "pct_compromiso": Y}

    # Cantidad de meses en el rango (para decidir si mostrar estacionalidad)
    meses_en_rango: int = 0





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
        self.db = SimulacionDBService()
    
    # =========================================================================
    # MÉTODOS AUXILIARES
    # =========================================================================
    
    def get_current_datetime_mx(self) -> datetime:
        """Obtiene hora actual en México."""
        return datetime.now(self.zona_mx)
        
    # _get_catalog_ids removed/replaced by db_service call

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
        cats = await self.db.get_report_catalog_ids(conn)
        row = await self.db.get_report_metricas_generales_row(conn, asdict(filtros), cats)
        
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
        row = await self.db.get_report_motivo_retrabajo(conn, asdict(filtros), user_id)
        
        if row:
            return row['motivo'], row['conteo']
        else:
            return None, 0
        
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
        dias_promedio = await self.db.get_report_tiempo_promedio_global(conn, user_id, asdict(filtros))
        return round(dias_promedio, 1) if dias_promedio else None
    
    async def get_metricas_por_tecnologia(self, conn, filtros: FiltrosReporte) -> List[MetricaTecnologia]:
        """
        Obtiene métricas desglosadas por cada tecnología con KPIs duales.
        Usa CTE con join a tb_sitios_oportunidad para KPIs a nivel sitio.
        """
        cats = await self.db.get_report_catalog_ids(conn)
        rows = await self.db.get_report_metricas_tech(conn, asdict(filtros), cats)
        
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
        cats = await self.db.get_report_catalog_ids(conn)
        rows = await self.db.get_report_tabla_contabilizacion(conn, asdict(filtros), cats)
        
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
                entregas_a_tiempo_interno=row['entregas_a_tiempo_interno'] or 0,
                entregas_tarde_interno=row['entregas_tarde_interno'] or 0,
                entregas_a_tiempo_compromiso=row['entregas_a_tiempo_compromiso'] or 0,
                entregas_tarde_compromiso=row['entregas_tarde_compromiso'] or 0,
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
        usuarios = await self.db.get_report_users_active(conn, asdict(filtros))
        
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

        cats = await self.db.get_report_catalog_ids(conn)
        return await self.db.get_report_tiempo_promedio_tipo(conn, user_id, asdict(filtros), cats)
    
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
        motivo_retrabajo_principal: tuple = (None, 0),
        # === NUEVOS PARÁMETROS ===
        metricas_tecnologia: List[MetricaTecnologia] = None,
        resumen_mensual: Dict[str, 'FilaMensual'] = None
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
        
        # =====================================================================
        # NUEVO: Gestión de demanda - explicación de diferencia
        # =====================================================================
        diferencia = metricas.total_solicitudes - metricas.total_ofertas - metricas.en_espera
        partes_explicacion = []
        if metricas.canceladas > 0:
            partes_explicacion.append(f"{metricas.canceladas} canceladas")
        if metricas.no_viables > 0:
            partes_explicacion.append(f"{metricas.no_viables} no viables")
        if metricas.sin_fecha_entrega > 0:
            partes_explicacion.append(f"{metricas.sin_fecha_entrega} sin fecha")
        diferencia_explicacion = ", ".join(partes_explicacion) if partes_explicacion else ""

        # =====================================================================
        # NUEVO: Análisis por tecnología
        # =====================================================================
        tecnologias_detalle = []
        mejor_tecnologia = None
        peor_tecnologia = None

        if metricas_tecnologia:
            for tech in metricas_tecnologia:
                # Solo incluir tecnologías con actividad
                if tech.total_solicitudes > 0:
                    detalle = {
                        "nombre": tech.nombre,
                        "solicitudes": tech.total_solicitudes,
                        "ofertas": tech.total_ofertas,
                        "pct_interno": tech.porcentaje_a_tiempo_interno,
                        "pct_compromiso": tech.porcentaje_a_tiempo_compromiso
                    }
                    tecnologias_detalle.append(detalle)
            
            # Ordenar por solicitudes descendente
            tecnologias_detalle.sort(key=lambda x: x["solicitudes"], reverse=True)
            
            # Encontrar mejor y peor por cumplimiento compromiso (mínimo 5 ofertas para ser considerado)
            techs_evaluables = [t for t in tecnologias_detalle if t["ofertas"] >= 5]
            if techs_evaluables:
                mejor_tecnologia = max(techs_evaluables, key=lambda x: x["pct_compromiso"])
                peor_tecnologia = min(techs_evaluables, key=lambda x: x["pct_compromiso"])
                # Evitar que mejor y peor sean el mismo si solo hay una tecnología evaluable
                if mejor_tecnologia == peor_tecnologia:
                    peor_tecnologia = None

        # =====================================================================
        # NUEVO: Estacionalidad (solo si >6 meses)
        # =====================================================================
        # Calcular cantidad de meses en el rango
        
        delta = relativedelta(filtros.fecha_fin, filtros.fecha_inicio)
        meses_en_rango = delta.years * 12 + delta.months + 1

        mostrar_estacionalidad = meses_en_rango > 6
        mejor_mes = None
        peor_mes = None

        meses_nombres_full = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
                              'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']

        if mostrar_estacionalidad and resumen_mensual:
            # Extraer datos mensuales de KPI compromiso
            meses_data = []
            
            # resumen_mensual tiene estructura: {"metrica_nombre": FilaMensual}
            # Necesitamos cruzar entregas_a_tiempo_compromiso con total evaluable por mes
            
            fila_a_tiempo = resumen_mensual.get("entregas_a_tiempo_compromiso")
            fila_tarde = resumen_mensual.get("entregas_tarde_compromiso")
            
            if fila_a_tiempo and fila_tarde:
                for mes in fila_a_tiempo.valores.keys():
                    a_tiempo = fila_a_tiempo.valores.get(mes, 0) or 0
                    tarde = fila_tarde.valores.get(mes, 0) or 0
                    total = a_tiempo + tarde
                    if total >= 5:  # Mínimo para considerar
                        pct = round((a_tiempo / total) * 100, 1) if total > 0 else 0
                        meses_data.append({
                            "mes": mes,
                            "nombre": meses_nombres_full[mes],
                            "pct_compromiso": pct,
                            "total": total
                        })
            
            if meses_data:
                mejor_mes = max(meses_data, key=lambda x: x["pct_compromiso"])
                peor_mes = min(meses_data, key=lambda x: x["pct_compromiso"])
                # Evitar que mejor y peor sean el mismo
                if mejor_mes["mes"] == peor_mes["mes"]:
                    peor_mes = None
        
        # Construir objeto de datos
        return ResumenEjecutivo(
            fecha_inicio_formatted=fecha_inicio,
            fecha_fin_formatted=fecha_fin,
            total_solicitudes=metricas.total_solicitudes,
            clasificadas=metricas.total_solicitudes - metricas.en_espera,
            en_espera=metricas.en_espera,
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
            umbral_licitaciones_pct=score_config.umbral_ratio_licitaciones * 100,

            # === NUEVOS CAMPOS ===
            sin_fecha_sistema=metricas.sin_fecha_entrega,
            diferencia_explicacion=diferencia_explicacion,
            tecnologias_detalle=tecnologias_detalle,
            mejor_tecnologia=mejor_tecnologia,
            peor_tecnologia=peor_tecnologia,
            mostrar_estacionalidad=mostrar_estacionalidad,
            mejor_mes=mejor_mes,
            peor_mes=peor_mes,
            meses_en_rango=meses_en_rango,
        )
    
    async def get_resumen_mensual(self, conn, filtros: FiltrosReporte) -> Dict[str, FilaMensual]:
        """
        Genera el resumen mensual tipo pivot con KPIs duales.
        
        Returns:
            Dict con métricas como keys y FilaMensual como values
        """
        cats = await self.db.get_report_catalog_ids(conn)
        rows = await self.db.get_report_resumen_mensual(conn, asdict(filtros), cats)
        
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
        rows = await self.db.get_chart_estatus(conn, asdict(filtros))
        
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
        rows = await self.db.get_chart_mensual(conn, asdict(filtros))
        
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
        rows = await self.db.get_chart_tecnologia(conn, asdict(filtros))
        
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
        rows = await self.db.get_chart_motivos_cierre(conn, asdict(filtros))
        
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
        return await self.db.get_report_catalogos_filtros(conn)


# =============================================================================
# HELPER PARA INYECCIÓN DE DEPENDENCIAS
# =============================================================================

def get_reportes_service() -> ReportesSimulacionService:
    return ReportesSimulacionService()
