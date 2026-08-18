"""
Tests de subida real de PDF de cotizacion BOM (Fase 2 del plan
_Planes_Activos/2026-06-29-aprobaciones-cotizaciones-post-bom.md, seccion ## 16):
subir_pdf_cotizacion sube el archivo via ComprasService.upload_archivo_sharepoint
(origen_slug='cotizacion_bom') y actualiza pdf_url, bloqueando si la cotizacion
tiene una aprobacion de Direccion APROBADA activa.
"""

from uuid import uuid4

import pytest

from core.bom.service import BomService
from modules.compras.service import ComprasService


class FakeConn:
    def transaction(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakePdfFile:
    content_type = "application/pdf"


class FakeDB:
    def __init__(self, cotizacion, aprobacion=None):
        self.cotizacion = dict(cotizacion)
        self.aprobacion = aprobacion
        self.actualizar_calls = []
        self.eliminados = []

    async def get_cotizacion_by_id(self, conn, cotizacion_id):
        return dict(self.cotizacion) if self.cotizacion["id"] == cotizacion_id else None

    async def get_cotizacion_aprobacion_activa(self, conn, cotizacion_id):
        return dict(self.aprobacion) if self.aprobacion else None

    async def actualizar_pdf_cotizacion(self, conn, cotizacion_id, pdf_url, lock_version_esperado):
        self.actualizar_calls.append((cotizacion_id, pdf_url, lock_version_esperado))
        if lock_version_esperado != self.cotizacion["lock_version"]:
            return None
        self.cotizacion["pdf_url"] = pdf_url
        self.cotizacion["estatus"] = "RECIBIDA"
        self.cotizacion["lock_version"] += 1
        return dict(self.cotizacion)

    async def eliminar_attachment_huerfano(self, conn, doc_id):
        self.eliminados.append(doc_id)


def _cotizacion(cotizacion_id, lock_version=0):
    return {"id": cotizacion_id, "estatus": "BORRADOR", "pdf_url": None, "lock_version": lock_version}


def make_service(cotizacion, aprobacion=None):
    svc = BomService()
    svc.db = FakeDB(cotizacion, aprobacion)
    return svc


@pytest.mark.asyncio
async def test_bloquea_subida_si_aprobacion_activa_esta_aprobada(monkeypatch):
    cotizacion_id = uuid4()
    svc = make_service(
        _cotizacion(cotizacion_id),
        aprobacion={"id": uuid4(), "estatus": "APROBADA"},
    )

    async def _no_deberia_llamarse(self, *a, **kw):
        raise AssertionError("no debe subir a SharePoint si la aprobacion esta APROBADA")

    monkeypatch.setattr(ComprasService, "upload_archivo_sharepoint", _no_deberia_llamarse)

    with pytest.raises(ValueError, match="aprobada por Dirección"):
        await svc.subir_pdf_cotizacion(FakeConn(), cotizacion_id, object(), uuid4(), 0)


@pytest.mark.asyncio
async def test_sube_pdf_y_actualiza_url(monkeypatch):
    cotizacion_id = uuid4()
    svc = make_service(_cotizacion(cotizacion_id, lock_version=2))

    async def _fake_upload(self, conn, file, subcarpeta, id_comprobante, origen_slug, user_id,
                            metadata_extra=None, id_bom_cotizacion=None):
        assert origen_slug == "cotizacion_bom"
        assert id_bom_cotizacion == cotizacion_id
        assert id_comprobante is None
        return {"url_sharepoint": "https://sharepoint/cot.pdf", "id_documento_attachment": str(uuid4())}

    monkeypatch.setattr(ComprasService, "upload_archivo_sharepoint", _fake_upload)

    updated = await svc.subir_pdf_cotizacion(FakeConn(), cotizacion_id, FakePdfFile(), uuid4(), 2)

    assert updated["pdf_url"] == "https://sharepoint/cot.pdf"
    assert updated["estatus"] == "RECIBIDA"
    assert svc.db.actualizar_calls == [(cotizacion_id, "https://sharepoint/cot.pdf", 2)]


@pytest.mark.asyncio
async def test_falla_si_upload_sharepoint_regresa_none(monkeypatch):
    cotizacion_id = uuid4()
    svc = make_service(_cotizacion(cotizacion_id))

    async def _fake_upload_falla(self, *a, **kw):
        return None

    monkeypatch.setattr(ComprasService, "upload_archivo_sharepoint", _fake_upload_falla)

    with pytest.raises(ValueError, match="No se pudo subir"):
        await svc.subir_pdf_cotizacion(FakeConn(), cotizacion_id, FakePdfFile(), uuid4(), 0)


@pytest.mark.asyncio
async def test_rechaza_archivo_que_no_es_pdf(monkeypatch):
    """Defensa contra XSS almacenado: el preview sirve el archivo inline, asi
    que un content_type distinto a application/pdf (ej. text/html) se rechaza
    en el upload en vez de confiar en el header que manda el cliente."""
    cotizacion_id = uuid4()
    svc = make_service(_cotizacion(cotizacion_id))

    async def _no_deberia_llamarse(self, *a, **kw):
        raise AssertionError("no debe subir a SharePoint un archivo que no es PDF")

    monkeypatch.setattr(ComprasService, "upload_archivo_sharepoint", _no_deberia_llamarse)

    class FakeHtmlFile:
        content_type = "text/html"

    with pytest.raises(ValueError, match="debe ser un PDF"):
        await svc.subir_pdf_cotizacion(FakeConn(), cotizacion_id, FakeHtmlFile(), uuid4(), 0)


@pytest.mark.asyncio
async def test_falla_si_lock_version_no_coincide(monkeypatch):
    cotizacion_id = uuid4()
    svc = make_service(_cotizacion(cotizacion_id, lock_version=5))
    doc_id = uuid4()

    async def _fake_upload(self, *a, **kw):
        return {"url_sharepoint": "https://sharepoint/cot.pdf", "id_documento_attachment": str(doc_id)}

    monkeypatch.setattr(ComprasService, "upload_archivo_sharepoint", _fake_upload)

    with pytest.raises(ValueError):
        await svc.subir_pdf_cotizacion(FakeConn(), cotizacion_id, FakePdfFile(), uuid4(), 0)

    # El attachment huerfano se limpia para que el /preview no lo sirva por error.
    assert svc.db.eliminados == [str(doc_id)]
