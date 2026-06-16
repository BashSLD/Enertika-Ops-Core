# modules/simulacion/report_db_service.py
"""
Queries SQL para el módulo de Reportes de Simulación.
Solo usado por ReportesSimulacionService.

Fase 4 decouple FV/BESS + Montaje de oferta (2026-06-16)
-------------------------------------------------------
Los KPI de entrega/cumplimiento se leen de `tb_entregas_componente`
(`componente='FV'`, área SIMULACION), no de `tb_sitios_oportunidad`. Esto
desacopla el KPI de FV del de BESS en oportunidades híbridas. Cada query de KPI:
  - JOIN a `tb_oportunidades` para filtrar `excluir_kpis_simulacion` (la tabla de
    componentes no replica ese flag; Monitoreo/Montaje quedan fuera de KPIs).
  - usa `e.cuenta_para_kpi = true` en vez del hardcode `IN (entregado, perdido,
    ganada)` (mismo conjunto, resuelto desde el catálogo).
La sección BESS (`get_report_seccion_bess`) reporta esos componentes por separado.

Los conteos de negocio/volumen (total_solicitudes, en_espera, canceladas,
no_viables, ganadas, distribuciones) NO cambian de fuente ni aplican
`cuenta_para_kpi`/exclusión: siguen contando desde oportunidades/sitios.

Los índices de parámetros se generan con `_P` (builder), eliminando el frágil
cálculo manual `len(params) - N`.
"""

from typing import Dict, List, Any, Optional
from uuid import UUID
import logging

logger = logging.getLogger("ReportDBService")


class _P:
    """Builder de parámetros posicionales para asyncpg.

    `add(valor)` registra el valor y devuelve su placeholder (`$N`), evitando el
    cálculo manual de índices. `values` se pasa con `*` a `conn.fetch`.
    """

    def __init__(self) -> None:
        self.values: List[Any] = []

    def add(self, value: Any) -> str:
        self.values.append(value)
        return f"${len(self.values)}"


# Fragmentos SQL reutilizados en las queries de KPI (entrega/cumplimiento).
_KPI_STATUS = "e.cuenta_para_kpi = true"
_NO_EXCLUIDA = "COALESCE(o.excluir_kpis_simulacion, false) = false"

# Las 4 columnas de conteo dual (interno/compromiso, a tiempo/tarde) sobre los
# componentes (`ec`). Definición única reutilizada por todas las queries de KPI.
_KPI_COUNT_COLS = (
    "COUNT(*) FILTER (WHERE ec.kpi_status_interno = 'Entrega a tiempo') as entregas_a_tiempo_interno, "
    "COUNT(*) FILTER (WHERE ec.kpi_status_interno = 'Entrega tarde') as entregas_tarde_interno, "
    "COUNT(*) FILTER (WHERE ec.kpi_status_compromiso = 'Entrega a tiempo') as entregas_a_tiempo_compromiso, "
    "COUNT(*) FILTER (WHERE ec.kpi_status_compromiso = 'Entrega tarde') as entregas_tarde_compromiso"
)


def _componente_kpi_from(where: str, componente: str) -> str:
    """Esqueleto FROM/JOIN/WHERE para leer KPIs de un componente desde
    `tb_entregas_componente`: JOIN a oportunidades + catálogo de estatus, filtros
    de la query (`where`), componente, estatus KPI y exclusión. `componente` es un
    literal controlado ('FV' | 'BESS'), no entrada de usuario.
    """
    return f"""FROM tb_entregas_componente ec
                JOIN tb_oportunidades o ON ec.id_oportunidad = o.id_oportunidad
                JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
                {where}
                  AND ec.componente = '{componente}'
                  AND {_KPI_STATUS}
                  AND {_NO_EXCLUIDA}"""


