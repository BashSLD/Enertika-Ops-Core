"""
Service Layer del modulo Proyectos.
Vista global de todos los proyectos, sin filtro de area.
"""
from typing import Optional, List, Dict, Any
from uuid import UUID
import logging

import asyncpg

from core.config_service import ConfigService
from core.constants import ROL_OPERATIVO_POR_AREA
from core.transfers.service import get_transfer_service
from .db_service import ProyectosDBService, get_db_service, ROL_RESPONSABLE_POR_AREA

logger = logging.getLogger("ProyectosService")

# Roles asignables al equipo de proyecto (almacenados en tb_proyecto_usuarios).
# Fuente unica: todos los mapas derivados (ROLES_EQUIPO_MAP, PERMISO_POR_ROL, etc.)
# se construyen a partir de esta lista para evitar repetir las tuplas (rol, area).
# El campo "rol" de cada entrada se toma de ROL_OPERATIVO_POR_AREA (core/constants.py),
# que a su vez es la fuente que usa core/transfers/db_service.py — evita que ambos se desincronicen.
ROLES_EQUIPO = [
    {
        "rol": ROL_OPERATIVO_POR_AREA["INGENIERIA"], "area": "INGENIERIA", "label": "Ingeniero de Diseño",
        "permiso": "puede_asignar_ingenieria", "departamento": "ingenieria",
        "rol_jefe": "jefe_ingenieria",
    },
    {
        "rol": ROL_OPERATIVO_POR_AREA["CONSTRUCCION"], "area": "CONSTRUCCION", "label": "Coordinador de Obra",
        "permiso": "puede_asignar_construccion", "departamento": "construccion",
        "rol_jefe": "jefe_construccion",
    },
    {
        "rol": ROL_OPERATIVO_POR_AREA["OYM"], "area": "OYM", "label": "Encargado O&M",
        "permiso": "puede_asignar_oym", "departamento": "oym",
        "rol_jefe": None,
    },
    {
        "rol": ROL_OPERATIVO_POR_AREA["COMPRAS"], "area": "COMPRAS", "label": "Comprador Asignado",
        "permiso": "puede_asignar_compras", "departamento": "compras",
        "rol_jefe": "jefe_compras",
    },
]

ROLES_EQUIPO_MAP = {(r["rol"], r["area"]): r for r in ROLES_EQUIPO}
PERMISO_POR_ROL = {(r["rol"], r["area"]): r["permiso"] for r in ROLES_EQUIPO}
DEPARTAMENTO_POR_ROL = {(r["rol"], r["area"]): r["departamento"] for r in ROLES_EQUIPO}

# Nombres legibles por rol_proyecto, para mensajes de error claros. Incluye los
# roles operativos (ROLES_EQUIPO) y los roles de responsable (RC/RI), que no
# tienen entrada en ROLES_EQUIPO porque no son editables directamente en el modal.
ROL_PROYECTO_LABELS = {
    **{r["rol"]: r["label"] for r in ROLES_EQUIPO},
    "responsable_ingenieria": "Responsable de Ingeniería (RI)",
    "responsable_construccion": "Responsable de Construcción (RC)",
    "responsable_compras": "Responsable de Compras",
}

# Excepcion de negocio: en Ingenieria una misma persona puede ejecutar el rol
# operativo y conservar el ownership como RI. Cualquier otra combinacion de
# roles activos para el mismo usuario y area sigue siendo invalida.
ROLES_COMPATIBLES_MISMO_USUARIO = {
    "INGENIERIA": frozenset({"ingeniero_asignado", "responsable_ingenieria"}),
}


def _msg_rol_duplicado_area(area: str, rol_conflicto: str) -> str:
    """Pre-check (uq_proyecto_usuario_area_activo): se conoce el rol existente
    con el que choca el usuario."""
    rol_label = ROL_PROYECTO_LABELS.get(rol_conflicto, rol_conflicto)
    return (
        f"Este usuario ya es {rol_label} en el área {area} de este proyecto y no "
        "puede tener dos roles activos a la vez en la misma área."
    )


