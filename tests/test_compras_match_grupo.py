from decimal import Decimal
from uuid import uuid4

import pytest

from modules.compras import db_service as compras_db_module
from modules.compras.service import ComprasService


class FakeComprasDBService:
    def __init__(self, comprobantes):
        self.comprobantes = {c["id_comprobante"]: dict(c) for c in comprobantes}
        self.links = []
        self.id_proveedor = uuid4()

    async def get_comprobantes_by_ids(self, conn, ids, for_update=False):
        return [dict(self.comprobantes[i]) for i in ids if i in self.comprobantes]

    async def uuid_factura_exists_for_comprobante(self, conn, id_comprobante, uuid_factura):
        return any(
            l["id_comprobante"] == id_comprobante and l["uuid_factura"] == uuid_factura
            for l in self.links
        )

    async def get_proveedor_by_rfc(self, conn, rfc):
        return {
            "id_proveedor": self.id_proveedor,
            "razon_social": "Proveedor Demo",
            "nombre_comercial": None,
        }

    async def get_comprobante_by_id(self, conn, id_comprobante, for_update=False):
        comprobante = self.comprobantes.get(id_comprobante)
        return dict(comprobante) if comprobante else None

    async def get_factura_aplicacion_resumen(self, conn, uuid_factura):
        links = [l for l in self.links if l["uuid_factura"] == uuid_factura]
        if not links:
            return {"monto_factura": Decimal("0"), "monto_aplicado": Decimal("0")}
        return {
            "monto_factura": max(l["monto"] for l in links),
            "monto_aplicado": sum(l["monto_aplicado"] for l in links),
        }

    async def insertar_comprobante_factura(
        self, conn, id_comprobante, uuid_factura, tipo, monto=None,
        monto_aplicado=None, moneda="MXN", fecha=None, id_proveedor=None,
        rfc_emisor=None, nombre_emisor=None,
    ):
        self.links.append({
            "id_comprobante": id_comprobante,
            "uuid_factura": uuid_factura,
            "tipo": tipo,
            "monto": monto,
            "monto_aplicado": monto_aplicado if monto_aplicado is not None else monto,
        })

    async def confirmar_match(
        self, conn, id_comprobante, uuid_factura, id_proveedor,
        tipo_factura="NORMAL", current_estatus=None, monto_factura=Decimal("0"),
        id_comprobante_anticipo=None, monto_comprobante=None,
        monto_acumulado=None, monto_aplicado=None,
    ):
        comp = self.comprobantes[id_comprobante]
        movimiento = Decimal(str(monto_aplicado if monto_aplicado is not None else monto_factura))
        comp["uuid_factura"] = comp.get("uuid_factura") or uuid_factura
        comp["id_proveedor"] = id_proveedor
        comp["monto_facturado"] = Decimal(str(comp.get("monto_facturado") or 0)) + movimiento
        comp["estatus"] = (
            "FACTURADO"
            if comp["monto_facturado"] >= comp["monto"] - Decimal("0.50")
            else "PARCIALMENTE_FACTURADO"
        )

    async def guardar_relacion_beneficiario(self, conn, beneficiario, id_proveedor, user_id):
        return None

    async def guardar_conceptos_historial(self, *args, **kwargs):
        return None

    async def guardar_cfdi_relacionados(self, conn, uuid_factura, relacionados):
        return None

    async def confirm_xml_staging(self, conn, uuid_factura):
        return None

    async def cerrar_remanente_automatico(self, conn, id_comprobante, motivo, user_id):
        comp = self.comprobantes[id_comprobante]
        remanente = comp["monto"] - comp["monto_facturado"]
        if comp["estatus"] not in ("PARCIALMENTE_FACTURADO", "FACTURADO"):
            return {"id_comprobante": id_comprobante, "cerrado": False}
        if abs(remanente) <= Decimal("0.005"):
            return {"id_comprobante": id_comprobante, "cerrado": False}
        comp["estatus"] = "CERRADO"
        comp["monto_remanente"] = remanente
        comp["motivo_cierre"] = motivo
        return {
            "id_comprobante": id_comprobante,
            "estatus": "CERRADO",
            "monto_remanente": remanente,
            "cerrado": True,
        }


def _factura(uuid, total):
    return {
        "uuid": uuid,
        "emisor_rfc": "PRO010101AA1",
        "emisor_nombre": "Proveedor Demo",
        "total": str(total),
        "subtotal": str(total),
        "moneda": "MXN",
        "fecha": "2026-05-20",
        "tipo_factura": "NORMAL",
        "conceptos": [],
        "relacionados": [],
    }


