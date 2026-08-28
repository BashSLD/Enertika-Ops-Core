"""
Tests de cobertura parcial en cotizacion de items BOM
(_Planes_Activos/2026-08-27-cantidades-parciales-cotizacion-bom.md): un item
puede cubrirse en mas de una cotizacion (adjudicacion parcial), con
cantidad_cubierta/cantidad_pendiente derivando el estatus_compra resultante
(SIN_COTIZAR/PARCIALMENTE_COTIZADO/COTIZADO) y bloqueando una 2a cotizacion
activa sobre el mismo remanente.
"""

from decimal import Decimal
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


def _item(item_id, id_bom, *, cantidad=10, cantidad_cubierta=0,
          estatus_compra="SIN_COTIZAR", precio_unitario=100):
    return {
        "id_item": item_id,
        "id_bom": id_bom,
        "descripcion": "Item de prueba",
        "cantidad": Decimal(str(cantidad)),
        "cantidad_cubierta": Decimal(str(cantidad_cubierta)),
        "moneda": "MXN",
        "estatus_compra": estatus_compra,
        "estatus_ejecucion": None,
        "activo": True,
        "precio_unitario": precio_unitario,
        "origen_precio": "MANUAL",
        "tipo_origen_item": "BASE",
        "id_item_reemplazado": None,
        "creado_en_adenda": None,
        "adenda_estatus": None,
        "lock_version": 0,
        "ejecucion_lock_version": 0,
    }


