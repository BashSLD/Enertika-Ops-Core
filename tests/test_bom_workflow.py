from uuid import uuid4

import pytest

from core.bom.schemas import EstatusBOM, TipoAprobacion
from core.bom.service import BomService
from core.bom.router import router as bom_router, templates as bom_templates
from core.config_service import ConfigService


class FakeConn:
    pass


class FakeTxConn:
    def transaction(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeWorkflowDB:
    def __init__(
        self,
        bom,
        *,
        items=None,
        items_sin_costo=None,
        roles_by_user=None,
        aprobador_final_id=None,
        titulares_by_user=None,
    ):
        self.bom = dict(bom)
        self.items = list(items or [])
        self.items_sin_costo = list(items_sin_costo or [])
        self.roles_by_user = {str(k): v for k, v in (roles_by_user or {}).items()}
        self.aprobador_final_id = aprobador_final_id
        self.titulares_by_user = {
            str(k): list(v) for k, v in (titulares_by_user or {}).items()
        }
        self.updates = []
        self.aprobaciones = []

    async def get_bom_by_id(self, conn, id_bom):
        return dict(self.bom) if str(self.bom["id_bom"]) == str(id_bom) else None

    async def get_bom_for_update(self, conn, id_bom):
        return await self.get_bom_by_id(conn, id_bom)

    async def usuario_tiene_rol_org(self, conn, user_id, rol_organizacional):
        return self.roles_by_user.get(str(user_id)) == rol_organizacional

    async def usuario_tiene_asignacion_proyecto(
        self, conn, id_proyecto, user_id, rol_proyecto, area
    ):
        return False

    async def get_aprobador_final_id(self, conn):
        return self.aprobador_final_id

    async def get_titulares_que_representa(self, conn, user_id):
        return list(self.titulares_by_user.get(str(user_id), []))

    async def get_items_by_bom(self, conn, id_bom):
        return list(self.items)

    async def get_items_sin_costo_bom(self, conn, id_bom):
        return list(self.items_sin_costo)

    async def get_asignacion_proyecto(self, conn, id_proyecto, rol_proyecto, area):
        return None

    async def get_responsable_proyecto_o_global(self, conn, id_proyecto, rol_proyecto):
        return None

    async def get_usuario_activo_por_rol_org(self, conn, rol_organizacional):
        return None

    async def update_bom_estatus(self, conn, id_bom, estatus, **kwargs):
        self.updates.append((estatus, kwargs))
        self.bom["estatus"] = estatus.value if hasattr(estatus, "value") else estatus
        self.bom.update(kwargs)
        return dict(self.bom)

    async def update_bom_estatus_cas(
        self, conn, id_bom, estatus_esperado, lock_version_esperado,
        nuevo_estatus, **kwargs,
    ):
        if (
            self.bom["estatus"] != estatus_esperado
            or self.bom["lock_version"] != lock_version_esperado
        ):
            return None
        self.updates.append((nuevo_estatus, kwargs))
        self.bom.update(
            estatus=nuevo_estatus,
            lock_version=self.bom["lock_version"] + 1,
            **kwargs,
        )
        return dict(self.bom)

    async def invalidar_aprobaciones_vigentes(self, conn, id_bom, user_id):
        return None

    async def registrar_evento_outbox(self, *args, **kwargs):
        return {}

    async def registrar_aprobacion(
        self, conn, id_bom, tipo, version_bom, usuario_id, id_paquete, comentarios=None,
        destino_rechazo=None
    ):
        self.aprobaciones.append((tipo, usuario_id, id_paquete, comentarios, destino_rechazo))
        return {}


async def _noop_notify(*args, **kwargs):
    return None


@pytest.fixture(autouse=True)
def _config_workflow_solo_responsable(monkeypatch):
    async def _get_global_config(cls, conn, clave, default, tipo=str):
        if clave == "bom.gestion_solo_responsable":
            return True
        return default

    monkeypatch.setattr(
        ConfigService,
        "get_global_config",
        classmethod(_get_global_config),
    )


def _base_bom(**overrides):
    elaborado_por = uuid4()
    bom = {
        "id_bom": uuid4(),
        "id_paquete": uuid4(),
        "id_proyecto": uuid4(),
        "version": 1,
        "estatus": EstatusBOM.BORRADOR.value,
        "elaborado_por": elaborado_por,
        "ingeniero_responsable_id": elaborado_por,
        "responsable_ing": uuid4(),
        "coordinador_obra": uuid4(),
        "jefe_construccion": uuid4(),
        "lock_version": 0,
        "es_cabeza_trabajo": True,
        "es_cabeza_oficial": False,
        "estado_paquete": "ACTIVO",
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
async def test_capacidades_ejecucion_exigen_control_del_turno_antes_del_final():
    titular = uuid4()
    ajeno = uuid4()
    bom = _base_bom(
        estatus=EstatusBOM.BORRADOR.value,
        ingeniero_responsable_id=titular,
        elaborado_por=titular,
    )
    service = _service(FakeWorkflowDB(bom))

    capacidades_ajeno = await service.get_capacidades_bom(
        FakeConn(), bom, ajeno, module_roles={"construccion": "editor"}
    )
    capacidades_titular = await service.get_capacidades_bom(
        FakeConn(), bom, titular, module_roles={"ingenieria": "editor"}
    )

    assert capacidades_ajeno["editar_ejecucion"] is False
    assert capacidades_titular["editar_ejecucion"] is True


@pytest.mark.asyncio
async def test_capacidades_downstream_siguen_en_cabeza_oficial_durante_retrabajo():
    usuario_compras = uuid4()
    bom = _base_bom(
        estatus=EstatusBOM.APROBADO_FINAL.value,
        es_cabeza_trabajo=False,
        es_cabeza_oficial=True,
    )
    service = _service(FakeWorkflowDB(bom))

    capacidades = await service.get_capacidades_bom(
        FakeConn(), bom, usuario_compras, module_roles={"compras": "editor"}
    )

    assert capacidades["editar_ejecucion"] is True


def test_cotizaciones_usan_cabeza_oficial_si_hay_retrabajo():
    assert BomService._es_cabeza_cotizable({
        "estatus": EstatusBOM.APROBADO_FINAL.value,
        "es_cabeza_trabajo": False,
        "es_cabeza_oficial": True,
    })
    assert not BomService._es_cabeza_cotizable({
        "estatus": EstatusBOM.APROBADO_FINAL.value,
        "es_cabeza_trabajo": True,
        "es_cabeza_oficial": False,
    })
    assert BomService._es_cabeza_cotizable({
        "estatus": EstatusBOM.APROBADO_CONST.value,
        "es_cabeza_trabajo": True,
        "es_cabeza_oficial": False,
    })


@pytest.mark.asyncio
async def test_enviar_revision_ing_bloquea_si_falta_responsable():
    """Coordinador de Obra y Jefe de Construccion ya no se validan aqui: se
    resuelven en vivo hasta enviar_revision_obra (ver test correspondiente)."""
    user_id = uuid4()
    director_id = uuid4()
    bom = _base_bom(responsable_ing=None, ingeniero_responsable_id=user_id)
    db = FakeWorkflowDB(
        bom,
        items=[{"id_item": uuid4(), "precio_unitario": 1}],
        roles_by_user={user_id: "jefe_ingenieria", director_id: "director"},
        aprobador_final_id=director_id,
    )
    service = _service(db)

    with pytest.raises(ValueError, match="falta responsable de Ingenieria"):
        await service.enviar_revision_ing(FakeConn(), bom["id_bom"], user_id)

    assert db.updates == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("coordinador_obra", "falta Coordinador de Obra"),
        ("jefe_construccion", "falta Jefe de Construccion"),
    ],
)
async def test_enviar_revision_obra_bloquea_si_falta_responsable(field, expected):
    user_id = uuid4()
    bom = _base_bom(
        estatus=EstatusBOM.APROBADO_ING.value,
        responsable_ing=user_id,
        **{field: None},
    )
    db = FakeWorkflowDB(
        bom,
        items_sin_costo=[],
        roles_by_user={user_id: "jefe_ingenieria"},
    )
    service = _service(db)

    with pytest.raises(ValueError, match=expected):
        await service.enviar_revision_obra(FakeConn(), bom["id_bom"], user_id)

    assert db.updates == []


