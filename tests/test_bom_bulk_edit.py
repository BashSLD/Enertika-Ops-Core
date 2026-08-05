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
    def __init__(self, items, *, actor_id=None, es_jefe=False, es_asignado=False):
        self.items = {item["id_item"]: item for item in items}
        self.actor_id = actor_id
        self.es_jefe = es_jefe
        self.es_asignado = es_asignado
        self.grupo_calls = []
        self.historial_calls = []
        self.base_updates = []
        self.execution_updates = []

    async def get_items_context_by_ids(self, conn, item_ids):
        return [self.items[item_id] for item_id in item_ids if item_id in self.items]

    async def lock_items_context_by_ids(self, conn, item_ids):
        return await self.get_items_context_by_ids(conn, item_ids)

    async def get_item_by_id(self, conn, item_id):
        return self.items.get(item_id)

    async def get_bom_by_id(self, conn, bom_id):
        item = next(
            (row for row in self.items.values() if row["id_bom"] == bom_id),
            None,
        )
        if not item:
            return None
        return {
            "id_bom": bom_id,
            "id_proyecto": item["id_proyecto"],
            "id_paquete": item["id_paquete"],
            "estatus": item["bom_estatus"],
            "version": item["bom_version"],
            "lock_version": item["bom_lock_version"],
            "es_cabeza_trabajo": True,
            "es_cabeza_oficial": item["bom_estatus"] == "APROBADO_FINAL",
            "estado_paquete": "ACTIVO",
            "elaborado_por": self.actor_id,
            "ingeniero_responsable_id": self.actor_id,
            "responsable_ing": self.actor_id,
            "coordinador_obra": self.actor_id,
            "jefe_construccion": self.actor_id,
        }

    async def get_bom_for_update(self, conn, bom_id):
        return await self.get_bom_by_id(conn, bom_id)

    async def incrementar_lock_bom_cas(self, conn, bom_id, esperado, estatus):
        bom = await self.get_bom_by_id(conn, bom_id)
        if not bom or bom["lock_version"] != esperado or bom["estatus"] != estatus:
            return None
        for item in self.items.values():
            if item["id_bom"] == bom_id:
                item["bom_lock_version"] += 1
        return {"lock_version": esperado + 1}

    async def get_aprobador_final_id(self, conn):
        return None

    async def set_item_grupos(self, conn, item_id, grupo_ids):
        self.grupo_calls.append((item_id, list(grupo_ids)))

    async def get_grupos_por_item(self, conn, item_id):
        return []

    async def get_grupos_operativos_por_item(self, conn, item_id):
        return []

    async def set_item_grupos_operativos(self, conn, item_id, grupo_ids, user_id):
        self.grupo_calls.append((item_id, list(grupo_ids)))

    async def update_item(self, conn, item_id, **campos):
        self.base_updates.append((item_id, campos))
        self.items[item_id].update(campos)
        return self.items[item_id]

    async def upsert_item_ejecucion(
        self, conn, item_id, updated_by=None, lock_version_esperado=None, **campos
    ):
        item = self.items[item_id]
        if lock_version_esperado != item.get("ejecucion_lock_version", 0):
            return None
        self.execution_updates.append((item_id, updated_by, campos))
        item["ejecucion_lock_version"] = lock_version_esperado + 1
        public_map = {
            "id_proveedor_real": "id_proveedor",
            "precio_real": "precio_real",
            "moneda_real": "moneda_real",
            "cantidad_recibida": "cantidad_recibida",
            "fecha_llegada_real": "fecha_llegada_real",
            "fecha_estimada_entrega": "fecha_estimada_entrega",
            "tipo_entrega": "tipo_entrega",
            "estatus_ejecucion": "estatus_ejecucion",
            "comentarios_operativos": "comentarios_operativos",
        }
        for key, value in campos.items():
            item[public_map.get(key, key)] = value
        return dict(item)

    async def registrar_historial(self, *args, **kwargs):
        self.historial_calls.append((args, kwargs))

    async def usuario_tiene_rol_org(self, conn, user_id, rol_org):
        return self.es_jefe

    async def usuario_tiene_asignacion_proyecto(
        self, conn, id_proyecto, user_id, rol_proyecto, area
    ):
        return self.es_asignado


class FakeCostDB:
    def __init__(self, items_sin_costo):
        self.items_sin_costo = items_sin_costo

    async def get_items_sin_costo_bom(self, conn, id_bom):
        return list(self.items_sin_costo)


