"""
Service Layer del modulo Proyectos.
Vista global de todos los proyectos, sin filtro de area.
"""
from typing import Optional, List, Dict, Any
from uuid import UUID
import logging

import asyncpg

from core.config_service import ConfigService
from core.transfers.service import TransferService, get_transfer_service
from .db_service import ProyectosDBService, get_db_service, ROL_RESPONSABLE_POR_AREA

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
# Por area: (rol_proyecto del responsable, rol_organizacional del jefe del area).
# El rol_resp se toma de ROL_RESPONSABLE_POR_AREA (fuente unica en db_service).
RESPONSABLE_POR_AREA = {
    "INGENIERIA": (ROL_RESPONSABLE_POR_AREA["INGENIERIA"], "jefe_ingenieria"),
    "CONSTRUCCION": (ROL_RESPONSABLE_POR_AREA["CONSTRUCCION"], "jefe_construccion"),
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

        # Responsables del proyecto: RC/RI persistido (decision 3 del modelo cerrado);
        # fallback al primer jefe organizacional solo si el proyecto aun no tiene RC/RI.
        jefes_rows = await self.db.get_jefes_organizacionales(conn)
        jefes_ingenieria = [j for j in jefes_rows if j["rol_organizacional"] == "jefe_ingenieria"]
        jefes_construccion = [j for j in jefes_rows if j["rol_organizacional"] == "jefe_construccion"]

        # RC/RI persistido: ya viene en asignaciones (get_asignaciones_equipo trae todas
        # las filas activas del proyecto), evitamos 2 queries extra. Se resuelve desde la
        # propia asignacion (id + nombre), de modo que un RC/RI que ya no sea jefe activo
        # se sigue mostrando. Fallback al primer jefe organizacional si no hay RC/RI.
        def _responsable(rol_proyecto, default):
            row = next((a for a in asignaciones if a["rol_proyecto"] == rol_proyecto), None)
            if row:
                return {"id_usuario": row["id_usuario"], "nombre": row["nombre_usuario"]}
            return default

        jefe_ingenieria = _responsable("responsable_ingenieria", jefes_ingenieria[0] if jefes_ingenieria else None)
        jefe_construccion = _responsable("responsable_construccion", jefes_construccion[0] if jefes_construccion else None)

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
            "jefes_ingenieria": jefes_ingenieria,
            "jefes_construccion": jefes_construccion,
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
        context: Optional[Dict] = None,
        responsables_explicitos: Optional[Dict[str, UUID]] = None,
    ) -> None:
        """
        Actualiza solo las secciones del equipo que el usuario puede editar.
        Preserva asignaciones existentes para secciones sin permiso.
        Al definir coordinador/ingeniero en un proyecto sin RC/RI, autoasigna el
        responsable (ver _asegurar_responsable).
        asignaciones = [{"rol_proyecto": ..., "area": ..., "id_usuario": UUID|None}, ...]
        """
        context = context or {}
        responsables_explicitos = responsables_explicitos or {}
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
                    if key in ROL_EDITABLE_DEFINE_RESPONSABLE:
                        await self._asegurar_responsable(
                            conn, id_proyecto, ROL_EDITABLE_DEFINE_RESPONSABLE[key],
                            asignado_por_id, context, responsables_explicitos,
                        )

        logger.info("Equipo actualizado para proyecto %s por usuario %s", id_proyecto, asignado_por_id)

    async def _asegurar_responsable(
        self, conn, id_proyecto: UUID, area: str, asignado_por_id: UUID,
        context: Dict, responsables_explicitos: Dict[str, UUID],
    ) -> None:
        """Define el RC/RI del proyecto si aun no existe. No lo cambia en rotaciones."""
        rol_resp, rol_jefe = RESPONSABLE_POR_AREA[area]
        existente = await self.db.get_responsable_proyecto(conn, id_proyecto, area)
        if existente is not None:
            return  # ya definido: las rotaciones de coordinador no cambian el RC/RI

        es_admin = context.get("role") == "ADMIN"
        rol_org = (context.get("rol_organizacional") or "").strip().lower()
        es_director = rol_org == "director"
        autoasignacion = await ConfigService.get_global_config(
            conn, "equipo.autoasignacion_rc_por_jefes", True, bool
        )

        if not es_admin and not es_director and autoasignacion and rol_org == rol_jefe:
            responsable_id = asignado_por_id
        elif area in responsables_explicitos and responsables_explicitos[area]:
            responsable_id = responsables_explicitos[area]
            if not await self.db.usuario_tiene_rol_organizacional(conn, responsable_id, rol_jefe):
                raise ValueError(f"El responsable indicado no tiene el rol {rol_jefe}")
        else:
            # No se puede determinar el RC/RI automaticamente (ADMIN/Direccion sin
            # seleccion explicita, o autoasignacion deshabilitada). No abortamos el
            # guardado del coordinador: el RC/RI queda sin definir y Direccion lo fija
            # luego via reasignacion. Evita el 400 + rollback del equipo completo.
            logger.info(
                "RC/RI no autodefinido en proyecto %s area %s: se guarda el equipo sin responsable",
                id_proyecto, area,
            )
            return

        # Savepoint anidado: si el jefe ya esta activo en esta area con otro rol
        # (uq_proyecto_usuario_area_activo, mig 086), el INSERT viola el indice. Sin el
        # savepoint, la excepcion abortaria la transaccion externa de save_equipo_proyecto.
        # Con el savepoint solo se revierte este INSERT y el resto del guardado persiste.
        try:
            async with conn.transaction():
                await self.db.insertar_asignacion_equipo(
                    conn, id_proyecto, responsable_id, rol_resp, area, asignado_por_id
                )
        except asyncpg.UniqueViolationError:
            logger.warning(
                "No se autoasigno RC/RI en proyecto %s area %s: usuario %s ya activo en el area",
                id_proyecto, area, responsable_id,
            )

    async def reasignar_responsable(
        self, conn, id_proyecto: UUID, area: str,
        nuevo_responsable_id: Optional[UUID], asignado_por_id: UUID,
    ) -> None:
        """Reasigna el RC/RI del proyecto. Solo lo invoca el router con permiso de Direccion/ADMIN."""
        if area not in RESPONSABLE_POR_AREA:
            raise ValueError("Area invalida")
        rol_resp, rol_jefe = RESPONSABLE_POR_AREA[area]
        if nuevo_responsable_id is not None:
            if not await self.db.usuario_tiene_rol_organizacional(conn, nuevo_responsable_id, rol_jefe):
                raise ValueError(f"El responsable indicado no tiene el rol {rol_jefe}")
        async with conn.transaction():
            await self.db.desactivar_asignacion_equipo(conn, id_proyecto, rol_resp, area)
            if nuevo_responsable_id is not None:
                await self.db.insertar_asignacion_equipo(
                    conn, id_proyecto, nuevo_responsable_id, rol_resp, area, asignado_por_id
                )
        logger.info("Responsable %s reasignado en proyecto %s por %s", area, id_proyecto, asignado_por_id)

    async def permisos_equipo(
        self, conn, context: Dict, id_proyecto: UUID
    ) -> Dict[str, bool]:
        """
        Flags de permiso por seccion del equipo, conscientes del proyecto.
        - Sin RC/RI definido: cualquier jefe del area puede tomar el proyecto.
        - Con RC/RI definido: solo ese RC/RI gestiona su coordinador (candado de
          propiedad, configurable via equipo.gestion_solo_responsable).
        - ADMIN y Direccion sobrescriben; Direccion reasigna el RC/RI.
        """
        role = context.get("role")
        rol_org = (context.get("rol_organizacional") or "").strip().lower()
        user_id = context.get("user_db_id")
        es_admin = role == "ADMIN"
        es_director = rol_org == "director"

        # ADMIN sobrescribe todo: evita consultar RC/RI y config.
        if es_admin:
            return {
                "puede_asignar_ingenieria": True,
                "puede_asignar_construccion": True,
                "puede_asignar_oym": True,
                "puede_reasignar_responsable": True,
                "puede_ver_modal": True,
            }

        rc_id = await self.db.get_responsable_proyecto(conn, id_proyecto, "CONSTRUCCION")
        ri_id = await self.db.get_responsable_proyecto(conn, id_proyecto, "INGENIERIA")
        solo_responsable = await ConfigService.get_global_config(
            conn, "equipo.gestion_solo_responsable", True, bool
        )

        def _puede_gestionar(responsable_id, es_jefe_area):
            if es_admin or es_director:
                return True
            if responsable_id is None:
                return es_jefe_area
            if not solo_responsable:
                return es_jefe_area
            return str(responsable_id) == str(user_id)

        dept_slug = await self.db.get_department_slug(conn, context.get("department"))

        return {
            "puede_asignar_ingenieria": _puede_gestionar(ri_id, rol_org == "jefe_ingenieria"),
            "puede_asignar_construccion": _puede_gestionar(rc_id, rol_org == "jefe_construccion"),
            "puede_asignar_oym": es_admin or dept_slug == "oym",
            "puede_reasignar_responsable": es_admin or es_director,
            "puede_ver_modal": True,
        }


def get_service() -> ProyectosService:
    return ProyectosService()