@pytest.mark.asyncio
async def test_enviar_revision_ing_bloquea_si_falta_aprobador_final_direccion():
    user_id = uuid4()
    bom = _base_bom(
        ingeniero_responsable_id=user_id,
        responsable_ing=user_id,
    )
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
    bom = _base_bom(
        ingeniero_responsable_id=user_id,
        responsable_ing=user_id,
    )
    db = FakeWorkflowDB(
        bom,
        items=[{"id_item": uuid4(), "precio_unitario": 1}],
        roles_by_user={user_id: "jefe_ingenieria", director_id: "director"},
        aprobador_final_id=director_id,
    )
    service = _service(db)

    updated = await service.enviar_revision_ing(
        FakeConn(), bom["id_bom"], user_id, lock_version_esperado=0
    )

    assert updated["estatus"] == EstatusBOM.EN_REVISION_ING.value
    assert "fecha_envio_ing" in updated
    assert db.updates[0][0] == EstatusBOM.EN_REVISION_ING


@pytest.mark.asyncio
async def test_aprobar_revision_obra_avanza_a_construccion_y_setea_fecha_envio_const():
    user_id = uuid4()
    bom = _base_bom(
        estatus=EstatusBOM.EN_REVISION_OBRA.value,
        coordinador_obra=user_id,
    )
    db = FakeWorkflowDB(
        bom,
        roles_by_user={user_id: "coordinador_obra"},
    )
    service = _service(db)

    updated = await service.aprobar_revision_obra(
        FakeConn(), bom["id_bom"], user_id, "USER", None, "Ok",
        lock_version_esperado=0,
    )

    assert updated["estatus"] == EstatusBOM.EN_REVISION_CONST.value
    assert "fecha_aprobacion_obra" in updated
    assert "fecha_envio_const" in updated


