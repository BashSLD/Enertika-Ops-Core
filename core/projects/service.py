# Archivo: core/projects/service.py
"""
Servicio compartido para gestion de Proyectos Gate.
Usado por: Compras, Construccion, y futuros modulos.
"""

from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4
import logging

from core.timezone import now_mx
from .db_service import ProjectsGateDBService, get_projects_gate_db_service

logger = logging.getLogger("ProjectsService")


class ProjectsGateService:
    """
    Logica de negocio para creacion y gestion de proyectos Gate.

    Un proyecto Gate se crea cuando una oportunidad es GANADA y
    necesita pasar a fases de ejecucion: Ingenieria, Construccion y O&M.
    """

    def __init__(self, db: ProjectsGateDBService | None = None):
        self.db = db or get_projects_gate_db_service()

    async def _get_estatus_ganada_id(self, conn) -> int:
        estatus_id = await self.db.get_estatus_ganada_id(conn)
        if not estatus_id:
            raise ValueError("El estatus Ganada no esta configurado en el catalogo")
        return estatus_id

    async def get_sitios_ganados_sin_proyecto(self, conn) -> List[Dict[str, Any]]:
        estatus_ganada_id = await self._get_estatus_ganada_id(conn)
        return await self.db.get_sitios_ganados_sin_proyecto(conn, estatus_ganada_id)

    async def get_oportunidades_ganadas(self, conn) -> List[Dict[str, Any]]:
        """Compatibilidad: retorna sitios ganados sin proyecto."""
        return await self.get_sitios_ganados_sin_proyecto(conn)

    async def get_tecnologias(self, conn) -> List[Dict[str, Any]]:
        return await self.db.get_tecnologias(conn)

    async def validar_consecutivo_unico(self, conn, consecutivo: int) -> bool:
        return not await self.db.consecutivo_exists(conn, consecutivo)

    async def generar_proyecto_id_estandar(
        self,
        prefijo: str,
        consecutivo: int,
        tecnologia_nombre: str,
        nombre_corto: str,
    ) -> str:
        return f"{prefijo}-{consecutivo}-{tecnologia_nombre} {nombre_corto}".strip()

    async def crear_proyecto(
        self,
        conn,
        id_sitio: UUID,
        prefijo: str,
        consecutivo: int,
        id_tecnologia: int,
        nombre_corto: str,
        user_id: UUID,
    ) -> Dict[str, Any]:
        estatus_ganada_id = await self._get_estatus_ganada_id(conn)

        sitio = await self.db.get_sitio_para_proyecto(conn, id_sitio)
        if not sitio:
            raise LookupError("Sitio no encontrado")

        if sitio["id_estatus_global"] != estatus_ganada_id:
            raise ValueError("Solo se pueden crear proyectos de sitios GANADOS")

        if sitio["oportunidad_estatus"] != estatus_ganada_id:
            raise ValueError("La oportunidad padre no esta en estatus GANADA")

        if await self.db.proyecto_exists_for_sitio(conn, id_sitio):
            raise ValueError("Ya existe un proyecto para este sitio")

        if not await self.validar_consecutivo_unico(conn, consecutivo):
            raise ValueError(f"El consecutivo {consecutivo} ya esta en uso")

        tecnologia_nombre = await self.db.get_tecnologia_nombre(conn, id_tecnologia)
        if not tecnologia_nombre:
            raise ValueError("Tecnologia no valida")

        nombre_sitio_snapshot = (sitio["nombre_sitio"] or "").strip()
        if not nombre_sitio_snapshot:
            raise ValueError("El sitio no tiene un nombre valido para crear proyecto")

        prefijo_normalizado = prefijo.strip().upper()
        proyecto_id_estandar = await self.generar_proyecto_id_estandar(
            prefijo_normalizado,
            consecutivo,
            tecnologia_nombre,
            nombre_sitio_snapshot,
        )

        if await self.db.proyecto_id_estandar_exists(conn, proyecto_id_estandar):
            raise ValueError(f"Ya existe un proyecto con ID {proyecto_id_estandar}")

        new_id = uuid4()
        now = now_mx()

        await self.db.insert_proyecto_gate(
            conn,
            {
                "id_proyecto": new_id,
                "id_oportunidad": sitio["id_oportunidad"],
                "id_sitio": id_sitio,
                "proyecto_id_estandar": proyecto_id_estandar,
                "status_fase": "INGENIERIA",
                "aprobacion_direccion": True,
                "fecha_aprobacion": now,
                "prefijo": prefijo_normalizado,
                "consecutivo": consecutivo,
                "id_tecnologia": id_tecnologia,
                "nombre_corto": nombre_sitio_snapshot,
                "created_at": now,
                "created_by_id": user_id,
            },
        )

        logger.info("Proyecto creado: %s por usuario %s", proyecto_id_estandar, user_id)
        return await self.get_proyecto_by_id(conn, new_id)

    async def get_proyecto_by_id(
        self,
        conn,
        id_proyecto: UUID,
    ) -> Optional[Dict[str, Any]]:
        return await self.db.get_proyecto_by_id(conn, id_proyecto)

    async def get_proyectos_list(
        self,
        conn,
        solo_aprobados: bool = True,
    ) -> List[Dict[str, Any]]:
        return await self.db.get_proyectos_list(conn, solo_aprobados)

    async def get_siguiente_consecutivo_sugerido(self, conn) -> int:
        return await self.db.get_siguiente_consecutivo_sugerido(conn)


def get_projects_gate_service():
    """Dependency injection para FastAPI."""
    return ProjectsGateService()
