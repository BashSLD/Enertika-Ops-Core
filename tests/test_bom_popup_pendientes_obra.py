"""
Tests unitarios del popup de autorizaciones de Obra pendientes al entrar a la
app (_Planes_Activos/PLAN_popup_pendientes_autorizacion_obra.md): la query
cross-BOM del service (titular directo, via suplencia, fallback
jefe_construccion sin coordinador asignado, exclusion de terceros) y el gate
de acceso extendido de compras_paquete_ui/preview_pdf_cotizacion (§4).
"""
from uuid import uuid4

import pytest
from fastapi import HTTPException

import core.bom.router  # noqa: F401 -- fuerza el orden de import (evita circular import con compras_router)
from core.bom.compras_router import _exigir_acceso_paquete_o_403
from core.bom.service import BomService


class FakeConn:
    pass


class FakePopupDB:
    def __init__(self, titulares=None, autorizaciones=None, items=None):
        self.titulares = titulares or []
        self.autorizaciones = autorizaciones or []
        self.items = items or []
        self.llamadas_autorizaciones = 0
        self.llamadas_items = 0
        self.representados_recibidos = None
        self.rol_org_recibido = None

    async def get_titulares_que_representa(self, conn, suplente_id):
        return self.titulares

    async def get_autorizaciones_pendientes_por_coordinador(self, conn, representados, rol_organizacional):
        self.llamadas_autorizaciones += 1
        self.representados_recibidos = set(representados)
        self.rol_org_recibido = rol_organizacional
        return self.autorizaciones

    async def get_items_by_cotizacion_ids(self, conn, cotizacion_ids):
        self.llamadas_items += 1
        return self.items


def _autorizacion(cotizacion_id, id_paquete, **extra):
    data = {
        "id": uuid4(),
        "cotizacion_id": cotizacion_id,
        "bom_id": uuid4(),
        "estatus": "PENDIENTE",
        "monto_total": 1000.0,
        "moneda": "MXN",
        "nombre_proveedor": "Proveedor Uno",
        "id_paquete": id_paquete,
        "paquete_codigo": "PAQ-1",
        "paquete_nombre": "Paquete de prueba",
    }
    data.update(extra)
    return data


@pytest.mark.asyncio
async def test_listar_pendientes_incluye_titular_directo_y_no_hace_n_mas_uno():
    user_id = uuid4()
    cotizacion_id = uuid4()
    db = FakePopupDB(
        titulares=[],
        autorizaciones=[_autorizacion(cotizacion_id, uuid4())],
        items=[{"cotizacion_id": cotizacion_id, "descripcion": "Item A"}],
    )
    svc = BomService()
    svc.db = db

    resultado = await svc.listar_pendientes_popup_coordinador(FakeConn(), user_id, None)

    assert len(resultado) == 1
    assert resultado[0]["items"] == [{"cotizacion_id": cotizacion_id, "descripcion": "Item A"}]
    # user_id siempre se agrega a representados (get_titulares_que_representa en service.py)
    assert user_id in db.representados_recibidos
    # una sola query de autorizaciones + una sola de items, sin loop por autorizacion
    assert db.llamadas_autorizaciones == 1
    assert db.llamadas_items == 1


@pytest.mark.asyncio
async def test_listar_pendientes_incluye_titular_representado_via_suplencia():
    suplente_id = uuid4()
    titular_id = uuid4()
    db = FakePopupDB(titulares=[titular_id], autorizaciones=[])
    svc = BomService()
    svc.db = db

    await svc.listar_pendientes_popup_coordinador(FakeConn(), suplente_id, None)

    assert db.representados_recibidos == {suplente_id, titular_id}


@pytest.mark.asyncio
async def test_listar_pendientes_pasa_rol_organizacional_para_fallback_jefe_construccion():
    user_id = uuid4()
    db = FakePopupDB(titulares=[], autorizaciones=[])
    svc = BomService()
    svc.db = db

    await svc.listar_pendientes_popup_coordinador(FakeConn(), user_id, "jefe_construccion")

    assert db.rol_org_recibido == "jefe_construccion"


@pytest.mark.asyncio
async def test_listar_pendientes_vacio_no_llama_a_items():
    db = FakePopupDB(titulares=[], autorizaciones=[])
    svc = BomService()
    svc.db = db

    resultado = await svc.listar_pendientes_popup_coordinador(FakeConn(), uuid4(), None)

    assert resultado == []
    assert db.llamadas_items == 0


# ─── Gate de acceso extendido (§4): compras_paquete_ui / preview_pdf_cotizacion ───

class FakeGateDB:
    def __init__(self, titulares=None):
        self.titulares = titulares or []

    async def get_titulares_que_representa(self, conn, suplente_id):
        return self.titulares


def _context(role="USER", module_roles=None, rol_organizacional=None, user_db_id=None):
    return {
        "role": role,
        "module_roles": module_roles or {},
        "rol_organizacional": rol_organizacional,
        "user_db_id": user_db_id or uuid4(),
    }


async def _exigir(svc, context, bom):
    """Replica el gate real: el caller (router) calcula tiene_acceso_modulo
    primero y se lo pasa ya resuelto a _exigir_acceso_paquete_o_403."""
    tiene_acceso_modulo = BomService.tiene_acceso_modulo_compras(context)
    await _exigir_acceso_paquete_o_403(
        svc, FakeConn(), context, bom, tiene_acceso_modulo, "este paquete",
    )


@pytest.mark.asyncio
async def test_gate_permite_coordinador_de_obra_sin_acceso_de_modulo():
    user_id = uuid4()
    bom = {"coordinador_obra": user_id}
    svc = BomService()
    svc.db = FakeGateDB(titulares=[])

    # No lanza HTTPException: coordinador de obra directo, sin ningun modulo asignado.
    await _exigir(svc, _context(role="USER", module_roles={}, user_db_id=user_id), bom)


@pytest.mark.asyncio
async def test_gate_permite_suplente_del_coordinador_de_obra():
    titular_id = uuid4()
    suplente_id = uuid4()
    bom = {"coordinador_obra": titular_id}
    svc = BomService()
    svc.db = FakeGateDB(titulares=[titular_id])

    await _exigir(svc, _context(role="USER", module_roles={}, user_db_id=suplente_id), bom)


@pytest.mark.asyncio
async def test_gate_permite_jefe_construccion_si_paquete_sin_coordinador():
    bom = {"coordinador_obra": None}
    svc = BomService()
    svc.db = FakeGateDB(titulares=[])

    await _exigir(
        svc, _context(role="USER", module_roles={}, rol_organizacional="jefe_construccion"), bom,
    )


@pytest.mark.asyncio
async def test_gate_permite_acceso_de_modulo_normal_sin_consultar_bom():
    svc = BomService()
    svc.db = FakeGateDB(titulares=[])

    await _exigir(svc, _context(role="USER", module_roles={"compras": "editor"}), None)


@pytest.mark.asyncio
async def test_gate_rechaza_usuario_sin_modulo_ni_coordinacion():
    bom = {"coordinador_obra": uuid4()}
    svc = BomService()
    svc.db = FakeGateDB(titulares=[])

    with pytest.raises(HTTPException) as exc_info:
        await _exigir(svc, _context(role="USER", module_roles={}), bom)
    assert exc_info.value.status_code == 403
