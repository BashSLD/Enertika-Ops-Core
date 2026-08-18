"""
Tests del bloqueo de fallback alfabetico RC/RI al crear un paquete BOM
(_Planes_Activos/._BOOM/02-resolucion-responsables-rcri.md): si el proyecto no tiene RC/RI
persistido y hay 2+ jefes activos del area, crear_paquete debe rechazar (via estricto=True en
get_responsable_proyecto_o_global) en vez de autoasignar el primero alfabeticamente.
"""

from uuid import uuid4

import pytest

from core.bom.service import BomService


class _AvanzoSinBloquear(Exception):
    """Sentinela: el guard de RC/RI ambiguo no bloqueo, la ejecucion siguio de largo."""


def _usuario():
    return {"id_usuario": uuid4(), "nombre": "Jefe Uno", "email": "jefe@enertika.mx"}


class FakeDB:
    def __init__(self, ambiguo_ingenieria=False, ambiguo_construccion=False):
        self.ambiguo = {
            "jefe_ingenieria": ambiguo_ingenieria,
            "jefe_construccion": ambiguo_construccion,
        }

    async def get_proyecto_info(self, conn, id_proyecto):
        return {"id_proyecto": id_proyecto}

    async def get_responsable_proyecto_o_global(
        self, conn, id_proyecto, rol_organizacional, estricto=False
    ):
        if estricto and self.ambiguo.get(rol_organizacional):
            raise ValueError(f"Hay mas de un usuario activo con rol '{rol_organizacional}'")
        return _usuario()

    async def get_asignacion_proyecto(self, conn, id_proyecto, rol_proyecto, area):
        raise _AvanzoSinBloquear("paso el guard de RC/RI sin bloquear")


class FakeConn:
    pass


def make_service(**ambiguos):
    db = FakeDB(**ambiguos)
    svc = BomService()
    svc.db = db
    return svc


@pytest.mark.asyncio
async def test_bloquea_si_hay_2_jefes_ingenieria_sin_rcri_persistido():
    svc = make_service(ambiguo_ingenieria=True)
    with pytest.raises(ValueError, match="Ingeniería"):
        await svc.crear_paquete(
            FakeConn(), uuid4(), uuid4(), "COMPLETO", "Paquete X",
            user_role="ADMIN", aceptar_responsabilidad=True,
            clave_idempotencia="clave-1",
        )


@pytest.mark.asyncio
async def test_bloquea_si_hay_2_jefes_construccion_sin_rcri_persistido():
    svc = make_service(ambiguo_construccion=True)
    with pytest.raises(ValueError, match="Construcción"):
        await svc.crear_paquete(
            FakeConn(), uuid4(), uuid4(), "COMPLETO", "Paquete X",
            user_role="ADMIN", aceptar_responsabilidad=True,
            clave_idempotencia="clave-2",
        )


@pytest.mark.asyncio
async def test_no_bloquea_sin_ambiguedad():
    svc = make_service()
    with pytest.raises(_AvanzoSinBloquear):
        await svc.crear_paquete(
            FakeConn(), uuid4(), uuid4(), "COMPLETO", "Paquete X",
            user_role="ADMIN", aceptar_responsabilidad=True,
            clave_idempotencia="clave-3",
        )