@pytest.mark.asyncio
async def test_aprobar_revision_obra_permite_suplente_activo_del_responsable():
    suplente_id = uuid4()
    coordinador_id = uuid4()
    bom = _base_bom(
        estatus=EstatusBOM.EN_REVISION_OBRA.value,
        coordinador_obra=coordinador_id,
    )
    db = FakeWorkflowDB(
        bom,
        titulares_by_user={suplente_id: [coordinador_id]},
    )
    service = _service(db)

    updated = await service.aprobar_revision_obra(
        FakeConn(), bom["id_bom"], suplente_id, "USER", None, "Ok",
        lock_version_esperado=0,
    )

    assert updated["estatus"] == EstatusBOM.EN_REVISION_CONST.value


@pytest.mark.asyncio
async def test_admin_sin_ownership_no_puede_aprobar_revision_obra():
    admin_id = uuid4()
    bom = _base_bom(estatus=EstatusBOM.EN_REVISION_OBRA.value)
    db = FakeWorkflowDB(bom)
    service = _service(db)

    with pytest.raises(ValueError, match="Coordinador de Obra"):
        await service.aprobar_revision_obra(
            FakeConn(), bom["id_bom"], admin_id, "ADMIN", None, "Ok",
            lock_version_esperado=0,
        )

    assert db.updates == []


@pytest.mark.asyncio
async def test_enviar_revision_ing_rechaza_lock_faltante():
    user_id = uuid4()
    director_id = uuid4()
    bom = _base_bom(
        ingeniero_responsable_id=user_id,
        responsable_ing=user_id,
    )
    db = FakeWorkflowDB(
        bom,
        items=[{"id_item": uuid4(), "precio_unitario": 1}],
        roles_by_user={director_id: "director"},
        aprobador_final_id=director_id,
    )
    service = _service(db)

    with pytest.raises(ValueError, match="Falta la revision del BOM"):
        await service.enviar_revision_ing(FakeConn(), bom["id_bom"], user_id)

    assert db.updates == []


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
        await service.aprobar_final(
            FakeConn(), bom["id_bom"], user_id, "Ok", lock_version_esperado=0
        )

    assert db.updates == []


@pytest.mark.asyncio
async def test_rechazar_ing_vuelve_misma_version_a_borrador():
    user_id = uuid4()
    bom = _base_bom(
        estatus=EstatusBOM.EN_REVISION_ING.value,
        responsable_ing=user_id,
        **_fechas_seteadas(),
    )
    db = FakeWorkflowDB(bom)
    service = _service(db)

    updated = await service.rechazar_ing(
        FakeConn(), bom["id_bom"], user_id, "USER", None, "Corregir diseno",
        lock_version_esperado=0,
    )

    assert updated["estatus"] == EstatusBOM.BORRADOR.value
    assert updated["version"] == bom["version"]
    assert all(updated[campo] is None for campo in FLUJO_FECHAS)
    assert db.aprobaciones[0][0] == TipoAprobacion.RECHAZO_ING
    assert db.aprobaciones[0][2] == bom["id_paquete"]