class FakeSeleccionCotizacionDB:
    def __init__(self, cotizacion, items):
        self.cotizacion = cotizacion
        self.items = items
        self.estatus_items = []
        self.execution_updates = []

    async def get_cotizacion_by_id(self, conn, cotizacion_id):
        return dict(self.cotizacion)

    async def get_cotizacion_for_update(self, conn, cotizacion_id):
        return dict(self.cotizacion)

    async def actualizar_estatus_cotizacion(
        self, conn, cotizacion_id, estatus, estatus_esperado, lock_version_esperado
    ):
        if (
            self.cotizacion["estatus"] != estatus_esperado
            or self.cotizacion["lock_version"] != lock_version_esperado
        ):
            return None
        updated = {
            **self.cotizacion,
            "estatus": estatus,
            "lock_version": lock_version_esperado + 1,
        }
        self.cotizacion = updated
        return updated

    async def get_items_cotizacion(self, conn, cotizacion_id):
        return list(self.items)

    async def get_items_by_ids(self, conn, item_ids):
        rows = []
        for item_id in item_ids:
            match = next(
                (item for item in self.items if item["bom_item_id"] == item_id),
                None,
            )
            if match:
                rows.append({
                    "id_item": item_id,
                    "id_bom": self.cotizacion["bom_id"],
                    "descripcion": match.get("descripcion", "Item"),
                    "cantidad": match.get("cantidad", 1),
                    "precio_unitario": match.get("precio_unitario"),
                    "estatus_ejecucion": match.get("estatus_ejecucion"),
                    "estatus_compra": match.get("estatus_compra", "SIN_COTIZAR"),
                    "activo": True,
                })
        return rows

    async def actualizar_estatus_compra_items(self, conn, item_ids, estatus):
        self.estatus_items.append((list(item_ids), estatus))

    async def lock_items_context_by_ids(self, conn, item_ids):
        return await self.get_items_by_ids(conn, item_ids)

    async def upsert_item_ejecucion(
        self, conn, item_id, updated_by=None, lock_version_esperado=None,
        **campos,
    ):
        self.execution_updates.append((item_id, updated_by, campos))
        return {"id_item": item_id, **campos}

    async def get_autorizacion_by_cotizacion(self, conn, cotizacion_id):
        return {"id": uuid4()}

    async def get_bom_by_id(self, conn, bom_id):
        return {
            "id_bom": bom_id,
            "id_proyecto": uuid4(),
            "id_paquete": uuid4(),
            "estatus": "APROBADO_FINAL",
            "es_cabeza_trabajo": True,
            "es_cabeza_oficial": True,
            "estado_paquete": "ACTIVO",
            "coordinador_obra": None,
        }

    async def get_bom_for_update(self, conn, bom_id):
        return await self.get_bom_by_id(conn, bom_id)

    async def registrar_evento_outbox(self, *args, **kwargs):
        return None


def _item(item_id, bom_id, proyecto_id, *, estatus="BORRADOR", activo=True, bloqueado=False):
    return {
        "id_item": item_id,
        "id_bom": bom_id,
        "id_proyecto": proyecto_id,
        "bom_estatus": estatus,
        "bom_version": 1,
        "bom_lock_version": 0,
        "ejecucion_lock_version": 0,
        "id_paquete": uuid4(),
        "activo": activo,
        "bloqueado": bloqueado,
        "cantidad": 10,
        "cantidad_recibida": 0,
        "precio_unitario": 100,
        "precio_real": None,
        "moneda": "MXN",
        "moneda_real": None,
        "origen_precio": "MANUAL",
    }


def _service(items, **db_kwargs):
    svc = BomService()
    svc.db = FakeBulkDB(items, **db_kwargs)
    return svc


@pytest.mark.asyncio
async def test_bulk_grupos_rechaza_lote_si_un_item_es_de_otro_bom():
    bom_id = uuid4()
    otro_bom_id = uuid4()
    proyecto_id = uuid4()
    item_valido = uuid4()
    item_externo = uuid4()
    user_id = uuid4()
    svc = _service([
        _item(item_valido, bom_id, proyecto_id),
        _item(item_externo, otro_bom_id, proyecto_id),
    ], actor_id=user_id)

    with pytest.raises(ValueError, match="no pertenece a este BOM"):
        await svc.editar_items_bulk(
            FakeConn(), bom_id, [item_valido, item_externo], user_id,
            "construccion", "grupos", grupo_ids=[1], lock_version_esperado=0,
            module_roles={"construccion": "editor"},
        )

    assert svc.db.grupo_calls == []


