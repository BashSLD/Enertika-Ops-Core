import pytest
from unittest.mock import AsyncMock
from uuid import uuid4

from modules.cfe.service import CfeService


def _svc_con_db():
    return CfeService(db=AsyncMock())


@pytest.mark.asyncio
async def test_resolver_simulacion_usuario_filtra_por_registrados(mock_conn):
    svc = _svc_con_db()
    ids = [uuid4(), uuid4()]
    svc.db.get_servicio_ids_visibles = AsyncMock(return_value=ids)
    user = {"user_db_id": uuid4(), "role": "USER", "module_roles": {"simulacion": "viewer"}}

    creado_por_ids, servicio_ids = await svc.resolver_filtro_visibilidad(mock_conn, user, "simulacion")

    assert creado_por_ids is None
    assert servicio_ids == ids


@pytest.mark.asyncio
async def test_resolver_simulacion_sin_registros_ve_nada(mock_conn):
    # [] (no None): filtro estricto, el usuario no ve ningun servicio.
    svc = _svc_con_db()
    svc.db.get_servicio_ids_visibles = AsyncMock(return_value=[])
    user = {"user_db_id": uuid4(), "role": "USER", "module_roles": {"simulacion": "editor"}}

    creado_por_ids, servicio_ids = await svc.resolver_filtro_visibilidad(mock_conn, user, "simulacion")

    assert creado_por_ids is None
    assert servicio_ids == []


@pytest.mark.asyncio
async def test_resolver_simulacion_admin_ve_todo(mock_conn, manager_context):
    # manager_context tiene module_roles {"simulacion": "admin"}.
    svc = _svc_con_db()
    svc.db.get_servicio_ids_visibles = AsyncMock(return_value=[])

    creado_por_ids, servicio_ids = await svc.resolver_filtro_visibilidad(mock_conn, manager_context, "simulacion")

    assert (creado_por_ids, servicio_ids) == (None, None)
    svc.db.get_servicio_ids_visibles.assert_not_called()


@pytest.mark.asyncio
async def test_resolver_admin_sistema_ve_todo(mock_conn, admin_context):
    svc = _svc_con_db()
    creado_por_ids, servicio_ids = await svc.resolver_filtro_visibilidad(mock_conn, admin_context, "simulacion")
    assert (creado_por_ids, servicio_ids) == (None, None)


@pytest.mark.asyncio
async def test_crear_servicio_simulacion_reregistro_otorga_visibilidad(mock_conn):
    svc = _svc_con_db()
    existente = {"id": uuid4(), "nombre": "CLIENTE X", "modulos": ["simulacion"]}
    svc.db.get_servicio_by_numero = AsyncMock(return_value=existente)
    svc.db.agregar_registrador = AsyncMock(return_value=True)

    servicio, estado = await svc.crear_servicio(
        mock_conn, numero_servicio="123", nombre="cliente x", alias=None,
        lada="55", telefono="1", email="a@b.com", usuario_id=uuid4(), modulo="simulacion",
    )

    assert estado == "visibilidad_otorgada"
    assert servicio is existente
    svc.db.agregar_registrador.assert_awaited_once()


@pytest.mark.asyncio
async def test_crear_servicio_oym_existente_sigue_lanzando_error(mock_conn):
    svc = _svc_con_db()
    svc.db.get_servicio_by_numero = AsyncMock(
        return_value={"id": uuid4(), "nombre": "CLIENTE X", "modulos": ["oym"]}
    )

    with pytest.raises(ValueError, match="ya está registrado"):
        await svc.crear_servicio(
            mock_conn, numero_servicio="123", nombre="cliente x", alias=None,
            lada="55", telefono="1", email="a@b.com", usuario_id=uuid4(), modulo="oym",
        )
