from typing import Any, Dict, List, Optional
from uuid import UUID

# CTE compartida para resolver la raiz de la cadena hilo/parent de una oportunidad.
# Reutilizada tambien por modules/comercial/db_service.py (QUERY_GET_HILO_EMAIL_ANCHOR) -
# no duplicar este fragmento.
CTE_ROOT_OPORTUNIDAD = """root AS (
        SELECT COALESCE(parent_id, id_oportunidad) AS root_id
        FROM tb_oportunidades
        WHERE id_oportunidad = $1
    )"""


class WorkflowDBService:
    """Queries SQL puras para workflow compartido."""

    async def insert_comentario(
        self,
        conn,
        data: Dict[str, Any],
    ) -> None:
        await conn.execute(
            """
            INSERT INTO tb_comentarios_workflow (
                id, id_oportunidad, usuario_id, usuario_nombre, usuario_email,
                comentario, departamento_origen, modulo_origen, fecha_comentario
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            data["id"],
            data["id_oportunidad"],
            data["usuario_id"],
            data["usuario_nombre"],
            data["usuario_email"],
            data["comentario"],
            data["departamento_origen"],
            data["modulo_origen"],
            data["fecha_comentario"],
        )

    async def get_attachment_config(self, conn) -> Dict[str, str]:
        rows = await conn.fetch(
            """
            SELECT clave, valor
            FROM tb_configuracion_global
            WHERE clave IN ('MAX_UPLOAD_SIZE_MB', 'SHAREPOINT_BASE_FOLDER')
            """
        )
        return {row["clave"]: row["valor"] for row in rows}

    async def get_oportunidad_estandar(self, conn, id_oportunidad: UUID) -> Optional[str]:
        return await conn.fetchval(
            "SELECT op_id_estandar FROM tb_oportunidades WHERE id_oportunidad = $1",
            id_oportunidad,
        )

    async def insert_document_attachment(
        self,
        conn,
        data: Dict[str, Any],
    ) -> None:
        await conn.execute(
            """
            INSERT INTO tb_documentos_attachments (
                id_documento, nombre_archivo, url_sharepoint, drive_item_id, parent_drive_id,
                tipo_contenido, tamano_bytes, id_comentario, id_oportunidad, subido_por_id,
                origen_slug, activo
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 'comentario', TRUE)
            """,
            data["id_documento"],
            data["nombre_archivo"],
            data["url_sharepoint"],
            data["drive_item_id"],
            data["parent_drive_id"],
            data["tipo_contenido"],
            data["tamano_bytes"],
            data["id_comentario"],
            data["id_oportunidad"],
            data["subido_por_id"],
        )

    async def get_historial_rows(
        self,
        conn,
        id_oportunidad: UUID,
        limit: Optional[int] = None,
    ) -> List[dict]:
        params: list[Any] = [id_oportunidad]
        query = """
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
                c.id, c.usuario_nombre, c.usuario_email, c.comentario,
                c.departamento_origen, c.modulo_origen, c.fecha_comentario,
                c.id_oportunidad as comentario_oportunidad_id,
                op.op_id_estandar as comentario_op_estandar,
                d.nombre_archivo as adjunto_nombre,
                d.url_sharepoint as adjunto_url
            FROM tb_comentarios_workflow c
            LEFT JOIN tb_documentos_attachments d ON c.id = d.id_comentario
            LEFT JOIN tb_oportunidades op ON c.id_oportunidad = op.id_oportunidad
            WHERE c.id_oportunidad IN (SELECT id_oportunidad FROM cadena)
              AND (d.id_documento IS NULL OR d.activo = TRUE)
            ORDER BY c.fecha_comentario DESC
        """
        if limit:
            params.append(limit)
            query += f" LIMIT ${len(params)}"

        rows = await conn.fetch(query, *params)
        return [dict(row) for row in rows]

    async def get_detalle_oportunidad(
        self,
        conn,
        id_oportunidad: UUID,
    ) -> Optional[dict]:
        row = await conn.fetchrow(
            """
            SELECT
                op.*,
                c.nombre_fiscal as cliente_nombre,
                t.nombre as tecnologia_nombre,
                u_sim.nombre as responsable_simulacion,
                u_sim.email as responsable_simulacion_email,
                u_com.nombre as creador_nombre,
                u_com.email as creador_email,
                COALESCE(u_resp.nombre, u_com.nombre) as responsable_comercial_nombre,
                COALESCE(u_resp.email, u_com.email) as responsable_comercial_email,
                estatus.nombre as status_global
            FROM tb_oportunidades op
            LEFT JOIN tb_clientes c ON op.cliente_id = c.id
            LEFT JOIN tb_cat_tecnologias t ON op.id_tecnologia = t.id
            LEFT JOIN tb_usuarios u_sim ON op.responsable_simulacion_id = u_sim.id_usuario
            LEFT JOIN tb_usuarios u_com ON op.creado_por_id = u_com.id_usuario
            LEFT JOIN tb_usuarios u_resp ON op.responsable_comercial_id = u_resp.id_usuario
            LEFT JOIN tb_cat_estatus_oportunidades estatus ON op.id_estatus_global = estatus.id
            WHERE op.id_oportunidad = $1
            """,
            id_oportunidad,
        )
        return dict(row) if row else None

    async def es_ultimo_del_grupo(self, conn, id_oportunidad: UUID) -> bool:
        """True si id_oportunidad es el registro mas reciente del hilo (raiz + seguimientos)."""
        return bool(await conn.fetchval(
            f"""
            WITH {CTE_ROOT_OPORTUNIDAD},
            miembros AS (
                SELECT o.id_oportunidad, o.fecha_creacion
                FROM tb_oportunidades o
                CROSS JOIN root
                WHERE o.id_oportunidad = root.root_id OR o.parent_id = root.root_id
            )
            SELECT $1 = (
                SELECT id_oportunidad FROM miembros
                ORDER BY fecha_creacion DESC, id_oportunidad DESC LIMIT 1
            )
            """,
            id_oportunidad,
        ))

    async def get_historial_responsables(
        self,
        conn,
        id_oportunidad: UUID,
    ) -> List[dict]:
        rows = await conn.fetch(
            f"""
            WITH {CTE_ROOT_OPORTUNIDAD},
            cadena AS (
                SELECT o.*
                FROM tb_oportunidades o
                CROSS JOIN root
                WHERE o.id_oportunidad = root.root_id
                   OR o.parent_id = root.root_id
            ),
            creaciones AS (
                SELECT
                    'creacion'::text AS tipo_evento,
                    1 AS orden_evento,
                    o.id_oportunidad,
                    o.op_id_estandar,
                    o.titulo_proyecto,
                    COALESCE(o.fecha_solicitud, o.fecha_creacion) AS fecha_evento,
                    u_creador.nombre AS actor_nombre,
                    u_creador.email AS actor_email,
                    NULL::text AS responsable_anterior_nombre,
                    NULL::text AS responsable_anterior_email,
                    COALESCE(u_resp.nombre, u_creador.nombre) AS responsable_nuevo_nombre,
                    COALESCE(u_resp.email, u_creador.email) AS responsable_nuevo_email,
                    NULL::text AS motivo
                FROM cadena o
                LEFT JOIN tb_usuarios u_creador ON u_creador.id_usuario = o.creado_por_id
                LEFT JOIN tb_usuarios u_resp ON u_resp.id_usuario = o.responsable_comercial_id
            ),
            transferencias AS (
                SELECT
                    'transferencia'::text AS tipo_evento,
                    2 AS orden_evento,
                    o.id_oportunidad,
                    o.op_id_estandar,
                    o.titulo_proyecto,
                    t.fecha_transferencia AS fecha_evento,
                    u_actor.nombre AS actor_nombre,
                    u_actor.email AS actor_email,
                    u_anterior.nombre AS responsable_anterior_nombre,
                    u_anterior.email AS responsable_anterior_email,
                    u_nuevo.nombre AS responsable_nuevo_nombre,
                    u_nuevo.email AS responsable_nuevo_email,
                    t.motivo
                FROM tb_oportunidades_transferencias t
                JOIN cadena o ON o.id_oportunidad = t.id_oportunidad
                LEFT JOIN tb_usuarios u_actor ON u_actor.id_usuario = t.transferido_por_id
                LEFT JOIN tb_usuarios u_anterior ON u_anterior.id_usuario = t.responsable_anterior_id
                LEFT JOIN tb_usuarios u_nuevo ON u_nuevo.id_usuario = t.responsable_nuevo_id
            )
            SELECT *
            FROM (
                SELECT * FROM creaciones
                UNION ALL
                SELECT * FROM transferencias
            ) eventos
            ORDER BY fecha_evento ASC NULLS LAST, orden_evento ASC, op_id_estandar ASC
            """,
            id_oportunidad,
        )
        return [dict(row) for row in rows]

    async def get_oportunidad_basic_info(
        self,
        conn,
        id_oportunidad: UUID,
    ) -> Optional[dict]:
        row = await conn.fetchrow(
            """
            SELECT op_id_estandar, nombre_proyecto, titulo_proyecto, cliente_nombre
            FROM tb_oportunidades
            WHERE id_oportunidad = $1
            """,
            id_oportunidad,
        )
        return dict(row) if row else None

    async def get_sitios_oportunidad(
        self,
        conn,
        id_oportunidad: UUID,
    ) -> List[dict]:
        rows = await conn.fetch(
            """
            SELECT id_sitio, nombre_sitio
            FROM tb_sitios_oportunidad
            WHERE id_oportunidad = $1
            ORDER BY nombre_sitio
            """,
            id_oportunidad,
        )
        return [dict(row) for row in rows]

    async def get_sitios_ganados_detalle(
        self,
        conn,
        id_oportunidad: UUID,
    ) -> List[dict]:
        rows = await conn.fetch(
            """
            SELECT
                s.id_sitio,
                s.nombre_sitio,
                (p.id_proyecto IS NOT NULL) AS tiene_proyecto,
                p.proyecto_id_estandar
            FROM tb_sitios_oportunidad s
            LEFT JOIN tb_proyectos_gate p ON p.id_sitio = s.id_sitio
            WHERE s.id_oportunidad = $1
              AND s.id_estatus_global = (
                  SELECT id FROM tb_cat_estatus_oportunidades
                  WHERE LOWER(nombre) = 'ganada' LIMIT 1
              )
            ORDER BY s.nombre_sitio
            """,
            id_oportunidad,
        )
        return [dict(row) for row in rows]


def get_workflow_db_service() -> WorkflowDBService:
    return WorkflowDBService()