class FakeCotizacionParcialDB:
    """Fake liviano de BomComprasDBMixin: rastrea items/cotizaciones/autorizaciones
    en memoria con la misma aritmetica que la migracion 183 (cantidad_cubierta
    delta + CASE por rango) para probar el flujo de principio a fin."""

    def __init__(self, bom_id, items):
        self.bom_id = bom_id
        self.items = {i["id_item"]: dict(i) for i in items}
        self.cotizaciones = {}
        self.cotizacion_items = {}
        self.autorizaciones = {}
        self.eventos_outbox = []
        self.historial_calls = []
        # Test hook: fuerza que estos item_ids ya esten en OTRA cotizacion
        # activa (get_items_con_cotizacion_activa), sin tener que modelar
        # tb_bom_cotizaciones completo para ese escenario.
        self.items_con_cotizacion_activa_forzado = set()

    def _bom(self):
        return {
            "id_bom": self.bom_id, "id_proyecto": uuid4(), "id_paquete": uuid4(),
            "estatus": "APROBADO_FINAL", "lock_version": 0,
            "es_cabeza_oficial": True, "es_cabeza_trabajo": True,
            "estado_paquete": "ACTIVO", "coordinador_obra": None,
        }

    async def get_bom_by_id(self, conn, id_bom):
        return self._bom() if id_bom == self.bom_id else None

    async def get_bom_for_update(self, conn, id_bom):
        return await self.get_bom_by_id(conn, id_bom)

    async def get_rfq_by_id(self, conn, rfq_id):
        return None

    async def get_items_by_ids(self, conn, item_ids):
        return [dict(self.items[i]) for i in item_ids if i in self.items]

    async def lock_items_context_by_ids(self, conn, item_ids):
        return [dict(self.items[i]) for i in item_ids if i in self.items]

    async def get_items_con_cotizacion_activa(self, conn, item_ids, excluir_cotizacion_id=None):
        return [i for i in item_ids if i in self.items_con_cotizacion_activa_forzado]

    async def crear_cotizacion(
        self, conn, id_bom, proveedor_id, nombre_proveedor, moneda,
        subtotal, iva, total, notas, creado_por, rfq_id=None,
        modo_simplificado=False, folio_proveedor=None,
    ):
        cot_id = uuid4()
        cot = {
            "id": cot_id, "bom_id": id_bom, "proveedor_id": proveedor_id,
            "nombre_proveedor": nombre_proveedor, "moneda": moneda,
            "subtotal": subtotal, "iva": iva, "total": total, "notas": notas,
            "estatus": "BORRADOR", "lock_version": 0, "pdf_url": None,
        }
        self.cotizaciones[cot_id] = cot
        return dict(cot)

    async def agregar_items_cotizacion(self, conn, cotizacion_id, bom_id, items):
        self.cotizacion_items[cotizacion_id] = [dict(i) for i in items]

    async def get_cotizacion_by_id(self, conn, cotizacion_id):
        cot = self.cotizaciones.get(cotizacion_id)
        return dict(cot) if cot else None

    async def get_cotizacion_for_update(self, conn, cotizacion_id):
        return await self.get_cotizacion_by_id(conn, cotizacion_id)

    async def actualizar_estatus_cotizacion(
        self, conn, cotizacion_id, estatus, estatus_esperado, lock_version_esperado,
    ):
        cot = self.cotizaciones[cotizacion_id]
        if cot["estatus"] != estatus_esperado or cot["lock_version"] != lock_version_esperado:
            return None
        cot["estatus"] = estatus
        cot["lock_version"] += 1
        return dict(cot)

    async def actualizar_cotizacion(
        self, conn, cotizacion_id, proveedor_id, nombre_proveedor, moneda,
        subtotal, iva, total, notas, lock_version_esperado,
        modo_simplificado=False, folio_proveedor=None,
    ):
        cot = self.cotizaciones[cotizacion_id]
        if cot["lock_version"] != lock_version_esperado or cot["estatus"] not in ("BORRADOR", "RECIBIDA"):
            return None
        cot.update({
            "proveedor_id": proveedor_id, "nombre_proveedor": nombre_proveedor,
            "moneda": moneda, "subtotal": subtotal, "iva": iva, "total": total,
            "notas": notas, "lock_version": lock_version_esperado + 1,
        })
        return dict(cot)

    async def bulk_replace_cotizacion_items(self, conn, cotizacion_id, bom_id, items):
        self.cotizacion_items[cotizacion_id] = [dict(i) for i in items]

    async def get_items_cotizacion(self, conn, cotizacion_id):
        return [dict(r) for r in self.cotizacion_items.get(cotizacion_id, [])]

    async def ajustar_cantidad_cubierta_items(self, conn, ajustes):
        resultados = []
        for item_id, delta in ajustes:
            item = self.items[item_id]
            nueva = Decimal(str(item.get("cantidad_cubierta") or 0)) + delta
            cantidad = Decimal(str(item["cantidad"]))
            if nueva <= 0:
                estatus = "SIN_COTIZAR"
            elif nueva >= cantidad:
                estatus = "COTIZADO"
            else:
                estatus = "PARCIALMENTE_COTIZADO"
            item["cantidad_cubierta"] = nueva
            item["estatus_compra"] = estatus
            item["lock_version"] = item.get("lock_version", 0) + 1
            resultados.append({
                "id_item": item_id, "estatus_compra": estatus,
                "cantidad_cubierta": nueva, "cantidad": cantidad,
            })
        return resultados

    async def upsert_item_ejecucion(
        self, conn, item_id, updated_by=None, lock_version_esperado=None, **campos,
    ):
        item = self.items[item_id]
        if lock_version_esperado != item.get("ejecucion_lock_version", 0):
            return None
        item["ejecucion_lock_version"] = lock_version_esperado + 1
        if "estatus_ejecucion" in campos:
            item["estatus_ejecucion"] = campos["estatus_ejecucion"]
        return dict(item)

    async def get_autorizacion_by_cotizacion(self, conn, cotizacion_id):
        for aut in self.autorizaciones.values():
            if aut["cotizacion_id"] == cotizacion_id:
                return dict(aut)
        return None

    async def crear_autorizacion(
        self, conn, cotizacion_id, bom_id, proyecto_id, monto_total, moneda,
        tipo_cambio_snapshot, creado_por,
    ):
        aut_id = uuid4()
        aut = {
            "id": aut_id, "cotizacion_id": cotizacion_id, "bom_id": bom_id,
            "proyecto_id": proyecto_id, "estatus": "PENDIENTE", "lock_version": 0,
            "monto_total": monto_total, "moneda": moneda,
        }
        self.autorizaciones[aut_id] = aut
        return dict(aut)

    async def reabrir_autorizacion_db(
        self, conn, autorizacion_id, monto_total, moneda, tipo_cambio_snapshot,
        creado_por, lock_version_esperado,
    ):
        aut = self.autorizaciones[autorizacion_id]
        if aut["lock_version"] != lock_version_esperado:
            return None
        aut.update({"estatus": "PENDIENTE", "lock_version": lock_version_esperado + 1})
        return dict(aut)

    async def registrar_evento_outbox(self, conn, *args, **kwargs):
        self.eventos_outbox.append((args, kwargs))

    async def guardar_historial_cotizacion(self, *args, **kwargs):
        self.historial_calls.append((args, kwargs))

    async def get_autorizacion_by_id(self, conn, autorizacion_id):
        aut = self.autorizaciones.get(autorizacion_id)
        return dict(aut) if aut else None

    async def get_autorizacion_for_update(self, conn, autorizacion_id):
        return await self.get_autorizacion_by_id(conn, autorizacion_id)

    async def usuario_tiene_rol_org(self, conn, user_id, rol_org):
        return True

    async def get_titulares_que_representa(self, conn, suplente_id):
        return []

    async def rechazar_autorizacion_db(
        self, conn, autorizacion_id, user_id, motivo, paso,
        estatus_esperado, lock_version_esperado,
    ):
        aut = self.autorizaciones[autorizacion_id]
        if aut["estatus"] != estatus_esperado or aut["lock_version"] != lock_version_esperado:
            return None
        aut.update({"estatus": "RECHAZADO", "lock_version": lock_version_esperado + 1})
        return dict(aut)


