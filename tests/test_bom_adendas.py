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
            "id_bom": id_bom_base,
            "tipo_adenda": tipo_adenda,
            "motivo": motivo,
            "creado_por": creado_por,
            "estatus": "PENDIENTE_CONSTRUCCION",
            "bom_estatus": self.bom["estatus"],
            "bom_version": self.bom["version"],
            "jefe_construccion": self.bom.get("jefe_construccion"),
            "responsable_ing": self.bom.get("responsable_ing"),
        }
        self.adendas.append(adenda)
        return adenda

    async def registrar_adenda_item(
        self, conn, id_adenda, tipo_linea, motivo,
        id_item_origen=None, id_item_bom=None, datos_item=None, grupo_ids=None,
    ):
        row = {
            "id_adenda_item": uuid4(),
            "id_adenda": id_adenda,
            "tipo_linea": tipo_linea,
            "motivo": motivo,
            "id_item_origen": id_item_origen,
            "id_item_bom": id_item_bom,
            "datos_item": datos_item or {},
            "grupo_ids": list(grupo_ids or []),
        }
        self.adenda_items.append(row)
        return row

    async def get_adenda_by_id(self, conn, id_adenda):
        for adenda in self.adendas:
            if adenda["id_adenda"] == id_adenda:
                return dict(adenda)
        return None

    async def get_adenda_items(self, conn, id_adenda):
        return [dict(i) for i in self.adenda_items if i["id_adenda"] == id_adenda]

    async def marcar_adenda_construccion(
        self, conn, id_adenda, user_id, requiere_ingenieria
    ):
        adenda = await self.get_adenda_by_id(conn, id_adenda)
        adenda["estatus"] = (
            "PENDIENTE_INGENIERIA" if requiere_ingenieria else "APROBADA"
        )
        adenda["requiere_aprobacion_ingenieria"] = requiere_ingenieria
        for idx, actual in enumerate(self.adendas):
            if actual["id_adenda"] == id_adenda:
                self.adendas[idx].update(adenda)
        return adenda

    async def aprobar_adenda_ingenieria(self, conn, id_adenda, user_id):
        adenda = await self.get_adenda_by_id(conn, id_adenda)
        adenda["estatus"] = "APROBADA"
        for idx, actual in enumerate(self.adendas):
            if actual["id_adenda"] == id_adenda:
                self.adendas[idx].update(adenda)
        return adenda

    async def rechazar_adenda(self, conn, id_adenda, user_id, motivo_rechazo):
        adenda = await self.get_adenda_by_id(conn, id_adenda)
        adenda["estatus"] = "RECHAZADA"
        adenda["motivo_rechazo"] = motivo_rechazo
        for idx, actual in enumerate(self.adendas):
            if actual["id_adenda"] == id_adenda:
                self.adendas[idx].update(adenda)
        return adenda

    async def vincular_adenda_item_bom(self, conn, id_adenda_item, id_item_bom):
        for row in self.adenda_items:
            if row["id_adenda_item"] == id_adenda_item:
                row["id_item_bom"] = id_item_bom
                return dict(row)
        return None

    async def get_item_compra_bloqueante(self, conn, id_item):
        item = self.items.get(id_item, {})
        return {
            "tiene_cotizacion_seleccionada": item.get("cotizacion_seleccionada", False),
            "tiene_autorizacion_activa": item.get("autorizacion_activa", False),
        }

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

    async def set_item_grupos_operativos(self, conn, id_item, grupo_ids, user_id=None):
        self.grupos.append((id_item, list(grupo_ids)))

    async def get_adendas_by_bom(self, conn, id_bom):
        return [a for a in self.adendas if a["id_bom_base"] == id_bom]

    async def cancelar_adenda(self, conn, id_adenda, user_id):
        adenda = await self.get_adenda_by_id(conn, id_adenda)
        adenda["estatus"] = "CANCELADA"
        adenda["cancelado_por"] = user_id
        for idx, actual in enumerate(self.adendas):
            if actual["id_adenda"] == id_adenda:
                self.adendas[idx].update(adenda)
        return adenda


def _service(db):
    svc = BomService()
    svc.db = db
    return svc


