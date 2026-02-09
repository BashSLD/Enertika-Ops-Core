from typing import List, Optional, Dict, Any, Tuple
from uuid import UUID
from datetime import datetime, date
from decimal import Decimal
import logging

from core.database import get_db_connection

logger = logging.getLogger("SimulacionDBService")

class SimulacionDBService:
    """
    Data Access Layer para el módulo de Simulación.
    Centraliza todas las consultas SQL para separar la lógica de acceso a datos.
    """

    async def get_oportunidad_by_id(self, conn, id_oportunidad: UUID) -> Optional[Dict[str, Any]]:
        """Obtiene una oportunidad por ID con todos sus campos raw."""
        row = await conn.fetchrow("SELECT * FROM tb_oportunidades WHERE id_oportunidad = $1", id_oportunidad)
        return dict(row) if row else None

    async def get_estatus_simulacion_dropdown(self, conn, exclude_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Obtiene opciones para el dropdown de estatus global, filtrando por módulo."""
        if exclude_id:
            rows = await conn.fetch(
                "SELECT id, nombre FROM tb_cat_estatus_global WHERE activo = true AND modulo_aplicable = 'SIMULACION' AND id != $1 ORDER BY id",
                exclude_id
            )
        else:
            rows = await conn.fetch(
                "SELECT id, nombre FROM tb_cat_estatus_global WHERE activo = true AND modulo_aplicable = 'SIMULACION' ORDER BY id"
            )
        return [dict(r) for r in rows]

    async def get_motivos_cierre(self, conn) -> List[Dict[str, Any]]:
        rows = await conn.fetch("SELECT id, motivo FROM tb_cat_motivos_cierre WHERE activo = true ORDER BY motivo")
        return [dict(r) for r in rows]

    async def get_motivos_retrabajo(self, conn) -> List[Dict[str, Any]]:
        rows = await conn.fetch("SELECT id, nombre FROM tb_cat_motivos_retrabajo WHERE activo = true ORDER BY nombre")
        return [dict(r) for r in rows]
    
    async def get_sitios_by_oportunidad(self, conn, id_oportunidad: UUID) -> List[Dict[str, Any]]:
        query = """
        SELECT id_sitio, nombre_sitio, direccion, es_retrabajo, id_estatus_global
        FROM tb_sitios_oportunidad 
        WHERE id_oportunidad = $1 
        ORDER BY nombre_sitio
        """
        rows = await conn.fetch(query, id_oportunidad)
        return [dict(r) for r in rows]

    async def update_responsable(self, conn, id_oportunidad: UUID, id_responsable: UUID) -> None:
        await conn.execute(
            "UPDATE tb_oportunidades SET responsable_simulacion_id = $1 WHERE id_oportunidad = $2",
            id_responsable, id_oportunidad
        )

    async def get_id_oportunidad_from_sitio(self, conn, id_sitio: UUID) -> Optional[UUID]:
        return await conn.fetchval(
            "SELECT id_oportunidad FROM tb_sitios_oportunidad WHERE id_sitio = $1", 
            id_sitio
        )

    # --- Métodos para Métricas Operativas (Admin) ---

    async def get_usuarios_activos(self, conn) -> List[Dict[str, Any]]:
        rows = await conn.fetch("""
            SELECT id_usuario as id, nombre
            FROM tb_usuarios
            WHERE is_active = TRUE
            ORDER BY nombre
        """)
        return [dict(r) for r in rows]

    async def get_tipos_solicitud(self, conn) -> List[Dict[str, Any]]:
        rows = await conn.fetch("""
            SELECT id, nombre
            FROM tb_cat_tipos_solicitud
            ORDER BY nombre
        """)
        return [dict(r) for r in rows]


    async def get_responsables_simulacion(self, conn) -> List[Dict[str, Any]]:
        query = """
            SELECT id_usuario, nombre, department as departamento
            FROM tb_usuarios
            WHERE is_active = true 
            AND (
                LOWER(department) = 'simulación'
                OR puede_asignarse_simulacion = true
            )
            ORDER BY nombre
        """
        rows = await conn.fetch(query)
        return [dict(r) for r in rows]

    async def registrar_cambio_deadline(self, conn, id_oportunidad: UUID, 
                                      deadline_anterior: Optional[datetime], deadline_nuevo: datetime,
                                      id_motivo_cambio: int, comentario: Optional[str],
                                      user_id: UUID, user_name: str):
        """
        (FUTURA IMPLEMENTACIÓN)
        Registra el histórico de cambios de fecha.
        Actualmente no se invoca desde la UI porque falta el selector de motivos.
        """
        query = """
            INSERT INTO tb_historial_cambios_deadline (
                id_oportunidad, deadline_anterior, deadline_nuevo,
                id_motivo_cambio, comentario, usuario_id, usuario_nombre
            ) VALUES ($1, $2, $3, $4, $5, $6, $7)
        """
        await conn.execute(query, id_oportunidad, deadline_anterior, deadline_nuevo, 
                         id_motivo_cambio, comentario, user_id, user_name)

    async def get_oportunidad_for_update(self, conn, id_oportunidad: UUID) -> Optional[Dict[str, Any]]:
        return await conn.fetchrow("""
            SELECT 
                id_oportunidad, id_interno_simulacion, responsable_simulacion_id, deadline_negociado,
                monto_cierre_usd, potencia_cierre_fv_kwp, capacidad_cierre_bess_kwh,
                id_estatus_global, deadline_calculado, fecha_solicitud
            FROM tb_oportunidades 
            WHERE id_oportunidad = $1
        """, id_oportunidad)

    async def get_total_sitios_count(self, conn, id_oportunidad: UUID) -> int:
        return await conn.fetchval(
            "SELECT count(*) FROM tb_sitios_oportunidad WHERE id_oportunidad = $1", 
            id_oportunidad
        )

    async def get_sitios_pendientes_count(self, conn, id_oportunidad: UUID, terminal_status_ids: List[int]) -> int:
        query = """
            SELECT count(*) FROM tb_sitios_oportunidad 
            WHERE id_oportunidad = $1 
            AND id_estatus_global != ALL($2::int[])
        """
        return await conn.fetchval(query, id_oportunidad, terminal_status_ids)

    async def update_oportunidad_padre(self, conn, id_oportunidad: UUID, datos: Dict[str, Any]):
        query = """
            UPDATE tb_oportunidades SET
                id_interno_simulacion = $1,
                responsable_simulacion_id = $2,
                fecha_entrega_simulacion = $3,
                deadline_negociado = $4,
                id_estatus_global = $5,
                id_motivo_cierre = $6,
                monto_cierre_usd = $7,
                potencia_cierre_fv_kwp = $8,
                capacidad_cierre_bess_kwh = $9,
                kpi_status_sla_interno = $10,
                kpi_status_compromiso = $11,
                tiempo_elaboracion_horas = $12
            WHERE id_oportunidad = $13
        """
        await conn.execute(query,
            datos['id_interno_simulacion'],
            datos['responsable_simulacion_id'],
            datos['fecha_entrega_simulacion'],
            datos['deadline_negociado'],
            datos['id_estatus_global'],
            datos['id_motivo_cierre'],
            datos['monto_cierre_usd'],
            datos['potencia_cierre_fv_kwp'],
            datos['capacidad_cierre_bess_kwh'],
            datos['kpi_sla_val'],
            datos['kpi_compromiso_val'],
            datos['tiempo_elaboracion_horas'],
            id_oportunidad
        )

    async def get_deadlines_padre(self, conn, id_oportunidad: UUID) -> Optional[Dict[str, Any]]:
        return await conn.fetchrow(
            """
            SELECT deadline_calculado, deadline_negociado 
            FROM tb_oportunidades 
            WHERE id_oportunidad = $1
            """,
            id_oportunidad
        )
        
    async def update_sitios_batch_execute(self, conn, id_oportunidad: UUID, datos_batch: Any, 
                                        fecha_cierre_final: Optional[datetime], 
                                        kpi_interno: Optional[str], kpi_compromiso: Optional[str]):
        query = """
            UPDATE tb_sitios_oportunidad
            SET 
                id_estatus_global = $1,
                fecha_cierre = CASE WHEN $2::timestamptz IS NOT NULL THEN $2::timestamptz ELSE fecha_cierre END,
                kpi_status_interno = $3,
                kpi_status_compromiso = $4,
                es_retrabajo = $5,
                id_motivo_retrabajo = $6
            WHERE id_sitio = ANY($7::uuid[])
            AND id_oportunidad = $8
        """
        await conn.execute(
            query, 
            datos_batch.id_estatus_global, 
            fecha_cierre_final, 
            kpi_interno,
            kpi_compromiso,
            datos_batch.es_retrabajo,
            datos_batch.id_motivo_retrabajo,
            datos_batch.ids_sitios,
            id_oportunidad
        )

    async def update_sitios_cascada(self, conn, id_oportunidad: UUID, id_estatus_global: int, 
                                  fecha_cierre: datetime, kpi_interno: str, kpi_compromiso: str):
        # Solo actualizar sitios NO terminales (evitar reabrir o cambiar estatus de cerrados)
        # IDs terminales hardcoded por seguridad (o pasados como arg, pero SQL es más directo)
        # 2=Entregado, 3=Cancelado, 4=Perdido, 5=Ganada (según catálogo estándar)
        # Mejor: Usamos "NOT IN" con subselect o filtro lógico.
        query = """
            UPDATE tb_sitios_oportunidad
            SET id_estatus_global = $1,
                fecha_cierre = $2,
                kpi_status_interno = $3,
                kpi_status_compromiso = $4
            WHERE id_oportunidad = $5
            AND id_estatus_global NOT IN (
                SELECT id FROM tb_cat_estatus_global 
                WHERE LOWER(nombre) IN ('entregado', 'cancelado', 'perdido', 'ganada')
            )
        """
        await conn.execute(query, id_estatus_global, fecha_cierre, kpi_interno, kpi_compromiso, id_oportunidad)

    async def update_retrabajo_single(self, conn, id_oportunidad: UUID, id_motivo_retrabajo: int):
        await conn.execute("""
            UPDATE tb_sitios_oportunidad
            SET es_retrabajo = TRUE,
                id_motivo_retrabajo = $1
            WHERE id_oportunidad = $2
        """, id_motivo_retrabajo, id_oportunidad)

    async def update_retrabajo_multi(self, conn, id_oportunidad: UUID, sitios_ids: List[UUID], id_motivo_retrabajo: int):
        await conn.execute("""
            UPDATE tb_sitios_oportunidad
            SET es_retrabajo = TRUE,
                id_motivo_retrabajo = $1
            WHERE id_sitio = ANY($2)
            AND id_oportunidad = $3
        """, id_motivo_retrabajo, sitios_ids, id_oportunidad)

    async def check_any_retrabajo(self, conn, id_oportunidad: UUID) -> bool:
        """Verifica si existe AL MENOS UN sitio marcado como retrabajo."""
        return await conn.fetchval("""
            SELECT EXISTS(
                SELECT 1 FROM tb_sitios_oportunidad 
                WHERE id_oportunidad = $1 AND es_retrabajo = TRUE
            )
        """, id_oportunidad)

    async def update_es_retrabajo_parent(self, conn, id_oportunidad: UUID, es_retrabajo: bool):
        """Sincroniza el flag es_retrabajo del padre."""
        await conn.execute("""
            UPDATE tb_oportunidades 
            SET es_retrabajo = $1 
            WHERE id_oportunidad = $2
        """, es_retrabajo, id_oportunidad)

    async def get_catalogos_create(self, conn, id_tecnologia: int, id_tipo: int) -> tuple:
        tec = await conn.fetchval("SELECT nombre FROM tb_cat_tecnologias WHERE id = $1", id_tecnologia)
        tipo = await conn.fetchval("SELECT nombre FROM tb_cat_tipos_solicitud WHERE id = $1", id_tipo)
        return tec, tipo

    async def insert_oportunidad_completa(self, conn, data: Dict[str, Any]):
        query = """
            INSERT INTO tb_oportunidades (
                id_oportunidad, op_id_estandar, id_interno_simulacion,
                titulo_proyecto, nombre_proyecto, cliente_nombre,
                canal_venta, id_tecnologia, id_tipo_solicitud,
                id_estatus_global, cantidad_sitios, prioridad,
                direccion_obra, google_maps_link, coordenadas_gps, sharepoint_folder_url,
                fecha_solicitud, creado_por_id, solicitado_por,
                es_fuera_horario, es_carga_manual,
                clasificacion_solicitud, cliente_id
            ) VALUES (
                $1, $2, $3,
                $4, $5, $6,
                $7, $8, $9,
                $10, $11, $12,
                $13, $14, $15, $16,
                $17, $18, $19,
                $20, $21,
                $22, $23
            )
        """
        await conn.execute(query,
            data['id'], data['op_id_estandar'], data['id_interno'],
            data['titulo_proyecto'], data['nombre_proyecto'], data['cliente_nombre'],
            data['canal_venta'], data['id_tecnologia'], data['id_tipo_solicitud'],
            data['id_estatus_global'], data['cantidad_sitios'], data['prioridad'],
            data['direccion_obra'], data['google_maps_link'], data['coordenadas_gps'], data['sharepoint_folder_url'],
            data['fecha_solicitud'], data['creado_por_id'], data['solicitado_por'],
            data['es_fuera_horario'], data['es_carga_manual'],
            data['clasificacion_solicitud'], data['cliente_id']
        )

    async def get_sitios_list(self, conn, id_oportunidad: UUID) -> List[Dict[str, Any]]:
        rows = await conn.fetch("""
            SELECT s.id_sitio, s.nombre_sitio, s.direccion, s.id_estatus_global,
                   e.nombre as nombre_estatus, s.fecha_cierre
            FROM tb_sitios_oportunidad s
            LEFT JOIN tb_cat_estatus_global e ON s.id_estatus_global = e.id
            WHERE s.id_oportunidad = $1 ORDER BY s.nombre_sitio
        """, id_oportunidad)
        return [dict(r) for r in rows]

    async def get_detalles_bess(self, conn, id_oportunidad: UUID) -> Optional[Dict[str, Any]]:
        row = await conn.fetchrow("SELECT * FROM tb_detalles_bess WHERE id_oportunidad = $1", id_oportunidad)
        return dict(row) if row else None

    async def get_comentarios_workflow(self, conn, id_oportunidad: UUID) -> List[Dict[str, Any]]:
        rows = await conn.fetch("""
            SELECT 
                comentario,
                usuario_nombre,
                modulo_origen,
                fecha_comentario AT TIME ZONE 'UTC' AT TIME ZONE 'America/Mexico_City' as fecha_comentario
            FROM tb_comentarios_workflow
            WHERE id_oportunidad = $1
            ORDER BY fecha_comentario DESC
        """, id_oportunidad)
        return [dict(r) for r in rows]

    async def get_catalog_tecnologias(self, conn) -> List[Dict[str, Any]]:
        rows = await conn.fetch("SELECT id, nombre FROM tb_cat_tecnologias WHERE activo = true ORDER BY nombre")
        return [dict(r) for r in rows]
    
    async def get_catalog_tipos_solicitud_ui(self, conn, codigos: List[str]) -> List[Dict[str, Any]]:
        rows = await conn.fetch(f"""
            SELECT id, nombre 
            FROM tb_cat_tipos_solicitud 
            WHERE activo = true 
            AND codigo_interno = ANY($1)
            ORDER BY nombre
        """, codigos)
        return [dict(r) for r in rows]
    
    async def get_usuarios_all(self, conn) -> List[Dict[str, Any]]:
        rows = await conn.fetch("SELECT id_usuario, nombre FROM tb_usuarios WHERE is_active = true ORDER BY nombre")
        return [dict(r) for r in rows]

    # --- KPIs & Dashboard Stats ---

    async def get_kpi_total_oportunidades(self, conn, where_clause: str) -> int:
        return await conn.fetchval(f"SELECT count(*) FROM tb_oportunidades {where_clause}")

    async def get_kpi_conteo_estatus(self, conn, status_ids: List[int]) -> int:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM tb_oportunidades WHERE id_estatus_global = ANY($1) AND email_enviado = true",
            status_ids
        )
    
    async def get_kpi_levantamientos(self, conn, id_levantamiento: int) -> int:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM tb_oportunidades WHERE id_tipo_solicitud = $1 AND email_enviado = true",
            id_levantamiento
        )
    
    async def get_chart_tech_mix(self, conn) -> List[Dict[str, Any]]:
        rows = await conn.fetch("""
            SELECT t.nombre, COUNT(o.id_oportunidad) as total 
            FROM tb_oportunidades o
            JOIN tb_cat_tecnologias t ON o.id_tecnologia = t.id
            WHERE o.email_enviado = true
            GROUP BY t.nombre
            ORDER BY total DESC
            LIMIT 5
        """)
        return [dict(r) for r in rows]
    
    async def get_chart_trend(self, conn) -> List[Dict[str, Any]]:
        rows = await conn.fetch("""
            SELECT to_char(fecha_solicitud, 'YYYY-MM-DD') as fecha, COUNT(*) as total
            FROM tb_oportunidades
            WHERE fecha_solicitud >= NOW() - INTERVAL '30 days' AND email_enviado = true
            GROUP BY 1
            ORDER BY 1 ASC
        """)
        return [dict(r) for r in rows]

    async def get_status_map(self, conn) -> Dict[str, int]:
        rows = await conn.fetch("SELECT id, LOWER(nombre) as nombre FROM tb_cat_estatus_global WHERE activo = true")
        return {r['nombre']: r['id'] for r in rows}
    
    async def get_id_levantamiento(self, conn) -> Optional[int]:
         return await conn.fetchval(
            "SELECT id FROM tb_cat_tipos_solicitud WHERE LOWER(nombre) = 'levantamiento' LIMIT 1"
        )

    async def get_oportunidades_filtradas(self, conn, tab: str, subtab: Optional[str], q: Optional[str], limit: int, filtro_tecnologia_id: Optional[int] = None) -> List[Dict[str, Any]]:
        status_map = await self.get_status_map(conn)
        
        # Query base
        query = """
            SELECT
                o.id_oportunidad, o.op_id_estandar, o.nombre_proyecto, o.titulo_proyecto, o.cliente_nombre,
                o.fecha_solicitud, estatus.nombre as status_global, o.id_estatus_global,
                o.id_interno_simulacion, o.deadline_calculado, o.deadline_negociado,
                o.fecha_entrega_simulacion, o.cantidad_sitios, o.prioridad, o.es_fuera_horario,
                o.es_licitacion,
                o.fecha_ideal_usuario,
                tipo_sol.nombre as tipo_solicitud,
                u_creador.nombre as solicitado_por,
                u_sim.nombre as responsable_simulacion,
                u_sim.email as responsable_email,
                CASE WHEN db.id IS NOT NULL THEN true ELSE false END as tiene_detalles_bess,
                lev_estatus.nombre as status_levantamiento,
                lev.fecha_visita_programada as fecha_programada,
                lev.id_levantamiento,
                u_tecnico.nombre as tecnico_asignado_nombre
            FROM tb_oportunidades o
            LEFT JOIN tb_cat_estatus_global estatus ON o.id_estatus_global = estatus.id
            LEFT JOIN tb_cat_tipos_solicitud tipo_sol ON o.id_tipo_solicitud = tipo_sol.id
            LEFT JOIN tb_usuarios u_creador ON o.creado_por_id = u_creador.id_usuario
            LEFT JOIN tb_usuarios u_sim ON o.responsable_simulacion_id = u_sim.id_usuario
            LEFT JOIN tb_detalles_bess db ON o.id_oportunidad = db.id_oportunidad
            LEFT JOIN tb_levantamientos lev ON o.id_oportunidad = lev.id_oportunidad
            LEFT JOIN tb_cat_estatus_global lev_estatus ON lev.id_estatus_global = lev_estatus.id
            LEFT JOIN tb_usuarios u_tecnico ON lev.tecnico_asignado_id = u_tecnico.id_usuario
            WHERE o.email_enviado = true
        """
        
        params = []
        
        # Filtro de Tabs
        if tab == "historial":
             if subtab == "entregado":
                  ids_historial = [status_map.get("entregado")]
             elif subtab == "cancelado_perdido":
                  ids_historial = [status_map.get("cancelado"), status_map.get("perdido")]
             else:
                  ids_historial = [status_map.get("entregado"), status_map.get("ganada")]
             
             ids_historial = [i for i in ids_historial if i is not None]
             
             if ids_historial:
                 placeholders = ','.join([f'${len(params) + i + 1}' for i in range(len(ids_historial))])
                 query += f" AND o.id_estatus_global IN ({placeholders})"
                 params.extend(ids_historial)
             
             # Excluir Levantamientos
             id_levantamiento = await self.get_id_levantamiento(conn)
             if id_levantamiento:
                 query += f" AND o.id_tipo_solicitud != ${len(params) + 1}"
                 params.append(id_levantamiento)

        elif tab == "levantamientos":
            id_levantamiento = await self.get_id_levantamiento(conn)
            if id_levantamiento:
                query += f" AND o.id_tipo_solicitud = ${len(params) + 1}"
                params.append(id_levantamiento)
            
            if subtab == 'realizados':
                id_entregado = status_map.get('entregado')
                if id_entregado:
                    query += f" AND o.id_estatus_global = ${len(params) + 1}"
                    params.append(id_entregado)
            else:
                id_entregado = status_map.get('entregado')
                if id_entregado:
                    query += f" AND o.id_estatus_global != ${len(params) + 1}"
                    params.append(id_entregado)
                
        elif tab == "ganadas":
             id_ganada = status_map.get('ganada')
             if id_ganada:
                 query += f" AND o.id_estatus_global = ${len(params) + 1}"
                 params.append(id_ganada)
                
        else:  # ACTIVOS (Default)
            ids_terminales = [
                status_map.get("entregado"), status_map.get("cancelado"), 
                status_map.get("perdido"), status_map.get("ganada")
            ]
            ids_terminales = [i for i in ids_terminales if i is not None]
            
            if ids_terminales:
                placeholders = ','.join([f'${len(params) + i + 1}' for i in range(len(ids_terminales))])
                query += f" AND o.id_estatus_global NOT IN ({placeholders})"
                params.extend(ids_terminales)
            
            id_levantamiento = await self.get_id_levantamiento(conn)
            if id_levantamiento:
                query += f" AND o.id_tipo_solicitud != ${len(params) + 1}"
                params.append(id_levantamiento)

        # Filtro de Tecnología (Nuevo)
        if filtro_tecnologia_id:
            query += f" AND o.id_tecnologia = ${len(params) + 1}"
            params.append(filtro_tecnologia_id)

        # Búsqueda
        if q:
            param_ph = f"${len(params) + 1}"
            query += f" AND (o.op_id_estandar ILIKE {param_ph} OR o.nombre_proyecto ILIKE {param_ph} OR o.cliente_nombre ILIKE {param_ph})"
            params.append(f"%{q}%")

        query += " ORDER BY o.fecha_solicitud DESC"
        
        if limit > 0:
            query += f" LIMIT {limit}"
        
        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    # --- Reporting Support Methods ---

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
        """Obtiene IDs de catálogos para reportes"""
        estatus = await conn.fetch(
            "SELECT id, LOWER(nombre) as nombre FROM tb_cat_estatus_global WHERE activo = true"
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
            "motivos_no_viables": [row['id'] for row in motivos_nv]
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
                    o.fecha_entrega_simulacion,
                    o.cantidad_sitios
                FROM tb_sitios_oportunidad s
                JOIN tb_oportunidades o ON s.id_oportunidad = o.id_oportunidad
                JOIN tb_cat_estatus_global e ON o.id_estatus_global = e.id
                {where_clause}
            )
            SELECT
                COUNT(DISTINCT id_oportunidad) as total_solicitudes,
                COUNT(DISTINCT CASE WHEN id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) THEN id_oportunidad END) as total_ofertas,
                COUNT(DISTINCT CASE WHEN id_estatus_global IN (${idx_pendiente}, ${idx_proceso}, ${idx_revision}) THEN id_oportunidad END) as en_espera,
                COUNT(DISTINCT CASE WHEN id_estatus_global = ${idx_cancelado} THEN id_oportunidad END) as canceladas,
                COUNT(DISTINCT CASE WHEN id_estatus_global = ${idx_cancelado} AND id_motivo_cierre = ANY(${idx_no_viables}::integer[]) THEN id_oportunidad END) as no_viables,
                COUNT(DISTINCT CASE WHEN clasificacion_solicitud = 'EXTRAORDINARIO' THEN id_oportunidad END) as extraordinarias,
                COUNT(DISTINCT CASE WHEN parent_id IS NOT NULL THEN id_oportunidad END) as versiones,
                COUNT(CASE WHEN es_retrabajo = TRUE THEN id_sitio END) as retrabajos,
                COUNT(DISTINCT CASE WHEN es_licitacion = TRUE THEN id_oportunidad END) as licitaciones,
                COUNT(CASE WHEN kpi_status_interno = 'Entrega a tiempo' AND id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) AND id_tipo_solicitud != ${idx_levantamiento} THEN id_sitio END) as entregas_a_tiempo_interno,
                COUNT(CASE WHEN kpi_status_interno = 'Entrega tarde' AND id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) AND id_tipo_solicitud != ${idx_levantamiento} THEN id_sitio END) as entregas_tarde_interno,
                COUNT(CASE WHEN kpi_status_compromiso = 'Entrega a tiempo' AND id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) AND id_tipo_solicitud != ${idx_levantamiento} THEN id_sitio END) as entregas_a_tiempo_compromiso,
                COUNT(CASE WHEN kpi_status_compromiso = 'Entrega tarde' AND id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) AND id_tipo_solicitud != ${idx_levantamiento} THEN id_sitio END) as entregas_tarde_compromiso,
                COUNT(DISTINCT CASE WHEN id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) AND fecha_entrega_simulacion IS NULL THEN id_oportunidad END) as sin_fecha_entrega,
                AVG(CASE WHEN tiempo_elaboracion_horas IS NOT NULL AND id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) THEN tiempo_elaboracion_horas END) as tiempo_promedio_horas,
                COUNT(id_sitio) as total_sitios,
                COUNT(CASE WHEN id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) THEN id_sitio END) as total_sitios_entregados,
                COUNT(DISTINCT CASE WHEN cantidad_sitios > 1 THEN id_oportunidad END) as oportunidades_multisitio
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
            JOIN tb_cat_estatus_global e ON o.id_estatus_global = e.id
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
                JOIN tb_cat_estatus_global e ON o.id_estatus_global = e.id
                {where_clause}
                AND o.tiempo_elaboracion_horas IS NOT NULL
                AND o.id_estatus_global IN (
                    SELECT id FROM tb_cat_estatus_global WHERE LOWER(nombre) IN ('entregado', 'perdido')
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
        id_ganada = cats['estatus'].get('ganada')  # FIX: Incluir Ganada
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
                JOIN tb_cat_estatus_global e ON o.id_estatus_global = e.id
                {where_clause}
            )
            SELECT
                t.id as id_tecnologia, t.nombre,
                COUNT(DISTINCT st.id_oportunidad) as total_solicitudes,
                COUNT(DISTINCT st.id_oportunidad) FILTER (WHERE st.id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada})) as total_ofertas,
                COUNT(*) FILTER (WHERE st.kpi_status_interno = 'Entrega a tiempo' AND st.id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) AND st.id_tipo_solicitud != ${idx_levantamiento}) as entregas_a_tiempo_interno,
                COUNT(*) FILTER (WHERE st.kpi_status_interno = 'Entrega tarde' AND st.id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) AND st.id_tipo_solicitud != ${idx_levantamiento}) as entregas_tarde_interno,
                COUNT(*) FILTER (WHERE st.kpi_status_compromiso = 'Entrega a tiempo' AND st.id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) AND st.id_tipo_solicitud != ${idx_levantamiento}) as entregas_a_tiempo_compromiso,
                COUNT(*) FILTER (WHERE st.kpi_status_compromiso = 'Entrega tarde' AND st.id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) AND st.id_tipo_solicitud != ${idx_levantamiento}) as entregas_tarde_compromiso,
                COUNT(DISTINCT st.id_oportunidad) FILTER (WHERE st.clasificacion_solicitud = 'EXTRAORDINARIO') as extraordinarias,
                COUNT(DISTINCT st.id_oportunidad) FILTER (WHERE st.parent_id IS NOT NULL) as versiones,
                COUNT(*) FILTER (WHERE st.es_retrabajo = TRUE) as retrabajos,
                COUNT(DISTINCT st.id_oportunidad) FILTER (WHERE st.es_licitacion = TRUE) as licitaciones,
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
        return [dict(r) for r in rows]

    async def get_report_tabla_contabilizacion(self, conn, filters: Dict[str, Any], cats: Dict) -> List[Dict[str, Any]]:
        where_clause, params = self._build_report_where_clause(filters)
        
        id_entregado = cats['estatus'].get('entregado')
        id_perdido = cats['estatus'].get('perdido')
        id_ganada = cats['estatus'].get('ganada')  # FIX: Incluir Ganada
        id_levantamiento = cats['tipos'].get('levantamiento')
        
        params.extend([id_entregado, id_perdido, id_ganada, id_levantamiento])
        idx_entregado, idx_perdido, idx_ganada, idx_levantamiento = len(params)-3, len(params)-2, len(params)-1, len(params)

        query = f"""
            SELECT 
                ts.id as id_tipo_solicitud, ts.nombre, ts.codigo_interno,
                COUNT(DISTINCT o.id_oportunidad) as total,
                COUNT(CASE WHEN s.kpi_status_interno = 'Entrega a tiempo' AND o.id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) THEN s.id_sitio END) as entregas_a_tiempo_interno,
                COUNT(CASE WHEN s.kpi_status_interno = 'Entrega tarde' AND o.id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) THEN s.id_sitio END) as entregas_tarde_interno,
                COUNT(CASE WHEN s.kpi_status_compromiso = 'Entrega a tiempo' AND o.id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) THEN s.id_sitio END) as entregas_a_tiempo_compromiso,
                COUNT(CASE WHEN s.kpi_status_compromiso = 'Entrega tarde' AND o.id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) THEN s.id_sitio END) as entregas_tarde_compromiso,
                COUNT(DISTINCT CASE WHEN o.id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada}) AND o.fecha_entrega_simulacion IS NULL THEN o.id_oportunidad END) as sin_fecha,
                COUNT(DISTINCT CASE WHEN o.es_licitacion = TRUE THEN o.id_oportunidad END) as licitaciones,
                (ts.id = ${idx_levantamiento}) as es_levantamiento
            FROM tb_cat_tipos_solicitud ts
            LEFT JOIN tb_oportunidades o ON ts.id = o.id_tipo_solicitud
            LEFT JOIN tb_sitios_oportunidad s ON o.id_oportunidad = s.id_oportunidad
            LEFT JOIN tb_cat_estatus_global e ON o.id_estatus_global = e.id
            {where_clause}
            GROUP BY ts.id, ts.nombre, ts.codigo_interno HAVING COUNT(DISTINCT o.id_oportunidad) > 0
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
            INNER JOIN tb_cat_estatus_global e ON o.id_estatus_global = e.id
            {where_clause}
            ORDER BY u.nombre
        """
        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    async def get_report_tiempo_promedio_tipo(self, conn, user_id: UUID, filters: Dict[str, Any], cats: Dict) -> Dict[str, float]:
        where_clause, params = self._build_report_where_clause(filters)
        idx_user = len(params) + 1
        params.append(user_id)
        
        id_entregado = cats['estatus'].get('entregado')
        id_perdido = cats['estatus'].get('perdido')
        id_ganada = cats['estatus'].get('ganada')  # FIX: Incluir Ganada
        params.extend([id_entregado, id_perdido, id_ganada])
        idx_entregado, idx_perdido, idx_ganada = len(params)-2, len(params)-1, len(params)
        
        query = f"""
            SELECT ts.nombre as tipo, AVG(o.tiempo_elaboracion_horas) / 24 as dias_promedio
            FROM tb_oportunidades o
            JOIN tb_cat_tipos_solicitud ts ON o.id_tipo_solicitud = ts.id
            JOIN tb_cat_estatus_global e ON o.id_estatus_global = e.id
            {where_clause}
            AND o.responsable_simulacion_id = ${idx_user}
            AND o.tiempo_elaboracion_horas IS NOT NULL
            AND o.id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada})
            AND o.id_tipo_solicitud != (SELECT id FROM tb_cat_tipos_solicitud WHERE LOWER(nombre) = 'levantamiento')
            GROUP BY ts.nombre HAVING AVG(o.tiempo_elaboracion_horas) IS NOT NULL
        """
        rows = await conn.fetch(query, *params)
        return {row['tipo']: round(float(row['dias_promedio']), 1) for row in rows}

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
                JOIN tb_cat_estatus_global e ON o.id_estatus_global = e.id
                {where_clause}
            )
            SELECT
                mes,
                COUNT(DISTINCT id_oportunidad) as solicitudes_recibidas,
                COUNT(DISTINCT id_oportunidad) FILTER (WHERE id_estatus_global IN (${idx_entregado}, ${idx_perdido}, ${idx_ganada})) as ofertas_generadas,
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
                COUNT(*) as total_sitios
            FROM sitios_mensual
            GROUP BY mes ORDER BY mes
        """
        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    async def get_report_catalogos_filtros(self, conn) -> Dict[str, Any]:
        """Obtiene catálogos para filtros de reportes"""
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

    async def get_chart_estatus(self, conn, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Distribución por estatus."""
        where_clause, params = self._build_report_where_clause(filters)
        
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
        return [dict(r) for r in rows]

    async def get_chart_mensual(self, conn, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Solicitudes por mes."""
        # Note: Postgres EXTRACT(MONTH ...) returns 1-12
        where_clause, params = self._build_report_where_clause(filters)
        
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
        return [dict(r) for r in rows]

    async def get_chart_tecnologia(self, conn, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Distribución por tecnología."""
        where_clause, params = self._build_report_where_clause(filters)
        
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
        return [dict(r) for r in rows]

QUERY_INSERT_HISTORIAL_ESTATUS = """
    INSERT INTO tb_historial_estatus (
        id_oportunidad, id_estatus_anterior, id_estatus_nuevo, 
        fecha_cambio_real, fecha_cambio_sla, cambiado_por_id
    ) VALUES (
        $1, $2, $3, $4, $5, $6
    )
"""

def get_db_service() -> SimulacionDBService:
    return SimulacionDBService()
