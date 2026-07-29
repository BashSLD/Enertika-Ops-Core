import pytest

from core.integrations import sharepoint as sharepoint_module
from core.integrations.sharepoint import SharePointService


def _folder_item(id_, name):
    return {"id": id_, "name": name, "folder": {}, "webUrl": f"https://sp.example/{id_}"}


class _FakeSPResponse:
    def __init__(self, status_code=200, json_data=None, headers=None, text=""):
        self.status_code = status_code
        self._json = json_data or {}
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeAsyncClient:
    responses = []
    captured_urls = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, url, headers=None):
        self.captured_urls.append(url)
        return _FakeAsyncClient.responses.pop(0)


def test_match_folders_sin_match():
    svc = SharePointService(access_token="token")
    folders = [_folder_item("1", "MX-99999-FV Otro Proyecto")]

    matches = svc._match_folders(folders, "MX-50072-FV Dario Moran")

    assert matches == []


def test_match_folders_tolera_espacios():
    svc = SharePointService(access_token="token")
    folders = [
        _folder_item("1", "MX-50072-Lighting  Dario  Moran"),
        _folder_item("2", "MX-99999-FV Otro Proyecto"),
    ]

    matches = svc._match_folders(folders, "MX-50072-Lighting Dario Moran")

    assert len(matches) == 1
    assert matches[0]["id"] == "1"


def test_match_folders_ambiguo():
    svc = SharePointService(access_token="token")
    folders = [
        _folder_item("1", "MX-50080-FV Granja Doramon 2"),
        _folder_item("2", "MX-50081-FV Granja Doramon 3"),
    ]

    matches = svc._match_folders(folders, "Granja Doramon")

    assert len(matches) >= 2


@pytest.mark.asyncio
async def test_list_children_paginated_pagina_con_nextlink(monkeypatch):
    next_link = "https://graph.microsoft.com/v1.0/drives/drive-1/root/children?$skiptoken=abc"
    _FakeAsyncClient.responses = [
        _FakeSPResponse(200, {
            "value": [_folder_item("1", "MX-10001-FV Alfa")],
            "@odata.nextLink": next_link,
        }),
        _FakeSPResponse(200, {"value": [_folder_item("2", "MX-50072-FV Dario Moran")]}),
    ]
    _FakeAsyncClient.captured_urls = []
    monkeypatch.setattr(sharepoint_module.httpx, "AsyncClient", _FakeAsyncClient)

    svc = SharePointService(access_token="token")
    folders = await svc._list_children_paginated("drive-1", "")

    assert len(folders) == 2
    assert {f["id"] for f in folders} == {"1", "2"}
    assert len(_FakeAsyncClient.captured_urls) == 2
    assert _FakeAsyncClient.captured_urls[1] == next_link


@pytest.mark.asyncio
async def test_resolver_carpeta_con_fallback_excluye_carpeta_administrativa(monkeypatch):
    # Un proyecto seed cuyo nombre corto cruza el umbral de similitud contra la
    # carpeta administrativa "Proyectos sin expediente" no debe hacer match con
    # ella — debe quedar excluida del pool y devuelta aparte como fallback.
    _FakeAsyncClient.responses = [
        _FakeSPResponse(200, {"value": [
            _folder_item("1", "Proyectos sin expediente"),
            _folder_item("2", "MX-99999-FV Otro Proyecto"),
        ]}),
    ]
    _FakeAsyncClient.captured_urls = []
    monkeypatch.setattr(sharepoint_module.httpx, "AsyncClient", _FakeAsyncClient)

    svc = SharePointService(access_token="token")
    matches, fallback = await svc.resolver_carpeta_con_fallback(
        "drive-1", "", ["MX-50072-FV Sitio Seed Golfo Pacifico"], "Proyectos sin expediente"
    )

    assert matches == []
    assert fallback is not None
    assert fallback["id"] == "1"


