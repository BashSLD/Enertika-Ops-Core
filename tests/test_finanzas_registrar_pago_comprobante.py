"""
Tests de registrar_pago con comprobante real (Fase 4 del plan
_Planes_Activos/2026-06-29-aprobaciones-cotizaciones-post-bom.md, seccion ## 16): si se adjunta un
PDF, se sube via ComprasService.upload_archivo_sharepoint (origen_slug='comprobante_pago') ANTES de
la transaccion (para no mantener el lock FOR UPDATE de la autorizacion durante el upload), con un
id_comprobante generado por FinanzasService y compartido entre tb_bom_pagos.comprobante_url y
tb_comprobantes_pago.
"""

from decimal import Decimal
from datetime import date
from uuid import uuid4

import pytest

from core.bom.db_service import BomDBService
from modules.compras.service import ComprasService
from modules.finanzas.service import FinanzasService


class FakeConn:
    def transaction(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _autorizacion(autorizacion_id, **extra):
    data = {
        "id": autorizacion_id,
        "estatus": "AUTORIZADO_FINANZAS",
        "lock_version": 0,
        "moneda": "MXN",
        "monto_total": Decimal("1000.00"),
        "monto_pagado_acumulado": Decimal("0"),
        "nombre_proveedor": "Proveedor Uno",
        "proveedor_id": uuid4(),
        "proyecto_id": uuid4(),
        "id_paquete": uuid4(),
        "bom_id": uuid4(),
        "bom_version": 1,
        "paquete_codigo": "PKG-1",
        "cotizacion_id": None,
    }
    data.update(extra)
    return data


class FakeFinanzasDB:
    def __init__(self, autorizacion):
        self.autorizacion = dict(autorizacion)
        self.crear_pago_calls = []
        self.crear_comprobante_calls = []

    async def get_autorizacion_para_pago_for_update(self, conn, autorizacion_id):
        return dict(self.autorizacion)

    async def get_pago_por_clave_idempotencia(self, conn, clave):
        return None

    async def crear_pago_db(self, conn, **kwargs):
        self.crear_pago_calls.append(kwargs)
        return {"id": uuid4(), **kwargs}

    async def actualizar_estatus_autorizacion(self, conn, autorizacion_id, estatus_esperado,
                                                lock_version_esperado, nuevo_estatus):
        return {**self.autorizacion, "estatus": nuevo_estatus, "lock_version": lock_version_esperado + 1}

    async def crear_comprobante_bom(self, conn, **kwargs):
        self.crear_comprobante_calls.append(kwargs)


def make_service(autorizacion):
    db = FakeFinanzasDB(autorizacion)
    return FinanzasService(db=db), db


async def _noop_outbox(self, *a, **kw):
    return None


@pytest.mark.asyncio
async def test_no_sube_archivo_si_no_se_adjunto(monkeypatch):
    async def _no_deberia_llamarse(self, *a, **kw):
        raise AssertionError("no debe subir a SharePoint si no hay archivo adjunto")

    monkeypatch.setattr(ComprasService, "upload_archivo_sharepoint", _no_deberia_llamarse)
    monkeypatch.setattr(BomDBService, "registrar_evento_outbox", _noop_outbox)

    autorizacion_id = uuid4()
    svc, db = make_service(_autorizacion(autorizacion_id))

    await svc.registrar_pago(
        FakeConn(), autorizacion_id=autorizacion_id, monto_pagado=Decimal("1000.00"),
        moneda="MXN", tipo_cambio_usado=None, fecha_pago=date.today(),
        referencia_bancaria=None, registrado_por=uuid4(), lock_version_esperado=0,
        clave_idempotencia="clave-1", archivo=None,
    )
    assert db.crear_pago_calls[0]["comprobante_url"] is None
    assert db.crear_comprobante_calls


@pytest.mark.asyncio
async def test_sube_archivo_y_comparte_id_comprobante_con_pago(monkeypatch):
    calls = []

    async def _fake_upload(self, conn, file, subcarpeta, id_comprobante, origen_slug, user_id,
                            metadata_extra=None, id_bom_cotizacion=None):
        calls.append({
            "id_comprobante": id_comprobante, "origen_slug": origen_slug,
            "subcarpeta": subcarpeta,
        })
        return {"url_sharepoint": "https://sharepoint/comprobante.pdf"}

    monkeypatch.setattr(ComprasService, "upload_archivo_sharepoint", _fake_upload)
    monkeypatch.setattr(BomDBService, "registrar_evento_outbox", _noop_outbox)

    autorizacion_id = uuid4()
    svc, db = make_service(_autorizacion(autorizacion_id))

    await svc.registrar_pago(
        FakeConn(), autorizacion_id=autorizacion_id, monto_pagado=Decimal("1000.00"),
        moneda="MXN", tipo_cambio_usado=None, fecha_pago=date.today(),
        referencia_bancaria=None, registrado_por=uuid4(), lock_version_esperado=0,
        clave_idempotencia="clave-2", archivo=object(),
    )

    assert len(calls) == 1
    assert calls[0]["origen_slug"] == "comprobante_pago"
    assert db.crear_pago_calls[0]["comprobante_url"] == "https://sharepoint/comprobante.pdf"
    assert db.crear_comprobante_calls[0]["id_comprobante"] == calls[0]["id_comprobante"]


@pytest.mark.asyncio
async def test_registra_pago_aunque_falle_la_subida(monkeypatch):
    async def _fake_upload_falla(self, *a, **kw):
        return None

    monkeypatch.setattr(ComprasService, "upload_archivo_sharepoint", _fake_upload_falla)
    monkeypatch.setattr(BomDBService, "registrar_evento_outbox", _noop_outbox)

    autorizacion_id = uuid4()
    svc, db = make_service(_autorizacion(autorizacion_id))

    await svc.registrar_pago(
        FakeConn(), autorizacion_id=autorizacion_id, monto_pagado=Decimal("1000.00"),
        moneda="MXN", tipo_cambio_usado=None, fecha_pago=date.today(),
        referencia_bancaria=None, registrado_por=uuid4(), lock_version_esperado=0,
        clave_idempotencia="clave-3", archivo=object(),
    )
    assert db.crear_pago_calls[0]["comprobante_url"] is None
    assert db.crear_comprobante_calls
