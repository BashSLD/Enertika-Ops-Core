# modules/simulacion/report_db_service.py
"""
Queries SQL para el módulo de Reportes de Simulación.
Solo usado por ReportesSimulacionService.
"""

from typing import Dict, List, Any, Optional, Tuple
from uuid import UUID
import logging

logger = logging.getLogger("ReportDBService")


class ReportDBService:
    """Queries de reporte de simulación. Stateless, instanciable sin args."""

    def _build_report_where_clause(self, filters: Dict[str, Any], param_offset: int = 0) -> Tuple[str, List]:
        """
        Construye cláusula WHERE dinámica para reportes.
        filters keys: fecha_inicio, fecha_fin, id_tecnologia, id_tipo_solicitud, id_estatus, responsable_id
        """
        conditions = [
            "e.modulo_aplicable = 'SIMULACION'",
            f"o.fecha_solicitud >= ${param_offset + 1}::timestamptz",
            f"o.fecha_solicitud < ${param_offset + 2}::timestamptz + INTERVAL '1 day'"
        ]
        params = [filters['fecha_inicio'], filters['fecha_fin']]

        if filters.get('id_tecnologia'):
            conditions.append(f"o.id_tecnologia = ${param_offset + len(params) + 1}")
            params.append(filters['id_tecnologia'])

        if filters.get('id_tipo_solicitud'):
            conditions.append(f"o.id_tipo_solicitud = ${param_offset + len(params) + 1}")
            params.append(filters['id_tipo_solicitud'])

        if filters.get('id_estatus'):
            conditions.append(f"o.id_estatus_global = ${param_offset + len(params) + 1}")
            params.append(filters['id_estatus'])

        if filters.get('responsable_id'):
            conditions.append(f"o.responsable_simulacion_id = ${param_offset + len(params) + 1}")
            params.append(filters['responsable_id'])

        where_clause = " AND ".join(conditions)
        return f"WHERE {where_clause}", params

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
        where_clause, params = self._build_report_where_clause(filters)

        id_entregado = cats['estatus'].get('entregado')
        id_perdido = cats['estatus'].get('perdido')
        id_cancelado = cats['estatus'].get('cancelado')
        id_ganada = cats['estatus'].get('ganada')
        id_levantamiento = cats['tipos'].get('levantamiento')
        id_pendiente = cats['estatus'].get('pendiente')
        id_en_proceso = cats['estatus'].get('en proceso')
        id_en_revision = cats['estatus'].get('en revisión')
        ids_no_viables = cats.get('motivos_no_viables', [])

        params.extend([
            id_entregado, id_perdido, id_cancelado, id_ganada, id_levantamiento,
            id_pendiente, id_en_proceso, id_en_revision, ids_no_viables
        ])

        idx_entregado = len(params) - 8
        idx_perdido = len(params) - 7
        idx_cancelado = len(params) - 6
        idx_ganada = len(params) - 5
        idx_levantamiento = len(params) - 4
        idx_pendiente = len(params) - 3
        idx_proceso = len(params) - 2
        idx_revision = len(params) - 1
        idx_no_viables = len(params)

        query = f"""
            WITH sitios_kpis AS (
                SELECT
                    s.id_oportunidad, s.id_sitio,
                    s.kpi_status_interno, s.kpi_status_compromiso, s.es_retrabajo,
                    o.parent_id, o.clasificacion_solicitud, o.es_licitacion,
                    o.id_tipo_solicitud, o.id_estatus_global, o.id_motivo_cierre,
                    o.tiempo_elaboracion_horas, o.fecha_entrega_simulacion, o.cantidad_sitios,
                    'sitio_normal' AS origen
                FROM tb_sitios_oportunidad s
                JOIN tb_oportunidades o ON s.id_oportunidad = o.id_oportunidad
                JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
                {where_clause}

                UNION ALL

                SELECT
                    sa.id_oportunidad, sa.id AS id_sitio,
                    sa.kpi_status_interno, sa.kpi_status_compromiso, false AS es_retrabajo,
                    o.parent_id, o.clasificacion_solicitud, o.es_licitacion,
                    o.id_tipo_solicitud, o.id_estatus_global, o.id_motivo_cierre,
                    NULL AS tiempo_elaboracion_horas, sa.fecha_entrega AS fecha_entrega_simulacion,
                    o.cantidad_sitios, 'sim_adicional' AS origen
                FROM tb_simulaciones_adicionales sa
                JOIN tb_oportunidades o ON sa.id_oportunidad = o.id_oportunidad
                JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
                {where_clause}
            )
            SELECT
                COUNT(DISTINCT CASE WHEN id_tipo_solicitud != ${idx_levantamiento} THEN id_oportunidad END) as total_solicitudes,
                COUNT(CASE WHEN id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) AND id_tipo_solicitud != ${idx_levantamiento} THEN id_sitio END) as total_ofertas,
                COUNT(DISTINCT CASE WHEN id_estatus_global IN (${idx_pendiente}, ${idx_proceso}, ${idx_revision}) THEN id_oportunidad END) as en_espera,
                COUNT(DISTINCT CASE WHEN id_estatus_global = ${idx_cancelado} THEN id_oportunidad END) as canceladas,
                COUNT(DISTINCT CASE WHEN id_estatus_global = ${idx_cancelado} AND id_motivo_cierre = ANY(${idx_no_viables}::integer[]) THEN id_oportunidad END) as no_viables,
                COUNT(DISTINCT CASE WHEN clasificacion_solicitud = 'EXTRAORDINARIO' THEN id_oportunidad END) as extraordinarias,
                COUNT(DISTINCT CASE WHEN parent_id IS NOT NULL THEN id_oportunidad END) as versiones,
                COUNT(CASE WHEN es_retrabajo = TRUE THEN id_sitio END) as retrabajos,
                COUNT(DISTINCT CASE WHEN es_licitacion = TRUE THEN COALESCE(parent_id, id_oportunidad) END) as licitaciones,
                COUNT(CASE WHEN kpi_status_interno = 'Entrega a tiempo' AND id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) AND id_tipo_solicitud != ${idx_levantamiento} THEN id_sitio END) as entregas_a_tiempo_interno,
                COUNT(CASE WHEN kpi_status_interno = 'Entrega tarde' AND id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) AND id_tipo_solicitud != ${idx_levantamiento} THEN id_sitio END) as entregas_tarde_interno,
                COUNT(CASE WHEN kpi_status_compromiso = 'Entrega a tiempo' AND id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) AND id_tipo_solicitud != ${idx_levantamiento} THEN id_sitio END) as entregas_a_tiempo_compromiso,
                COUNT(CASE WHEN kpi_status_compromiso = 'Entrega tarde' AND id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) AND id_tipo_solicitud != ${idx_levantamiento} THEN id_sitio END) as entregas_tarde_compromiso,
                COUNT(DISTINCT CASE WHEN id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) AND fecha_entrega_simulacion IS NULL THEN id_oportunidad END) as sin_fecha_entrega,
                AVG(CASE WHEN tiempo_elaboracion_horas IS NOT NULL AND id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) THEN tiempo_elaboracion_horas END) as tiempo_promedio_horas,
                COUNT(CASE WHEN id_tipo_solicitud != ${idx_levantamiento} THEN id_sitio END) as total_sitios,
                COUNT(CASE WHEN id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) AND id_tipo_solicitud != ${idx_levantamiento} THEN id_sitio END) as total_sitios_entregados,
                COUNT(DISTINCT CASE WHEN cantidad_sitios > 1 AND id_tipo_solicitud != ${idx_levantamiento} THEN id_oportunidad END) as oportunidades_multisitio,
                COUNT(DISTINCT CASE WHEN id_estatus_global = ${idx_ganada} AND id_tipo_solicitud != ${idx_levantamiento} THEN id_oportunidad END) as ganadas,
                COUNT(CASE WHEN origen = 'sim_adicional' THEN id_sitio END) as sim_adicionales_count
            FROM sitios_kpis
        """
        row = await conn.fetchrow(query, *params)
        return dict(row) if row else None

    async def get_report_motivo_retrabajo(self, conn, filters: Dict[str, Any], user_id: Optional[UUID] = None) -> Optional[Dict[str, Any]]:
        where_clause, params = self._build_report_where_clause(filters)
        if user_id:
            where_clause += f" AND o.responsable_simulacion_id = ${len(params) + 1}"
            params.append(user_id)

        query = f"""
            SELECT mr.nombre as motivo, COUNT(*) as conteo
            FROM tb_sitios_oportunidad s
            JOIN tb_oportunidades o ON s.id_oportunidad = o.id_oportunidad
            JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
            LEFT JOIN tb_cat_motivos_retrabajo mr ON s.id_motivo_retrabajo = mr.id
            {where_clause}
            AND s.es_retrabajo = TRUE AND s.id_motivo_retrabajo IS NOT NULL
            GROUP BY mr.nombre ORDER BY conteo DESC LIMIT 1
        """
        row = await conn.fetchrow(query, *params)
        return dict(row) if row else None

    async def get_report_tiempo_promedio_global(self, conn, user_id: UUID, filters: Dict[str, Any]) -> Optional[float]:
        where_clause, params = self._build_report_where_clause(filters)
        where_clause += f" AND o.responsable_simulacion_id = ${len(params) + 1}"
        params.append(user_id)

        query = f"""
            WITH tiempos AS (
                SELECT tiempo_elaboracion_horas / 24 as dias
                FROM tb_oportunidades o
                JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
                {where_clause}
                AND o.tiempo_elaboracion_horas IS NOT NULL
                AND o.id_estatus_global IN (
                    SELECT id FROM tb_cat_estatus_oportunidades WHERE LOWER(nombre) IN ('entregado', 'perdido')
                )
                AND o.id_tipo_solicitud != (
                    SELECT id FROM tb_cat_tipos_solicitud WHERE LOWER(nombre) = 'levantamiento'
                )
            )
            SELECT AVG(dias) as dias_promedio
            FROM tiempos
            WHERE dias <= (SELECT PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY dias) FROM tiempos)
        """
        row = await conn.fetchrow(query, *params)
        return row['dias_promedio'] if row and row['dias_promedio'] else None

    async def get_report_metricas_tech(self, conn, filters: Dict[str, Any], cats: Dict) -> List[Dict[str, Any]]:
        where_clause, params = self._build_report_where_clause(filters)

        id_entregado = cats['estatus'].get('entregado')
        id_perdido = cats['estatus'].get('perdido')
        id_ganada = cats['estatus'].get('ganada')
        id_levantamiento = cats['tipos'].get('levantamiento')

        params.extend([id_entregado, id_perdido, id_ganada, id_levantamiento])
        idx_entregado, idx_perdido, idx_ganada, idx_levantamiento = len(params)-3, len(params)-2, len(params)-1, len(params)

        query = f"""
            WITH sitios_tech AS (
                SELECT
                    o.id_tecnologia, s.id_oportunidad, s.id_sitio,
                    s.kpi_status_interno, s.kpi_status_compromiso, s.es_retrabajo,
                    o.parent_id, o.clasificacion_solicitud, o.es_licitacion, o.id_estatus_global, o.id_tipo_solicitud,
                    o.tiempo_elaboracion_horas, o.potencia_cierre_fv_kwp, o.capacidad_cierre_bess_kwh
                FROM tb_sitios_oportunidad s
                JOIN tb_oportunidades o ON s.id_oportunidad = o.id_oportunidad
                JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
                {where_clause}

                UNION ALL

                SELECT
                    o.id_tecnologia, sa.id_oportunidad, sa.id AS id_sitio,
                    sa.kpi_status_interno, sa.kpi_status_compromiso, false AS es_retrabajo,
                    o.parent_id, o.clasificacion_solicitud, o.es_licitacion, o.id_estatus_global, o.id_tipo_solicitud,
                    NULL AS tiempo_elaboracion_horas, sa.potencia_cierre_fv_kwp, sa.capacidad_cierre_bess_kwh
                FROM tb_simulaciones_adicionales sa
                JOIN tb_oportunidades o ON sa.id_oportunidad = o.id_oportunidad
                JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
                {where_clause}
            )
            SELECT
                t.id as id_tecnologia, t.nombre,
                COUNT(DISTINCT CASE WHEN st.id_tipo_solicitud != ${idx_levantamiento} THEN st.id_oportunidad END) as total_solicitudes,
                COUNT(CASE WHEN st.id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) AND st.id_tipo_solicitud != ${idx_levantamiento} THEN st.id_sitio END) as total_ofertas,
                COUNT(*) FILTER (WHERE st.kpi_status_interno = 'Entrega a tiempo' AND st.id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) AND st.id_tipo_solicitud != ${idx_levantamiento}) as entregas_a_tiempo_interno,
                COUNT(*) FILTER (WHERE st.kpi_status_interno = 'Entrega tarde' AND st.id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) AND st.id_tipo_solicitud != ${idx_levantamiento}) as entregas_tarde_interno,
                COUNT(*) FILTER (WHERE st.kpi_status_compromiso = 'Entrega a tiempo' AND st.id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) AND st.id_tipo_solicitud != ${idx_levantamiento}) as entregas_a_tiempo_compromiso,
                COUNT(*) FILTER (WHERE st.kpi_status_compromiso = 'Entrega tarde' AND st.id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) AND st.id_tipo_solicitud != ${idx_levantamiento}) as entregas_tarde_compromiso,
                COUNT(DISTINCT st.id_oportunidad) FILTER (WHERE st.clasificacion_solicitud = 'EXTRAORDINARIO') as extraordinarias,
                COUNT(DISTINCT st.id_oportunidad) FILTER (WHERE st.parent_id IS NOT NULL) as versiones,
                COUNT(*) FILTER (WHERE st.es_retrabajo = TRUE) as retrabajos,
                COUNT(DISTINCT COALESCE(st.parent_id, st.id_oportunidad)) FILTER (WHERE st.es_licitacion = TRUE) as licitaciones,
                AVG(st.tiempo_elaboracion_horas) FILTER (WHERE st.tiempo_elaboracion_horas IS NOT NULL) as tiempo_promedio_horas,
                COALESCE(SUM(DISTINCT st.potencia_cierre_fv_kwp), 0) as potencia_total_kwp,
                COALESCE(SUM(DISTINCT st.capacidad_cierre_bess_kwh), 0) as capacidad_total_kwh,
                COUNT(st.id_sitio) as total_sitios
            FROM tb_cat_tecnologias t
            LEFT JOIN sitios_tech st ON st.id_tecnologia = t.id
            WHERE t.activo = true
            GROUP BY t.id, t.nombre ORDER BY t.id
        """
        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    async def get_chart_motivos_cierre(self, conn, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        where_clause, params = self._build_report_where_clause(filters)

        query = f"""
            SELECT m.motivo, m.categoria, COUNT(*) as total
            FROM tb_oportunidades o
            JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
            JOIN tb_cat_motivos_cierre m ON o.id_motivo_cierre = m.id
            {where_clause}
            AND o.id_motivo_cierre IS NOT NULL
            AND LOWER(e.nombre) IN ('cancelado', 'perdido')
            GROUP BY m.id, m.motivo, m.categoria
            ORDER BY total DESC
            LIMIT 10
        """
        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    async def get_report_tabla_contabilizacion(self, conn, filters: Dict[str, Any], cats: Dict) -> List[Dict[str, Any]]:
        where_clause, params = self._build_report_where_clause(filters)

        id_entregado = cats['estatus'].get('entregado')
        id_perdido = cats['estatus'].get('perdido')
        id_ganada = cats['estatus'].get('ganada')
        id_levantamiento = cats['tipos'].get('levantamiento')

        params.extend([id_entregado, id_perdido, id_ganada, id_levantamiento])
        idx_entregado, idx_perdido, idx_ganada, idx_levantamiento = len(params)-3, len(params)-2, len(params)-1, len(params)

        query = f"""
            WITH sitios_contab AS (
                SELECT
                    o.id_tipo_solicitud, s.id_sitio, s.kpi_status_interno, s.kpi_status_compromiso,
                    o.id_estatus_global, o.id_oportunidad, o.fecha_entrega_simulacion,
                    o.es_licitacion, o.parent_id
                FROM tb_sitios_oportunidad s
                JOIN tb_oportunidades o ON s.id_oportunidad = o.id_oportunidad
                JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
                {where_clause}

                UNION ALL

                SELECT
                    o.id_tipo_solicitud, sa.id AS id_sitio, sa.kpi_status_interno, sa.kpi_status_compromiso,
                    o.id_estatus_global, o.id_oportunidad, sa.fecha_entrega AS fecha_entrega_simulacion,
                    o.es_licitacion, o.parent_id
                FROM tb_simulaciones_adicionales sa
                JOIN tb_oportunidades o ON sa.id_oportunidad = o.id_oportunidad
                JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
                {where_clause}
            )
            SELECT
                ts.id as id_tipo_solicitud, ts.nombre, ts.codigo_interno,
                COUNT(sc.id_sitio) as total,
                COUNT(CASE WHEN sc.kpi_status_interno = 'Entrega a tiempo' AND sc.id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) THEN sc.id_sitio END) as entregas_a_tiempo_interno,
                COUNT(CASE WHEN sc.kpi_status_interno = 'Entrega tarde' AND sc.id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) THEN sc.id_sitio END) as entregas_tarde_interno,
                COUNT(CASE WHEN sc.kpi_status_compromiso = 'Entrega a tiempo' AND sc.id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) THEN sc.id_sitio END) as entregas_a_tiempo_compromiso,
                COUNT(CASE WHEN sc.kpi_status_compromiso = 'Entrega tarde' AND sc.id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) THEN sc.id_sitio END) as entregas_tarde_compromiso,
                COUNT(DISTINCT CASE WHEN sc.id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) AND sc.fecha_entrega_simulacion IS NULL THEN sc.id_oportunidad END) as sin_fecha,
                COUNT(DISTINCT CASE WHEN sc.es_licitacion = TRUE THEN COALESCE(sc.parent_id, sc.id_oportunidad) END) as licitaciones,
                (ts.id = ${idx_levantamiento}) as es_levantamiento
            FROM tb_cat_tipos_solicitud ts
            LEFT JOIN sitios_contab sc ON ts.id = sc.id_tipo_solicitud
            GROUP BY ts.id, ts.nombre, ts.codigo_interno HAVING COUNT(sc.id_sitio) > 0
            ORDER BY ts.id
        """
        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    async def get_report_users_active(self, conn, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        where_clause, params = self._build_report_where_clause(filters)
        query = f"""
            SELECT DISTINCT u.id_usuario, u.nombre
            FROM tb_usuarios u
            INNER JOIN tb_oportunidades o ON o.responsable_simulacion_id = u.id_usuario
            INNER JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
            {where_clause}
            ORDER BY u.nombre
        """
        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    async def get_report_oportunidades_usuario(self, conn, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        where_clause, params = self._build_report_where_clause(filters)
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
                        WHEN COUNT(CASE WHEN s.kpi_status_interno = 'Entrega tarde' THEN 1 END) > 0 THEN 'Tarde'
                        WHEN COUNT(CASE WHEN s.kpi_status_interno = 'Entrega a tiempo' THEN 1 END) = COUNT(s.id_sitio)
                             AND COUNT(s.id_sitio) > 0 THEN 'A tiempo'
                        ELSE '-'
                    END AS kpi_interno,
                    CASE
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
                {where_clause}
                GROUP BY
                    o.id_oportunidad, o.op_id_estandar, o.nombre_proyecto, o.cliente_nombre,
                    o.es_licitacion, o.clasificacion_solicitud, o.parent_id, o.cantidad_sitios,
                    o.fecha_solicitud, o.fecha_entrega_simulacion,
                    o.deadline_calculado, o.deadline_negociado,
                    e.nombre, ts.nombre, t.nombre
            ) sub
            ORDER BY
                (kpi_compromiso = 'Tarde') DESC,
                fecha_solicitud DESC
        """
        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    async def get_kpi_insights_usuario(self, conn, filters: Dict[str, Any], cats: Dict) -> List[Dict[str, Any]]:
        where_clause, params = self._build_report_where_clause(filters)

        id_entregado = cats['estatus'].get('entregado')
        id_perdido = cats['estatus'].get('perdido')
        id_ganada = cats['estatus'].get('ganada')
        id_levantamiento = cats['tipos'].get('levantamiento')

        params.extend([id_entregado, id_perdido, id_ganada, id_levantamiento])
        idx_entregado = len(params) - 3
        idx_perdido = len(params) - 2
        idx_ganada = len(params) - 1
        idx_levantamiento = len(params)

        query = f"""
            WITH sitios_combined AS (
                SELECT
                    s.kpi_status_compromiso,
                    o.id_oportunidad, s.id_sitio,
                    o.op_id_estandar, o.nombre_proyecto,
                    o.deadline_negociado, o.deadline_calculado
                FROM tb_sitios_oportunidad s
                JOIN tb_oportunidades o ON s.id_oportunidad = o.id_oportunidad
                JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
                {where_clause}
                AND o.id_tipo_solicitud != ${idx_levantamiento}
                AND o.id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada})

                UNION ALL

                SELECT
                    sa.kpi_status_compromiso,
                    o.id_oportunidad, sa.id AS id_sitio,
                    o.op_id_estandar, o.nombre_proyecto,
                    o.deadline_negociado, o.deadline_calculado
                FROM tb_simulaciones_adicionales sa
                JOIN tb_oportunidades o ON sa.id_oportunidad = o.id_oportunidad
                JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
                {where_clause}
                AND o.id_tipo_solicitud != ${idx_levantamiento}
                AND o.id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada})
            ),
            base AS (
                SELECT
                    id_oportunidad,
                    op_id_estandar,
                    nombre_proyecto,
                    (MIN(deadline_negociado) < MIN(deadline_calculado)) AS compromiso_adelantado,
                    COUNT(id_sitio) AS total_sitios,
                    COUNT(CASE WHEN kpi_status_compromiso = 'Entrega tarde' THEN 1 END) AS sitios_tarde,
                    COUNT(CASE WHEN kpi_status_compromiso = 'Entrega a tiempo' THEN 1 END) AS sitios_a_tiempo
                FROM sitios_combined
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
        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    async def get_report_tiempo_promedio_tipo(self, conn, user_id: UUID, filters: Dict[str, Any], cats: Dict) -> Dict[str, float]:
        where_clause, params = self._build_report_where_clause(filters)
        idx_user = len(params) + 1
        params.append(user_id)

        id_entregado = cats['estatus'].get('entregado')
        id_perdido = cats['estatus'].get('perdido')
        id_ganada = cats['estatus'].get('ganada')
        params.extend([id_entregado, id_perdido, id_ganada])
        idx_entregado, idx_perdido, idx_ganada = len(params)-2, len(params)-1, len(params)

        query = f"""
            SELECT ts.nombre as tipo, AVG(o.tiempo_elaboracion_horas) / 24 as dias_promedio
            FROM tb_oportunidades o
            JOIN tb_cat_tipos_solicitud ts ON o.id_tipo_solicitud = ts.id
            JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
            {where_clause}
            AND o.responsable_simulacion_id = ${idx_user}
            AND o.tiempo_elaboracion_horas IS NOT NULL
            AND o.id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada})
            AND o.id_tipo_solicitud != (SELECT id FROM tb_cat_tipos_solicitud WHERE LOWER(nombre) = 'levantamiento')
            GROUP BY ts.nombre HAVING AVG(o.tiempo_elaboracion_horas) IS NOT NULL
        """
        rows = await conn.fetch(query, *params)
        return {row['tipo']: round(float(row['dias_promedio']), 1) for row in rows}

    # =========================================================================
    # BATCH QUERIES — Fase 2 optimización
    # Reemplazan 6N queries individuales por 6 queries fijas independientemente
    # del número de usuarios. Retornan filas agrupadas por responsable_simulacion_id
    # para mapear en memoria en el service layer.
    # =========================================================================

    async def get_report_metricas_generales_batch(self, conn, filters: Dict[str, Any], cats: Dict) -> List[Dict[str, Any]]:
        where_clause, params = self._build_report_where_clause(filters)
        where_batch = where_clause + " AND o.responsable_simulacion_id IS NOT NULL"

        id_entregado = cats['estatus'].get('entregado')
        id_perdido = cats['estatus'].get('perdido')
        id_cancelado = cats['estatus'].get('cancelado')
        id_ganada = cats['estatus'].get('ganada')
        id_levantamiento = cats['tipos'].get('levantamiento')
        id_pendiente = cats['estatus'].get('pendiente')
        id_en_proceso = cats['estatus'].get('en proceso')
        id_en_revision = cats['estatus'].get('en revisión')
        ids_no_viables = cats.get('motivos_no_viables', [])

        params.extend([
            id_entregado, id_perdido, id_cancelado, id_ganada, id_levantamiento,
            id_pendiente, id_en_proceso, id_en_revision, ids_no_viables
        ])
        idx_entregado = len(params) - 8
        idx_perdido = len(params) - 7
        idx_cancelado = len(params) - 6
        idx_ganada = len(params) - 5
        idx_levantamiento = len(params) - 4
        idx_pendiente = len(params) - 3
        idx_proceso = len(params) - 2
        idx_revision = len(params) - 1
        idx_no_viables = len(params)

        query = f"""
            WITH sitios_kpis AS (
                SELECT
                    o.responsable_simulacion_id,
                    s.id_oportunidad, s.id_sitio,
                    s.kpi_status_interno, s.kpi_status_compromiso, s.es_retrabajo,
                    o.parent_id, o.clasificacion_solicitud, o.es_licitacion,
                    o.id_tipo_solicitud, o.id_estatus_global, o.id_motivo_cierre,
                    o.tiempo_elaboracion_horas, o.fecha_entrega_simulacion,
                    o.cantidad_sitios, 'sitio_normal' AS origen
                FROM tb_sitios_oportunidad s
                JOIN tb_oportunidades o ON s.id_oportunidad = o.id_oportunidad
                JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
                {where_batch}

                UNION ALL

                SELECT
                    o.responsable_simulacion_id,
                    sa.id_oportunidad, sa.id AS id_sitio,
                    sa.kpi_status_interno, sa.kpi_status_compromiso, false AS es_retrabajo,
                    o.parent_id, o.clasificacion_solicitud, o.es_licitacion,
                    o.id_tipo_solicitud, o.id_estatus_global, o.id_motivo_cierre,
                    NULL AS tiempo_elaboracion_horas, sa.fecha_entrega AS fecha_entrega_simulacion,
                    o.cantidad_sitios, 'sim_adicional' AS origen
                FROM tb_simulaciones_adicionales sa
                JOIN tb_oportunidades o ON sa.id_oportunidad = o.id_oportunidad
                JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
                {where_batch}
            )
            SELECT
                responsable_simulacion_id,
                COUNT(DISTINCT CASE WHEN id_tipo_solicitud != ${idx_levantamiento} THEN id_oportunidad END) as total_solicitudes,
                COUNT(CASE WHEN id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) AND id_tipo_solicitud != ${idx_levantamiento} THEN id_sitio END) as total_ofertas,
                COUNT(DISTINCT CASE WHEN id_estatus_global IN (${idx_pendiente}, ${idx_proceso}, ${idx_revision}) THEN id_oportunidad END) as en_espera,
                COUNT(DISTINCT CASE WHEN id_estatus_global = ${idx_cancelado} THEN id_oportunidad END) as canceladas,
                COUNT(DISTINCT CASE WHEN id_estatus_global = ${idx_cancelado} AND id_motivo_cierre = ANY(${idx_no_viables}::integer[]) THEN id_oportunidad END) as no_viables,
                COUNT(DISTINCT CASE WHEN clasificacion_solicitud = 'EXTRAORDINARIO' THEN id_oportunidad END) as extraordinarias,
                COUNT(DISTINCT CASE WHEN parent_id IS NOT NULL THEN id_oportunidad END) as versiones,
                COUNT(CASE WHEN es_retrabajo = TRUE THEN id_sitio END) as retrabajos,
                COUNT(DISTINCT CASE WHEN es_licitacion = TRUE THEN COALESCE(parent_id, id_oportunidad) END) as licitaciones,
                COUNT(CASE WHEN kpi_status_interno = 'Entrega a tiempo' AND id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) AND id_tipo_solicitud != ${idx_levantamiento} THEN id_sitio END) as entregas_a_tiempo_interno,
                COUNT(CASE WHEN kpi_status_interno = 'Entrega tarde' AND id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) AND id_tipo_solicitud != ${idx_levantamiento} THEN id_sitio END) as entregas_tarde_interno,
                COUNT(CASE WHEN kpi_status_compromiso = 'Entrega a tiempo' AND id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) AND id_tipo_solicitud != ${idx_levantamiento} THEN id_sitio END) as entregas_a_tiempo_compromiso,
                COUNT(CASE WHEN kpi_status_compromiso = 'Entrega tarde' AND id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) AND id_tipo_solicitud != ${idx_levantamiento} THEN id_sitio END) as entregas_tarde_compromiso,
                COUNT(DISTINCT CASE WHEN id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) AND fecha_entrega_simulacion IS NULL THEN id_oportunidad END) as sin_fecha_entrega,
                AVG(CASE WHEN tiempo_elaboracion_horas IS NOT NULL AND id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) THEN tiempo_elaboracion_horas END) as tiempo_promedio_horas,
                COUNT(CASE WHEN id_tipo_solicitud != ${idx_levantamiento} THEN id_sitio END) as total_sitios,
                COUNT(CASE WHEN id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) AND id_tipo_solicitud != ${idx_levantamiento} THEN id_sitio END) as total_sitios_entregados,
                COUNT(DISTINCT CASE WHEN cantidad_sitios > 1 AND id_tipo_solicitud != ${idx_levantamiento} THEN id_oportunidad END) as oportunidades_multisitio,
                COUNT(DISTINCT CASE WHEN id_estatus_global = ${idx_ganada} AND id_tipo_solicitud != ${idx_levantamiento} THEN id_oportunidad END) as ganadas,
                COUNT(CASE WHEN origen = 'sim_adicional' THEN id_sitio END) as sim_adicionales_count
            FROM sitios_kpis
            GROUP BY responsable_simulacion_id
        """
        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    async def get_report_metricas_tech_batch(self, conn, filters: Dict[str, Any], cats: Dict) -> List[Dict[str, Any]]:
        where_clause, params = self._build_report_where_clause(filters)
        where_batch = where_clause + " AND o.responsable_simulacion_id IS NOT NULL"

        id_entregado = cats['estatus'].get('entregado')
        id_perdido = cats['estatus'].get('perdido')
        id_ganada = cats['estatus'].get('ganada')
        id_levantamiento = cats['tipos'].get('levantamiento')

        params.extend([id_entregado, id_perdido, id_ganada, id_levantamiento])
        idx_entregado, idx_perdido, idx_ganada, idx_levantamiento = len(params)-3, len(params)-2, len(params)-1, len(params)

        query = f"""
            WITH sitios_tech AS (
                SELECT
                    o.responsable_simulacion_id, o.id_tecnologia,
                    s.id_oportunidad, s.id_sitio,
                    s.kpi_status_interno, s.kpi_status_compromiso, s.es_retrabajo,
                    o.parent_id, o.clasificacion_solicitud, o.es_licitacion,
                    o.id_estatus_global, o.id_tipo_solicitud,
                    o.tiempo_elaboracion_horas, o.potencia_cierre_fv_kwp, o.capacidad_cierre_bess_kwh
                FROM tb_sitios_oportunidad s
                JOIN tb_oportunidades o ON s.id_oportunidad = o.id_oportunidad
                JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
                {where_batch}

                UNION ALL

                SELECT
                    o.responsable_simulacion_id, o.id_tecnologia,
                    sa.id_oportunidad, sa.id AS id_sitio,
                    sa.kpi_status_interno, sa.kpi_status_compromiso, false AS es_retrabajo,
                    o.parent_id, o.clasificacion_solicitud, o.es_licitacion,
                    o.id_estatus_global, o.id_tipo_solicitud,
                    NULL AS tiempo_elaboracion_horas, sa.potencia_cierre_fv_kwp, sa.capacidad_cierre_bess_kwh
                FROM tb_simulaciones_adicionales sa
                JOIN tb_oportunidades o ON sa.id_oportunidad = o.id_oportunidad
                JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
                {where_batch}
            )
            SELECT
                st.responsable_simulacion_id,
                t.id as id_tecnologia, t.nombre,
                COUNT(DISTINCT CASE WHEN st.id_tipo_solicitud != ${idx_levantamiento} THEN st.id_oportunidad END) as total_solicitudes,
                COUNT(CASE WHEN st.id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) AND st.id_tipo_solicitud != ${idx_levantamiento} THEN st.id_sitio END) as total_ofertas,
                COUNT(*) FILTER (WHERE st.kpi_status_interno = 'Entrega a tiempo' AND st.id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) AND st.id_tipo_solicitud != ${idx_levantamiento}) as entregas_a_tiempo_interno,
                COUNT(*) FILTER (WHERE st.kpi_status_interno = 'Entrega tarde' AND st.id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) AND st.id_tipo_solicitud != ${idx_levantamiento}) as entregas_tarde_interno,
                COUNT(*) FILTER (WHERE st.kpi_status_compromiso = 'Entrega a tiempo' AND st.id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) AND st.id_tipo_solicitud != ${idx_levantamiento}) as entregas_a_tiempo_compromiso,
                COUNT(*) FILTER (WHERE st.kpi_status_compromiso = 'Entrega tarde' AND st.id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) AND st.id_tipo_solicitud != ${idx_levantamiento}) as entregas_tarde_compromiso,
                COUNT(DISTINCT st.id_oportunidad) FILTER (WHERE st.clasificacion_solicitud = 'EXTRAORDINARIO') as extraordinarias,
                COUNT(DISTINCT st.id_oportunidad) FILTER (WHERE st.parent_id IS NOT NULL) as versiones,
                COUNT(*) FILTER (WHERE st.es_retrabajo = TRUE) as retrabajos,
                COUNT(DISTINCT COALESCE(st.parent_id, st.id_oportunidad)) FILTER (WHERE st.es_licitacion = TRUE) as licitaciones,
                AVG(st.tiempo_elaboracion_horas) FILTER (WHERE st.tiempo_elaboracion_horas IS NOT NULL) as tiempo_promedio_horas,
                COALESCE(SUM(DISTINCT st.potencia_cierre_fv_kwp), 0) as potencia_total_kwp,
                COALESCE(SUM(DISTINCT st.capacidad_cierre_bess_kwh), 0) as capacidad_total_kwh,
                COUNT(st.id_sitio) as total_sitios
            FROM sitios_tech st
            JOIN tb_cat_tecnologias t ON t.id = st.id_tecnologia
            WHERE t.activo = true
            GROUP BY st.responsable_simulacion_id, t.id, t.nombre
            ORDER BY st.responsable_simulacion_id, t.id
        """
        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    async def get_report_tabla_contabilizacion_batch(self, conn, filters: Dict[str, Any], cats: Dict) -> List[Dict[str, Any]]:
        where_clause, params = self._build_report_where_clause(filters)
        where_batch = where_clause + " AND o.responsable_simulacion_id IS NOT NULL"

        id_entregado = cats['estatus'].get('entregado')
        id_perdido = cats['estatus'].get('perdido')
        id_ganada = cats['estatus'].get('ganada')
        id_levantamiento = cats['tipos'].get('levantamiento')

        params.extend([id_entregado, id_perdido, id_ganada, id_levantamiento])
        idx_entregado, idx_perdido, idx_ganada, idx_levantamiento = len(params)-3, len(params)-2, len(params)-1, len(params)

        query = f"""
            WITH sitios_contab AS (
                SELECT
                    o.responsable_simulacion_id,
                    o.id_tipo_solicitud, s.id_sitio, s.kpi_status_interno, s.kpi_status_compromiso,
                    o.id_estatus_global, o.id_oportunidad, o.fecha_entrega_simulacion,
                    o.es_licitacion, o.parent_id
                FROM tb_sitios_oportunidad s
                JOIN tb_oportunidades o ON s.id_oportunidad = o.id_oportunidad
                JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
                {where_batch}

                UNION ALL

                SELECT
                    o.responsable_simulacion_id,
                    o.id_tipo_solicitud, sa.id AS id_sitio, sa.kpi_status_interno, sa.kpi_status_compromiso,
                    o.id_estatus_global, o.id_oportunidad, sa.fecha_entrega AS fecha_entrega_simulacion,
                    o.es_licitacion, o.parent_id
                FROM tb_simulaciones_adicionales sa
                JOIN tb_oportunidades o ON sa.id_oportunidad = o.id_oportunidad
                JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
                {where_batch}
            )
            SELECT
                sc.responsable_simulacion_id,
                ts.id as id_tipo_solicitud, ts.nombre, ts.codigo_interno,
                COUNT(sc.id_sitio) as total,
                COUNT(CASE WHEN sc.kpi_status_interno = 'Entrega a tiempo' AND sc.id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) THEN sc.id_sitio END) as entregas_a_tiempo_interno,
                COUNT(CASE WHEN sc.kpi_status_interno = 'Entrega tarde' AND sc.id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) THEN sc.id_sitio END) as entregas_tarde_interno,
                COUNT(CASE WHEN sc.kpi_status_compromiso = 'Entrega a tiempo' AND sc.id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) THEN sc.id_sitio END) as entregas_a_tiempo_compromiso,
                COUNT(CASE WHEN sc.kpi_status_compromiso = 'Entrega tarde' AND sc.id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) THEN sc.id_sitio END) as entregas_tarde_compromiso,
                COUNT(DISTINCT CASE WHEN sc.id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) AND sc.fecha_entrega_simulacion IS NULL THEN sc.id_oportunidad END) as sin_fecha,
                COUNT(DISTINCT CASE WHEN sc.es_licitacion = TRUE THEN COALESCE(sc.parent_id, sc.id_oportunidad) END) as licitaciones,
                (ts.id = ${idx_levantamiento}) as es_levantamiento
            FROM sitios_contab sc
            JOIN tb_cat_tipos_solicitud ts ON ts.id = sc.id_tipo_solicitud
            GROUP BY sc.responsable_simulacion_id, ts.id, ts.nombre, ts.codigo_interno
            HAVING COUNT(sc.id_sitio) > 0
            ORDER BY sc.responsable_simulacion_id, ts.id
        """
        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    async def get_report_tiempo_promedio_tipo_batch(self, conn, filters: Dict[str, Any], cats: Dict) -> List[Dict[str, Any]]:
        where_clause, params = self._build_report_where_clause(filters)
        where_batch = where_clause + " AND o.responsable_simulacion_id IS NOT NULL"

        id_entregado = cats['estatus'].get('entregado')
        id_perdido = cats['estatus'].get('perdido')
        id_ganada = cats['estatus'].get('ganada')
        params.extend([id_entregado, id_perdido, id_ganada])
        idx_entregado, idx_perdido, idx_ganada = len(params)-2, len(params)-1, len(params)

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
            AND o.id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada})
            AND o.id_tipo_solicitud != (
                SELECT id FROM tb_cat_tipos_solicitud WHERE LOWER(nombre) = 'levantamiento'
            )
            GROUP BY o.responsable_simulacion_id, ts.nombre
            HAVING AVG(o.tiempo_elaboracion_horas) IS NOT NULL
        """
        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    async def get_report_tiempo_promedio_global_batch(self, conn, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        where_clause, params = self._build_report_where_clause(filters)
        where_batch = where_clause + " AND o.responsable_simulacion_id IS NOT NULL"

        query = f"""
            WITH tiempos AS (
                SELECT
                    o.responsable_simulacion_id,
                    o.tiempo_elaboracion_horas / 24 AS dias
                FROM tb_oportunidades o
                JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
                {where_batch}
                AND o.tiempo_elaboracion_horas IS NOT NULL
                AND o.id_estatus_global IN (
                    SELECT id FROM tb_cat_estatus_oportunidades WHERE LOWER(nombre) IN ('entregado', 'perdido')
                )
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
        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    async def get_report_motivo_retrabajo_batch(self, conn, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        where_clause, params = self._build_report_where_clause(filters)
        where_batch = where_clause + " AND o.responsable_simulacion_id IS NOT NULL"

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
        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    async def get_report_resumen_mensual(self, conn, filters: Dict[str, Any], cats: Dict) -> List[Dict[str, Any]]:
        where_clause, params = self._build_report_where_clause(filters)

        id_entregado = cats['estatus'].get('entregado')
        id_perdido = cats['estatus'].get('perdido')
        id_cancelado = cats['estatus'].get('cancelado')
        id_ganada = cats['estatus'].get('ganada')
        id_levantamiento = cats['tipos'].get('levantamiento')
        id_pendiente = cats['estatus'].get('pendiente')
        id_en_proceso = cats['estatus'].get('en proceso')
        id_en_revision = cats['estatus'].get('en revisión')
        ids_no_viables = cats.get('motivos_no_viables', [])

        params.extend([
            id_entregado, id_perdido, id_cancelado, id_ganada, id_levantamiento,
            id_pendiente, id_en_proceso, id_en_revision, ids_no_viables
        ])
        idx_entregado = len(params) - 8
        idx_perdido = len(params) - 7
        idx_cancelado = len(params) - 6
        idx_ganada = len(params) - 5
        idx_levantamiento = len(params) - 4
        idx_pendiente = len(params) - 3
        idx_proceso = len(params) - 2
        idx_revision = len(params) - 1
        idx_no_viables = len(params)

        query = f"""
            WITH sitios_mensual AS (
                SELECT
                    EXTRACT(MONTH FROM o.fecha_solicitud AT TIME ZONE 'America/Mexico_City')::int as mes,
                    s.id_oportunidad, s.kpi_status_interno, s.kpi_status_compromiso, s.es_retrabajo,
                    o.parent_id, o.clasificacion_solicitud, o.id_estatus_global, o.id_tipo_solicitud,
                    o.tiempo_elaboracion_horas, o.id_motivo_cierre
                FROM tb_sitios_oportunidad s
                JOIN tb_oportunidades o ON s.id_oportunidad = o.id_oportunidad
                JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
                {where_clause}

                UNION ALL

                SELECT
                    EXTRACT(MONTH FROM o.fecha_solicitud AT TIME ZONE 'America/Mexico_City')::int as mes,
                    sa.id_oportunidad, sa.kpi_status_interno, sa.kpi_status_compromiso, false AS es_retrabajo,
                    o.parent_id, o.clasificacion_solicitud, o.id_estatus_global, o.id_tipo_solicitud,
                    NULL AS tiempo_elaboracion_horas, o.id_motivo_cierre
                FROM tb_simulaciones_adicionales sa
                JOIN tb_oportunidades o ON sa.id_oportunidad = o.id_oportunidad
                JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
                {where_clause}
            )
            SELECT
                mes,
                COUNT(*) FILTER (WHERE id_tipo_solicitud != ${idx_levantamiento}) as solicitudes_recibidas,
                COUNT(*) FILTER (WHERE id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) AND id_tipo_solicitud != ${idx_levantamiento}) as ofertas_generadas,
                COUNT(*) FILTER (WHERE kpi_status_interno = 'Entrega a tiempo' AND id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) AND id_tipo_solicitud != ${idx_levantamiento}) as entregas_a_tiempo_interno,
                COUNT(*) FILTER (WHERE kpi_status_interno = 'Entrega tarde' AND id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) AND id_tipo_solicitud != ${idx_levantamiento}) as entregas_tarde_interno,
                COUNT(*) FILTER (WHERE kpi_status_compromiso = 'Entrega a tiempo' AND id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) AND id_tipo_solicitud != ${idx_levantamiento}) as entregas_a_tiempo_compromiso,
                COUNT(*) FILTER (WHERE kpi_status_compromiso = 'Entrega tarde' AND id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) AND id_tipo_solicitud != ${idx_levantamiento}) as entregas_tarde_compromiso,
                AVG(tiempo_elaboracion_horas) FILTER (WHERE tiempo_elaboracion_horas IS NOT NULL) as tiempo_promedio,
                COUNT(DISTINCT id_oportunidad) FILTER (WHERE id_estatus_global IN (${idx_pendiente}, ${idx_proceso}, ${idx_revision})) as en_espera,
                COUNT(DISTINCT id_oportunidad) FILTER (WHERE id_estatus_global = ${idx_cancelado}) as canceladas,
                COUNT(DISTINCT id_oportunidad) FILTER (WHERE id_estatus_global = ${idx_cancelado} AND id_motivo_cierre = ANY(${idx_no_viables}::integer[])) as no_viables,
                COUNT(DISTINCT id_oportunidad) FILTER (WHERE id_estatus_global = ${idx_perdido}) as perdidas,
                COUNT(DISTINCT id_oportunidad) FILTER (WHERE clasificacion_solicitud = 'EXTRAORDINARIO') as extraordinarias,
                COUNT(DISTINCT id_oportunidad) FILTER (WHERE parent_id IS NOT NULL) as versiones,
                COUNT(*) FILTER (WHERE es_retrabajo = TRUE) as retrabajos,
                COUNT(*) FILTER (WHERE id_tipo_solicitud != ${idx_levantamiento}) as total_sitios
            FROM sitios_mensual
            GROUP BY mes ORDER BY mes
        """
        rows = await conn.fetch(query, *params)
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
        where_clause, params = self._build_report_where_clause(filters)
        query = f"""
            SELECT e.nombre, e.color_hex, COUNT(*) as total
            FROM tb_oportunidades o
            JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
            {where_clause}
            GROUP BY e.id, e.nombre, e.color_hex
            ORDER BY total DESC
        """
        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    async def get_chart_mensual(self, conn, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        where_clause, params = self._build_report_where_clause(filters)
        query = f"""
            SELECT
                EXTRACT(MONTH FROM o.fecha_solicitud AT TIME ZONE 'America/Mexico_City')::int as mes,
                COUNT(*) as total
            FROM tb_oportunidades o
            JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
            {where_clause}
            GROUP BY mes
            ORDER BY mes
        """
        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    async def get_chart_tecnologia(self, conn, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        where_clause, params = self._build_report_where_clause(filters)
        query = f"""
            SELECT t.nombre, COUNT(*) as total
            FROM tb_oportunidades o
            JOIN tb_cat_estatus_oportunidades e ON o.id_estatus_global = e.id
            JOIN tb_cat_tecnologias t ON o.id_tecnologia = t.id
            {where_clause}
            GROUP BY t.id, t.nombre
            ORDER BY total DESC
        """
        rows = await conn.fetch(query, *params)
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


def get_report_db_service() -> ReportDBService:
    return ReportDBService()