def _msg_usuario_ya_tiene_rol_activo(area: str, rol_nuevo: str) -> str:
    """Carrera check-then-insert sobre uq_proyecto_usuario_area_activo: no se
    conoce el rol existente en conflicto, solo el rol nuevo que se intentaba
    asignar."""
    rol_label = ROL_PROYECTO_LABELS.get(rol_nuevo, rol_nuevo)
    return (
        f"Este usuario ya tiene un rol activo en el área {area} de este "
        f"proyecto; no puede asignarse también como {rol_label}."
    )


def _msg_rol_tomado_por_otro(area: str) -> str:
    """Carrera check-then-insert sobre uq_proyecto_rol_area_activo: otro
    usuario tomo el mismo rol+area casi al mismo tiempo (no es un conflicto
    de dos roles del usuario que se esta asignando)."""
    return (
        f"Otro usuario acaba de tomar este rol en el área {area}; "
        "actualiza la página e intenta de nuevo."
    )

# Rol editable que, al asignarse por primera vez, define el RC/RI del proyecto
ROL_EDITABLE_DEFINE_RESPONSABLE = {
    (r["rol"], r["area"]): r["area"] for r in ROLES_EQUIPO if r["rol_jefe"]
}
# Por area: (rol_proyecto del responsable, rol_organizacional del jefe del area).
# El rol_resp se toma de ROL_RESPONSABLE_POR_AREA (fuente unica en db_service).
RESPONSABLE_POR_AREA = {
    r["area"]: (ROL_RESPONSABLE_POR_AREA[r["area"]], r["rol_jefe"])
    for r in ROLES_EQUIPO if r["rol_jefe"]
}

