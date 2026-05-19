import pytest
import zipfile
from datetime import date, datetime
from io import BytesIO
from uuid import uuid4

from modules.proveedores.constants import (
    ESTATUS_DOC_PROXIMO,
    ESTATUS_DOC_SIN_DOCS,
    ESTATUS_DOC_VENCIDO,
    ESTATUS_DOC_VIGENTE,
)
from modules.proveedores.service import ProveedoresService


class FakeProveedoresDB:
    def __init__(self, rows, documento=None, documentos_vigentes=None, proveedor=None):
        self.rows = rows
        self.documento = documento
        self.documentos_vigentes = documentos_vigentes or []
        self.proveedor = proveedor

    async def get_proveedores_con_estatus_docs(self, conn):
        return [dict(row) for row in self.rows]

    async def get_documento_archivo(self, conn, id_proveedor, doc_id):
        return dict(self.documento) if self.documento else None

    async def get_documentos_vigentes_proveedor(self, conn, id_proveedor):
        return [dict(row) for row in self.documentos_vigentes]

    async def get_proveedor_detalle(self, conn, id_proveedor):
        return dict(self.proveedor) if self.proveedor else None


class RecordingProveedoresDB(FakeProveedoresDB):
    def __init__(self):
        super().__init__([])
        self.insert_args = None
        self.insert_kwargs = None

    async def insert_documento_proveedor(self, *args, **kwargs):
        self.insert_args = args
        self.insert_kwargs = kwargs
        return {"id": uuid4()}


class FakeMSAuth:
    async def get_application_token(self):
        return "token"


class FakeSharePoint:
    def __init__(self, access_token, bytes_by_item):
        self.access_token = access_token
        self.bytes_by_item = bytes_by_item
        self.site_id = None
        self.drive_id = None

    async def _resolve_config(self, conn):
        return {"site_id": "site-id", "drive_id": "drive-id"}

    async def download_bytes_direct_by_item_id(self, drive_item_id):
        return self.bytes_by_item[drive_item_id]


class FakeSharePointFactory:
    def __init__(self, bytes_by_item):
        self.bytes_by_item = bytes_by_item
        self.instances = []

    def __call__(self, access_token):
        instance = FakeSharePoint(access_token, self.bytes_by_item)
        self.instances.append(instance)
        return instance


class FakeRouterProveedoresService:
    def __init__(self):
        self.id_proveedor = uuid4()
        self.doc_id = uuid4()
        self.documentos = [
            {
                "id": self.doc_id,
                "id_proveedor": self.id_proveedor,
                "tipo_documento": "constancia_fiscal",
                "tipo_persona": "MORAL",
                "sharepoint_url": "https://sharepoint.test/doc.pdf",
                "fecha_documento": date(2026, 5, 1),
                "fecha_vencimiento": date(2026, 6, 1),
                "vigente": True,
                "estatus": "vigente",
                "subido_por_nombre": "Usuario Test",
                "created_at": datetime(2026, 5, 10, 12, 0),
                "nombre_archivo": "constancia.pdf",
                "tipo_contenido": "application/pdf",
                "drive_item_id": "drive-item",
                "periodo": "2026-05",
                "nombre_documento_personalizado": None,
                "version": 2,
                "notas": "Vigente",
            }
        ]

    async def get_documento_metadata(self, conn, id_proveedor, doc_id):
        return {
            "id": str(doc_id),
            "id_proveedor": str(id_proveedor),
            "nombre_archivo": "constancia.pdf",
            "drive_item_id": "drive-item",
        }

    async def get_documento_archivo(self, conn, id_proveedor, doc_id):
        from modules.proveedores.service import DocumentoArchivo

        return DocumentoArchivo(
            nombre_archivo="constancia.pdf",
            media_type="application/pdf",
            contenido=b"%PDF-test",
        )

    async def generar_zip_expediente(self, conn, id_proveedor):
        from modules.proveedores.service import DocumentoArchivo

        return DocumentoArchivo(
            nombre_archivo="expediente.zip",
            media_type="application/zip",
            contenido=b"zip-test",
        )

    async def get_documentos_proveedor(self, conn, id_proveedor):
        return self.documentos

    async def get_documentos_vigentes_proveedor(self, conn, id_proveedor):
        return self.documentos

    async def get_proveedor_detalle(self, conn, id_proveedor):
        return {
            "id_proveedor": id_proveedor,
            "rfc": "ABC123456T1A",
            "razon_social": "Proveedor Test",
            "nombre_comercial": "Proveedor",
        }

    async def get_proveedores_con_estatus_docs(self, conn):
        return [
            {
                "id_proveedor": self.id_proveedor,
                "nombre_comercial": "Proveedor",
                "razon_social": "Proveedor Test",
                "rfc": "ABC123456T1A",
                "tipos_persona_docs": "MORAL",
                "docs_vigentes": 1,
                "total_docs": 1,
                "estatus_docs": "vigente",
                "prox_vencimiento": date(2026, 6, 1),
            }
        ]