def _service(bom_id, items):
    svc = BomService()
    svc.db = FakeCotizacionParcialDB(bom_id, items)
    return svc


async def _crear_cotizacion(svc, bom_id, item_id, cantidad, precio=100, **extra):
    return await svc.crear_cotizacion(
        FakeConn(), bom_id, None, "Proveedor X", "MXN",
        [{"bom_item_id": item_id, "cantidad": cantidad, "precio_unitario": precio}],
        16, None, uuid4(), bom_lock_version_esperado=0, **extra,
    )


async def _seleccionar(svc, cotizacion_id, user_id=None):
    cot = svc.db.cotizaciones[cotizacion_id]
    cot["pdf_url"] = "https://example.com/c.pdf"
    return await svc.seleccionar_cotizacion(
        FakeConn(), cotizacion_id, user_id or uuid4(),
        lock_version_esperado=cot["lock_version"],
    )


@pytest.mark.asyncio
async def test_adjudicacion_parcial_deja_estatus_parcial_y_pendiente_correcto():
    bom_id = uuid4()
    item_id = uuid4()
    svc = _service(bom_id, [_item(item_id, bom_id, cantidad=10)])

    cot = await _crear_cotizacion(svc, bom_id, item_id, cantidad=4)
    await _seleccionar(svc, cot["id"])

    item = svc.db.items[item_id]
    assert item["estatus_compra"] == "PARCIALMENTE_COTIZADO"
    assert item["cantidad_cubierta"] == Decimal("4")
    assert item["cantidad"] - item["cantidad_cubierta"] == Decimal("6")


