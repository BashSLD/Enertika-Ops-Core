# ==============================================================
# modules/levantamientos/db_service.py
# Capa de consultas a BD para el módulo Levantamientos.
# El service.py consume estos métodos — aquí no hay lógica
# de negocio, solo queries + mapeo de resultados.
# ==============================================================

from uuid import UUID
from typing import List, Optional
import logging
import json

logger = logging.getLogger("Levantamientos.DBService")


class LevantamientosDBService:
    """
    Todas las consultas que necesitan los endpoints de:
      - Modales (detalle, posponer, reagendar, viaticos)
      - CRUD de viaticos
      - Envío y registro histórico de solicitud
    """

    # ----------------------------------------------------------
    # DATOS DEL LEVANTAMIENTO (queries compartidas por modales)
    # ----------------------------------------------------------

    async def get_levantamiento_base(self, conn, id_levantamiento: UUID) -> Optional[dict]:
        """
        Obtiene los datos principales del levantamiento con joins a
        oportunidad, sitio y usuarios (solicitante, técnico, jefe).
        Usado por: modal detalle, posponer, reagendar, viaticos.
        """
        row = await conn.fetchrow("""
            SELECT
                l.id_levantamiento,
                l.id_oportunidad,
                l.id_sitio,
                l.id_estatus_global,
                l.fecha_solicitud,
                l.fecha_visita_programada,
                l.motivo_pospone,
                l.fecha_reagenda,
                l.created_at,
                l.updated_at,

                -- Oportunidad
                o.op_id_estandar,
                o.nombre_proyecto,
                o.titulo_proyecto,
                o.cliente_nombre,
                o.prioridad,
                o.direccion_obra,

                -- Sitio
                s.nombre_sitio,
                s.direccion AS sitio_direccion,

                -- Usuarios
                u_sol.nombre   AS solicitante_nombre,
                u_sol.email    AS solicitante_email,
                u_tec.nombre   AS tecnico_nombre,
                u_tec.email    AS tecnico_email,
                u_jefe.nombre  AS jefe_nombre,
                u_jefe.email   AS jefe_email,

                -- Estado nombre
                est.nombre     AS estatus_nombre,
                est.color_hex  AS estatus_color
            FROM tb_levantamientos l
            INNER JOIN tb_oportunidades      o    ON l.id_oportunidad          = o.id_oportunidad
            LEFT  JOIN tb_sitios_oportunidad s    ON l.id_sitio                = s.id_sitio
            LEFT  JOIN tb_usuarios           u_sol ON l.solicitado_por_id      = u_sol.id_usuario
            LEFT  JOIN tb_usuarios           u_tec ON l.tecnico_asignado_id   = u_tec.id_usuario
            LEFT  JOIN tb_usuarios           u_jefe ON l.jefe_area_id         = u_jefe.id_usuario
            LEFT  JOIN tb_cat_estatus_global est  ON l.id_estatus_global      = est.id
            WHERE l.id_levantamiento = $1
        """, id_levantamiento)

        return dict(row) if row else None
    
    async def get_levantamiento_modal_header(self, conn, id_levantamiento: UUID) -> Optional[dict]:
        """
        Obtiene datos para header de modales (Assign/Historial).
        """
        row = await conn.fetchrow("""
            SELECT l.*, o.op_id_estandar, o.nombre_proyecto, o.cliente_nombre
            FROM tb_levantamientos l
            INNER JOIN tb_oportunidades o ON l.id_oportunidad = o.id_oportunidad
            WHERE l.id_levantamiento = $1
        """, id_levantamiento)
        return dict(row) if row else None

    async def get_asignaciones_actuales(self, conn, id_levantamiento: UUID) -> List[UUID]:
        """Retorna IDs de técnicos asignados actualmente."""
        rows = await conn.fetch("""
            SELECT tecnico_id FROM tb_levantamiento_asignaciones WHERE id_levantamiento = $1
        """, id_levantamiento)
        return [row['tecnico_id'] for row in rows]

    async def check_asignaciones(self, conn, id_levantamiento: UUID) -> bool:
        """Verifica si hay técnicos asignados (pivote o legacy)."""
        has_techs = await conn.fetchval("""
            SELECT EXISTS(SELECT 1 FROM tb_levantamiento_asignaciones WHERE id_levantamiento = $1)
        """, id_levantamiento)

        if not has_techs:
            has_techs = await conn.fetchval("""
                SELECT (tecnico_asignado_id IS NOT NULL) FROM tb_levantamientos WHERE id_levantamiento = $1
            """, id_levantamiento)
        
        return has_techs

    async def check_viaticos_sent(self, conn, id_levantamiento: UUID) -> bool:
        """Verifica si se ha enviado solicitud de viáticos."""
        return await conn.fetchval("""
            SELECT EXISTS(
                SELECT 1 FROM tb_levantamiento_viaticos_historico
                WHERE id_levantamiento = $1 
                AND estatus = 'enviado'
                AND fecha_envio > COALESCE((
                    SELECT MAX(fecha_envio) 
                    FROM tb_levantamiento_viaticos_historico 
                    WHERE id_levantamiento = $1 AND estatus = 'devuelto'
                ), '2000-01-01'::timestamp)
            )
        """, id_levantamiento)
    
    async def get_id_by_oportunidad(self, conn, id_oportunidad: UUID) -> Optional[UUID]:
        """Obtiene ID de levantamiento por ID de oportunidad."""
        return await conn.fetchval("""
            SELECT id_levantamiento FROM tb_levantamientos WHERE id_oportunidad = $1 LIMIT 1
        """, id_oportunidad)

    async def get_detalle_completo(self, conn, id_levantamiento: UUID) -> Optional[dict]:
        """
        Obtiene TODOS los detalles para el modal de vista completa.
        Incluye:
        - Datos base (get_levantamiento_base)
        - Lista completa de técnicos asignados
        - Adjuntos de entrega (tb_documentos_attachments)
        - Flag de si tiene viáticos
        """
        # 1. Datos Base
        lev = await self.get_levantamiento_base(conn, id_levantamiento)
        if not lev:
            return None
            
        # 2. Técnicos Asignados (Lista completa con nombres)
        lev['tecnicos_asignados'] = await self.get_tecnicos_asignados_detalle(conn, id_levantamiento)
        
        # 3. Adjuntos de Entrega (Metadata tipo=entrega o asociados directos)
        # Se busca en tb_documentos_attachments donde id_oportunidad match y metadata indique levantamiento
        # Ojo: El upload se hizo con id_oportunidad, y metadata={"id_levantamiento": ...}
        lev['adjuntos'] = await self.get_adjuntos_levantamiento(conn, id_levantamiento)
        
        # 4. Check Viáticos (para mostrar botón)
        lev['tiene_viaticos'] = await conn.fetchval("""
            SELECT EXISTS(SELECT 1 FROM tb_levantamiento_viaticos WHERE id_levantamiento = $1)
        """, id_levantamiento)
        
        return lev

    async def get_tecnicos_asignados_detalle(self, conn, id_levantamiento: UUID) -> List[dict]:
        """Retorna lista de diccionarios de técnicos asignados."""
        rows = await conn.fetch("""
             SELECT u.id_usuario, u.nombre, u.email
             FROM tb_levantamiento_asignaciones la
             JOIN tb_usuarios u ON la.tecnico_id = u.id_usuario
             WHERE la.id_levantamiento = $1
        """, id_levantamiento)
        return [dict(r) for r in rows]

    async def get_adjuntos_levantamiento(self, conn, id_levantamiento: UUID) -> List[dict]:
        """Retorna lista de archivos adjuntos asociados al levantamiento."""
        # Se filtra por metadata->>'id_levantamiento' que es como se guardó en el router
        rows = await conn.fetch("""
            SELECT 
                id_documento, nombre_archivo, url_sharepoint, 
                tipo_contenido, tamano_bytes, fecha_subida AS created_at
            FROM tb_documentos_attachments
            WHERE metadata->>'id_levantamiento' = $1
              AND activo = true
            ORDER BY fecha_subida DESC
        """, str(id_levantamiento))
        return [dict(r) for r in rows]


    # ----------------------------------------------------------
    # POSPONER
    # ----------------------------------------------------------

    async def update_posponer(self, conn, id_levantamiento: UUID, motivo: str, user_id: UUID) -> None:
        """
        Guarda motivo_pospone y cambia estado a 13 (Pospuesto).
        El historial lo registra el service via _registrar_en_historial.
        """
        await conn.execute("""
            UPDATE tb_levantamientos
            SET id_estatus_global    = 13,
                motivo_pospone       = $1,
                updated_at           = now(),
                updated_by_id        = $2
            WHERE id_levantamiento   = $3
        """, motivo, user_id, id_levantamiento)

    # ----------------------------------------------------------
    # REAGENDAR
    # ----------------------------------------------------------

    async def update_reagendar(self, conn, id_levantamiento: UUID, nueva_fecha, user_id: UUID, is_rescheduling: bool = True) -> None:
        """
        Actualiza fecha_visita_programada con la nueva fecha.
        Si is_rescheduling=True, registra fecha_reagenda (now).
        Si es cita inicial (False), mantiene fecha_reagenda (NULL).
        Limpia motivo_pospone y cambia estado a 9 (Agendado).
        """
        await conn.execute("""
            UPDATE tb_levantamientos
            SET id_estatus_global       = 9,
                fecha_visita_programada = $1,
                fecha_reagenda          = CASE WHEN $4::boolean THEN now() ELSE fecha_reagenda END,
                motivo_pospone          = NULL,
                updated_at              = now(),
                updated_by_id           = $2
            WHERE id_levantamiento      = $3
        """, nueva_fecha, user_id, id_levantamiento, is_rescheduling)

    # ----------------------------------------------------------
    # VIATICOS — CRUD
    # ----------------------------------------------------------

    async def get_viaticos(self, conn, id_levantamiento: UUID) -> List[dict]:
        """
        Retorna los viaticos activos del levantamiento con nombre
        del usuario asociado. Orden por fecha de creación.
        """
        rows = await conn.fetch("""
            SELECT
                v.id,
                v.usuario_id,
                u.nombre   AS usuario_nombre,
                v.concepto,
                v.monto,
                v.created_at
            FROM tb_levantamiento_viaticos v
            LEFT JOIN tb_usuarios u ON v.usuario_id = u.id_usuario
            WHERE v.id_levantamiento = $1
            ORDER BY v.created_at ASC
        """, id_levantamiento)

        return [dict(r) for r in rows]

    async def create_viatico(
        self,
        conn,
        id_levantamiento: UUID,
        usuario_id: UUID,
        concepto: str,
        monto: float,
        created_by_id: UUID
    ) -> dict:
        """
        Inserta un viatico y retorna la fila completa con nombre
        del usuario (para que el endpoint pueda devolver el partial
        sin hacer otra consulta).
        """
        row = await conn.fetchrow("""
            WITH nuevo AS (
                INSERT INTO tb_levantamiento_viaticos
                    (id_levantamiento, usuario_id, concepto, monto, created_by_id)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING *
            )
            SELECT
                nuevo.id,
                nuevo.usuario_id,
                u.nombre AS usuario_nombre,
                nuevo.concepto,
                nuevo.monto,
                nuevo.created_at
            FROM nuevo
            LEFT JOIN tb_usuarios u ON nuevo.usuario_id = u.id_usuario
        """, id_levantamiento, usuario_id, concepto, monto, created_by_id)

        return dict(row) if row else None

    async def delete_viatico(self, conn, id_levantamiento: UUID, viatico_id: UUID) -> bool:
        """
        Elimina un viatico. Retorna True si existió y se borró.
        """
        status = await conn.execute("""
            DELETE FROM tb_levantamiento_viaticos
            WHERE id = $1 AND id_levantamiento = $2
        """, viatico_id, id_levantamiento)

        # asyncpg retorna 'DELETE N' como string
        return status == "DELETE 1"

    # ----------------------------------------------------------
    # VIATICOS — USUARIOS disponibles para el select
    # ----------------------------------------------------------

    async def get_usuarios_viaticos(self, conn) -> List[dict]:
        """
        Lista de usuarios activos que pueden ser asignados como
        beneficiarios de un viatico. Mismo patrón que el select
        del modal.
        """
        rows = await conn.fetch("""
            SELECT id_usuario, nombre, email
            FROM tb_usuarios
            WHERE is_active = true
            ORDER BY nombre ASC
        """)
        return [dict(r) for r in rows]

    # ----------------------------------------------------------
    # VIATICOS — CC configurados desde tb_config_emails
    # ----------------------------------------------------------

    async def get_cc_configurados_viaticos(self, conn) -> List[str]:
        """
        Retorna los emails CC configurados para el evento
        SOLICITUD_VIATICOS en tb_config_emails.
        """
        rows = await conn.fetch("""
            SELECT email_to_add
            FROM tb_config_emails
            WHERE modulo        = 'LEVANTAMIENTOS'
              AND trigger_field = 'EVENTO'
              AND trigger_value = 'SOLICITUD_VIATICOS'
              AND type          = 'CC'
            ORDER BY email_to_add
        """)
        return [r['email_to_add'] for r in rows]

    async def get_to_configurados_viaticos(self, conn) -> List[str]:
        """
        Retorna los emails TO configurados para el evento
        SOLICITUD_VIATICOS en tb_config_emails.
        """
        rows = await conn.fetch("""
            SELECT email_to_add
            FROM tb_config_emails
            WHERE modulo        = 'LEVANTAMIENTOS'
              AND trigger_field = 'EVENTO'
              AND trigger_value = 'SOLICITUD_VIATICOS'
              AND type          = 'TO'
            ORDER BY email_to_add
        """)
        return [r['email_to_add'] for r in rows]

    # ----------------------------------------------------------
    # VIATICOS — HISTORIAL de envíos (tabla historico)
    # ----------------------------------------------------------

    async def get_historial_envios(self, conn, id_levantamiento: UUID) -> List[dict]:
        """
        Historial de solicitudes enviadas para un levantamiento.
        Orden: más reciente primero.
        """
        rows = await conn.fetch("""
            SELECT
                id,
                enviado_por_nombre,
                fecha_envio,
                to_destinatarios,
                cc_destinatarios,
                viaticos_snapshot,
                total_monto,
                estatus,
                error_detalle
            FROM tb_levantamiento_viaticos_historico
            WHERE id_levantamiento = $1
            ORDER BY fecha_envio DESC
        """, id_levantamiento)

        return [dict(r) for r in rows]

    async def insert_historial_envio(
        self,
        conn,
        id_levantamiento: UUID,
        enviado_por_id: UUID,
        enviado_por_nombre: str,
        to_destinatarios: List[str],
        cc_destinatarios: List[str],
        viaticos_snapshot: list,
        total_monto: float,
        estatus: str = "enviado",
        error_detalle: Optional[str] = None
    ) -> dict:
        """
        Registra un nuevo envío en el historial con snapshot completo.
        """
        row = await conn.fetchrow("""
            INSERT INTO tb_levantamiento_viaticos_historico (
                id_levantamiento,
                enviado_por_id,
                enviado_por_nombre,
                fecha_envio,
                to_destinatarios,
                cc_destinatarios,
                viaticos_snapshot,
                total_monto,
                estatus,
                error_detalle
            )
            VALUES ($1, $2, $3, now(), $4, $5, $6::jsonb, $7, $8, $9)
            RETURNING *
        """,
            id_levantamiento,
            enviado_por_id,
            enviado_por_nombre,
            to_destinatarios,
            cc_destinatarios,
            json.dumps(viaticos_snapshot),
            total_monto,
            estatus,
            error_detalle
        )

        return dict(row) if row else None

    async def registrar_devolucion_viaticos(
        self,
        conn,
        id_levantamiento: UUID,
        usuario_id: UUID,
        usuario_nombre: str
    ) -> None:
        """
        Registra un evento de devolución en el historial.
        Esto invalida envíos anteriores para efectos de check_viaticos_sent.
        """
        await conn.execute("""
            INSERT INTO tb_levantamiento_viaticos_historico (
                id_levantamiento,
                enviado_por_id,
                enviado_por_nombre,
                fecha_envio,
                to_destinatarios,
                cc_destinatarios,
                viaticos_snapshot,
                total_monto,
                estatus,
                error_detalle
            )
            VALUES ($1, $2, $3, now(), $4, $5, $6::jsonb, $7, $8, $9)
        """,
            id_levantamiento,
            usuario_id,
            usuario_nombre,
            [], # No recipients
            [],
            json.dumps([]), # Empty snapshot
            0.0,
            'devuelto',
            'Viáticos devueltos por posposición'
        )

    async def clear_viaticos_activos(self, conn, id_levantamiento: UUID) -> None:
        """Elimina todos los viáticos activos de un levantamiento."""
        await conn.execute("""
            DELETE FROM tb_levantamiento_viaticos
            WHERE id_levantamiento = $1
        """, id_levantamiento)

    # ----------------------------------------------------------
    # VISTA LISTA — Histórico con tabs activos/terminados
    # ----------------------------------------------------------

    async def get_lista_activos(
        self,
        conn,
        q: Optional[str] = None,
        estado: Optional[int] = None,
        tecnico_id: Optional[str] = None,
        fecha_inicio: Optional[str] = None,
        fecha_fin: Optional[str] = None,
    ) -> List[dict]:
        """
        Lista de levantamientos activos (estados 8, 9, 10, 13) con filtros dinámicos.
        """
        params = []
        conditions = ["l.id_estatus_global IN (8, 9, 10, 13)", "o.email_enviado = true"]

        if estado is not None:
            params.append(estado)
            conditions.append(f"l.id_estatus_global = ${len(params)}")

        if tecnico_id:
            try:
                from uuid import UUID as _UUID
                tid = _UUID(tecnico_id)
                params.append(tid)
                conditions.append(
                    f"(l.tecnico_asignado_id = ${len(params)} OR EXISTS("
                    f"SELECT 1 FROM tb_levantamiento_asignaciones la "
                    f"WHERE la.id_levantamiento = l.id_levantamiento AND la.tecnico_id = ${len(params)}))"
                )
            except ValueError:
                pass

        if fecha_inicio:
            params.append(fecha_inicio)
            conditions.append(f"l.fecha_solicitud >= ${len(params)}::date")

        if fecha_fin:
            params.append(fecha_fin)
            conditions.append(f"l.fecha_solicitud <= ${len(params)}::date")

        where_clause = " AND ".join(conditions)

        base_query = f"""
            SELECT
                l.id_levantamiento,
                l.id_oportunidad,
                l.id_estatus_global,
                l.fecha_solicitud,
                l.fecha_visita_programada,
                o.op_id_estandar,
                o.titulo_proyecto,
                o.nombre_proyecto,
                o.cliente_nombre,
                s.nombre_sitio,
                est.nombre   AS estatus_nombre,
                est.color_hex AS estatus_color,
                COALESCE(techs.nombres, u_tec.nombre) AS tecnico_nombre,
                u_jefe.nombre AS jefe_nombre
            FROM tb_levantamientos l
            INNER JOIN tb_oportunidades o ON l.id_oportunidad = o.id_oportunidad
            LEFT  JOIN tb_sitios_oportunidad s   ON l.id_sitio = s.id_sitio
            LEFT  JOIN tb_usuarios u_tec ON l.tecnico_asignado_id = u_tec.id_usuario
            LEFT  JOIN tb_usuarios u_jefe ON l.jefe_area_id = u_jefe.id_usuario
            LEFT  JOIN tb_cat_estatus_global est ON l.id_estatus_global = est.id
            LEFT  JOIN LATERAL (
                SELECT string_agg(u.nombre, ', ') AS nombres
                FROM tb_levantamiento_asignaciones la
                JOIN tb_usuarios u ON la.tecnico_id = u.id_usuario
                WHERE la.id_levantamiento = l.id_levantamiento
            ) techs ON true
            WHERE {where_clause}
        """

        # Filtro de texto (búsqueda en cliente, proyecto, op_id, sitio)
        if q:
            params.append(f"%{q.strip()}%")
            idx = len(params)
            base_query += f"""
                AND (
                    o.cliente_nombre ILIKE ${idx}
                    OR o.nombre_proyecto ILIKE ${idx}
                    OR o.titulo_proyecto ILIKE ${idx}
                    OR o.op_id_estandar ILIKE ${idx}
                    OR s.nombre_sitio ILIKE ${idx}
                )
            """

        base_query += " ORDER BY l.created_at DESC"

        rows = await conn.fetch(base_query, *params)
        return [dict(r) for r in rows]

    async def get_lista_terminados(
        self,
        conn,
        q: Optional[str] = None,
        estado: Optional[int] = None,
        tecnico_id: Optional[str] = None,
        fecha_inicio: Optional[str] = None,
        fecha_fin: Optional[str] = None,
    ) -> List[dict]:
        """
        Lista de levantamientos terminados (estados 11, 12) con filtros dinámicos.
        """
        params = []
        conditions = ["l.id_estatus_global IN (11, 12)", "o.email_enviado = true"]

        if estado is not None and estado in (11, 12):
            params.append(estado)
            conditions.append(f"l.id_estatus_global = ${len(params)}")

        if tecnico_id:
            try:
                from uuid import UUID as _UUID
                tid = _UUID(tecnico_id)
                params.append(tid)
                conditions.append(
                    f"(l.tecnico_asignado_id = ${len(params)} OR EXISTS("
                    f"SELECT 1 FROM tb_levantamiento_asignaciones la "
                    f"WHERE la.id_levantamiento = l.id_levantamiento AND la.tecnico_id = ${len(params)}))"
                )
            except ValueError:
                pass

        if fecha_inicio:
            params.append(fecha_inicio)
            conditions.append(f"l.fecha_solicitud >= ${len(params)}::date")

        if fecha_fin:
            params.append(fecha_fin)
            conditions.append(f"l.fecha_solicitud <= ${len(params)}::date")

        where_clause = " AND ".join(conditions)

        base_query = f"""
            SELECT
                l.id_levantamiento,
                l.id_oportunidad,
                l.id_estatus_global,
                l.fecha_solicitud,
                l.fecha_visita_programada,
                o.op_id_estandar,
                o.titulo_proyecto,
                o.nombre_proyecto,
                o.cliente_nombre,
                s.nombre_sitio,
                est.nombre   AS estatus_nombre,
                est.color_hex AS estatus_color,
                COALESCE(techs.nombres, u_tec.nombre) AS tecnico_nombre,
                u_jefe.nombre AS jefe_nombre
            FROM tb_levantamientos l
            INNER JOIN tb_oportunidades o ON l.id_oportunidad = o.id_oportunidad
            LEFT  JOIN tb_sitios_oportunidad s   ON l.id_sitio = s.id_sitio
            LEFT  JOIN tb_usuarios u_tec ON l.tecnico_asignado_id = u_tec.id_usuario
            LEFT  JOIN tb_usuarios u_jefe ON l.jefe_area_id = u_jefe.id_usuario
            LEFT  JOIN tb_cat_estatus_global est ON l.id_estatus_global = est.id
            LEFT  JOIN LATERAL (
                SELECT string_agg(u.nombre, ', ') AS nombres
                FROM tb_levantamiento_asignaciones la
                JOIN tb_usuarios u ON la.tecnico_id = u.id_usuario
                WHERE la.id_levantamiento = l.id_levantamiento
            ) techs ON true
            WHERE {where_clause}
        """

        if q:
            params.append(f"%{q.strip()}%")
            idx = len(params)
            base_query += f"""
                AND (
                    o.cliente_nombre ILIKE ${idx}
                    OR o.nombre_proyecto ILIKE ${idx}
                    OR o.titulo_proyecto ILIKE ${idx}
                    OR o.op_id_estandar ILIKE ${idx}
                    OR s.nombre_sitio ILIKE ${idx}
                )
            """

        base_query += " ORDER BY l.updated_at DESC"

        rows = await conn.fetch(base_query, *params)
        return [dict(r) for r in rows]

    async def get_usuarios_tecnicos(self, conn) -> List[dict]:
        """Lista de técnicos para el filtro de la vista lista."""
        rows = await conn.fetch("""
            SELECT DISTINCT u.id_usuario, u.nombre
            FROM tb_usuarios u
            INNER JOIN tb_permisos_modulos pm ON u.id_usuario = pm.usuario_id
            WHERE pm.modulo_slug = 'levantamientos'
              AND u.is_active = true
            ORDER BY u.nombre
        """)
        return [dict(r) for r in rows]

    # ----------------------------------------------------------
    # VISTA GRÁFICAS — 4 queries para charts
    # ----------------------------------------------------------

    async def get_distribucion_estatus(self, conn) -> List[dict]:
        """
        Conteo de levantamientos por estatus para gráfica de dona.
        Incluye todos los estados activos (8-13).
        """
        rows = await conn.fetch("""
            SELECT
                est.nombre     AS estatus,
                est.color_hex  AS color,
                COUNT(*)       AS total
            FROM tb_levantamientos l
            INNER JOIN tb_oportunidades o ON l.id_oportunidad = o.id_oportunidad
            INNER JOIN tb_cat_estatus_global est ON l.id_estatus_global = est.id
            WHERE l.id_estatus_global IN (8, 9, 10, 11, 12, 13)
              AND o.email_enviado = true
            GROUP BY est.id, est.nombre, est.color_hex
            ORDER BY est.id
        """)
        return [dict(r) for r in rows]

    async def get_carga_tecnicos(self, conn) -> List[dict]:
        """
        Conteo de levantamientos activos por técnico asignado para gráfica de barras.
        """
        rows = await conn.fetch("""
            SELECT
                u.nombre   AS tecnico,
                COUNT(*)   AS total
            FROM tb_levantamiento_asignaciones la
            INNER JOIN tb_usuarios u ON la.tecnico_id = u.id_usuario
            INNER JOIN tb_levantamientos l ON la.id_levantamiento = l.id_levantamiento
            INNER JOIN tb_oportunidades o ON l.id_oportunidad = o.id_oportunidad
            WHERE l.id_estatus_global IN (8, 9, 10, 13)
              AND o.email_enviado = true
            GROUP BY u.id_usuario, u.nombre
            ORDER BY total DESC
            LIMIT 15
        """)
        return [dict(r) for r in rows]

    async def get_tendencia_semanal(self, conn) -> List[dict]:
        """
        Tendencia semanal de levantamientos creados vs completados/entregados.
        Últimas 12 semanas.
        """
        rows = await conn.fetch("""
            WITH semanas AS (
                SELECT generate_series(
                    date_trunc('week', NOW() AT TIME ZONE 'America/Mexico_City') - INTERVAL '11 weeks',
                    date_trunc('week', NOW() AT TIME ZONE 'America/Mexico_City'),
                    INTERVAL '1 week'
                ) AS semana
            ),
            creados AS (
                SELECT
                    date_trunc('week', l.created_at AT TIME ZONE 'America/Mexico_City') AS semana,
                    COUNT(*) AS total
                FROM tb_levantamientos l
                INNER JOIN tb_oportunidades o ON l.id_oportunidad = o.id_oportunidad
                WHERE l.created_at >= NOW() - INTERVAL '12 weeks'
                  AND o.email_enviado = true
                GROUP BY 1
            ),
            terminados AS (
                SELECT
                    date_trunc('week', lh.fecha_transicion AT TIME ZONE 'America/Mexico_City') AS semana,
                    COUNT(*) AS total
                FROM tb_levantamientos_historial lh
                INNER JOIN tb_levantamientos l ON lh.id_levantamiento = l.id_levantamiento
                INNER JOIN tb_oportunidades o ON l.id_oportunidad = o.id_oportunidad
                WHERE lh.id_estatus_nuevo IN (11, 12)
                  AND lh.fecha_transicion >= NOW() - INTERVAL '12 weeks'
                  AND o.email_enviado = true
                GROUP BY 1
            )
            SELECT
                to_char(s.semana, 'DD/MM') AS semana_label,
                COALESCE(c.total, 0)       AS creados,
                COALESCE(t.total, 0)       AS terminados
            FROM semanas s
            LEFT JOIN creados   c ON s.semana = c.semana
            LEFT JOIN terminados t ON s.semana = t.semana
            ORDER BY s.semana
        """)
        return [dict(r) for r in rows]

    async def get_tiempos_y_costos(self, conn) -> dict:
        """
        KPIs: tiempo promedio en cada estado y costo promedio de viáticos.
        """
        tiempos = await conn.fetch("""
            SELECT
                est.nombre AS estatus,
                ROUND(AVG(
                    EXTRACT(EPOCH FROM (NOW() - COALESCE(te.ultima_transicion, l.created_at))) / 3600
                )::numeric, 1) AS avg_horas
            FROM tb_levantamientos l
            INNER JOIN tb_oportunidades o ON l.id_oportunidad = o.id_oportunidad
            INNER JOIN tb_cat_estatus_global est ON l.id_estatus_global = est.id
            LEFT JOIN LATERAL (
                SELECT MAX(fecha_transicion) AS ultima_transicion
                FROM tb_levantamientos_historial
                WHERE id_levantamiento = l.id_levantamiento
                  AND id_estatus_nuevo = l.id_estatus_global
            ) te ON true
            WHERE l.id_estatus_global IN (8, 9, 10, 11, 12, 13)
              AND o.email_enviado = true
            GROUP BY est.id, est.nombre
            ORDER BY est.id
        """)

        avg_viaticos = await conn.fetchval("""
            SELECT ROUND(COALESCE(AVG(totales.monto_total), 0)::numeric, 2)
            FROM (
                SELECT id_levantamiento, SUM(monto) AS monto_total
                FROM tb_levantamiento_viaticos
                GROUP BY id_levantamiento
            ) totales
        """)

        total_levantamientos = await conn.fetchval("""
            SELECT COUNT(*) FROM tb_levantamientos l
            INNER JOIN tb_oportunidades o ON l.id_oportunidad = o.id_oportunidad
            WHERE l.id_estatus_global IN (8, 9, 10, 11, 12, 13)
              AND o.email_enviado = true
        """)

        return {
            "tiempos_por_estado": [dict(r) for r in tiempos],
            "avg_viaticos": float(avg_viaticos or 0),
            "total_levantamientos": int(total_levantamientos or 0),
        }


# --------------------------------------------------------------
# Helper de inyección (mismo patrón que get_service en service.py)
# --------------------------------------------------------------
def get_db_service() -> LevantamientosDBService:
    return LevantamientosDBService()
