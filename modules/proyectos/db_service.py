"""
DB Service del modulo Proyectos.
Queries SQL puras con asyncpg. Recibe conn como parametro.
"""
from typing import Optional, List, Dict, Any
from uuid import UUID


class ProyectosDBService:
    """Capa de acceso a datos para Proyectos."""

    async def get_asignaciones_equipo(
        self, conn, id_proyecto: UUID
    ) -> List[Dict[str, Any]]:
        rows = await conn.fetch(
            """
            SELECT pu.rol_proyecto, pu.area, pu.id_usuario, u.nombre AS nombre_usuario
            FROM tb_proyecto_usuarios pu
            JOIN tb_usuarios u ON u.id_usuario = pu.id_usuario
            WHERE pu.id_proyecto = $1 AND pu.activo = TRUE
            ORDER BY pu.area, pu.rol_proyecto
            """,
            id_proyecto,
        )
        return [dict(r) for r in rows]

    async def get_jefes_organizacionales(self, conn) -> List[Dict[str, Any]]:
        rows = await conn.fetch(
            """
            SELECT id_usuario, nombre, rol_organizacional
            FROM tb_usuarios
            WHERE rol_organizacional IN ('jefe_ingenieria', 'jefe_construccion')
              AND is_active = TRUE
            """
        )
        return [dict(r) for r in rows]

    async def get_usuarios_por_departamentos(
        self, conn, slugs: List[str]
    ) -> List[Dict[str, Any]]:
        rows = await conn.fetch(
            """
            SELECT u.id_usuario, u.nombre, d.slug AS dept_slug
            FROM tb_usuarios u
            JOIN tb_cat_departamentos d ON LOWER(d.nombre) = LOWER(u.department)
            WHERE d.slug = ANY($1::varchar[])
              AND u.is_active = TRUE
            ORDER BY d.slug, u.nombre
            """,
            slugs,
        )
        return [dict(r) for r in rows]

    async def get_department_slug(
        self, conn, department_name: Optional[str]
    ) -> Optional[str]:
        if not department_name:
            return None
        return await conn.fetchval(
            """
            SELECT slug
            FROM tb_cat_departamentos
            WHERE LOWER(nombre) = LOWER($1)
               OR LOWER(slug) = LOWER($1)
            LIMIT 1
            """,
            department_name,
        )

    async def usuario_activo_en_departamento(
        self, conn, id_usuario: UUID, dept_slug: str
    ) -> bool:
        exists = await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT 1
                FROM tb_usuarios u
                JOIN tb_cat_departamentos d ON LOWER(d.nombre) = LOWER(u.department)
                WHERE u.id_usuario = $1
                  AND u.is_active = TRUE
                  AND d.slug = $2
            )
            """,
            id_usuario,
            dept_slug,
        )
        return bool(exists)

    async def desactivar_asignacion_equipo(
        self, conn, id_proyecto: UUID, rol_proyecto: str, area: str
    ) -> None:
        await conn.execute(
            """
            UPDATE tb_proyecto_usuarios
            SET activo = FALSE, fecha_fin = NOW()
            WHERE id_proyecto = $1
              AND rol_proyecto = $2
              AND area = $3
              AND activo = TRUE
            """,
            id_proyecto,
            rol_proyecto,
            area,
        )

    async def insertar_asignacion_equipo(
        self,
        conn,
        id_proyecto: UUID,
        id_usuario: UUID,
        rol_proyecto: str,
        area: str,
        asignado_por_id: UUID,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO tb_proyecto_usuarios
                (id_proyecto, id_usuario, rol_proyecto, area, activo, asignado_por_id)
            VALUES ($1, $2, $3, $4, TRUE, $5)
            """,
            id_proyecto,
            id_usuario,
            rol_proyecto,
            area,
            asignado_por_id,
        )


def get_db_service() -> ProyectosDBService:
    return ProyectosDBService()
