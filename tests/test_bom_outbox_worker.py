"""Pruebas unitarias del consumidor durable y registro del outbox BOM.

Las pruebas con FakeConn de abajo verifican el SQL emitido y sus argumentos -- utiles para
no romper el contrato de columnas/orden de parametros, pero un FakeConn no puede demostrar
que FOR UPDATE SKIP LOCKED realmente evita que dos workers reclamen la misma entrega, ni que
un evento entregado deja una notificacion real en tb_notificaciones. Esas dos garantias se
prueban con Postgres real al final del archivo (real_conn / two_real_conns).
"""

import asyncio
from uuid import uuid4

import pytest

from core.bom import outbox_worker
from core.bom.db_service import BomDBService


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeConn:
    def __init__(self, *, fetch_rows=None, fetchval_result=None, fetchrow_result=None):
        self.fetch_rows = list(fetch_rows or [])
        self.fetchval_result = fetchval_result
        self.fetchrow_result = fetchrow_result
        self.executions = []
        self.fetches = []
        self.fetchvals = []
        self.fetchrows = []

    def transaction(self):
        return FakeTransaction()

    async def execute(self, query, *args):
        self.executions.append((query, args))
        return "UPDATE 1"

    async def fetch(self, query, *args):
        self.fetches.append((query, args))
        return self.fetch_rows

    async def fetchval(self, query, *args):
        self.fetchvals.append((query, args))
        return self.fetchval_result

    async def fetchrow(self, query, *args):
        self.fetchrows.append((query, args))
        return self.fetchrow_result


def _entrega(*, intentos=1, canal="INTERNA"):
    return {
        "id_entrega": uuid4(),
        "id_evento": uuid4(),
        "intentos": intentos,
        "canal": canal,
    }


@pytest.mark.asyncio
async def test_reclamar_lote_recupera_lease_y_usa_skip_locked():
    entrega = _entrega()
    conn = FakeConn(fetch_rows=[entrega])

    reclamadas = await outbox_worker._reclamar_lote(
        conn,
        "worker-a",
        limite=17,
        max_intentos=5,
        lease_segundos=240,
    )

    assert reclamadas == [entrega]
    recuperar_sql, recuperar_args = next(
        llamada for llamada in conn.fetches
        if "lease_hasta < NOW()" in llamada[0]
    )
    assert "lease_hasta < NOW()" in recuperar_sql
    assert "AGOTADO" in recuperar_sql
    assert recuperar_args == (5,)

    reclamar_sql, reclamar_args = next(
        llamada for llamada in conn.fetches
        if "FOR UPDATE SKIP LOCKED" in llamada[0]
    )
    assert "FOR UPDATE SKIP LOCKED" in reclamar_sql
    assert "intentos = entrega.intentos + 1" in reclamar_sql
    assert "lease_hasta = NOW()" in reclamar_sql
    assert reclamar_args == ("worker-a", 17, 5, 240)


@pytest.mark.asyncio
async def test_recuperar_leases_recalcula_padres_en_lote_serializado():
    evento_id = uuid4()
    conn = FakeConn(fetch_rows=[{"id_evento": evento_id}])

    await outbox_worker._recuperar_leases(conn, max_intentos=8)

    assert len(conn.executions) == 1
    recuperar_sql, recuperar_args = conn.fetches[0]
    assert "RETURNING id_evento" in recuperar_sql
    assert recuperar_args == (8,)
    bloqueo_sql, bloqueo_args = conn.fetches[1]
    assert "ORDER BY id_evento" in bloqueo_sql
    assert "FOR UPDATE" in bloqueo_sql
    assert bloqueo_args == ([evento_id],)
    padre_sql, padre_args = conn.executions[0]
    assert "UPDATE tb_bom_eventos_outbox evento" in padre_sql
    assert "FROM tb_bom_evento_entregas" in padre_sql
    assert padre_args == ([evento_id],)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("intentos", "max_intentos", "error", "estatus", "demora"),
    [
        (2, 5, "RuntimeError: fallo transitorio", "REINTENTO", 60),
        (5, 5, "RuntimeError: fallo definitivo", "AGOTADO", 0),
        (1, 5, None, "ENVIADO", 0),
    ],
)
async def test_finalizar_entrega_aplica_retry_exhaust_y_exito_con_cas(
    intentos, max_intentos, error, estatus, demora
):
    entrega = _entrega(intentos=intentos)
    conn = FakeConn(fetchval_result=entrega["id_entrega"])

    actualizada = await outbox_worker._finalizar_entrega(
        conn,
        entrega,
        "worker-a",
        error,
        max_intentos,
    )

    assert actualizada is True
    finalizar_sql, finalizar_args = conn.fetchvals[0]
    assert "estatus = 'PROCESANDO'" in finalizar_sql
    assert "worker_id = $2" in finalizar_sql
    assert "intentos = $3" in finalizar_sql
    assert "lease_hasta = NULL" in finalizar_sql
    assert finalizar_args == (
        entrega["id_entrega"],
        "worker-a",
        intentos,
        estatus,
        demora,
        error,
    )
    assert any("UPDATE tb_bom_eventos_outbox" in sql for sql, _ in conn.executions)


