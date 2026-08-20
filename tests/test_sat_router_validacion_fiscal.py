"""
Cobertura de `_procesar_match_unico` (flujo Buzon SAT, modules/compras/sat_router.py):
antes del refactor a core/cfdi/ este flujo no tenia ningun test. Cubre el caso de
datos fiscales del receptor invalidos (bloquea + audita) y el caso PENDIENTE_CONFIGURAR
(no bloquea, ver decision 2 de _Planes_Activos/2026-08-19-cfdi-servicio-compartido.md).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

import core.cfdi.extractor as cfdi_extractor_module
import modules.compras.sat_service as sat_service_module
import modules.compras.service as compras_service_module
import modules.compras.sat_router as sat_router_module


class FakeConn:
    async def execute(self, *args, **kwargs):
        return None

    def transaction(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _fake_cfdi(receptor_rfc, tipo_comprobante=None):
    return SimpleNamespace(
        archivo="factura.xml",
        uuid="DDDDDDDD-1111-2222-3333-444444444444",
        emisor_rfc="AAA010101AAA",
        emisor_nombre="Proveedor Demo",
        receptor_rfc=receptor_rfc,
        receptor_nombre=None,
        receptor_cp=None,
        receptor_regimen_fiscal=None,
        uso_cfdi=None,
        metodo_pago=None,
        forma_pago=None,
        tipo_comprobante=tipo_comprobante,
        total=1000.0,
        subtotal=1000.0,
        moneda="MXN",
        fecha="2026-01-01",
        conceptos=[],
        relacionados=[],
        tipo_factura=SimpleNamespace(value="NORMAL"),
    )


@pytest.mark.asyncio
async def test_procesar_match_unico_bloquea_datos_fiscales_invalidos(monkeypatch):
    empresa = {"rfc": "ENE010101AAA", "razon_social": "ENERTIKA"}
    monkeypatch.setattr(
        sat_service_module, "descargar_xml_de_inbox",
        AsyncMock(return_value=(b"<xml/>", "DDDDDDDD-1111-2222-3333-444444444444")),
    )
    monkeypatch.setattr(
        cfdi_extractor_module, "parse_cfdi_xml",
        lambda content, filename: _fake_cfdi("ZZZ999999ZZZ"),
    )

    with pytest.raises(ValueError, match="Datos fiscales del receptor invalidos"):
        await sat_router_module._procesar_match_unico(
            FakeConn(), uuid4(), uuid4(), uuid4(), empresa,
        )


@pytest.mark.asyncio
async def test_procesar_match_unico_pendiente_configurar_no_bloquea(monkeypatch):
    empresa = {"rfc": "PENDIENTE_CONFIGURAR"}
    monkeypatch.setattr(
        sat_service_module, "descargar_xml_de_inbox",
        AsyncMock(return_value=(b"<xml/>", "DDDDDDDD-1111-2222-3333-444444444444")),
    )
    monkeypatch.setattr(
        cfdi_extractor_module, "parse_cfdi_xml",
        lambda content, filename: _fake_cfdi("CUALQUIER_RFC"),
    )

    fake_compras_service = AsyncMock()
    fake_compras_service.confirmar_match_xml = AsyncMock(return_value={"saldo_factura": 0})
    fake_compras_service.upload_archivo_sharepoint = AsyncMock()
    monkeypatch.setattr(compras_service_module, "ComprasService", lambda: fake_compras_service)
    monkeypatch.setattr(sat_router_module.sat_db_service, "marcar_matcheado", AsyncMock())

    # No debe lanzar ValueError por datos fiscales -- avanza hasta confirmar el match.
    await sat_router_module._procesar_match_unico(
        FakeConn(), uuid4(), uuid4(), uuid4(), empresa,
    )

    fake_compras_service.confirmar_match_xml.assert_awaited_once()
