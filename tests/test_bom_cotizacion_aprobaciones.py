"""
Tests unitarios de aprobaciones post-BOM de cotizaciones (Fase 1 del plan
_Planes_Activos/2026-06-29-aprobaciones-cotizaciones-post-bom.md): solicitar/aprobar/rechazar
en tb_bom_cotizacion_aprobaciones, auto-avance de Fase D via _avanzar_paso_finanzas()
y cancelacion en cascada con paso RECHAZO_COTIZACION.
"""

from datetime import timedelta
from uuid import uuid4

import pytest

from core.bom.service import BomService
from core.config_service import ConfigService
from core.timezone import today_mx


@pytest.fixture(autouse=True)
def _config_sin_db(monkeypatch):
    """_alerta_variacion_costo() (gate de vigencia) lee el umbral via
    ConfigService.get_global_config, que golpea BD si no hay cache -- FakeConn
    de este archivo no implementa fetchrow. Los tests aqui no ejercen ese
    ajuste de configuracion, solo el default."""
    async def _get_global_config(cls, conn, clave, default, tipo=str):
        return default

    monkeypatch.setattr(
        ConfigService,
        "get_global_config",
        classmethod(_get_global_config),
    )


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
        "id_paquete": uuid4(),
        "estatus": estatus,
        "version": 1,
        "lock_version": 0,
        "es_cabeza_oficial": estatus == "APROBADO_FINAL",
        "estado_paquete": "ACTIVO",
    }


def _cotizacion(cotizacion_id, bom_id, **extra):
    data = {
        "id": cotizacion_id,
        "bom_id": bom_id,
        "estatus": "SELECCIONADA",
        "pdf_url": "https://sharepoint/cotizacion.pdf",
        "total": 1000.0,
        "moneda": "MXN",
        "proveedor_id": uuid4(),
        "nombre_proveedor": "Proveedor Uno",
        "lock_version": 0,
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
        "proyecto_id": uuid4(),
        "lock_version": 0,
    }
    data.update(extra)
    return data


