from uuid import uuid4

import pytest

from modules.proyectos.service import ProyectosService


async def _async_value(v):
    return v


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeConn:
    def transaction(self):
        return FakeTransaction()


class FakeProyectosDB:
    def __init__(self, asignacion_actual=None, responsable=None, jefes=None):
        self.asignacion_actual = asignacion_actual
        self.responsable = responsable  # id del RC/RI ya definido (o None)
        self.jefes = jefes or {}        # {id_usuario: rol_organizacional}
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

    async def get_responsable_proyecto(self, conn, id_proyecto, area):
        return self.responsable

    async def usuario_tiene_rol_organizacional(self, conn, id_usuario, rol):
        return self.jefes.get(id_usuario) == rol


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
    fake_db = FakeProyectosDB(
        asignacion_actual={"id_usuario": id_usuario_anterior},
        responsable=uuid4(),  # RC/RI ya existe -> _asegurar_responsable retorna temprano
    )
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


@pytest.mark.asyncio
async def test_autoasigna_rc_al_jefe_que_asigna_coordinador(monkeypatch):
    from core.config_service import ConfigService

    monkeypatch.setattr(ConfigService, "get_global_config", classmethod(
        lambda cls, conn, clave, default, tipo=str: _async_value(default)))

    id_proyecto = uuid4()
    id_coord = uuid4()
    id_jefe = uuid4()
    service = ProyectosService()
    service.db = FakeProyectosDB(responsable=None, jefes={id_jefe: "jefe_construccion"})

    await service.save_equipo_proyecto(
        FakeConn(),
        id_proyecto,
        [{"rol_proyecto": "coordinador_obra", "area": "CONSTRUCCION", "id_usuario": id_coord}],
        id_jefe,
        {"puede_asignar_ingenieria": False, "puede_asignar_construccion": True, "puede_asignar_oym": False},
        context={"role": "USER", "rol_organizacional": "jefe_construccion"},
    )

    assert (id_proyecto, id_coord, "coordinador_obra", "CONSTRUCCION", id_jefe) in service.db.insertadas
    assert (id_proyecto, id_jefe, "responsable_construccion", "CONSTRUCCION", id_jefe) in service.db.insertadas


@pytest.mark.asyncio
async def test_no_cambia_rc_existente_al_rotar_coordinador(monkeypatch):
    from core.config_service import ConfigService
    monkeypatch.setattr(ConfigService, "get_global_config", classmethod(
        lambda cls, conn, clave, default, tipo=str: _async_value(default)))

    id_proyecto = uuid4()
    id_coord_nuevo = uuid4()
    id_jefe_b = uuid4()
    id_rc_existente = uuid4()
    service = ProyectosService()
    service.db = FakeProyectosDB(
        asignacion_actual={"id_usuario": uuid4()},
        responsable=id_rc_existente,
        jefes={id_jefe_b: "jefe_construccion"},
    )

    await service.save_equipo_proyecto(
        FakeConn(),
        id_proyecto,
        [{"rol_proyecto": "coordinador_obra", "area": "CONSTRUCCION", "id_usuario": id_coord_nuevo}],
        id_jefe_b,
        {"puede_asignar_ingenieria": False, "puede_asignar_construccion": True, "puede_asignar_oym": False},
        context={"role": "USER", "rol_organizacional": "jefe_construccion"},
    )

    roles_insertados = [r[2] for r in service.db.insertadas]
    assert "responsable_construccion" not in roles_insertados  # no se redefine el RC
