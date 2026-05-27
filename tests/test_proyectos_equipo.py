from uuid import uuid4

import pytest

from modules.proyectos.service import ProyectosService


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeConn:
    def transaction(self):
        return FakeTransaction()


class FakeProyectosDB:
    def __init__(self, asignacion_actual=None):
        self.asignacion_actual = asignacion_actual
        self.desactivadas = []
        self.insertadas = []

    async def usuario_activo_en_departamento(self, conn, id_usuario, dept_slug):
        return True

    async def get_asignacion_equipo_actual(self, conn, id_proyecto, rol_proyecto, area):
        return self.asignacion_actual

    async def desactivar_asignacion_equipo(self, conn, id_proyecto, rol_proyecto, area):
        self.desactivadas.append((id_proyecto, rol_proyecto, area))

    async def insertar_asignacion_equipo(
        self, conn, id_proyecto, id_usuario, rol_proyecto, area, asignado_por_id
    ):
        self.insertadas.append(
            (id_proyecto, id_usuario, rol_proyecto, area, asignado_por_id)
        )


@pytest.mark.asyncio
async def test_save_equipo_no_reinserta_si_el_usuario_no_cambia():
    id_proyecto = uuid4()
    id_usuario = uuid4()
    asignado_por_id = uuid4()
    service = ProyectosService()
    fake_db = FakeProyectosDB(asignacion_actual={"id_usuario": id_usuario})
    service.db = fake_db

    await service.save_equipo_proyecto(
        FakeConn(),
        id_proyecto,
        [
            {
                "rol_proyecto": "ingeniero_asignado",
                "area": "INGENIERIA",
                "id_usuario": id_usuario,
            }
        ],
        asignado_por_id,
        {
            "puede_asignar_ingenieria": True,
            "puede_asignar_construccion": False,
            "puede_asignar_oym": False,
        },
    )

    assert fake_db.desactivadas == []
    assert fake_db.insertadas == []


@pytest.mark.asyncio
async def test_save_equipo_desactiva_e_inserta_si_el_usuario_cambia():
    id_proyecto = uuid4()
    id_usuario_anterior = uuid4()
    id_usuario_nuevo = uuid4()
    asignado_por_id = uuid4()
    service = ProyectosService()
    fake_db = FakeProyectosDB(asignacion_actual={"id_usuario": id_usuario_anterior})
    service.db = fake_db

    await service.save_equipo_proyecto(
        FakeConn(),
        id_proyecto,
        [
            {
                "rol_proyecto": "ingeniero_asignado",
                "area": "INGENIERIA",
                "id_usuario": id_usuario_nuevo,
            }
        ],
        asignado_por_id,
        {
            "puede_asignar_ingenieria": True,
            "puede_asignar_construccion": False,
            "puede_asignar_oym": False,
        },
    )

    assert fake_db.desactivadas == [
        (id_proyecto, "ingeniero_asignado", "INGENIERIA")
    ]
    assert fake_db.insertadas == [
        (
            id_proyecto,
            id_usuario_nuevo,
            "ingeniero_asignado",
            "INGENIERIA",
            asignado_por_id,
        )
    ]