class FakeAprobacionesDB:
    def __init__(self, bom, cotizacion, autorizacion=None, items=None):
        self.bom = bom
        self.paquete = {
            "id_paquete": bom["id_paquete"],
            "estado_paquete": "ACTIVO",
            "lock_version": 0,
        }
        self.aprobador_direccion_id = uuid4()
        self.titulares_por_suplente = {}
        self.cotizaciones = {cotizacion["id"]: dict(cotizacion)}
        self.autorizaciones = {}
        if autorizacion:
            self.autorizaciones[autorizacion["id"]] = dict(autorizacion)
        self.aprobaciones = {}
        self.items_cotizacion = list(items or [])
        self.items_estatus_updates = []
        self.eventos_outbox = []

    # ── BOM / cotizaciones ──
    async def get_bom_by_id(self, conn, id_bom):
        return dict(self.bom) if id_bom == self.bom["id_bom"] else None

    async def get_bom_for_update(self, conn, id_bom):
        return await self.get_bom_by_id(conn, id_bom)

    async def get_paquete_for_update(self, conn, id_paquete):
        return dict(self.paquete) if id_paquete == self.paquete["id_paquete"] else None

    async def get_cotizacion_by_id(self, conn, cotizacion_id):
        cot = self.cotizaciones.get(cotizacion_id)
        return dict(cot) if cot else None

    async def get_cotizacion_for_update(self, conn, cotizacion_id):
        return await self.get_cotizacion_by_id(conn, cotizacion_id)

    async def actualizar_estatus_cotizacion(
        self, conn, cotizacion_id, estatus, estatus_esperado, lock_version_esperado
    ):
        cotizacion = self.cotizaciones[cotizacion_id]
        if (
            cotizacion["estatus"] != estatus_esperado
            or cotizacion["lock_version"] != lock_version_esperado
        ):
            return None
        cotizacion["estatus"] = estatus
        cotizacion["lock_version"] += 1
        return dict(self.cotizaciones[cotizacion_id])

    async def get_items_cotizacion(self, conn, cotizacion_id):
        return [dict(i) for i in self.items_cotizacion]

    async def actualizar_estatus_compra_items(self, conn, item_ids, estatus):
        self.items_estatus_updates.append((list(item_ids), estatus))

    async def get_items_by_ids(self, conn, item_ids):
        return [
            {
                "id_item": item["bom_item_id"],
                "id_bom": self.bom["id_bom"],
                "descripcion": "Item",
                "cantidad": item.get("cantidad", 1),
                "cantidad_cubierta": 0,
                "precio_unitario": 100,
                "estatus_compra": "SIN_COTIZAR",
                "activo": True,
            }
            for item in self.items_cotizacion
            if item["bom_item_id"] in item_ids
        ]

    async def lock_items_context_by_ids(self, conn, item_ids):
        return await self.get_items_by_ids(conn, item_ids)

    async def get_items_con_cotizacion_activa(self, conn, item_ids, excluir_cotizacion_id=None):
        return []

    async def ajustar_cantidad_cubierta_items(self, conn, ajustes):
        """Fake liviano: este archivo prueba el flujo de aprobaciones/autorizacion
        (Fase D), no la aritmetica de cobertura parcial (ver test_bom_cotizacion_parcial.py)
        -- solo deriva SIN_COTIZAR/COTIZADO por el signo del delta, suficiente para
        que las aserciones existentes sobre items_estatus_updates sigan siendo validas."""
        resultados = []
        for item_id, delta in ajustes:
            estatus = "SIN_COTIZAR" if delta < 0 else "COTIZADO"
            self.items_estatus_updates.append(([item_id], estatus))
            resultados.append({
                "id_item": item_id, "estatus_compra": estatus,
                "cantidad_cubierta": max(delta, 0), "cantidad": 1,
            })
        return resultados

    async def upsert_item_ejecucion(self, conn, item_id, updated_by=None, **campos):
        return {"id_item": item_id, **campos}

    async def actualizar_estatus_ejecucion_batch(self, conn, filas):
        return [f[0] for f in filas]

    async def registrar_evento_outbox(self, conn, id_evento, tipo_evento, *args, **kwargs):
        self.eventos_outbox.append({
            "id_evento": id_evento,
            "tipo_evento": tipo_evento,
            **kwargs,
        })
        return None

    async def get_aprobador_final_id(self, conn):
        return self.aprobador_direccion_id

    async def get_titulares_que_representa(self, conn, suplente_id):
        return list(self.titulares_por_suplente.get(suplente_id, []))

    # ── Autorizaciones Fase D ──
    async def get_autorizacion_by_cotizacion(self, conn, cotizacion_id):
        for aut in self.autorizaciones.values():
            if aut["cotizacion_id"] == cotizacion_id:
                return dict(aut)
        return None

    async def get_autorizacion_by_id(self, conn, autorizacion_id):
        aut = self.autorizaciones.get(autorizacion_id)
        return dict(aut) if aut else None

    async def get_autorizacion_for_update(self, conn, autorizacion_id):
        return await self.get_autorizacion_by_id(conn, autorizacion_id)

    async def update_autorizacion_paso_direccion(
        self, conn, autorizacion_id, user_id, nota, lock_version_esperado
    ):
        aut = self.autorizaciones[autorizacion_id]
        if aut["lock_version"] != lock_version_esperado:
            return None
        aut.update({
            "estatus": "AUTORIZADO_DIRECCION",
            "aprobador_direccion_id": user_id,
            "nota_direccion": nota,
            "lock_version": lock_version_esperado + 1,
        })
        return dict(aut)

    async def update_autorizacion_paso_finanzas(
        self, conn, autorizacion_id, user_id, nota, lock_version_esperado
    ):
        aut = self.autorizaciones[autorizacion_id]
        if aut["lock_version"] != lock_version_esperado:
            return None
        aut.update({
            "estatus": "AUTORIZADO_FINANZAS",
            "aprobador_finanzas_id": user_id,
            "nota_finanzas": nota,
            "lock_version": lock_version_esperado + 1,
        })
        return dict(aut)

    async def rechazar_autorizacion_db(
        self, conn, autorizacion_id, user_id, motivo, paso,
        estatus_esperado, lock_version_esperado,
    ):
        aut = self.autorizaciones[autorizacion_id]
        if (
            aut["estatus"] != estatus_esperado
            or aut["lock_version"] != lock_version_esperado
        ):
            return None
        aut.update({
            "estatus": "RECHAZADO",
            "rechazado_en_paso": paso,
            "rechazado_por": user_id,
            "motivo_rechazo": motivo,
            "lock_version": lock_version_esperado + 1,
        })
        return dict(aut)

    async def get_tipo_cambio_vigente(self, conn):
        return None

    async def reabrir_autorizacion_db(
        self, conn, autorizacion_id, monto_total, moneda, tipo_cambio_snapshot, creado_por,
        lock_version_esperado,
    ):
        aut = self.autorizaciones.get(autorizacion_id)
        if (
            not aut
            or aut["estatus"] != "RECHAZADO"
            or aut["lock_version"] != lock_version_esperado
        ):
            return None
        aut.update({
            "estatus": "PENDIENTE",
            "monto_total": monto_total,
            "moneda": moneda,
            "creado_por": creado_por,
            "rechazado_en_paso": None,
            "rechazado_por": None,
            "motivo_rechazo": None,
            "lock_version": lock_version_esperado + 1,
        })
        return dict(aut)

    # ── Aprobaciones de cotizacion (post-BOM) ──
    async def crear_cotizacion_aprobacion(
        self, conn, cotizacion_id, bom_id, proyecto_id, solicitado_por,
        comentarios_solicitud=None,
        cotizacion_reemplazada_id=None, aprobacion_reemplazada_id=None,
    ):
        aprobacion = {
            "id": uuid4(),
            "cotizacion_id": cotizacion_id,
            "bom_id": bom_id,
            "proyecto_id": proyecto_id,
            "estatus": "PENDIENTE_DIRECCION",
            "solicitado_por": solicitado_por,
            "comentarios_solicitud": comentarios_solicitud,
            "cotizacion_reemplazada_id": cotizacion_reemplazada_id,
            "aprobacion_reemplazada_id": aprobacion_reemplazada_id,
            "lock_version": 0,
        }
        self.aprobaciones[aprobacion["id"]] = aprobacion
        return dict(aprobacion)

    async def marcar_cotizacion_aprobacion_reemplazada(
        self, conn, aprobacion_id, nuevo_estatus, motivo_reemplazo, lock_version_esperado,
    ):
        ap = self.aprobaciones.get(aprobacion_id)
        if (
            not ap
            or ap["estatus"] != "APROBADA"
            or ap["lock_version"] != lock_version_esperado
        ):
            return None
        ap.update({
            "estatus": nuevo_estatus,
            "motivo_reemplazo": motivo_reemplazo,
            "lock_version": lock_version_esperado + 1,
        })
        return dict(ap)

    async def get_cotizacion_aprobacion_activa(self, conn, cotizacion_id):
        for ap in self.aprobaciones.values():
            if ap["cotizacion_id"] == cotizacion_id and ap["estatus"] in (
                "PENDIENTE_DIRECCION", "APROBADA",
                "EN_STANDBY", "PENDIENTE_VIGENCIA_COMPRAS",
            ):
                return dict(ap)
        return None

    async def get_cotizacion_aprobacion_for_update(self, conn, aprobacion_id):
        aprobacion = self.aprobaciones.get(aprobacion_id)
        return dict(aprobacion) if aprobacion else None

    async def aprobar_cotizacion_aprobacion_db(
        self, conn, aprobacion_id, user_id, comentarios, lock_version_esperado
    ):
        ap = self.aprobaciones.get(aprobacion_id)
        if (
            not ap
            or ap["estatus"] != "PENDIENTE_DIRECCION"
            or ap["lock_version"] != lock_version_esperado
        ):
            return None
        ap.update({
            "estatus": "APROBADA",
            "aprobado_por": user_id,
            "comentarios_direccion": comentarios,
            "lock_version": lock_version_esperado + 1,
        })
        return dict(ap)

    async def rechazar_cotizacion_aprobacion_db(
        self, conn, aprobacion_id, user_id, motivo, lock_version_esperado
    ):
        ap = self.aprobaciones.get(aprobacion_id)
        if (
            not ap
            or ap["estatus"] != "PENDIENTE_DIRECCION"
            or ap["lock_version"] != lock_version_esperado
        ):
            return None
        ap.update({
            "estatus": "RECHAZADA",
            "rechazado_por": user_id,
            "motivo_rechazo": motivo,
            "lock_version": lock_version_esperado + 1,
        })
        return dict(ap)

    # ── Standby / vigencia (2026-08-28) ──
    async def poner_en_standby_db(
        self, conn, aprobacion_id, motivo_standby, fecha_recordatorio, lock_version_esperado,
    ):
        ap = self.aprobaciones.get(aprobacion_id)
        if (
            not ap
            or ap["estatus"] != "PENDIENTE_DIRECCION"
            or ap["lock_version"] != lock_version_esperado
        ):
            return None
        ap.update({
            "estatus": "EN_STANDBY",
            "motivo_standby": motivo_standby,
            "fecha_recordatorio": fecha_recordatorio,
            "recordatorio_enviado_at": None,
            "lock_version": lock_version_esperado + 1,
        })
        return dict(ap)

    async def reprogramar_standby_db(
        self, conn, aprobacion_id, motivo_standby, fecha_recordatorio, lock_version_esperado,
    ):
        ap = self.aprobaciones.get(aprobacion_id)
        if (
            not ap
            or ap["estatus"] != "EN_STANDBY"
            or ap["lock_version"] != lock_version_esperado
        ):
            return None
        ap.update({
            "motivo_standby": motivo_standby,
            "fecha_recordatorio": fecha_recordatorio,
            "recordatorio_enviado_at": None,
            "lock_version": lock_version_esperado + 1,
        })
        return dict(ap)

    async def confirmar_vigencia_reactiva_direccion_db(
        self, conn, aprobacion_id, lock_version_esperado,
    ):
        ap = self.aprobaciones.get(aprobacion_id)
        if (
            not ap
            or ap["estatus"] != "PENDIENTE_VIGENCIA_COMPRAS"
            or ap["lock_version"] != lock_version_esperado
        ):
            return None
        ap.update({
            "estatus": "PENDIENTE_DIRECCION",
            "motivo_standby": None,
            "fecha_recordatorio": None,
            "recordatorio_enviado_at": None,
            "lock_version": lock_version_esperado + 1,
        })
        return dict(ap)

    async def rechazar_cotizacion_aprobacion_vigencia_db(
        self, conn, aprobacion_id, user_id, motivo, lock_version_esperado,
    ):
        ap = self.aprobaciones.get(aprobacion_id)
        if (
            not ap
            or ap["estatus"] != "PENDIENTE_VIGENCIA_COMPRAS"
            or ap["lock_version"] != lock_version_esperado
        ):
            return None
        ap.update({
            "estatus": "RECHAZADA",
            "rechazado_por": user_id,
            "motivo_rechazo": motivo,
            "lock_version": lock_version_esperado + 1,
        })
        return dict(ap)

    async def actualizar_total_pdf_cotizacion_vigencia(
        self, conn, cotizacion_id, nuevo_total, nuevo_pdf_url, lock_version_esperado,
    ):
        cot = self.cotizaciones.get(cotizacion_id)
        if (
            not cot
            or cot["estatus"] != "SELECCIONADA"
            or cot["lock_version"] != lock_version_esperado
        ):
            return None
        cot.update({
            "total": nuevo_total,
            "pdf_url": nuevo_pdf_url or cot["pdf_url"],
            "lock_version": lock_version_esperado + 1,
        })
        return dict(cot)

    async def sincronizar_monto_autorizacion_db(
        self, conn, autorizacion_id, monto_total, lock_version_esperado,
    ):
        aut = self.autorizaciones.get(autorizacion_id)
        if not aut or aut["lock_version"] != lock_version_esperado:
            return None
        aut.update({
            "monto_total": monto_total,
            "lock_version": lock_version_esperado + 1,
        })
        return dict(aut)


