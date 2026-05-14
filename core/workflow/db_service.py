from typing import Any, Dict, List, Optional
from uuid import UUID


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
                u_com.email as responsable_email,
                estatus.nombre as status_global
            FROM tb_oportunidades op
            LEFT JOIN tb_clientes c ON op.cliente_id = c.id
            LEFT JOIN tb_cat_tecnologias t ON op.id_tecnologia = t.id
            LEFT JOIN tb_usuarios u_sim ON op.responsable_simulacion_id = u_sim.id_usuario
            LEFT JOIN tb_usuarios u_com ON op.creado_por_id = u_com.id_usuario
            LEFT JOIN tb_cat_estatus_oportunidades estatus ON op.id_estatus_global = estatus.id
            WHERE op.id_oportunidad = $1
            """,
            id_oportunidad,
        )
        return dict(row) if row else None

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

