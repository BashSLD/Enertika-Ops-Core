from typing import List, Optional, Dict, Any, Tuple
from uuid import UUID
from datetime import datetime, date
from decimal import Decimal
import logging

from core.database import get_db_connection
from core.config_service import ConfigService

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
                "SELECT id, nombre FROM tb_cat_estatus_oportunidades WHERE activo = true AND modulo_aplicable = 'SIMULACION' AND id != $1 ORDER BY id",
                exclude_id
            )
        else:
            rows = await conn.fetch(
                "SELECT id, nombre FROM tb_cat_estatus_oportunidades WHERE activo = true AND modulo_aplicable = 'SIMULACION' ORDER BY id"
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
        ORDER BY fecha_carga ASC
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
                id_estatus_global, deadline_calculado, fecha_solicitud, id_tecnologia
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

    async def insert_simulaciones_adicionales(
        self, conn, id_oportunidad: UUID, sims: list,
        kpi_interno: Optional[str], kpi_compromiso: Optional[str], fecha_entrega
    ):
        """Inserta las simulaciones adicionales capturadas al momento del cierre."""
        for idx, sim in enumerate(sims):
            await conn.execute("""
                INSERT INTO tb_simulaciones_adicionales
                    (id_oportunidad, numero, potencia_cierre_fv_kwp, capacidad_cierre_bess_kwh,
                     monto_cierre_usd, kpi_status_interno, kpi_status_compromiso, fecha_entrega)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (id_oportunidad, numero) DO NOTHING
            """,
                id_oportunidad,
                idx + 2,  # numero: la principal es siempre #1
                sim.potencia_cierre_fv_kwp,
                sim.capacidad_cierre_bess_kwh,
                sim.monto_cierre_usd,
                kpi_interno,
                kpi_compromiso,
                fecha_entrega
            )

    async def get_simulaciones_adicionales(self, conn, id_oportunidad: UUID) -> list:
        """Retorna las simulaciones adicionales registradas para una oportunidad, ordenadas por numero."""
        rows = await conn.fetch("""
            SELECT id, numero, potencia_cierre_fv_kwp, capacidad_cierre_bess_kwh,
                   monto_cierre_usd, kpi_status_interno, kpi_status_compromiso, fecha_entrega
            FROM tb_simulaciones_adicionales
            WHERE id_oportunidad = $1
            ORDER BY numero
        """, id_oportunidad)
        return [dict(r) for r in rows]

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
                SELECT id FROM tb_cat_estatus_oportunidades 
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
                   e.nombre as nombre_estatus, s.fecha_cierre, s.es_retrabajo,
                   s.google_maps_link
            FROM tb_sitios_oportunidad s
            LEFT JOIN tb_cat_estatus_oportunidades e ON s.id_estatus_global = e.id
            WHERE s.id_oportunidad = $1 ORDER BY s.fecha_carga ASC
        """, id_oportunidad)
        return [dict(r) for r in rows]

    async def get_detalles_bess(self, conn, id_oportunidad: UUID) -> Optional[Dict[str, Any]]:
        row = await conn.fetchrow("SELECT * FROM tb_detalles_bess WHERE id_oportunidad = $1", id_oportunidad)
        return dict(row) if row else None

    async def get_comentarios_workflow(self, conn, id_oportunidad: UUID) -> List[Dict[str, Any]]:
        rows = await conn.fetch("""
            WITH cadena AS (
                SELECT id_oportunidad FROM tb_oportunidades WHERE id_oportunidad = $1
                UNION
                SELECT id_oportunidad FROM tb_oportunidades WHERE parent_id = $1
                UNION
                SELECT parent_id FROM tb_oportunidades 
                WHERE id_oportunidad = $1 AND parent_id IS NOT NULL
                UNION
                SELECT id_oportunidad FROM tb_oportunidades 
                WHERE parent_id = (
                    SELECT parent_id FROM tb_oportunidades WHERE id_oportunidad = $1
                ) AND parent_id IS NOT NULL
            )
            SELECT 
                cw.comentario,
                cw.usuario_nombre,
                cw.modulo_origen,
                cw.fecha_comentario AT TIME ZONE 'UTC' AT TIME ZONE 'America/Mexico_City' as fecha_comentario,
                op.op_id_estandar as comentario_op_estandar
            FROM tb_comentarios_workflow cw
            LEFT JOIN tb_oportunidades op ON cw.id_oportunidad = op.id_oportunidad
            WHERE cw.id_oportunidad IN (SELECT id_oportunidad FROM cadena)
            ORDER BY cw.fecha_comentario DESC
        """, id_oportunidad)
        return [dict(r) for r in rows]

    async def get_catalog_tecnologias(self, conn) -> List[Dict[str, Any]]:
        cache_key = "SIM_tecnologias_list"
        cached = await ConfigService.get_cached_value(cache_key)
        if cached:
            return cached
        rows = await conn.fetch("SELECT id, nombre FROM tb_cat_tecnologias WHERE activo = true ORDER BY nombre")
        result = [dict(r) for r in rows]
        await ConfigService.set_cached_value(cache_key, result)
        return result
    
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

    async def get_kpi_total_oportunidades(self, conn, email_enviado: bool = True) -> int:
        """Cuenta total de oportunidades con filtro parametrizado."""
        return await conn.fetchval(
            "SELECT count(*) FROM tb_oportunidades WHERE email_enviado = $1",
            email_enviado
        )

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
        return await ConfigService.get_catalog_map(conn, "tb_cat_estatus_oportunidades", "nombre", "id")
    
    async def get_id_levantamiento(self, conn) -> Optional[int]:
         return await conn.fetchval(
            "SELECT id FROM tb_cat_tipos_solicitud WHERE LOWER(nombre) = 'levantamiento' LIMIT 1"
        )

    async def get_oportunidades_filtradas(self, conn, tab: str, subtab: Optional[str], q: Optional[str], limit: int, page: int = 1, filtro_tecnologia_id: Optional[int] = None) -> dict:
        status_map = await self.get_status_map(conn)
        
        # Query base
        query = """
            SELECT
                o.id_oportunidad, o.op_id_estandar, o.nombre_proyecto, o.titulo_proyecto, o.cliente_nombre,
                o.fecha_solicitud, estatus.nombre as status_global, o.id_estatus_global,
                o.id_interno_simulacion, o.deadline_calculado, o.deadline_negociado,
                o.fecha_entrega_simulacion, o.cantidad_sitios, o.prioridad, o.es_fuera_horario,
                o.es_licitacion,
                o.fecha_ideal_usuario, o.google_maps_link,
                tipo_sol.nombre as tipo_solicitud,
                u_creador.nombre as solicitado_por,
                u_sim.nombre as responsable_simulacion,
                u_sim.email as responsable_email,
                CASE WHEN db.id IS NOT NULL THEN true ELSE false END as tiene_detalles_bess,
                lev_estatus.nombre as status_levantamiento,
                lev.fecha_visita_programada as fecha_programada,
                lev.id_levantamiento,
                u_tecnico.nombre as tecnico_asignado_nombre,
                COUNT(*) OVER() AS total_count
            FROM tb_oportunidades o
            LEFT JOIN tb_cat_estatus_oportunidades estatus ON o.id_estatus_global = estatus.id
            LEFT JOIN tb_cat_tipos_solicitud tipo_sol ON o.id_tipo_solicitud = tipo_sol.id
            LEFT JOIN tb_usuarios u_creador ON o.creado_por_id = u_creador.id_usuario
            LEFT JOIN tb_usuarios u_sim ON o.responsable_simulacion_id = u_sim.id_usuario
            LEFT JOIN tb_detalles_bess db ON o.id_oportunidad = db.id_oportunidad
            LEFT JOIN (
                SELECT DISTINCT ON (l.id_oportunidad)
                    l.id_oportunidad, l.id_levantamiento, l.id_estatus_global,
                    l.fecha_visita_programada, l.tecnico_asignado_id
                FROM tb_levantamientos l
                ORDER BY l.id_oportunidad, l.id_estatus_global ASC
            ) lev ON o.id_oportunidad = lev.id_oportunidad
            LEFT JOIN tb_cat_estatus_levantamiento lev_estatus ON lev.id_estatus_global = lev_estatus.id
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
                # Realizados: Completado (5), Entregado (6) — tb_cat_estatus_levantamiento
                # Se filtra por el estatus del LEVANTAMIENTO (lev.id_estatus_global), no de la oportunidad
                ids_realizados = [5, 6]
                placeholders = ','.join([f'${len(params) + i + 1}' for i in range(len(ids_realizados))])
                query += f" AND lev.id_estatus_global IN ({placeholders})"
                params.extend(ids_realizados)

            else:
                # Solicitados (Default): Pendiente (1), Agendado (2), En Proceso (3), Pospuesto (4) — tb_cat_estatus_levantamiento
                ids_solicitados = [1, 2, 3, 4]
                placeholders = ','.join([f'${len(params) + i + 1}' for i in range(len(ids_solicitados))])
                query += f" AND lev.id_estatus_global IN ({placeholders})"
                params.extend(ids_solicitados)
                
        elif tab == "ganadas":
             id_ganada = status_map.get('ganada')
             if id_ganada:
                 query += f" AND o.id_estatus_global = ${len(params) + 1}"
                 params.append(id_ganada)

        elif tab == "monitoreo":
            id_monitoreo = status_map.get("monitoreo de cotización")
            if id_monitoreo:
                query += f" AND o.id_estatus_global = ${len(params) + 1}"
                params.append(id_monitoreo)
            id_levantamiento = await self.get_id_levantamiento(conn)
            if id_levantamiento:
                query += f" AND o.id_tipo_solicitud != ${len(params) + 1}"
                params.append(id_levantamiento)

        else:  # ACTIVOS (Default)
            ids_terminales = [
                status_map.get("entregado"), status_map.get("cancelado"),
                status_map.get("perdido"), status_map.get("ganada"),
                status_map.get("monitoreo de cotización"),
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

        offset = (page - 1) * limit
        query += f" ORDER BY o.fecha_solicitud DESC LIMIT {limit} OFFSET {offset}"

        rows = await conn.fetch(query, *params)
        total = rows[0]['total_count'] if rows else 0
        total_pages = (total + limit - 1) // limit
        return {
            "items": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
        }



    async def get_simulaciones_para_excel(
        self, conn,
        fecha_inicio: date, fecha_fin: date,
        responsable_id=None, id_tecnologia: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        rows = await conn.fetch("""
            SELECT
                o.op_id_estandar,
                u.nombre                                                        AS responsable,
                o.cliente_nombre,
                o.titulo_proyecto,
                o.fecha_solicitud   AT TIME ZONE 'America/Mexico_City'          AS fecha_solicitud,
                o.deadline_calculado AT TIME ZONE 'America/Mexico_City'         AS deadline_calculado,
                o.deadline_negociado AT TIME ZONE 'America/Mexico_City'         AS deadline_negociado,
                o.fecha_entrega_simulacion AT TIME ZONE 'America/Mexico_City'   AS fecha_entrega,
                e.nombre                                                        AS estatus,
                o.kpi_status_sla_interno,
                o.kpi_status_compromiso
            FROM tb_oportunidades o
            LEFT JOIN tb_cat_estatus_oportunidades e ON e.id = o.id_estatus_global
            LEFT JOIN tb_usuarios u ON u.id_usuario = o.responsable_simulacion_id
            WHERE (o.fecha_solicitud AT TIME ZONE 'America/Mexico_City')::date >= $1
              AND (o.fecha_solicitud AT TIME ZONE 'America/Mexico_City')::date <= $2
              AND ($3::uuid IS NULL OR o.responsable_simulacion_id = $3)
              AND ($4::int IS NULL OR o.id_tecnologia = $4)
            ORDER BY o.fecha_solicitud ASC
        """, fecha_inicio, fecha_fin, responsable_id, id_tecnologia)
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