def make_service(db):
    svc = BomService()
    svc.db = db
    return svc, db.eventos_outbox


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
    items = [{"bom_item_id": uuid4(), "cantidad": 1}, {"bom_item_id": uuid4(), "cantidad": 1}]
    db = FakeAprobacionesDB(bom, cotizacion, autorizacion, items)
    svc, notificaciones = make_service(db)
    return svc, db, notificaciones, cotizacion_id


async def _solicitar(svc, db, cotizacion_id, user_id=None, comentarios=None):
    autorizacion = await db.get_autorizacion_by_cotizacion(None, cotizacion_id)
    return await svc.solicitar_aprobacion_cotizacion(
        FakeConn(),
        cotizacion_id,
        user_id or uuid4(),
        comentarios,
        cotizacion_lock_version_esperado=db.cotizaciones[cotizacion_id]["lock_version"],
        autorizacion_lock_version_esperado=autorizacion["lock_version"],
    )


async def _aprobar(svc, db, cotizacion_id, user_id=None, comentarios=None, user_role="USER"):
    autorizacion = await db.get_autorizacion_by_cotizacion(None, cotizacion_id)
    aprobacion = await db.get_cotizacion_aprobacion_activa(None, cotizacion_id)
    return await svc.aprobar_cotizacion_direccion(
        FakeConn(),
        cotizacion_id,
        user_id or db.aprobador_direccion_id,
        user_role,
        None,
        comentarios,
        aprobacion_lock_version_esperado=aprobacion["lock_version"],
        autorizacion_lock_version_esperado=autorizacion["lock_version"],
    )


async def _rechazar(
    svc,
    db,
    cotizacion_id,
    motivo,
    user_id=None,
    user_role="USER",
):
    autorizacion = await db.get_autorizacion_by_cotizacion(None, cotizacion_id)
    aprobacion = await db.get_cotizacion_aprobacion_activa(None, cotizacion_id)
    return await svc.rechazar_cotizacion_direccion(
        FakeConn(),
        cotizacion_id,
        user_id or db.aprobador_direccion_id,
        motivo,
        user_role,
        None,
        aprobacion_lock_version_esperado=aprobacion["lock_version"],
        autorizacion_lock_version_esperado=autorizacion["lock_version"],
    )


async def _reemplazar(
    svc, db, cotizacion_id, motivo, user_id=None, user_role="USER", rol_org=None,
    es_override=False, cancelar_definitivo=False,
):
    autorizacion = await db.get_autorizacion_by_cotizacion(None, cotizacion_id)
    aprobacion = await db.get_cotizacion_aprobacion_activa(None, cotizacion_id)
    return await svc.reemplazar_cotizacion_proveedor(
        FakeConn(),
        cotizacion_id,
        motivo,
        user_id or uuid4(),
        user_role,
        rol_org,
        aprobacion_lock_version_esperado=aprobacion["lock_version"],
        autorizacion_lock_version_esperado=autorizacion["lock_version"],
        es_override=es_override,
        cancelar_definitivo=cancelar_definitivo,
    )


async def _llevar_a_aprobada(svc, db, cotizacion_id):
    """Recorre solicitar+aprobar para dejar la cotizacion con aprobacion APROBADA."""
    await _solicitar(svc, db, cotizacion_id)
    return await _aprobar(svc, db, cotizacion_id, db.aprobador_direccion_id)


def _nueva_cotizacion_lista_para_aprobar(db, bom_id):
    """Crea una cotizacion + autorizacion AUTORIZADO_OBRA lista para solicitar aprobacion."""
    nueva_cot_id = uuid4()
    db.cotizaciones[nueva_cot_id] = _cotizacion(nueva_cot_id, bom_id)
    nueva_aut = _autorizacion(nueva_cot_id, bom_id, "AUTORIZADO_OBRA")
    db.autorizaciones[nueva_aut["id"]] = nueva_aut
    return nueva_cot_id


