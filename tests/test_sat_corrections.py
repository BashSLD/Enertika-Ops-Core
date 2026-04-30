from decimal import Decimal
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

satcfdi_module = ModuleType("satcfdi")
satcfdi_models_module = ModuleType("satcfdi.models")
satcfdi_pacs_module = ModuleType("satcfdi.pacs")
satcfdi_sat_module = ModuleType("satcfdi.pacs.sat")


class _FakeSigner:
    pass


class _FakeSAT:
    pass


class _FakeEstadoComprobante:
    VIGENTE = "vigente"


satcfdi_models_module.Signer = _FakeSigner
satcfdi_sat_module.SAT = _FakeSAT
satcfdi_sat_module.EstadoComprobante = _FakeEstadoComprobante
sys.modules.setdefault("satcfdi", satcfdi_module)
sys.modules.setdefault("satcfdi.models", satcfdi_models_module)
sys.modules.setdefault("satcfdi.pacs", satcfdi_pacs_module)
sys.modules.setdefault("satcfdi.pacs.sat", satcfdi_sat_module)

from core.integrations import sharepoint as sharepoint_module
from core.integrations.sharepoint import SharePointService
from modules.compras import db_service as compras_db_module
from modules.compras import sat_db_service
from modules.compras import sat_service
from modules.compras.db_service import ComprasDBService
from modules.compras.service import ComprasService


@pytest.mark.asyncio
async def test_confirmar_match_cierre_anticipo_cierra_pago_y_guarda_referencia():
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value="UPDATE 1")

    id_comprobante = uuid4()
    id_proveedor = uuid4()
    svc = ComprasDBService()

    await svc.confirmar_match(
        conn,
        id_comprobante,
        "CCCCCCCC-1111-2222-3333-444444444444",
        id_proveedor,
        "CIERRE_ANTICIPO",
        "ANTICIPO",
        Decimal("1000.00"),
        id_comprobante_anticipo=id_comprobante,
    )

    sql, *params = conn.execute.await_args.args
    assert "estatus = 'FACTURADO'" in sql
    assert "es_anticipo = FALSE" in sql
    assert "monto_facturado = monto" in sql
    assert "id_comprobante_anticipo" in sql
    assert params[3] == id_comprobante


@pytest.mark.asyncio
async def test_confirmar_match_xml_cierre_anticipo_sin_relacion_07_usa_anticipo_seleccionado(monkeypatch):
    id_comprobante = uuid4()
    id_proveedor = uuid4()

    fake_db = SimpleNamespace(
        uuid_factura_exists=AsyncMock(return_value=False),
        uuid_factura_exists_in_junction=AsyncMock(return_value=False),
        get_proveedor_by_rfc=AsyncMock(return_value={
            "id_proveedor": id_proveedor,
            "razon_social": "Proveedor Demo",
        }),
        get_comprobante_by_id=AsyncMock(side_effect=[
            {
                "id_comprobante": id_comprobante,
                "id_proveedor": id_proveedor,
                "estatus": "ANTICIPO",
                "monto": Decimal("1000.00"),
                "monto_facturado": Decimal("400.00"),
                "beneficiario_orig": "Proveedor Demo",
            },
            {
                "id_comprobante": id_comprobante,
                "id_proveedor": id_proveedor,
                "estatus": "FACTURADO",
                "monto": Decimal("1000.00"),
                "monto_facturado": Decimal("1000.00"),
                "beneficiario_orig": "Proveedor Demo",
            },
        ]),
        insertar_comprobante_factura=AsyncMock(),
        confirmar_match=AsyncMock(),
        confirm_xml_staging=AsyncMock(),
    )
    monkeypatch.setattr(compras_db_module, "get_db_service", lambda: fake_db)

    cfdi_data = {
        "uuid": "CCCCCCCC-1111-2222-3333-444444444444",
        "emisor_rfc": "AAA010101AAA",
        "emisor_nombre": "Proveedor Demo",
        "total": "1000.00",
        "moneda": "MXN",
        "tipo_factura": "CIERRE_ANTICIPO",
        "relacionados": [],
    }

    resultado = await ComprasService().confirmar_match_xml(
        AsyncMock(),
        cfdi_data,
        id_comprobante,
        uuid4(),
        guardar_relacion=False,
    )

    assert resultado["nuevo_estatus"] == "FACTURADO"
    fake_db.confirmar_match.assert_awaited_once()
    assert fake_db.confirmar_match.await_args.kwargs["id_comprobante_anticipo"] == id_comprobante


@pytest.mark.asyncio
async def test_confirmar_match_xml_cierre_anticipo_sin_relacion_07_rechaza_no_anticipo(monkeypatch):
    id_comprobante = uuid4()
    id_proveedor = uuid4()

    fake_db = SimpleNamespace(
        uuid_factura_exists=AsyncMock(return_value=False),
        uuid_factura_exists_in_junction=AsyncMock(return_value=False),
        get_proveedor_by_rfc=AsyncMock(return_value={
            "id_proveedor": id_proveedor,
            "razon_social": "Proveedor Demo",
        }),
        get_comprobante_by_id=AsyncMock(return_value={
            "id_comprobante": id_comprobante,
            "id_proveedor": id_proveedor,
            "estatus": "PENDIENTE",
            "monto": Decimal("1000.00"),
            "monto_facturado": Decimal("0.00"),
            "beneficiario_orig": "Proveedor Demo",
        }),
    )
    monkeypatch.setattr(compras_db_module, "get_db_service", lambda: fake_db)

    cfdi_data = {
        "uuid": "CCCCCCCC-1111-2222-3333-444444444444",
        "emisor_rfc": "AAA010101AAA",
        "emisor_nombre": "Proveedor Demo",
        "total": "1000.00",
        "moneda": "MXN",
        "tipo_factura": "CIERRE_ANTICIPO",
        "relacionados": [],
    }

    with pytest.raises(ValueError, match="estatus ANTICIPO"):
        await ComprasService().confirmar_match_xml(
            AsyncMock(),
            cfdi_data,
            id_comprobante,
            uuid4(),
            guardar_relacion=False,
        )


