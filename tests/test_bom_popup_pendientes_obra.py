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
    def __init__(self, titulares=None, autorizaciones=None, items=None, total=None):
        self.titulares = titulares or []
        self.autorizaciones = autorizaciones or []
        self.items = items or []
        self.total = total if total is not None else len(self.autorizaciones)
        self.llamadas_autorizaciones = 0
        self.llamadas_items = 0
        self.llamadas_count = 0
        self.representados_recibidos = None
        self.rol_org_recibido = None
        self.limit_recibido = None
        self.offset_recibido = None
        self.id_proyecto_recibido = None

    async def get_titulares_que_representa(self, conn, suplente_id):
        return self.titulares

    async def get_autorizaciones_pendientes_por_coordinador(
        self, conn, representados, rol_organizacional, limit=20, offset=0, id_proyecto=None,
    ):
        self.llamadas_autorizaciones += 1
        self.representados_recibidos = set(representados)
        self.rol_org_recibido = rol_organizacional
        self.limit_recibido = limit
        self.offset_recibido = offset
        self.id_proyecto_recibido = id_proyecto
        return self.autorizaciones

    async def get_items_by_cotizacion_ids(self, conn, cotizacion_ids):
        self.llamadas_items += 1
        return self.items

    async def contar_autorizaciones_pendientes_por_coordinador(
        self, conn, representados, rol_organizacional, id_proyecto=None,
    ):
        self.llamadas_count += 1
        return self.total


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
    # user_id siempre se agrega a representados (get_titulares_que_representa en service.py)
    assert user_id in db.representados_recibidos
    # una sola query de autorizaciones, sin loop por autorizacion; el banner
    # simplificado (2026-09-02) ya no muestra items, asi que no se batch-fetchean
    assert db.llamadas_autorizaciones == 1
    assert db.llamadas_items == 0


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


# ─── Variante paginada cross-proyecto: listar_autorizaciones_obra_coordinador ───

@pytest.mark.asyncio
async def test_popup_usa_defaults_limit_20_offset_0_sin_tocarlos():
    """El popup (listar_pendientes_popup_coordinador) no pasa limit/offset --
    debe preservar exactamente el LIMIT 20 fijo que tenia antes de la extension
    de la query (plan Ronda A, seccion 2)."""
    db = FakePopupDB(titulares=[], autorizaciones=[])
    svc = BomService()
    svc.db = db

    await svc.listar_pendientes_popup_coordinador(FakeConn(), uuid4(), None)

    assert db.limit_recibido == 20
    assert db.offset_recibido == 0


@pytest.mark.asyncio
async def test_listar_autorizaciones_obra_coordinador_no_llama_a_items():
    cotizacion_id = uuid4()
    db = FakePopupDB(
        titulares=[],
        autorizaciones=[_autorizacion(cotizacion_id, uuid4())],
        items=[{"cotizacion_id": cotizacion_id, "descripcion": "Item A"}],
    )
    svc = BomService()
    svc.db = db

    autorizaciones, total = await svc.listar_autorizaciones_obra_coordinador(
        FakeConn(), uuid4(), None,
    )

    assert len(autorizaciones) == 1
    assert "items" not in autorizaciones[0]
    assert db.llamadas_items == 0
    assert total == 1


@pytest.mark.asyncio
async def test_listar_autorizaciones_obra_coordinador_propaga_paginacion_y_total_real():
    db = FakePopupDB(titulares=[], autorizaciones=[], total=57)
    svc = BomService()
    svc.db = db

    autorizaciones, total = await svc.listar_autorizaciones_obra_coordinador(
        FakeConn(), uuid4(), None, limit=25, offset=50,
    )

    assert db.limit_recibido == 25
    assert db.offset_recibido == 50
    assert db.llamadas_count == 1
    assert total == 57


@pytest.mark.asyncio
async def test_listar_autorizaciones_obra_coordinador_propaga_id_proyecto():
    """`id_proyecto` (modo solo-lectura por proyecto) debe llegar tal cual a
    ambas queries del db_service (autorizaciones y conteo)."""
    id_proyecto = uuid4()
    db = FakePopupDB(titulares=[], autorizaciones=[], total=0)
    svc = BomService()
    svc.db = db

    await svc.listar_autorizaciones_obra_coordinador(
        FakeConn(), uuid4(), None, id_proyecto=id_proyecto,
    )

    assert db.id_proyecto_recibido == id_proyecto


@pytest.mark.asyncio
async def test_listar_autorizaciones_obra_coordinador_marca_puede_actuar_por_fila():
    """Cada fila lleva `puede_actuar` calculado con el mismo predicado que el
    gate real (BomService.es_coordinador_obra) -- el template usa esta bandera
    para decidir entre Aprobar/Rechazar o mostrar el coordinador asignado."""
    user_id = uuid4()
    coordinador_propio = user_id
    coordinador_ajeno = uuid4()
    db = FakePopupDB(
        titulares=[],
        autorizaciones=[
            _autorizacion(uuid4(), uuid4(), coordinador_obra=coordinador_propio),
            _autorizacion(uuid4(), uuid4(), coordinador_obra=coordinador_ajeno),
        ],
    )
    svc = BomService()
    svc.db = db

    autorizaciones, _ = await svc.listar_autorizaciones_obra_coordinador(
        FakeConn(), user_id, None,
    )

    assert autorizaciones[0]["puede_actuar"] is True
    assert autorizaciones[1]["puede_actuar"] is False


@pytest.mark.asyncio
async def test_listar_autorizaciones_obra_coordinador_jefe_construccion_puede_actuar_con_coordinador_asignado():
    """Autoridad permanente de jefe_construccion (decision 2026-09-02): incluso
    con un coordinador_obra asignado que no es el usuario, jefe_construccion
    puede actuar en cualquier fila."""
    db = FakePopupDB(
        titulares=[],
        autorizaciones=[_autorizacion(uuid4(), uuid4(), coordinador_obra=uuid4())],
    )
    svc = BomService()
    svc.db = db

    autorizaciones, _ = await svc.listar_autorizaciones_obra_coordinador(
        FakeConn(), uuid4(), "jefe_construccion",
    )

    assert autorizaciones[0]["puede_actuar"] is True


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