@pytest.mark.asyncio
async def test_bulk_grupos_rechaza_lote_si_un_item_esta_bloqueado():
    bom_id = uuid4()
    proyecto_id = uuid4()
    item_bloqueado = uuid4()
    item_final = uuid4()
    user_id = uuid4()
    svc = _service([
        _item(item_bloqueado, bom_id, proyecto_id, bloqueado=True),
        _item(item_final, bom_id, proyecto_id, estatus="APROBADO_FINAL"),
    ], actor_id=user_id)

    with pytest.raises(ValueError, match="version anterior"):
        await svc.editar_items_bulk(
                FakeConn(), bom_id, [item_bloqueado, item_final], user_id,
                "construccion", "grupos", grupo_ids=[1], lock_version_esperado=0,
                module_roles={"construccion": "editor"},
        )

    assert svc.db.grupo_calls == []


@pytest.mark.asyncio
async def test_bulk_rechaza_lock_bom_obsoleto_sin_mutar_items():
    bom_id = uuid4()
    proyecto_id = uuid4()
    item_id = uuid4()
    user_id = uuid4()
    svc = _service(
        [_item(item_id, bom_id, proyecto_id)],
        actor_id=user_id,
    )

    with pytest.raises(ValueError, match="El BOM cambio"):
        await svc.editar_items_bulk(
            FakeConn(), bom_id, [item_id], user_id,
            "construccion", "grupos", grupo_ids=[1],
            lock_version_esperado=99,
            module_roles={"construccion": "editor"},
        )

    assert svc.db.grupo_calls == []
    assert svc.db.base_updates == []


@pytest.mark.asyncio
async def test_bulk_grupos_ingenieria_exige_jefe_o_ingeniero_asignado():
    bom_id = uuid4()
    proyecto_id = uuid4()
    item_id = uuid4()
    svc = _service([_item(item_id, bom_id, proyecto_id)])

    with pytest.raises(ValueError, match="Solo Ingenieria puede modificar"):
        await svc.editar_items_bulk(
            FakeConn(), bom_id, [item_id], uuid4(),
            "ingenieria", "grupos", grupo_ids=[1], lock_version_esperado=0,
        )

    assert svc.db.grupo_calls == []


@pytest.mark.asyncio
async def test_editar_item_compras_rechaza_precio_negativo():
    bom_id = uuid4()
    proyecto_id = uuid4()
    item_id = uuid4()
    svc = _service([
        _item(item_id, bom_id, proyecto_id, estatus="APROBADO_ING"),
    ])

    with pytest.raises(ValueError) as exc:
        await svc.editar_item(
            FakeConn(), item_id, uuid4(), "compras", precio_unitario="-1"
        )

    assert str(exc.value) == "El costo real no puede ser negativo"


@pytest.mark.asyncio
async def test_editar_item_compras_aprobado_final_actualiza_ejecucion_no_base():
    bom_id = uuid4()
    proyecto_id = uuid4()
    item_id = uuid4()
    proveedor_id = uuid4()
    user_id = uuid4()
    svc = _service([
        _item(item_id, bom_id, proyecto_id, estatus="APROBADO_FINAL"),
    ])

    updated = await svc.editar_item(
        FakeConn(), item_id, user_id, "compras",
        precio_real="125.50", id_proveedor=proveedor_id, moneda_real="MXN",
        ejecucion_lock_version_esperado=0,
        module_roles={"compras": "editor"},
    )

    assert updated["precio_unitario"] == 100
    assert updated["precio_real"] == "125.50"
    assert svc.db.base_updates == []
    assert svc.db.execution_updates == [
        (
            item_id,
            user_id,
            {
                "precio_real": "125.50",
                "id_proveedor_real": proveedor_id,
                "moneda_real": "MXN",
                "estatus_ejecucion": "COTIZADO",
            },
        )
    ]


@pytest.mark.asyncio
async def test_editar_ejecucion_rechaza_lock_faltante_y_obsoleto():
    bom_id = uuid4()
    item_id = uuid4()
    svc = _service([
        _item(item_id, bom_id, uuid4(), estatus="APROBADO_FINAL"),
    ])

    with pytest.raises(ValueError, match="Falta la revisión de ejecución"):
        await svc.editar_item(
            FakeConn(), item_id, uuid4(), "compras", precio_real="125",
            module_roles={"compras": "editor"},
        )

    svc.db.items[item_id]["ejecucion_lock_version"] = 2
    with pytest.raises(ValueError, match="ejecución del item cambió"):
        await svc.editar_item(
            FakeConn(), item_id, uuid4(), "compras", precio_real="125",
            ejecucion_lock_version_esperado=1,
            module_roles={"compras": "editor"},
        )

    assert svc.db.execution_updates == []