@pytest.mark.asyncio
async def test_finalizar_entrega_no_actualiza_evento_si_perdio_el_lease():
    entrega = _entrega(intentos=2)
    conn = FakeConn(fetchval_result=None)

    actualizada = await outbox_worker._finalizar_entrega(
        conn,
        entrega,
        "worker-viejo",
        None,
        max_intentos=5,
    )

    assert actualizada is False
    assert conn.executions == []


@pytest.mark.asyncio
async def test_procesar_lote_contabiliza_reintento_sin_detener_otras_entregas(monkeypatch):
    exitosa = _entrega(canal="INTERNA")
    fallida = _entrega(canal="NO_SOPORTADO")
    finalizaciones = []

    async def reclamar(*args, **kwargs):
        return [exitosa, fallida]

    async def entregar_interna(conn, entrega):
        return None

    async def finalizar(conn, entrega, worker_id, error, max_intentos):
        finalizaciones.append((entrega["id_entrega"], error))
        return True

    monkeypatch.setattr(outbox_worker, "_reclamar_lote", reclamar)
    monkeypatch.setattr(outbox_worker, "_entregar_interna", entregar_interna)
    monkeypatch.setattr(outbox_worker, "_finalizar_entrega", finalizar)
    conn = FakeConn()

    metricas = await outbox_worker.procesar_bom_outbox_lote(
        conn,
        worker_id="worker-a",
        max_intentos=5,
    )

    assert metricas == {
        "reclamadas": 2,
        "enviadas": 1,
        "reintentos": 1,
        "agotadas": 0,
    }
    assert finalizaciones[0] == (exitosa["id_entrega"], None)
    assert finalizaciones[1][0] == fallida["id_entrega"]
    assert finalizaciones[1][1].startswith("ValueError: Canal de outbox no soportado")


@pytest.mark.asyncio
async def test_reprogramar_agotada_reinicia_intentos_y_audita_replay():
    entrega_id = uuid4()
    evento_id = uuid4()
    actor_id = uuid4()
    conn = FakeConn(fetchrow_result={
        "id_entrega": entrega_id,
        "id_evento": evento_id,
        "estatus": "REINTENTO",
    })

    replay = await outbox_worker.reprogramar_entrega_agotada(
        conn,
        entrega_id,
        actor_id,
        "  Incidente confirmado  ",
    )

    assert replay["estatus"] == "REINTENTO"
    replay_sql, replay_args = conn.fetchrows[0]
    assert "intentos = 0" in replay_sql
    assert "replay_count = replay_count + 1" in replay_sql
    assert "estatus = 'AGOTADO'" in replay_sql
    assert replay_args == (entrega_id, actor_id, "Incidente confirmado")
    assert len(conn.executions) == 1
    bloqueo_sql, bloqueo_args = conn.fetches[0]
    assert "ORDER BY id_evento" in bloqueo_sql
    assert "FOR UPDATE" in bloqueo_sql
    assert bloqueo_args == ([evento_id],)
    padre_sql, padre_args = conn.executions[0]
    assert "UPDATE tb_bom_eventos_outbox evento" in padre_sql
    assert "FROM tb_bom_evento_entregas" in padre_sql
    assert padre_args == ([evento_id],)


@pytest.mark.asyncio
async def test_reprogramar_agotada_exige_motivo_y_estado_agotado():
    with pytest.raises(ValueError, match="motivo"):
        await outbox_worker.reprogramar_entrega_agotada(
            FakeConn(), uuid4(), uuid4(), "  "
        )

    with pytest.raises(ValueError, match="agotada"):
        await outbox_worker.reprogramar_entrega_agotada(
            FakeConn(fetchrow_result=None), uuid4(), uuid4(), "Reintentar"
        )


