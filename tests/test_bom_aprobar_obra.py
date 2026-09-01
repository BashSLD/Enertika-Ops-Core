"""
Cobertura minima de BomService.aprobar_obra (core/bom/compras_service.py:893),
que hasta ahora no tenia NINGUN test directo (contraste: rechazar_autorizacion
si tenia cobertura parcial via tests/test_bom_cotizacion_parcial.py) pese a que
los 2 endpoints nuevos de la tabla cross-proyecto "Mis Autorizaciones"
(tests/test_bom_obra_autorizaciones.py) lo reusan tal cual.

_Planes_Activos/2026-08-31-plan-tabla-autorizaciones-obra-cross-proyecto.md,
seccion 6, primer punto pendiente: exito, CAS/lock_version obsoleto y
coordinador invalido.
"""
from uuid import uuid4

import pytest

from core.bom.service import BomService


class FakeConn:
    def transaction(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _bom(bom_id, coordinador_obra=None, **extra):
    data = {"id_bom": bom_id, "id_paquete": uuid4(), "coordinador_obra": coordinador_obra}
    data.update(extra)
    return data


def _autorizacion(autorizacion_id, bom_id, estatus="PENDIENTE", **extra):
    data = {
        "id": autorizacion_id,
        "bom_id": bom_id,
        "proyecto_id": uuid4(),
        "estatus": estatus,
        "lock_version": 0,
    }
    data.update(extra)
    return data


class FakeAprobarObraDB:
    def __init__(self, bom, autorizacion, titulares_por_suplente=None):
        self.bom = dict(bom)
        self.autorizacion = dict(autorizacion)
        self.titulares_por_suplente = titulares_por_suplente or {}
        self.eventos_outbox = []

    async def get_autorizacion_by_id(self, conn, autorizacion_id):
        return dict(self.autorizacion) if autorizacion_id == self.autorizacion["id"] else None

    async def get_bom_by_id(self, conn, id_bom):
        return dict(self.bom) if id_bom == self.bom["id_bom"] else None

    async def get_titulares_que_representa(self, conn, user_id):
        return list(self.titulares_por_suplente.get(user_id, []))

    async def get_autorizacion_for_update(self, conn, autorizacion_id):
        return dict(self.autorizacion) if autorizacion_id == self.autorizacion["id"] else None

    async def update_autorizacion_paso_obra(self, conn, autorizacion_id, user_id, nota, lock_version_esperado):
        aut = self.autorizacion
        if (
            aut["id"] != autorizacion_id
            or aut["estatus"] != "PENDIENTE"
            or aut["lock_version"] != lock_version_esperado
        ):
            return None
        aut.update({
            "estatus": "AUTORIZADO_OBRA",
            "aprobador_obra_id": user_id,
            "nota_obra": nota,
            "lock_version": lock_version_esperado + 1,
        })
        return dict(aut)

    async def registrar_evento_outbox(self, conn, id_evento, tipo_evento, *args, **kwargs):
        self.eventos_outbox.append({"id_evento": id_evento, "tipo_evento": tipo_evento, **kwargs})


def _service(bom, autorizacion, titulares_por_suplente=None):
    db = FakeAprobarObraDB(bom, autorizacion, titulares_por_suplente)
    svc = BomService()
    svc.db = db
    return svc, db


# ─── EXITO ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_aprobar_obra_titular_exito():
    user_id = uuid4()
    bom_id, autorizacion_id = uuid4(), uuid4()
    bom = _bom(bom_id, coordinador_obra=user_id)
    aut = _autorizacion(autorizacion_id, bom_id)
    svc, db = _service(bom, aut)

    updated = await svc.aprobar_obra(
        FakeConn(), autorizacion_id, user_id, "Adelante", "USER",
        lock_version_esperado=0,
    )

    assert updated["estatus"] == "AUTORIZADO_OBRA"
    assert updated["aprobador_obra_id"] == user_id
    assert updated["nota_obra"] == "Adelante"
    assert updated["lock_version"] == 1
    assert any(e["tipo_evento"] == "AUTORIZACION_OBRA" for e in db.eventos_outbox)


@pytest.mark.asyncio
async def test_aprobar_obra_suplente_activo_tambien_puede():
    titular_id, suplente_id = uuid4(), uuid4()
    bom_id, autorizacion_id = uuid4(), uuid4()
    bom = _bom(bom_id, coordinador_obra=titular_id)
    aut = _autorizacion(autorizacion_id, bom_id)
    svc, _ = _service(bom, aut, titulares_por_suplente={suplente_id: [titular_id]})

    updated = await svc.aprobar_obra(
        FakeConn(), autorizacion_id, suplente_id, None, "USER",
        lock_version_esperado=0,
    )

    assert updated["estatus"] == "AUTORIZADO_OBRA"
    assert updated["aprobador_obra_id"] == suplente_id


@pytest.mark.asyncio
async def test_aprobar_obra_jefe_construccion_si_bom_sin_coordinador():
    user_id = uuid4()
    bom_id, autorizacion_id = uuid4(), uuid4()
    bom = _bom(bom_id, coordinador_obra=None)
    aut = _autorizacion(autorizacion_id, bom_id)
    svc, _ = _service(bom, aut)

    updated = await svc.aprobar_obra(
        FakeConn(), autorizacion_id, user_id, None, "USER",
        lock_version_esperado=0, rol_organizacional="jefe_construccion",
    )

    assert updated["estatus"] == "AUTORIZADO_OBRA"


@pytest.mark.asyncio
async def test_aprobar_obra_jefe_construccion_incluso_con_coordinador_asignado():
    """Autoridad permanente (decision 2026-09-02): jefe_construccion, siendo el
    superior organizacional de coordinador_obra, puede aprobar en su nombre
    aunque el BOM SI tenga un coordinador de obra asignado -- cubre el caso
    donde el CO no puede ingresar y no configuro un suplente."""
    jefe_construccion_id = uuid4()
    coordinador_obra_id = uuid4()
    bom_id, autorizacion_id = uuid4(), uuid4()
    bom = _bom(bom_id, coordinador_obra=coordinador_obra_id)
    aut = _autorizacion(autorizacion_id, bom_id)
    svc, _ = _service(bom, aut)

    updated = await svc.aprobar_obra(
        FakeConn(), autorizacion_id, jefe_construccion_id, None, "USER",
        lock_version_esperado=0, rol_organizacional="jefe_construccion",
    )

    assert updated["estatus"] == "AUTORIZADO_OBRA"
    assert updated["aprobador_obra_id"] == jefe_construccion_id


# ─── COORDINADOR INVALIDO ─────────────────────────────────────

@pytest.mark.asyncio
async def test_aprobar_obra_falla_si_no_es_coordinador_ni_suplente():
    bom_id, autorizacion_id = uuid4(), uuid4()
    bom = _bom(bom_id, coordinador_obra=uuid4())
    aut = _autorizacion(autorizacion_id, bom_id)
    svc, db = _service(bom, aut)

    with pytest.raises(ValueError, match="coordinador de obra"):
        await svc.aprobar_obra(
            FakeConn(), autorizacion_id, uuid4(), None, "USER",
            lock_version_esperado=0,
        )
    assert db.autorizacion["estatus"] == "PENDIENTE"


@pytest.mark.asyncio
async def test_aprobar_obra_falla_sin_coordinador_asignado_y_sin_jefe_construccion():
    bom_id, autorizacion_id = uuid4(), uuid4()
    bom = _bom(bom_id, coordinador_obra=None)
    aut = _autorizacion(autorizacion_id, bom_id)
    svc, _ = _service(bom, aut)

    with pytest.raises(ValueError, match="jefe de Construccion"):
        await svc.aprobar_obra(
            FakeConn(), autorizacion_id, uuid4(), None, "USER",
            lock_version_esperado=0, rol_organizacional=None,
        )


# ─── ESTADO / CAS ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_aprobar_obra_falla_si_autorizacion_no_encontrada():
    bom_id = uuid4()
    bom = _bom(bom_id, coordinador_obra=uuid4())
    aut = _autorizacion(uuid4(), bom_id)
    svc, _ = _service(bom, aut)

    with pytest.raises(ValueError, match="no encontrada"):
        await svc.aprobar_obra(
            FakeConn(), uuid4(), uuid4(), None, "USER",
            lock_version_esperado=0,
        )


@pytest.mark.asyncio
async def test_aprobar_obra_falla_si_no_esta_pendiente():
    user_id = uuid4()
    bom_id, autorizacion_id = uuid4(), uuid4()
    bom = _bom(bom_id, coordinador_obra=user_id)
    aut = _autorizacion(autorizacion_id, bom_id, estatus="AUTORIZADO_OBRA")
    svc, _ = _service(bom, aut)

    with pytest.raises(ValueError, match="no puede aprobarse"):
        await svc.aprobar_obra(
            FakeConn(), autorizacion_id, user_id, None, "USER",
            lock_version_esperado=0,
        )


@pytest.mark.asyncio
async def test_aprobar_obra_falla_sin_lock_version():
    user_id = uuid4()
    bom_id, autorizacion_id = uuid4(), uuid4()
    bom = _bom(bom_id, coordinador_obra=user_id)
    aut = _autorizacion(autorizacion_id, bom_id)
    svc, _ = _service(bom, aut)

    with pytest.raises(ValueError, match="recarga"):
        await svc.aprobar_obra(
            FakeConn(), autorizacion_id, user_id, None, "USER",
            lock_version_esperado=None,
        )


@pytest.mark.asyncio
async def test_aprobar_obra_falla_cas_lock_version_obsoleto():
    """El cliente llega con un lock_version desactualizado (ej. cargo la pagina
    antes de que otra sesion ya aprobara/rechazara) -- el CAS bajo FOR UPDATE
    debe rechazarlo aunque el resto de las validaciones pasen."""
    user_id = uuid4()
    bom_id, autorizacion_id = uuid4(), uuid4()
    bom = _bom(bom_id, coordinador_obra=user_id)
    aut = _autorizacion(autorizacion_id, bom_id)
    svc, db = _service(bom, aut)

    with pytest.raises(ValueError, match="ya cambio"):
        await svc.aprobar_obra(
            FakeConn(), autorizacion_id, user_id, None, "USER",
            lock_version_esperado=5,
        )
    assert db.autorizacion["estatus"] == "PENDIENTE"
    assert db.autorizacion["lock_version"] == 0