def _comprobante(id_comprobante, monto):
    return {
        "id_comprobante": id_comprobante,
        "fecha_pago": None,
        "beneficiario_orig": "Proveedor Demo",
        "monto": Decimal(str(monto)),
        "moneda": "MXN",
        "estatus": "PENDIENTE",
        "monto_facturado": Decimal("0"),
        "uuid_factura": None,
        "id_proveedor": None,
    }


@pytest.mark.asyncio
async def test_confirmar_match_grupo_distribuye_xmls_en_comprobantes_correctos(monkeypatch):
    comp_1 = uuid4()
    comp_2 = uuid4()
    fake_db = FakeComprasDBService([
        _comprobante(comp_1, "200.00"),
        _comprobante(comp_2, "100.00"),
    ])
    monkeypatch.setattr(compras_db_module, "get_db_service", lambda: fake_db)

    resultado = await ComprasService().confirmar_match_grupo(
        None,
        [
            _factura("10000000-0000-4000-8000-000000000001", "120.00"),
            _factura("10000000-0000-4000-8000-000000000002", "80.00"),
            _factura("10000000-0000-4000-8000-000000000003", "60.00"),
            _factura("10000000-0000-4000-8000-000000000004", "40.00"),
        ],
        [comp_1, comp_2],
        uuid4(),
    )

    assert resultado["total_facturas"] == 4
    assert resultado["total_comprobantes"] == 2
    assert resultado["comprobantes_cerrados"] == []
    assert fake_db.comprobantes[comp_1]["estatus"] == "FACTURADO"
    assert fake_db.comprobantes[comp_2]["estatus"] == "FACTURADO"
    assert {l["id_comprobante"] for l in fake_db.links} == {comp_1, comp_2}
    assert sum(Decimal(str(a["monto_aplicado"])) for a in resultado["asignaciones"]) == Decimal("300.0")


@pytest.mark.asyncio
async def test_confirmar_match_grupo_cierra_diferencia_dentro_de_tolerancia(monkeypatch):
    comp_id = uuid4()
    fake_db = FakeComprasDBService([_comprobante(comp_id, "100.00")])
    monkeypatch.setattr(compras_db_module, "get_db_service", lambda: fake_db)

    resultado = await ComprasService().confirmar_match_grupo(
        None,
        [_factura("20000000-0000-4000-8000-000000000001", "99.75")],
        [comp_id],
        uuid4(),
    )

    assert fake_db.comprobantes[comp_id]["estatus"] == "CERRADO"
    assert fake_db.comprobantes[comp_id]["monto_remanente"] == Decimal("0.25")
    assert "tolerancia" in fake_db.comprobantes[comp_id]["motivo_cierre"]
    assert len(resultado["comprobantes_cerrados"]) == 1


@pytest.mark.asyncio
async def test_confirmar_match_grupo_rechaza_excedente_sin_motivo(monkeypatch):
    comp_id = uuid4()
    fake_db = FakeComprasDBService([_comprobante(comp_id, "100.00")])
    monkeypatch.setattr(compras_db_module, "get_db_service", lambda: fake_db)

    with pytest.raises(ValueError, match="motivo de excepcion"):
        await ComprasService().confirmar_match_grupo(
            None,
            [_factura("30000000-0000-4000-8000-000000000001", "98.00")],
            [comp_id],
            uuid4(),
        )

    assert fake_db.links == []


@pytest.mark.asyncio
async def test_confirmar_match_grupo_permite_excedente_con_motivo(monkeypatch):
    comp_id = uuid4()
    fake_db = FakeComprasDBService([_comprobante(comp_id, "100.00")])
    monkeypatch.setattr(compras_db_module, "get_db_service", lambda: fake_db)

    resultado = await ComprasService().confirmar_match_grupo(
        None,
        [_factura("40000000-0000-4000-8000-000000000001", "98.00")],
        [comp_id],
        uuid4(),
        forzar_excepcion=True,
        motivo_excepcion="Diferencia autorizada por compras",
    )

    assert fake_db.comprobantes[comp_id]["estatus"] == "CERRADO"
    assert fake_db.comprobantes[comp_id]["monto_remanente"] == Decimal("2.00")
    assert "Excepcion match grupal XML" in fake_db.comprobantes[comp_id]["motivo_cierre"]
    assert resultado["requiere_excepcion"] is True
    assert len(resultado["comprobantes_cerrados"]) == 1