@pytest.mark.asyncio
async def test_estatus_docs_prioriza_documentos_vencidos():
    service = ProveedoresService(
        FakeProveedoresDB(
            [
                {
                    "total_docs": 3,
                    "docs_vencidos": 1,
                    "docs_proximos": 2,
                }
            ]
        )
    )

    proveedores = await service.get_proveedores_con_estatus_docs(None)

    assert proveedores[0]["estatus_docs"] == ESTATUS_DOC_VENCIDO


@pytest.mark.asyncio
async def test_estatus_docs_detecta_proximos_sin_vencidos():
    service = ProveedoresService(
        FakeProveedoresDB(
            [
                {
                    "total_docs": 2,
                    "docs_vencidos": 0,
                    "docs_proximos": 1,
                }
            ]
        )
    )

    proveedores = await service.get_proveedores_con_estatus_docs(None)

    assert proveedores[0]["estatus_docs"] == ESTATUS_DOC_PROXIMO


@pytest.mark.asyncio
async def test_estatus_docs_sin_documentos_y_vigente():
    service = ProveedoresService(
        FakeProveedoresDB(
            [
                {"total_docs": 0, "docs_vencidos": 0, "docs_proximos": 0},
                {"total_docs": 1, "docs_vencidos": 0, "docs_proximos": 0},
            ]
        )
    )

    proveedores = await service.get_proveedores_con_estatus_docs(None)

    assert proveedores[0]["estatus_docs"] == ESTATUS_DOC_SIN_DOCS
    assert proveedores[1]["estatus_docs"] == ESTATUS_DOC_VIGENTE


@pytest.mark.asyncio
async def test_registrar_documento_proveedor_pasa_metadata_sharepoint():
    db = RecordingProveedoresDB()
    service = ProveedoresService(db)
    id_proveedor = uuid4()
    id_attachment = uuid4()

    await service.registrar_documento_proveedor(
        None,
        id_proveedor,
        "constancia_fiscal",
        "MORAL",
        "https://sharepoint.test/doc.pdf",
        id_documento_attachment=id_attachment,
        nombre_archivo="doc.pdf",
        tipo_contenido="application/pdf",
        tamano_bytes=123,
        drive_item_id="drive-item",
        parent_drive_id="drive",
        folder_path="base/proveedores",
        periodo="2026-05",
        nombre_documento_personalizado=None,
    )

    assert db.insert_args[:5] == (
        None,
        id_proveedor,
        "constancia_fiscal",
        "MORAL",
        "https://sharepoint.test/doc.pdf",
    )
    assert db.insert_kwargs["id_documento_attachment"] == id_attachment
    assert db.insert_kwargs["drive_item_id"] == "drive-item"
    assert db.insert_kwargs["periodo"] == "2026-05"


@pytest.mark.asyncio
async def test_get_documento_archivo_descarga_por_drive_item_id():
    id_proveedor = uuid4()
    doc_id = uuid4()
    sp_factory = FakeSharePointFactory({"drive-item": b"contenido-pdf"})
    service = ProveedoresService(
        FakeProveedoresDB(
            [],
            documento={
                "id": doc_id,
                "id_proveedor": id_proveedor,
                "tipo_documento": "constancia_fiscal",
                "sharepoint_url": "https://sharepoint.test/doc.pdf",
                "nombre_archivo": "constancia.pdf",
                "tipo_contenido": "application/pdf",
                "drive_item_id": "drive-item",
            },
        ),
        ms_auth=FakeMSAuth(),
        sharepoint_factory=sp_factory,
    )

    archivo = await service.get_documento_archivo(None, id_proveedor, doc_id)

    assert archivo.contenido == b"contenido-pdf"
    assert archivo.redirect_url is None
    assert archivo.nombre_archivo == "constancia.pdf"
    assert archivo.media_type == "application/pdf"
    assert sp_factory.instances[0].drive_id == "drive-id"


