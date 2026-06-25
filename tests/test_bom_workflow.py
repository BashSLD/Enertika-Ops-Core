from uuid import uuid4

import pytest

from core.bom.schemas import EstatusBOM, TipoAprobacion
from core.bom.service import BomService
from core.bom.router import router as bom_router, templates as bom_templates


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


FLUJO_FECHAS = (
    "fecha_envio_ing",
    "fecha_aprobacion_ing",
    "fecha_envio_obra",
    "fecha_aprobacion_obra",
    "fecha_envio_const",
    "fecha_aprobacion_const",
    "fecha_envio_final",
    "fecha_aprobacion_final",
)


def _fechas_seteadas():
    return {campo: "2026-06-25T12:00:00" for campo in FLUJO_FECHAS}


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


@pytest.mark.asyncio
async def test_rechazar_obra_vuelve_a_borrador_y_limpia_fechas():
    user_id = uuid4()
    bom = _base_bom(estatus=EstatusBOM.EN_REVISION_OBRA.value, **_fechas_seteadas())
    db = FakeWorkflowDB(bom)
    service = _service(db)

    updated = await service.rechazar_obra(
        FakeConn(), bom["id_bom"], user_id, "ADMIN", None, "Corregir alcance"
    )

    assert updated["estatus"] == EstatusBOM.BORRADOR.value
    assert all(updated[campo] is None for campo in FLUJO_FECHAS)
    assert db.aprobaciones[0][0] == TipoAprobacion.RECHAZO_OBRA


@pytest.mark.asyncio
async def test_rechazar_const_a_obra_vuelve_a_revision_obra():
    user_id = uuid4()
    bom = _base_bom(estatus=EstatusBOM.EN_REVISION_CONST.value, **_fechas_seteadas())
    db = FakeWorkflowDB(bom)
    service = _service(db)

    updated = await service.rechazar_const(
        FakeConn(), bom["id_bom"], user_id, "ADMIN", None, "Revisar frente",
        destino_rechazo="obra"
    )

    assert updated["estatus"] == EstatusBOM.EN_REVISION_OBRA.value
    assert updated["fecha_envio_ing"] == "2026-06-25T12:00:00"
    assert updated["fecha_aprobacion_ing"] == "2026-06-25T12:00:00"
    assert updated["fecha_envio_obra"] == "2026-06-25T12:00:00"
    assert updated["fecha_aprobacion_obra"] is None
    assert updated["fecha_envio_const"] is None
    assert updated["fecha_aprobacion_const"] is None
    assert updated["fecha_envio_final"] is None
    assert updated["fecha_aprobacion_final"] is None
    assert db.aprobaciones[0][0] == TipoAprobacion.RECHAZO_CONST


@pytest.mark.asyncio
async def test_rechazar_const_a_ingenieria_vuelve_a_borrador():
    user_id = uuid4()
    bom = _base_bom(estatus=EstatusBOM.EN_REVISION_CONST.value, **_fechas_seteadas())
    db = FakeWorkflowDB(bom)
    service = _service(db)

    updated = await service.rechazar_const(
        FakeConn(), bom["id_bom"], user_id, "ADMIN", None, "Redisenar partida",
        destino_rechazo="ingenieria"
    )

    assert updated["estatus"] == EstatusBOM.BORRADOR.value
    assert all(updated[campo] is None for campo in FLUJO_FECHAS)
    assert db.aprobaciones[0][0] == TipoAprobacion.RECHAZO_CONST


@pytest.mark.asyncio
@pytest.mark.parametrize("destino_rechazo", [None, "compras"])
async def test_rechazar_const_rechaza_destino_invalido(destino_rechazo):
    user_id = uuid4()
    bom = _base_bom(estatus=EstatusBOM.EN_REVISION_CONST.value)
    db = FakeWorkflowDB(bom)
    service = _service(db)

    with pytest.raises(ValueError, match="Destino de rechazo invalido"):
        await service.rechazar_const(
            FakeConn(), bom["id_bom"], user_id, "ADMIN", None, "No aplica",
            destino_rechazo=destino_rechazo
        )

    assert db.updates == []
    assert db.aprobaciones == []


