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


class FakeBulkDB:
    def __init__(self, items, *, es_jefe=False, es_asignado=False):
        self.items = {item["id_item"]: item for item in items}
        self.es_jefe = es_jefe
        self.es_asignado = es_asignado
        self.grupo_calls = []
        self.historial_calls = []

    async def get_items_context_by_ids(self, conn, item_ids):
        return [self.items[item_id] for item_id in item_ids if item_id in self.items]

    async def get_item_by_id(self, conn, item_id):
        return self.items.get(item_id)

    async def set_item_grupos(self, conn, item_id, grupo_ids):
        self.grupo_calls.append((item_id, list(grupo_ids)))

    async def registrar_historial(self, *args, **kwargs):
        self.historial_calls.append((args, kwargs))

    async def usuario_tiene_rol_org(self, conn, user_id, rol_org):
        return self.es_jefe

    async def usuario_tiene_asignacion_proyecto(
        self, conn, id_proyecto, user_id, rol_proyecto, area
    ):
        return self.es_asignado


def _item(item_id, bom_id, proyecto_id, *, estatus="BORRADOR", activo=True, bloqueado=False):
    return {
        "id_item": item_id,
        "id_bom": bom_id,
        "id_proyecto": proyecto_id,
        "bom_estatus": estatus,
        "bom_version": 1,
        "activo": activo,
        "bloqueado": bloqueado,
    }


def _service(items, **db_kwargs):
    svc = BomService()
    svc.db = FakeBulkDB(items, **db_kwargs)
    return svc


@pytest.mark.asyncio
async def test_bulk_grupos_omite_item_de_otro_bom_sin_mutarlo():
    bom_id = uuid4()
    otro_bom_id = uuid4()
    proyecto_id = uuid4()
    item_valido = uuid4()
    item_externo = uuid4()
    svc = _service([
        _item(item_valido, bom_id, proyecto_id),
        _item(item_externo, otro_bom_id, proyecto_id),
    ])

    resultado = await svc.editar_items_bulk(
        FakeConn(), bom_id, [item_valido, item_externo], uuid4(),
        "construccion", "grupos", grupo_ids=[1],
    )

    assert resultado["actualizados"] == 1
    assert resultado["omitidos"] == [
        {"id_item": item_externo, "motivo": "El item no pertenece a este BOM"}
    ]
    assert svc.db.grupo_calls == [(item_valido, [1])]


@pytest.mark.asyncio
async def test_bulk_grupos_omite_items_bloqueados_o_en_estado_final():
    bom_id = uuid4()
    proyecto_id = uuid4()
    item_bloqueado = uuid4()
    item_final = uuid4()
    svc = _service([
        _item(item_bloqueado, bom_id, proyecto_id, bloqueado=True),
        _item(item_final, bom_id, proyecto_id, estatus="APROBADO_FINAL"),
    ])

    resultado = await svc.editar_items_bulk(
        FakeConn(), bom_id, [item_bloqueado, item_final], uuid4(),
        "construccion", "grupos", grupo_ids=[1, 2],
    )

    assert resultado["actualizados"] == 0
    assert [omitido["id_item"] for omitido in resultado["omitidos"]] == [
        item_bloqueado,
        item_final,
    ]
    assert svc.db.grupo_calls == []


@pytest.mark.asyncio
async def test_bulk_grupos_ingenieria_exige_jefe_o_ingeniero_asignado():
    bom_id = uuid4()
    proyecto_id = uuid4()
    item_id = uuid4()
    svc = _service([_item(item_id, bom_id, proyecto_id)])

    resultado = await svc.editar_items_bulk(
        FakeConn(), bom_id, [item_id], uuid4(),
        "ingenieria", "grupos", grupo_ids=[1],
    )

    assert resultado["actualizados"] == 0
    assert resultado["omitidos"] == [
        {
            "id_item": item_id,
            "motivo": (
                "Solo el jefe de Ingenieria o el ingeniero asignado pueden "
                "crear o retomar el BOM"
            ),
        }
    ]
    assert svc.db.grupo_calls == []