class ReportDBService:
    """Queries de reporte de simulación. Stateless, instanciable sin args."""

    def _build_where(self, p: _P, filters: Dict[str, Any]) -> str:
        """Cláusula WHERE dinámica para reportes sobre los alias `o` y `e`.

        filters keys: fecha_inicio, fecha_fin, id_tecnologia, id_tipo_solicitud,
        id_estatus, responsable_id. Registra los params en `p`.
        """
        conditions = [
            "e.modulo_aplicable = 'SIMULACION'",
            f"o.fecha_solicitud >= {p.add(filters['fecha_inicio'])}::timestamptz",
            f"o.fecha_solicitud < {p.add(filters['fecha_fin'])}::timestamptz + INTERVAL '1 day'",
        ]
        if filters.get('id_tecnologia'):
            conditions.append(f"o.id_tecnologia = {p.add(filters['id_tecnologia'])}")
        if filters.get('id_tipo_solicitud'):
            conditions.append(f"o.id_tipo_solicitud = {p.add(filters['id_tipo_solicitud'])}")
        if filters.get('id_estatus'):
            conditions.append(f"o.id_estatus_global = {p.add(filters['id_estatus'])}")
        if filters.get('responsable_id'):
            conditions.append(f"o.responsable_simulacion_id = {p.add(filters['responsable_id'])}")
        return "WHERE " + " AND ".join(conditions)

    async def get_report_catalog_ids(self, conn) -> Dict[str, Any]:
        estatus = await conn.fetch(
            "SELECT id, LOWER(nombre) as nombre FROM tb_cat_estatus_oportunidades WHERE activo = true"
        )
        tipos = await conn.fetch(
            "SELECT id, LOWER(codigo_interno) as codigo FROM tb_cat_tipos_solicitud WHERE activo = true"
        )
        motivos_nv = await conn.fetch(
            "SELECT id FROM tb_cat_motivos_cierre WHERE es_no_viable = TRUE AND activo = TRUE"
        )
        return {
            "estatus": {row['nombre']: row['id'] for row in estatus},
            "tipos": {row['codigo']: row['id'] for row in tipos},
            "motivos_no_viables": [row['id'] for row in motivos_nv],
        }

    async def get_report_metricas_generales_row(self, conn, filters: Dict[str, Any], cats: Dict) -> Optional[Dict[str, Any]]:
        p = _P()
        where = self._build_where(p, filters)

        ph_lev = p.add(cats['tipos'].get('levantamiento'))
        ph_cancelado = p.add(cats['estatus'].get('cancelado'))
        ph_ganada = p.add(cats['estatus'].get('ganada'))
        ph_pendiente = p.add(cats['estatus'].get('pendiente'))
        ph_proceso = p.add(cats['estatus'].get('en proceso'))
        ph_revision = p.add(cats['estatus'].get('en revisión'))
        ph_no_viables = p.add(cats.get('motivos_no_viables', []))

        query = f"""
            WITH base AS (
                SELECT
                    s.id_oportunidad, s.id_sitio, s.es_retrabajo,
                    o.parent_id, o.clasificacion_solicitud, o.es_licitacion,
                    o.id_tipo_solicitud, o.id_estatus_global, o.id_motivo_cierre,
                    o.cantidad_sitios, 'sitio_normal' AS origen
                FROM tb_sitios_oportunidad s
                JOIN tb_oportunidades o ON s.id_oportunidad = o.id_oportunidad
                JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
                {where}

                UNION ALL

                SELECT
                    sa.id_oportunidad, sa.id AS id_sitio, false AS es_retrabajo,
                    o.parent_id, o.clasificacion_solicitud, o.es_licitacion,
                    o.id_tipo_solicitud, o.id_estatus_global, o.id_motivo_cierre,
                    o.cantidad_sitios, 'sim_adicional' AS origen
                FROM tb_simulaciones_adicionales sa
                JOIN tb_oportunidades o ON sa.id_oportunidad = o.id_oportunidad
                JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
                {where}
            ),
            agg_base AS (
                SELECT
                    COUNT(DISTINCT CASE WHEN id_tipo_solicitud != {ph_lev} THEN id_oportunidad END) as total_solicitudes,
                    COUNT(DISTINCT CASE WHEN id_estatus_global IN ({ph_pendiente}, {ph_proceso}, {ph_revision}) THEN id_oportunidad END) as en_espera,
                    COUNT(DISTINCT CASE WHEN id_estatus_global = {ph_cancelado} THEN id_oportunidad END) as canceladas,
                    COUNT(DISTINCT CASE WHEN id_estatus_global = {ph_cancelado} AND id_motivo_cierre = ANY({ph_no_viables}::integer[]) THEN id_oportunidad END) as no_viables,
                    COUNT(DISTINCT CASE WHEN clasificacion_solicitud = 'EXTRAORDINARIO' THEN id_oportunidad END) as extraordinarias,
                    COUNT(DISTINCT CASE WHEN parent_id IS NOT NULL THEN id_oportunidad END) as versiones,
                    COUNT(CASE WHEN es_retrabajo = TRUE THEN id_sitio END) as retrabajos,
                    COUNT(DISTINCT CASE WHEN es_licitacion = TRUE THEN COALESCE(parent_id, id_oportunidad) END) as licitaciones,
                    COUNT(CASE WHEN id_tipo_solicitud != {ph_lev} THEN id_sitio END) as total_sitios,
                    COUNT(DISTINCT CASE WHEN cantidad_sitios > 1 AND id_tipo_solicitud != {ph_lev} THEN id_oportunidad END) as oportunidades_multisitio,
                    COUNT(DISTINCT CASE WHEN id_estatus_global = {ph_ganada} AND id_tipo_solicitud != {ph_lev} THEN id_oportunidad END) as ganadas,
                    COUNT(CASE WHEN origen = 'sim_adicional' THEN id_sitio END) as sim_adicionales_count
                FROM base
            ),
            agg_fv AS (
                SELECT
                    COUNT(*) as total_ofertas,
                    COUNT(*) as total_sitios_entregados,
                    {_KPI_COUNT_COLS},
                    COUNT(DISTINCT ec.id_oportunidad) FILTER (WHERE ec.fecha_entrega IS NULL) as sin_fecha_entrega
                {_componente_kpi_from(where, 'FV')}
            ),
            agg_tiempo AS (
                SELECT AVG(o.tiempo_elaboracion_horas) as tiempo_promedio_horas
                FROM tb_sitios_oportunidad s
                JOIN tb_oportunidades o ON s.id_oportunidad = o.id_oportunidad
                JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
                {where}
                  AND o.tiempo_elaboracion_horas IS NOT NULL
                  AND {_KPI_STATUS}
                  AND {_NO_EXCLUIDA}
                  AND o.id_tipo_solicitud != {ph_lev}
            )
            SELECT ab.*, af.*, tt.tiempo_promedio_horas
            FROM agg_base ab, agg_fv af, agg_tiempo tt
        """
        row = await conn.fetchrow(query, *p.values)
        return dict(row) if row else None

    async def get_report_motivo_retrabajo(self, conn, filters: Dict[str, Any], user_id: Optional[UUID] = None) -> Optional[Dict[str, Any]]:
        p = _P()
        where = self._build_where(p, filters)
        if user_id:
            where += f" AND o.responsable_simulacion_id = {p.add(user_id)}"

        query = f"""
            SELECT mr.nombre as motivo, COUNT(*) as conteo
            FROM tb_sitios_oportunidad s
            JOIN tb_oportunidades o ON s.id_oportunidad = o.id_oportunidad
            JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
            LEFT JOIN tb_cat_motivos_retrabajo mr ON s.id_motivo_retrabajo = mr.id
            {where}
            AND s.es_retrabajo = TRUE AND s.id_motivo_retrabajo IS NOT NULL
            GROUP BY mr.nombre ORDER BY conteo DESC LIMIT 1
        """
        row = await conn.fetchrow(query, *p.values)
        return dict(row) if row else None

    async def get_report_tiempo_promedio_global(self, conn, user_id: UUID, filters: Dict[str, Any]) -> Optional[float]:
        p = _P()
        where = self._build_where(p, filters)
        where += f" AND o.responsable_simulacion_id = {p.add(user_id)}"

        query = f"""
            WITH tiempos AS (
                SELECT tiempo_elaboracion_horas / 24 as dias
                FROM tb_oportunidades o
                JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
                {where}
                AND o.tiempo_elaboracion_horas IS NOT NULL
                AND {_KPI_STATUS}
                AND {_NO_EXCLUIDA}
                AND o.id_tipo_solicitud != (
                    SELECT id FROM tb_cat_tipos_solicitud WHERE LOWER(nombre) = 'levantamiento'
                )
            )
            SELECT AVG(dias) as dias_promedio
            FROM tiempos
            WHERE dias <= (SELECT PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY dias) FROM tiempos)
        """
        row = await conn.fetchrow(query, *p.values)
        return row['dias_promedio'] if row and row['dias_promedio'] else None

    async def get_report_metricas_tech(self, conn, filters: Dict[str, Any], cats: Dict) -> List[Dict[str, Any]]:
        p = _P()
        where = self._build_where(p, filters)
        ph_lev = p.add(cats['tipos'].get('levantamiento'))

        query = f"""
            WITH base AS (
                SELECT
                    o.id_tecnologia, s.id_oportunidad, s.id_sitio,
                    s.es_retrabajo, o.parent_id, o.clasificacion_solicitud, o.es_licitacion,
                    o.id_tipo_solicitud, o.potencia_cierre_fv_kwp, o.capacidad_cierre_bess_kwh
                FROM tb_sitios_oportunidad s
                JOIN tb_oportunidades o ON s.id_oportunidad = o.id_oportunidad
                JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
                {where}

                UNION ALL

                SELECT
                    o.id_tecnologia, sa.id_oportunidad, sa.id AS id_sitio,
                    false AS es_retrabajo, o.parent_id, o.clasificacion_solicitud, o.es_licitacion,
                    o.id_tipo_solicitud, sa.potencia_cierre_fv_kwp, sa.capacidad_cierre_bess_kwh
                FROM tb_simulaciones_adicionales sa
                JOIN tb_oportunidades o ON sa.id_oportunidad = o.id_oportunidad
                JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
                {where}
            ),
            agg_base AS (
                SELECT
                    id_tecnologia,
                    COUNT(DISTINCT CASE WHEN id_tipo_solicitud != {ph_lev} THEN id_oportunidad END) as total_solicitudes,
                    COUNT(DISTINCT id_oportunidad) FILTER (WHERE clasificacion_solicitud = 'EXTRAORDINARIO') as extraordinarias,
                    COUNT(DISTINCT id_oportunidad) FILTER (WHERE parent_id IS NOT NULL) as versiones,
                    COUNT(*) FILTER (WHERE es_retrabajo = TRUE) as retrabajos,
                    COUNT(DISTINCT COALESCE(parent_id, id_oportunidad)) FILTER (WHERE es_licitacion = TRUE) as licitaciones,
                    COALESCE(SUM(DISTINCT potencia_cierre_fv_kwp), 0) as potencia_total_kwp,
                    COALESCE(SUM(DISTINCT capacidad_cierre_bess_kwh), 0) as capacidad_total_kwh,
                    COUNT(id_sitio) as total_sitios
                FROM base
                GROUP BY id_tecnologia
            ),
            agg_fv AS (
                SELECT
                    o.id_tecnologia,
                    COUNT(*) as total_ofertas,
                    {_KPI_COUNT_COLS}
                {_componente_kpi_from(where, 'FV')}
                GROUP BY o.id_tecnologia
            ),
            agg_tiempo AS (
                SELECT o.id_tecnologia, AVG(o.tiempo_elaboracion_horas) as tiempo_promedio_horas
                FROM tb_sitios_oportunidad s
                JOIN tb_oportunidades o ON s.id_oportunidad = o.id_oportunidad
                JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
                {where}
                  AND o.tiempo_elaboracion_horas IS NOT NULL
                  AND {_KPI_STATUS}
                  AND {_NO_EXCLUIDA}
                  AND o.id_tipo_solicitud != {ph_lev}
                GROUP BY o.id_tecnologia
            )
            SELECT
                t.id as id_tecnologia, t.nombre,
                COALESCE(ab.total_solicitudes, 0) as total_solicitudes,
                COALESCE(af.total_ofertas, 0) as total_ofertas,
                COALESCE(af.entregas_a_tiempo_interno, 0) as entregas_a_tiempo_interno,
                COALESCE(af.entregas_tarde_interno, 0) as entregas_tarde_interno,
                COALESCE(af.entregas_a_tiempo_compromiso, 0) as entregas_a_tiempo_compromiso,
                COALESCE(af.entregas_tarde_compromiso, 0) as entregas_tarde_compromiso,
                COALESCE(ab.extraordinarias, 0) as extraordinarias,
                COALESCE(ab.versiones, 0) as versiones,
                COALESCE(ab.retrabajos, 0) as retrabajos,
                COALESCE(ab.licitaciones, 0) as licitaciones,
                tt.tiempo_promedio_horas,
                COALESCE(ab.potencia_total_kwp, 0) as potencia_total_kwp,
                COALESCE(ab.capacidad_total_kwh, 0) as capacidad_total_kwh,
                COALESCE(ab.total_sitios, 0) as total_sitios
            FROM tb_cat_tecnologias t
            LEFT JOIN agg_base ab ON ab.id_tecnologia = t.id
            LEFT JOIN agg_fv af ON af.id_tecnologia = t.id
            LEFT JOIN agg_tiempo tt ON tt.id_tecnologia = t.id
            WHERE t.activo = true
            ORDER BY t.id
        """
        rows = await conn.fetch(query, *p.values)
        return [dict(r) for r in rows]

    async def get_report_seccion_bess(self, conn, filters: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Sección BESS (Almacenamiento): cuántos componentes BESS se entregaron
        a tiempo / tarde. Separada de los KPIs de Simulación (FV). Aplica el mismo
        filtro de exclusión y `cuenta_para_kpi` que los KPIs de FV.
        """
        p = _P()
        where = self._build_where(p, filters)

        query = f"""
            SELECT
                COUNT(*) as total,
                {_KPI_COUNT_COLS},
                COUNT(DISTINCT ec.id_oportunidad) FILTER (WHERE ec.fecha_entrega IS NULL) as sin_fecha
            {_componente_kpi_from(where, 'BESS')}
        """
        row = await conn.fetchrow(query, *p.values)
        return dict(row) if row else None

    async def get_chart_motivos_cierre(self, conn, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        p = _P()
        where = self._build_where(p, filters)

        query = f"""
            SELECT m.motivo, m.categoria, COUNT(*) as total
            FROM tb_oportunidades o
            JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
            JOIN tb_cat_motivos_cierre m ON o.id_motivo_cierre = m.id
            {where}
            AND o.id_motivo_cierre IS NOT NULL
            AND LOWER(e.nombre) IN ('cancelado', 'perdido')
            GROUP BY m.id, m.motivo, m.categoria
            ORDER BY total DESC
            LIMIT 10
        """
        rows = await conn.fetch(query, *p.values)
        return [dict(r) for r in rows]

    async def get_report_tabla_contabilizacion(self, conn, filters: Dict[str, Any], cats: Dict) -> List[Dict[str, Any]]:
        p = _P()
        where = self._build_where(p, filters)
        ph_lev = p.add(cats['tipos'].get('levantamiento'))

        query = f"""
            WITH base AS (
                SELECT o.id_tipo_solicitud, s.id_sitio, o.id_oportunidad, o.es_licitacion, o.parent_id
                FROM tb_sitios_oportunidad s
                JOIN tb_oportunidades o ON s.id_oportunidad = o.id_oportunidad
                JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
                {where}

                UNION ALL

                SELECT o.id_tipo_solicitud, sa.id AS id_sitio, o.id_oportunidad, o.es_licitacion, o.parent_id
                FROM tb_simulaciones_adicionales sa
                JOIN tb_oportunidades o ON sa.id_oportunidad = o.id_oportunidad
                JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
                {where}
            ),
            agg_base AS (
                SELECT
                    id_tipo_solicitud,
                    COUNT(id_sitio) as total,
                    COUNT(DISTINCT CASE WHEN es_licitacion = TRUE THEN COALESCE(parent_id, id_oportunidad) END) as licitaciones
                FROM base
                GROUP BY id_tipo_solicitud
            ),
            agg_fv AS (
                SELECT
                    o.id_tipo_solicitud,
                    {_KPI_COUNT_COLS},
                    COUNT(DISTINCT ec.id_oportunidad) FILTER (WHERE ec.fecha_entrega IS NULL) as sin_fecha
                {_componente_kpi_from(where, 'FV')}
                GROUP BY o.id_tipo_solicitud
            )
            SELECT
                ts.id as id_tipo_solicitud, ts.nombre, ts.codigo_interno,
                COALESCE(ab.total, 0) as total,
                COALESCE(af.entregas_a_tiempo_interno, 0) as entregas_a_tiempo_interno,
                COALESCE(af.entregas_tarde_interno, 0) as entregas_tarde_interno,
                COALESCE(af.entregas_a_tiempo_compromiso, 0) as entregas_a_tiempo_compromiso,
                COALESCE(af.entregas_tarde_compromiso, 0) as entregas_tarde_compromiso,
                COALESCE(af.sin_fecha, 0) as sin_fecha,
                COALESCE(ab.licitaciones, 0) as licitaciones,
                (ts.id = {ph_lev}) as es_levantamiento
            FROM tb_cat_tipos_solicitud ts
            LEFT JOIN agg_base ab ON ab.id_tipo_solicitud = ts.id
            LEFT JOIN agg_fv af ON af.id_tipo_solicitud = ts.id
            WHERE COALESCE(ab.total, 0) > 0
            ORDER BY ts.id
        """
        rows = await conn.fetch(query, *p.values)
        return [dict(r) for r in rows]

    async def get_report_users_active(self, conn, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        p = _P()
        where = self._build_where(p, filters)
        query = f"""
            SELECT DISTINCT u.id_usuario, u.nombre
            FROM tb_usuarios u
            INNER JOIN tb_oportunidades o ON o.responsable_simulacion_id = u.id_usuario
            INNER JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
            {where}
            ORDER BY u.nombre
        """
        rows = await conn.fetch(query, *p.values)
        return [dict(r) for r in rows]

    async def get_report_oportunidades_usuario(self, conn, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Listado (detalle) de oportunidades del usuario. KPI por fila derivados de
        los sitios. Las oportunidades excluidas (Monitoreo/Montaje) muestran '-' en
        sus columnas KPI para ser consistentes con los agregados — el `kpi_status` del
        sitio NO se limpia al entrar a Montaje (la exclusión es a nivel oportunidad),
        por eso se filtra aquí explícitamente con `excluir_kpis_simulacion`.
        """
        p = _P()
        where = self._build_where(p, filters)
        query = f"""
            SELECT * FROM (
                SELECT
                    o.id_oportunidad, o.op_id_estandar, o.nombre_proyecto, o.cliente_nombre,
                    o.es_licitacion, o.clasificacion_solicitud, o.parent_id, o.cantidad_sitios,
                    o.fecha_solicitud, o.fecha_entrega_simulacion,
                    o.deadline_calculado,
                    o.deadline_negociado,
                    (o.deadline_negociado < o.deadline_calculado) AS compromiso_adelantado,
                    e.nombre AS estatus_nombre,
                    ts.nombre AS tipo_solicitud,
                    t.nombre AS tecnologia,
                    COUNT(s.id_sitio) AS sitios_count,
                    CASE
                        WHEN COALESCE(o.excluir_kpis_simulacion, false) THEN '-'
                        WHEN COUNT(CASE WHEN s.kpi_status_interno = 'Entrega tarde' THEN 1 END) > 0 THEN 'Tarde'
                        WHEN COUNT(CASE WHEN s.kpi_status_interno = 'Entrega a tiempo' THEN 1 END) = COUNT(s.id_sitio)
                             AND COUNT(s.id_sitio) > 0 THEN 'A tiempo'
                        ELSE '-'
                    END AS kpi_interno,
                    CASE
                        WHEN COALESCE(o.excluir_kpis_simulacion, false) THEN '-'
                        WHEN COUNT(CASE WHEN s.kpi_status_compromiso = 'Entrega tarde' THEN 1 END) > 0 THEN 'Tarde'
                        WHEN COUNT(CASE WHEN s.kpi_status_compromiso = 'Entrega a tiempo' THEN 1 END) = COUNT(s.id_sitio)
                             AND COUNT(s.id_sitio) > 0 THEN 'A tiempo'
                        ELSE '-'
                    END AS kpi_compromiso
                FROM tb_oportunidades o
                JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
                JOIN tb_cat_tipos_solicitud ts ON o.id_tipo_solicitud = ts.id
                LEFT JOIN tb_cat_tecnologias t ON o.id_tecnologia = t.id
                LEFT JOIN tb_sitios_oportunidad s ON o.id_oportunidad = s.id_oportunidad
                {where}
                GROUP BY
                    o.id_oportunidad, o.op_id_estandar, o.nombre_proyecto, o.cliente_nombre,
                    o.es_licitacion, o.clasificacion_solicitud, o.parent_id, o.cantidad_sitios,
                    o.fecha_solicitud, o.fecha_entrega_simulacion,
                    o.deadline_calculado, o.deadline_negociado, o.excluir_kpis_simulacion,
                    e.nombre, ts.nombre, t.nombre
            ) sub
            ORDER BY
                (kpi_compromiso = 'Tarde') DESC,
                fecha_solicitud DESC
        """
        rows = await conn.fetch(query, *p.values)
        return [dict(r) for r in rows]

    async def get_kpi_insights_usuario(self, conn, filters: Dict[str, Any], cats: Dict) -> List[Dict[str, Any]]:
        p = _P()
        where = self._build_where(p, filters)
        ph_lev = p.add(cats['tipos'].get('levantamiento'))

        query = f"""
            WITH fv AS (
                SELECT
                    ec.id_oportunidad, ec.kpi_status_compromiso,
                    o.op_id_estandar, o.nombre_proyecto,
                    o.deadline_negociado, o.deadline_calculado
                {_componente_kpi_from(where, 'FV')}
                  AND o.id_tipo_solicitud != {ph_lev}
            ),
            base AS (
                SELECT
                    id_oportunidad,
                    op_id_estandar,
                    nombre_proyecto,
                    (MIN(deadline_negociado) < MIN(deadline_calculado)) AS compromiso_adelantado,
                    COUNT(*) AS total_sitios,
                    COUNT(*) FILTER (WHERE kpi_status_compromiso = 'Entrega tarde') AS sitios_tarde,
                    COUNT(*) FILTER (WHERE kpi_status_compromiso = 'Entrega a tiempo') AS sitios_a_tiempo
                FROM fv
                GROUP BY id_oportunidad, op_id_estandar, nombre_proyecto
            ),
            totals AS (
                SELECT
                    SUM(sitios_tarde)    AS total_tarde_global,
                    SUM(sitios_a_tiempo) AS total_a_tiempo_global,
                    COUNT(*) FILTER (WHERE compromiso_adelantado) AS casos_compromiso_adelantado
                FROM base
            )
            SELECT b.*, t.total_tarde_global, t.total_a_tiempo_global, t.casos_compromiso_adelantado
            FROM base b, totals t
            ORDER BY b.sitios_tarde DESC
        """
        rows = await conn.fetch(query, *p.values)
        return [dict(r) for r in rows]

    async def get_report_tiempo_promedio_tipo(self, conn, user_id: UUID, filters: Dict[str, Any], cats: Dict) -> Dict[str, float]:
        p = _P()
        where = self._build_where(p, filters)
        ph_user = p.add(user_id)
        ph_lev = p.add(cats['tipos'].get('levantamiento'))

        query = f"""
            SELECT ts.nombre as tipo, AVG(o.tiempo_elaboracion_horas) / 24 as dias_promedio
            FROM tb_oportunidades o
            JOIN tb_cat_tipos_solicitud ts ON o.id_tipo_solicitud = ts.id
            JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
            {where}
            AND o.responsable_simulacion_id = {ph_user}
            AND o.tiempo_elaboracion_horas IS NOT NULL
            AND {_KPI_STATUS}
            AND {_NO_EXCLUIDA}
            AND o.id_tipo_solicitud != {ph_lev}
            GROUP BY ts.nombre HAVING AVG(o.tiempo_elaboracion_horas) IS NOT NULL
        """
        rows = await conn.fetch(query, *p.values)
        return {row['tipo']: round(float(row['dias_promedio']), 1) for row in rows}

    # =========================================================================
    # BATCH QUERIES — Fase 2 optimización
    # Reemplazan 6N queries individuales por 6 queries fijas independientemente
    # del número de usuarios. Retornan filas agrupadas por responsable_simulacion_id
    # para mapear en memoria en el service layer.
    # =========================================================================

    async def get_report_metricas_generales_batch(self, conn, filters: Dict[str, Any], cats: Dict) -> List[Dict[str, Any]]:
        p = _P()
        where = self._build_where(p, filters)
        where_batch = where + " AND o.responsable_simulacion_id IS NOT NULL"

        ph_lev = p.add(cats['tipos'].get('levantamiento'))
        ph_cancelado = p.add(cats['estatus'].get('cancelado'))
        ph_ganada = p.add(cats['estatus'].get('ganada'))
        ph_pendiente = p.add(cats['estatus'].get('pendiente'))
        ph_proceso = p.add(cats['estatus'].get('en proceso'))
        ph_revision = p.add(cats['estatus'].get('en revisión'))
        ph_no_viables = p.add(cats.get('motivos_no_viables', []))

        query = f"""
            WITH base AS (
                SELECT
                    o.responsable_simulacion_id,
                    s.id_oportunidad, s.id_sitio, s.es_retrabajo,
                    o.parent_id, o.clasificacion_solicitud, o.es_licitacion,
                    o.id_tipo_solicitud, o.id_estatus_global, o.id_motivo_cierre,
                    o.cantidad_sitios, 'sitio_normal' AS origen
                FROM tb_sitios_oportunidad s
                JOIN tb_oportunidades o ON s.id_oportunidad = o.id_oportunidad
                JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
                {where_batch}

                UNION ALL

                SELECT
                    o.responsable_simulacion_id,
                    sa.id_oportunidad, sa.id AS id_sitio, false AS es_retrabajo,
                    o.parent_id, o.clasificacion_solicitud, o.es_licitacion,
                    o.id_tipo_solicitud, o.id_estatus_global, o.id_motivo_cierre,
                    o.cantidad_sitios, 'sim_adicional' AS origen
                FROM tb_simulaciones_adicionales sa
                JOIN tb_oportunidades o ON sa.id_oportunidad = o.id_oportunidad
                JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
                {where_batch}
            ),
            agg_base AS (
                SELECT
                    responsable_simulacion_id,
                    COUNT(DISTINCT CASE WHEN id_tipo_solicitud != {ph_lev} THEN id_oportunidad END) as total_solicitudes,
                    COUNT(DISTINCT CASE WHEN id_estatus_global IN ({ph_pendiente}, {ph_proceso}, {ph_revision}) THEN id_oportunidad END) as en_espera,
                    COUNT(DISTINCT CASE WHEN id_estatus_global = {ph_cancelado} THEN id_oportunidad END) as canceladas,
                    COUNT(DISTINCT CASE WHEN id_estatus_global = {ph_cancelado} AND id_motivo_cierre = ANY({ph_no_viables}::integer[]) THEN id_oportunidad END) as no_viables,
                    COUNT(DISTINCT CASE WHEN clasificacion_solicitud = 'EXTRAORDINARIO' THEN id_oportunidad END) as extraordinarias,
                    COUNT(DISTINCT CASE WHEN parent_id IS NOT NULL THEN id_oportunidad END) as versiones,
                    COUNT(CASE WHEN es_retrabajo = TRUE THEN id_sitio END) as retrabajos,
                    COUNT(DISTINCT CASE WHEN es_licitacion = TRUE THEN COALESCE(parent_id, id_oportunidad) END) as licitaciones,
                    COUNT(CASE WHEN id_tipo_solicitud != {ph_lev} THEN id_sitio END) as total_sitios,
                    COUNT(DISTINCT CASE WHEN cantidad_sitios > 1 AND id_tipo_solicitud != {ph_lev} THEN id_oportunidad END) as oportunidades_multisitio,
                    COUNT(DISTINCT CASE WHEN id_estatus_global = {ph_ganada} AND id_tipo_solicitud != {ph_lev} THEN id_oportunidad END) as ganadas,
                    COUNT(CASE WHEN origen = 'sim_adicional' THEN id_sitio END) as sim_adicionales_count
                FROM base
                GROUP BY responsable_simulacion_id
            ),
            agg_fv AS (
                SELECT
                    o.responsable_simulacion_id,
                    COUNT(*) as total_ofertas,
                    COUNT(*) as total_sitios_entregados,
                    {_KPI_COUNT_COLS},
                    COUNT(DISTINCT ec.id_oportunidad) FILTER (WHERE ec.fecha_entrega IS NULL) as sin_fecha_entrega
                {_componente_kpi_from(where_batch, 'FV')}
                GROUP BY o.responsable_simulacion_id
            ),
            agg_tiempo AS (
                SELECT o.responsable_simulacion_id, AVG(o.tiempo_elaboracion_horas) as tiempo_promedio_horas
                FROM tb_sitios_oportunidad s
                JOIN tb_oportunidades o ON s.id_oportunidad = o.id_oportunidad
                JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
                {where_batch}
                  AND o.tiempo_elaboracion_horas IS NOT NULL
                  AND {_KPI_STATUS}
                  AND {_NO_EXCLUIDA}
                  AND o.id_tipo_solicitud != {ph_lev}
                GROUP BY o.responsable_simulacion_id
            )
            SELECT
                ab.responsable_simulacion_id,
                ab.total_solicitudes, ab.en_espera, ab.canceladas, ab.no_viables,
                ab.extraordinarias, ab.versiones, ab.retrabajos, ab.licitaciones,
                ab.total_sitios, ab.oportunidades_multisitio, ab.ganadas, ab.sim_adicionales_count,
                COALESCE(af.total_ofertas, 0) as total_ofertas,
                COALESCE(af.total_sitios_entregados, 0) as total_sitios_entregados,
                COALESCE(af.entregas_a_tiempo_interno, 0) as entregas_a_tiempo_interno,
                COALESCE(af.entregas_tarde_interno, 0) as entregas_tarde_interno,
                COALESCE(af.entregas_a_tiempo_compromiso, 0) as entregas_a_tiempo_compromiso,
                COALESCE(af.entregas_tarde_compromiso, 0) as entregas_tarde_compromiso,
                COALESCE(af.sin_fecha_entrega, 0) as sin_fecha_entrega,
                tt.tiempo_promedio_horas
            FROM agg_base ab
            LEFT JOIN agg_fv af ON af.responsable_simulacion_id = ab.responsable_simulacion_id
            LEFT JOIN agg_tiempo tt ON tt.responsable_simulacion_id = ab.responsable_simulacion_id
        """
        rows = await conn.fetch(query, *p.values)
        return [dict(r) for r in rows]

    async def get_report_metricas_tech_batch(self, conn, filters: Dict[str, Any], cats: Dict) -> List[Dict[str, Any]]:
        p = _P()
        where = self._build_where(p, filters)
        where_batch = where + " AND o.responsable_simulacion_id IS NOT NULL"
        ph_lev = p.add(cats['tipos'].get('levantamiento'))

        query = f"""
            WITH base AS (
                SELECT
                    o.responsable_simulacion_id, o.id_tecnologia,
                    s.id_oportunidad, s.id_sitio, s.es_retrabajo,
                    o.parent_id, o.clasificacion_solicitud, o.es_licitacion,
                    o.id_tipo_solicitud, o.potencia_cierre_fv_kwp, o.capacidad_cierre_bess_kwh
                FROM tb_sitios_oportunidad s
                JOIN tb_oportunidades o ON s.id_oportunidad = o.id_oportunidad
                JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
                {where_batch}

                UNION ALL

                SELECT
                    o.responsable_simulacion_id, o.id_tecnologia,
                    sa.id_oportunidad, sa.id AS id_sitio, false AS es_retrabajo,
                    o.parent_id, o.clasificacion_solicitud, o.es_licitacion,
                    o.id_tipo_solicitud, sa.potencia_cierre_fv_kwp, sa.capacidad_cierre_bess_kwh
                FROM tb_simulaciones_adicionales sa
                JOIN tb_oportunidades o ON sa.id_oportunidad = o.id_oportunidad
                JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
                {where_batch}
            ),
            agg_base AS (
                SELECT
                    responsable_simulacion_id, id_tecnologia,
                    COUNT(DISTINCT CASE WHEN id_tipo_solicitud != {ph_lev} THEN id_oportunidad END) as total_solicitudes,
                    COUNT(DISTINCT id_oportunidad) FILTER (WHERE clasificacion_solicitud = 'EXTRAORDINARIO') as extraordinarias,
                    COUNT(DISTINCT id_oportunidad) FILTER (WHERE parent_id IS NOT NULL) as versiones,
                    COUNT(*) FILTER (WHERE es_retrabajo = TRUE) as retrabajos,
                    COUNT(DISTINCT COALESCE(parent_id, id_oportunidad)) FILTER (WHERE es_licitacion = TRUE) as licitaciones,
                    COALESCE(SUM(DISTINCT potencia_cierre_fv_kwp), 0) as potencia_total_kwp,
                    COALESCE(SUM(DISTINCT capacidad_cierre_bess_kwh), 0) as capacidad_total_kwh,
                    COUNT(id_sitio) as total_sitios
                FROM base
                GROUP BY responsable_simulacion_id, id_tecnologia
            ),
            agg_fv AS (
                SELECT
                    o.responsable_simulacion_id, o.id_tecnologia,
                    COUNT(*) as total_ofertas,
                    {_KPI_COUNT_COLS}
                {_componente_kpi_from(where_batch, 'FV')}
                GROUP BY o.responsable_simulacion_id, o.id_tecnologia
            ),
            agg_tiempo AS (
                SELECT o.responsable_simulacion_id, o.id_tecnologia, AVG(o.tiempo_elaboracion_horas) as tiempo_promedio_horas
                FROM tb_sitios_oportunidad s
                JOIN tb_oportunidades o ON s.id_oportunidad = o.id_oportunidad
                JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
                {where_batch}
                  AND o.tiempo_elaboracion_horas IS NOT NULL
                  AND {_KPI_STATUS}
                  AND {_NO_EXCLUIDA}
                  AND o.id_tipo_solicitud != {ph_lev}
                GROUP BY o.responsable_simulacion_id, o.id_tecnologia
            )
            SELECT
                ab.responsable_simulacion_id,
                t.id as id_tecnologia, t.nombre,
                COALESCE(ab.total_solicitudes, 0) as total_solicitudes,
                COALESCE(af.total_ofertas, 0) as total_ofertas,
                COALESCE(af.entregas_a_tiempo_interno, 0) as entregas_a_tiempo_interno,
                COALESCE(af.entregas_tarde_interno, 0) as entregas_tarde_interno,
                COALESCE(af.entregas_a_tiempo_compromiso, 0) as entregas_a_tiempo_compromiso,
                COALESCE(af.entregas_tarde_compromiso, 0) as entregas_tarde_compromiso,
                COALESCE(ab.extraordinarias, 0) as extraordinarias,
                COALESCE(ab.versiones, 0) as versiones,
                COALESCE(ab.retrabajos, 0) as retrabajos,
                COALESCE(ab.licitaciones, 0) as licitaciones,
                tt.tiempo_promedio_horas,
                COALESCE(ab.potencia_total_kwp, 0) as potencia_total_kwp,
                COALESCE(ab.capacidad_total_kwh, 0) as capacidad_total_kwh,
                COALESCE(ab.total_sitios, 0) as total_sitios
            FROM agg_base ab
            JOIN tb_cat_tecnologias t ON t.id = ab.id_tecnologia
            LEFT JOIN agg_fv af
                ON af.responsable_simulacion_id = ab.responsable_simulacion_id
               AND af.id_tecnologia = ab.id_tecnologia
            LEFT JOIN agg_tiempo tt
                ON tt.responsable_simulacion_id = ab.responsable_simulacion_id
               AND tt.id_tecnologia = ab.id_tecnologia
            WHERE t.activo = true
            ORDER BY ab.responsable_simulacion_id, t.id
        """
        rows = await conn.fetch(query, *p.values)
        return [dict(r) for r in rows]

    async def get_report_tabla_contabilizacion_batch(self, conn, filters: Dict[str, Any], cats: Dict) -> List[Dict[str, Any]]:
        p = _P()
        where = self._build_where(p, filters)
        where_batch = where + " AND o.responsable_simulacion_id IS NOT NULL"
        ph_lev = p.add(cats['tipos'].get('levantamiento'))

        query = f"""
            WITH base AS (
                SELECT
                    o.responsable_simulacion_id, o.id_tipo_solicitud,
                    s.id_sitio, o.id_oportunidad, o.es_licitacion, o.parent_id
                FROM tb_sitios_oportunidad s
                JOIN tb_oportunidades o ON s.id_oportunidad = o.id_oportunidad
                JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
                {where_batch}

                UNION ALL

                SELECT
                    o.responsable_simulacion_id, o.id_tipo_solicitud,
                    sa.id AS id_sitio, o.id_oportunidad, o.es_licitacion, o.parent_id
                FROM tb_simulaciones_adicionales sa
                JOIN tb_oportunidades o ON sa.id_oportunidad = o.id_oportunidad
                JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
                {where_batch}
            ),
            agg_base AS (
                SELECT
                    responsable_simulacion_id, id_tipo_solicitud,
                    COUNT(id_sitio) as total,
                    COUNT(DISTINCT CASE WHEN es_licitacion = TRUE THEN COALESCE(parent_id, id_oportunidad) END) as licitaciones
                FROM base
                GROUP BY responsable_simulacion_id, id_tipo_solicitud
            ),
            agg_fv AS (
                SELECT
                    o.responsable_simulacion_id, o.id_tipo_solicitud,
                    {_KPI_COUNT_COLS},
                    COUNT(DISTINCT ec.id_oportunidad) FILTER (WHERE ec.fecha_entrega IS NULL) as sin_fecha
                {_componente_kpi_from(where_batch, 'FV')}
                GROUP BY o.responsable_simulacion_id, o.id_tipo_solicitud
            )
            SELECT
                ab.responsable_simulacion_id,
                ts.id as id_tipo_solicitud, ts.nombre, ts.codigo_interno,
                COALESCE(ab.total, 0) as total,
                COALESCE(af.entregas_a_tiempo_interno, 0) as entregas_a_tiempo_interno,
                COALESCE(af.entregas_tarde_interno, 0) as entregas_tarde_interno,
                COALESCE(af.entregas_a_tiempo_compromiso, 0) as entregas_a_tiempo_compromiso,
                COALESCE(af.entregas_tarde_compromiso, 0) as entregas_tarde_compromiso,
                COALESCE(af.sin_fecha, 0) as sin_fecha,
                COALESCE(ab.licitaciones, 0) as licitaciones,
                (ts.id = {ph_lev}) as es_levantamiento
            FROM agg_base ab
            JOIN tb_cat_tipos_solicitud ts ON ts.id = ab.id_tipo_solicitud
            LEFT JOIN agg_fv af
                ON af.responsable_simulacion_id = ab.responsable_simulacion_id
               AND af.id_tipo_solicitud = ab.id_tipo_solicitud
            WHERE COALESCE(ab.total, 0) > 0
            ORDER BY ab.responsable_simulacion_id, ts.id
        """
        rows = await conn.fetch(query, *p.values)
        return [dict(r) for r in rows]

    async def get_report_tiempo_promedio_tipo_batch(self, conn, filters: Dict[str, Any], cats: Dict) -> List[Dict[str, Any]]:
        p = _P()
        where = self._build_where(p, filters)
        where_batch = where + " AND o.responsable_simulacion_id IS NOT NULL"
        ph_lev = p.add(cats['tipos'].get('levantamiento'))

        query = f"""
            SELECT
                o.responsable_simulacion_id,
                ts.nombre as tipo,
                AVG(o.tiempo_elaboracion_horas) / 24 as dias_promedio
            FROM tb_oportunidades o
            JOIN tb_cat_tipos_solicitud ts ON o.id_tipo_solicitud = ts.id
            JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
            {where_batch}
            AND o.tiempo_elaboracion_horas IS NOT NULL
            AND {_KPI_STATUS}
            AND {_NO_EXCLUIDA}
            AND o.id_tipo_solicitud != {ph_lev}
            GROUP BY o.responsable_simulacion_id, ts.nombre
            HAVING AVG(o.tiempo_elaboracion_horas) IS NOT NULL
        """
        rows = await conn.fetch(query, *p.values)
        return [dict(r) for r in rows]

    async def get_report_tiempo_promedio_global_batch(self, conn, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        p = _P()
        where = self._build_where(p, filters)
        where_batch = where + " AND o.responsable_simulacion_id IS NOT NULL"

        query = f"""
            WITH tiempos AS (
                SELECT
                    o.responsable_simulacion_id,
                    o.tiempo_elaboracion_horas / 24 AS dias
                FROM tb_oportunidades o
                JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
                {where_batch}
                AND o.tiempo_elaboracion_horas IS NOT NULL
                AND {_KPI_STATUS}
                AND {_NO_EXCLUIDA}
                AND o.id_tipo_solicitud != (
                    SELECT id FROM tb_cat_tipos_solicitud WHERE LOWER(nombre) = 'levantamiento'
                )
            ),
            percentiles AS (
                SELECT responsable_simulacion_id,
                       PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY dias) AS p95
                FROM tiempos
                GROUP BY responsable_simulacion_id
            )
            SELECT t.responsable_simulacion_id, AVG(t.dias) AS dias_promedio
            FROM tiempos t
            JOIN percentiles p ON t.responsable_simulacion_id = p.responsable_simulacion_id
            WHERE t.dias <= p.p95
            GROUP BY t.responsable_simulacion_id
        """
        rows = await conn.fetch(query, *p.values)
        return [dict(r) for r in rows]

    async def get_report_motivo_retrabajo_batch(self, conn, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        p = _P()
        where = self._build_where(p, filters)
        where_batch = where + " AND o.responsable_simulacion_id IS NOT NULL"

        query = f"""
            WITH motivos AS (
                SELECT
                    o.responsable_simulacion_id,
                    mr.nombre AS motivo,
                    COUNT(*) AS conteo
                FROM tb_sitios_oportunidad s
                JOIN tb_oportunidades o ON s.id_oportunidad = o.id_oportunidad
                JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
                LEFT JOIN tb_cat_motivos_retrabajo mr ON s.id_motivo_retrabajo = mr.id
                {where_batch}
                AND s.es_retrabajo = TRUE AND s.id_motivo_retrabajo IS NOT NULL
                GROUP BY o.responsable_simulacion_id, mr.nombre
            )
            SELECT DISTINCT ON (responsable_simulacion_id)
                responsable_simulacion_id, motivo, conteo
            FROM motivos
            ORDER BY responsable_simulacion_id, conteo DESC
        """
        rows = await conn.fetch(query, *p.values)
        return [dict(r) for r in rows]

    async def get_report_resumen_mensual(self, conn, filters: Dict[str, Any], cats: Dict) -> List[Dict[str, Any]]:
        p = _P()
        where = self._build_where(p, filters)

        ph_lev = p.add(cats['tipos'].get('levantamiento'))
        ph_cancelado = p.add(cats['estatus'].get('cancelado'))
        ph_perdido = p.add(cats['estatus'].get('perdido'))
        ph_pendiente = p.add(cats['estatus'].get('pendiente'))
        ph_proceso = p.add(cats['estatus'].get('en proceso'))
        ph_revision = p.add(cats['estatus'].get('en revisión'))
        ph_no_viables = p.add(cats.get('motivos_no_viables', []))

        mes_expr = "EXTRACT(MONTH FROM o.fecha_solicitud AT TIME ZONE 'America/Mexico_City')::int"

        query = f"""
            WITH base AS (
                SELECT
                    {mes_expr} as mes,
                    s.id_oportunidad, s.es_retrabajo,
                    o.parent_id, o.clasificacion_solicitud, o.id_estatus_global,
                    o.id_tipo_solicitud, o.id_motivo_cierre
                FROM tb_sitios_oportunidad s
                JOIN tb_oportunidades o ON s.id_oportunidad = o.id_oportunidad
                JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
                {where}

                UNION ALL

                SELECT
                    {mes_expr} as mes,
                    sa.id_oportunidad, false AS es_retrabajo,
                    o.parent_id, o.clasificacion_solicitud, o.id_estatus_global,
                    o.id_tipo_solicitud, o.id_motivo_cierre
                FROM tb_simulaciones_adicionales sa
                JOIN tb_oportunidades o ON sa.id_oportunidad = o.id_oportunidad
                JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
                {where}
            ),
            agg_base AS (
                SELECT
                    mes,
                    COUNT(*) FILTER (WHERE id_tipo_solicitud != {ph_lev}) as solicitudes_recibidas,
                    COUNT(DISTINCT id_oportunidad) FILTER (WHERE id_estatus_global IN ({ph_pendiente}, {ph_proceso}, {ph_revision})) as en_espera,
                    COUNT(DISTINCT id_oportunidad) FILTER (WHERE id_estatus_global = {ph_cancelado}) as canceladas,
                    COUNT(DISTINCT id_oportunidad) FILTER (WHERE id_estatus_global = {ph_cancelado} AND id_motivo_cierre = ANY({ph_no_viables}::integer[])) as no_viables,
                    COUNT(DISTINCT id_oportunidad) FILTER (WHERE id_estatus_global = {ph_perdido}) as perdidas,
                    COUNT(DISTINCT id_oportunidad) FILTER (WHERE clasificacion_solicitud = 'EXTRAORDINARIO') as extraordinarias,
                    COUNT(DISTINCT id_oportunidad) FILTER (WHERE parent_id IS NOT NULL) as versiones,
                    COUNT(*) FILTER (WHERE es_retrabajo = TRUE) as retrabajos,
                    COUNT(*) FILTER (WHERE id_tipo_solicitud != {ph_lev}) as total_sitios
                FROM base
                GROUP BY mes
            ),
            agg_fv AS (
                SELECT
                    {mes_expr} as mes,
                    COUNT(*) as ofertas_generadas,
                    {_KPI_COUNT_COLS}
                {_componente_kpi_from(where, 'FV')}
                GROUP BY mes
            ),
            agg_tiempo AS (
                SELECT {mes_expr} as mes, AVG(o.tiempo_elaboracion_horas) as tiempo_promedio
                FROM tb_sitios_oportunidad s
                JOIN tb_oportunidades o ON s.id_oportunidad = o.id_oportunidad
                JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
                {where}
                  AND o.tiempo_elaboracion_horas IS NOT NULL
                  AND {_KPI_STATUS}
                  AND {_NO_EXCLUIDA}
                  AND o.id_tipo_solicitud != {ph_lev}
                GROUP BY mes
            )
            SELECT
                ab.mes,
                ab.solicitudes_recibidas,
                COALESCE(af.ofertas_generadas, 0) as ofertas_generadas,
                COALESCE(af.entregas_a_tiempo_interno, 0) as entregas_a_tiempo_interno,
                COALESCE(af.entregas_tarde_interno, 0) as entregas_tarde_interno,
                COALESCE(af.entregas_a_tiempo_compromiso, 0) as entregas_a_tiempo_compromiso,
                COALESCE(af.entregas_tarde_compromiso, 0) as entregas_tarde_compromiso,
                tt.tiempo_promedio,
                ab.en_espera, ab.canceladas, ab.no_viables, ab.perdidas,
                ab.extraordinarias, ab.versiones, ab.retrabajos, ab.total_sitios
            FROM agg_base ab
            LEFT JOIN agg_fv af ON af.mes = ab.mes
            LEFT JOIN agg_tiempo tt ON tt.mes = ab.mes
            ORDER BY ab.mes
        """
        rows = await conn.fetch(query, *p.values)
        return [dict(r) for r in rows]

    async def get_report_catalogos_filtros(self, conn) -> Dict[str, Any]:
        tecnologias = await conn.fetch(
            "SELECT id, nombre FROM tb_cat_tecnologias WHERE activo = true ORDER BY nombre"
        )
        tipos = await conn.fetch(
            "SELECT id, nombre, codigo_interno FROM tb_cat_tipos_solicitud WHERE activo = true ORDER BY nombre"
        )
        estatus = await conn.fetch(
            "SELECT id, nombre FROM tb_cat_estatus_oportunidades WHERE activo = true AND modulo_aplicable = 'SIMULACION' ORDER BY id"
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
            "usuarios": [dict(u) for u in usuarios],
        }

    async def get_chart_estatus(self, conn, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        p = _P()
        where = self._build_where(p, filters)
        query = f"""
            SELECT e.nombre, e.color_hex, COUNT(*) as total
            FROM tb_oportunidades o
            JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
            {where}
            GROUP BY e.id, e.nombre, e.color_hex
            ORDER BY total DESC
        """
        rows = await conn.fetch(query, *p.values)
        return [dict(r) for r in rows]

    async def get_chart_mensual(self, conn, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        p = _P()
        where = self._build_where(p, filters)
        query = f"""
            SELECT
                EXTRACT(MONTH FROM o.fecha_solicitud AT TIME ZONE 'America/Mexico_City')::int as mes,
                COUNT(*) as total
            FROM tb_oportunidades o
            JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
            {where}
            GROUP BY mes
            ORDER BY mes
        """
        rows = await conn.fetch(query, *p.values)
        return [dict(r) for r in rows]

    async def get_chart_tecnologia(self, conn, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        p = _P()
        where = self._build_where(p, filters)
        query = f"""
            SELECT t.nombre, COUNT(*) as total
            FROM tb_oportunidades o
            JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
            JOIN tb_cat_tecnologias t ON o.id_tecnologia = t.id
            {where}
            GROUP BY t.id, t.nombre
            ORDER BY total DESC
        """
        rows = await conn.fetch(query, *p.values)
        return [dict(r) for r in rows]

    async def get_clientes_alta_iteracion(
        self, conn, filters: Dict[str, Any], umbral: int = 3
    ) -> List[Dict[str, Any]]:
        fecha_inicio = filters.get("fecha_inicio")
        fecha_fin = filters.get("fecha_fin")

        query = """
            WITH RECURSIVE cadena AS (
                SELECT id_oportunidad,
                       id_oportunidad  AS raiz_id,
                       nombre_proyecto AS raiz_nombre,
                       cliente_id
                FROM tb_oportunidades
                WHERE parent_id IS NULL

                UNION ALL

                SELECT o.id_oportunidad,
                       c.raiz_id,
                       c.raiz_nombre,
                       o.cliente_id
                FROM tb_oportunidades o
                JOIN cadena c ON o.parent_id = c.id_oportunidad
            ),
            clientes_en_periodo AS (
                SELECT DISTINCT cliente_id
                FROM tb_oportunidades
                WHERE fecha_solicitud >= $1
                  AND fecha_solicitud < $2::date + INTERVAL '1 day'
                  AND cliente_id IS NOT NULL
            ),
            ciclos_con_alta_iter AS (
                SELECT cad.cliente_id, cad.raiz_id
                FROM tb_oportunidades o
                JOIN cadena cad ON o.id_oportunidad = cad.id_oportunidad
                JOIN clientes_en_periodo cp ON cad.cliente_id = cp.cliente_id
                JOIN tb_cat_tipos_solicitud ts ON o.id_tipo_solicitud = ts.id
                WHERE ts.codigo_interno = 'ACTUALIZACION'
                GROUP BY cad.cliente_id, cad.raiz_id
                HAVING COUNT(*) > $3
            ),
            resumen AS (
                SELECT
                    c.nombre_fiscal                                                    AS cliente_nombre,
                    cad.raiz_nombre                                                    AS proyecto_nombre,
                    COUNT(*) FILTER (WHERE ts.codigo_interno = 'ACTUALIZACION')        AS cnt_actualizaciones,
                    COUNT(*) FILTER (WHERE ts.codigo_interno = 'PRE_OFERTA')           AS cnt_pre_oferta,
                    COUNT(*) FILTER (WHERE ts.codigo_interno = 'LEVANTAMIENTO')        AS cnt_levantamientos,
                    COUNT(*) FILTER (WHERE ts.codigo_interno = 'OFERTA_FINAL')         AS cnt_ofertas_finales,
                    COUNT(*) FILTER (WHERE ts.codigo_interno = 'LICITACION')           AS cnt_licitaciones,
                    COUNT(*) FILTER (WHERE ts.codigo_interno NOT IN (
                        'ACTUALIZACION','PRE_OFERTA','LEVANTAMIENTO','OFERTA_FINAL','LICITACION'
                    ))                                                                  AS cnt_otros,
                    ARRAY_AGG(
                        DISTINCT COALESCE(u.nombre, o.solicitado_por)
                        ORDER BY COALESCE(u.nombre, o.solicitado_por)
                    ) FILTER (
                        WHERE ts.codigo_interno = 'ACTUALIZACION'
                          AND COALESCE(u.nombre, o.solicitado_por) IS NOT NULL
                    )                                                                   AS solicitantes
                FROM tb_oportunidades o
                JOIN cadena cad              ON o.id_oportunidad = cad.id_oportunidad
                JOIN ciclos_con_alta_iter ca ON cad.cliente_id = ca.cliente_id
                                            AND cad.raiz_id    = ca.raiz_id
                JOIN tb_clientes c           ON cad.cliente_id = c.id
                JOIN tb_cat_tipos_solicitud ts ON o.id_tipo_solicitud = ts.id
                LEFT JOIN tb_usuarios u      ON o.solicitado_por_id = u.id_usuario
                GROUP BY c.id, c.nombre_fiscal, cad.raiz_id, cad.raiz_nombre
            )
            SELECT * FROM resumen
            ORDER BY cnt_actualizaciones DESC
        """
        rows = await conn.fetch(query, fecha_inicio, fecha_fin, umbral)
        return [dict(r) for r in rows]

    async def get_oportunidades_tarde_revision(
        self, conn, filters: Dict[str, Any], umbral_horas: float
    ) -> List[Dict[str, Any]]:
        """
        Oportunidades marcadas tarde (compromiso) cuya espera en 'En Revisión'
        (orden=3) supera el umbral, contando solo horas hábiles (excluye fines de
        semana via fn_segundos_habiles_mx). Sirve para distinguir el retraso
        atribuible a la espera de Dirección del atribuible a Simulación.
        """
        p = _P()
        where = self._build_where(p, filters)
        ph_umbral = p.add(umbral_horas)

        query = f"""
            WITH opp AS (
                SELECT
                    o.id_oportunidad,
                    o.op_id_estandar,
                    o.cliente_nombre,
                    o.titulo_proyecto,
                    u.nombre AS responsable
                FROM tb_oportunidades o
                JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
                LEFT JOIN tb_usuarios u ON o.responsable_simulacion_id = u.id_usuario
                {where}
                  AND o.kpi_status_compromiso = 'Entrega tarde'
            ),
            segmentos AS (
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
                WHERE h.id_oportunidad IN (SELECT id_oportunidad FROM opp)
            ),
            revision AS (
                SELECT
                    id_oportunidad,
                    SUM(fn_segundos_habiles_mx(inicio, fin)) / 3600.0 AS horas_revision,
                    COUNT(*) AS rondas
                FROM segmentos
                WHERE orden = 3 AND fin IS NOT NULL
                GROUP BY id_oportunidad
            )
            SELECT
                opp.op_id_estandar,
                opp.cliente_nombre,
                opp.titulo_proyecto,
                opp.responsable,
                r.horas_revision,
                r.rondas
            FROM opp
            JOIN revision r ON opp.id_oportunidad = r.id_oportunidad
            WHERE r.horas_revision > {ph_umbral}
            ORDER BY r.horas_revision DESC
        """
        rows = await conn.fetch(query, *p.values)
        return [dict(r) for r in rows]


def get_report_db_service() -> ReportDBService:
    return ReportDBService()
