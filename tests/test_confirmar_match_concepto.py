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
        self.ejecucion_calls = []

    async def confirmar_match_concepto(
        self, conn, historial_id, id_bom_item, id_bom_item_anterior,
        lock_version_esperado, id_grupo,
    ):
        self.confirm_calls.append((
            historial_id, id_bom_item, id_bom_item_anterior,
            lock_version_esperado, id_grupo,
        ))
        return {"historial_id": historial_id, "id_bom_item": id_bom_item}

    async def lock_items_context_by_ids(self, conn, item_ids):
        return [
            {"id_item": item_id, "ejecucion_lock_version": 0}
            for item_id in item_ids
        ]

    async def actualizar_estatus_compra_items(self, conn, item_ids, estatus):
        self.estatus_calls.append((list(item_ids), estatus))

    async def upsert_item_ejecucion(
        self, conn, item_id, updated_by=None, lock_version_esperado=None, **campos,
    ):
        self.ejecucion_calls.append(
            (item_id, updated_by, lock_version_esperado, campos)
        )
        return {"id_item": item_id, "lock_version": lock_version_esperado + 1}


def _svc():
    svc = BomService()
    svc.db = FakeDB()
    return svc


@pytest.mark.asyncio
async def test_asignar_marca_item_facturado():
    svc = _svc()
    hist, item = uuid4(), uuid4()

    res = await svc.confirmar_match_concepto(FakeConn(), hist, item, None, 0)

    assert res["id_bom_item"] == item
    assert svc.db.confirm_calls == [(hist, item, None, 0, None)]
    assert svc.db.estatus_calls == [([item], "FACTURADO")]
    assert svc.db.ejecucion_calls == [
        (item, None, 0, {"estatus_ejecucion": "FACTURADO"})
    ]


@pytest.mark.asyncio
async def test_desasignar_no_toca_estatus():
    svc = _svc()
    hist = uuid4()

    item_anterior = uuid4()
    res = await svc.confirmar_match_concepto(
        FakeConn(), hist, None, item_anterior, 3
    )

    assert res["id_bom_item"] is None
    assert svc.db.confirm_calls == [(hist, None, item_anterior, 3, None)]
    assert svc.db.estatus_calls == []
    assert svc.db.ejecucion_calls == []


@pytest.mark.asyncio
async def test_concepto_inexistente_no_marca_estatus():
    # Si el db no encuentra el concepto (None), no se intenta marcar FACTURADO.
    svc = BomService()

    class _DBNone(FakeDB):
        async def confirmar_match_concepto(
            self, conn, historial_id, id_bom_item, id_bom_item_anterior,
            lock_version_esperado, id_grupo,
        ):
            return None

    svc.db = _DBNone()
    with pytest.raises(ValueError, match="El concepto cambio"):
        await svc.confirmar_match_concepto(
            FakeConn(), uuid4(), uuid4(), None, 0
        )
    assert svc.db.estatus_calls == []