# ─── SOLICITAR ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_solicitar_crea_aprobacion_pendiente():
    svc, db, _, cotizacion_id = build_escenario()
    aprobacion = await _solicitar(svc, db, cotizacion_id, comentarios="Urge para obra")
    assert aprobacion["estatus"] == "PENDIENTE_DIRECCION"
    assert aprobacion["cotizacion_id"] == cotizacion_id
    assert aprobacion["comentarios_solicitud"] == "Urge para obra"
    assert len(db.aprobaciones) == 1


@pytest.mark.asyncio
async def test_solicitar_falla_sin_pdf():
    svc, db, _, cotizacion_id = build_escenario(cotizacion_extra={"pdf_url": None})
    with pytest.raises(ValueError, match="PDF"):
        await _solicitar(svc, db, cotizacion_id)


@pytest.mark.asyncio
async def test_solicitar_falla_sin_total():
    svc, db, _, cotizacion_id = build_escenario(cotizacion_extra={"total": 0})
    with pytest.raises(ValueError, match="total"):
        await _solicitar(svc, db, cotizacion_id)


@pytest.mark.asyncio
async def test_solicitar_falla_si_no_seleccionada():
    svc, db, _, cotizacion_id = build_escenario(cotizacion_extra={"estatus": "RECIBIDA"})
    with pytest.raises(ValueError, match="seleccionada"):
        await _solicitar(svc, db, cotizacion_id)


@pytest.mark.asyncio
async def test_solicitar_falla_si_bom_no_aprobado_final():
    svc, db, _, cotizacion_id = build_escenario(bom_estatus="APROBADO_CONST")
    with pytest.raises(ValueError, match="APROBADO_FINAL"):
        await _solicitar(svc, db, cotizacion_id)


@pytest.mark.asyncio
async def test_solicitar_falla_si_fase_d_no_autorizada_por_obra():
    svc, db, _, cotizacion_id = build_escenario(aut_estatus="PENDIENTE")
    with pytest.raises(ValueError, match="Obra"):
        await _solicitar(svc, db, cotizacion_id)


@pytest.mark.asyncio
async def test_solicitar_falla_sin_autorizacion_fase_d():
    svc, _, _, cotizacion_id = build_escenario(con_autorizacion=False)
    with pytest.raises(ValueError, match="Obra"):
        await svc.solicitar_aprobacion_cotizacion(FakeConn(), cotizacion_id, uuid4())


@pytest.mark.asyncio
async def test_solicitar_falla_si_ya_hay_aprobacion_activa():
    svc, db, _, cotizacion_id = build_escenario()
    await _solicitar(svc, db, cotizacion_id)
    with pytest.raises(ValueError, match="ya tiene"):
        await _solicitar(svc, db, cotizacion_id)


@pytest.mark.asyncio
async def test_solicitar_falla_si_falta_un_lock_documental():
    svc, db, _, cotizacion_id = build_escenario()
    autorizacion = await db.get_autorizacion_by_cotizacion(None, cotizacion_id)

    with pytest.raises(ValueError, match="recarga"):
        await svc.solicitar_aprobacion_cotizacion(
            FakeConn(),
            cotizacion_id,
            uuid4(),
            cotizacion_lock_version_esperado=db.cotizaciones[cotizacion_id]["lock_version"],
            autorizacion_lock_version_esperado=None,
        )

    assert autorizacion["lock_version"] == 0
    assert db.aprobaciones == {}


# ─── APROBAR (Direccion) ─────────────────────────────────────

@pytest.mark.asyncio
async def test_aprobar_auto_avanza_fase_d_via_service():
    svc, db, eventos_outbox, cotizacion_id = build_escenario()
    await _solicitar(svc, db, cotizacion_id)

    director_id = db.aprobador_direccion_id
    updated = await _aprobar(svc, db, cotizacion_id, director_id, "Adelante")

    assert updated["estatus"] == "APROBADA"
    assert updated["aprobado_por"] == director_id
    aut = list(db.autorizaciones.values())[0]
    # Direccion autoavanza tambien el paso de Finanzas (decision 2026-08-19:
    # Finanzas ya no aprueba manualmente, solo paga) — ver
    # memory/bom_gate_finanzas_deshabilitado.md
    assert aut["estatus"] == "AUTORIZADO_FINANZAS"
    assert aut["aprobador_direccion_id"] == director_id
    assert aut["aprobador_finanzas_id"] == director_id
    assert any(
        evento["tipo_evento"] == "COTIZACION_APROBACION_APROBADA"
        for evento in eventos_outbox
    )
    assert any(
        evento["tipo_evento"] == "AUTORIZACION_FINANZAS"
        for evento in eventos_outbox
    )


@pytest.mark.asyncio
async def test_aprobar_admin_no_puede_aprobar_si_no_es_owner():
    svc, db, _, cotizacion_id = build_escenario()
    await _solicitar(svc, db, cotizacion_id)

    with pytest.raises(ValueError, match="aprobador de Direcci"):
        await _aprobar(svc, db, cotizacion_id, uuid4(), user_role="ADMIN")


@pytest.mark.asyncio
async def test_aprobar_suplente_activo_del_director_puede_aprobar():
    svc, db, _, cotizacion_id = build_escenario()
    await _solicitar(svc, db, cotizacion_id)
    suplente_id = uuid4()
    db.titulares_por_suplente[suplente_id] = [db.aprobador_direccion_id]

    updated = await _aprobar(svc, db, cotizacion_id, suplente_id)

    assert updated["estatus"] == "APROBADA"
    assert updated["aprobado_por"] == suplente_id


@pytest.mark.asyncio
async def test_aprobar_falla_si_no_es_director():
    svc, db, _, cotizacion_id = build_escenario()
    await _solicitar(svc, db, cotizacion_id)
    with pytest.raises(ValueError, match="Direcci"):
        await _aprobar(svc, db, cotizacion_id, uuid4())


@pytest.mark.asyncio
async def test_aprobar_falla_sin_aprobacion_pendiente():
    svc, db, _, cotizacion_id = build_escenario()
    with pytest.raises(ValueError, match="pendiente"):
        await svc.aprobar_cotizacion_direccion(
            FakeConn(), cotizacion_id, db.aprobador_direccion_id, "USER", None
        )