@pytest.mark.asyncio
async def test_cerrar_item_sin_compra_registra_adenda_y_no_muta_base():
    bom_id = uuid4()
    item_id = uuid4()
    user_id = uuid4()
    db = FakeAdendaDB(_bom(bom_id), [_item(item_id, bom_id)])
    svc = _service(db)

    adenda = await svc.cerrar_item_sin_compra(
        FakeConn(), item_id, user_id, "Proveedor sin disponibilidad"
    )

    assert db.items[item_id]["activo"] is True
    assert db.items[item_id]["estatus_ejecucion"] is None
    assert adenda["estatus"] == "PENDIENTE_CONSTRUCCION"
    assert db.adendas[0]["tipo_adenda"] == "NO_ADQUIRIDO"
    assert db.adenda_items == [
        {
            "id_adenda_item": db.adenda_items[0]["id_adenda_item"],
            "id_adenda": db.adendas[0]["id_adenda"],
            "tipo_linea": "NO_ADQUIRIDO",
            "motivo": "Proveedor sin disponibilidad",
            "id_item_origen": item_id,
            "id_item_bom": None,
            "datos_item": {},
            "grupo_ids": [],
        }
    ]


@pytest.mark.asyncio
async def test_aprobar_cierre_sin_compra_aplica_cambio():
    bom_id = uuid4()
    item_id = uuid4()
    user_id = uuid4()
    db = FakeAdendaDB(_bom(bom_id), [_item(item_id, bom_id)])
    svc = _service(db)

    adenda = await svc.cerrar_item_sin_compra(
        FakeConn(), item_id, user_id, "Proveedor sin disponibilidad"
    )

    await svc.aprobar_adenda_construccion(
        FakeConn(), adenda["id_adenda"], user_id, "ADMIN"
    )

    assert db.items[item_id]["estatus_ejecucion"] == "NO_ADQUIRIDO"
    assert db.adendas[0]["estatus"] == "APROBADA"


@pytest.mark.asyncio
async def test_crear_reemplazo_queda_pendiente_hasta_aprobacion():
    bom_id = uuid4()
    item_id = uuid4()
    user_id = uuid4()
    db = FakeAdendaDB(_bom(bom_id), [_item(item_id, bom_id)])
    svc = _service(db)

    adenda = await svc.crear_reemplazo_item(
        FakeConn(), item_id, user_id,
        descripcion="Modulo FV equivalente",
        cantidad=10,
        grupo_ids=[1, 2],
        motivo="Cambio por disponibilidad",
        id_categoria=11,
        unidad_medida="pza",
    )

    assert adenda["estatus"] == "PENDIENTE_CONSTRUCCION"
    assert len(db.items) == 1
    assert db.items[item_id]["estatus_ejecucion"] is None

    await svc.aprobar_adenda_construccion(
        FakeConn(), adenda["id_adenda"], user_id, "ADMIN"
    )

    reemplazos = [
        item for item in db.items.values()
        if item.get("tipo_origen_item") == "REEMPLAZO"
    ]
    assert len(reemplazos) == 1
    reemplazo = reemplazos[0]
    assert reemplazo["tipo_origen_item"] == "REEMPLAZO"
    assert reemplazo["id_item_reemplazado"] == item_id
    assert reemplazo["motivo_adenda"] == "Cambio por disponibilidad"
    assert db.items[item_id]["estatus_ejecucion"] == "REEMPLAZADO"
    assert db.grupos == [(reemplazo["id_item"], [1, 2])]
    assert db.adenda_items[0]["id_item_origen"] == item_id
    assert db.adenda_items[0]["id_item_bom"] == reemplazo["id_item"]


@pytest.mark.asyncio
async def test_agregar_fuera_scope_crea_item_al_aprobar():
    bom_id = uuid4()
    user_id = uuid4()
    db = FakeAdendaDB(_bom(bom_id))
    svc = _service(db)

    adenda = await svc.agregar_fuera_scope(
        FakeConn(), bom_id, user_id,
        descripcion="Base adicional",
        cantidad=1,
        grupo_ids=[3],
        motivo="Solicitud de obra",
        unidad_medida="servicio",
    )

    assert len(db.items) == 0
    await svc.aprobar_adenda_construccion(
        FakeConn(), adenda["id_adenda"], user_id, "ADMIN"
    )

    item = next(iter(db.items.values()))
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

    with pytest.raises(ValueError, match="cotizado, autorizado, pagado o facturado"):
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

    with pytest.raises(ValueError, match="cotizado, autorizado, pagado o facturado"):
        await svc.crear_reemplazo_item(
            FakeConn(), item_id, uuid4(),
            descripcion="Reemplazo",
            cantidad=1,
            grupo_ids=[1],
            motivo="Cambio",
        )


