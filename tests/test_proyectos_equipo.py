from uuid import uuid4

import asyncpg
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
    def __init__(self, asignacion_actual=None, responsable=None, jefes=None,
                 asignaciones_equipo=None, jefes_org=None, dept_users=None,
                 activas_area=None, error_insertar=None):
        self.asignacion_actual = asignacion_actual
        self.responsable = responsable  # id del RC/RI ya definido (o None)
        self.jefes = jefes or {}        # {id_usuario: rol_organizacional}
        self.asignaciones_equipo = asignaciones_equipo or []
        self.jefes_org = jefes_org or []
        self.dept_users = dept_users or []
        # Lista completa de asignaciones activas del area (varios roles a la vez).
        # Si no se especifica, se deriva de asignacion_actual para compatibilidad
        # con los tests que solo simulan un unico rol activo.
        self.activas_area = activas_area
        # Excepcion a lanzar desde insertar_asignacion_equipo (simula la carrera
        # check-then-insert sobre uq_proyecto_usuario_area_activo/uq_proyecto_rol_area_activo).
        self.error_insertar = error_insertar
        self.desactivadas = []
        self.insertadas = []

    async def get_asignaciones_equipo(self, conn, id_proyecto):
        return self.asignaciones_equipo

    async def get_jefes_organizacionales(self, conn):
        return self.jefes_org

    async def get_usuarios_por_departamentos(self, conn, slugs):
        return self.dept_users

    async def usuario_activo_en_departamento(self, conn, id_usuario, dept_slug):
        return True

    async def get_asignaciones_activas_area(self, conn, id_proyecto, area):
        if self.activas_area is not None:
            return self.activas_area
        return [self.asignacion_actual] if self.asignacion_actual else []

    async def desactivar_asignacion_equipo(self, conn, id_proyecto, rol_proyecto, area):
        self.desactivadas.append((id_proyecto, rol_proyecto, area))

    async def insertar_asignacion_equipo(
        self, conn, id_proyecto, id_usuario, rol_proyecto, area, asignado_por_id
    ):
        if self.error_insertar is not None:
            raise self.error_insertar
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
    fake_db = FakeProyectosDB(
        asignacion_actual={"id_usuario": id_usuario, "rol_proyecto": "ingeniero_asignado"}
    )
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
        asignacion_actual={"id_usuario": id_usuario_anterior, "rol_proyecto": "ingeniero_asignado"},
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
async def test_save_equipo_rechaza_usuario_con_otro_rol_activo_en_area():
    id_proyecto = uuid4()
    id_usuario = uuid4()
    asignado_por_id = uuid4()
    service = ProyectosService()
    fake_db = FakeProyectosDB(
        activas_area=[{"id_usuario": id_usuario, "rol_proyecto": "responsable_ingenieria"}],
    )
    service.db = fake_db

    with pytest.raises(ValueError, match="Responsable de Ingeniería"):
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

    assert fake_db.insertadas == []


@pytest.mark.asyncio
async def test_save_equipo_traduce_carrera_mismo_usuario_otro_rol():
    id_proyecto = uuid4()
    id_usuario = uuid4()
    asignado_por_id = uuid4()
    service = ProyectosService()
    error = asyncpg.UniqueViolationError("duplicate key value")
    error.constraint_name = "uq_proyecto_usuario_area_activo"
    fake_db = FakeProyectosDB(error_insertar=error)
    service.db = fake_db

    with pytest.raises(ValueError, match="ya tiene un rol activo"):
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


@pytest.mark.asyncio
async def test_save_equipo_traduce_carrera_mismo_rol_otro_usuario():
    id_proyecto = uuid4()
    id_usuario = uuid4()
    asignado_por_id = uuid4()
    service = ProyectosService()
    error = asyncpg.UniqueViolationError("duplicate key value")
    error.constraint_name = "uq_proyecto_rol_area_activo"
    fake_db = FakeProyectosDB(error_insertar=error)
    service.db = fake_db

    with pytest.raises(ValueError, match="Otro usuario acaba de tomar este rol"):
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
        asignacion_actual={"id_usuario": uuid4(), "rol_proyecto": "coordinador_obra"},
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


