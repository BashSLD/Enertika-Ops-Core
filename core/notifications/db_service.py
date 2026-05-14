from typing import List, Optional
from uuid import UUID


class NotificationsDBService:
    """Queries SQL puras para notificaciones."""

    async def get_user_id_by_email(self, conn, email: str) -> Optional[UUID]:
        return await conn.fetchval(
            "SELECT id_usuario FROM tb_usuarios WHERE email = $1",
            email,
        )

    async def get_levantamiento_id_by_oportunidad(
        self,
        conn,
        oportunidad_id: UUID,
    ) -> Optional[UUID]:
        return await conn.fetchval(
            """
            SELECT id_levantamiento
            FROM tb_levantamientos
            WHERE id_oportunidad = $1
            LIMIT 1
            """,
            oportunidad_id,
        )

    async def get_pending_notifications(
        self,
        conn,
        usuario_id: UUID,
        limit: int,
    ) -> List[dict]:
        rows = await conn.fetch(
            """
            SELECT id, tipo, titulo, mensaje, id_oportunidad, created_at
            FROM tb_notificaciones
            WHERE usuario_id = $1 AND leida = false
            ORDER BY created_at DESC
            LIMIT $2
            """,
            usuario_id,
            limit,
        )
        return [dict(row) for row in rows]

    async def list_unread_notifications(
        self,
        conn,
        usuario_id: UUID,
        limit: int,
    ) -> List[dict]:
        rows = await conn.fetch(
            """
            SELECT id, tipo, titulo, mensaje, id_oportunidad, leida, created_at
            FROM tb_notificaciones
            WHERE usuario_id = $1 AND leida = false
            ORDER BY created_at DESC
            LIMIT $2
            """,
            usuario_id,
            limit,
        )
        return [dict(row) for row in rows]

    async def get_unread_count(self, conn, usuario_id: UUID) -> int:
        return await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM tb_notificaciones
            WHERE usuario_id = $1 AND leida = false
            """,
            usuario_id,
        ) or 0

    async def mark_as_read(self, conn, notification_id: UUID, usuario_id: UUID) -> None:
        await conn.execute(
            """
            UPDATE tb_notificaciones
            SET leida = true
            WHERE id = $1 AND usuario_id = $2
            """,
            notification_id,
            usuario_id,
        )

    async def delete_notification(
        self,
        conn,
        notification_id: UUID,
        usuario_id: UUID,
    ) -> int:
        result = await conn.execute(
            """
            DELETE FROM tb_notificaciones
            WHERE id = $1 AND usuario_id = $2
            """,
            notification_id,
            usuario_id,
        )
        return int(result.split()[-1])

    async def mark_all_read(self, conn, usuario_id: UUID) -> int:
        result = await conn.execute(
            """
            UPDATE tb_notificaciones
            SET leida = true
            WHERE usuario_id = $1 AND leida = false
            """,
            usuario_id,
        )
        return int(result.split()[-1])

    async def delete_all_notifications(self, conn, usuario_id: UUID) -> int:
        result = await conn.execute(
            "DELETE FROM tb_notificaciones WHERE usuario_id = $1",
            usuario_id,
        )
        return int(result.split()[-1])

    async def create_notification(
        self,
        conn,
        usuario_id: UUID,
        tipo: str,
        titulo: str,
        mensaje: str,
        id_oportunidad: Optional[UUID],
    ) -> dict:
        row = await conn.fetchrow(
            """
            INSERT INTO tb_notificaciones (usuario_id, tipo, titulo, mensaje, id_oportunidad)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id, created_at
            """,
            usuario_id,
            tipo,
            titulo,
            mensaje,
            id_oportunidad,
        )
        return dict(row)

    async def notify_channel(self, conn, channel: str, payload: str) -> None:
        await conn.execute("SELECT pg_notify($1, $2)", channel, payload)


def get_notifications_db_service() -> NotificationsDBService:
    return NotificationsDBService()

