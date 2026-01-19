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

logger = logging.getLogger("ReportesSimulacion")


# =============================================================================
# CONSTANTES
# =============================================================================

# Umbrales para semáforo
UMBRAL_VERDE = 90.0    # >= 90%
UMBRAL_AMBAR = 85.0    # >= 85% y < 90%
# < 85% = Rojo


# =============================================================================
# DATACLASSES PARA RESPUESTAS TIPADAS
# =============================================================================

@dataclass
class MetricasGenerales:
    """Métricas principales del dashboard."""
    total_solicitudes: int = 0
    total_ofertas: int = 0
    en_espera: int = 0
    canceladas: int = 0
    no_viables: int = 0
    extraordinarias: int = 0
    retrabajadas: int = 0
    licitaciones: int = 0
    entregas_a_tiempo: int = 0
    entregas_tarde: int = 0
    sin_fecha_entrega: int = 0
    tiempo_promedio_horas: Optional[float] = None
    
    @property
    def porcentaje_a_tiempo(self) -> float:
        """Calcula % entregas a tiempo sobre total de ofertas con KPI."""
        total_con_kpi = self.entregas_a_tiempo + self.entregas_tarde
        if total_con_kpi == 0:
            return 0.0
        return round((self.entregas_a_tiempo / total_con_kpi) * 100, 1)
    
    @property
    def porcentaje_tarde(self) -> float:
        """Calcula % entregas tarde sobre total de ofertas con KPI."""
        total_con_kpi = self.entregas_a_tiempo + self.entregas_tarde
        if total_con_kpi == 0:
            return 0.0
        return round((self.entregas_tarde / total_con_kpi) * 100, 1)
    
    @property
    def tiempo_promedio_dias(self) -> Optional[float]:
        """Convierte horas a días para display."""
        if self.tiempo_promedio_horas is None:
            return None
        return round(self.tiempo_promedio_horas / 24, 1)


@dataclass
class MetricaTecnologia:
    """Métricas para una tecnología específica."""
    id_tecnologia: int
    nombre: str
    total_solicitudes: int = 0
    total_ofertas: int = 0
    entregas_a_tiempo: int = 0
    entregas_tarde: int = 0
    extraordinarias: int = 0
    retrabajadas: int = 0
    tiempo_promedio_horas: Optional[float] = None
    potencia_total_kwp: float = 0.0
    capacidad_total_kwh: float = 0.0
    
    @property
    def porcentaje_a_tiempo(self) -> float:
        total_con_kpi = self.entregas_a_tiempo + self.entregas_tarde
        if total_con_kpi == 0:
            return 0.0
        return round((self.entregas_a_tiempo / total_con_kpi) * 100, 1)
    
    @property
    def porcentaje_tarde(self) -> float:
        total_con_kpi = self.entregas_a_tiempo + self.entregas_tarde
        if total_con_kpi == 0:
            return 0.0
        return round((self.entregas_tarde / total_con_kpi) * 100, 1)


@dataclass
class FilaContabilizacion:
    """Fila de la tabla de contabilización por tipo de solicitud."""
    id_tipo_solicitud: int
    nombre: str
    codigo_interno: str
    total: int = 0
    en_plazo: int = 0
    fuera_plazo: int = 0
    sin_fecha: int = 0
    es_levantamiento: bool = False
    # Subclasificación para levantamientos
    info_completa: int = 0
    info_incompleta: int = 0
    
    @property
    def porcentaje_en_plazo(self) -> float:
        """Calcula % en plazo sobre total con fecha."""
        total_con_fecha = self.en_plazo + self.fuera_plazo
        if total_con_fecha == 0:
            return 0.0
        return round((self.en_plazo / total_con_fecha) * 100, 1)
    
    @property
    def semaforo(self) -> str:
        """Determina color del semáforo."""
        if self.es_levantamiento:
            return "gray"  # Levantamientos no tienen semáforo
        pct = self.porcentaje_en_plazo
        if pct >= UMBRAL_VERDE:
            return "green"
        elif pct >= UMBRAL_AMBAR:
            return "amber"
        else:
            return "red"


