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

    async def update_reagendar(self, conn, id_levantamiento: UUID, nueva_fecha: str, user_id: UUID) -> None:
        """
        Actualiza fecha_visita_programada con la nueva fecha,
        registra fecha_reagenda (now), limpia motivo_pospone,
        y cambia estado a 9 (Agendado).
        """
        await conn.execute("""
            UPDATE tb_levantamientos
            SET id_estatus_global       = 9,
                fecha_visita_programada = $1::date AT TIME ZONE 'America/Mexico_City',
                fecha_reagenda          = now(),
                motivo_pospone          = NULL,
                updated_at              = now(),
                updated_by_id           = $2
            WHERE id_levantamiento      = $3
        """, nueva_fecha, user_id, id_levantamiento)

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


# --------------------------------------------------------------
# Helper de inyección (mismo patrón que get_service en service.py)
# --------------------------------------------------------------
def get_db_service() -> LevantamientosDBService:
    return LevantamientosDBService()
