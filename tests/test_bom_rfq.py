"""
Tests de RFQ en tablas propias (doc 35, _Planes_Activos/._BOOM/35-rfq-pdf-neutro-compras.md):
tb_bom_rfq/tb_bom_rfq_items/tb_bom_rfq_historial, sin bloqueo de items del BOM.
"""

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


def _bom(bom_id, estatus="APROBADO_CONST"):
    return {"id_bom": bom_id, "id_proyecto": uuid4(), "estatus": estatus}


def _bom_item(item_id, id_bom, cantidad=3, **extra):
    data = {"id_item": item_id, "id_bom": id_bom, "cantidad": cantidad, "descripcion": "Item X"}
    data.update(extra)
    return data


class FakeDB:
    def __init__(self, bom, items_bd):
        self.bom = bom
        self.items_bd = {str(i["id_item"]): i for i in items_bd}
        self.rfqs = {}
        self.rfq_items = {}
        self.historial = []
        self.lock_calls = []

    async def get_bom_by_id(self, conn, id_bom):
        return self.bom if self.bom["id_bom"] == id_bom else None

    async def get_items_by_ids(self, conn, item_ids):
        return [self.items_bd[str(i)] for i in item_ids if str(i) in self.items_bd]

    async def crear_rfq(self, conn, bom_id, creado_por, notas):
        rfq_id = uuid4()
        rfq = {
            "id": rfq_id, "bom_id": bom_id, "creado_por": creado_por,
            "notas": notas, "lock_version": 0,
        }
        self.rfqs[rfq_id] = rfq
        self.rfq_items[rfq_id] = []
        return dict(rfq)

    async def agregar_items_rfq(self, conn, rfq_id, items):
        self.rfq_items.setdefault(rfq_id, []).extend(items)

    async def get_rfq_by_id(self, conn, rfq_id):
        rfq = self.rfqs.get(rfq_id)
        return dict(rfq) if rfq else None

    async def incrementar_lock_rfq(self, conn, rfq_id, lock_version_esperado):
        self.lock_calls.append((rfq_id, lock_version_esperado))
        rfq = self.rfqs.get(rfq_id)
        if not rfq or rfq["lock_version"] != lock_version_esperado:
            return None
        rfq["lock_version"] += 1
        return dict(rfq)

    async def quitar_item_rfq(self, conn, rfq_id, bom_item_id):
        antes = len(self.rfq_items.get(rfq_id, []))
        self.rfq_items[rfq_id] = [
            i for i in self.rfq_items.get(rfq_id, []) if i["bom_item_id"] != bom_item_id
        ]
        return antes - len(self.rfq_items[rfq_id])

    async def registrar_historial_rfq(self, conn, rfq_id, usuario_id, accion, detalle=None):
        self.historial.append((rfq_id, usuario_id, accion, detalle))


def make_service(bom, items_bd):
    svc = BomService()
    svc.db = FakeDB(bom, items_bd)
    return svc


@pytest.mark.asyncio
async def test_crear_rfq_no_requiere_lock_de_bom_ni_bloquea_items():
    bom_id = uuid4()
    item_id = uuid4()
    svc = make_service(_bom(bom_id), [_bom_item(item_id, bom_id)])

    rfq = await svc.crear_rfq(FakeConn(), bom_id, [item_id], uuid4())

    assert rfq["total_items"] == 1
    assert svc.db.rfq_items[rfq["id"]][0]["bom_item_id"] == item_id
    assert svc.db.historial[0][2] == "CREADO"


@pytest.mark.asyncio
async def test_crear_rfq_rechaza_item_de_otro_bom():
    bom_id = uuid4()
    otro_bom_id = uuid4()
    item_id = uuid4()
    svc = make_service(_bom(bom_id), [_bom_item(item_id, otro_bom_id)])

    with pytest.raises(ValueError, match="otro paquete BOM"):
        await svc.crear_rfq(FakeConn(), bom_id, [item_id], uuid4())


@pytest.mark.asyncio
async def test_crear_rfq_rechaza_bom_no_cotizable():
    bom_id = uuid4()
    item_id = uuid4()
    svc = make_service(_bom(bom_id, estatus="BORRADOR"), [_bom_item(item_id, bom_id)])

    with pytest.raises(ValueError, match="aprobados por Construccion"):
        await svc.crear_rfq(FakeConn(), bom_id, [item_id], uuid4())


@pytest.mark.asyncio
async def test_crear_rfq_filtra_items_ya_autorizados():
    """El servicio (no solo el router) debe descartar items AUTORIZADO/PAGADO/FACTURADO."""
    bom_id = uuid4()
    disponible_id = uuid4()
    autorizado_id = uuid4()
    svc = make_service(_bom(bom_id), [
        _bom_item(disponible_id, bom_id),
        _bom_item(autorizado_id, bom_id, estatus_compra="AUTORIZADO"),
    ])

    rfq = await svc.crear_rfq(FakeConn(), bom_id, [disponible_id, autorizado_id], uuid4())

    assert rfq["total_items"] == 1
    assert svc.db.rfq_items[rfq["id"]][0]["bom_item_id"] == disponible_id


@pytest.mark.asyncio
async def test_crear_rfq_rechaza_si_todos_los_items_no_disponibles():
    bom_id = uuid4()
    item_id = uuid4()
    svc = make_service(_bom(bom_id), [_bom_item(item_id, bom_id, estatus_compra="FACTURADO")])

    with pytest.raises(ValueError, match="autorizados, pagados o facturados"):
        await svc.crear_rfq(FakeConn(), bom_id, [item_id], uuid4())


@pytest.mark.asyncio
async def test_quitar_item_rfq_usa_cas_y_registra_historial():
    bom_id = uuid4()
    item_id = uuid4()
    svc = make_service(_bom(bom_id), [_bom_item(item_id, bom_id)])
    rfq = await svc.crear_rfq(FakeConn(), bom_id, [item_id], uuid4())

    actualizado = await svc.quitar_item_rfq(
        FakeConn(), rfq["id"], item_id, uuid4(), lock_version_esperado=0,
    )

    assert actualizado["lock_version"] == 1
    assert svc.db.rfq_items[rfq["id"]] == []
    assert svc.db.historial[-1][2] == "ITEM_QUITADO"


@pytest.mark.asyncio
async def test_quitar_item_rfq_falla_si_lock_no_coincide():
    bom_id = uuid4()
    item_id = uuid4()
    svc = make_service(_bom(bom_id), [_bom_item(item_id, bom_id)])
    rfq = await svc.crear_rfq(FakeConn(), bom_id, [item_id], uuid4())

    with pytest.raises(ValueError, match="cambio"):
        await svc.quitar_item_rfq(
            FakeConn(), rfq["id"], item_id, uuid4(), lock_version_esperado=99,
        )


@pytest.mark.asyncio
async def test_agregar_item_rfq_rechaza_item_ya_autorizado():
    bom_id = uuid4()
    inicial_id = uuid4()
    pagado_id = uuid4()
    svc = make_service(_bom(bom_id), [
        _bom_item(inicial_id, bom_id),
        _bom_item(pagado_id, bom_id, estatus_compra="PAGADO"),
    ])
    rfq = await svc.crear_rfq(FakeConn(), bom_id, [inicial_id], uuid4())

    with pytest.raises(ValueError, match="autorizado, pagado o facturado"):
        await svc.agregar_item_rfq(
            FakeConn(), rfq["id"], pagado_id, 2, None, uuid4(), lock_version_esperado=0,
        )
    assert len(svc.db.rfq_items[rfq["id"]]) == 1
