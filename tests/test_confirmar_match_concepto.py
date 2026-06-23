"""
B3b: orquestacion de `BomService.confirmar_match_concepto`.

- Asignar (id_bom_item set) -> persiste el match y marca el item como FACTURADO.
- Desasignar (id_bom_item None) -> persiste la limpieza y NO toca estatus_compra.

El SQL real (CASE ALTA/HUMANO vs NULL) vive en la capa db y se valida via MCP/EXPLAIN;
aqui se prueba la logica de ramas del service con un db falso.
"""

from uuid import uuid4

import pytest

from core.bom.service import BomService


class FakeConn:
    """Conn minimo: solo necesita soportar `async with conn.transaction()`."""

    def transaction(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeDB:
    def __init__(self):
        self.confirm_calls = []
        self.estatus_calls = []

    async def confirmar_match_concepto(self, conn, historial_id, id_bom_item):
        self.confirm_calls.append((historial_id, id_bom_item))
        return {"historial_id": historial_id, "id_bom_item": id_bom_item}

    async def update_items_estatus_compra(self, conn, item_ids, estatus):
        self.estatus_calls.append((list(item_ids), estatus))


def _svc():
    svc = BomService()
    svc.db = FakeDB()
    return svc


@pytest.mark.asyncio
async def test_asignar_marca_item_facturado():
    svc = _svc()
    hist, item = uuid4(), uuid4()

    res = await svc.confirmar_match_concepto(FakeConn(), hist, item)

    assert res["id_bom_item"] == item
    assert svc.db.confirm_calls == [(hist, item)]
    assert svc.db.estatus_calls == [([item], "FACTURADO")]


@pytest.mark.asyncio
async def test_desasignar_no_toca_estatus():
    svc = _svc()
    hist = uuid4()

    res = await svc.confirmar_match_concepto(FakeConn(), hist, None)

    assert res["id_bom_item"] is None
    assert svc.db.confirm_calls == [(hist, None)]
    assert svc.db.estatus_calls == []


@pytest.mark.asyncio
async def test_concepto_inexistente_no_marca_estatus():
    # Si el db no encuentra el concepto (None), no se intenta marcar FACTURADO.
    svc = BomService()

    class _DBNone(FakeDB):
        async def confirmar_match_concepto(self, conn, historial_id, id_bom_item):
            return None

    svc.db = _DBNone()
    res = await svc.confirmar_match_concepto(FakeConn(), uuid4(), uuid4())

    assert res is None
    assert svc.db.estatus_calls == []
