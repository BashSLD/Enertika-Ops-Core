from uuid import UUID


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
            """
        )
        return [dict(row) for row in rows]

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
                   AND l.created_at < NOW() - INTERVAL '24 hours')
                  OR
                  (e.codigo = 'agendado'
                   AND l.fecha_visita_programada < NOW() - INTERVAL '1 day')
              )
            """
        )
        return [dict(row) for row in rows]

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
            """
        )
        return [dict(row) for row in rows]

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
                ta.nombre AS tipo_nombre,
                ta.abreviatura AS tipo_abreviatura,
                u.nombre AS solicitante_nombre,
                u.email AS solicitante_email,
                ARRAY_REMOVE(ARRAY[u_ap.email::text], NULL)::text[] AS aprobador_emails,
                COALESCE(jefes.emails, ARRAY[]::text[]) AS jefe_emails,
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

    async def mark_absence_approver_notified(self, conn, solicitud_id) -> None:
        await conn.execute(
            "UPDATE tb_solicitudes_ausencia SET ultima_notificacion_aprobador = now() WHERE id = $1",
            solicitud_id,
        )

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
            """
            SELECT DISTINCT u.id_usuario, u.email
            FROM tb_usuarios u
            LEFT JOIN tb_permisos_modulos pm
                ON pm.usuario_id = u.id_usuario
               AND pm.modulo_slug = 'rrhh'
               AND pm.rol_modulo IN ('editor', 'admin')
            WHERE u.is_active = true
              AND u.email IS NOT NULL
              AND (u.rol_sistema = 'ADMIN' OR pm.usuario_id IS NOT NULL)
            """
        )
        return [dict(row) for row in rows]


def get_tasks_db_service() -> TasksDBService:
    return TasksDBService()