@pytest.mark.asyncio
async def test_aprobar_falla_si_falta_lock_de_aprobacion():
    svc, db, _, cotizacion_id = build_escenario()
    await _solicitar(svc, db, cotizacion_id)
    autorizacion = await db.get_autorizacion_by_cotizacion(None, cotizacion_id)

    with pytest.raises(ValueError, match="recarga"):
        await svc.aprobar_cotizacion_direccion(
            FakeConn(),
            cotizacion_id,
            db.aprobador_direccion_id,
            "USER",
            None,
            aprobacion_lock_version_esperado=None,
            autorizacion_lock_version_esperado=autorizacion["lock_version"],
        )


@pytest.mark.asyncio
async def test_aprobar_falla_si_fase_d_no_esta_en_obra():
    """Guard duro: si la Fase D cambio por la superficie standalone, no se puede aprobar."""
    svc, db, eventos_outbox, cotizacion_id = build_escenario()
    await _solicitar(svc, db, cotizacion_id)
    # La Fase D fue rechazada despues de solicitar la aprobacion documental
    aut = list(db.autorizaciones.values())[0]
    aut["estatus"] = "RECHAZADO"

    with pytest.raises(ValueError, match="Obra"):
        await _aprobar(svc, db, cotizacion_id)
    aprobacion = list(db.aprobaciones.values())[0]
    assert aprobacion["estatus"] == "PENDIENTE_DIRECCION"
    assert aut["estatus"] == "RECHAZADO"
    assert [e["tipo_evento"] for e in eventos_outbox] == [
        "COTIZACION_APROBACION_SOLICITADA"
    ]


# ─── RECHAZAR (Direccion) ────────────────────────────────────

@pytest.mark.asyncio
async def test_rechazar_cancela_fase_d_en_cascada():
    svc, db, eventos_outbox, cotizacion_id = build_escenario()
    await _solicitar(svc, db, cotizacion_id)

    director_id = db.aprobador_direccion_id
    updated = await _rechazar(
        svc, db, cotizacion_id, "Precio fuera de mercado", director_id
    )

    assert updated["estatus"] == "RECHAZADA"
    assert updated["motivo_rechazo"] == "Precio fuera de mercado"
    aut = list(db.autorizaciones.values())[0]
    assert aut["estatus"] == "RECHAZADO"
    assert aut["rechazado_en_paso"] == "RECHAZO_COTIZACION"
    assert db.cotizaciones[cotizacion_id]["estatus"] == "RECIBIDA"
    assert db.items_estatus_updates
    assert db.items_estatus_updates[-1][1] == "SIN_COTIZAR"
    assert any(
        evento["tipo_evento"] == "COTIZACION_APROBACION_RECHAZADA"
        for evento in eventos_outbox
    )


@pytest.mark.asyncio
async def test_rechazar_falla_sin_motivo():
    svc, db, _, cotizacion_id = build_escenario()
    await _solicitar(svc, db, cotizacion_id)
    with pytest.raises(ValueError, match="motivo"):
        await _rechazar(svc, db, cotizacion_id, "  ")


@pytest.mark.asyncio
async def test_rechazar_falla_si_no_es_director():
    svc, db, _, cotizacion_id = build_escenario()
    await _solicitar(svc, db, cotizacion_id)
    with pytest.raises(ValueError, match="Direcci"):
        await _rechazar(svc, db, cotizacion_id, "No procede", uuid4())


@pytest.mark.asyncio
async def test_rechazar_admin_no_puede_rechazar_si_no_es_owner():
    svc, db, _, cotizacion_id = build_escenario()
    await _solicitar(svc, db, cotizacion_id)

    with pytest.raises(ValueError, match="aprobador de Direcci"):
        await _rechazar(
            svc,
            db,
            cotizacion_id,
            "No procede",
            uuid4(),
            user_role="ADMIN",
        )


@pytest.mark.asyncio
async def test_rechazar_falla_si_falta_lock_de_autorizacion():
    svc, db, _, cotizacion_id = build_escenario()
    await _solicitar(svc, db, cotizacion_id)
    aprobacion = await db.get_cotizacion_aprobacion_activa(None, cotizacion_id)

    with pytest.raises(ValueError, match="recarga"):
        await svc.rechazar_cotizacion_direccion(
            FakeConn(),
            cotizacion_id,
            db.aprobador_direccion_id,
            "No procede",
            "USER",
            None,
            aprobacion_lock_version_esperado=aprobacion["lock_version"],
            autorizacion_lock_version_esperado=None,
        )


@pytest.mark.asyncio
async def test_rechazar_falla_si_fase_d_ya_avanzo():
    """Guard duro simetrico: si la Fase D ya avanzo, el rechazo documental se bloquea."""
    svc, db, _, cotizacion_id = build_escenario()
    await _solicitar(svc, db, cotizacion_id)
    aut = list(db.autorizaciones.values())[0]
    aut["estatus"] = "AUTORIZADO_FINANZAS"

    with pytest.raises(ValueError, match="Autorizaciones"):
        await _rechazar(svc, db, cotizacion_id, "No procede")
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
    await _solicitar(svc, db, cotizacion_id)
    await _rechazar(svc, db, cotizacion_id, "Faltaba contexto")
    aut = list(db.autorizaciones.values())[0]
    assert aut["estatus"] == "RECHAZADO"
    assert db.cotizaciones[cotizacion_id]["estatus"] == "RECIBIDA"

    # Compras re-selecciona la misma cotizacion (sin items para aislar la Fase D)
    db.items_cotizacion = []
    nuevo_user = uuid4()
    await svc.seleccionar_cotizacion(
        FakeConn(), cotizacion_id, nuevo_user,
        lock_version_esperado=db.cotizaciones[cotizacion_id]["lock_version"],
    )

    aut = list(db.autorizaciones.values())[0]
    assert aut["estatus"] == "PENDIENTE"
    assert aut["creado_por"] == nuevo_user
    assert aut["motivo_rechazo"] is None
    assert db.cotizaciones[cotizacion_id]["estatus"] == "SELECCIONADA"
    assert len(db.autorizaciones) == 1  # se reabre, no se duplica


@pytest.mark.asyncio
async def test_rechazada_permite_nueva_solicitud():
    svc, db, _, cotizacion_id = build_escenario()
    await _solicitar(svc, db, cotizacion_id)
    await _rechazar(svc, db, cotizacion_id, "Cambiar proveedor")
    # Tras el rechazo: Compras re-selecciona (la reapertura deja la Fase D en
    # PENDIENTE) y Obra vuelve a aprobar — simulado con los dos updates directos.
    db.cotizaciones[cotizacion_id]["estatus"] = "SELECCIONADA"
    aut = list(db.autorizaciones.values())[0]
    aut["estatus"] = "AUTORIZADO_OBRA"

    aprobacion = await _solicitar(svc, db, cotizacion_id)
    assert aprobacion["estatus"] == "PENDIENTE_DIRECCION"
    activas = [
        a for a in db.aprobaciones.values()
        if a["estatus"] in ("PENDIENTE_DIRECCION", "APROBADA")
    ]
    assert len(activas) == 1


