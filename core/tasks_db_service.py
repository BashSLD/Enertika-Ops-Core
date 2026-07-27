from uuid import UUID


def _jefe_emails_lateral_join(empleado_id_expr: str) -> str:
    """Fragmento SQL compartido: emails de jefes activos + si alguno es director.

    `empleado_id_expr` es siempre un literal de codigo (columna correlacionada,
    ej. "ad.usuario_id"), nunca input de usuario.
    """
    return f"""
            LEFT JOIN LATERAL (
                SELECT
                    ARRAY_AGG(DISTINCT j.email) FILTER (WHERE j.email IS NOT NULL) AS emails,
                    BOOL_OR(LOWER(COALESCE(j.rol_organizacional, '')) = 'director') AS tiene_director
                FROM tb_empleados_jefes ej
                JOIN tb_usuarios j ON j.id_usuario = ej.jefe_id AND j.is_active = true
                WHERE ej.empleado_id = {empleado_id_expr}
            ) jefes ON true
    """


def _he_override_lateral_join(empleado_id_expr: str) -> str:
    """Fragmento SQL compartido: aprobador exclusivo HE (activo) y aprobador de vacaciones activo,
    para resolver destinatarios de recordatorios sin N+1 — ver
    modules.asistencia.service.resolver_destinatarios_he_puro, que consume estas mismas columnas.

    `empleado_id_expr` es siempre un literal de codigo (columna correlacionada), nunca input de usuario.
    """
    return f"""
            LEFT JOIN tb_empleados_datos ed_override ON ed_override.usuario_id = {empleado_id_expr}
            LEFT JOIN tb_usuarios u_override ON u_override.id_usuario = ed_override.id_aprobador_horas_extra
            LEFT JOIN tb_usuarios u_aprobador_vac
                ON u_aprobador_vac.id_usuario = ed_override.id_aprobador_vacaciones
               AND u_aprobador_vac.is_active = true
               AND u_aprobador_vac.email IS NOT NULL
    """


_HE_OVERRIDE_SELECT_COLUMNS = """
                (ed_override.id_aprobador_horas_extra IS NOT NULL) AS tiene_override,
                (CASE WHEN u_override.is_active THEN u_override.email END) AS override_email,
                u_aprobador_vac.email AS aprobador_vac_email"""


# Predicado RH editor/admin activo + ADMIN global con correo. Compartido por
# get_active_rh_contacts (este archivo) y por los fallback CTEs de
# modules.asistencia.db_service (get_datos_resolucion_notificacion_he,
# verificar_fallback_aprobador_he), que lo inlinean via este mismo string
# porque lo necesitan en el mismo round trip que el resto de sus datos.
ACTIVE_RH_CONTACTS_WHERE = """u.is_active = true
              AND u.email IS NOT NULL
              AND (u.rol_sistema = 'ADMIN' OR pm.usuario_id IS NOT NULL)"""


