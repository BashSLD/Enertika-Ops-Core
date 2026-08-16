from uuid import uuid4
import pytest

from modules.proyectos.service import ProyectosService


async def _async_value(v):
    return v


class FakeDB:
    def __init__(self, rc=None, ri=None, compras=None, dept_slug=None):
        self.rc, self.ri, self.compras, self.dept_slug = rc, ri, compras, dept_slug

    async def get_responsable_proyecto(self, conn, id_proyecto, area):
        if area == "CONSTRUCCION":
            return self.rc
        if area == "COMPRAS":
            return self.compras
        return self.ri

    async def get_responsables_proyecto(self, conn, id_proyecto, areas):
        valores = {"CONSTRUCCION": self.rc, "INGENIERIA": self.ri, "COMPRAS": self.compras}
        return {area: valores[area] for area in areas if valores.get(area) is not None}

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


@pytest.mark.asyncio
async def test_jefe_compras_puede_tomar_proyecto_sin_responsable():
    service = ProyectosService()
    service.db = FakeDB(compras=None)
    permisos = await service.permisos_equipo(
        None, {"role": "USER", "rol_organizacional": "jefe_compras", "user_db_id": uuid4()}, uuid4()
    )
    assert permisos["puede_asignar_compras"] is True


@pytest.mark.asyncio
async def test_jefe_compras_par_no_gestiona_proyecto_ajeno():
    compras_id = uuid4()
    otro_jefe = uuid4()
    service = ProyectosService()
    service.db = FakeDB(compras=compras_id)
    permisos = await service.permisos_equipo(
        None, {"role": "USER", "rol_organizacional": "jefe_compras", "user_db_id": otro_jefe}, uuid4()
    )
    assert permisos["puede_asignar_compras"] is False


@pytest.mark.asyncio
async def test_responsable_compras_actual_gestiona_su_proyecto():
    compras_id = uuid4()
    service = ProyectosService()
    service.db = FakeDB(compras=compras_id)
    permisos = await service.permisos_equipo(
        None, {"role": "USER", "rol_organizacional": "jefe_compras", "user_db_id": compras_id}, uuid4()
    )
    assert permisos["puede_asignar_compras"] is True


@pytest.mark.asyncio
async def test_admin_tiene_puede_asignar_compras():
    service = ProyectosService()
    service.db = FakeDB()
    permisos = await service.permisos_equipo(
        None, {"role": "ADMIN", "rol_organizacional": "", "user_db_id": uuid4()}, uuid4()
    )
    assert permisos["puede_asignar_compras"] is True