@pytest.mark.asyncio
async def test_rechazar_obra_vuelve_a_borrador_y_limpia_fechas():
    user_id = uuid4()
    bom = _base_bom(
        estatus=EstatusBOM.EN_REVISION_OBRA.value,
        coordinador_obra=user_id,
        **_fechas_seteadas(),
    )
    db = FakeWorkflowDB(bom)
    service = _service(db)

    updated = await service.rechazar_obra(
        FakeConn(), bom["id_bom"], user_id, "USER", None, "Corregir alcance",
        lock_version_esperado=0,
    )

    assert updated["estatus"] == EstatusBOM.BORRADOR.value
    assert all(updated[campo] is None for campo in FLUJO_FECHAS)
    assert db.aprobaciones[0][0] == TipoAprobacion.RECHAZO_OBRA
    assert db.aprobaciones[0][2] == bom["id_paquete"]
    assert updated["version"] == bom["version"]


@pytest.mark.asyncio
async def test_rechazar_const_siempre_vuelve_a_borrador():
    user_id = uuid4()
    bom = _base_bom(
        estatus=EstatusBOM.EN_REVISION_CONST.value,
        jefe_construccion=user_id,
        **_fechas_seteadas(),
    )
    db = FakeWorkflowDB(bom)
    service = _service(db)

    updated = await service.rechazar_const(
        FakeConn(), bom["id_bom"], user_id, "USER", None, "Revisar frente",
        destino_rechazo="obra", lock_version_esperado=0,
    )

    assert updated["estatus"] == EstatusBOM.BORRADOR.value
    assert all(updated[campo] is None for campo in FLUJO_FECHAS)
    assert db.aprobaciones[0][0] == TipoAprobacion.RECHAZO_CONST
    assert db.aprobaciones[0][2] == bom["id_paquete"]
    assert db.aprobaciones[0][4] == "ingenieria"
    assert updated["version"] == bom["version"]


@pytest.mark.asyncio
async def test_rechazar_const_a_ingenieria_vuelve_a_borrador():
    user_id = uuid4()
    bom = _base_bom(
        estatus=EstatusBOM.EN_REVISION_CONST.value,
        jefe_construccion=user_id,
        **_fechas_seteadas(),
    )
    db = FakeWorkflowDB(bom)
    service = _service(db)

    updated = await service.rechazar_const(
        FakeConn(), bom["id_bom"], user_id, "USER", None, "Redisenar partida",
        destino_rechazo="ingenieria", lock_version_esperado=0,
    )

    assert updated["estatus"] == EstatusBOM.BORRADOR.value
    assert all(updated[campo] is None for campo in FLUJO_FECHAS)
    assert db.aprobaciones[0][0] == TipoAprobacion.RECHAZO_CONST
    assert db.aprobaciones[0][2] == bom["id_paquete"]
    assert db.aprobaciones[0][4] == "ingenieria"


@pytest.mark.asyncio
@pytest.mark.parametrize("destino_rechazo", [None, "compras"])
async def test_rechazar_const_ignora_destino_legacy_y_vuelve_a_borrador(destino_rechazo):
    user_id = uuid4()
    bom = _base_bom(
        estatus=EstatusBOM.EN_REVISION_CONST.value,
        jefe_construccion=user_id,
    )
    db = FakeWorkflowDB(bom)
    service = _service(db)

    updated = await service.rechazar_const(
        FakeConn(), bom["id_bom"], user_id, "USER", None, "No aplica",
        destino_rechazo=destino_rechazo, lock_version_esperado=0,
    )

    assert updated["estatus"] == EstatusBOM.BORRADOR.value


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
        FakeConn(), bom["id_bom"], user_id, "Corregir presupuesto",
        lock_version_esperado=0,
    )

    assert updated["estatus"] == EstatusBOM.BORRADOR.value
    assert all(updated[campo] is None for campo in FLUJO_FECHAS)
    assert db.aprobaciones[0][0] == TipoAprobacion.RECHAZO_FINAL
    assert db.aprobaciones[0][2] == bom["id_paquete"]
    assert updated["version"] == bom["version"]


def test_no_existe_camino_service_directo_a_construccion():
    assert not hasattr(BomService, "enviar_revision_const")


def test_router_y_modal_no_exponen_enviar_const():
    route_paths = {route.path for route in bom_router.routes}

    assert "/bom/{id_bom}/enviar-const" not in route_paths
    with open("templates/bom/partials/modal_aprobar.html", encoding="utf-8") as template:
        contenido = template.read()
        assert "enviar-const" not in contenido
        assert 'name="destino_rechazo"' not in contenido


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
        capacidades={"editar_base": False, "editar_ejecucion": False},
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
        capacidades={"editar_base": False, "editar_ejecucion": True},
    )

    assert f"/bom/items/{item_id}/modal" in html


