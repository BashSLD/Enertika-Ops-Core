# modules/simulacion/report_service.py
"""
Service Layer para Reportes de Simulación.

Responsabilidades:
- Lógica de negocio y orquestación de datos para reportes
- Cálculos de KPIs y agregaciones
- Preparación de datos para gráficas

NO contiene:
- Definición de dataclasses (ver report_models.py)
- Queries SQL (ver db_service.py)
- Lógica HTTP (ver report_router.py)
"""

from datetime import datetime, date
from typing import List, Dict, Optional, Any, Tuple
from uuid import UUID
from zoneinfo import ZoneInfo
from dataclasses import asdict, replace as dc_replace
import logging
import asyncio

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
    VOLUMEN_MAX_NORMALIZACION,
)
from .report_models import (
    _MESES_ES,
    UMBRAL_VERDE,
    UMBRAL_AMBAR,
    KPIMetricsMixin,
    ConfiguracionScore,
    MetricasGenerales,
    MetricaTecnologia,
    FilaContabilizacion,
    ResumenUsuario,
    DetalleUsuario,
    MetricaUsuario,
    ScoreUsuario,
    FilaMensual,
    DatosGrafica,
    FiltrosReporte,
    ResumenEjecutivo,
    categorizar_usuario,
    calcular_score_usuario,
)
from .report_db_service import ReportDBService
from core.config_service import ConfigService, UmbralesKPI

