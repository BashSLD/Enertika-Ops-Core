from uuid import uuid4

import pytest

from core.bom.service import BomService


class FakeConn:
    def transaction(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _bom(bom_id):
    return {
        "id_bom": bom_id,
        "id_proyecto": uuid4(),
        "estatus": "APROBADO_FINAL",
        "version": 1,
    }


def _item(item_id, bom_id, **extra):
    data = {
        "id_item": item_id,
        "id_bom": bom_id,
        "descripcion": "Modulo FV",
        "cantidad": 10,
        "unidad_medida": "pza",
        "id_categoria": 11,
        "precio_unitario": 100,
        "tipo_partida": "MATERIAL",
        "moneda": "MXN",
        "activo": True,
        "estatus_compra": "SIN_COTIZAR",
        "tipo_origen_item": "BASE",
        "estatus_ejecucion": None,
    }
    data.update(extra)
    return data


class FakeAdendaDB:
    def __init__(self, bom, items=None):
        self.bom = bom
        self.items = {item["id_item"]: dict(item) for item in (items or [])}
        self.adendas = []
        self.adenda_items = []
        self.execution_updates = []
        self.historial = []
        self.grupos = []

    async def get_bom_by_id(self, conn, id_bom):
        return dict(self.bom) if id_bom == self.bom["id_bom"] else None

    async def get_item_by_id(self, conn, id_item):
        item = self.items.get(id_item)
        return dict(item) if item else None

    async def crear_adenda(self, conn, id_bom_base, tipo_adenda, motivo, creado_por):
        adenda = {
            "id_adenda": uuid4(),
            "id_bom_base": id_bom_base,
            "tipo_adenda": tipo_adenda,
            "motivo": motivo,
            "creado_por": creado_por,
        }
        self.adendas.append(adenda)
        return adenda

    async def registrar_adenda_item(
        self, conn, id_adenda, tipo_linea, motivo,
        id_item_origen=None, id_item_bom=None,
    ):
        row = {
            "id_adenda": id_adenda,
            "tipo_linea": tipo_linea,
            "motivo": motivo,
            "id_item_origen": id_item_origen,
            "id_item_bom": id_item_bom,
        }
        self.adenda_items.append(row)
        return row

    async def upsert_item_ejecucion(self, conn, id_item, updated_by=None, **campos):
        self.execution_updates.append((id_item, updated_by, campos))
        self.items[id_item].update(campos)
        return dict(self.items[id_item])

    async def registrar_historial(self, *args, **kwargs):
        self.historial.append((args, kwargs))

    async def get_next_orden(self, conn, id_bom):
        return len(self.items) + 1

    async def agregar_item(self, conn, id_bom, descripcion, cantidad, **kwargs):
        item_id = uuid4()
        item = {
            "id_item": item_id,
            "id_bom": id_bom,
            "descripcion": descripcion,
            "cantidad": cantidad,
            "activo": True,
            "estatus_ejecucion": None,
            "tipo_origen_item": "BASE",
            "id_item_reemplazado": None,
            "motivo_adenda": None,
            "creado_en_adenda": None,
            **kwargs,
        }
        self.items[item_id] = item
        return dict(item)

    async def set_item_grupos(self, conn, id_item, grupo_ids):
        self.grupos.append((id_item, list(grupo_ids)))

    async def get_adendas_by_bom(self, conn, id_bom):
        return [a for a in self.adendas if a["id_bom_base"] == id_bom]


def _service(db):
    svc = BomService()
    svc.db = db
    return svc


@pytest.mark.asyncio
async def test_cerrar_item_sin_compra_registra_adenda_y_no_desactiva_base():
    bom_id = uuid4()
    item_id = uuid4()
    user_id = uuid4()
    db = FakeAdendaDB(_bom(bom_id), [_item(item_id, bom_id)])
    svc = _service(db)

    updated = await svc.cerrar_item_sin_compra(
        FakeConn(), item_id, user_id, "Proveedor sin disponibilidad"
    )

    assert updated["activo"] is True
    assert updated["estatus_ejecucion"] == "NO_ADQUIRIDO"
    assert db.adendas[0]["tipo_adenda"] == "NO_ADQUIRIDO"
    assert db.adenda_items == [
        {
            "id_adenda": db.adendas[0]["id_adenda"],
            "tipo_linea": "NO_ADQUIRIDO",
            "motivo": "Proveedor sin disponibilidad",
            "id_item_origen": item_id,
            "id_item_bom": None,
        }
    ]


@pytest.mark.asyncio
async def test_crear_reemplazo_marca_origen_y_crea_item_cotizable():
    bom_id = uuid4()
    item_id = uuid4()
    user_id = uuid4()
    db = FakeAdendaDB(_bom(bom_id), [_item(item_id, bom_id)])
    svc = _service(db)

    reemplazo = await svc.crear_reemplazo_item(
        FakeConn(), item_id, user_id,
        descripcion="Modulo FV equivalente",
        cantidad=10,
        grupo_ids=[1, 2],
        motivo="Cambio por disponibilidad",
        id_categoria=11,
        unidad_medida="pza",
    )

    assert reemplazo["tipo_origen_item"] == "REEMPLAZO"
    assert reemplazo["id_item_reemplazado"] == item_id
    assert reemplazo["motivo_adenda"] == "Cambio por disponibilidad"
    assert db.items[item_id]["estatus_ejecucion"] == "REEMPLAZADO"
    assert db.grupos == [(reemplazo["id_item"], [1, 2])]
    assert db.adenda_items[0]["id_item_origen"] == item_id
    assert db.adenda_items[0]["id_item_bom"] == reemplazo["id_item"]


@pytest.mark.asyncio
async def test_agregar_fuera_scope_crea_item_separado_del_presupuesto_base():
    bom_id = uuid4()
    user_id = uuid4()
    db = FakeAdendaDB(_bom(bom_id))
    svc = _service(db)

    item = await svc.agregar_fuera_scope(
        FakeConn(), bom_id, user_id,
        descripcion="Base adicional",
        cantidad=1,
        grupo_ids=[3],
        motivo="Solicitud de obra",
        unidad_medida="servicio",
    )

    assert item["tipo_origen_item"] == "FUERA_SCOPE"
    assert item["id_item_reemplazado"] is None
    assert item["creado_en_adenda"] == db.adendas[0]["id_adenda"]
    assert db.adendas[0]["tipo_adenda"] == "FUERA_SCOPE"
    assert db.adenda_items[0]["id_item_bom"] == item["id_item"]


@pytest.mark.asyncio
async def test_no_permite_reemplazar_item_ya_cerrado():
    bom_id = uuid4()
    item_id = uuid4()
    db = FakeAdendaDB(
        _bom(bom_id),
        [_item(item_id, bom_id, estatus_ejecucion="NO_ADQUIRIDO")],
    )
    svc = _service(db)

    with pytest.raises(ValueError, match="ya esta cerrado"):
        await svc.crear_reemplazo_item(
            FakeConn(), item_id, uuid4(),
            descripcion="Reemplazo",
            cantidad=1,
            grupo_ids=[1],
            motivo="Cambio",
        )


@pytest.mark.asyncio
async def test_no_permite_cerrar_item_autorizado():
    bom_id = uuid4()
    item_id = uuid4()
    db = FakeAdendaDB(
        _bom(bom_id),
        [_item(item_id, bom_id, estatus_compra="AUTORIZADO")],
    )
    svc = _service(db)

    with pytest.raises(ValueError, match="autorizado, pagado o facturado"):
        await svc.cerrar_item_sin_compra(
            FakeConn(), item_id, uuid4(), "Ya esta autorizado"
        )


@pytest.mark.asyncio
async def test_no_permite_reemplazar_item_autorizado():
    bom_id = uuid4()
    item_id = uuid4()
    db = FakeAdendaDB(
        _bom(bom_id),
        [_item(item_id, bom_id, estatus_compra="AUTORIZADO")],
    )
    svc = _service(db)

    with pytest.raises(ValueError, match="autorizado, pagado o facturado"):
        await svc.crear_reemplazo_item(
            FakeConn(), item_id, uuid4(),
            descripcion="Reemplazo",
            cantidad=1,
            grupo_ids=[1],
            motivo="Cambio",
        )