class TasksDBService:
    """Queries SQL puras para tareas periodicas del worker."""

    async def get_default_sender_email(self, conn) -> str | None:
        row = await conn.fetchrow(
            """
            SELECT email_remitente FROM tb_correos_notificaciones
            WHERE departamento = 'DEFAULT' AND activo = true
            LIMIT 1
            """
        )
        return row["email_remitente"] if row else None

    async def get_unassigned_levantamientos_reminders(self, conn) -> list[dict]:
        rows = await conn.fetch(
            """
            SELECT
                l.id_levantamiento,
                l.jefe_area_id,
                l.id_oportunidad,
                l.fecha_solicitud AT TIME ZONE 'America/Mexico_City' AS fecha_solicitud,
                o.op_id_estandar,
                o.nombre_proyecto,
                o.titulo_proyecto,
                o.cliente_nombre,
                u_jefe.nombre AS jefe_nombre,
                u_jefe.email  AS jefe_email,
                s.nombre_sitio,
                s.direccion        AS sitio_direccion,
                s.google_maps_link AS sitio_maps_link,
                o.coordenadas_gps,
                o.google_maps_link AS op_maps_link
            FROM tb_levantamientos l
            INNER JOIN tb_oportunidades o ON l.id_oportunidad = o.id_oportunidad
            INNER JOIN tb_cat_estatus_levantamiento e ON l.id_estatus_global = e.id
            INNER JOIN tb_usuarios u_jefe ON l.jefe_area_id = u_jefe.id_usuario
            INNER JOIN tb_sitios_oportunidad s ON s.id_sitio = l.id_sitio
            WHERE e.codigo = 'pendiente'
              AND l.created_at < NOW() - INTERVAL '24 hours'
              AND o.email_enviado = true
              AND u_jefe.is_active = true
              AND u_jefe.email IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM tb_levantamiento_asignaciones la
                  WHERE la.id_levantamiento = l.id_levantamiento
                    AND la.es_responsable = true
              )
              AND (l.recordatorio_sin_asignar_at IS NULL
                   OR l.recordatorio_sin_asignar_at < NOW() - INTERVAL '24 hours'
                   OR l.recordatorio_sin_asignar_jefe_id IS DISTINCT FROM l.jefe_area_id)
            """
        )
        return [dict(row) for row in rows]

    # Fuera de _RECORDATORIO_COL/mark_recordatorio_enviado: este caso necesita persistir
    # jefe_id ademas del timestamp para detectar cambio de jefe, no solo una columna *_at.
    async def mark_sin_asignar_reminder_sent(self, conn, id_levantamiento, jefe_id) -> None:
        await conn.execute(
            """
            UPDATE tb_levantamientos
            SET recordatorio_sin_asignar_at = NOW(),
                recordatorio_sin_asignar_jefe_id = $2
            WHERE id_levantamiento = $1
            """,
            id_levantamiento,
            jefe_id,
        )

    async def get_levantamientos_recordatorios(self, conn) -> list[dict]:
        rows = await conn.fetch(
            """
            SELECT
                l.id_levantamiento,
                CASE
                    WHEN e.codigo = 'pendiente' THEN 'pendiente_sin_agendar'
                    WHEN e.codigo = 'agendado'  THEN 'agendado_vencido'
                END AS tipo_recordatorio,
                o.op_id_estandar,
                o.nombre_proyecto,
                o.titulo_proyecto,
                o.cliente_nombre,
                l.fecha_visita_programada AT TIME ZONE 'America/Mexico_City' AS fecha_programada,
                u.nombre  AS responsable_nombre,
                u.email   AS responsable_email,
                s.nombre_sitio,
                s.direccion        AS sitio_direccion,
                s.google_maps_link AS sitio_maps_link,
                o.coordenadas_gps,
                o.google_maps_link AS op_maps_link
            FROM tb_levantamientos l
            JOIN tb_oportunidades o ON l.id_oportunidad = o.id_oportunidad
            JOIN tb_cat_estatus_levantamiento e ON l.id_estatus_global = e.id
            JOIN tb_levantamiento_asignaciones la
                ON la.id_levantamiento = l.id_levantamiento AND la.es_responsable = true
            JOIN tb_usuarios u ON la.tecnico_id = u.id_usuario
            JOIN tb_sitios_oportunidad s ON s.id_sitio = l.id_sitio
            WHERE u.email IS NOT NULL
              AND u.is_active = true
              AND o.email_enviado = true
              AND (
                  (e.codigo = 'pendiente'
                   AND l.fecha_visita_programada IS NULL
                   AND l.created_at < NOW() - INTERVAL '24 hours'
                   AND (l.recordatorio_pendiente_at IS NULL
                        OR l.recordatorio_pendiente_at < NOW() - INTERVAL '24 hours'))
                  OR
                  (e.codigo = 'agendado'
                   AND l.fecha_visita_programada < NOW() - INTERVAL '1 day'
                   AND (l.recordatorio_agendado_at IS NULL
                        OR l.recordatorio_agendado_at < NOW() - INTERVAL '24 hours'))
              )
            """
        )
        return [dict(row) for row in rows]

    _RECORDATORIO_COL = {
        "pendiente_sin_agendar": "recordatorio_pendiente_at",
        "agendado_vencido": "recordatorio_agendado_at",
        "en_proceso": "recordatorio_en_proceso_at",
        "completado": "recordatorio_completado_at",
    }

    async def mark_recordatorio_enviado(self, conn, id_levantamiento, tipo: str) -> None:
        col = self._RECORDATORIO_COL[tipo]
        await conn.execute(
            f"UPDATE tb_levantamientos SET {col} = NOW() WHERE id_levantamiento = $1",
            id_levantamiento,
        )

    async def get_levantamientos_en_proceso_reminders(self, conn) -> list[dict]:
        rows = await conn.fetch(
            """
            SELECT
                l.id_levantamiento,
                CASE
                    WHEN l.fecha_visita_programada IS NOT NULL THEN 'fecha_vencida'
                    ELSE 'en_proceso_largo'
                END AS subtipo,
                o.op_id_estandar,
                o.nombre_proyecto,
                o.titulo_proyecto,
                o.cliente_nombre,
                l.fecha_visita_programada AT TIME ZONE 'America/Mexico_City' AS fecha_programada,
                h.fecha_transicion AT TIME ZONE 'America/Mexico_City' AS fecha_inicio_proceso,
                u_ing.nombre AS ingeniero_nombre,
                u_ing.email  AS ingeniero_email,
                u_jefe.nombre AS jefe_nombre,
                u_jefe.email  AS jefe_email,
                s.nombre_sitio,
                s.direccion        AS sitio_direccion,
                s.google_maps_link AS sitio_maps_link,
                o.coordenadas_gps,
                o.google_maps_link AS op_maps_link
            FROM tb_levantamientos l
            JOIN tb_oportunidades o ON l.id_oportunidad = o.id_oportunidad
            JOIN tb_cat_estatus_levantamiento e ON l.id_estatus_global = e.id
            LEFT JOIN LATERAL (
                SELECT fecha_transicion
                FROM tb_levantamientos_historial
                WHERE id_levantamiento = l.id_levantamiento
                  AND id_estatus_nuevo = 3
                ORDER BY fecha_transicion DESC
                LIMIT 1
            ) h ON true
            LEFT JOIN tb_levantamiento_asignaciones la
                ON la.id_levantamiento = l.id_levantamiento AND la.es_responsable = true
            LEFT JOIN tb_usuarios u_ing
                ON la.tecnico_id = u_ing.id_usuario AND u_ing.is_active = true
            LEFT JOIN tb_usuarios u_jefe
                ON l.jefe_area_id = u_jefe.id_usuario AND u_jefe.is_active = true
            JOIN tb_sitios_oportunidad s ON s.id_sitio = l.id_sitio
            WHERE e.codigo = 'en_proceso'
              AND o.email_enviado = true
              AND (
                  (l.fecha_visita_programada IS NOT NULL
                   AND l.fecha_visita_programada < NOW() - INTERVAL '24 hours')
                  OR
                  (l.fecha_visita_programada IS NULL
                   AND h.fecha_transicion IS NOT NULL
                   AND h.fecha_transicion < NOW() - INTERVAL '48 hours')
              )
              AND (l.recordatorio_en_proceso_at IS NULL
                   OR l.recordatorio_en_proceso_at < NOW() - INTERVAL '24 hours')
            """
        )
        return [dict(row) for row in rows]

    async def get_completed_levantamientos_reminders(self, conn) -> list[dict]:
        rows = await conn.fetch(
            """
            SELECT
                l.id_levantamiento,
                o.op_id_estandar,
                o.nombre_proyecto,
                o.titulo_proyecto,
                o.cliente_nombre,
                h.fecha_transicion AT TIME ZONE 'America/Mexico_City' AS fecha_completado,
                u_ing.nombre AS ingeniero_nombre,
                u_ing.email  AS ingeniero_email,
                u_jefe.nombre AS jefe_nombre,
                u_jefe.email  AS jefe_email,
                s.nombre_sitio,
                s.direccion        AS sitio_direccion,
                s.google_maps_link AS sitio_maps_link,
                o.coordenadas_gps,
                o.google_maps_link AS op_maps_link
            FROM tb_levantamientos l
            JOIN tb_oportunidades o ON l.id_oportunidad = o.id_oportunidad
            JOIN tb_cat_estatus_levantamiento e ON l.id_estatus_global = e.id
            LEFT JOIN LATERAL (
                SELECT fecha_transicion
                FROM tb_levantamientos_historial
                WHERE id_levantamiento = l.id_levantamiento
                  AND id_estatus_nuevo = 5
                ORDER BY fecha_transicion DESC
                LIMIT 1
            ) h ON true
            LEFT JOIN tb_levantamiento_asignaciones la
                ON la.id_levantamiento = l.id_levantamiento AND la.es_responsable = true
            LEFT JOIN tb_usuarios u_ing
                ON la.tecnico_id = u_ing.id_usuario AND u_ing.is_active = true
            LEFT JOIN tb_usuarios u_jefe
                ON l.jefe_area_id = u_jefe.id_usuario AND u_jefe.is_active = true
            JOIN tb_sitios_oportunidad s ON s.id_sitio = l.id_sitio
            WHERE e.codigo = 'completado'
              AND o.email_enviado = true
              AND (l.recordatorio_completado_at IS NULL
                   OR l.recordatorio_completado_at < NOW() - INTERVAL '24 hours')
            """
        )
        return [dict(row) for row in rows]

    async def get_op_levantamiento_sin_cerrar_candidatas(self, conn) -> list[dict]:
        """OPs tipo LEVANTAMIENTO en estatus no terminal cuyos levantamientos estan
        TODOS cancelados -- candidatas al recordatorio de cierre manual (ver
        check_op_levantamiento_sin_cerrar_periodically). Debe coincidir EXACTO con
        el filtro de la subpestaña "Cancelados" de Comercial (unico lugar con el
        boton de cierre): si aqui se incluyera "todos terminales + >=1 cancelado"
        (que tambien cubre mezclas como completado+cancelado), el correo llevaria a
        una lista donde la OP no aparece y no hay forma de actuar. El caso
        "todos Completado sin entrega formal" (G-6) se queda bloqueado a proposito
        hasta la entrega manual -- no le corresponde este recordatorio. "Terminal"
        de OP se resuelve igual que QUERY_CHECK_GRUPO_BLOQUEADOR (es_estatus_final=true
        OR nombre='Ganada'), no solo por el flag."""
        rows = await conn.fetch(
            """
            SELECT
                o.id_oportunidad,
                o.op_id_estandar,
                o.nombre_proyecto,
                o.cliente_nombre,
                o.recordatorio_lev_cancelado_at AT TIME ZONE 'America/Mexico_City' AS ultimo_envio,
                COALESCE(u_resp.email, u_creador.email) AS to_email,
                (
                    SELECT MAX(lh.fecha_transicion) AT TIME ZONE 'America/Mexico_City'
                    FROM tb_levantamientos_historial lh
                    JOIN tb_levantamientos l2 ON l2.id_levantamiento = lh.id_levantamiento
                    JOIN tb_cat_estatus_levantamiento cel2 ON cel2.id = lh.id_estatus_nuevo
                    WHERE l2.id_oportunidad = o.id_oportunidad AND cel2.es_estatus_final = true
                ) AS ultima_transicion_terminal,
                ARRAY(
                    SELECT l3.motivo_pospone
                    FROM tb_levantamientos l3
                    JOIN tb_cat_estatus_levantamiento cel3 ON cel3.id = l3.id_estatus_global
                    WHERE l3.id_oportunidad = o.id_oportunidad
                      AND cel3.codigo = 'cancelado'
                      AND l3.motivo_pospone IS NOT NULL
                ) AS motivos_cancelacion
            FROM tb_oportunidades o
            JOIN tb_cat_tipos_solicitud ts ON ts.id = o.id_tipo_solicitud AND ts.codigo_interno = 'LEVANTAMIENTO'
            JOIN tb_usuarios u_creador ON u_creador.id_usuario = o.creado_por_id
            LEFT JOIN tb_usuarios u_resp ON u_resp.id_usuario = o.responsable_comercial_id AND u_resp.is_active = true
            WHERE o.email_enviado = true
              AND o.id_estatus_global NOT IN (
                  SELECT id FROM tb_cat_estatus_oportunidades
                  WHERE es_estatus_final = true OR LOWER(nombre) = 'ganada'
              )
              AND EXISTS (
                  SELECT 1 FROM tb_levantamientos l
                  WHERE l.id_oportunidad = o.id_oportunidad
              )
              AND NOT EXISTS (
                  SELECT 1 FROM tb_levantamientos l
                  JOIN tb_cat_estatus_levantamiento cel ON cel.id = l.id_estatus_global
                  WHERE l.id_oportunidad = o.id_oportunidad AND cel.codigo <> 'cancelado'
              )
            """
        )
        return [dict(row) for row in rows]

    async def get_comercial_admin_manager_emails(self, conn) -> set[str]:
        """CC del recordatorio de cierre: admin de Comercial, o MANAGER global con
        editor/admin en Comercial -- excluyendo ADMIN global (ya recibe TO via
        otros canales). No usa tb_config_emails: esa tabla guarda direcciones
        estaticas y no puede expresar este OR entre rol de sistema y rol de modulo."""
        rows = await conn.fetch(
            """
            SELECT DISTINCT u.email
            FROM tb_usuarios u
            JOIN tb_permisos_modulos pm ON pm.usuario_id = u.id_usuario
            WHERE u.is_active = true
              AND u.email IS NOT NULL
              AND pm.modulo_slug = 'comercial'
              AND (
                  pm.rol_modulo = 'admin'
                  OR (u.rol_sistema = 'MANAGER' AND pm.rol_modulo IN ('editor', 'admin'))
              )
              AND u.rol_sistema <> 'ADMIN'
            """
        )
        return {row["email"] for row in rows}

    async def mark_recordatorio_lev_cancelado_op(self, conn, id_oportunidad: UUID) -> None:
        """Anti-spam propio de tb_oportunidades.recordatorio_lev_cancelado_at --
        NO reusa mark_recordatorio_enviado, que esta hardcodeado a tb_levantamientos."""
        await conn.execute(
            "UPDATE tb_oportunidades SET recordatorio_lev_cancelado_at = NOW() WHERE id_oportunidad = $1",
            id_oportunidad,
        )

    async def get_estatus_ganada_id(self, conn) -> int | None:
        return await conn.fetchval(
            """
            SELECT id
            FROM tb_cat_estatus_oportunidades
            WHERE LOWER(nombre) = 'ganada'
            LIMIT 1
            """
        )

    async def close_completed_opportunity_won_reminders(self, conn, ganada_id: int) -> None:
        await conn.execute(
            """
            UPDATE tb_recordatorios_oportunidad_ganada r
            SET activo = FALSE,
                updated_at = NOW()
            WHERE r.activo = TRUE
              AND EXISTS (
                  SELECT 1
                  FROM tb_sitios_oportunidad s
                  WHERE s.id_oportunidad = r.id_oportunidad
                    AND s.id_estatus_global = $1
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM tb_sitios_oportunidad s
                  WHERE s.id_oportunidad = r.id_oportunidad
                    AND s.id_estatus_global = $1
                    AND NOT EXISTS (
                        SELECT 1
                        FROM tb_proyectos_gate p
                        WHERE p.id_sitio = s.id_sitio
                    )
              )
            """,
            ganada_id,
        )

    async def claim_due_opportunity_won_reminders(self, conn, ganada_id: int) -> list[dict]:
        rows = await conn.fetch(
            """
            WITH candidatos AS (
                SELECT r.id_oportunidad
                FROM tb_recordatorios_oportunidad_ganada r
                JOIN tb_oportunidades o ON o.id_oportunidad = r.id_oportunidad
                WHERE r.activo = TRUE
                  AND r.proximo_recordatorio_at <= NOW()
                  AND o.id_estatus_global = $1
                  AND EXISTS (
                      SELECT 1
                      FROM tb_sitios_oportunidad s
                      WHERE s.id_oportunidad = r.id_oportunidad
                        AND s.id_estatus_global = $1
                  )
                  AND EXISTS (
                      SELECT 1
                      FROM tb_sitios_oportunidad s
                      WHERE s.id_oportunidad = r.id_oportunidad
                        AND s.id_estatus_global = $1
                        AND NOT EXISTS (
                            SELECT 1
                            FROM tb_proyectos_gate p
                            WHERE p.id_sitio = s.id_sitio
                        )
                  )
                ORDER BY r.proximo_recordatorio_at ASC
                LIMIT 25
                FOR UPDATE SKIP LOCKED
            )
            UPDATE tb_recordatorios_oportunidad_ganada r
            SET proximo_recordatorio_at = NOW() + INTERVAL '10 minutes',
                updated_at = NOW()
            FROM candidatos c
            WHERE r.id_oportunidad = c.id_oportunidad
            RETURNING r.id_oportunidad, r.recordatorios_enviados
            """,
            ganada_id,
        )
        return [dict(row) for row in rows]

    async def opportunity_won_has_complete_coverage(
        self,
        conn,
        id_oportunidad: UUID,
        ganada_id: int,
    ) -> bool:
        return await conn.fetchval(
            """
            SELECT NOT EXISTS (
                SELECT 1
                FROM tb_sitios_oportunidad s
                WHERE s.id_oportunidad = $1
                  AND s.id_estatus_global = $2
                  AND NOT EXISTS (
                      SELECT 1
                      FROM tb_proyectos_gate p
                      WHERE p.id_sitio = s.id_sitio
                  )
            )
            """,
            id_oportunidad,
            ganada_id,
        )

    async def deactivate_opportunity_won_reminder(self, conn, id_oportunidad: UUID) -> None:
        await conn.execute(
            """
            UPDATE tb_recordatorios_oportunidad_ganada
            SET activo = FALSE,
                updated_at = NOW()
            WHERE id_oportunidad = $1
            """,
            id_oportunidad,
        )

    async def mark_opportunity_won_reminder_sent(
        self,
        conn,
        id_oportunidad: UUID,
        reminder_number: int,
        include_director: bool,
    ) -> None:
        await conn.execute(
            """
            UPDATE tb_recordatorios_oportunidad_ganada
            SET recordatorios_enviados = recordatorios_enviados + 1,
                ultimo_recordatorio_at = NOW(),
                proximo_recordatorio_at = NOW() + INTERVAL '48 hours',
                updated_at = NOW()
            WHERE id_oportunidad = $1
            """,
            id_oportunidad,
        )
        await conn.execute(
            """
            UPDATE tb_oportunidades
            SET notificacion_ganada_at = NOW() AT TIME ZONE 'America/Mexico_City'
            WHERE id_oportunidad = $1
            """,
            id_oportunidad,
        )
        await self.log_opportunity_won_reminder(
            conn,
            id_oportunidad,
            reminder_number,
            include_director,
            "ENVIADO",
        )

    async def mark_opportunity_won_reminder_not_sent(
        self,
        conn,
        id_oportunidad: UUID,
        reminder_number: int,
        include_director: bool,
    ) -> None:
        await conn.execute(
            """
            UPDATE tb_recordatorios_oportunidad_ganada
            SET proximo_recordatorio_at = NOW() + INTERVAL '48 hours',
                updated_at = NOW()
            WHERE id_oportunidad = $1
            """,
            id_oportunidad,
        )
        await self.log_opportunity_won_reminder(
            conn,
            id_oportunidad,
            reminder_number,
            include_director,
            "NO_ENVIADO",
            "No se enviaron destinatarios o fallo de envio",
        )

    async def log_opportunity_won_reminder(
        self,
        conn,
        id_oportunidad: UUID,
        reminder_number: int,
        include_director: bool,
        status: str,
        error_message: str | None = None,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO tb_recordatorios_oportunidad_ganada_log (
                id_oportunidad,
                numero_recordatorio,
                incluye_director,
                status,
                error_message,
                created_at
            ) VALUES ($1, $2, $3, $4, $5, NOW())
            """,
            id_oportunidad,
            reminder_number,
            include_director,
            status,
            error_message,
        )

    async def get_sat_inbox_cleanup_urls(self, conn) -> list[dict]:
        rows = await conn.fetch(
            """
            SELECT id, sharepoint_url FROM tb_sat_inbox
            WHERE estado IN ('matcheado', 'descartado')
              AND updated_at < NOW() - INTERVAL '30 days'
              AND sharepoint_url != ''
            """
        )
        return [dict(row) for row in rows]

    async def delete_sat_inbox_resolved_old(self, conn) -> str:
        return await conn.execute(
            """
            DELETE FROM tb_sat_inbox
            WHERE estado IN ('matcheado', 'descartado')
              AND updated_at < NOW() - INTERVAL '30 days'
            """
        )

    async def delete_sat_inbox_pending_old(self, conn) -> str:
        return await conn.execute(
            """
            DELETE FROM tb_sat_inbox
            WHERE estado = 'pendiente'
              AND created_at < NOW() - INTERVAL '90 days'
            """
        )

    async def delete_sat_orphan_jobs_old(self, conn) -> None:
        await conn.execute(
            """
            DELETE FROM tb_sat_jobs j
            WHERE j.created_at < NOW() - INTERVAL '90 days'
              AND NOT EXISTS (
                SELECT 1 FROM tb_sat_inbox i
                WHERE i.job_id = j.id AND i.estado = 'pendiente'
              )
            """
        )

    async def get_pending_absence_approval_reminders(self, conn, hoy) -> list[dict]:
        rows = await conn.fetch(
            """
            SELECT
                sa.id,
                sa.fecha_inicio,
                sa.fecha_fin,
                sa.dias_solicitados,
                sa.fecha_presentarse,
                sa.observaciones,
                sa.hora_llegada,
                sa.hora_salida,
                ta.nombre AS tipo_nombre,
                ta.abreviatura AS tipo_abreviatura,
                u.nombre AS solicitante_nombre,
                u.email AS solicitante_email,
                CASE
                    WHEN u_ap.email IS NOT NULL THEN ARRAY[u_ap.email::text]::text[]
                    ELSE COALESCE(jefes.emails, ARRAY[]::text[])
                END AS responsable_emails
            FROM tb_solicitudes_ausencia sa
            JOIN tb_cat_tipos_ausencia ta ON ta.id = sa.tipo_ausencia_id
            JOIN tb_usuarios u ON u.id_usuario = sa.usuario_id
            LEFT JOIN tb_empleados_datos ed ON ed.usuario_id = sa.usuario_id
            LEFT JOIN tb_usuarios u_ap
                ON u_ap.id_usuario = ed.id_aprobador_vacaciones AND u_ap.is_active = true
            LEFT JOIN LATERAL (
                SELECT ARRAY_AGG(j.email::text ORDER BY j.nombre)::text[] AS emails
                FROM (
                    SELECT DISTINCT u_jefe.email, u_jefe.nombre
                    FROM tb_empleados_jefes ej
                    JOIN tb_usuarios u_jefe
                        ON u_jefe.id_usuario = ej.jefe_id
                       AND u_jefe.is_active = true
                       AND u_jefe.email IS NOT NULL
                    WHERE ej.empleado_id = sa.usuario_id
                ) j
            ) jefes ON true
            WHERE sa.estado = 'pendiente'
              AND sa.firma_solicitante_pendiente = false
              AND sa.fecha_inicio > $1
            ORDER BY sa.fecha_inicio, sa.fecha_solicitud
            """,
            hoy,
        )
        return [dict(row) for row in rows]

    async def get_vacation_days_catalog(self, conn) -> list[dict]:
        rows = await conn.fetch(
            """
            SELECT antiguedad_anios, antiguedad_anios_fin, dias_lft, dias_enertika
            FROM tb_cat_dias_vacaciones
            ORDER BY antiguedad_anios
            """
        )
        return [dict(row) for row in rows]

    async def get_active_employees_with_vacation_data(self, conn) -> list[dict]:
        rows = await conn.fetch(
            """
            SELECT u.id_usuario, u.nombre, u.email, ed.fecha_contratacion,
                   COALESCE(ed.dias_vacaciones_ajuste, 0) AS ajuste
            FROM tb_empleados_datos ed
            JOIN tb_usuarios u ON u.id_usuario = ed.usuario_id
            WHERE ed.fecha_contratacion IS NOT NULL AND u.is_active = true
            """
        )
        return [dict(row) for row in rows]

    async def get_overdue_absence_requests(self, conn, hoy) -> list[dict]:
        rows = await conn.fetch(
            """
            SELECT
                sa.id,
                sa.fecha_inicio,
                sa.fecha_fin,
                ta.nombre AS tipo_nombre,
                u.nombre AS solicitante_nombre,
                COALESCE(u_ap.id_usuario, u_jefe.id_usuario) AS aprobador_id,
                COALESCE(u_ap.email, u_jefe.email) AS aprobador_email
            FROM tb_solicitudes_ausencia sa
            JOIN tb_cat_tipos_ausencia ta ON ta.id = sa.tipo_ausencia_id
            JOIN tb_usuarios u ON u.id_usuario = sa.usuario_id
            LEFT JOIN tb_empleados_datos ed ON ed.usuario_id = sa.usuario_id
            LEFT JOIN tb_usuarios u_ap
                ON u_ap.id_usuario = ed.id_aprobador_vacaciones AND u_ap.is_active = true
            LEFT JOIN LATERAL (
                SELECT jefe_id FROM tb_empleados_jefes
                WHERE empleado_id = sa.usuario_id LIMIT 1
            ) ej ON true
            LEFT JOIN tb_usuarios u_jefe
                ON u_jefe.id_usuario = ej.jefe_id AND u_jefe.is_active = true
            WHERE sa.estado = 'pendiente'
              AND sa.firma_solicitante_pendiente = false
              AND sa.fecha_inicio <= $1
            """,
            hoy,
        )
        return [dict(row) for row in rows]

    async def get_active_rh_contacts(self, conn) -> list[dict]:
        rows = await conn.fetch(
            f"""
            SELECT DISTINCT u.id_usuario, u.email
            FROM tb_usuarios u
            LEFT JOIN tb_permisos_modulos pm
                ON pm.usuario_id = u.id_usuario
               AND pm.modulo_slug = 'rrhh'
               AND pm.rol_modulo IN ('editor', 'admin')
            WHERE {ACTIVE_RH_CONTACTS_WHERE}
            """
        )
        return [dict(row) for row in rows]

    async def get_horas_extra_recordatorios_pendientes(
        self,
        conn,
        *,
        primer_delay_horas: int,
        intervalo_horas: int,
        max_recordatorios: int,
        limit: int = 50,
    ) -> list[dict]:
        rows = await conn.fetch(
            f"""
            SELECT
                ad.id,
                ad.usuario_id,
                ad.fecha_laboral,
                ad.minutos_extra,
                ad.motivo_solicitud,
                ad.horas_extra_recordatorios_enviados,
                u.nombre AS empleado_nombre,
                u.email AS empleado_email,
                COALESCE(jefes.emails, ARRAY[]::text[]) AS jefe_emails,
                COALESCE(jefes.tiene_director, false) AS tiene_director,
                {_HE_OVERRIDE_SELECT_COLUMNS}
            FROM tb_asistencia_diaria ad
            JOIN tb_usuarios u ON u.id_usuario = ad.usuario_id
            {_jefe_emails_lateral_join("ad.usuario_id")}
            {_he_override_lateral_join("ad.usuario_id")}
            WHERE ad.horas_extra_estado = 'solicitado'
              AND ad.minutos_extra > 0
              AND COALESCE(ad.horas_extra_recordatorios_enviados, 0) < $3
              AND (
                  (
                      COALESCE(ad.horas_extra_recordatorios_enviados, 0) = 0
                      AND ad.horas_extra_solicitada_at IS NOT NULL
                      AND ad.horas_extra_solicitada_at <= now() - ($1::int * INTERVAL '1 hour')
                  )
                  OR
                  (
                      COALESCE(ad.horas_extra_recordatorios_enviados, 0) > 0
                      AND ad.horas_extra_ultimo_recordatorio_at IS NOT NULL
                      AND ad.horas_extra_ultimo_recordatorio_at <= now() - ($2::int * INTERVAL '1 hour')
                  )
              )
            ORDER BY COALESCE(ad.horas_extra_ultimo_recordatorio_at, ad.horas_extra_solicitada_at),
                     ad.fecha_laboral,
                     u.nombre
            LIMIT $4
            """,
            primer_delay_horas,
            intervalo_horas,
            max_recordatorios,
            limit,
        )
        return [dict(row) for row in rows]

    async def mark_horas_extra_recordatorio_enviado(self, conn, asistencia_id: UUID) -> None:
        await conn.execute(
            """
            UPDATE tb_asistencia_diaria
            SET horas_extra_ultimo_recordatorio_at = now(),
                horas_extra_recordatorios_enviados = COALESCE(horas_extra_recordatorios_enviados, 0) + 1
            WHERE id = $1
              AND horas_extra_estado = 'solicitado'
            """,
            asistencia_id,
        )

    async def get_horas_extra_resumen_rh_pendiente(
        self,
        conn,
        *,
        max_recordatorios: int,
        intervalo_dias: int,
        limit: int = 100,
    ) -> list[dict]:
        rows = await conn.fetch(
            """
            SELECT
                ad.id,
                ad.usuario_id,
                ad.fecha_laboral,
                ad.minutos_extra,
                ad.motivo_solicitud,
                ad.horas_extra_recordatorios_enviados,
                ad.horas_extra_ultimo_recordatorio_at,
                u.nombre AS empleado_nombre,
                u.email AS empleado_email
            FROM tb_asistencia_diaria ad
            JOIN tb_usuarios u ON u.id_usuario = ad.usuario_id
            WHERE ad.horas_extra_estado = 'solicitado'
              AND ad.minutos_extra > 0
              AND COALESCE(ad.horas_extra_recordatorios_enviados, 0) >= $1
              AND ad.horas_extra_ultimo_recordatorio_at IS NOT NULL
              AND ad.horas_extra_ultimo_recordatorio_at <= now() - ($2::int * INTERVAL '1 day')
              AND (
                  ad.horas_extra_resumen_rh_at IS NULL
                  OR ad.horas_extra_resumen_rh_at <= now() - ($2::int * INTERVAL '1 day')
              )
            ORDER BY ad.horas_extra_ultimo_recordatorio_at, ad.fecha_laboral, u.nombre
            LIMIT $3
            """,
            max_recordatorios,
            intervalo_dias,
            limit,
        )
        return [dict(row) for row in rows]

    async def mark_horas_extra_resumen_rh_enviado(self, conn, asistencia_ids: list[UUID]) -> None:
        if not asistencia_ids:
            return
        await conn.execute(
            """
            UPDATE tb_asistencia_diaria
            SET horas_extra_resumen_rh_at = now()
            WHERE id = ANY($1::uuid[])
              AND horas_extra_estado = 'solicitado'
            """,
            asistencia_ids,
        )

    async def get_he_compensatorio_recordatorios_pendientes(
        self,
        conn,
        *,
        primer_delay_horas: int,
        intervalo_horas: int,
        max_recordatorios: int,
        limit: int = 50,
    ) -> list[dict]:
        rows = await conn.fetch(
            f"""
            SELECT
                s.id,
                s.usuario_id,
                s.fecha_descanso,
                s.minutos_solicitados,
                s.motivo,
                s.recordatorios_enviados,
                u.nombre AS empleado_nombre,
                u.email AS empleado_email,
                COALESCE(jefes.emails, ARRAY[]::text[]) AS jefe_emails,
                COALESCE(jefes.tiene_director, false) AS tiene_director,
                {_HE_OVERRIDE_SELECT_COLUMNS}
            FROM tb_he_solicitudes_compensatorio s
            JOIN tb_usuarios u ON u.id_usuario = s.usuario_id
            {_jefe_emails_lateral_join("s.usuario_id")}
            {_he_override_lateral_join("s.usuario_id")}
            WHERE s.estatus = 'pendiente'
              AND COALESCE(s.recordatorios_enviados, 0) < $3
              AND (
                  (
                      COALESCE(s.recordatorios_enviados, 0) = 0
                      AND s.fecha_solicitud <= now() - ($1::int * INTERVAL '1 hour')
                  )
                  OR
                  (
                      COALESCE(s.recordatorios_enviados, 0) > 0
                      AND s.ultimo_recordatorio_at IS NOT NULL
                      AND s.ultimo_recordatorio_at <= now() - ($2::int * INTERVAL '1 hour')
                  )
              )
            ORDER BY COALESCE(s.ultimo_recordatorio_at, s.fecha_solicitud),
                     s.fecha_descanso,
                     u.nombre
            LIMIT $4
            """,
            primer_delay_horas,
            intervalo_horas,
            max_recordatorios,
            limit,
        )
        return [dict(row) for row in rows]

    async def mark_he_compensatorio_recordatorio_enviado(self, conn, solicitud_id: UUID) -> None:
        await conn.execute(
            """
            UPDATE tb_he_solicitudes_compensatorio
            SET ultimo_recordatorio_at = now(),
                recordatorios_enviados = COALESCE(recordatorios_enviados, 0) + 1,
                updated_at = now()
            WHERE id = $1
              AND estatus = 'pendiente'
            """,
            solicitud_id,
        )

    async def get_he_compensatorio_resumen_rh_pendiente(
        self,
        conn,
        *,
        max_recordatorios: int,
        intervalo_dias: int,
        limit: int = 100,
    ) -> list[dict]:
        rows = await conn.fetch(
            """
            SELECT
                s.id,
                s.usuario_id,
                s.fecha_descanso,
                s.minutos_solicitados,
                s.motivo,
                s.recordatorios_enviados,
                s.ultimo_recordatorio_at,
                u.nombre AS empleado_nombre,
                u.email AS empleado_email
            FROM tb_he_solicitudes_compensatorio s
            JOIN tb_usuarios u ON u.id_usuario = s.usuario_id
            WHERE s.estatus = 'pendiente'
              AND COALESCE(s.recordatorios_enviados, 0) >= $1
              AND s.ultimo_recordatorio_at IS NOT NULL
              AND s.ultimo_recordatorio_at <= now() - ($2::int * INTERVAL '1 day')
              AND (
                  s.resumen_rh_at IS NULL
                  OR s.resumen_rh_at <= now() - ($2::int * INTERVAL '1 day')
              )
            ORDER BY s.ultimo_recordatorio_at, s.fecha_descanso, u.nombre
            LIMIT $3
            """,
            max_recordatorios,
            intervalo_dias,
            limit,
        )
        return [dict(row) for row in rows]

    async def mark_he_compensatorio_resumen_rh_enviado(self, conn, solicitud_ids: list[UUID]) -> None:
        if not solicitud_ids:
            return
        await conn.execute(
            """
            UPDATE tb_he_solicitudes_compensatorio
            SET resumen_rh_at = now(),
                updated_at = now()
            WHERE id = ANY($1::uuid[])
              AND estatus = 'pendiente'
            """,
            solicitud_ids,
        )


def get_tasks_db_service() -> TasksDBService:
    return TasksDBService()