@pytest.mark.asyncio
async def test_get_documento_archivo_fallback_a_sharepoint_url_sin_drive_item_id():
    id_proveedor = uuid4()
    doc_id = uuid4()
    sp_factory = FakeSharePointFactory({})
    service = ProveedoresService(
        FakeProveedoresDB(
            [],
            documento={
                "id": doc_id,
                "id_proveedor": id_proveedor,
                "tipo_documento": "acta_constitutiva",
                "sharepoint_url": "https://sharepoint.test/acta.pdf",
                "nombre_archivo": "acta.pdf",
                "tipo_contenido": "application/pdf",
                "drive_item_id": None,
            },
        ),
        ms_auth=FakeMSAuth(),
        sharepoint_factory=sp_factory,
    )

    archivo = await service.get_documento_archivo(None, id_proveedor, doc_id)

    assert archivo.contenido is None
    assert archivo.redirect_url == "https://sharepoint.test/acta.pdf"
    assert sp_factory.instances == []


@pytest.mark.asyncio
async def test_generar_zip_expediente_agrupa_vigentes_por_categoria():
    id_proveedor = uuid4()
    sp_factory = FakeSharePointFactory(
        {
            "fiscal-item": b"fiscal",
            "legal-item": b"legal",
        }
    )
    service = ProveedoresService(
        FakeProveedoresDB(
            [],
            documentos_vigentes=[
                {
                    "id": uuid4(),
                    "id_proveedor": id_proveedor,
                    "rfc": "ABC123456T1A",
                    "razon_social": "Proveedor Test",
                    "tipo_documento": "constancia_fiscal",
                    "nombre_archivo": "constancia.pdf",
                    "tipo_contenido": "application/pdf",
                    "drive_item_id": "fiscal-item",
                    "sharepoint_url": "https://sharepoint.test/constancia.pdf",
                },
                {
                    "id": uuid4(),
                    "id_proveedor": id_proveedor,
                    "rfc": "ABC123456T1A",
                    "razon_social": "Proveedor Test",
                    "tipo_documento": "acta_constitutiva",
                    "nombre_archivo": "acta.pdf",
                    "tipo_contenido": "application/pdf",
                    "drive_item_id": "legal-item",
                    "sharepoint_url": "https://sharepoint.test/acta.pdf",
                },
                {
                    "id": uuid4(),
                    "id_proveedor": id_proveedor,
                    "rfc": "ABC123456T1A",
                    "razon_social": "Proveedor Test",
                    "tipo_documento": "opinion_cumplimiento",
                    "nombre_archivo": "opinion.pdf",
                    "tipo_contenido": "application/pdf",
                    "drive_item_id": None,
                    "sharepoint_url": "https://sharepoint.test/opinion.pdf",
                },
            ],
        ),
        ms_auth=FakeMSAuth(),
        sharepoint_factory=sp_factory,
    )

    archivo = await service.generar_zip_expediente(None, id_proveedor)

    assert archivo.media_type == "application/zip"
    with zipfile.ZipFile(BytesIO(archivo.contenido)) as zf:
        names = sorted(zf.namelist())
        assert names == [
            "ABC123456T1A - Proveedor Test/Fiscal/constancia.pdf",
            "ABC123456T1A - Proveedor Test/Legal/acta.pdf",
        ]
        assert zf.read("ABC123456T1A - Proveedor Test/Fiscal/constancia.pdf") == b"fiscal"


def test_build_sharepoint_subcarpeta_usa_rfc_razon_social_y_categoria():
    service = ProveedoresService(FakeProveedoresDB([]))
    id_proveedor = uuid4()

    subcarpeta = service.build_sharepoint_subcarpeta(
        {
            "id_proveedor": id_proveedor,
            "rfc": "abc123456t1a",
            "razon_social": "Proveedor: Test/Solar",
        },
        "opinion_cumplimiento",
    )

    assert subcarpeta == "Proveedores/ABC123456T1A - Proveedor_ Test_Solar/01_Fiscal"


def test_templates_proveedores_fase4_cargan_sin_error():
    from jinja2 import Environment, FileSystemLoader

    env = Environment(loader=FileSystemLoader("templates"))

    for template in (
        "compras/partials/modal_proveedor_docs.html",
        "finanzas/partials/lista_proveedores.html",
        "finanzas/partials/proveedor_docs.html",
    ):
        env.get_template(template)


def _context(module_roles=None, role="USER"):
    return {
        "user_db_id": uuid4(),
        "user_name": "Usuario Test",
        "email": "test@example.com",
        "role": role,
        "module_roles": module_roles or {},
    }