# Constantes de rol_proyecto para consumidores externos (p. ej. modules/comercial),
# derivadas de ROLES_EQUIPO en vez de repetir el literal.
ROL_COORDINADOR_OBRA = next(r["rol"] for r in ROLES_EQUIPO if r["area"] == "CONSTRUCCION")
ROL_ENCARGADO_OYM = next(r["rol"] for r in ROLES_EQUIPO if r["area"] == "OYM")


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

    async def get_usuarios_activos_nombres(self, conn) -> List[str]:
        return await self.db.get_usuarios_activos_nombres(conn)

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
        # Reusa el lookup de proyecto ya existente (core/transfers) en vez de una query nueva:
        # p.* + nombre_proyecto/cliente_nombre cubren lo que necesita el header del modal.
        proyecto = await self.get_proyecto_detalle(conn, id_proyecto)
        asignaciones = await self.db.get_asignaciones_equipo(conn, id_proyecto)

        # RC/RI persistido por proyecto (modelo cerrado, decision 3). Solo se muestra
        # si hay una fila activa en tb_proyecto_usuarios; sin ella el campo queda vacio.
        # La auto-asignacion ocurre en save_equipo_proyecto al asignar el primer ingeniero
        # o coordinador — no se infiere un default aqui para evitar confusion en el modal.
        jefes_rows = await self.db.get_jefes_organizacionales(conn)
        jefes_ingenieria = [j for j in jefes_rows if j["rol_organizacional"] == "jefe_ingenieria"]
        jefes_construccion = [j for j in jefes_rows if j["rol_organizacional"] == "jefe_construccion"]
        jefes_compras = [j for j in jefes_rows if j["rol_organizacional"] == "jefe_compras"]

        def _slim(usuario):
            return {"id_usuario": usuario["id_usuario"], "nombre": usuario["nombre"]} if usuario else None

        def _responsable(rol_proyecto):
            row = next((a for a in asignaciones if a["rol_proyecto"] == rol_proyecto), None)
            if row:
                return {"id_usuario": row["id_usuario"], "nombre": row["nombre_usuario"]}
            return None

        jefe_ingenieria = _responsable("responsable_ingenieria")
        jefe_construccion = _responsable("responsable_construccion")
        jefe_compras = _responsable("responsable_compras")

        # El RC/RI actual debe poder preseleccionarse en el selector de reasignacion
        # aunque ya no sea jefe activo (no estaria en jefes_*); lo agregamos si falta.
        def _con_responsable(jefes, responsable):
            jefes = [_slim(j) for j in jefes]
            if responsable and not any(str(j["id_usuario"]) == str(responsable["id_usuario"]) for j in jefes):
                jefes.append(responsable)
            return jefes

        jefes_ingenieria = _con_responsable(jefes_ingenieria, jefe_ingenieria)
        jefes_construccion = _con_responsable(jefes_construccion, jefe_construccion)
        jefes_compras = _con_responsable(jefes_compras, jefe_compras)

        # Usuarios activos filtrados por departamento (via slug de tb_cat_departamentos)
        dept_rows = await self.db.get_usuarios_por_departamentos(
            conn, ["ingenieria", "construccion", "oym", "compras"]
        )

        usuarios_ingenieria = [r for r in dept_rows if r["dept_slug"] == "ingenieria"]
        usuarios_construccion = [r for r in dept_rows if r["dept_slug"] == "construccion"]
        usuarios_oym = [r for r in dept_rows if r["dept_slug"] == "oym"]
        usuarios_compras = [r for r in dept_rows if r["dept_slug"] == "compras"]

        return {
            "proyecto": proyecto,
            "asignaciones": asignaciones,
            "jefe_ingenieria": jefe_ingenieria,
            "jefe_construccion": jefe_construccion,
            "jefe_compras": jefe_compras,
            "jefes_ingenieria": jefes_ingenieria,
            "jefes_construccion": jefes_construccion,
            "jefes_compras": jefes_compras,
            "usuarios_ingenieria": usuarios_ingenieria,
            "usuarios_construccion": usuarios_construccion,
            "usuarios_oym": usuarios_oym,
            "usuarios_compras": usuarios_compras,
        }

    async def save_equipo_proyecto(
        self,
        conn,
        id_proyecto: UUID,
        asignaciones: List[Dict],
        asignado_por_id: UUID,
        permisos: Dict[str, bool],
        context: Optional[Dict] = None,
        responsables_explicitos: Optional[Dict[str, Optional[UUID]]] = None,
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

        if responsables_explicitos and not permisos.get("puede_reasignar_responsable"):
            raise ValueError("Solo Direccion puede reasignar al responsable")

        async with conn.transaction():
            areas_tocadas = {
                area
                for (rol, area) in asignaciones_por_rol
                if permisos.get(PERMISO_POR_ROL[(rol, area)])
            }
            areas_tocadas.update(responsables_explicitos)

            activas_por_area = {
                area: await self.db.get_asignaciones_activas_area(conn, id_proyecto, area)
                for area in sorted(areas_tocadas)
            }
            deseadas_por_area = {
                area: {row["rol_proyecto"]: row["id_usuario"] for row in rows}
                for area, rows in activas_por_area.items()
            }
            roles_gestionados = {area: set() for area in areas_tocadas}

            for key, item in asignaciones_por_rol.items():
                permiso = PERMISO_POR_ROL[key]
                if not permisos.get(permiso):
                    continue
                rol, area = key
                id_usuario = item.get("id_usuario")
                if id_usuario:
                    dept_slug = DEPARTAMENTO_POR_ROL[key]
                    usuario_valido = await self.db.usuario_activo_en_departamento(
                        conn, id_usuario, dept_slug
                    )
                    if not usuario_valido:
                        raise ValueError(
                            "El usuario seleccionado no pertenece al departamento requerido"
                        )
                deseadas_por_area[area][rol] = id_usuario
                roles_gestionados[area].add(rol)

            for area, responsable_id in responsables_explicitos.items():
                if area not in RESPONSABLE_POR_AREA:
                    raise ValueError("Area invalida")
                rol_resp, rol_jefe = RESPONSABLE_POR_AREA[area]
                if responsable_id is not None and not await self.db.usuario_tiene_rol_organizacional(
                    conn, responsable_id, rol_jefe
                ):
                    raise ValueError(f"El responsable indicado no tiene el rol {rol_jefe}")
                deseadas_por_area[area][rol_resp] = responsable_id
                roles_gestionados[area].add(rol_resp)

            for key, area in ROL_EDITABLE_DEFINE_RESPONSABLE.items():
                if key not in asignaciones_por_rol or not permisos.get(PERMISO_POR_ROL[key]):
                    continue
                id_operativo = asignaciones_por_rol[key].get("id_usuario")
                rol_resp, _ = RESPONSABLE_POR_AREA[area]
                if not id_operativo or area in responsables_explicitos:
                    continue
                if not deseadas_por_area[area].get(rol_resp):
                    responsable_existente = await self.db.get_responsable_proyecto(
                        conn, id_proyecto, area
                    )
                    if responsable_existente:
                        deseadas_por_area[area][rol_resp] = responsable_existente
                    else:
                        responsable_inicial = await self._resolver_responsable_inicial(
                            conn, area, asignado_por_id, context
                        )
                        if responsable_inicial:
                            deseadas_por_area[area][rol_resp] = responsable_inicial
                            roles_gestionados[area].add(rol_resp)

            for area, deseadas in deseadas_por_area.items():
                roles_por_usuario = {}
                for rol, id_usuario in deseadas.items():
                    if id_usuario is None:
                        continue
                    usuario_key = str(id_usuario)
                    roles_existentes = roles_por_usuario.setdefault(usuario_key, [])
                    roles_resultantes = {*roles_existentes, rol}
                    if (
                        len(roles_resultantes) > 1
                        and roles_resultantes
                        != ROLES_COMPATIBLES_MISMO_USUARIO.get(area, frozenset())
                    ):
                        raise ValueError(
                            _msg_rol_duplicado_area(area, roles_existentes[0])
                        )
                    roles_existentes.append(rol)

            cambios = []
            for area, roles in roles_gestionados.items():
                actuales = {
                    row["rol_proyecto"]: row["id_usuario"]
                    for row in activas_por_area[area]
                }
                for rol in roles:
                    actual = actuales.get(rol)
                    deseada = deseadas_por_area[area].get(rol)
                    if str(actual or "") != str(deseada or ""):
                        cambios.append((area, rol, deseada))

            # Desactivar primero permite intercambiar dos personas entre roles sin
            # chocar temporalmente con la unicidad por usuario+area.
            for area, rol, _ in sorted(cambios, key=lambda row: (row[0], row[1])):
                await self.db.desactivar_asignacion_equipo(conn, id_proyecto, rol, area)

            for area, rol, id_usuario in sorted(cambios, key=lambda row: (row[0], row[1])):
                if id_usuario:
                    await self._insertar_asignacion_segura(
                        conn, id_proyecto, id_usuario, rol, area, asignado_por_id
                    )

        logger.info("Equipo actualizado para proyecto %s por usuario %s", id_proyecto, asignado_por_id)

    async def _resolver_responsable_inicial(
        self, conn, area: str, asignado_por_id: UUID, context: Dict
    ) -> Optional[UUID]:
        """Resuelve la autoasignacion inicial de RC/RI sin escribir en BD."""
        _, rol_jefe = RESPONSABLE_POR_AREA[area]
        es_admin = context.get("role") == "ADMIN"
        rol_org = (context.get("rol_organizacional") or "").strip().lower()
        es_director = rol_org == "director"
        if es_admin or es_director or rol_org != rol_jefe:
            return None
        autoasignacion = await ConfigService.get_global_config(
            conn, "equipo.autoasignacion_rc_por_jefes", True, bool
        )
        if autoasignacion:
            return asignado_por_id
        return None

    async def _insertar_asignacion_segura(
        self, conn, id_proyecto: UUID, id_usuario: UUID, rol_proyecto: str,
        area: str, asignado_por_id: UUID,
    ) -> None:
        """Inserta con savepoint y traduce de forma uniforme las dos carreras posibles."""
        try:
            async with conn.transaction():
                await self.db.insertar_asignacion_equipo(
                    conn, id_proyecto, id_usuario, rol_proyecto, area, asignado_por_id
                )
        except asyncpg.UniqueViolationError as exc:
            if exc.constraint_name == "uq_proyecto_rol_area_activo":
                raise ValueError(_msg_rol_tomado_por_otro(area)) from exc
            raise ValueError(
                _msg_usuario_ya_tiene_rol_activo(area, rol_proyecto)
            ) from exc

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
                await self._insertar_asignacion_segura(
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
                "puede_asignar_compras": True,
                "puede_reasignar_responsable": True,
                "puede_ver_modal": True,
            }

        responsables = await self.db.get_responsables_proyecto(
            conn, id_proyecto, list(RESPONSABLE_POR_AREA)
        )
        rc_id = responsables.get("CONSTRUCCION")
        ri_id = responsables.get("INGENIERIA")
        r_compras_id = responsables.get("COMPRAS")
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
            "puede_asignar_compras": _puede_gestionar(r_compras_id, rol_org == "jefe_compras"),
            "puede_reasignar_responsable": es_admin or es_director,
            "puede_ver_modal": True,
        }


def get_service() -> ProyectosService:
    return ProyectosService()