@pytest.mark.asyncio
async def test_editar_item_construccion_aprobado_final_actualiza_recepcion_no_base():
    bom_id = uuid4()
    proyecto_id = uuid4()
    item_id = uuid4()
    user_id = uuid4()
    svc = _service([
        _item(item_id, bom_id, proyecto_id, estatus="APROBADO_FINAL"),
    ])

    updated = await svc.editar_item(
        FakeConn(), item_id, user_id, "construccion", cantidad_recibida="4",
        ejecucion_lock_version_esperado=0,
        module_roles={"construccion": "editor"},
    )

    assert updated["cantidad_recibida"] == "4"
    assert svc.db.base_updates == []
    assert svc.db.execution_updates == [
        (
            item_id,
            user_id,
            {
                "cantidad_recibida": "4",
                "estatus_ejecucion": "RECIBIDO_PARCIAL",
            },
        )
    ]


@pytest.mark.asyncio
async def test_editar_item_construccion_en_revision_muta_base_durante_su_turno():
    bom_id = uuid4()
    proyecto_id = uuid4()
    item_id = uuid4()
    user_id = uuid4()
    svc = _service([
        _item(item_id, bom_id, proyecto_id, estatus="EN_REVISION_CONST"),
    ], actor_id=user_id)

    await svc.editar_item(
        FakeConn(), item_id, user_id, "construccion",
        fecha_requerida="2026-07-01", lock_version_esperado=0,
        module_roles={"construccion": "editor"},
    )

    assert svc.db.base_updates == [(item_id, {"fecha_requerida": "2026-07-01"})]
    assert svc.db.execution_updates == []


@pytest.mark.asyncio
async def test_set_item_grupos_construccion_en_revision_muta_base_durante_su_turno():
    bom_id = uuid4()
    proyecto_id = uuid4()
    item_id = uuid4()
    user_id = uuid4()
    svc = _service([
        _item(item_id, bom_id, proyecto_id, estatus="EN_REVISION_CONST"),
    ], actor_id=user_id)

    await svc.set_item_grupos(
        FakeConn(), item_id, user_id, [1], "construccion",
        lock_version_esperado=0,
        module_roles={"construccion": "editor"},
    )

    assert svc.db.grupo_calls == [(item_id, [1])]


@pytest.mark.asyncio
async def test_editar_item_ingenieria_aprobado_final_rechaza_presupuesto_base():
    bom_id = uuid4()
    proyecto_id = uuid4()
    item_id = uuid4()
    svc = _service([
        _item(item_id, bom_id, proyecto_id, estatus="APROBADO_FINAL"),
    ], es_jefe=True)

    with pytest.raises(ValueError, match="Operacion downstream"):
        await svc.editar_item(
            FakeConn(), item_id, uuid4(), "ingenieria", precio_unitario="90"
        )

    assert svc.db.base_updates == []
    assert svc.db.execution_updates == []


@pytest.mark.asyncio
async def test_seleccionar_cotizacion_registra_costo_real_sin_actualizar_base():
    cotizacion_id = uuid4()
    item_id = uuid4()
    proveedor_id = uuid4()
    user_id = uuid4()
    svc = BomService()
    svc.db = FakeSeleccionCotizacionDB(
        {
            "id": cotizacion_id,
            "bom_id": uuid4(),
            "estatus": "RECIBIDA",
            "lock_version": 0,
            "proveedor_id": proveedor_id,
            "moneda": "MXN",
            "pdf_url": "https://example.com/cotizacion.pdf",
            "total": 123,
        },
        [
            {
                "bom_item_id": item_id,
                "precio_unitario": 123,
                "moneda": "MXN",
            }
        ],
    )

    await svc.seleccionar_cotizacion(
        FakeConn(), cotizacion_id, user_id, lock_version_esperado=0
    )

    assert svc.db.estatus_items == [([item_id], "COTIZADO")]
    assert svc.db.execution_updates == [
        (
            item_id,
            user_id,
            {
                "id_proveedor_real": proveedor_id,
                "precio_real": 123,
                "moneda_real": "MXN",
                "estatus_ejecucion": "COTIZADO",
            },
        )
    ]


@pytest.mark.asyncio
async def test_validar_sin_costos_pendientes_bloquea_null_y_cero():
    svc = BomService()
    svc.db = FakeCostDB([
        {"descripcion": "Modulo FV", "precio_unitario": None, "activo": True},
        {"descripcion": "Inversor", "precio_unitario": 0, "activo": True},
    ])

    with pytest.raises(ValueError) as exc:
        await svc.validar_sin_costos_pendientes(FakeConn(), uuid4())

    message = str(exc.value)
    assert "hay 2 item(s) sin presupuesto base" in message
    assert "Modulo FV" in message
    assert "Inversor" in message


@pytest.mark.asyncio
async def test_validar_sin_costos_pendientes_permite_bom_con_costos():
    svc = BomService()
    svc.db = FakeCostDB([])

    await svc.validar_sin_costos_pendientes(FakeConn(), uuid4())