# ─── REEMPLAZO POR PROVEEDOR INCUMPLIDO (## 7.4) ─────────────

@pytest.mark.asyncio
async def test_reemplazar_libera_items_y_cancela_fase_d_sin_tocar_cotizacion():
    svc, db, eventos_outbox, cotizacion_id = build_escenario()
    await _llevar_a_aprobada(svc, db, cotizacion_id)

    updated = await _reemplazar(svc, db, cotizacion_id, "El proveedor quebró")

    assert updated["estatus"] == "REEMPLAZADA"
    assert updated["motivo_reemplazo"] == "El proveedor quebró"
    aut = list(db.autorizaciones.values())[0]
    assert aut["estatus"] == "RECHAZADO"
    assert aut["rechazado_en_paso"] == "REEMPLAZO_PROVEEDOR"
    # La cotizacion original NO se toca (evidencia historica) — sigue SELECCIONADA,
    # a diferencia del rechazo (## 7.3) que la regresa a RECIBIDA.
    assert db.cotizaciones[cotizacion_id]["estatus"] == "SELECCIONADA"
    assert db.items_estatus_updates
    assert db.items_estatus_updates[-1][1] == "SIN_COTIZAR"
    assert any(
        evento["tipo_evento"] == "COTIZACION_APROBACION_REEMPLAZADA"
        for evento in eventos_outbox
    )


@pytest.mark.asyncio
async def test_reemplazar_cancelar_definitivo_usa_cancelada_proveedor():
    svc, db, _, cotizacion_id = build_escenario()
    await _llevar_a_aprobada(svc, db, cotizacion_id)

    updated = await _reemplazar(
        svc, db, cotizacion_id, "Se cancela el paquete", cancelar_definitivo=True
    )
    assert updated["estatus"] == "CANCELADA_PROVEEDOR"


@pytest.mark.asyncio
async def test_reemplazar_falla_sin_motivo():
    svc, db, _, cotizacion_id = build_escenario()
    await _llevar_a_aprobada(svc, db, cotizacion_id)
    with pytest.raises(ValueError, match="motivo"):
        await _reemplazar(svc, db, cotizacion_id, "   ")


@pytest.mark.asyncio
async def test_reemplazar_falla_si_no_esta_aprobada():
    svc, db, _, cotizacion_id = build_escenario()
    await _solicitar(svc, db, cotizacion_id)  # se queda PENDIENTE_DIRECCION
    with pytest.raises(ValueError, match="aprobada"):
        await _reemplazar(svc, db, cotizacion_id, "Motivo")


@pytest.mark.asyncio
async def test_reemplazar_bloqueado_si_autorizacion_pagada():
    svc, db, _, cotizacion_id = build_escenario()
    await _llevar_a_aprobada(svc, db, cotizacion_id)
    aut = list(db.autorizaciones.values())[0]
    aut["estatus"] = "PAGADO"

    with pytest.raises(ValueError, match="pago"):
        await _reemplazar(svc, db, cotizacion_id, "Motivo")


@pytest.mark.asyncio
async def test_reemplazar_bloqueado_si_item_facturado():
    svc, db, _, cotizacion_id = build_escenario()
    await _llevar_a_aprobada(svc, db, cotizacion_id)

    async def get_items_by_ids_facturado(conn, item_ids):
        return [
            {"id_item": iid, "id_bom": db.bom["id_bom"], "estatus_compra": "FACTURADO"}
            for iid in item_ids
        ]
    db.get_items_by_ids = get_items_by_ids_facturado

    with pytest.raises(ValueError, match="facturados"):
        await _reemplazar(svc, db, cotizacion_id, "Motivo")


@pytest.mark.asyncio
async def test_reemplazar_override_admin_permite_pese_a_bloqueo():
    svc, db, _, cotizacion_id = build_escenario()
    await _llevar_a_aprobada(svc, db, cotizacion_id)
    aut = list(db.autorizaciones.values())[0]
    aut["estatus"] = "PAGO_PARCIAL"

    updated = await _reemplazar(
        svc, db, cotizacion_id, "Excepcion autorizada",
        user_role="ADMIN", es_override=True,
    )
    assert updated["estatus"] == "REEMPLAZADA"


@pytest.mark.asyncio
async def test_reemplazar_override_rechazado_si_no_es_admin_director():
    svc, db, _, cotizacion_id = build_escenario()
    await _llevar_a_aprobada(svc, db, cotizacion_id)
    aut = list(db.autorizaciones.values())[0]
    aut["estatus"] = "PAGADO"

    with pytest.raises(ValueError, match="pago"):
        await _reemplazar(
            svc, db, cotizacion_id, "Motivo",
            user_role="USER", rol_org=None, es_override=True,
        )


@pytest.mark.asyncio
async def test_solicitar_liga_reemplazo_exitoso():
    svc, db, _, cotizacion_id = build_escenario()
    await _llevar_a_aprobada(svc, db, cotizacion_id)
    reemplazada = await _reemplazar(svc, db, cotizacion_id, "Proveedor incumplió")

    nueva_cot_id = _nueva_cotizacion_lista_para_aprobar(db, db.bom["id_bom"])

    nueva_aprobacion = await svc.solicitar_aprobacion_cotizacion(
        FakeConn(), nueva_cot_id, uuid4(),
        cotizacion_lock_version_esperado=0,
        autorizacion_lock_version_esperado=0,
        reemplaza_aprobacion_id=reemplazada["id"],
    )
    assert nueva_aprobacion["aprobacion_reemplazada_id"] == reemplazada["id"]
    assert nueva_aprobacion["cotizacion_reemplazada_id"] == cotizacion_id


@pytest.mark.asyncio
async def test_solicitar_rechaza_reemplazo_invalido_no_reemplazada():
    svc, db, _, cotizacion_id = build_escenario()
    await _llevar_a_aprobada(svc, db, cotizacion_id)
    aprobacion_aprobada = await db.get_cotizacion_aprobacion_activa(None, cotizacion_id)

    nueva_cot_id = _nueva_cotizacion_lista_para_aprobar(db, db.bom["id_bom"])

    with pytest.raises(ValueError, match="reemplazada"):
        await svc.solicitar_aprobacion_cotizacion(
            FakeConn(), nueva_cot_id, uuid4(),
            cotizacion_lock_version_esperado=0,
            autorizacion_lock_version_esperado=0,
            # Referencia una aprobacion que sigue APROBADA, no REEMPLAZADA
            reemplaza_aprobacion_id=aprobacion_aprobada["id"],
        )


