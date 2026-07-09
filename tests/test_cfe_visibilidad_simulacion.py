import asyncpg
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


class FakeConnTx:
    """Conn minimo: solo necesita soportar `async with conn.transaction()`.
    Registra si se entro al context manager para poder afirmarlo en el test
    (un AsyncMock() plano no deja verificar esto de forma confiable)."""
    def __init__(self):
        self.transaction_entered = False
    def transaction(self):
        return self
    async def __aenter__(self):
        self.transaction_entered = True
        return self
    async def __aexit__(self, *exc):
        return False


@pytest.mark.asyncio
async def test_crear_servicio_nuevo_usa_transaccion_atomica():
    svc = _svc_con_db()
    svc.db.get_servicio_by_numero = AsyncMock(return_value=None)
    creado = {"id": uuid4(), "nombre": "CLIENTE X", "modulos": ["simulacion"]}
    svc.db.crear_servicio = AsyncMock(return_value=creado)
    svc.db.agregar_registrador = AsyncMock(return_value=True)
    svc.db.marcar_alta_miespacio_pendiente = AsyncMock()

    conn = FakeConnTx()
    await svc.crear_servicio(
        conn, numero_servicio="123", nombre="cliente x", alias=None,
        lada="55", telefono="1", email="a@b.com", usuario_id=uuid4(), modulo="simulacion",
    )

    assert conn.transaction_entered is True, "crear_servicio debe envolver el alta en conn.transaction()"
    svc.db.crear_servicio.assert_awaited_once()
    svc.db.agregar_registrador.assert_awaited_once()


@pytest.mark.asyncio
async def test_crear_servicio_simulacion_reregistro_otorga_visibilidad():
    svc = _svc_con_db()
    existente = {"id": uuid4(), "nombre": "CLIENTE X", "modulos": ["simulacion"]}
    svc.db.get_servicio_by_numero = AsyncMock(return_value=existente)
    svc.db.agregar_registrador = AsyncMock(return_value=True)

    servicio, estado = await svc.crear_servicio(
        FakeConnTx(), numero_servicio="123", nombre="cliente x", alias=None,
        lada="55", telefono="1", email="a@b.com", usuario_id=uuid4(), modulo="simulacion",
    )

    assert estado == "visibilidad_otorgada"
    assert servicio is existente
    svc.db.agregar_registrador.assert_awaited_once()


@pytest.mark.asyncio
async def test_crear_servicio_oym_existente_sigue_lanzando_error():
    svc = _svc_con_db()
    svc.db.get_servicio_by_numero = AsyncMock(
        return_value={"id": uuid4(), "nombre": "CLIENTE X", "modulos": ["oym"]}
    )

    with pytest.raises(ValueError, match="ya está registrado"):
        await svc.crear_servicio(
            FakeConnTx(), numero_servicio="123", nombre="cliente x", alias=None,
            lada="55", telefono="1", email="a@b.com", usuario_id=uuid4(), modulo="oym",
        )


@pytest.mark.asyncio
async def test_crear_servicio_falla_en_registrador_no_swallowed(mock_conn):
    # Si agregar_registrador falla a mitad de la transaccion, la excepcion debe
    # propagarse (no ser atrapada dentro del `async with conn.transaction()`) —
    # es justo esa propagacion la que hace que asyncpg dispare el rollback real
    # y evita que quede un servicio sin su fila de registrador (Tarea 0).
    svc = _svc_con_db()
    svc.db.get_servicio_by_numero = AsyncMock(return_value=None)
    creado = {"id": uuid4(), "nombre": "CLIENTE X", "modulos": ["simulacion"]}
    svc.db.crear_servicio = AsyncMock(return_value=creado)
    svc.db.agregar_registrador = AsyncMock(side_effect=asyncpg.PostgresError("boom"))
    svc.db.marcar_alta_miespacio_pendiente = AsyncMock()

    conn = FakeConnTx()
    with pytest.raises(asyncpg.PostgresError):
        await svc.crear_servicio(
            conn, numero_servicio="123", nombre="cliente x", alias=None,
            lada="55", telefono="1", email="a@b.com", usuario_id=uuid4(), modulo="simulacion",
        )

    assert conn.transaction_entered is True
    svc.db.crear_servicio.assert_awaited_once()
    svc.db.marcar_alta_miespacio_pendiente.assert_not_awaited()


@pytest.mark.asyncio
async def test_ocultar_servicio_solo_en_modulos_del_usuario(mock_conn):
    svc = _svc_con_db()
    servicio = {"id": uuid4(), "modulos": ["simulacion"]}
    svc.db.ocultar_servicio = AsyncMock()

    await svc.ocultar_servicio(mock_conn, servicio, uuid4(), modulos_usuario=["oym", "simulacion"])

    svc.db.ocultar_servicio.assert_awaited_once()
    assert svc.db.ocultar_servicio.await_args.args[-1] == ["simulacion"]


@pytest.mark.asyncio
async def test_ocultar_servicio_sin_acceso_lanza_error(mock_conn):
    svc = _svc_con_db()
    servicio = {"id": uuid4(), "modulos": ["oym"]}

    with pytest.raises(ValueError, match="No tienes acceso"):
        await svc.ocultar_servicio(mock_conn, servicio, uuid4(), modulos_usuario=["simulacion"])


@pytest.mark.asyncio
async def test_resolver_ocultos_sin_usuario_no_filtra(mock_conn):
    svc = _svc_con_db()
    assert await svc.resolver_ocultos(mock_conn, {}, ["oym"]) is None
