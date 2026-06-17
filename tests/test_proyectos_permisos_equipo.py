from uuid import uuid4
import pytest

from modules.proyectos.service import ProyectosService


async def _async_value(v):
    return v


class FakeDB:
    def __init__(self, rc=None, ri=None, dept_slug=None):
        self.rc, self.ri, self.dept_slug = rc, ri, dept_slug

    async def get_responsable_proyecto(self, conn, id_proyecto, area):
        return self.rc if area == "CONSTRUCCION" else self.ri

    async def get_department_slug(self, conn, department):
        return self.dept_slug


@pytest.fixture(autouse=True)
def _cfg(monkeypatch):
    from core.config_service import ConfigService
    monkeypatch.setattr(ConfigService, "get_global_config", classmethod(
        lambda cls, conn, clave, default, tipo=str: _async_value(default)))


@pytest.mark.asyncio
async def test_jefe_puede_tomar_proyecto_sin_rc():
    service = ProyectosService()
    service.db = FakeDB(rc=None)
    permisos = await service.permisos_equipo(
        None, {"role": "USER", "rol_organizacional": "jefe_construccion", "user_db_id": uuid4()}, uuid4()
    )
    assert permisos["puede_asignar_construccion"] is True


@pytest.mark.asyncio
async def test_jefe_par_no_gestiona_proyecto_ajeno():
    rc_id = uuid4()
    otro_jefe = uuid4()
    service = ProyectosService()
    service.db = FakeDB(rc=rc_id)
    permisos = await service.permisos_equipo(
        None, {"role": "USER", "rol_organizacional": "jefe_construccion", "user_db_id": otro_jefe}, uuid4()
    )
    assert permisos["puede_asignar_construccion"] is False


@pytest.mark.asyncio
async def test_rc_actual_gestiona_su_proyecto():
    rc_id = uuid4()
    service = ProyectosService()
    service.db = FakeDB(rc=rc_id)
    permisos = await service.permisos_equipo(
        None, {"role": "USER", "rol_organizacional": "jefe_construccion", "user_db_id": rc_id}, uuid4()
    )
    assert permisos["puede_asignar_construccion"] is True


@pytest.mark.asyncio
async def test_director_reasigna_responsable():
    service = ProyectosService()
    service.db = FakeDB(rc=uuid4())
    permisos = await service.permisos_equipo(
        None, {"role": "USER", "rol_organizacional": "director", "user_db_id": uuid4()}, uuid4()
    )
    assert permisos["puede_reasignar_responsable"] is True
    assert permisos["puede_asignar_construccion"] is True