@pytest.mark.asyncio
async def test_admin_asigna_coordinador_sin_rc_no_aborta(monkeypatch):
    from core.config_service import ConfigService
    monkeypatch.setattr(ConfigService, "get_global_config", classmethod(
        lambda cls, conn, clave, default, tipo=str: _async_value(default)))

    id_proyecto = uuid4()
    id_coord = uuid4()
    id_admin = uuid4()
    service = ProyectosService()
    service.db = FakeProyectosDB(responsable=None)

    await service.save_equipo_proyecto(
        FakeConn(),
        id_proyecto,
        [{"rol_proyecto": "coordinador_obra", "area": "CONSTRUCCION", "id_usuario": id_coord}],
        id_admin,
        {"puede_asignar_ingenieria": True, "puede_asignar_construccion": True, "puede_asignar_oym": True},
        context={"role": "ADMIN", "rol_organizacional": ""},
    )

    roles = [r[2] for r in service.db.insertadas]
    assert "coordinador_obra" in roles               # el coordinador se guarda
    assert "responsable_construccion" not in roles   # ADMIN no autodefine el RC (sin abortar)


@pytest.mark.asyncio
async def test_autoasignacion_off_no_aborta_guardado(monkeypatch):
    from core.config_service import ConfigService
    monkeypatch.setattr(ConfigService, "get_global_config", classmethod(
        lambda cls, conn, clave, default, tipo=str: _async_value(False)))

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

    roles = [r[2] for r in service.db.insertadas]
    assert "coordinador_obra" in roles               # se guarda sin abortar
    assert "responsable_construccion" not in roles   # autoasignacion off -> no RC


@pytest.mark.asyncio
async def test_get_equipo_muestra_rc_persistido_aunque_no_sea_jefe_activo():
    id_proyecto = uuid4()
    id_rc = uuid4()           # RC persistido que ya no figura como jefe activo
    id_jefe_activo = uuid4()
    service = ProyectosService()
    service.db = FakeProyectosDB(
        asignaciones_equipo=[
            {"rol_proyecto": "responsable_construccion", "area": "CONSTRUCCION",
             "id_usuario": id_rc, "nombre_usuario": "RC Persistido"},
        ],
        jefes_org=[
            {"id_usuario": id_jefe_activo, "nombre": "Jefe Activo",
             "rol_organizacional": "jefe_construccion"},
        ],
    )

    data = await service.get_equipo_proyecto(FakeConn(), id_proyecto)

    # Se muestra el RC persistido (desde la asignacion), no el jefe activo por defecto
    assert data["jefe_construccion"] == {"id_usuario": id_rc, "nombre": "RC Persistido"}
    # El RC persistido esta entre las opciones del selector, para poder preseleccionarse
    ids = [str(j["id_usuario"]) for j in data["jefes_construccion"]]
    assert str(id_rc) in ids
    assert str(id_jefe_activo) in ids


@pytest.mark.asyncio
async def test_get_equipo_sin_responsable_persistido_queda_vacio():
    id_proyecto = uuid4()
    id_jefe = uuid4()
    service = ProyectosService()
    service.db = FakeProyectosDB(
        asignaciones_equipo=[],   # sin RC/RI persistido
        jefes_org=[
            {"id_usuario": id_jefe, "nombre": "Jefe Ing",
             "rol_organizacional": "jefe_ingenieria"},
        ],
    )

    data = await service.get_equipo_proyecto(FakeConn(), id_proyecto)

    # Sin RI persistido el campo queda vacio; el jefe organizacional sigue siendo opcion.
    assert data["jefe_ingenieria"] is None
    assert data["jefe_construccion"] is None   # no hay jefe_construccion configurado
    assert data["jefes_ingenieria"] == [{"id_usuario": id_jefe, "nombre": "Jefe Ing"}]