def test_row_item_filtra_por_grupo_operativo_si_existe():
    template = bom_templates.env.get_template("bom/partials/row_item.html")
    item_id = uuid4()
    item = {
        "id_item": item_id,
        "grupos": ["AC"],
        "grupos_operativos": ["DC"],
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
        area_editor="construccion",
        puede_gestionar_bom_ingenieria=False,
        capacidades={"editar_base": False, "editar_ejecucion": True},
    )

    assert 'data-grupos="DC"' in html


def test_adendas_template_renderiza_acciones_workflow():
    template = bom_templates.env.get_template("bom/partials/adendas.html")
    adenda_id = uuid4()

    html = template.render(
        bom={"estatus": EstatusBOM.APROBADO_FINAL.value},
        adendas=[
            {
                "id_adenda": adenda_id,
                "tipo_adenda": "REEMPLAZO",
                "estatus": "PENDIENTE_CONSTRUCCION",
                "motivo": "Cambio por disponibilidad",
                "items_resumen": "Modulo FV",
                "total_lineas": 1,
                "creado_por_nombre": "Compras",
                "created_at": None,
                "requiere_aprobacion_ingenieria": False,
                "aprobado_construccion_por_nombre": None,
                "aprobado_ingenieria_por_nombre": None,
                "motivo_rechazo": None,
            }
        ],
        comentarios_adendas={str(adenda_id): []},
        es_const_editor=True,
        es_ing_editor=False,
    )

    assert "Aprobar Construcción" in html
    assert f"/bom/adendas/{adenda_id}/aprobar-construccion" in html


class FakePropuestaDB:
    def __init__(self, bom):
        self.bom = dict(bom)
        self.propuestas = []
        self.items = []
        self.historial = []

    async def get_bom_by_id(self, conn, id_bom):
        return dict(self.bom) if self.bom["id_bom"] == id_bom else None

    async def crear_propuesta_cambio(
        self, conn, id_bom, tipo_solicitante, motivo, lineas, creado_por
    ):
        propuesta = {
            "id_propuesta": uuid4(),
            "id_bom": id_bom,
            "tipo_solicitante": tipo_solicitante,
            "motivo": motivo,
            "lineas": list(lineas),
            "creado_por": creado_por,
            "estatus": "PENDIENTE_INGENIERIA",
            "lock_version": 0,
            "bom_version": self.bom["version"],
            "bom_estatus": self.bom["estatus"],
            "id_proyecto": self.bom["id_proyecto"],
            "id_paquete": self.bom["id_paquete"],
            "responsable_ing": self.bom.get("responsable_ing"),
        }
        self.propuestas.append(propuesta)
        return dict(propuesta)

    async def get_propuesta_cambio_by_id(self, conn, id_propuesta):
        for propuesta in self.propuestas:
            if propuesta["id_propuesta"] == id_propuesta:
                return dict(propuesta)
        return None

    async def get_propuesta_cambio_for_update(self, conn, id_propuesta):
        return await self.get_propuesta_cambio_by_id(conn, id_propuesta)

    async def get_bom_for_update(self, conn, id_bom):
        return await self.get_bom_by_id(conn, id_bom)

    async def lock_items_context_by_ids(self, conn, item_ids):
        return [dict(item) for item in self.items if item["id_item"] in item_ids]

    async def get_next_orden(self, conn, id_bom):
        return len(self.items) + 1

    async def agregar_item(self, conn, id_bom, descripcion, cantidad, **kwargs):
        item = {
            "id_item": uuid4(),
            "id_bom": id_bom,
            "descripcion": descripcion,
            "cantidad": cantidad,
            **kwargs,
        }
        self.items.append(item)
        return dict(item)

    async def set_item_grupos(self, conn, id_item, grupo_ids):
        for item in self.items:
            if item["id_item"] == id_item:
                item["grupo_ids"] = list(grupo_ids)

    async def registrar_historial(self, *args, **kwargs):
        self.historial.append((args, kwargs))

    async def actualizar_propuesta_cambio_revision(
        self, conn, id_propuesta, estatus, revisado_por, comentario_revision,
        lock_version_esperado,
    ):
        propuesta = await self.get_propuesta_cambio_by_id(conn, id_propuesta)
        if propuesta["lock_version"] != lock_version_esperado:
            return None
        propuesta["estatus"] = estatus
        propuesta["revisado_por"] = revisado_por
        propuesta["lock_version"] += 1
        for idx, actual in enumerate(self.propuestas):
            if actual["id_propuesta"] == id_propuesta:
                self.propuestas[idx].update(propuesta)
        return propuesta

    async def update_bom_estatus(self, conn, id_bom, estatus, **kwargs):
        self.bom["estatus"] = estatus.value if hasattr(estatus, "value") else estatus
        self.bom.update(kwargs)
        return dict(self.bom)

    async def update_bom_estatus_cas(
        self, conn, id_bom, estatus_esperado, lock_version_esperado,
        nuevo_estatus, **kwargs,
    ):
        if (
            self.bom["estatus"] != estatus_esperado
            or self.bom["lock_version"] != lock_version_esperado
        ):
            return None
        self.bom.update(
            estatus=nuevo_estatus,
            lock_version=self.bom["lock_version"] + 1,
            **kwargs,
        )
        return dict(self.bom)

    async def registrar_evento_outbox(self, *args, **kwargs):
        return {}