@pytest.mark.asyncio
async def test_resolver_carpeta_con_fallback_sin_carpeta_administrativa(monkeypatch):
    _FakeAsyncClient.responses = [
        _FakeSPResponse(200, {"value": [_folder_item("2", "MX-50072-FV Dario Moran")]}),
    ]
    _FakeAsyncClient.captured_urls = []
    monkeypatch.setattr(sharepoint_module.httpx, "AsyncClient", _FakeAsyncClient)

    svc = SharePointService(access_token="token")
    matches, fallback = await svc.resolver_carpeta_con_fallback(
        "drive-1", "", ["MX-50072-FV Dario Moran"], "Proyectos sin expediente"
    )

    assert len(matches) == 1
    assert matches[0]["id"] == "2"
    assert fallback is None


@pytest.mark.asyncio
async def test_resolver_carpeta_con_fallback_ancla_evita_ambiguedad_falsa(monkeypatch):
    # Caso real reportado: MX-50158-FV VOESTALPINE vs carpeta real
    # "MX-50158 FV VOESTALPINE" (espacio en vez de guion). El fuzzy contra el
    # nombre completo devolvia AMBIGUO por otro proyecto con nombre parecido;
    # el ancla "MX-50158" (consecutivo unico en el sistema) debe resolverlo
    # sin ambiguedad.
    _FakeAsyncClient.responses = [
        _FakeSPResponse(200, {"value": [
            _folder_item("1", "MX-50158 FV VOESTALPINE"),
            _folder_item("2", "MX-50159 FV VOESTALPINE Fase 2"),
        ]}),
    ]
    _FakeAsyncClient.captured_urls = []
    monkeypatch.setattr(sharepoint_module.httpx, "AsyncClient", _FakeAsyncClient)

    svc = SharePointService(access_token="token")
    matches, fallback = await svc.resolver_carpeta_con_fallback(
        "drive-1", "", ["MX-50158-FV VOESTALPINE"], "Proyectos sin expediente", ancla="MX-50158"
    )

    assert len(matches) == 1
    assert matches[0]["id"] == "1"
    assert fallback is None


@pytest.mark.asyncio
async def test_resolver_carpeta_con_fallback_ancla_sin_match_no_cae_a_fuzzy(monkeypatch):
    # Caso real reportado: proyecto seed "MX-50165-FV Sitio Seed - TEST-SEED-006"
    # sin carpeta real en SharePoint (el ancla "MX-50165" no matchea nada). El
    # fallback nombre_proyecto ("Proyecto Seed FV") es generico y cruzaba el
    # umbral de fuzzy contra una carpeta real no relacionada, produciendo un
    # falso MAPEADO que ademas se persiste solo. Con ancla presente, la
    # ausencia de match por prefijo debe ganar siempre — nunca degradar a fuzzy.
    _FakeAsyncClient.responses = [
        _FakeSPResponse(200, {"value": [
            _folder_item("1", "MX-50077 FV San Bartolo 2"),
            _folder_item("2", "MX-99999-FV Otro Proyecto"),
        ]}),
    ]
    _FakeAsyncClient.captured_urls = []
    monkeypatch.setattr(sharepoint_module.httpx, "AsyncClient", _FakeAsyncClient)

    svc = SharePointService(access_token="token")
    matches, fallback = await svc.resolver_carpeta_con_fallback(
        "drive-1",
        "",
        ["MX-50165-FV Sitio Seed - TEST-SEED-006", "Proyecto Seed FV"],
        "Proyectos sin expediente",
        ancla="MX-50165",
    )

    assert matches == []
    assert fallback is None


@pytest.mark.asyncio
async def test_list_children_paginated_retry_429(monkeypatch):
    sleep_calls = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(sharepoint_module.asyncio, "sleep", fake_sleep)

    _FakeAsyncClient.responses = [
        _FakeSPResponse(429, {}, headers={"Retry-After": "2"}, text="rate limited"),
        _FakeSPResponse(200, {"value": [_folder_item("1", "MX-50072-FV Dario Moran")]}),
    ]
    _FakeAsyncClient.captured_urls = []
    monkeypatch.setattr(sharepoint_module.httpx, "AsyncClient", _FakeAsyncClient)

    svc = SharePointService(access_token="token")
    folders = await svc._list_children_paginated("drive-1", "")

    assert len(folders) == 1
    assert sleep_calls == [2.0]
    assert len(_FakeAsyncClient.captured_urls) == 2