class FakeRegistroConn(FakeConn):
    def __init__(self, id_evento):
        super().__init__(fetchrow_result={"id_evento": id_evento})


@pytest.mark.asyncio
async def test_registrar_evento_conserva_idempotencia_y_payload_versionado():
    id_evento = uuid4()
    id_proyecto = uuid4()
    id_paquete = uuid4()
    conn = FakeRegistroConn(id_evento)

    evento = await BomDBService().registrar_evento_outbox(
        conn,
        "BOM:paquete:1:APROBACION_ING",
        "APROBACION_ING",
        id_proyecto,
        uuid4(),
        {"version": 1},
        id_paquete=id_paquete,
        id_bom=uuid4(),
    )

    assert evento["id_evento"] == id_evento
    evento_sql, evento_args = conn.fetchrows[0]
    assert "ON CONFLICT (clave_idempotencia)" in evento_sql
    assert "payload_version" in evento_sql
    assert evento_args[0] == "BOM:paquete:1:APROBACION_ING"
    assert '"payload_version": 1' in evento_args[8]
    assert f'"id_paquete": "{id_paquete}"' in evento_args[8]

    entregas_sql, entregas_args = conn.executions[0]
    assert "ON CONFLICT (id_evento, canal, destinatario_id) DO NOTHING" in entregas_sql
    assert entregas_args[0] == id_evento


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tipo_evento",
    ["APROBACION_ING", "COTIZACION_APROBACION_SOLICITADA"],
)
async def test_registrar_evento_resuelve_destinatarios_segun_tipo_evento(tipo_evento):
    conn = FakeRegistroConn(uuid4())

    await BomDBService().registrar_evento_outbox(
        conn,
        f"BOM:1:{tipo_evento}",
        tipo_evento,
        uuid4(),
        uuid4(),
        {"version": 1},
        id_paquete=uuid4(),
        id_bom=uuid4(),
    )

    entregas_sql, entregas_args = conn.executions[0]
    assert tipo_evento in entregas_args
    assert "$7" in entregas_sql
    assert "candidatos_paquete" in entregas_sql
    assert "UNNEST(ARRAY[" not in entregas_sql


# ─────────────────────────────────────────────────────────────────────────────
# Postgres real: SKIP LOCKED entre dos workers y entrega interna de punta a punta.
#
# IMPORTANTE: registrar_evento_outbox crea entregas de canal INTERNA y CORREO para cada
# destinatario real. _entregar_correo llama a Microsoft Graph de verdad -- estas pruebas
# construyen la fila de entrega a mano (solo canal INTERNA) en vez de dejar que el worker
# reclame lo que registrar_evento_outbox generaria, para no disparar un correo real a un
# empleado real de Enertika.
# ─────────────────────────────────────────────────────────────────────────────


async def _usuario_de_prueba(conn) -> "uuid4":
    return await conn.fetchval(
        """
        INSERT INTO tb_usuarios (email, nombre, rol_sistema, is_active)
        VALUES ($1, $2, 'USER', TRUE)
        RETURNING id_usuario
        """,
        f"outbox-test-{uuid4().hex[:10]}@example.com",
        "Usuario Prueba Outbox",
    )


async def _proyecto_real(conn):
    id_proyecto = await conn.fetchval("SELECT id_proyecto FROM tb_bom_paquetes LIMIT 1")
    if id_proyecto is None:
        pytest.skip("No hay tb_bom_paquetes reales en DEV para anclar el evento del outbox")
    return id_proyecto


async def _crear_evento_y_entrega_interna(conn, *, destinatario_id, id_proyecto):
    id_evento = await conn.fetchval(
        """
        INSERT INTO tb_bom_eventos_outbox (clave_idempotencia, tipo_evento, id_proyecto, payload)
        VALUES ($1, 'TEST_OUTBOX_REAL', $2, '{}'::jsonb)
        RETURNING id_evento
        """,
        f"test-outbox-{uuid4()}",
        id_proyecto,
    )
    id_entrega = await conn.fetchval(
        """
        INSERT INTO tb_bom_evento_entregas
            (id_evento, canal, destinatario_id, clave_idempotencia, payload)
        VALUES ($1, 'INTERNA', $2, $3, '{}'::jsonb)
        RETURNING id_entrega
        """,
        id_evento,
        destinatario_id,
        f"test-entrega-{uuid4()}",
    )
    return id_evento, id_entrega


