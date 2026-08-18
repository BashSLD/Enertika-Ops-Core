"""
Test de validacion del RFC receptor contra tb_config_empresa (doc 35): procesar_xmls rechaza
un XML timbrado a nombre de otra empresa como error de carga, antes de crear proveedor/match.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

import modules.compras.db_service as compras_db_module
import modules.compras.service as compras_service_module
from modules.compras.service import ComprasService


class FakeFile:
    def __init__(self, filename):
        self.filename = filename

    async def read(self):
        return b"<xml/>"

    async def seek(self, pos):
        return None


def _fake_cfdi(receptor_rfc):
    return SimpleNamespace(
        uuid="DDDDDDDD-1111-2222-3333-444444444444",
        emisor_rfc="AAA010101AAA",
        emisor_nombre="Proveedor Demo",
        receptor_rfc=receptor_rfc,
        total=1000.0,
        moneda="MXN",
        tipo_factura=SimpleNamespace(value="NORMAL"),
    )


@pytest.mark.asyncio
async def test_rechaza_xml_con_rfc_receptor_distinto(monkeypatch):
    fake_db = SimpleNamespace(
        get_config_empresa=AsyncMock(return_value={"rfc": "ENE010101AAA"}),
        get_proveedor_by_rfc=AsyncMock(),
        uuid_factura_exists=AsyncMock(),
    )
    monkeypatch.setattr(compras_db_module, "get_db_service", lambda: fake_db)
    monkeypatch.setattr(compras_service_module, "validate_xml_content", lambda content, filename: None)
    monkeypatch.setattr(
        compras_service_module, "parse_cfdi_xml",
        lambda content, filename: _fake_cfdi("ZZZ999999ZZZ"),
    )

    result = await ComprasService().procesar_xmls(AsyncMock(), [FakeFile("factura.xml")], uuid4())

    assert len(result.errores) == 1
    assert "RFC receptor" in result.errores[0].error
    assert not result.procesados
    fake_db.get_proveedor_by_rfc.assert_not_awaited()
    fake_db.uuid_factura_exists.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_bloquea_si_config_empresa_sigue_pendiente(monkeypatch):
    fake_db = SimpleNamespace(
        get_config_empresa=AsyncMock(return_value={"rfc": "PENDIENTE_CONFIGURAR"}),
        get_proveedor_by_rfc=AsyncMock(return_value=None),
        create_proveedor=AsyncMock(return_value={"id_proveedor": uuid4()}),
        uuid_factura_exists=AsyncMock(return_value=True),
        uuid_factura_exists_in_junction=AsyncMock(return_value=False),
    )
    monkeypatch.setattr(compras_db_module, "get_db_service", lambda: fake_db)
    monkeypatch.setattr(compras_service_module, "validate_xml_content", lambda content, filename: None)
    monkeypatch.setattr(
        compras_service_module, "parse_cfdi_xml",
        lambda content, filename: _fake_cfdi("CUALQUIER_RFC"),
    )

    result = await ComprasService().procesar_xmls(AsyncMock(), [FakeFile("factura.xml")], uuid4())

    # Con el RFC sin configurar, el XML avanza mas alla del check de RFC y llega al de
    # duplicado (uuid_factura_exists=True) -- confirma que no se bloqueo por RFC.
    assert len(result.duplicados) == 1
    assert not result.errores
