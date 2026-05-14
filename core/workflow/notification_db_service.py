from typing import Dict, List, Optional, Set
from uuid import UUID


class WorkflowNotificationDBService:
    """Queries SQL puras para notificaciones de workflow."""

    async def get_active_user_contact(self, conn, user_id: UUID) -> Optional[dict]:
        row = await conn.fetchrow(
            "SELECT nombre, email FROM tb_usuarios WHERE id_usuario = $1 AND is_active = TRUE",
            user_id,
        )
        return dict(row) if row else None

    async def get_status_names(self, conn, status_ids: List[int]) -> Dict[int, str]:
        rows = await conn.fetch(
            """
            SELECT id, nombre FROM tb_cat_estatus_oportunidades WHERE id = ANY($1::int[])
            UNION ALL
            SELECT id, nombre FROM tb_cat_estatus_levantamiento WHERE id = ANY($1::int[])
            """,
            status_ids,
        )
        return {row["id"]: row["nombre"] for row in rows}

    async def get_cancellation_recipients(self, conn, id_levantamiento: UUID) -> List[dict]:
        rows = await conn.fetch(
            """
            SELECT u.nombre, u.email, 'jefe' AS rol
            FROM tb_levantamientos l
            JOIN tb_usuarios u ON l.jefe_area_id = u.id_usuario
            WHERE l.id_levantamiento = $1 AND l.jefe_area_id IS NOT NULL
            UNION
            SELECT u.nombre, u.email, 'solicitante' AS rol
            FROM tb_levantamientos l
            JOIN tb_usuarios u ON l.solicitado_por_id = u.id_usuario
            WHERE l.id_levantamiento = $1
            """,
            id_levantamiento,
        )
        return [dict(row) for row in rows]

    async def get_reassignment_recipients(self, conn, id_levantamiento: UUID) -> List[dict]:
        rows = []

        asignador = await conn.fetchrow(
            """
            SELECT u.nombre, u.email
            FROM tb_levantamiento_asignaciones la
            JOIN tb_usuarios u ON la.asignado_por_id = u.id_usuario
            WHERE la.id_levantamiento = $1 AND la.es_responsable = true
            LIMIT 1
            """,
            id_levantamiento,
        )
        if asignador:
            rows.append(dict(asignador))

        solicitante = await conn.fetchrow(
            """
            SELECT u.nombre, u.email
            FROM tb_levantamientos l
            JOIN tb_usuarios u ON l.solicitado_por_id = u.id_usuario
            WHERE l.id_levantamiento = $1
            """,
            id_levantamiento,
        )
        if solicitante:
            rows.append(dict(solicitante))

        return rows

    async def schedule_opportunity_won_reminders(
        self,
        conn,
        id_oportunidad: UUID,
        reminder_hours: int,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO tb_recordatorios_oportunidad_ganada (
                id_oportunidad,
                recordatorios_enviados,
                ultimo_recordatorio_at,
                proximo_recordatorio_at,
                activo,
                created_at,
                updated_at
            )
            VALUES (
                $1,
                0,
                NULL,
                NOW() + ($2 * INTERVAL '1 hour'),
                TRUE,
                NOW(),
                NOW()
            )
            ON CONFLICT (id_oportunidad) DO UPDATE
            SET activo = TRUE,
                proximo_recordatorio_at = NOW() + ($2 * INTERVAL '1 hour'),
                updated_at = NOW()
            """,
            id_oportunidad,
            reminder_hours,
        )

    async def get_opportunity(self, conn, id_oportunidad: UUID) -> dict:
        row = await conn.fetchrow(
            """
            SELECT
                id_oportunidad,
                op_id_estandar,
                nombre_proyecto,
                cliente_nombre,
                creado_por_id,
                responsable_simulacion_id,
                id_estatus_global
            FROM tb_oportunidades
            WHERE id_oportunidad = $1
            """,
            id_oportunidad,
        )
        return dict(row) if row else {}

    async def get_emails_by_organizational_roles(self, conn, roles: List[str]) -> Set[str]:
        rows = await conn.fetch(
            """
            SELECT email
            FROM tb_usuarios
            WHERE rol_organizacional = ANY($1::varchar[])
              AND is_active = TRUE
              AND email IS NOT NULL
            """,
            roles,
        )
        return {row["email"].strip().lower() for row in rows if row["email"]}

    async def get_active_user_email(self, conn, user_id: UUID) -> Optional[str]:
        return await conn.fetchval(
            "SELECT email FROM tb_usuarios WHERE id_usuario = $1 AND is_active = TRUE",
            user_id,
        )

    async def get_active_user_emails_by_ids(
        self,
        conn,
        user_ids: List[UUID],
    ) -> Dict[str, str]:
        rows = await conn.fetch(
            """
            SELECT id_usuario, email
            FROM tb_usuarios
            WHERE id_usuario = ANY($1::uuid[]) AND is_active = TRUE
            """,
            user_ids,
        )
        return {str(row["id_usuario"]): row["email"] for row in rows if row["email"]}

    async def get_emails_for_event(
        self,
        conn,
        trigger_value: str,
        type_filter: str,
    ) -> Set[str]:
        rows = await conn.fetch(
            """
            SELECT email_to_add
            FROM tb_config_emails
            WHERE trigger_field = 'EVENTO'
              AND trigger_value = $1
              AND type = $2
            """,
            trigger_value,
            type_filter,
        )
        return {row["email_to_add"] for row in rows if row["email_to_add"]}

    async def get_notification_sender(
        self,
        conn,
        departamento: str,
    ) -> Optional[dict]:
        row = await conn.fetchrow(
            """
            SELECT email_remitente, nombre_remitente
            FROM tb_correos_notificaciones
            WHERE departamento = $1 AND activo = true
            LIMIT 1
            """,
            departamento.upper(),
        )
        return dict(row) if row else None

    async def get_default_notification_sender(self, conn) -> Optional[dict]:
        row = await conn.fetchrow(
            """
            SELECT email_remitente, nombre_remitente
            FROM tb_correos_notificaciones
            WHERE departamento = 'DEFAULT' AND activo = true
            LIMIT 1
            """
        )
        return dict(row) if row else None

    async def get_user_id_by_email(self, conn, email: str) -> Optional[UUID]:
        row = await conn.fetchrow(
            "SELECT id_usuario FROM tb_usuarios WHERE email = $1",
            email,
        )
        return row["id_usuario"] if row else None

    async def get_rh_emails(self, conn) -> Set[str]:
        rows = await conn.fetch(
            """
            SELECT DISTINCT u.email
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
        return {row["email"] for row in rows}

    async def get_user_name_by_email(self, conn, email: str) -> Optional[str]:
        return await conn.fetchval(
            "SELECT nombre FROM tb_usuarios WHERE email = $1",
            email,
        )


def get_workflow_notification_db_service() -> WorkflowNotificationDBService:
    return WorkflowNotificationDBService()
