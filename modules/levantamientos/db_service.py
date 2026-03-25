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
from core.email_rules import EmailRulesService

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
                l.solicitado_por_id,
                l.fecha_solicitud             AT TIME ZONE 'America/Mexico_City' AS fecha_solicitud,
                l.fecha_visita_programada     AT TIME ZONE 'America/Mexico_City' AS fecha_visita_programada,
                l.fecha_ideal_solicitante     AT TIME ZONE 'America/Mexico_City' AS fecha_ideal_solicitante,
                l.motivo_pospone,
                l.fecha_reagenda              AT TIME ZONE 'America/Mexico_City' AS fecha_reagenda,
                l.created_at                  AT TIME ZONE 'America/Mexico_City' AS created_at,
                l.updated_at                  AT TIME ZONE 'America/Mexico_City' AS updated_at,

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
                est.color_hex  AS estatus_color,
                est.codigo     AS estatus_codigo
            FROM tb_levantamientos l
            INNER JOIN tb_oportunidades      o    ON l.id_oportunidad          = o.id_oportunidad
            LEFT  JOIN tb_sitios_oportunidad s    ON l.id_sitio                = s.id_sitio
            LEFT  JOIN tb_usuarios           u_sol ON l.solicitado_por_id      = u_sol.id_usuario
            LEFT  JOIN tb_usuarios           u_tec ON l.tecnico_asignado_id   = u_tec.id_usuario
            LEFT  JOIN tb_usuarios           u_jefe ON l.jefe_area_id         = u_jefe.id_usuario
            LEFT  JOIN tb_cat_estatus_levantamiento est  ON l.id_estatus_global = est.id
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
    
    async def get_levantamientos_con_viaticos_activos(self, conn, ids: List[UUID]) -> List[dict]:
        """
        Dado un listado de IDs, retorna los que tienen viáticos activos
        (enviados y sin devolución posterior). Incluye referencia legible.
        """
        rows = await conn.fetch("""
            SELECT
                l.id_levantamiento,
                o.op_id_estandar,
                COALESCE(s.nombre_sitio, o.nombre_proyecto) AS nombre_referencia
            FROM tb_levantamientos l
            INNER JOIN tb_oportunidades o ON l.id_oportunidad = o.id_oportunidad
            LEFT  JOIN tb_sitios_oportunidad s ON l.id_sitio = s.id_sitio
            WHERE l.id_levantamiento = ANY($1)
            AND EXISTS (
                SELECT 1 FROM tb_levantamiento_viaticos_historico h
                WHERE h.id_levantamiento = l.id_levantamiento
                AND h.estatus = 'enviado'
                AND h.fecha_envio > COALESCE((
                    SELECT MAX(fecha_envio)
                    FROM tb_levantamiento_viaticos_historico
                    WHERE id_levantamiento = l.id_levantamiento AND estatus = 'devuelto'
                ), '2000-01-01'::timestamp)
            )
        """, ids)
        return [dict(r) for r in rows]

    async def get_op_ids_by_ids(self, conn, ids: List[UUID]) -> dict:
        """Retorna {str(id_levantamiento): op_id_estandar} para los IDs dados."""
        rows = await conn.fetch("""
            SELECT l.id_levantamiento, o.op_id_estandar
            FROM tb_levantamientos l
            INNER JOIN tb_oportunidades o ON l.id_oportunidad = o.id_oportunidad
            WHERE l.id_levantamiento = ANY($1)
        """, ids)
        return {str(r["id_levantamiento"]): r["op_id_estandar"] for r in rows}

    async def revertir_estatus_pendiente(self, conn, id_levantamiento: UUID) -> None:
        """
        Revierte el levantamiento a 'pendiente' al removerlo de una visita.
        Limpia fecha_visita_programada ya que fue asignada por la visita.
        """
        await conn.execute("""
            UPDATE tb_levantamientos
            SET id_estatus_global = (
                SELECT id FROM tb_cat_estatus_levantamiento WHERE codigo = 'pendiente'
            ),
            fecha_visita_programada = NULL,
            updated_at = NOW()
            WHERE id_levantamiento = $1
        """, id_levantamiento)

    async def get_id_by_oportunidad(self, conn, id_oportunidad: UUID) -> Optional[UUID]:
        """Obtiene ID de levantamiento por ID de oportunidad."""
        return await conn.fetchval("""
            SELECT id_levantamiento FROM tb_levantamientos WHERE id_oportunidad = $1 LIMIT 1
        """, id_oportunidad)

    async def update_fecha_ideal_solicitante(self, conn, id_levantamiento: UUID, fecha_ideal) -> None:
        """Actualiza la fecha ideal del solicitante en el levantamiento."""
        await conn.execute("""
            UPDATE tb_levantamientos
               SET fecha_ideal_solicitante = $1,
                   updated_at              = NOW()
             WHERE id_levantamiento = $2
        """, fecha_ideal, id_levantamiento)

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
        """Retorna lista de diccionarios de técnicos asignados, responsable primero."""
        rows = await conn.fetch("""
             SELECT u.id_usuario, u.nombre, u.email, la.es_responsable
             FROM tb_levantamiento_asignaciones la
             JOIN tb_usuarios u ON la.tecnico_id = u.id_usuario
             WHERE la.id_levantamiento = $1
             ORDER BY la.es_responsable DESC, u.nombre ASC
        """, id_levantamiento)
        return [dict(r) for r in rows]

    async def get_responsable_asignado(self, conn, id_levantamiento: UUID) -> Optional[dict]:
        """Retorna {id_usuario, nombre} del técnico marcado como responsable, o None."""
        row = await conn.fetchrow("""
            SELECT u.id_usuario, u.nombre
            FROM tb_levantamiento_asignaciones la
            JOIN tb_usuarios u ON la.tecnico_id = u.id_usuario
            WHERE la.id_levantamiento = $1 AND la.es_responsable = true
            LIMIT 1
        """, id_levantamiento)
        return dict(row) if row else None

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

    async def update_posponer(self, conn, id_levantamiento: UUID, motivo: str, user_id: UUID, estatus_id: int) -> None:
        """
        Guarda motivo_pospone y cambia estado al estatus Pospuesto.
        El historial lo registra el service via _registrar_en_historial.
        """
        await conn.execute("""
            UPDATE tb_levantamientos
            SET id_estatus_global    = $4,
                motivo_pospone       = $1,
                updated_at           = now(),
                updated_by_id        = $2
            WHERE id_levantamiento   = $3
        """, motivo, user_id, id_levantamiento, estatus_id)

    # ----------------------------------------------------------
    # REAGENDAR
    # ----------------------------------------------------------

    async def update_reagendar(self, conn, id_levantamiento: UUID, nueva_fecha, user_id: UUID, estatus_id: int, is_rescheduling: bool = True) -> None:
        """
        Actualiza fecha_visita_programada con la nueva fecha.
        Si is_rescheduling=True, registra fecha_reagenda (now).
        Si es cita inicial (False), mantiene fecha_reagenda (NULL).
        Limpia motivo_pospone y cambia estado al estatus Agendado.
        """
        await conn.execute("""
            UPDATE tb_levantamientos
            SET id_estatus_global       = $5,
                fecha_visita_programada = $1,
                fecha_reagenda          = CASE WHEN $4::boolean THEN now() ELSE fecha_reagenda END,
                motivo_pospone          = NULL,
                updated_at              = now(),
                updated_by_id           = $2
            WHERE id_levantamiento      = $3
        """, nueva_fecha, user_id, id_levantamiento, is_rescheduling, estatus_id)

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

    async def get_usuarios_viaticos(self, conn, id_levantamiento: Optional[UUID] = None) -> List[dict]:
        """
        Lista de usuarios para el selector de viáticos.
        Si se pasa id_levantamiento, filtra a los técnicos asignados al levantamiento
        más el jefe_area_id. Fallback a todos los usuarios activos si no hay asignados.
        """
        if id_levantamiento is not None:
            rows = await conn.fetch("""
                SELECT DISTINCT u.id_usuario, u.nombre, u.email
                FROM tb_usuarios u
                WHERE u.id_usuario IN (
                    SELECT tecnico_id FROM tb_levantamiento_asignaciones WHERE id_levantamiento = $1
                    UNION
                    SELECT jefe_area_id FROM tb_levantamientos
                    WHERE id_levantamiento = $1 AND jefe_area_id IS NOT NULL
                ) AND u.is_active = true
                ORDER BY u.nombre ASC
            """, id_levantamiento)
            if rows:
                return [dict(r) for r in rows]
            # Fallback: sin asignaciones aún → todos los activos
        rows = await conn.fetch("""
            SELECT id_usuario, nombre, email
            FROM tb_usuarios
            WHERE is_active = true
            ORDER BY nombre ASC
        """)
        return [dict(r) for r in rows]

    async def update_responsable(
        self,
        conn,
        id_levantamiento: UUID,
        nuevo_responsable_id: UUID,
        asignado_por_id: UUID
    ) -> None:
        """
        Actualiza el responsable del levantamiento:
        1. Quita es_responsable del anterior.
        2. Upsert del nuevo responsable con es_responsable=true.
        Requiere UNIQUE constraint en (id_levantamiento, tecnico_id).
        """
        await conn.execute("""
            UPDATE tb_levantamiento_asignaciones
            SET es_responsable = false
            WHERE id_levantamiento = $1 AND es_responsable = true
        """, id_levantamiento)

        await conn.execute("""
            INSERT INTO tb_levantamiento_asignaciones
                (id_levantamiento, tecnico_id, asignado_por_id, es_responsable)
            VALUES ($1, $2, $3, true)
            ON CONFLICT (id_levantamiento, tecnico_id)
            DO UPDATE SET es_responsable = true, asignado_por_id = $3
        """, id_levantamiento, nuevo_responsable_id, asignado_por_id)

    # ----------------------------------------------------------
    # VIATICOS — CC configurados desde tb_config_emails
    # ----------------------------------------------------------

    async def get_cc_configurados_viaticos(self, conn) -> List[str]:
        """
        Retorna los emails CC configurados para el evento SOLICITUD_VIATICOS.
        Incluye reglas del módulo LEVANTAMIENTOS y reglas GLOBAL.
        """
        svc = EmailRulesService()
        emails = await svc.get_emails_by_event(conn, 'LEVANTAMIENTOS', 'SOLICITUD_VIATICOS')
        return emails['cc']

    async def get_to_configurados_viaticos(self, conn) -> List[str]:
        """
        Retorna los emails TO configurados para el evento SOLICITUD_VIATICOS.
        Incluye reglas del módulo LEVANTAMIENTOS y reglas GLOBAL.
        """
        svc = EmailRulesService()
        emails = await svc.get_emails_by_event(conn, 'LEVANTAMIENTOS', 'SOLICITUD_VIATICOS')
        return emails['to']

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
                fecha_envio AT TIME ZONE 'America/Mexico_City' AS fecha_envio,
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
        ids_activos: List[int],
        q: Optional[str] = None,
        estado: Optional[int] = None,
        tecnico_id: Optional[str] = None,
        fecha_inicio: Optional[str] = None,
        fecha_fin: Optional[str] = None,
    ) -> List[dict]:
        """
        Lista de levantamientos activos (estados pendiente/agendado/en_proceso/pospuesto) con filtros dinámicos.
        ids_activos: lista de IDs de estatus que se consideran activos (obtenidos vía get_estatus_map).
        """
        params: list = [ids_activos]
        conditions = ["l.id_estatus_global = ANY($1::int[])", "o.email_enviado = true"]

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
                l.fecha_solicitud         AT TIME ZONE 'America/Mexico_City' AS fecha_solicitud,
                l.fecha_visita_programada AT TIME ZONE 'America/Mexico_City' AS fecha_visita_programada,
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
            LEFT  JOIN tb_cat_estatus_levantamiento est ON l.id_estatus_global = est.id
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
        ids_terminados: List[int],
        q: Optional[str] = None,
        estado: Optional[int] = None,
        tecnico_id: Optional[str] = None,
        fecha_inicio: Optional[str] = None,
        fecha_fin: Optional[str] = None,
    ) -> List[dict]:
        """
        Lista de levantamientos terminados (completado/entregado) con filtros dinámicos.
        ids_terminados: lista de IDs de estatus terminales (obtenidos vía get_estatus_map).
        """
        params: list = [ids_terminados]
        conditions = ["l.id_estatus_global = ANY($1::int[])", "o.email_enviado = true"]

        if estado is not None and estado in ids_terminados:
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
                l.fecha_solicitud         AT TIME ZONE 'America/Mexico_City' AS fecha_solicitud,
                l.fecha_visita_programada AT TIME ZONE 'America/Mexico_City' AS fecha_visita_programada,
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
            LEFT  JOIN tb_cat_estatus_levantamiento est ON l.id_estatus_global = est.id
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

    async def get_lista_cancelados(
        self,
        conn,
        id_cancelado: int,
        q: Optional[str] = None,
        tecnico_id: Optional[str] = None,
        fecha_inicio: Optional[str] = None,
        fecha_fin: Optional[str] = None,
    ) -> List[dict]:
        """
        Lista de levantamientos cancelados con filtros dinámicos.
        Incluye motivo_pospone (reutilizado como motivo_cancelacion).
        """
        params: list = [id_cancelado]
        conditions = ["l.id_estatus_global = $1", "o.email_enviado = true"]

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
            conditions.append(f"l.updated_at >= ${len(params)}::date")

        if fecha_fin:
            params.append(fecha_fin)
            conditions.append(f"l.updated_at <= ${len(params)}::date")

        where_clause = " AND ".join(conditions)

        base_query = f"""
            SELECT
                l.id_levantamiento,
                l.id_oportunidad,
                l.id_estatus_global,
                l.fecha_solicitud         AT TIME ZONE 'America/Mexico_City' AS fecha_solicitud,
                l.updated_at              AT TIME ZONE 'America/Mexico_City' AS fecha_cancelacion,
                l.motivo_pospone          AS motivo_cancelacion,
                o.op_id_estandar,
                o.titulo_proyecto,
                o.nombre_proyecto,
                o.cliente_nombre,
                s.nombre_sitio,
                est.nombre   AS estatus_nombre,
                est.color_hex AS estatus_color,
                COALESCE(techs.nombres, u_tec.nombre) AS tecnico_nombre,
                u_jefe.nombre AS jefe_nombre,
                u_sol.nombre  AS solicitado_por_nombre
            FROM tb_levantamientos l
            INNER JOIN tb_oportunidades o ON l.id_oportunidad = o.id_oportunidad
            LEFT  JOIN tb_sitios_oportunidad s   ON l.id_sitio = s.id_sitio
            LEFT  JOIN tb_usuarios u_tec ON l.tecnico_asignado_id = u_tec.id_usuario
            LEFT  JOIN tb_usuarios u_jefe ON l.jefe_area_id = u_jefe.id_usuario
            LEFT  JOIN tb_usuarios u_sol ON l.solicitado_por_id = u_sol.id_usuario
            LEFT  JOIN tb_cat_estatus_levantamiento est ON l.id_estatus_global = est.id
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

    async def get_estatus_map(self, conn) -> dict:
        """Retorna {codigo: id} para todos los estatus activos de levantamientos."""
        rows = await conn.fetch(
            "SELECT id, codigo FROM tb_cat_estatus_levantamiento WHERE activo = TRUE"
        )
        return {r['codigo']: r['id'] for r in rows}

    async def get_estatus_list(self, conn) -> List[dict]:
        """Retorna lista de estatus para el template (filtros, etc.)."""
        rows = await conn.fetch(
            "SELECT id, nombre, codigo, grupo_kanban FROM tb_cat_estatus_levantamiento WHERE activo = TRUE ORDER BY orden_kanban"
        )
        return [dict(r) for r in rows]

    async def get_usuarios_tecnicos(self, conn) -> List[dict]:
        """Lista de técnicos para el filtro de la vista lista."""
        rows = await conn.fetch("""
            SELECT DISTINCT u.id_usuario, u.nombre
            FROM tb_usuarios u
            WHERE u.is_active = true
              AND (
                  u.puede_asignarse_levantamientos = true
                  OR EXISTS (
                      SELECT 1 FROM tb_permisos_modulos pm
                      WHERE pm.usuario_id = u.id_usuario
                        AND pm.modulo_slug = 'levantamientos'
                  )
              )
            ORDER BY u.nombre
        """)
        return [dict(r) for r in rows]

    # ----------------------------------------------------------
    # VISITAS DE CAMPO — indicador en modal viaticos individuales
    # ----------------------------------------------------------

    async def get_visitas_campo_for_lev(self, conn, id_levantamiento: UUID) -> List[dict]:
        """
        Retorna visitas de campo que contienen este levantamiento, con viáticos y prorrateo.
        """
        rows = await conn.fetch("""
            SELECT
                v.id_visita,
                v.nombre,
                v.fecha_inicio AT TIME ZONE 'America/Mexico_City' AS fecha_inicio,
                v.fecha_fin    AT TIME ZONE 'America/Mexico_City' AS fecha_fin,
                (SELECT COALESCE(SUM(monto), 0) FROM tb_visita_campo_viaticos WHERE id_visita = v.id_visita) AS total_viaticos,
                (SELECT COUNT(*) FROM tb_visita_campo_levantamientos WHERE id_visita = v.id_visita) AS num_levantamientos,
                EXISTS(SELECT 1 FROM tb_visita_campo_envios WHERE id_visita = v.id_visita AND estatus = 'enviado') AS enviada
            FROM tb_visita_campo_levantamientos vcl
            JOIN tb_visitas_campo v ON vcl.id_visita = v.id_visita
            WHERE vcl.id_levantamiento = $1
            ORDER BY v.fecha_inicio DESC
        """, id_levantamiento)
        rows_dicts = [dict(r) for r in rows]
        # Calcular prorrateo para este levantamiento en cada visita
        for r in rows_dicts:
            n = r["num_levantamientos"] or 1
            r["monto_prorrateo"] = float(r["total_viaticos"]) / n if r["total_viaticos"] else 0.0
        return rows_dicts

    async def check_visita_tiene_viaticos(self, conn, id_levantamiento: UUID) -> bool:
        """
        Verifica si el levantamiento pertenece a alguna visita de campo
        que tenga viáticos registrados (aunque aún no se haya enviado el correo).
        """
        return await conn.fetchval("""
            SELECT EXISTS(
                SELECT 1
                FROM tb_visita_campo_levantamientos vcl
                JOIN tb_visita_campo_viaticos vcv ON vcl.id_visita = vcv.id_visita
                WHERE vcl.id_levantamiento = $1
            )
        """, id_levantamiento)


# --------------------------------------------------------------
# Helper de inyección (mismo patrón que get_service en service.py)
# --------------------------------------------------------------
def get_db_service() -> LevantamientosDBService:
    return LevantamientosDBService()
