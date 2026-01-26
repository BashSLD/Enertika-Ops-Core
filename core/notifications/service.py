# core/notifications/service.py
"""
Service Layer para notificaciones SSE.
Maneja lógica de negocio: CRUD de notificaciones, gestión de conexiones activas.

Patrón recomendado por GUIA_MAESTRA: Service Layer separado del Router.
"""
from typing import Dict, Optional
from uuid import UUID
from asyncio import Queue
import logging

logger = logging.getLogger("NotificationsService")

# Store de conexiones activas SSE: {usuario_id: Queue}
active_connections: Dict[UUID, Queue] = {}


class NotificationsService:
    """
    Maneja lógica de negocio de notificaciones.
    
    Responsabilidades:
    - CRUD de notificaciones en tb_notificaciones
    - Gestión de conexiones SSE activas
    - Broadcasting de notificaciones a usuarios conectados
    """
    
    async def get_pending_notifications(self, conn, usuario_id: UUID, limit: int = 10):
        """
        Obtiene notificaciones no leídas de un usuario.
        
        Args:
            conn: Conexión a base de datos
            usuario_id: ID del usuario
            limit: Máximo de notificaciones a retornar
            
        Returns:
            Lista de notificaciones pendientes
        """
        query = """
            SELECT 
                id, tipo, titulo, mensaje, id_oportunidad, created_at
            FROM tb_notificaciones
            WHERE usuario_id = $1 AND leida = false
            ORDER BY created_at DESC
            LIMIT $2
        """
        rows = await conn.fetch(query, usuario_id, limit)
        return [dict(r) for r in rows]
    
    async def get_unread_count(self, conn, usuario_id: UUID) -> int:
        """
        Cuenta notificaciones no leídas de un usuario.
        
        Args:
            conn: Conexión a base de datos
            usuario_id: ID del usuario
            
        Returns:
            Cantidad de notificaciones no leídas
        """
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM tb_notificaciones WHERE usuario_id = $1 AND leida = false",
            usuario_id
        )
        return count or 0
    
    async def mark_as_read(self, conn, notification_id: UUID, usuario_id: UUID):
        """
        Marca una notificación como leída.
        
        Args:
            conn: Conexión a base de datos
            notification_id: ID de la notificación
            usuario_id: ID del usuario (para seguridad)
        """
        await conn.execute(
            "UPDATE tb_notificaciones SET leida = true WHERE id = $1 AND usuario_id = $2",
            notification_id,
            usuario_id
        )
        logger.info(f"[NOTIF] Marcada como leída: {notification_id}")
    
    async def delete_notification(self, conn, notification_id: UUID, usuario_id: UUID) -> bool:
        """
        Elimina una notificación de un usuario.
        
        Args:
            conn: Conexión a base de datos
            notification_id: ID de la notificación
            usuario_id: ID del usuario (para seguridad)
            
        Returns:
            True si se eliminó, False si no existía
        """
        result = await conn.execute(
            "DELETE FROM tb_notificaciones WHERE id = $1 AND usuario_id = $2",
            notification_id,
            usuario_id
        )
        # asyncpg retorna "DELETE X" donde X es el número de filas eliminadas
        deleted_count = int(result.split()[-1])
        logger.info(f"[NOTIF] Eliminada: {notification_id} (rows: {deleted_count})")
        return deleted_count > 0
    
    async def create_notification(
        self,
        conn,
        usuario_id: UUID,
        tipo: str,
        titulo: str,
        mensaje: str,
        id_oportunidad: Optional[UUID] = None
    ) -> dict:
        """
        Crea una nueva notificación en BD.
        
        Args:
            conn: Conexión a base de datos
            usuario_id: Usuario destinatario
            tipo: Tipo de notificación (ASIGNACION, CAMBIO_ESTATUS, NUEVO_COMENTARIO)
            titulo: Título corto
            mensaje: Mensaje detallado
            id_oportunidad: Oportunidad relacionada (opcional)
            
        Returns:
            Notificación creada con ID y timestamp
        """
        query = """
            INSERT INTO tb_notificaciones (usuario_id, tipo, titulo, mensaje, id_oportunidad)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id, created_at
        """
        row = await conn.fetchrow(query, usuario_id, tipo, titulo, mensaje, id_oportunidad)
        
        notification_data = {
            "id": str(row['id']),
            "type": tipo,
            "title": titulo,
            "message": mensaje,
            "oportunidad_id": str(id_oportunidad) if id_oportunidad else None,
            "created_at": row['created_at'].isoformat()
        }
        
        logger.info(f"[NOTIF] Creada para usuario {usuario_id}: {tipo}")
        return notification_data
    
    def register_connection(self, usuario_id: UUID) -> Queue:
        """
        Registra una nueva conexión SSE para un usuario.
        
        Args:
            usuario_id: ID del usuario que se conecta
            
        Returns:
            Queue para enviar notificaciones a este usuario
        """
        queue = Queue()
        active_connections[usuario_id] = queue
        logger.info(f"[SSE] Usuario conectado: {usuario_id}")
        return queue
    
    def unregister_connection(self, usuario_id: UUID):
        """
        Elimina conexión SSE cuando usuario se desconecta.
        
        Args:
            usuario_id: ID del usuario que se desconecta
        """
        if usuario_id in active_connections:
            del active_connections[usuario_id]
            logger.info(f"[SSE] Usuario desconectado: {usuario_id}")
    
    async def broadcast_to_user(self, conn, usuario_id: UUID, notification_data: dict):
        """
        Envía notificación via LISTEN/NOTIFY (multi-worker) + fallback local.
        
        Estrategia híbrida para máxima resiliencia:
        1. PostgreSQL NOTIFY: Alcanza todos los workers en Railway/Gunicorn
        2. Fallback local: Si NOTIFY falla o es single-worker
        
        Args:
            conn: Conexión a base de datos (para NOTIFY)
            usuario_id: ID del usuario destinatario
            notification_data: Datos de la notificación
        """
        # 1. PostgreSQL NOTIFY (para multi-worker)
        try:
            # Nombre del canal: user_notif_<uuid_sin_guiones>
            import json
            channel = f"user_notif_{str(usuario_id).replace('-', '_')}"
            payload = json.dumps(notification_data)
            
            # Ejecutar NOTIFY usando pg_notify para soportar parametros seguros
            await conn.execute("SELECT pg_notify($1, $2)", channel, payload)
            logger.info(f"[SSE-PG] NOTIFY enviado a canal {channel[:30]}...")
            
            # Si el NOTIFY fue exitoso, no necesitamos hacer entrega local
            # El listener en router.py lo recibirá y lo pondrá en la queue.
            return 
            
        except Exception as e:
            logger.warning(f"[SSE-PG] NOTIFY falló (usando fallback local): {e}")
        
        # 2. Fallback local (para single-worker o si NOTIFY falla)
        if usuario_id in active_connections:
            queue = active_connections[usuario_id]
            await queue.put(notification_data)
            logger.info(f"[SSE-LOCAL] Entrega local a usuario {usuario_id}")
        else:
            logger.debug(f"[SSE] Usuario {usuario_id} no conectado localmente")
    
    def get_active_connections_count(self) -> int:
        """Retorna cantidad de usuarios actualmente conectados via SSE."""
        return len(active_connections)


def get_notifications_service():
    """Helper para inyección de dependencias."""
    return NotificationsService()