@pytest.mark.asyncio
async def test_procesar_lote_entrega_interna_real_deja_notificacion(real_conn):
    id_proyecto = await _proyecto_real(real_conn)
    destinatario_id = await _usuario_de_prueba(real_conn)
    id_evento, id_entrega = await _crear_evento_y_entrega_interna(
        real_conn, destinatario_id=destinatario_id, id_proyecto=id_proyecto
    )

    metricas = await outbox_worker.procesar_bom_outbox_lote(
        real_conn, worker_id="test-worker", limite=10, max_intentos=8,
    )

    assert metricas["reclamadas"] >= 1
    assert metricas["agotadas"] == 0

    entrega_estatus = await real_conn.fetchval(
        "SELECT estatus FROM tb_bom_evento_entregas WHERE id_entrega = $1", id_entrega
    )
    assert entrega_estatus == "ENVIADO"

    evento_estatus = await real_conn.fetchval(
        "SELECT estatus FROM tb_bom_eventos_outbox WHERE id_evento = $1", id_evento
    )
    assert evento_estatus == "ENVIADO"

    notificacion = await real_conn.fetchval(
        "SELECT COUNT(*) FROM tb_notificaciones WHERE id_evento_bom = $1 AND usuario_id = $2",
        id_evento, destinatario_id,
    )
    assert notificacion == 1


@pytest.mark.asyncio
async def test_registrar_evento_outbox_es_idempotente_con_datos_reales(real_conn):
    id_proyecto = await _proyecto_real(real_conn)
    actor_id = await _usuario_de_prueba(real_conn)
    clave = f"test-outbox-idempotente-{uuid4()}"

    primero = await BomDBService().registrar_evento_outbox(
        real_conn, clave, "CANCELACION", id_proyecto, actor_id, {"nota": "primera"},
    )
    segundo = await BomDBService().registrar_evento_outbox(
        real_conn, clave, "CANCELACION", id_proyecto, actor_id, {"nota": "segunda"},
    )

    assert primero["id_evento"] == segundo["id_evento"]
    total_eventos = await real_conn.fetchval(
        "SELECT COUNT(*) FROM tb_bom_eventos_outbox WHERE clave_idempotencia = $1", clave
    )
    assert total_eventos == 1


@pytest.mark.asyncio
async def test_reclamar_lote_real_dos_workers_no_duplican_entregas(two_real_conns):
    conn_a, conn_b = two_real_conns
    id_proyecto = await _proyecto_real(conn_a)
    ids_entrega = []
    ids_evento = []
    ids_usuario = []
    try:
        for _ in range(6):
            destinatario_id = await _usuario_de_prueba(conn_a)
            ids_usuario.append(destinatario_id)
            id_evento, id_entrega = await _crear_evento_y_entrega_interna(
                conn_a, destinatario_id=destinatario_id, id_proyecto=id_proyecto
            )
            ids_evento.append(id_evento)
            ids_entrega.append(id_entrega)

        reclamadas_a, reclamadas_b = await asyncio.gather(
            outbox_worker._reclamar_lote(conn_a, "worker-a", limite=6, max_intentos=8),
            outbox_worker._reclamar_lote(conn_b, "worker-b", limite=6, max_intentos=8),
        )

        ids_a = {r["id_entrega"] for r in reclamadas_a}
        ids_b = {r["id_entrega"] for r in reclamadas_b}
        propias_a = ids_a & set(ids_entrega)
        propias_b = ids_b & set(ids_entrega)

        assert not (propias_a & propias_b), "SKIP LOCKED no debe dejar que dos workers reclamen la misma entrega"
        assert propias_a | propias_b == set(ids_entrega), "entre los dos workers deben reclamar todas las entregas pendientes"
    finally:
        await conn_a.execute(
            "DELETE FROM tb_bom_evento_entregas WHERE id_entrega = ANY($1::UUID[])",
            ids_entrega,
        )
        await conn_a.execute(
            "DELETE FROM tb_bom_eventos_outbox WHERE id_evento = ANY($1::UUID[])",
            ids_evento,
        )
        await conn_a.execute(
            "DELETE FROM tb_usuarios WHERE id_usuario = ANY($1::UUID[])",
            ids_usuario,
        )
