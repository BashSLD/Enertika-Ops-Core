import logging
import io
from typing import Optional, List
from uuid import UUID
from datetime import datetime
import pandas as pd
from collections import defaultdict
from core.permissions import user_has_module_access

logger = logging.getLogger("ComercialServices")

class DashboardService:
    """
    Sub-servicio encargado de la analítica, KPIs y generación de reportes (Excel).
    """

    async def get_dashboard_stats(
        self, 
        conn, 
        user_context: dict,
        cats: dict, # Catalog IDs passed from parent to avoid re-fetching if possible
        # Filtros opcionales
        filtro_usuario_id: Optional[UUID] = None,
        filtro_tipo_id: Optional[int] = None,
        filtro_estatus_id: Optional[int] = None,
        filtro_tecnologia_id: Optional[int] = None,
        filtro_fecha_inicio: Optional[str] = None,
        filtro_fecha_fin: Optional[str] = None
    ) -> dict:
        """
        Calcula KPIs y datos para gráficos.
        """
        user_id = user_context.get("user_db_id")
        role = user_context.get("role", "USER")

        # Parse Dates
        if filtro_fecha_inicio and isinstance(filtro_fecha_inicio, str):
            try:
                filtro_fecha_inicio = datetime.strptime(filtro_fecha_inicio, '%Y-%m-%d').date()
            except ValueError: pass
        
        if filtro_fecha_fin and isinstance(filtro_fecha_fin, str):
            try:
                filtro_fecha_fin = datetime.strptime(filtro_fecha_fin, '%Y-%m-%d').date()
            except ValueError: pass

        # Default to Current Year if no dates provided
        if not filtro_fecha_inicio and not filtro_fecha_fin:
            now = datetime.now()
            filtro_fecha_inicio = now.replace(month=1, day=1).date()
            filtro_fecha_fin = now.replace(month=12, day=31).date()
        
        # Filtros de Seguridad
        params = []
        conditions = ["o.email_enviado = true"] # Solo activas
        
        # Roles que pueden ver data de todos: ADMIN del módulo
        if not user_has_module_access("comercial", user_context, "admin"):
            conditions.append(f"o.creado_por_id = ${len(params)+1}")
            params.append(user_id)
        
        # --- Filtros Globales ---
        if filtro_usuario_id:
            conditions.append(f"o.creado_por_id = ${len(params)+1}")
            params.append(filtro_usuario_id)
            
        if filtro_tipo_id:
            conditions.append(f"o.id_tipo_solicitud = ${len(params)+1}")
            params.append(filtro_tipo_id)
            
        if filtro_estatus_id:
            conditions.append(f"o.id_estatus_global = ${len(params)+1}")
            params.append(filtro_estatus_id)
            
        if filtro_tecnologia_id:
            conditions.append(f"o.id_tecnologia = ${len(params)+1}")
            params.append(filtro_tecnologia_id)
            
        if filtro_fecha_inicio:
            conditions.append(f"(o.fecha_solicitud AT TIME ZONE 'America/Mexico_City')::date >= ${len(params)+1}::date")
            params.append(filtro_fecha_inicio)
            
        if filtro_fecha_fin:
            conditions.append(f"(o.fecha_solicitud AT TIME ZONE 'America/Mexico_City') < (${len(params)+1}::date + INTERVAL '1 day')")
            params.append(filtro_fecha_fin)
            
        where_str = "WHERE " + " AND ".join(conditions)
        
        # KPIs
        id_ganada = cats['estatus'].get('ganada')
        id_perdido = cats['estatus'].get('perdido')
        
        idx_ganada = len(params) + 1
        idx_perdido = len(params) + 2
        
        q_kpis = f"""
            SELECT 
                count(*) FILTER (WHERE t.codigo_interno != 'LEVANTAMIENTO') as total,
                count(*) FILTER (WHERE t.codigo_interno = 'LEVANTAMIENTO') as levantamientos,
                count(*) FILTER (WHERE o.id_estatus_global = ${idx_ganada}) as ganadas,
                count(*) FILTER (WHERE o.id_estatus_global = ${idx_perdido}) as perdidas
            FROM tb_oportunidades o
            LEFT JOIN tb_cat_tipos_solicitud t ON o.id_tipo_solicitud = t.id
            {where_str}
        """
        
        # KPI Query
        row_kpis = await conn.fetchrow(q_kpis, *params, id_ganada, id_perdido)
        
        # Stats dictionary init
        stats = {
            "kpis": {
                "total": row_kpis['total'],
                "levantamientos": row_kpis['levantamientos'],
                "ganadas": row_kpis['ganadas'],
                "perdidas": row_kpis['perdidas']
            },
            "charts": {}
        }

        # --- Gráfica Semanal ---
        q_week = f"""
            WITH semana_actual AS (
                SELECT 
                    EXTRACT(ISODOW FROM (fecha_solicitud AT TIME ZONE 'America/Mexico_City'))::int as day_num,
                    count(*) as count
                FROM tb_oportunidades o
                {where_str}
                AND (fecha_solicitud AT TIME ZONE 'America/Mexico_City')::date 
                    >= DATE_TRUNC('week', (NOW() AT TIME ZONE 'America/Mexico_City')::date)
                AND (fecha_solicitud AT TIME ZONE 'America/Mexico_City')::date
                    < DATE_TRUNC('week', (NOW() AT TIME ZONE 'America/Mexico_City')::date) + INTERVAL '7 days'
                GROUP BY day_num
            )
            SELECT s.day_num, COALESCE(sa.count, 0) as count
            FROM generate_series(1, 7) AS s(day_num)
            LEFT JOIN semana_actual sa ON s.day_num = sa.day_num
            ORDER BY s.day_num
        """
        rows_week = await conn.fetch(q_week, *params)
        day_map = {1: 'Lun', 2: 'Mar', 3: 'Mié', 4: 'Jue', 5: 'Vie', 6: 'Sáb', 7: 'Dom'}
        stats["charts"]["week"] = {
            "labels": [day_map[r['day_num']] for r in rows_week],
            "data": [r['count'] for r in rows_week]
        }

        # --- Gráfica Mensual ---
        condition_monthly = ""
        # if not filtro_fecha_inicio and not filtro_fecha_fin:
        #      condition_monthly = "AND fecha_solicitud >= NOW() - INTERVAL '6 months'"
        
        if user_has_module_access("comercial", user_context, "admin"):
            q_monthly = f"""
                SELECT 
                    TO_CHAR((o.fecha_solicitud AT TIME ZONE 'America/Mexico_City'), 'Mon YY') as mes,
                    DATE_TRUNC('month', (o.fecha_solicitud AT TIME ZONE 'America/Mexico_City')) as mes_date,
                    COALESCE(u.nombre, 'Sin asignar') as vendedor,
                    count(*) as count
                FROM tb_oportunidades o
                LEFT JOIN tb_usuarios u ON o.creado_por_id = u.id_usuario
                {where_str}
                {condition_monthly}
                GROUP BY mes_date, mes, u.nombre
                ORDER BY mes_date, u.nombre
            """
            rows_monthly = await conn.fetch(q_monthly, *params)
            
            meses_unicos = []
            vendedores_data = defaultdict(lambda: defaultdict(int))
            
            for row in rows_monthly:
                mes = row['mes']
                vendedor = row['vendedor']
                if mes not in meses_unicos: meses_unicos.append(mes)
                vendedores_data[vendedor][mes] = row['count']
            
            datasets = []
            colors = ['#00BABB', '#123456', '#22c55e', '#f97316', '#8b5cf6', '#ec4899', '#fbbf24']
            for idx, (vendedor, meses_counts) in enumerate(vendedores_data.items()):
                datasets.append({
                    "label": vendedor,
                    "data": [meses_counts.get(mes, 0) for mes in meses_unicos],
                    "backgroundColor": colors[idx % len(colors)]
                })
            
            stats["charts"]["monthly"] = {
                "labels": meses_unicos,
                "datasets": datasets,
                "stacked": True
            }
        else:
            q_monthly = f"""
                SELECT 
                    TO_CHAR((fecha_solicitud AT TIME ZONE 'America/Mexico_City'), 'Mon YY') as mes,
                    count(*) as count
                FROM tb_oportunidades o
                {where_str}
                {condition_monthly}
                GROUP BY 
                    DATE_TRUNC('month', (fecha_solicitud AT TIME ZONE 'America/Mexico_City')),
                    TO_CHAR((fecha_solicitud AT TIME ZONE 'America/Mexico_City'), 'Mon YY')
                ORDER BY DATE_TRUNC('month', (fecha_solicitud AT TIME ZONE 'America/Mexico_City'))
            """
            rows_m = await conn.fetch(q_monthly, *params)
            stats["charts"]["monthly"] = {
                "labels": [r['mes'] for r in rows_m],
                "data": [r['count'] for r in rows_m],
                "stacked": False
            }

        # --- Mix Tecnológico ---
        q_mix = f"""
            SELECT t.nombre as label, count(*) as count
            FROM tb_oportunidades o
            JOIN tb_cat_tecnologias t ON o.id_tecnologia = t.id
            {where_str}
            GROUP BY t.nombre ORDER BY count DESC
        """
        rows_mix = await conn.fetch(q_mix, *params)
        stats["charts"]["mix"] = {
            "labels": [r['label'] for r in rows_mix],
            "data": [r['count'] for r in rows_mix]
        }

        # --- Estatus ---
        q_status = f"""
            SELECT e.nombre as label, count(*) as count
            FROM tb_oportunidades o
            JOIN tb_cat_estatus_global e ON o.id_estatus_global = e.id
            {where_str}
            GROUP BY e.nombre ORDER BY count DESC LIMIT 5
        """
        rows_status = await conn.fetch(q_status, *params)
        stats["charts"]["status"] = {
            "labels": [r['label'] for r in rows_status],
            "data": [r['count'] for r in rows_status]
        }

        # --- Tipos Solicitud ---
        q_types = f"""
            SELECT t.nombre as label, count(*) as count
            FROM tb_oportunidades o
            JOIN tb_cat_tipos_solicitud t ON o.id_tipo_solicitud = t.id
            {where_str}
            GROUP BY t.nombre ORDER BY count DESC
        """
        rows_types = await conn.fetch(q_types, *params)
        stats["charts"]["request_types"] = {
            "labels": [r['label'] for r in rows_types],
            "data": [r['count'] for r in rows_types]
        }
        
        return stats

    async def generate_multisite_excel(self, conn, id_oportunidad: UUID, id_interno: str) -> Optional[dict]:
        """Genera el archivo Excel para oportunidades multisitio."""
        try:
            sites_rows = await conn.fetch(
                "SELECT nombre_sitio, numero_servicio, direccion, tipo_tarifa, google_maps_link, comentarios FROM tb_sitios_oportunidad WHERE id_oportunidad = $1", 
                id_oportunidad
            )
            if sites_rows:
                df_sites = pd.DataFrame([dict(r) for r in sites_rows])
                df_sites.columns = ["NOMBRE", "# DE SERVICIO", "DIRECCION", "TARIFA", "LINK GOOGLE", "COMENTARIOS"]
                
                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
                    df_sites.to_excel(writer, index=False, sheet_name='Sitios')
                
                return {
                    "name": f"Listado_Multisitios_{id_interno}.xlsx",
                    "content_bytes": buf.getvalue(),
                    "contentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                }
        except Exception as e:
            logger.error(f"Error generando excel adjunto: {e}")
            return None