logger = logging.getLogger("ReportesSimulacion")


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
        self.db = ReportDBService()

    # =========================================================================
    # MÉTODOS AUXILIARES
    # =========================================================================

    def get_current_datetime_mx(self) -> datetime:
        return datetime.now(self.zona_mx)

    async def _get_score_config(self, conn) -> ConfiguracionScore:
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
            umbral_ambar=await ConfigService.get_global_config(conn, "sim_umbral_ambar", UMBRAL_AMBAR, float),
        )

    def calcular_semaforo(self, porcentaje: float, config: ConfiguracionScore = None) -> str:
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
        cats = await self.db.get_report_catalog_ids(conn)
        row = await self.db.get_report_metricas_generales_row(conn, asdict(filtros), cats)

        u_interno = await ConfigService.get_umbrales_kpi(conn, "kpi_interno")
        u_compromiso = await ConfigService.get_umbrales_kpi(conn, "kpi_compromiso")

        if not row:
            return MetricasGenerales(umbrales_interno=u_interno, umbrales_compromiso=u_compromiso)

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
            tiempo_promedio_horas=row['tiempo_promedio_horas'],
            total_sitios=row['total_sitios'] or 0,
            total_sitios_entregados=row['total_sitios_entregados'] or 0,
            oportunidades_multisitio=row['oportunidades_multisitio'] or 0,
            ganadas=row['ganadas'] or 0,
            sim_adicionales_count=row['sim_adicionales_count'] or 0,
        )

    async def get_motivo_retrabajo_principal(
        self,
        conn,
        filtros: FiltrosReporte,
        user_id: UUID = None,
    ) -> tuple:
        row = await self.db.get_report_motivo_retrabajo(conn, asdict(filtros), user_id)
        if row:
            return row['motivo'], row['conteo']
        return None, 0

    async def get_tiempo_promedio_global_usuario(
        self,
        conn,
        user_id: UUID,
        filtros: FiltrosReporte,
    ) -> float:
        dias_promedio = await self.db.get_report_tiempo_promedio_global(conn, user_id, asdict(filtros))
        return round(dias_promedio, 1) if dias_promedio else None

    async def get_metricas_por_tecnologia(self, conn, filtros: FiltrosReporte) -> List[MetricaTecnologia]:
        cats = await self.db.get_report_catalog_ids(conn)
        rows = await self.db.get_report_metricas_tech(conn, asdict(filtros), cats)

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
                capacidad_total_kwh=float(row['capacidad_total_kwh'] or 0),
                total_sitios=row['total_sitios'] or 0,
            )
            for row in rows
        ]

    async def get_tabla_contabilizacion(self, conn, filtros: FiltrosReporte) -> List[FilaContabilizacion]:
        cats = await self.db.get_report_catalog_ids(conn)
        rows = await self.db.get_report_tabla_contabilizacion(conn, asdict(filtros), cats)

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
                es_levantamiento=row['es_levantamiento'] or False,
            )
            for row in rows
        ]

    # =========================================================================
    # HELPERS PRIVADOS — construcción de dataclasses desde rows DB
    # Usados por get_detalle_por_usuario para evitar recargar cats/umbrales
    # por cada usuario en el loop.
    # =========================================================================

    def _build_metricas_generales(
        self,
        row: Optional[Dict],
        u_interno,
        u_compromiso,
    ) -> MetricasGenerales:
        if not row:
            return MetricasGenerales(umbrales_interno=u_interno, umbrales_compromiso=u_compromiso)
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
            tiempo_promedio_horas=row['tiempo_promedio_horas'],
            total_sitios=row['total_sitios'] or 0,
            total_sitios_entregados=row['total_sitios_entregados'] or 0,
            oportunidades_multisitio=row['oportunidades_multisitio'] or 0,
            ganadas=row['ganadas'] or 0,
            sim_adicionales_count=row['sim_adicionales_count'] or 0,
        )

    def _build_metricas_tech(
        self,
        rows: List[Dict],
        u_interno,
        u_compromiso,
    ) -> List[MetricaTecnologia]:
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
                capacidad_total_kwh=float(row['capacidad_total_kwh'] or 0),
                total_sitios=row['total_sitios'] or 0,
            )
            for row in rows
        ]

    def _build_tabla_contabilizacion(
        self,
        rows: List[Dict],
        u_interno,
        u_compromiso,
    ) -> List[FilaContabilizacion]:
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
                es_levantamiento=row['es_levantamiento'] or False,
            )
            for row in rows
        ]

    async def get_detalle_por_usuario(self, conn, filtros: FiltrosReporte) -> List[DetalleUsuario]:
        """
        Fase 2 — batch SQL: 6 queries fijas independientemente del número de usuarios.
        Antes: 1 + 6N queries. Ahora: ~9 queries fijas.
        """
        usuarios = await self.db.get_report_users_active(conn, asdict(filtros))
        if not usuarios:
            return []

        cats = await self.db.get_report_catalog_ids(conn)
        u_interno = await ConfigService.get_umbrales_kpi(conn, "kpi_interno")
        u_compromiso = await ConfigService.get_umbrales_kpi(conn, "kpi_compromiso")
        filtros_dict = asdict(filtros)

        batch_metricas = await self.db.get_report_metricas_generales_batch(conn, filtros_dict, cats)
        batch_tech = await self.db.get_report_metricas_tech_batch(conn, filtros_dict, cats)
        batch_contab = await self.db.get_report_tabla_contabilizacion_batch(conn, filtros_dict, cats)
        batch_tiempo_tipo = await self.db.get_report_tiempo_promedio_tipo_batch(conn, filtros_dict, cats)
        batch_tiempo_global = await self.db.get_report_tiempo_promedio_global_batch(conn, filtros_dict)
        batch_motivos = await self.db.get_report_motivo_retrabajo_batch(conn, filtros_dict)

        map_metricas = {r['responsable_simulacion_id']: r for r in batch_metricas}

        map_tech: Dict[Any, List[Dict]] = {}
        for r in batch_tech:
            map_tech.setdefault(r['responsable_simulacion_id'], []).append(r)

        map_contab: Dict[Any, List[Dict]] = {}
        for r in batch_contab:
            map_contab.setdefault(r['responsable_simulacion_id'], []).append(r)

        map_tiempo_tipo: Dict[Any, Dict[str, float]] = {}
        for r in batch_tiempo_tipo:
            uid = r['responsable_simulacion_id']
            if uid not in map_tiempo_tipo:
                map_tiempo_tipo[uid] = {}
            map_tiempo_tipo[uid][r['tipo']] = round(float(r['dias_promedio']), 1)

        map_tiempo_global = {
            r['responsable_simulacion_id']: round(float(r['dias_promedio']), 1) if r['dias_promedio'] else None
            for r in batch_tiempo_global
        }
        map_motivos = {r['responsable_simulacion_id']: r['motivo'] for r in batch_motivos}

        resultados = []
        for usuario in usuarios:
            uid = usuario['id_usuario']

            metricas_gen = self._build_metricas_generales(map_metricas.get(uid), u_interno, u_compromiso)
            metricas_tech = self._build_metricas_tech(map_tech.get(uid, []), u_interno, u_compromiso)
            tabla_cont = self._build_tabla_contabilizacion(map_contab.get(uid, []), u_interno, u_compromiso)

            detalle_usuario = DetalleUsuario(
                usuario_id=uid,
                nombre=usuario['nombre'],
                metricas_generales=metricas_gen,
                metricas_por_tecnologia=metricas_tech,
                tabla_contabilizacion=tabla_cont,
                tiempo_promedio_por_tipo=map_tiempo_tipo.get(uid, {}),
                resumen_texto="",
                resumen_datos=None,
            )

            detalle_usuario.resumen_datos = self.generar_resumen_usuario(
                detalle_usuario,
                filtros,
                motivo_retrabajo_principal=map_motivos.get(uid),
                tiempo_promedio_global_dias=map_tiempo_global.get(uid),
            )

            resultados.append(detalle_usuario)

        return resultados

    async def get_oportunidades_usuario_reporte(
        self,
        conn,
        usuario_id: UUID,
        filtros: FiltrosReporte,
    ) -> List[Dict[str, Any]]:
        filtros_usuario = dc_replace(filtros, responsable_id=usuario_id)
        return await self.db.get_report_oportunidades_usuario(conn, asdict(filtros_usuario))

    async def get_tiempo_promedio_por_tipo(
        self,
        conn,
        user_id: UUID,
        filtros: FiltrosReporte,
    ) -> Dict[str, float]:
        cats = await self.db.get_report_catalog_ids(conn)
        return await self.db.get_report_tiempo_promedio_tipo(conn, user_id, asdict(filtros), cats)

    def generar_resumen_usuario(
        self,
        usuario: 'DetalleUsuario',
        filtros: FiltrosReporte,
        motivo_retrabajo_principal: str = None,
        tiempo_promedio_global_dias: float = None,
    ) -> ResumenUsuario:
        tech_principal = None
        if usuario.metricas_por_tecnologia:
            techs_activas = [t for t in usuario.metricas_por_tecnologia if t.total_solicitudes > 0]
            if techs_activas:
                tech = max(techs_activas, key=lambda x: x.total_solicitudes)
                tech_principal = {"nombre": tech.nombre, "solicitudes": tech.total_solicitudes}

        tiempo_por_tipo = []
        if usuario.tiempo_promedio_por_tipo:
            tiempo_por_tipo = [
                {"tipo": tipo, "dias": dias}
                for tipo, dias in sorted(usuario.tiempo_promedio_por_tipo.items(), key=lambda x: x[1])
            ]

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
            tiempo_promedio_global_dias=tiempo_promedio_global_dias,
            total_retrabajos=m.retrabajos,
            porcentaje_retrabajos=round((m.retrabajos / m.total_sitios) * 100, 1) if m.total_sitios > 0 else 0,
            motivo_retrabajo_principal=motivo_retrabajo_principal,
            total_sitios=m.total_sitios,
            total_sitios_entregados=m.total_sitios_entregados,
            oportunidades_multisitio=m.oportunidades_multisitio,
            promedio_sitios_por_oportunidad=m.promedio_sitios_por_oportunidad,
        )

    async def generar_resumen_ejecutivo(
        self,
        conn,
        metricas: MetricasGenerales,
        usuarios: List['DetalleUsuario'],
        filas_tipo: List[FilaContabilizacion],
        filtros: FiltrosReporte,
        motivo_retrabajo_principal: tuple = (None, 0),
        metricas_tecnologia: List[MetricaTecnologia] = None,
        resumen_mensual: Dict[str, 'FilaMensual'] = None,
        motivos_cierre: List[Dict[str, Any]] = None,
    ) -> ResumenEjecutivo:
        def _fmt_fecha(d):
            return f"{d.day:02d} de {_MESES_ES[d.month]} de {d.year}"

        fecha_inicio = _fmt_fecha(filtros.fecha_inicio)
        fecha_fin = _fmt_fecha(filtros.fecha_fin)

        top_tipos = []
        levantamiento_info = None
        if filas_tipo:
            filas_no_lev = [f for f in filas_tipo if not f.es_levantamiento]
            fila_lev = next((f for f in filas_tipo if f.es_levantamiento), None)

            if filas_no_lev and metricas.total_sitios > 0:
                top_tipos_sorted = sorted(filas_no_lev, key=lambda x: x.total, reverse=True)[:3]
                top_tipos = [
                    {
                        "nombre": t.nombre,
                        "total": t.total,
                        "porcentaje": round((t.total / metricas.total_sitios) * 100, 1),
                    }
                    for t in top_tipos_sorted
                ]

            if fila_lev and fila_lev.total > 0:
                total_con_lev = metricas.total_sitios + fila_lev.total
                levantamiento_info = {
                    "total": fila_lev.total,
                    "porcentaje": round((fila_lev.total / total_con_lev) * 100, 1) if total_con_lev > 0 else 0,
                }

        mejor_usuario_data = None
        if usuarios:
            usuarios_con_kpi = [
                u for u in usuarios
                if (u.metricas_generales.entregas_a_tiempo_compromiso + u.metricas_generales.entregas_tarde_compromiso) > 0
            ]
            if usuarios_con_kpi:
                mejor_user = max(usuarios_con_kpi, key=lambda u: u.metricas_generales.porcentaje_a_tiempo_compromiso)
                mejor_usuario_data = {
                    "nombre": mejor_user.nombre,
                    "ofertas": mejor_user.metricas_generales.total_ofertas,
                    "porcentaje_interno": mejor_user.metricas_generales.porcentaje_a_tiempo_interno,
                    "porcentaje_compromiso": mejor_user.metricas_generales.porcentaje_a_tiempo_compromiso,
                }

        total_entregas_interno = metricas.entregas_a_tiempo_interno + metricas.entregas_tarde_interno
        total_entregas_compromiso = metricas.entregas_a_tiempo_compromiso + metricas.entregas_tarde_compromiso

        score_config = await self._get_score_config(conn)

        usuarios_con_score = []
        for usuario in usuarios:
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
                total_sitios=usuario.metricas_generales.total_sitios,
                total_sitios_entregados=usuario.metricas_generales.total_sitios_entregados,
                oportunidades_multisitio=usuario.metricas_generales.oportunidades_multisitio,
            )

            score = calcular_score_usuario(metrica_usuario, score_config)
            metrica_usuario.score = score

            if metrica_usuario.retrabajados > 0:
                motivo_usuario, _ = await self.get_motivo_retrabajo_principal(
                    conn, filtros, user_id=metrica_usuario.usuario_id
                )
                score.motivo_retrabajo_principal = motivo_usuario

            usuarios_con_score.append(metrica_usuario)

        categorias = {
            "alta_complejidad": [u for u in usuarios_con_score if u.score and u.score.categoria == "alta_complejidad"],
            "eficiencia": [u for u in usuarios_con_score if u.score and u.score.categoria == "eficiencia"],
            "evaluacion": [u for u in usuarios_con_score if u.score and u.score.categoria == "evaluacion"],
        }
        for cat in categorias.values():
            cat.sort(key=lambda u: u.score.score_final if u.score else 0, reverse=True)

        diferencia = metricas.total_solicitudes - metricas.total_ofertas - metricas.en_espera
        partes_explicacion = []
        if metricas.canceladas > 0:
            partes_explicacion.append(f"{metricas.canceladas} canceladas")
        if metricas.no_viables > 0:
            partes_explicacion.append(f"{metricas.no_viables} no viables")
        if metricas.sin_fecha_entrega > 0:
            partes_explicacion.append(f"{metricas.sin_fecha_entrega} sin fecha")
        diferencia_explicacion = ", ".join(partes_explicacion)

        tecnologias_detalle = []
        mejor_tecnologia = None
        peor_tecnologia = None

        if metricas_tecnologia:
            for tech in metricas_tecnologia:
                if tech.total_solicitudes > 0:
                    tecnologias_detalle.append({
                        "nombre": tech.nombre,
                        "solicitudes": tech.total_solicitudes,
                        "ofertas": tech.total_ofertas,
                        "total_sitios": tech.total_sitios,
                        "pct_interno": tech.porcentaje_a_tiempo_interno,
                        "pct_compromiso": tech.porcentaje_a_tiempo_compromiso,
                    })
            tecnologias_detalle.sort(key=lambda x: x["solicitudes"], reverse=True)

            techs_evaluables = [t for t in tecnologias_detalle if t["ofertas"] >= 5]
            if techs_evaluables:
                mejor_tecnologia = max(techs_evaluables, key=lambda x: x["pct_compromiso"])
                peor_tecnologia = min(techs_evaluables, key=lambda x: x["pct_compromiso"])
                if mejor_tecnologia == peor_tecnologia:
                    peor_tecnologia = None

        delta = relativedelta(filtros.fecha_fin, filtros.fecha_inicio)
        meses_en_rango = delta.years * 12 + delta.months + 1
        mostrar_estacionalidad = meses_en_rango > 6
        mejor_mes = None
        peor_mes = None

        meses_nombres_full = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
                              'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']

        if mostrar_estacionalidad and resumen_mensual:
            meses_data = []
            fila_a_tiempo = resumen_mensual.get("entregas_a_tiempo_compromiso")
            fila_tarde = resumen_mensual.get("entregas_tarde_compromiso")

            if fila_a_tiempo and fila_tarde:
                for mes in fila_a_tiempo.valores.keys():
                    a_tiempo = fila_a_tiempo.valores.get(mes, 0) or 0
                    tarde = fila_tarde.valores.get(mes, 0) or 0
                    total = a_tiempo + tarde
                    if total >= 5:
                        pct = round((a_tiempo / total) * 100, 1) if total > 0 else 0
                        meses_data.append({
                            "mes": mes,
                            "nombre": meses_nombres_full[mes],
                            "pct_compromiso": pct,
                            "total": total,
                        })

            if meses_data:
                mejor_mes = max(meses_data, key=lambda x: x["pct_compromiso"])
                peor_mes = min(meses_data, key=lambda x: x["pct_compromiso"])
                if mejor_mes["mes"] == peor_mes["mes"]:
                    peor_mes = None

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
            total_retrabajos=metricas.retrabajos,
            porcentaje_retrabajos=round((metricas.retrabajos / metricas.total_sitios) * 100, 1) if metricas.total_sitios > 0 else 0,
            motivo_retrabajo_principal=motivo_retrabajo_principal[0],
            conteo_motivo_principal=motivo_retrabajo_principal[1],
            categorias_usuarios=categorias,
            mostrar_nota_alta_complejidad=len(categorias["alta_complejidad"]) > 0,
            ratio_licitaciones_global=round((metricas.licitaciones / metricas.total_solicitudes * 100) if metricas.total_solicitudes > 0 else 0, 1),
            umbral_licitaciones_pct=score_config.umbral_ratio_licitaciones * 100,
            sin_fecha_sistema=metricas.sin_fecha_entrega,
            diferencia_explicacion=diferencia_explicacion,
            tecnologias_detalle=tecnologias_detalle,
            mejor_tecnologia=mejor_tecnologia,
            peor_tecnologia=peor_tecnologia,
            mostrar_estacionalidad=mostrar_estacionalidad,
            mejor_mes=mejor_mes,
            peor_mes=peor_mes,
            meses_en_rango=meses_en_rango,
            total_sitios_global=metricas.total_sitios,
            oportunidades_multisitio_global=metricas.oportunidades_multisitio,
            ganadas=metricas.ganadas,
            sim_adicionales_count=metricas.sim_adicionales_count,
            levantamiento_info=levantamiento_info,
            motivos_cierre=motivos_cierre or [],
        )

    async def get_resumen_mensual(self, conn, filtros: FiltrosReporte) -> Dict[str, FilaMensual]:
        cats = await self.db.get_report_catalog_ids(conn)
        rows = await self.db.get_report_resumen_mensual(conn, asdict(filtros), cats)

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
            'tiempo_promedio',
            'en_espera',
            'canceladas',
            'no_viables',
            'perdidas',
            'extraordinarias',
            'versiones',
            'retrabajos',
            'total_sitios',
        ]

        resultado = {nombre: FilaMensual(metrica=nombre) for nombre in metricas_nombres}

        for row in rows:
            mes = row['mes']

            total_kpi_interno = (row['entregas_a_tiempo_interno'] or 0) + (row['entregas_tarde_interno'] or 0)
            pct_interno = round((row['entregas_a_tiempo_interno'] or 0) / total_kpi_interno * 100, 1) if total_kpi_interno > 0 else 0

            total_kpi_compromiso = (row['entregas_a_tiempo_compromiso'] or 0) + (row['entregas_tarde_compromiso'] or 0)
            pct_compromiso = round((row['entregas_a_tiempo_compromiso'] or 0) / total_kpi_compromiso * 100, 1) if total_kpi_compromiso > 0 else 0
            pct_tarde = round((row['entregas_tarde_compromiso'] or 0) / total_kpi_compromiso * 100, 1) if total_kpi_compromiso > 0 else 0

            resultado['solicitudes_recibidas'].valores[mes] = row['solicitudes_recibidas'] or 0
            resultado['ofertas_generadas'].valores[mes] = row['ofertas_generadas'] or 0

            resultado['porcentaje_en_plazo_interno'].valores[mes] = pct_interno
            resultado['porcentaje_fuera_plazo_interno'].valores[mes] = round(100 - pct_interno, 1) if total_kpi_interno > 0 else 0
            resultado['entregas_a_tiempo_interno'].valores[mes] = row['entregas_a_tiempo_interno'] or 0
            resultado['entregas_tarde_interno'].valores[mes] = row['entregas_tarde_interno'] or 0

            resultado['porcentaje_en_plazo_compromiso'].valores[mes] = pct_compromiso
            resultado['porcentaje_fuera_plazo_compromiso'].valores[mes] = pct_tarde
            resultado['entregas_a_tiempo_compromiso'].valores[mes] = row['entregas_a_tiempo_compromiso'] or 0
            resultado['entregas_tarde_compromiso'].valores[mes] = row['entregas_tarde_compromiso'] or 0

            resultado['tiempo_promedio'].valores[mes] = round(float(row['tiempo_promedio'] or 0) / 24, 1)
            resultado['en_espera'].valores[mes] = row['en_espera'] or 0
            resultado['canceladas'].valores[mes] = row['canceladas'] or 0
            resultado['no_viables'].valores[mes] = row['no_viables'] or 0
            resultado['perdidas'].valores[mes] = row['perdidas'] or 0
            resultado['extraordinarias'].valores[mes] = row['extraordinarias'] or 0
            resultado['versiones'].valores[mes] = row['versiones'] or 0
            resultado['retrabajos'].valores[mes] = row['retrabajos'] or 0
            resultado['total_sitios'].valores[mes] = row['total_sitios'] or 0

        for nombre, fila in resultado.items():
            if nombre in ('porcentaje_en_plazo_interno', 'porcentaje_fuera_plazo_interno',
                          'porcentaje_en_plazo_compromiso', 'porcentaje_fuera_plazo_compromiso',
                          'tiempo_promedio'):
                valores = [v for v in fila.valores.values() if v > 0]
                fila.total = round(sum(valores) / len(valores), 1) if valores else 0
            else:
                fila.total = sum(fila.valores.values())

        return resultado

    # =========================================================================
    # DATOS PARA GRÁFICAS
    # =========================================================================

    async def get_clientes_alta_iteracion(
        self, conn, filtros: FiltrosReporte, umbral: int = 3
    ) -> List[Dict]:
        return await self.db.get_clientes_alta_iteracion(conn, asdict(filtros), umbral)

    async def get_all_report_data(self, conn, filtros: FiltrosReporte) -> dict:
        return {
            'metricas': await self.get_metricas_generales(conn, filtros),
            'tecnologias': await self.get_metricas_por_tecnologia(conn, filtros),
            'contabilizacion': await self.get_tabla_contabilizacion(conn, filtros),
            'usuarios': await self.get_detalle_por_usuario(conn, filtros),
            'mensual': await self.get_resumen_mensual(conn, filtros),
            'motivos_cierre': await self.db.get_chart_motivos_cierre(conn, asdict(filtros)),
            'alta_iteracion': await self.get_clientes_alta_iteracion(conn, filtros),
        }

    async def get_datos_graficas(
        self,
        conn,
        filtros: FiltrosReporte,
        metricas: Optional[MetricasGenerales] = None,
    ) -> Dict[str, DatosGrafica]:
        graficas = {}
        graficas['estatus_pie'] = await self._get_grafica_estatus(conn, filtros)
        graficas['mensual_bar'] = await self._get_grafica_mensual(conn, filtros)
        graficas['tecnologia_pie'] = await self._get_grafica_tecnologia(conn, filtros)
        graficas['motivos_bar'] = await self._get_grafica_motivos(conn, filtros)
        graficas['kpi_bar'] = await self._get_grafica_kpi(conn, filtros, metricas)
        return graficas

    async def _get_grafica_estatus(self, conn, filtros: FiltrosReporte) -> DatosGrafica:
        rows = await self.db.get_chart_estatus(conn, asdict(filtros))
        return DatosGrafica(
            tipo='doughnut',
            labels=[r['nombre'] for r in rows],
            datasets=[{
                'data': [r['total'] for r in rows],
                'backgroundColor': [r['color_hex'] or '#6B7280' for r in rows],
            }],
        )

    async def _get_grafica_mensual(self, conn, filtros: FiltrosReporte) -> DatosGrafica:
        rows = await self.db.get_chart_mensual(conn, asdict(filtros))
        meses_nombres = ['', 'Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun',
                         'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
        return DatosGrafica(
            tipo='bar',
            labels=[meses_nombres[r['mes']] for r in rows],
            datasets=[{
                'label': 'Solicitudes',
                'data': [r['total'] for r in rows],
                'backgroundColor': '#00BABB',
            }],
        )

    async def _get_grafica_tecnologia(self, conn, filtros: FiltrosReporte) -> DatosGrafica:
        rows = await self.db.get_chart_tecnologia(conn, asdict(filtros))
        colores = ['#00BABB', '#3B82F6', '#10B981', '#F59E0B', '#8B5CF6']
        return DatosGrafica(
            tipo='pie',
            labels=[r['nombre'] for r in rows],
            datasets=[{
                'data': [r['total'] for r in rows],
                'backgroundColor': colores[:len(rows)],
            }],
        )

    async def _get_grafica_kpi(
        self,
        conn,
        filtros: FiltrosReporte,
        metricas: Optional[MetricasGenerales] = None,
    ) -> DatosGrafica:
        if metricas is None:
            metricas = await self.get_metricas_generales(conn, filtros)
        return DatosGrafica(
            tipo='bar',
            labels=['Entregas'],
            datasets=[
                {'label': 'A Tiempo', 'data': [metricas.entregas_a_tiempo_compromiso], 'backgroundColor': '#10B981'},
                {'label': 'Fuera de Plazo', 'data': [metricas.entregas_tarde_compromiso], 'backgroundColor': '#EF4444'},
            ],
            opciones={'indexAxis': 'y'},
        )

    async def _get_grafica_motivos(self, conn, filtros: FiltrosReporte) -> DatosGrafica:
        rows = await self.db.get_chart_motivos_cierre(conn, asdict(filtros))
        colores_categoria = {
            'Técnico': '#3B82F6',
            'Regulatorio': '#8B5CF6',
            'Económico': '#F59E0B',
            'Competencia': '#EF4444',
            'Otros': '#6B7280',
        }
        return DatosGrafica(
            tipo='bar',
            labels=[r['motivo'][:30] + '...' if len(r['motivo']) > 30 else r['motivo'] for r in rows],
            datasets=[{
                'label': 'Cantidad',
                'data': [r['total'] for r in rows],
                'backgroundColor': [colores_categoria.get(r['categoria'], '#6B7280') for r in rows],
            }],
            opciones={'indexAxis': 'y'},
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
