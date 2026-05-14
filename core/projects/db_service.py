from typing import Any, Dict, List, Optional
from uuid import UUID


class ProjectsGateDBService:
    """Queries SQL puras para Proyectos Gate."""

    async def get_estatus_ganada_id(self, conn) -> Optional[int]:
        return await conn.fetchval(
            """
            SELECT id
            FROM tb_cat_estatus_oportunidades
            WHERE activo = true
              AND LOWER(nombre) = 'ganada'
            ORDER BY id
            LIMIT 1
            """
        )

    async def get_sitios_ganados_sin_proyecto(
        self,
        conn,
        estatus_ganada_id: int,
    ) -> List[Dict[str, Any]]:
        rows = await conn.fetch(
            """
            SELECT
                s.id_sitio,
                s.id_oportunidad,
                COALESCE(NULLIF(TRIM(s.nombre_sitio), ''), 'Sitio sin nombre') AS nombre_sitio,
                o.op_id_estandar,
                o.nombre_proyecto,
                o.cliente_nombre,
                o.id_tecnologia,
                t.nombre AS tecnologia_nombre,
                o.fecha_solicitud
            FROM tb_sitios_oportunidad s
            JOIN tb_oportunidades o ON o.id_oportunidad = s.id_oportunidad
            LEFT JOIN tb_cat_tecnologias t ON o.id_tecnologia = t.id
            WHERE s.id_estatus_global = $1
              AND NOT EXISTS (
                  SELECT 1
                  FROM tb_proyectos_gate p
                  WHERE p.id_sitio = s.id_sitio
              )
            ORDER BY o.fecha_solicitud DESC, s.fecha_carga ASC
            """,
            estatus_ganada_id,
        )
        return [dict(row) for row in rows]

    async def get_tecnologias(self, conn) -> List[Dict[str, Any]]:
        rows = await conn.fetch(
            """
            SELECT id, nombre
            FROM tb_cat_tecnologias
            WHERE activo = true
            ORDER BY id
            """
        )
        return [dict(row) for row in rows]

    async def consecutivo_exists(self, conn, consecutivo: int) -> bool:
        exists = await conn.fetchval(
            """
            SELECT 1
            FROM tb_proyectos_gate
            WHERE consecutivo = $1
            """,
            consecutivo,
        )
        return bool(exists)

    async def get_sitio_para_proyecto(self, conn, id_sitio: UUID) -> Optional[Dict[str, Any]]:
        row = await conn.fetchrow(
            """
            SELECT
                s.id_sitio,
                s.id_oportunidad,
                s.id_estatus_global,
                COALESCE(NULLIF(TRIM(s.nombre_sitio), ''), 'Sitio sin nombre') AS nombre_sitio,
                o.id_estatus_global AS oportunidad_estatus,
                o.nombre_proyecto,
                o.cliente_nombre,
                o.id_tecnologia AS oportunidad_id_tecnologia
            FROM tb_sitios_oportunidad s
            JOIN tb_oportunidades o ON o.id_oportunidad = s.id_oportunidad
            WHERE s.id_sitio = $1
            """,
            id_sitio,
        )
        return dict(row) if row else None

    async def proyecto_exists_for_sitio(self, conn, id_sitio: UUID) -> bool:
        exists = await conn.fetchval(
            """
            SELECT 1
            FROM tb_proyectos_gate
            WHERE id_sitio = $1
            LIMIT 1
            """,
            id_sitio,
        )
        return bool(exists)

    async def get_tecnologia_nombre(self, conn, id_tecnologia: int) -> Optional[str]:
        return await conn.fetchval(
            "SELECT nombre FROM tb_cat_tecnologias WHERE id = $1",
            id_tecnologia,
        )

    async def proyecto_id_estandar_exists(self, conn, proyecto_id_estandar: str) -> bool:
        exists = await conn.fetchval(
            "SELECT 1 FROM tb_proyectos_gate WHERE proyecto_id_estandar = $1",
            proyecto_id_estandar,
        )
        return bool(exists)

    async def insert_proyecto_gate(
        self,
        conn,
        data: Dict[str, Any],
    ) -> None:
        await conn.execute(
            """
            INSERT INTO tb_proyectos_gate (
                id_proyecto,
                id_oportunidad,
                id_sitio,
                proyecto_id_estandar,
                status_fase,
                aprobacion_direccion,
                fecha_aprobacion,
                prefijo,
                consecutivo,
                id_tecnologia,
                nombre_corto,
                created_at,
                created_by_id
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13
            )
            """,
            data["id_proyecto"],
            data["id_oportunidad"],
            data["id_sitio"],
            data["proyecto_id_estandar"],
            data["status_fase"],
            data["aprobacion_direccion"],
            data["fecha_aprobacion"],
            data["prefijo"],
            data["consecutivo"],
            data["id_tecnologia"],
            data["nombre_corto"],
            data["created_at"],
            data["created_by_id"],
        )

    async def get_proyecto_by_id(self, conn, id_proyecto: UUID) -> Optional[Dict[str, Any]]:
        row = await conn.fetchrow(
            """
            SELECT
                p.*,
                t.nombre as tecnologia_nombre,
                o.nombre_proyecto as oportunidad_nombre,
                o.cliente_nombre,
                o.op_id_estandar,
                u.nombre as creado_por_nombre,
                s.nombre_sitio
            FROM tb_proyectos_gate p
            LEFT JOIN tb_cat_tecnologias t ON p.id_tecnologia = t.id
            LEFT JOIN tb_oportunidades o ON p.id_oportunidad = o.id_oportunidad
            LEFT JOIN tb_usuarios u ON p.created_by_id = u.id_usuario
            LEFT JOIN tb_sitios_oportunidad s ON p.id_sitio = s.id_sitio
            WHERE p.id_proyecto = $1
            """,
            id_proyecto,
        )
        return dict(row) if row else None

    async def get_proyectos_list(
        self,
        conn,
        solo_aprobados: bool = True,
    ) -> List[Dict[str, Any]]:
        query = """
            SELECT
                p.id_proyecto,
                p.proyecto_id_estandar as nombre,
                p.consecutivo,
                t.nombre as tecnologia
            FROM tb_proyectos_gate p
            LEFT JOIN tb_cat_tecnologias t ON p.id_tecnologia = t.id
            WHERE 1=1
        """

        if solo_aprobados:
            query += " AND p.aprobacion_direccion = true"

        query += " ORDER BY p.consecutivo DESC"

        rows = await conn.fetch(query)
        return [dict(row) for row in rows]

    async def get_siguiente_consecutivo_sugerido(self, conn) -> int:
        max_consecutivo = await conn.fetchval(
            "SELECT COALESCE(MAX(consecutivo), 0) FROM tb_proyectos_gate"
        )
        return max_consecutivo + 1


def get_projects_gate_db_service() -> ProjectsGateDBService:
    return ProjectsGateDBService()