@pytest.mark.asyncio
async def test_segunda_cotizacion_sobre_remanente_cierra_item_en_cotizado():
    bom_id = uuid4()
    item_id = uuid4()
    svc = _service(bom_id, [_item(item_id, bom_id, cantidad=10)])

    cot1 = await _crear_cotizacion(svc, bom_id, item_id, cantidad=4)
    await _seleccionar(svc, cot1["id"])
    assert svc.db.items[item_id]["estatus_compra"] == "PARCIALMENTE_COTIZADO"

    # El remanente (6) se acepta en una 2a cotizacion nueva sobre el mismo item.
    cot2 = await _crear_cotizacion(svc, bom_id, item_id, cantidad=6)
    await _seleccionar(svc, cot2["id"])

    item = svc.db.items[item_id]
    assert item["estatus_compra"] == "COTIZADO"
    assert item["cantidad_cubierta"] == Decimal("10")


@pytest.mark.asyncio
async def test_rechazo_de_cotizacion_parcial_decrementa_sin_resetear_cobertura_previa():
    bom_id = uuid4()
    item_id = uuid4()
    svc = _service(bom_id, [_item(item_id, bom_id, cantidad=10)])

    cot1 = await _crear_cotizacion(svc, bom_id, item_id, cantidad=4)
    await _seleccionar(svc, cot1["id"])
    cot2 = await _crear_cotizacion(svc, bom_id, item_id, cantidad=3)
    await _seleccionar(svc, cot2["id"])
    assert svc.db.items[item_id]["cantidad_cubierta"] == Decimal("7")

    # Rechazar la autorizacion de la 2a cotizacion libera solo lo que ella cubria.
    aut2 = await svc.db.get_autorizacion_by_cotizacion(None, cot2["id"])
    await svc.rechazar_autorizacion(
        FakeConn(), aut2["id"], uuid4(), "Proveedor incumplio", "ADMIN", None,
        lock_version_esperado=aut2["lock_version"],
    )

    item = svc.db.items[item_id]
    assert item["cantidad_cubierta"] == Decimal("4")
    assert item["estatus_compra"] == "PARCIALMENTE_COTIZADO"


@pytest.mark.asyncio
async def test_adenda_bloqueada_sobre_item_parcialmente_cotizado():
    bom_id = uuid4()
    item_id = uuid4()

    class FakeAdendaDB:
        def __init__(self, item):
            self.item = item

        async def get_item_by_id(self, conn, id_item):
            return dict(self.item)

    svc = BomService()
    svc.db = FakeAdendaDB(_item(item_id, bom_id, cantidad=10, cantidad_cubierta=4,
                                 estatus_compra="PARCIALMENTE_COTIZADO"))

    with pytest.raises(ValueError, match="cotizado, autorizado, pagado o facturado"):
        await svc.cerrar_item_sin_compra(FakeConn(), item_id, uuid4(), "Ya no se requiere")


@pytest.mark.asyncio
async def test_bloquea_segunda_cotizacion_activa_sobre_remanente_ya_cubierto():
    bom_id = uuid4()
    item_id = uuid4()
    svc = _service(
        bom_id,
        [_item(item_id, bom_id, cantidad=10, cantidad_cubierta=4,
               estatus_compra="PARCIALMENTE_COTIZADO")],
    )
    # Otra cotizacion BORRADOR/RECIBIDA ya compite por el remanente de este item.
    svc.db.items_con_cotizacion_activa_forzado.add(item_id)

    with pytest.raises(ValueError, match="ya tienen otra cotización pendiente"):
        await _crear_cotizacion(svc, bom_id, item_id, cantidad=6)


@pytest.mark.asyncio
async def test_cap_cantidad_rechaza_cotizar_mas_del_remanente_pendiente():
    bom_id = uuid4()
    item_id = uuid4()
    svc = _service(
        bom_id,
        [_item(item_id, bom_id, cantidad=10, cantidad_cubierta=4,
               estatus_compra="PARCIALMENTE_COTIZADO")],
    )

    with pytest.raises(ValueError, match="remanente pendiente"):
        await _crear_cotizacion(svc, bom_id, item_id, cantidad=7)
