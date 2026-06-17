"""
Service Layer del modulo Proyectos.
Vista global de todos los proyectos, sin filtro de area.
"""
from typing import Optional, List, Dict, Any
from uuid import UUID
import logging

from core.transfers.service import TransferService, get_transfer_service
from .db_service import ProyectosDBService, get_db_service

logger = logging.getLogger("ProyectosService")

# Roles asignables al equipo de proyecto (almacenados en tb_proyecto_usuarios)
ROLES_EQUIPO = [
    {"rol": "ingeniero_asignado", "area": "INGENIERIA",   "label": "Ingeniero Asignado"},
    {"rol": "coordinador_obra",   "area": "CONSTRUCCION", "label": "Coordinador de Obra"},
    {"rol": "encargado",          "area": "OYM",          "label": "Encargado O&M"},
]

ROLES_EQUIPO_MAP = {(r["rol"], r["area"]): r for r in ROLES_EQUIPO}
PERMISO_POR_ROL = {
    ("ingeniero_asignado", "INGENIERIA"): "puede_asignar_ingenieria",
    ("coordinador_obra", "CONSTRUCCION"): "puede_asignar_construccion",
    ("encargado", "OYM"): "puede_asignar_oym",
}
DEPARTAMENTO_POR_ROL = {
    ("ingeniero_asignado", "INGENIERIA"): "ingenieria",
    ("coordinador_obra", "CONSTRUCCION"): "construccion",
    ("encargado", "OYM"): "oym",
}

# Rol editable que, al asignarse por primera vez, define el RC/RI del proyecto
ROL_EDITABLE_DEFINE_RESPONSABLE = {
    ("ingeniero_asignado", "INGENIERIA"): "INGENIERIA",
    ("coordinador_obra", "CONSTRUCCION"): "CONSTRUCCION",
}
# Por area: (rol_proyecto del responsable, rol_organizacional del jefe del area)
RESPONSABLE_POR_AREA = {
    "INGENIERIA": ("responsable_ingenieria", "jefe_ingenieria"),
    "CONSTRUCCION": ("responsable_construccion", "jefe_construccion"),
}


class ProyectosService:

    def __init__(self):
        self.transfers = get_transfer_service()
        self.db: ProyectosDBService = get_db_service()
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
        asignaciones = await self.db.get_asignaciones_equipo(conn, id_proyecto)

        # Responsables organizacionales (referencia, no asignables desde este modal)
        jefes_rows = await self.db.get_jefes_organizacionales(conn)
        jefe_ingenieria = next(
            (j for j in jefes_rows if j["rol_organizacional"] == "jefe_ingenieria"), None
        )
        jefe_construccion = next(
            (j for j in jefes_rows if j["rol_organizacional"] == "jefe_construccion"), None
        )

        # Usuarios activos filtrados por departamento (via slug de tb_cat_departamentos)
        dept_rows = await self.db.get_usuarios_por_departamentos(
            conn, ["ingenieria", "construccion", "oym"]
        )

        usuarios_ingenieria = [r for r in dept_rows if r["dept_slug"] == "ingenieria"]
        usuarios_construccion = [r for r in dept_rows if r["dept_slug"] == "construccion"]
        usuarios_oym = [r for r in dept_rows if r["dept_slug"] == "oym"]

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
        permisos: Dict[str, bool],
    ) -> None:
        """
        Actualiza solo las secciones del equipo que el usuario puede editar.
        Preserva asignaciones existentes para secciones sin permiso.
        asignaciones = [{"rol_proyecto": ..., "area": ..., "id_usuario": UUID|None}, ...]
        """
        asignaciones_por_rol = {}
        for item in asignaciones:
            key = (item.get("rol_proyecto"), item.get("area"))
            if key not in ROLES_EQUIPO_MAP:
                raise ValueError("Asignacion de equipo invalida")
            asignaciones_por_rol[key] = item

        async with conn.transaction():
            for key in ROLES_EQUIPO_MAP:
                permiso = PERMISO_POR_ROL[key]
                if not permisos.get(permiso):
                    continue

                if key not in asignaciones_por_rol:
                    continue

                item = asignaciones_por_rol[key]
                id_usuario = item.get("id_usuario")

                if id_usuario:
                    dept_slug = DEPARTAMENTO_POR_ROL[key]
                    usuario_valido = await self.db.usuario_activo_en_departamento(
                        conn, id_usuario, dept_slug
                    )
                    if not usuario_valido:
                        raise ValueError("El usuario seleccionado no pertenece al departamento requerido")

                asignacion_actual = await self.db.get_asignacion_equipo_actual(
                    conn, id_proyecto, key[0], key[1]
                )
                if asignacion_actual and id_usuario:
                    if str(asignacion_actual["id_usuario"]) == str(id_usuario):
                        continue

                await self.db.desactivar_asignacion_equipo(
                    conn, id_proyecto, key[0], key[1]
                )

                if id_usuario:
                    await self.db.insertar_asignacion_equipo(
                        conn, id_proyecto, id_usuario, key[0], key[1], asignado_por_id
                    )

        logger.info("Equipo actualizado para proyecto %s por usuario %s", id_proyecto, asignado_por_id)

    async def permisos_equipo(self, conn, context: Dict) -> Dict[str, bool]:
        """
        Retorna flags de permiso granulares por seccion del equipo.
        - Ingenieria: jefe_ingenieria organizacional.
        - Construccion: jefe_construccion organizacional.
        - O&M: usuario cuyo departamento resuelve al catalogo con slug oym.
        """
        if context.get("role") == "ADMIN":
            return {
                "puede_asignar_ingenieria": True,
                "puede_asignar_construccion": True,
                "puede_asignar_oym": True,
                "puede_ver_modal": True,
            }

        rol_org = (context.get("rol_organizacional") or "").strip().lower()
        dept_slug = await self.db.get_department_slug(conn, context.get("department"))

        return {
            "puede_asignar_ingenieria": rol_org == "jefe_ingenieria",
            "puede_asignar_construccion": rol_org == "jefe_construccion",
            "puede_asignar_oym": dept_slug == "oym",
            "puede_ver_modal": True,
        }


def get_service() -> ProyectosService:
    return ProyectosService()