def _proveedores_client(context, service):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from core.database import get_db_connection
    from core.security import get_current_user_context
    from modules.proveedores.router import router as proveedores_router
    from modules.proveedores.service import get_proveedores_service

    async def fake_conn():
        yield None

    app = FastAPI()
    app.include_router(proveedores_router)
    app.dependency_overrides[get_current_user_context] = lambda: context
    app.dependency_overrides[get_db_connection] = fake_conn
    app.dependency_overrides[get_proveedores_service] = lambda: service
    return TestClient(app)


@pytest.mark.parametrize(
    "path_builder",
    [
        lambda id_proveedor, doc_id: f"/proveedores/{id_proveedor}/documentos/{doc_id}/metadata",
        lambda id_proveedor, doc_id: f"/proveedores/{id_proveedor}/documentos/{doc_id}/preview",
        lambda id_proveedor, doc_id: f"/proveedores/{id_proveedor}/documentos/{doc_id}/download",
        lambda id_proveedor, doc_id: f"/proveedores/{id_proveedor}/documentos/zip",
    ],
)
def test_endpoints_compartidos_deniegan_usuario_sin_compras_o_finanzas(path_builder):
    service = FakeRouterProveedoresService()
    client = _proveedores_client(_context({"comercial": "viewer"}), service)

    response = client.get(path_builder(service.id_proveedor, service.doc_id))

    assert response.status_code == 403


@pytest.mark.parametrize(
    "context",
    [
        _context({"compras": "viewer"}),
        _context({"finanzas": "viewer"}),
        _context(role="ADMIN"),
    ],
)
def test_endpoints_compartidos_permiten_compras_finanzas_o_admin(context):
    service = FakeRouterProveedoresService()
    client = _proveedores_client(context, service)

    metadata = client.get(
        f"/proveedores/{service.id_proveedor}/documentos/{service.doc_id}/metadata"
    )
    preview = client.get(
        f"/proveedores/{service.id_proveedor}/documentos/{service.doc_id}/preview"
    )
    download = client.get(
        f"/proveedores/{service.id_proveedor}/documentos/{service.doc_id}/download"
    )
    zip_response = client.get(f"/proveedores/{service.id_proveedor}/documentos/zip")

    assert metadata.status_code == 200
    assert metadata.json()["drive_item_id"] == "drive-item"
    assert preview.status_code == 200
    assert preview.headers["content-disposition"].startswith("inline;")
    assert download.status_code == 200
    assert download.headers["content-disposition"].startswith("attachment;")
    assert zip_response.status_code == 200
    assert zip_response.headers["content-type"] == "application/zip"


def _module_client(router, context, service):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from core.database import get_db_connection
    from core.security import get_current_user_context
    from modules.proveedores.service import get_proveedores_service

    async def fake_conn():
        yield None

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user_context] = lambda: context
    app.dependency_overrides[get_db_connection] = fake_conn
    app.dependency_overrides[get_proveedores_service] = lambda: service
    return TestClient(app)


def test_htmx_compras_renderiza_modal_documentos_proveedor():
    from modules.compras.router import router as compras_router

    service = FakeRouterProveedoresService()
    client = _module_client(compras_router, _context({"compras": "viewer"}), service)

    response = client.get(
        f"/compras/proveedores/{service.id_proveedor}/documentos",
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    assert "Documentacion del Proveedor" in response.text
    assert f"/proveedores/{service.id_proveedor}/documentos/zip" in response.text
    assert f"/proveedores/{service.id_proveedor}/documentos/{service.doc_id}/preview" in response.text
    assert "Periodo" in response.text


def test_htmx_finanzas_renderiza_lista_y_documentos_vigentes():
    from modules.finanzas.router import router as finanzas_router

    service = FakeRouterProveedoresService()
    client = _module_client(finanzas_router, _context({"finanzas": "viewer"}), service)

    lista = client.get("/finanzas/proveedores", headers={"HX-Request": "true"})
    docs = client.get(
        f"/finanzas/proveedores/{service.id_proveedor}/documentos",
        headers={"HX-Request": "true"},
    )

    assert lista.status_code == 200
    assert "Documentacion de Proveedores" in lista.text
    assert f"/proveedores/{service.id_proveedor}/documentos/zip" in lista.text
    assert docs.status_code == 200
    assert "constancia.pdf" in docs.text
    assert f"/proveedores/{service.id_proveedor}/documentos/{service.doc_id}/download" in docs.text