@pytest.mark.asyncio
async def test_crear_propuesta_cambio_no_muta_items():
    solicitante_id = uuid4()
    bom = _base_bom(
        estatus=EstatusBOM.EN_REVISION_CONST.value,
        jefe_construccion=solicitante_id,
    )
    db = FakePropuestaDB(bom)
    service = _service(db)

    propuesta = await service.crear_propuesta_cambio(
        FakeConn(),
        bom["id_bom"],
        solicitante_id,
        "CONSTRUCCION",
        "Ajuste menor",
        [{"accion": "AGREGAR", "datos": {"descripcion": "Canalizacion", "cantidad": 1}}],
        "USER",
    )

    assert propuesta["estatus"] == "PENDIENTE_INGENIERIA"
    assert db.items == []


@pytest.mark.asyncio
async def test_aprobar_propuesta_obra_aplica_y_vuelve_a_construccion():
    user_id = uuid4()
    solicitante_id = uuid4()
    bom = _base_bom(
        estatus=EstatusBOM.EN_REVISION_OBRA.value,
        coordinador_obra=solicitante_id,
        responsable_ing=user_id,
    )
    db = FakePropuestaDB(bom)
    service = _service(db)
    propuesta = await service.crear_propuesta_cambio(
        FakeConn(),
        bom["id_bom"],
        solicitante_id,
        "OBRA",
        "Agregar material de montaje",
        [
            {
                "accion": "AGREGAR",
                "datos": {"descripcion": "Abrazadera", "cantidad": 2},
                "grupo_ids": [1],
            }
        ],
        "USER",
    )

    await service.aprobar_propuesta_cambio(
        FakeTxConn(), propuesta["id_propuesta"], user_id, "USER",
        lock_version_esperado=0,
        bom_lock_version_esperado=0,
    )

    assert len(db.items) == 1
    assert db.items[0]["descripcion"] == "Abrazadera"
    assert db.items[0]["grupo_ids"] == [1]
    assert db.propuestas[0]["estatus"] == "APLICADA"
    assert db.bom["estatus"] == EstatusBOM.EN_REVISION_CONST.value


@pytest.mark.asyncio
async def test_crear_propuesta_bloquea_tipo_que_no_corresponde_al_estado():
    bom = _base_bom(estatus=EstatusBOM.EN_REVISION_OBRA.value)
    db = FakePropuestaDB(bom)
    service = _service(db)

    with pytest.raises(ValueError, match="no corresponde al estado actual"):
        await service.crear_propuesta_cambio(
            FakeConn(),
            bom["id_bom"],
            uuid4(),
            "CONSTRUCCION",
            "Intento invalido",
            [{"accion": "AGREGAR", "datos": {"descripcion": "Canalizacion", "cantidad": 1}}],
            "ADMIN",
        )

    assert db.propuestas == []


@pytest.mark.asyncio
async def test_crear_propuesta_bloquea_estado_fuera_de_revision_obra_const():
    bom = _base_bom(estatus=EstatusBOM.APROBADO_CONST.value)
    db = FakePropuestaDB(bom)
    service = _service(db)

    with pytest.raises(ValueError, match="revision de Obra o Construccion"):
        await service.crear_propuesta_cambio(
            FakeConn(),
            bom["id_bom"],
            uuid4(),
            "CONSTRUCCION",
            "Intento tardio",
            [{"accion": "AGREGAR", "datos": {"descripcion": "Canalizacion", "cantidad": 1}}],
            "ADMIN",
        )

    assert db.propuestas == []
