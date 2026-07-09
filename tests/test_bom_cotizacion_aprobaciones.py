"""
Tests unitarios de aprobaciones post-BOM de cotizaciones (Fase 1 del plan
_Planes_Activos/2026-06-29-aprobaciones-cotizaciones-post-bom.md): solicitar/aprobar/rechazar
en tb_bom_cotizacion_aprobaciones, auto-avance de Fase D via aprobar_direccion()
y cancelacion en cascada con paso RECHAZO_COTIZACION.
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


def _bom(bom_id, estatus="APROBADO_FINAL"):
    return {
        "id_bom": bom_id,
        "id_proyecto": uuid4(),
        "estatus": estatus,
        "version": 1,
    }


def _cotizacion(cotizacion_id, bom_id, **extra):
    data = {
        "id": cotizacion_id,
        "bom_id": bom_id,
        "estatus": "SELECCIONADA",
        "es_rfq": False,
        "pdf_url": "https://sharepoint/cotizacion.pdf",
        "total": 1000.0,
        "moneda": "MXN",
        "proveedor_id": uuid4(),
        "nombre_proveedor": "Proveedor Uno",
    }
    data.update(extra)
    return data


def _autorizacion(cotizacion_id, bom_id, estatus="AUTORIZADO_OBRA", **extra):
    data = {
        "id": uuid4(),
        "cotizacion_id": cotizacion_id,
        "bom_id": bom_id,
        "estatus": estatus,
        "creado_por": uuid4(),
    }
    data.update(extra)
    return data


class FakeAprobacionesDB:
    def __init__(self, bom, cotizacion, autorizacion=None, items=None):
        self.bom = bom
        self.cotizaciones = {cotizacion["id"]: dict(cotizacion)}
        self.autorizaciones = {}
        if autorizacion:
            self.autorizaciones[autorizacion["id"]] = dict(autorizacion)
        self.aprobaciones = {}
        self.items_cotizacion = list(items or [])
        self.items_estatus_updates = []

    # ── BOM / cotizaciones ──
    async def get_bom_by_id(self, conn, id_bom):
        return dict(self.bom) if id_bom == self.bom["id_bom"] else None

    async def get_cotizacion_by_id(self, conn, cotizacion_id):
        cot = self.cotizaciones.get(cotizacion_id)
        return dict(cot) if cot else None

    async def actualizar_estatus_cotizacion(self, conn, cotizacion_id, estatus):
        self.cotizaciones[cotizacion_id]["estatus"] = estatus
        return dict(self.cotizaciones[cotizacion_id])

    async def get_items_cotizacion(self, conn, cotizacion_id):
        return [dict(i) for i in self.items_cotizacion]

    async def actualizar_estatus_compra_items(self, conn, item_ids, estatus):
        self.items_estatus_updates.append((list(item_ids), estatus))

    # ── Autorizaciones Fase D ──
    async def get_autorizacion_by_cotizacion(self, conn, cotizacion_id):
        for aut in self.autorizaciones.values():
            if aut["cotizacion_id"] == cotizacion_id:
                return dict(aut)
        return None

    async def get_autorizacion_by_id(self, conn, autorizacion_id):
        aut = self.autorizaciones.get(autorizacion_id)
        return dict(aut) if aut else None

    async def update_autorizacion_paso_direccion(self, conn, autorizacion_id, user_id, nota):
        aut = self.autorizaciones[autorizacion_id]
        aut.update({
            "estatus": "AUTORIZADO_DIRECCION",
            "aprobador_direccion_id": user_id,
            "nota_direccion": nota,
        })
        return dict(aut)

    async def rechazar_autorizacion_db(self, conn, autorizacion_id, user_id, motivo, paso):
        aut = self.autorizaciones[autorizacion_id]
        aut.update({
            "estatus": "RECHAZADO",
            "rechazado_en_paso": paso,
            "rechazado_por": user_id,
            "motivo_rechazo": motivo,
        })
        return dict(aut)

    async def get_tipo_cambio_vigente(self, conn):
        return None

    async def reabrir_autorizacion_db(
        self, conn, autorizacion_id, monto_total, moneda, tipo_cambio_snapshot, creado_por,
    ):
        aut = self.autorizaciones.get(autorizacion_id)
        if not aut or aut["estatus"] != "RECHAZADO":
            return None
        aut.update({
            "estatus": "PENDIENTE",
            "monto_total": monto_total,
            "moneda": moneda,
            "creado_por": creado_por,
            "rechazado_en_paso": None,
            "rechazado_por": None,
            "motivo_rechazo": None,
        })
        return dict(aut)

    # ── Aprobaciones de cotizacion (post-BOM) ──
    async def crear_cotizacion_aprobacion(
        self, conn, cotizacion_id, bom_id, proyecto_id, solicitado_por,
        comentarios_solicitud=None,
    ):
        aprobacion = {
            "id": uuid4(),
            "cotizacion_id": cotizacion_id,
            "bom_id": bom_id,
            "proyecto_id": proyecto_id,
            "estatus": "PENDIENTE_DIRECCION",
            "solicitado_por": solicitado_por,
            "comentarios_solicitud": comentarios_solicitud,
        }
        self.aprobaciones[aprobacion["id"]] = aprobacion
        return dict(aprobacion)

    async def get_cotizacion_aprobacion_activa(self, conn, cotizacion_id):
        for ap in self.aprobaciones.values():
            if ap["cotizacion_id"] == cotizacion_id and ap["estatus"] in (
                "PENDIENTE_DIRECCION", "APROBADA",
            ):
                return dict(ap)
        return None

    async def aprobar_cotizacion_aprobacion_db(self, conn, aprobacion_id, user_id, comentarios):
        ap = self.aprobaciones.get(aprobacion_id)
        if not ap or ap["estatus"] != "PENDIENTE_DIRECCION":
            return None
        ap.update({
            "estatus": "APROBADA",
            "aprobado_por": user_id,
            "comentarios_direccion": comentarios,
        })
        return dict(ap)

    async def rechazar_cotizacion_aprobacion_db(self, conn, aprobacion_id, user_id, motivo):
        ap = self.aprobaciones.get(aprobacion_id)
        if not ap or ap["estatus"] != "PENDIENTE_DIRECCION":
            return None
        ap.update({
            "estatus": "RECHAZADA",
            "rechazado_por": user_id,
            "motivo_rechazo": motivo,
        })
        return dict(ap)


def make_service(db):
    svc = BomService()
    svc.db = db
    notificaciones = []

    async def _fake_notify(conn, autorizacion, bom, to_user_id, evento, por_user_id=None, nota=None):
        notificaciones.append({"evento": evento, "to_user_id": to_user_id})

    svc._notify_autorizacion = _fake_notify
    return svc, notificaciones


def build_escenario(
    bom_estatus="APROBADO_FINAL",
    cotizacion_extra=None,
    aut_estatus="AUTORIZADO_OBRA",
    con_autorizacion=True,
):
    bom_id = uuid4()
    cotizacion_id = uuid4()
    bom = _bom(bom_id, bom_estatus)
    cotizacion = _cotizacion(cotizacion_id, bom_id, **(cotizacion_extra or {}))
    autorizacion = (
        _autorizacion(cotizacion_id, bom_id, aut_estatus) if con_autorizacion else None
    )
    items = [{"bom_item_id": uuid4()}, {"bom_item_id": uuid4()}]
    db = FakeAprobacionesDB(bom, cotizacion, autorizacion, items)
    svc, notificaciones = make_service(db)
    return svc, db, notificaciones, cotizacion_id


# ─── SOLICITAR ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_solicitar_crea_aprobacion_pendiente():
    svc, db, _, cotizacion_id = build_escenario()
    aprobacion = await svc.solicitar_aprobacion_cotizacion(
        FakeConn(), cotizacion_id, uuid4(), "Urge para obra"
    )
    assert aprobacion["estatus"] == "PENDIENTE_DIRECCION"
    assert aprobacion["cotizacion_id"] == cotizacion_id
    assert aprobacion["comentarios_solicitud"] == "Urge para obra"
    assert len(db.aprobaciones) == 1


@pytest.mark.asyncio
async def test_solicitar_falla_si_es_rfq():
    svc, _, _, cotizacion_id = build_escenario(cotizacion_extra={"es_rfq": True})
    with pytest.raises(ValueError, match="RFQ"):
        await svc.solicitar_aprobacion_cotizacion(FakeConn(), cotizacion_id, uuid4())


@pytest.mark.asyncio
async def test_solicitar_falla_sin_pdf():
    svc, _, _, cotizacion_id = build_escenario(cotizacion_extra={"pdf_url": None})
    with pytest.raises(ValueError, match="PDF"):
        await svc.solicitar_aprobacion_cotizacion(FakeConn(), cotizacion_id, uuid4())


@pytest.mark.asyncio
async def test_solicitar_falla_sin_total():
    svc, _, _, cotizacion_id = build_escenario(cotizacion_extra={"total": 0})
    with pytest.raises(ValueError, match="total"):
        await svc.solicitar_aprobacion_cotizacion(FakeConn(), cotizacion_id, uuid4())


@pytest.mark.asyncio
async def test_solicitar_falla_si_no_seleccionada():
    svc, _, _, cotizacion_id = build_escenario(cotizacion_extra={"estatus": "RECIBIDA"})
    with pytest.raises(ValueError, match="seleccionada"):
        await svc.solicitar_aprobacion_cotizacion(FakeConn(), cotizacion_id, uuid4())


@pytest.mark.asyncio
async def test_solicitar_falla_si_bom_no_aprobado_final():
    svc, _, _, cotizacion_id = build_escenario(bom_estatus="APROBADO_CONST")
    with pytest.raises(ValueError, match="APROBADO_FINAL"):
        await svc.solicitar_aprobacion_cotizacion(FakeConn(), cotizacion_id, uuid4())


@pytest.mark.asyncio
async def test_solicitar_falla_si_fase_d_no_autorizada_por_obra():
    svc, _, _, cotizacion_id = build_escenario(aut_estatus="PENDIENTE")
    with pytest.raises(ValueError, match="Obra"):
        await svc.solicitar_aprobacion_cotizacion(FakeConn(), cotizacion_id, uuid4())


@pytest.mark.asyncio
async def test_solicitar_falla_sin_autorizacion_fase_d():
    svc, _, _, cotizacion_id = build_escenario(con_autorizacion=False)
    with pytest.raises(ValueError, match="Obra"):
        await svc.solicitar_aprobacion_cotizacion(FakeConn(), cotizacion_id, uuid4())


@pytest.mark.asyncio
async def test_solicitar_falla_si_ya_hay_aprobacion_activa():
    svc, _, _, cotizacion_id = build_escenario()
    await svc.solicitar_aprobacion_cotizacion(FakeConn(), cotizacion_id, uuid4())
    with pytest.raises(ValueError, match="ya tiene"):
        await svc.solicitar_aprobacion_cotizacion(FakeConn(), cotizacion_id, uuid4())


# ─── APROBAR (Direccion) ─────────────────────────────────────

@pytest.mark.asyncio
async def test_aprobar_auto_avanza_fase_d_via_service():
    svc, db, notificaciones, cotizacion_id = build_escenario()
    await svc.solicitar_aprobacion_cotizacion(FakeConn(), cotizacion_id, uuid4())

    director_id = uuid4()
    updated = await svc.aprobar_cotizacion_direccion(
        FakeConn(), cotizacion_id, director_id, "USER", "director", "Adelante"
    )

    assert updated["estatus"] == "APROBADA"
    assert updated["aprobado_por"] == director_id
    aut = list(db.autorizaciones.values())[0]
    assert aut["estatus"] == "AUTORIZADO_DIRECCION"
    assert aut["aprobador_direccion_id"] == director_id
    # El auto-avance pasa por aprobar_direccion() y conserva la notificacion a Finanzas
    assert any(n["evento"] == "PENDIENTE_FINANZAS" for n in notificaciones)


@pytest.mark.asyncio
async def test_aprobar_admin_puede_aprobar():
    svc, _, _, cotizacion_id = build_escenario()
    await svc.solicitar_aprobacion_cotizacion(FakeConn(), cotizacion_id, uuid4())
    updated = await svc.aprobar_cotizacion_direccion(
        FakeConn(), cotizacion_id, uuid4(), "ADMIN", None
    )
    assert updated["estatus"] == "APROBADA"


@pytest.mark.asyncio
async def test_aprobar_falla_si_no_es_director():
    svc, _, _, cotizacion_id = build_escenario()
    await svc.solicitar_aprobacion_cotizacion(FakeConn(), cotizacion_id, uuid4())
    with pytest.raises(ValueError, match="Director"):
        await svc.aprobar_cotizacion_direccion(
            FakeConn(), cotizacion_id, uuid4(), "USER", "gerente"
        )


@pytest.mark.asyncio
async def test_aprobar_falla_sin_aprobacion_pendiente():
    svc, _, _, cotizacion_id = build_escenario()
    with pytest.raises(ValueError, match="pendiente"):
        await svc.aprobar_cotizacion_direccion(
            FakeConn(), cotizacion_id, uuid4(), "ADMIN", None
        )


@pytest.mark.asyncio
async def test_aprobar_falla_si_fase_d_no_esta_en_obra():
    """Guard duro: si la Fase D cambio por la superficie standalone, no se puede aprobar."""
    svc, db, notificaciones, cotizacion_id = build_escenario()
    await svc.solicitar_aprobacion_cotizacion(FakeConn(), cotizacion_id, uuid4())
    # La Fase D fue rechazada despues de solicitar la aprobacion documental
    aut = list(db.autorizaciones.values())[0]
    aut["estatus"] = "RECHAZADO"

    with pytest.raises(ValueError, match="Obra"):
        await svc.aprobar_cotizacion_direccion(
            FakeConn(), cotizacion_id, uuid4(), "ADMIN", None
        )
    aprobacion = list(db.aprobaciones.values())[0]
    assert aprobacion["estatus"] == "PENDIENTE_DIRECCION"
    assert aut["estatus"] == "RECHAZADO"
    assert notificaciones == []


# ─── RECHAZAR (Direccion) ────────────────────────────────────

@pytest.mark.asyncio
async def test_rechazar_cancela_fase_d_en_cascada():
    svc, db, notificaciones, cotizacion_id = build_escenario()
    await svc.solicitar_aprobacion_cotizacion(FakeConn(), cotizacion_id, uuid4())

    director_id = uuid4()
    updated = await svc.rechazar_cotizacion_direccion(
        FakeConn(), cotizacion_id, director_id, "Precio fuera de mercado", "USER", "director"
    )

    assert updated["estatus"] == "RECHAZADA"
    assert updated["motivo_rechazo"] == "Precio fuera de mercado"
    aut = list(db.autorizaciones.values())[0]
    assert aut["estatus"] == "RECHAZADO"
    assert aut["rechazado_en_paso"] == "RECHAZO_COTIZACION"
    assert db.cotizaciones[cotizacion_id]["estatus"] == "RECIBIDA"
    assert db.items_estatus_updates
    assert db.items_estatus_updates[-1][1] == "SIN_COTIZAR"
    # La cascada notifica al creador de la autorizacion (Compras), como el rechazo normal
    assert any(
        n["evento"] == "RECHAZADO" and n["to_user_id"] == aut["creado_por"]
        for n in notificaciones
    )


@pytest.mark.asyncio
async def test_rechazar_falla_sin_motivo():
    svc, _, _, cotizacion_id = build_escenario()
    await svc.solicitar_aprobacion_cotizacion(FakeConn(), cotizacion_id, uuid4())
    with pytest.raises(ValueError, match="motivo"):
        await svc.rechazar_cotizacion_direccion(
            FakeConn(), cotizacion_id, uuid4(), "  ", "USER", "director"
        )


@pytest.mark.asyncio
async def test_rechazar_falla_si_no_es_director():
    svc, _, _, cotizacion_id = build_escenario()
    await svc.solicitar_aprobacion_cotizacion(FakeConn(), cotizacion_id, uuid4())
    with pytest.raises(ValueError, match="Director"):
        await svc.rechazar_cotizacion_direccion(
            FakeConn(), cotizacion_id, uuid4(), "No procede", "USER", None
        )


@pytest.mark.asyncio
async def test_rechazar_falla_si_fase_d_ya_avanzo():
    """Guard duro simetrico: si la Fase D ya avanzo, el rechazo documental se bloquea."""
    svc, db, _, cotizacion_id = build_escenario()
    await svc.solicitar_aprobacion_cotizacion(FakeConn(), cotizacion_id, uuid4())
    aut = list(db.autorizaciones.values())[0]
    aut["estatus"] = "AUTORIZADO_FINANZAS"

    with pytest.raises(ValueError, match="Autorizaciones"):
        await svc.rechazar_cotizacion_direccion(
            FakeConn(), cotizacion_id, uuid4(), "No procede", "ADMIN", None
        )
    aprobacion = list(db.aprobaciones.values())[0]
    assert aprobacion["estatus"] == "PENDIENTE_DIRECCION"
    assert aut["estatus"] == "AUTORIZADO_FINANZAS"
    assert db.cotizaciones[cotizacion_id]["estatus"] == "SELECCIONADA"
    assert db.items_estatus_updates == []


# ─── REGLA DE UNA APROBACION ACTIVA ──────────────────────────

@pytest.mark.asyncio
async def test_reseleccion_reabre_autorizacion_rechazada():
    """Tras el rechazo de Direccion, re-seleccionar la misma cotizacion reabre la Fase D a PENDIENTE."""
    svc, db, _, cotizacion_id = build_escenario()
    await svc.solicitar_aprobacion_cotizacion(FakeConn(), cotizacion_id, uuid4())
    await svc.rechazar_cotizacion_direccion(
        FakeConn(), cotizacion_id, uuid4(), "Faltaba contexto", "ADMIN", None
    )
    aut = list(db.autorizaciones.values())[0]
    assert aut["estatus"] == "RECHAZADO"
    assert db.cotizaciones[cotizacion_id]["estatus"] == "RECIBIDA"

    # Compras re-selecciona la misma cotizacion (sin items para aislar la Fase D)
    db.items_cotizacion = []
    nuevo_user = uuid4()
    await svc.seleccionar_cotizacion(FakeConn(), cotizacion_id, nuevo_user)

    aut = list(db.autorizaciones.values())[0]
    assert aut["estatus"] == "PENDIENTE"
    assert aut["creado_por"] == nuevo_user
    assert aut["motivo_rechazo"] is None
    assert db.cotizaciones[cotizacion_id]["estatus"] == "SELECCIONADA"
    assert len(db.autorizaciones) == 1  # se reabre, no se duplica


@pytest.mark.asyncio
async def test_rechazada_permite_nueva_solicitud():
    svc, db, _, cotizacion_id = build_escenario()
    await svc.solicitar_aprobacion_cotizacion(FakeConn(), cotizacion_id, uuid4())
    await svc.rechazar_cotizacion_direccion(
        FakeConn(), cotizacion_id, uuid4(), "Cambiar proveedor", "ADMIN", None
    )
    # Tras el rechazo: Compras re-selecciona (la reapertura deja la Fase D en
    # PENDIENTE) y Obra vuelve a aprobar — simulado con los dos updates directos.
    db.cotizaciones[cotizacion_id]["estatus"] = "SELECCIONADA"
    aut = list(db.autorizaciones.values())[0]
    aut["estatus"] = "AUTORIZADO_OBRA"

    aprobacion = await svc.solicitar_aprobacion_cotizacion(FakeConn(), cotizacion_id, uuid4())
    assert aprobacion["estatus"] == "PENDIENTE_DIRECCION"
    activas = [
        a for a in db.aprobaciones.values()
        if a["estatus"] in ("PENDIENTE_DIRECCION", "APROBADA")
    ]
    assert len(activas) == 1