@pytest.mark.asyncio
async def test_get_comprobante_anticipo_by_uuid_busca_en_junction():
    conn = AsyncMock()
    id_comprobante = uuid4()
    id_proveedor = uuid4()
    conn.fetchrow = AsyncMock(return_value={
        "id_comprobante": id_comprobante,
        "id_proveedor": id_proveedor,
    })

    result = await ComprasDBService().get_comprobante_anticipo_by_uuid(
        conn,
        "AAAAAAAA-1111-2222-3333-444444444444",
    )

    sql, uuid_param = conn.fetchrow.await_args.args
    assert result["id_comprobante"] == id_comprobante
    assert "tb_comprobante_facturas" in sql
    assert "cf.uuid_factura = $1" in sql
    assert uuid_param == "AAAAAAAA-1111-2222-3333-444444444444"


@pytest.mark.asyncio
async def test_listar_comprobantes_para_anticipo_incluye_anticipos():
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])

    await sat_db_service.listar_comprobantes_para_anticipo(conn, "AAA010101AAA")

    sql, rfc_param = conn.fetch.await_args.args
    assert "PENDIENTE" in sql
    assert "PARCIALMENTE_FACTURADO" in sql
    assert "ANTICIPO" in sql
    assert "COALESCE(p.rfc = $1, false) DESC" in sql
    assert rfc_param == "AAA010101AAA"


class _FakeResponse:
    def __init__(self, content: bytes = b"<xml/>"):
        self.content = content

    def raise_for_status(self):
        return None


class _FakeAsyncClient:
    captured_urls = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, url, headers):
        self.captured_urls.append(url)
        return _FakeResponse()


@pytest.mark.asyncio
@pytest.mark.parametrize("drive_id,site_id,expected_url", [
    (
        "drive-123",
        "site-123",
        "https://graph.microsoft.com/v1.0/drives/drive-123/items/item-123/content",
    ),
    (
        "",
        "site-123",
        "https://graph.microsoft.com/v1.0/sites/site-123/drive/items/item-123/content",
    ),
])
async def test_sharepoint_download_direct_by_item_id(monkeypatch, drive_id, site_id, expected_url):
    _FakeAsyncClient.captured_urls = []
    monkeypatch.setattr(sharepoint_module.httpx, "AsyncClient", _FakeAsyncClient)

    svc = SharePointService(access_token="token")
    svc.drive_id = drive_id
    svc.site_id = site_id

    content = await svc.download_bytes_direct_by_item_id("item-123")

    assert content == b"<xml/>"
    assert _FakeAsyncClient.captured_urls == [expected_url]


@pytest.mark.asyncio
async def test_sharepoint_download_direct_by_item_id_requiere_drive_o_site():
    svc = SharePointService(access_token="token")
    svc.drive_id = ""
    svc.site_id = ""

    with pytest.raises(ValueError, match="drive_id o site_id requerido"):
        await svc.download_bytes_direct_by_item_id("item-123")


@pytest.mark.asyncio
async def test_descargar_xml_de_inbox_usa_item_id_y_config_sat(monkeypatch):
    class FakeAuth:
        async def get_application_token(self):
            return "token"

    class FakeSharePointService:
        instances = []

        def __init__(self, access_token):
            self.access_token = access_token
            self.site_id = None
            self.drive_id = None
            self.requested_item_id = None
            self.instances.append(self)

        async def download_bytes_direct_by_item_id(self, item_id):
            self.requested_item_id = item_id
            return b"<?xml version='1.0'?><cfdi:Comprobante/>"

    async def fake_item(conn, inbox_id):
        return {
            "sharepoint_item_id": "item-123",
            "uuid_cfdi": "CCCCCCCC-1111-2222-3333-444444444444",
        }

    async def fake_config(conn):
        return "site-123", "", "SAT-Inbox"

    monkeypatch.setattr(sat_service.sat_db_service, "obtener_inbox_item_para_descarga", fake_item)
    monkeypatch.setattr(sat_service, "_get_sat_sp_config", fake_config)
    monkeypatch.setattr(sat_service, "get_ms_auth", lambda: FakeAuth())
    monkeypatch.setattr(sat_service, "SharePointService", FakeSharePointService)

    xml_bytes, uuid_cfdi = await sat_service.descargar_xml_de_inbox(AsyncMock(), uuid4())

    sp = FakeSharePointService.instances[0]
    assert xml_bytes.startswith(b"<?xml")
    assert uuid_cfdi == "CCCCCCCC-1111-2222-3333-444444444444"
    assert sp.access_token == "token"
    assert sp.site_id == "site-123"
    assert sp.drive_id == ""
    assert sp.requested_item_id == "item-123"