# ─── TOCTOU: re-validacion post-lock en seleccionar_cotizacion ──

@pytest.mark.asyncio
async def test_seleccionar_revalida_items_tras_adquirir_locks():
    """Un item que pasa el pre-check pero llega COTIZADO al lock debe bloquear la seleccion."""
    svc, db, _, cotizacion_id = build_escenario(
        con_autorizacion=False, cotizacion_extra={"estatus": "RECIBIDA"}
    )

    async def lock_items_comprometidos(conn, item_ids):
        # Simula que otra cotizacion se quedo con los items entre el pre-check
        # (get_items_by_ids, estatus SIN_COTIZAR) y la adquisicion del lock.
        return [
            {
                "id_item": iid, "id_bom": db.bom["id_bom"],
                "estatus_compra": "COTIZADO", "descripcion": "Item",
            }
            for iid in item_ids
        ]
    db.lock_items_context_by_ids = lock_items_comprometidos

    with pytest.raises(ValueError, match="ya cotizados"):
        await svc.seleccionar_cotizacion(
            FakeConn(), cotizacion_id, uuid4(),
            lock_version_esperado=db.cotizaciones[cotizacion_id]["lock_version"],
        )


# ─── STANDBY DE DIRECCION Y VIGENCIA (COMPRAS) ──────────────
# Plan _Planes_Activos/PLAN_STANDBY_DIRECCION_VIGENCIA_COMPRAS_BOM.md

@pytest.mark.asyncio
async def test_standby_pone_cotizacion_en_espera():
    svc, db, _, cotizacion_id = build_escenario()
    aprobacion = await _solicitar(svc, db, cotizacion_id)
    fecha = today_mx() + timedelta(days=5)

    resultado = await svc.standby_cotizacion_direccion(
        FakeConn(), cotizacion_id, db.aprobador_direccion_id,
        "Esperando confirmación del cliente", fecha,
        aprobacion_lock_version_esperado=aprobacion["lock_version"],
    )

    assert resultado["estatus"] == "EN_STANDBY"
    assert resultado["motivo_standby"] == "Esperando confirmación del cliente"
    assert resultado["fecha_recordatorio"] == fecha
    autorizacion = await db.get_autorizacion_by_cotizacion(None, cotizacion_id)
    assert autorizacion["estatus"] == "AUTORIZADO_OBRA"


@pytest.mark.asyncio
async def test_standby_falla_sin_motivo():
    svc, db, _, cotizacion_id = build_escenario()
    aprobacion = await _solicitar(svc, db, cotizacion_id)

    with pytest.raises(ValueError, match="motivo"):
        await svc.standby_cotizacion_direccion(
            FakeConn(), cotizacion_id, db.aprobador_direccion_id,
            "   ", today_mx() + timedelta(days=1),
            aprobacion_lock_version_esperado=aprobacion["lock_version"],
        )


@pytest.mark.asyncio
async def test_standby_falla_fecha_en_pasado():
    svc, db, _, cotizacion_id = build_escenario()
    aprobacion = await _solicitar(svc, db, cotizacion_id)

    with pytest.raises(ValueError, match="pasado"):
        await svc.standby_cotizacion_direccion(
            FakeConn(), cotizacion_id, db.aprobador_direccion_id,
            "Motivo valido", today_mx() - timedelta(days=1),
            aprobacion_lock_version_esperado=aprobacion["lock_version"],
        )


@pytest.mark.asyncio
async def test_standby_falla_si_no_es_aprobador_direccion():
    svc, db, _, cotizacion_id = build_escenario()
    aprobacion = await _solicitar(svc, db, cotizacion_id)

    with pytest.raises(ValueError, match="Dirección"):
        await svc.standby_cotizacion_direccion(
            FakeConn(), cotizacion_id, uuid4(),
            "Motivo valido", today_mx() + timedelta(days=1),
            aprobacion_lock_version_esperado=aprobacion["lock_version"],
        )


@pytest.mark.asyncio
async def test_reprogramar_standby_actualiza_motivo_y_fecha():
    svc, db, _, cotizacion_id = build_escenario()
    aprobacion = await _solicitar(svc, db, cotizacion_id)
    en_standby = await svc.standby_cotizacion_direccion(
        FakeConn(), cotizacion_id, db.aprobador_direccion_id,
        "Motivo original", today_mx() + timedelta(days=3),
        aprobacion_lock_version_esperado=aprobacion["lock_version"],
    )

    nueva_fecha = today_mx() + timedelta(days=10)
    resultado = await svc.reprogramar_standby_direccion(
        FakeConn(), cotizacion_id, db.aprobador_direccion_id,
        "Motivo actualizado", nueva_fecha,
        aprobacion_lock_version_esperado=en_standby["lock_version"],
    )

    assert resultado["estatus"] == "EN_STANDBY"
    assert resultado["motivo_standby"] == "Motivo actualizado"
    assert resultado["fecha_recordatorio"] == nueva_fecha


@pytest.mark.asyncio
async def test_reprogramar_standby_falla_si_no_esta_en_standby():
    svc, db, _, cotizacion_id = build_escenario()
    aprobacion = await _solicitar(svc, db, cotizacion_id)

    with pytest.raises(ValueError, match="standby"):
        await svc.reprogramar_standby_direccion(
            FakeConn(), cotizacion_id, db.aprobador_direccion_id,
            "Motivo", today_mx() + timedelta(days=1),
            aprobacion_lock_version_esperado=aprobacion["lock_version"],
        )


@pytest.mark.asyncio
async def test_solicitar_no_vigente_rechaza_autorizacion_sin_crear_aprobacion():
    """Punto A, camino 'no vigente': no debe quedar ninguna aprobacion creada, y
    la autorizacion Fase D debe quedar RECHAZADO (no huerfana en AUTORIZADO_OBRA,
    Gap #4)."""
    svc, db, _, cotizacion_id = build_escenario()
    autorizacion = await db.get_autorizacion_by_cotizacion(None, cotizacion_id)

    resultado = await svc.solicitar_aprobacion_cotizacion(
        FakeConn(), cotizacion_id, uuid4(),
        cotizacion_lock_version_esperado=db.cotizaciones[cotizacion_id]["lock_version"],
        autorizacion_lock_version_esperado=autorizacion["lock_version"],
        vigente=False, motivo_no_vigente="El proveedor subió el precio",
    )

    assert resultado["estatus"] == "RECHAZADO"
    assert resultado["rechazado_en_paso"] == "RECHAZO_VIGENCIA"
    assert db.aprobaciones == {}
    autorizacion_final = await db.get_autorizacion_by_cotizacion(None, cotizacion_id)
    assert autorizacion_final["estatus"] == "RECHAZADO"


