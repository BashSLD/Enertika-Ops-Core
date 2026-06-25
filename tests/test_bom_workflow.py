from uuid import uuid4

import pytest

from core.bom.schemas import EstatusBOM
from core.bom.service import BomService
from core.bom.router import router as bom_router


class FakeConn:
    pass


class FakeWorkflowDB:
    def __init__(
        self,
        bom,
        *,
        items=None,
        items_sin_costo=None,
        roles_by_user=None,
        aprobador_final_id=None,
    ):
        self.bom = dict(bom)
        self.items = list(items or [])
        self.items_sin_costo = list(items_sin_costo or [])
        self.roles_by_user = {str(k): v for k, v in (roles_by_user or {}).items()}
        self.aprobador_final_id = aprobador_final_id
        self.updates = []
        self.aprobaciones = []

    async def get_bom_by_id(self, conn, id_bom):
        return dict(self.bom) if str(self.bom["id_bom"]) == str(id_bom) else None

    async def usuario_tiene_rol_org(self, conn, user_id, rol_organizacional):
        return self.roles_by_user.get(str(user_id)) == rol_organizacional

    async def usuario_tiene_asignacion_proyecto(
        self, conn, id_proyecto, user_id, rol_proyecto, area
    ):
        return False

    async def get_aprobador_final_id(self, conn):
        return self.aprobador_final_id

    async def get_items_by_bom(self, conn, id_bom):
        return list(self.items)

    async def get_items_sin_costo_bom(self, conn, id_bom):
        return list(self.items_sin_costo)

    async def update_bom_estatus(self, conn, id_bom, estatus, **kwargs):
        self.updates.append((estatus, kwargs))
        self.bom["estatus"] = estatus.value if hasattr(estatus, "value") else estatus
        self.bom.update(kwargs)
        return dict(self.bom)

    async def registrar_aprobacion(
        self, conn, id_bom, tipo, version_bom, usuario_id, comentarios=None
    ):
        self.aprobaciones.append((tipo, usuario_id, comentarios))
        return {}


async def _noop_notify(*args, **kwargs):
    return None


def _base_bom(**overrides):
    bom = {
        "id_bom": uuid4(),
        "id_proyecto": uuid4(),
        "version": 1,
        "estatus": EstatusBOM.BORRADOR.value,
        "elaborado_por": uuid4(),
        "responsable_ing": uuid4(),
        "coordinador_obra": uuid4(),
        "jefe_construccion": uuid4(),
    }
    bom.update(overrides)
    return bom


def _service(db):
    service = BomService()
    service.db = db
    service._notify_bom = _noop_notify
    return service


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("responsable_ing", "falta responsable de Ingenieria"),
        ("coordinador_obra", "falta Coordinador de Obra"),
        ("jefe_construccion", "falta Jefe de Construccion"),
    ],
)
async def test_enviar_revision_ing_bloquea_si_falta_responsable(field, expected):
    user_id = uuid4()
    director_id = uuid4()
    bom = _base_bom(**{field: None})
    db = FakeWorkflowDB(
        bom,
        items=[{"id_item": uuid4(), "precio_unitario": 1}],
        roles_by_user={user_id: "jefe_ingenieria", director_id: "director"},
        aprobador_final_id=director_id,
    )
    service = _service(db)

    with pytest.raises(ValueError, match=expected):
        await service.enviar_revision_ing(FakeConn(), bom["id_bom"], user_id)

    assert db.updates == []


@pytest.mark.asyncio
async def test_enviar_revision_ing_bloquea_si_falta_aprobador_final_direccion():
    user_id = uuid4()
    bom = _base_bom()
    db = FakeWorkflowDB(
        bom,
        items=[{"id_item": uuid4(), "precio_unitario": 1}],
        roles_by_user={user_id: "jefe_ingenieria"},
        aprobador_final_id=None,
    )
    service = _service(db)

    with pytest.raises(ValueError, match="Configura un aprobador final de Dirección"):
        await service.enviar_revision_ing(FakeConn(), bom["id_bom"], user_id)

    assert db.updates == []


@pytest.mark.asyncio
async def test_enviar_revision_ing_avanza_con_responsables_y_costos_completos():
    user_id = uuid4()
    director_id = uuid4()
    bom = _base_bom()
    db = FakeWorkflowDB(
        bom,
        items=[{"id_item": uuid4(), "precio_unitario": 1}],
        roles_by_user={user_id: "jefe_ingenieria", director_id: "director"},
        aprobador_final_id=director_id,
    )
    service = _service(db)

    updated = await service.enviar_revision_ing(FakeConn(), bom["id_bom"], user_id)

    assert updated["estatus"] == EstatusBOM.EN_REVISION_ING.value
    assert "fecha_envio_ing" in updated
    assert db.updates[0][0] == EstatusBOM.EN_REVISION_ING


@pytest.mark.asyncio
async def test_aprobar_revision_obra_avanza_a_construccion_y_setea_fecha_envio_const():
    user_id = uuid4()
    bom = _base_bom(estatus=EstatusBOM.EN_REVISION_OBRA.value)
    db = FakeWorkflowDB(
        bom,
        roles_by_user={user_id: "coordinador_obra"},
    )
    service = _service(db)

    updated = await service.aprobar_revision_obra(
        FakeConn(), bom["id_bom"], user_id, "ADMIN", None, "Ok"
    )

    assert updated["estatus"] == EstatusBOM.EN_REVISION_CONST.value
    assert "fecha_aprobacion_obra" in updated
    assert "fecha_envio_const" in updated


@pytest.mark.asyncio
async def test_aprobar_final_rechaza_configurado_que_no_es_direccion():
    user_id = uuid4()
    bom = _base_bom(estatus=EstatusBOM.EN_REVISION_FINAL.value)
    db = FakeWorkflowDB(
        bom,
        roles_by_user={user_id: "jefe_construccion"},
        aprobador_final_id=user_id,
    )
    service = _service(db)

    with pytest.raises(ValueError, match="usuario activo de Dirección"):
        await service.aprobar_final(FakeConn(), bom["id_bom"], user_id, "Ok")

    assert db.updates == []


def test_no_existe_camino_service_directo_a_construccion():
    assert not hasattr(BomService, "enviar_revision_const")


def test_router_y_modal_no_exponen_enviar_const():
    route_paths = {route.path for route in bom_router.routes}

    assert "/bom/{id_bom}/enviar-const" not in route_paths
    with open("templates/bom/partials/modal_aprobar.html", encoding="utf-8") as template:
        assert "enviar-const" not in template.read()