@dataclass
class DetalleUsuario:
    """Métricas detalladas por usuario responsable."""
    usuario_id: UUID
    nombre: str
    metricas_generales: MetricasGenerales = field(default_factory=MetricasGenerales)
    metricas_por_tecnologia: List[MetricaTecnologia] = field(default_factory=list)
    tabla_contabilizacion: List[FilaContabilizacion] = field(default_factory=list)


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

    def calcular_semaforo(self, porcentaje: float) -> str:
        """Determina color del semáforo según porcentaje."""
        if porcentaje >= UMBRAL_VERDE:
            return "green"
        elif porcentaje >= UMBRAL_AMBAR:
            return "amber"
        return "red"
    
    # =========================================================================
    # QUERIES PRINCIPALES
    # =========================================================================
    
    async def get_metricas_generales(self, conn, filtros: FiltrosReporte) -> MetricasGenerales:
        """
        Obtiene métricas agregadas principales.
        
        Query optimizado que calcula todo en una sola pasada.
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
        params.extend([id_entregado, id_perdido, id_cancelado, id_levantamiento, id_pendiente, id_en_proceso, id_en_revision])
        idx_entregado = len(params) - 6
        idx_perdido = len(params) - 5
        idx_cancelado = len(params) - 4
        idx_levantamiento = len(params) - 3
        idx_pendiente = len(params) - 2
        idx_proceso = len(params) - 1
        idx_revision = len(params)
        
        query = f"""
            SELECT 
                -- Totales básicos
                COUNT(*) as total_solicitudes,
                
                -- Ofertas generadas (Entregado + Perdido)
                COUNT(*) FILTER (
                    WHERE o.id_estatus_global IN (${idx_entregado}, ${idx_perdido})
                ) as total_ofertas,
                
                -- En espera (Pendiente, En Proceso, En Revisión)
                COUNT(*) FILTER (
                    WHERE o.id_estatus_global IN (${idx_pendiente}, ${idx_proceso}, ${idx_revision})
                ) as en_espera,
                
                -- Canceladas
                COUNT(*) FILTER (
                    WHERE o.id_estatus_global = ${idx_cancelado}
                ) as canceladas,
                
                -- No viables (canceladas con motivo técnico/regulatorio: IDs 1-8)
                COUNT(*) FILTER (
                    WHERE o.id_estatus_global = ${idx_cancelado}
                    AND o.id_motivo_cierre BETWEEN 1 AND 8
                ) as no_viables,
                
                -- Extraordinarias
                COUNT(*) FILTER (
                    WHERE o.clasificacion_solicitud = 'EXTRAORDINARIO'
                ) as extraordinarias,
                
                -- Retrabajadas (tienen parent_id)
                COUNT(*) FILTER (
                    WHERE o.parent_id IS NOT NULL
                ) as retrabajadas,
                
                -- Licitaciones
                COUNT(*) FILTER (
                    WHERE o.es_licitacion = true
                ) as licitaciones,
                
                -- KPI: Entregas a tiempo (excluyendo levantamientos)
                COUNT(*) FILTER (
                    WHERE o.kpi_status_compromiso = 'Entrega a tiempo'
                    AND o.id_estatus_global IN (${idx_entregado}, ${idx_perdido})
                    AND o.id_tipo_solicitud != ${idx_levantamiento}
                ) as entregas_a_tiempo,
                
                -- KPI: Entregas tarde (excluyendo levantamientos)
                COUNT(*) FILTER (
                    WHERE o.kpi_status_compromiso = 'Entrega tarde'
                    AND o.id_estatus_global IN (${idx_entregado}, ${idx_perdido})
                    AND o.id_tipo_solicitud != ${idx_levantamiento}
                ) as entregas_tarde,
                
                -- Sin fecha de entrega (ofertas sin fecha)
                COUNT(*) FILTER (
                    WHERE o.id_estatus_global IN (${idx_entregado}, ${idx_perdido})
                    AND o.fecha_entrega_simulacion IS NULL
                ) as sin_fecha_entrega,
                
                -- Tiempo promedio de elaboración (solo ofertas con tiempo)
                AVG(o.tiempo_elaboracion_horas) FILTER (
                    WHERE o.tiempo_elaboracion_horas IS NOT NULL
                    AND o.id_estatus_global IN (${idx_entregado}, ${idx_perdido})
                ) as tiempo_promedio_horas
                
            FROM tb_oportunidades o
            JOIN tb_cat_estatus_global e ON o.id_estatus_global = e.id
            {where_clause}
        """
        
        row = await conn.fetchrow(query, *params)
        
        if not row:
            return MetricasGenerales()
        
        return MetricasGenerales(
            total_solicitudes=row['total_solicitudes'] or 0,
            total_ofertas=row['total_ofertas'] or 0,
            en_espera=row['en_espera'] or 0,
            canceladas=row['canceladas'] or 0,
            no_viables=row['no_viables'] or 0,
            extraordinarias=row['extraordinarias'] or 0,
            retrabajadas=row['retrabajadas'] or 0,
            licitaciones=row['licitaciones'] or 0,
            entregas_a_tiempo=row['entregas_a_tiempo'] or 0,
            entregas_tarde=row['entregas_tarde'] or 0,
            sin_fecha_entrega=row['sin_fecha_entrega'] or 0,
            tiempo_promedio_horas=float(row['tiempo_promedio_horas']) if row['tiempo_promedio_horas'] else None
        )
    
    async def get_metricas_por_tecnologia(self, conn, filtros: FiltrosReporte) -> List[MetricaTecnologia]:
        """
        Obtiene métricas desglosadas por cada tecnología.
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
                t.id as id_tecnologia,
                t.nombre,
                
                COUNT(o.id_oportunidad) as total_solicitudes,
                
                COUNT(o.id_oportunidad) FILTER (
                    WHERE o.id_estatus_global IN (${idx_entregado}, ${idx_perdido})
                ) as total_ofertas,
                
                COUNT(o.id_oportunidad) FILTER (
                    WHERE o.kpi_status_compromiso = 'Entrega a tiempo'
                    AND o.id_estatus_global IN (${idx_entregado}, ${idx_perdido})
                    AND o.id_tipo_solicitud != ${idx_levantamiento}
                ) as entregas_a_tiempo,
                
                COUNT(o.id_oportunidad) FILTER (
                    WHERE o.kpi_status_compromiso = 'Entrega tarde'
                    AND o.id_estatus_global IN (${idx_entregado}, ${idx_perdido})
                    AND o.id_tipo_solicitud != ${idx_levantamiento}
                ) as entregas_tarde,
                
                COUNT(o.id_oportunidad) FILTER (
                    WHERE o.clasificacion_solicitud = 'EXTRAORDINARIO'
                ) as extraordinarias,
                
                COUNT(o.id_oportunidad) FILTER (
                    WHERE o.parent_id IS NOT NULL
                ) as retrabajadas,
                
                AVG(o.tiempo_elaboracion_horas) FILTER (
                    WHERE o.tiempo_elaboracion_horas IS NOT NULL
                ) as tiempo_promedio_horas,
                
                COALESCE(SUM(o.potencia_cierre_fv_kwp), 0) as potencia_total_kwp,
                COALESCE(SUM(o.capacidad_cierre_bess_kwh), 0) as capacidad_total_kwh
                
            FROM tb_cat_tecnologias t
            LEFT JOIN tb_oportunidades o ON o.id_tecnologia = t.id
            LEFT JOIN tb_cat_estatus_global e ON o.id_estatus_global = e.id
                AND e.modulo_aplicable = 'SIMULACION'
            {where_clause.replace('WHERE', 'AND') if 'WHERE' in where_clause else ''}
            WHERE t.activo = true
            GROUP BY t.id, t.nombre
            ORDER BY t.id
        """
        
        # Ajustar query para manejar el LEFT JOIN correctamente
        query_adjusted = f"""
            WITH filtered_ops AS (
                SELECT o.*, e.modulo_aplicable
                FROM tb_oportunidades o
                JOIN tb_cat_estatus_global e ON o.id_estatus_global = e.id
                {where_clause}
            )
            SELECT 
                t.id as id_tecnologia,
                t.nombre,
                COUNT(fo.id_oportunidad) as total_solicitudes,
                COUNT(fo.id_oportunidad) FILTER (
                    WHERE fo.id_estatus_global IN (${idx_entregado}, ${idx_perdido})
                ) as total_ofertas,
                COUNT(fo.id_oportunidad) FILTER (
                    WHERE fo.kpi_status_compromiso = 'Entrega a tiempo'
                    AND fo.id_estatus_global IN (${idx_entregado}, ${idx_perdido})
                    AND fo.id_tipo_solicitud != ${idx_levantamiento}
                ) as entregas_a_tiempo,
                COUNT(fo.id_oportunidad) FILTER (
                    WHERE fo.kpi_status_compromiso = 'Entrega tarde'
                    AND fo.id_estatus_global IN (${idx_entregado}, ${idx_perdido})
                    AND fo.id_tipo_solicitud != ${idx_levantamiento}
                ) as entregas_tarde,
                COUNT(fo.id_oportunidad) FILTER (
                    WHERE fo.clasificacion_solicitud = 'EXTRAORDINARIO'
                ) as extraordinarias,
                COUNT(fo.id_oportunidad) FILTER (
                    WHERE fo.parent_id IS NOT NULL
                ) as retrabajadas,
                AVG(fo.tiempo_elaboracion_horas) FILTER (
                    WHERE fo.tiempo_elaboracion_horas IS NOT NULL
                ) as tiempo_promedio_horas,
                COALESCE(SUM(fo.potencia_cierre_fv_kwp), 0) as potencia_total_kwp,
                COALESCE(SUM(fo.capacidad_cierre_bess_kwh), 0) as capacidad_total_kwh
            FROM tb_cat_tecnologias t
            LEFT JOIN filtered_ops fo ON fo.id_tecnologia = t.id
            WHERE t.activo = true
            GROUP BY t.id, t.nombre
            ORDER BY t.id
        """
        
        rows = await conn.fetch(query_adjusted, *params)
        
        return [
            MetricaTecnologia(
                id_tecnologia=row['id_tecnologia'],
                nombre=row['nombre'],
                total_solicitudes=row['total_solicitudes'] or 0,
                total_ofertas=row['total_ofertas'] or 0,
                entregas_a_tiempo=row['entregas_a_tiempo'] or 0,
                entregas_tarde=row['entregas_tarde'] or 0,
                extraordinarias=row['extraordinarias'] or 0,
                retrabajadas=row['retrabajadas'] or 0,
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
            WITH filtered_ops AS (
                SELECT o.*, e.modulo_aplicable
                FROM tb_oportunidades o
                JOIN tb_cat_estatus_global e ON o.id_estatus_global = e.id
                {where_clause}
            )
            SELECT 
                ts.id as id_tipo_solicitud,
                ts.nombre,
                ts.codigo_interno,
                
                COUNT(fo.id_oportunidad) as total,
                
                -- En plazo (ofertas con KPI a tiempo)
                COUNT(fo.id_oportunidad) FILTER (
                    WHERE fo.kpi_status_compromiso = 'Entrega a tiempo'
                    AND fo.id_estatus_global IN (${idx_entregado}, ${idx_perdido})
                ) as en_plazo,
                
                -- Fuera de plazo (ofertas con KPI tarde)
                COUNT(fo.id_oportunidad) FILTER (
                    WHERE fo.kpi_status_compromiso = 'Entrega tarde'
                    AND fo.id_estatus_global IN (${idx_entregado}, ${idx_perdido})
                ) as fuera_plazo,
                
                -- Sin fecha (ofertas sin fecha de entrega o sin KPI)
                COUNT(fo.id_oportunidad) FILTER (
                    WHERE fo.id_estatus_global IN (${idx_entregado}, ${idx_perdido})
                    AND (fo.fecha_entrega_simulacion IS NULL OR fo.kpi_status_compromiso IS NULL)
                ) as sin_fecha,
                
                -- Flag levantamiento
                (ts.id = ${idx_levantamiento}) as es_levantamiento
                
            FROM tb_cat_tipos_solicitud ts
            LEFT JOIN filtered_ops fo ON fo.id_tipo_solicitud = ts.id
            WHERE ts.activo = true
            GROUP BY ts.id, ts.nombre, ts.codigo_interno
            ORDER BY ts.id
        """
        
        rows = await conn.fetch(query, *params)
        
        return [
            FilaContabilizacion(
                id_tipo_solicitud=row['id_tipo_solicitud'],
                nombre=row['nombre'],
                codigo_interno=row['codigo_interno'],
                total=row['total'] or 0,
                en_plazo=row['en_plazo'] or 0,
                fuera_plazo=row['fuera_plazo'] or 0,
                sin_fecha=row['sin_fecha'] or 0,
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
            
            resultados.append(DetalleUsuario(
                usuario_id=usuario['id_usuario'],
                nombre=usuario['nombre'],
                metricas_generales=metricas_gen,
                metricas_por_tecnologia=metricas_tech,
                tabla_contabilizacion=tabla_cont
            ))
        
        return resultados
    
    async def get_resumen_mensual(self, conn, filtros: FiltrosReporte) -> Dict[str, FilaMensual]:
        """
        Genera el resumen mensual tipo pivot.
        
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
        
        query = f"""
            SELECT 
                EXTRACT(MONTH FROM o.fecha_solicitud AT TIME ZONE 'America/Mexico_City')::int as mes,
                
                COUNT(*) as solicitudes_recibidas,
                
                COUNT(*) FILTER (
                    WHERE o.id_estatus_global IN (${idx_entregado}, ${idx_perdido})
                ) as ofertas_generadas,
                
                COUNT(*) FILTER (
                    WHERE o.kpi_status_compromiso = 'Entrega a tiempo'
                    AND o.id_estatus_global IN (${idx_entregado}, ${idx_perdido})
                    AND o.id_tipo_solicitud != ${idx_levantamiento}
                ) as entregas_a_tiempo,
                
                COUNT(*) FILTER (
                    WHERE o.kpi_status_compromiso = 'Entrega tarde'
                    AND o.id_estatus_global IN (${idx_entregado}, ${idx_perdido})
                    AND o.id_tipo_solicitud != ${idx_levantamiento}
                ) as entregas_tarde,
                
                AVG(o.tiempo_elaboracion_horas) FILTER (
                    WHERE o.tiempo_elaboracion_horas IS NOT NULL
                ) as tiempo_promedio,
                
                COUNT(*) FILTER (
                    WHERE o.id_estatus_global IN (${idx_pendiente}, ${idx_proceso}, ${idx_revision})
                ) as en_espera,
                
                COUNT(*) FILTER (
                    WHERE o.id_estatus_global = ${idx_cancelado}
                ) as canceladas,
                
                COUNT(*) FILTER (
                    WHERE o.id_estatus_global = ${idx_cancelado}
                    AND o.id_motivo_cierre BETWEEN 1 AND 8
                ) as no_viables,
                
                COUNT(*) FILTER (
                    WHERE o.id_estatus_global = ${idx_perdido}
                ) as perdidas,
                
                COUNT(*) FILTER (
                    WHERE o.clasificacion_solicitud = 'EXTRAORDINARIO'
                ) as extraordinarias,
                
                COUNT(*) FILTER (
                    WHERE o.parent_id IS NOT NULL
                ) as retrabajadas
                
            FROM tb_oportunidades o
            JOIN tb_cat_estatus_global e ON o.id_estatus_global = e.id
            {where_clause}
            GROUP BY mes
            ORDER BY mes
        """
        
        rows = await conn.fetch(query, *params)
        
        # Inicializar estructura de respuesta
        metricas_nombres = [
            'solicitudes_recibidas',
            'ofertas_generadas', 
            'porcentaje_en_plazo',
            'porcentaje_fuera_plazo',
            'tiempo_promedio',
            'en_espera',
            'canceladas',
            'no_viables',
            'perdidas',
            'extraordinarias',
            'retrabajadas'
        ]
        
        resultado = {nombre: FilaMensual(metrica=nombre) for nombre in metricas_nombres}
        
        # Procesar filas
        for row in rows:
            mes = row['mes']
            
            # Calcular porcentajes
            total_con_kpi = (row['entregas_a_tiempo'] or 0) + (row['entregas_tarde'] or 0)
            pct_tiempo = round((row['entregas_a_tiempo'] or 0) / total_con_kpi * 100, 1) if total_con_kpi > 0 else 0
            pct_tarde = round((row['entregas_tarde'] or 0) / total_con_kpi * 100, 1) if total_con_kpi > 0 else 0
            
            resultado['solicitudes_recibidas'].valores[mes] = row['solicitudes_recibidas'] or 0
            resultado['ofertas_generadas'].valores[mes] = row['ofertas_generadas'] or 0
            resultado['porcentaje_en_plazo'].valores[mes] = pct_tiempo
            resultado['porcentaje_fuera_plazo'].valores[mes] = pct_tarde
            resultado['tiempo_promedio'].valores[mes] = round(float(row['tiempo_promedio'] or 0) / 24, 1)  # A días
            resultado['en_espera'].valores[mes] = row['en_espera'] or 0
            resultado['canceladas'].valores[mes] = row['canceladas'] or 0
            resultado['no_viables'].valores[mes] = row['no_viables'] or 0
            resultado['perdidas'].valores[mes] = row['perdidas'] or 0
            resultado['extraordinarias'].valores[mes] = row['extraordinarias'] or 0
            resultado['retrabajadas'].valores[mes] = row['retrabajadas'] or 0
        
        # Calcular totales
        for nombre, fila in resultado.items():
            if nombre in ['porcentaje_en_plazo', 'porcentaje_fuera_plazo', 'tiempo_promedio']:
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