@pytest.mark.asyncio
async def test_adenda_con_ok_ingenieria_no_aplica_hasta_aprobacion_tecnica():
    bom_id = uuid4()
    item_id = uuid4()
    user_id = uuid4()
    db = FakeAdendaDB(_bom(bom_id), [_item(item_id, bom_id)])
    svc = _service(db)

    adenda = await svc.crear_reemplazo_item(
        FakeConn(), item_id, user_id,
        descripcion="Modulo FV equivalente",
        cantidad=10,
        grupo_ids=[1],
        motivo="Cambio tecnico",
        id_categoria=11,
        unidad_medida="pza",
    )

    updated = await svc.aprobar_adenda_construccion(
        FakeConn(), adenda["id_adenda"], user_id, "ADMIN",
        requiere_ingenieria=True,
    )

    assert updated["estatus"] == "PENDIENTE_INGENIERIA"
    assert len(db.items) == 1

    await svc.aprobar_adenda_ingenieria(
        FakeConn(), adenda["id_adenda"], user_id, "ADMIN"
    )

    assert len(db.items) == 2
    assert db.adendas[0]["estatus"] == "APROBADA"


@pytest.mark.asyncio
async def test_aprobar_ingenieria_falla_si_bom_no_es_aprobado_final():
    bom_id = uuid4()
    user_id = uuid4()
    bom = {"id_bom": bom_id, "id_proyecto": uuid4(), "estatus": "BORRADOR", "version": 1}
    db = FakeAdendaDB(bom)
    adenda_id = uuid4()
    db.adendas.append({
        "id_adenda": adenda_id,
        "id_bom_base": bom_id,
        "id_bom": bom_id,
        "tipo_adenda": "NO_ADQUIRIDO",
        "motivo": "Test",
        "estatus": "PENDIENTE_INGENIERIA",
        "bom_estatus": "BORRADOR",
        "bom_version": 1,
        "jefe_construccion": None,
        "responsable_ing": None,
    })
    svc = _service(db)

    with pytest.raises(ValueError, match="Solo se pueden aprobar adendas en BOM aprobado final"):
        await svc.aprobar_adenda_ingenieria(FakeConn(), adenda_id, user_id, "ADMIN")


@pytest.mark.asyncio
async def test_cancelar_adenda_pendiente_construccion_ok():
    bom_id = uuid4()
    item_id = uuid4()
    user_id = uuid4()
    db = FakeAdendaDB(_bom(bom_id), [_item(item_id, bom_id)])
    svc = _service(db)

    adenda = await svc.cerrar_item_sin_compra(
        FakeConn(), item_id, user_id, "Proveedor sin stock"
    )
    assert adenda["estatus"] == "PENDIENTE_CONSTRUCCION"

    resultado = await svc.cancelar_adenda(FakeConn(), adenda["id_adenda"], user_id, "ADMIN")

    assert resultado["estatus"] == "CANCELADA"
    assert db.items[item_id]["estatus_ejecucion"] is None


@pytest.mark.asyncio
async def test_cancelar_adenda_falla_si_no_pendiente_construccion():
    bom_id = uuid4()
    item_id = uuid4()
    user_id = uuid4()
    db = FakeAdendaDB(_bom(bom_id), [_item(item_id, bom_id)])
    svc = _service(db)

    adenda = await svc.cerrar_item_sin_compra(
        FakeConn(), item_id, user_id, "Proveedor sin stock"
    )
    await svc.aprobar_adenda_construccion(
        FakeConn(), adenda["id_adenda"], user_id, "ADMIN", requiere_ingenieria=True
    )
    assert db.adendas[0]["estatus"] == "PENDIENTE_INGENIERIA"

    with pytest.raises(ValueError, match="Solo se pueden cancelar adendas pendientes de Construccion"):
        await svc.cancelar_adenda(FakeConn(), adenda["id_adenda"], user_id, "ADMIN")
