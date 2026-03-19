"""
Service Layer del modulo Proyectos.
Vista global de todos los proyectos, sin filtro de area.
"""
from typing import Optional, List, Dict, Any
from uuid import UUID
import logging

from core.transfers.service import TransferService, get_transfer_service

logger = logging.getLogger("ProyectosService")

# Roles asignables al equipo de proyecto (almacenados en tb_proyecto_usuarios)
ROLES_EQUIPO = [
    {"rol": "ingeniero_asignado", "area": "INGENIERIA",   "label": "Ingeniero Asignado"},
    {"rol": "coordinador_obra",   "area": "CONSTRUCCION", "label": "Coordinador de Obra"},
    {"rol": "encargado",          "area": "OYM",          "label": "Encargado O&M"},
]


class ProyectosService:

    def __init__(self):
        self.transfers = get_transfer_service()
        self.roles_equipo = ROLES_EQUIPO

    async def get_proyectos(
        self, conn,
        area_filter: Optional[str] = None,
        status_filter: Optional[str] = None,
        q: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        return await self.transfers.get_all_proyectos(
            conn, area_filter, status_filter, q, limit
        )

    async def get_kpis(self, conn) -> Dict[str, Any]:
        return await self.transfers.get_kpis_global(conn)

    async def get_proyecto_detalle(
        self, conn, id_proyecto: UUID
    ) -> Dict[str, Any]:
        return await self.transfers.get_proyecto_detalle(conn, id_proyecto)

    async def get_historial(
        self, conn, id_proyecto: UUID
    ) -> List[Dict[str, Any]]:
        return await self.transfers.get_historial_traspasos(conn, id_proyecto)

    async def get_equipo_proyecto(self, conn, id_proyecto: UUID) -> Dict[str, Any]:
        """
        Retorna el equipo actual del proyecto con:
        - asignaciones: roles almacenados en tb_proyecto_usuarios
        - jefe_ingenieria / jefe_construccion: referencias organizacionales (solo lectura)
        - usuarios por departamento: listas filtradas para los dropdowns
        """
        # Asignaciones actuales del proyecto
        rows = await conn.fetch(
            """
            SELECT pu.rol_proyecto, pu.area, pu.id_usuario, u.nombre AS nombre_usuario
            FROM tb_proyecto_usuarios pu
            JOIN tb_usuarios u ON u.id_usuario = pu.id_usuario
            WHERE pu.id_proyecto = $1 AND pu.activo = TRUE
            ORDER BY pu.area, pu.rol_proyecto
            """,
            id_proyecto
        )
        asignaciones = [dict(r) for r in rows]

        # Responsables organizacionales (referencia, no asignables desde este modal)
        jefes_rows = await conn.fetch(
            """
            SELECT id_usuario, nombre, rol_organizacional
            FROM tb_usuarios
            WHERE rol_organizacional IN ('jefe_ingenieria', 'jefe_construccion')
              AND is_active = TRUE
            """,
        )
        jefe_ingenieria = next(
            (dict(j) for j in jefes_rows if j["rol_organizacional"] == "jefe_ingenieria"), None
        )
        jefe_construccion = next(
            (dict(j) for j in jefes_rows if j["rol_organizacional"] == "jefe_construccion"), None
        )

        # Usuarios activos filtrados por departamento (via slug de tb_cat_departamentos)
        dept_rows = await conn.fetch(
            """
            SELECT u.id_usuario, u.nombre, d.slug AS dept_slug
            FROM tb_usuarios u
            JOIN tb_cat_departamentos d ON d.nombre = u.department
            WHERE d.slug IN ('ingenieria', 'construccion', 'oym')
              AND u.is_active = TRUE
            ORDER BY d.slug, u.nombre
            """
        )

        usuarios_ingenieria  = [dict(r) for r in dept_rows if r["dept_slug"] == "ingenieria"]
        usuarios_construccion = [dict(r) for r in dept_rows if r["dept_slug"] == "construccion"]
        usuarios_oym         = [dict(r) for r in dept_rows if r["dept_slug"] == "oym"]

        return {
            "asignaciones": asignaciones,
            "jefe_ingenieria": jefe_ingenieria,
            "jefe_construccion": jefe_construccion,
            "usuarios_ingenieria": usuarios_ingenieria,
            "usuarios_construccion": usuarios_construccion,
            "usuarios_oym": usuarios_oym,
        }

    async def save_equipo_proyecto(
        self,
        conn,
        id_proyecto: UUID,
        asignaciones: List[Dict],
        asignado_por_id: UUID,
    ) -> None:
        """
        Reemplaza el equipo del proyecto.
        Desactiva asignaciones anteriores e inserta las nuevas.
        asignaciones = [{"rol_proyecto": ..., "area": ..., "id_usuario": UUID|None}, ...]
        """
        await conn.execute(
            "UPDATE tb_proyecto_usuarios SET activo = FALSE, fecha_fin = NOW() WHERE id_proyecto = $1",
            id_proyecto
        )

        for item in asignaciones:
            if not item.get("id_usuario"):
                continue
            await conn.execute(
                """
                INSERT INTO tb_proyecto_usuarios
                    (id_proyecto, id_usuario, rol_proyecto, area, activo, asignado_por_id)
                VALUES ($1, $2, $3, $4, TRUE, $5)
                """,
                id_proyecto,
                item["id_usuario"],
                item["rol_proyecto"],
                item["area"],
                asignado_por_id,
            )

        logger.info("Equipo actualizado para proyecto %s por usuario %s", id_proyecto, asignado_por_id)

    def permisos_equipo(self, context: Dict) -> Dict[str, bool]:
        """
        Retorna flags de permiso granulares por seccion del equipo.
        - puede_asignar_ingenieria: ADMIN o jefe_ingenieria
        - puede_asignar_construccion: ADMIN o jefe_construccion
        - puede_asignar_oym: ADMIN o MANAGER
        """
        role = context.get("role", "")
        rol_org = context.get("rol_organizacional") or ""
        is_admin = role == "ADMIN"
        return {
            "puede_asignar_ingenieria":  is_admin or rol_org == "jefe_ingenieria",
            "puede_asignar_construccion": is_admin or rol_org == "jefe_construccion",
            "puede_asignar_oym":         is_admin or role == "MANAGER",
            "puede_ver_modal":           is_admin or role == "MANAGER" or rol_org in ("jefe_ingenieria", "jefe_construccion", "director"),
        }


def get_service() -> ProyectosService:
    return ProyectosService()