@pytest.mark.asyncio
async def test_solicitar_no_vigente_falla_sin_motivo():
    svc, db, _, cotizacion_id = build_escenario()
    autorizacion = await db.get_autorizacion_by_cotizacion(None, cotizacion_id)

    with pytest.raises(ValueError, match="motivo"):
        await svc.solicitar_aprobacion_cotizacion(
            FakeConn(), cotizacion_id, uuid4(),
            cotizacion_lock_version_esperado=db.cotizaciones[cotizacion_id]["lock_version"],
            autorizacion_lock_version_esperado=autorizacion["lock_version"],
            vigente=False,
        )


async def _llevar_a_pendiente_vigencia(svc, db, cotizacion_id):
    """Solicitar + standby + reactivar (simulando al worker) para dejar la
    aprobacion en PENDIENTE_VIGENCIA_COMPRAS."""
    aprobacion = await _solicitar(svc, db, cotizacion_id)
    en_standby = await svc.standby_cotizacion_direccion(
        FakeConn(), cotizacion_id, db.aprobador_direccion_id,
        "Esperando", today_mx() + timedelta(days=1),
        aprobacion_lock_version_esperado=aprobacion["lock_version"],
    )
    ap = db.aprobaciones[en_standby["id"]]
    ap["estatus"] = "PENDIENTE_VIGENCIA_COMPRAS"
    ap["lock_version"] += 1
    return dict(ap)


@pytest.mark.asyncio
async def test_confirmar_vigencia_vigente_regresa_a_pendiente_direccion():
    svc, db, _, cotizacion_id = build_escenario()
    reactivada = await _llevar_a_pendiente_vigencia(svc, db, cotizacion_id)
    autorizacion = await db.get_autorizacion_by_cotizacion(None, cotizacion_id)
    cotizacion = db.cotizaciones[cotizacion_id]

    resultado = await svc.confirmar_vigencia_reactivacion(
        FakeConn(), cotizacion_id, uuid4(), vigente=True,
        aprobacion_lock_version_esperado=reactivada["lock_version"],
        autorizacion_lock_version_esperado=autorizacion["lock_version"],
        cotizacion_lock_version_esperado=cotizacion["lock_version"],
    )

    assert resultado["estatus"] == "PENDIENTE_DIRECCION"
    assert resultado["motivo_standby"] is None
    autorizacion_final = await db.get_autorizacion_by_cotizacion(None, cotizacion_id)
    assert autorizacion_final["estatus"] == "AUTORIZADO_OBRA"


@pytest.mark.asyncio
async def test_confirmar_vigencia_no_vigente_rechaza_aprobacion_y_autorizacion():
    """Punto B, camino 'no vigente': la aprobacion queda RECHAZADA y la
    autorizacion Fase D queda RECHAZADO (no huerfana en AUTORIZADO_OBRA)."""
    svc, db, _, cotizacion_id = build_escenario()
    reactivada = await _llevar_a_pendiente_vigencia(svc, db, cotizacion_id)
    autorizacion = await db.get_autorizacion_by_cotizacion(None, cotizacion_id)
    cotizacion = db.cotizaciones[cotizacion_id]

    resultado = await svc.confirmar_vigencia_reactivacion(
        FakeConn(), cotizacion_id, uuid4(), vigente=False,
        motivo="El proveedor ya no puede cumplir",
        aprobacion_lock_version_esperado=reactivada["lock_version"],
        autorizacion_lock_version_esperado=autorizacion["lock_version"],
        cotizacion_lock_version_esperado=cotizacion["lock_version"],
    )

    assert resultado["estatus"] == "RECHAZADA"
    autorizacion_final = await db.get_autorizacion_by_cotizacion(None, cotizacion_id)
    assert autorizacion_final["estatus"] == "RECHAZADO"
    assert autorizacion_final["rechazado_en_paso"] == "RECHAZO_VIGENCIA"


@pytest.mark.asyncio
async def test_confirmar_vigencia_bloqueado_por_pago():
    """Gap #10: replica bajo lock el guard bloqueado_por_pago -- simula la
    carrera donde el pago se registra justo entre la pre-lectura (AUTORIZADO_OBRA,
    pasa el guard de entrada) y la relectura bajo FOR UPDATE (ya PAGADO). Sin este
    guard bajo lock, "por construccion" ya no alcanza para bloquear la carrera."""
    svc, db, _, cotizacion_id = build_escenario()
    reactivada = await _llevar_a_pendiente_vigencia(svc, db, cotizacion_id)
    autorizacion = await db.get_autorizacion_by_cotizacion(None, cotizacion_id)
    cotizacion = db.cotizaciones[cotizacion_id]

    original_for_update = db.get_autorizacion_for_update

    async def get_autorizacion_for_update_pagada(conn, autorizacion_id):
        db.autorizaciones[autorizacion_id]["estatus"] = "PAGADO"
        return await original_for_update(conn, autorizacion_id)
    db.get_autorizacion_for_update = get_autorizacion_for_update_pagada

    with pytest.raises(ValueError, match="pago"):
        await svc.confirmar_vigencia_reactivacion(
            FakeConn(), cotizacion_id, uuid4(), vigente=True,
            aprobacion_lock_version_esperado=reactivada["lock_version"],
            autorizacion_lock_version_esperado=autorizacion["lock_version"],
            cotizacion_lock_version_esperado=cotizacion["lock_version"],
        )


@pytest.mark.asyncio
async def test_confirmar_vigencia_sincroniza_monto_autorizacion():
    """Gap #7: si se actualiza el total, tb_bom_autorizaciones.monto_total debe
    sincronizarse en la misma operacion (evita el RAISE EXCEPTION del trigger
    DEFERRED fn_bom_validar_documento_cotizacion en un UPDATE futuro)."""
    svc, db, _, cotizacion_id = build_escenario()
    reactivada = await _llevar_a_pendiente_vigencia(svc, db, cotizacion_id)
    autorizacion = await db.get_autorizacion_by_cotizacion(None, cotizacion_id)
    cotizacion = db.cotizaciones[cotizacion_id]

    await svc.confirmar_vigencia_reactivacion(
        FakeConn(), cotizacion_id, uuid4(), vigente=True,
        nuevo_total=1500.0,
        aprobacion_lock_version_esperado=reactivada["lock_version"],
        autorizacion_lock_version_esperado=autorizacion["lock_version"],
        cotizacion_lock_version_esperado=cotizacion["lock_version"],
    )

    assert db.cotizaciones[cotizacion_id]["total"] == 1500.0
    assert db.autorizaciones[autorizacion["id"]]["monto_total"] == 1500.0