@pytest.mark.asyncio
async def test_rechazar_final_vuelve_a_borrador():
    user_id = uuid4()
    bom = _base_bom(estatus=EstatusBOM.EN_REVISION_FINAL.value, **_fechas_seteadas())
    db = FakeWorkflowDB(
        bom,
        roles_by_user={user_id: "director"},
        aprobador_final_id=user_id,
    )
    service = _service(db)

    updated = await service.rechazar_final(
        FakeConn(), bom["id_bom"], user_id, "Corregir presupuesto"
    )

    assert updated["estatus"] == EstatusBOM.BORRADOR.value
    assert all(updated[campo] is None for campo in FLUJO_FECHAS)
    assert db.aprobaciones[0][0] == TipoAprobacion.RECHAZO_FINAL


def test_no_existe_camino_service_directo_a_construccion():
    assert not hasattr(BomService, "enviar_revision_const")


def test_router_y_modal_no_exponen_enviar_const():
    route_paths = {route.path for route in bom_router.routes}

    assert "/bom/{id_bom}/enviar-const" not in route_paths
    with open("templates/bom/partials/modal_aprobar.html", encoding="utf-8") as template:
        contenido = template.read()
        assert "enviar-const" not in contenido
        assert 'name="destino_rechazo"' in contenido


def test_row_item_no_muestra_editar_en_aprobado_final():
    template = bom_templates.env.get_template("bom/partials/row_item.html")
    item_id = uuid4()
    item = {
        "id_item": item_id,
        "grupos": [],
        "tipo_partida": "MATERIAL",
        "entregado": False,
        "bloqueado": False,
        "orden": 1,
        "categoria_nombre": "Material",
        "id_item_origen": None,
        "descripcion": "Panel solar",
        "comentarios": None,
        "cantidad": 1,
        "unidad_medida": "pz",
        "precio_unitario": 100,
        "moneda": "MXN",
        "origen_precio": "MANUAL",
        "importe": 100,
        "costo_mxn": None,
        "gasto_real": None,
        "fecha_requerida": None,
        "estatus_compra": "SIN_COTIZAR",
        "proveedor_nombre": None,
        "tipo_entrega": None,
        "fecha_estimada_entrega": None,
        "fecha_llegada_real": None,
        "cantidad_recibida": 0,
    }

    html = template.render(
        item=item,
        bom={"estatus": EstatusBOM.APROBADO_FINAL.value},
        area_editor="ingenieria",
        puede_gestionar_bom_ingenieria=True,
    )

    assert f"/bom/items/{item_id}/modal" not in html


def test_row_item_muestra_editar_operativo_en_aprobado_final_para_compras():
    template = bom_templates.env.get_template("bom/partials/row_item.html")
    item_id = uuid4()
    item = {
        "id_item": item_id,
        "grupos": [],
        "tipo_partida": "MATERIAL",
        "entregado": False,
        "bloqueado": False,
        "orden": 1,
        "categoria_nombre": "Material",
        "id_item_origen": None,
        "descripcion": "Panel solar",
        "comentarios": None,
        "cantidad": 1,
        "unidad_medida": "pz",
        "precio_unitario": 100,
        "precio_real": None,
        "moneda": "MXN",
        "moneda_real": None,
        "origen_precio": "MANUAL",
        "importe": 100,
        "importe_real": None,
        "costo_mxn": None,
        "costo_real_mxn": None,
        "gasto_real": None,
        "fecha_requerida": None,
        "estatus_compra": "SIN_COTIZAR",
        "proveedor_nombre": None,
        "tipo_entrega": None,
        "fecha_estimada_entrega": None,
        "fecha_llegada_real": None,
        "cantidad_recibida": 0,
    }

    html = template.render(
        item=item,
        bom={"estatus": EstatusBOM.APROBADO_FINAL.value},
        area_editor="compras",
        puede_gestionar_bom_ingenieria=False,
    )

    assert f"/bom/items/{item_id}/modal" in html
