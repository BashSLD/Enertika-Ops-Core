"""
Tests de propagacion de estatus Levantamientos -> Oportunidades
(_Planes_Activos/2026-07-23-propagacion-estatus-levantamientos-PLAN.md).

No habia ningun test previo sobre cambiar_estado/cancelar_levantamiento/
reactivar_levantamiento/check_grupo_bloqueador (confirmado por el plan_scout).
Se escribieron primero como caracterizacion del comportamiento con bugs (Paso 1
de la secuencia sugerida) y se actualizaron para fijar el comportamiento
corregido una vez implementado _propagar_estatus_op (Pasos 1-4).
"""

from datetime import datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest

from modules.comercial.service import ComercialService
from modules.levantamientos.service import LevantamientoService

pytestmark = pytest.mark.asyncio


def _admin_context(user_id: UUID) -> dict:
    return {
        "user_db_id": user_id,
        "user_name": "Test Admin",
        "email": "admin@test.local",
        "role": "ADMIN",
        "module_roles": {},
    }


def _email() -> str:
    return f"test-{uuid4().hex}@test.local"


async def _crear_usuario(conn) -> UUID:
    return await conn.fetchval(
        """
        INSERT INTO tb_usuarios (email, nombre, rol_sistema, is_active)
        VALUES ($1, $2, 'USER', true)
        RETURNING id_usuario
        """,
        _email(),
        f"Test {uuid4().hex[:8]}",
    )


async def _crear_oportunidad(conn, *, creado_por_id: UUID, estatus_nombre: str = "Pendiente") -> UUID:
    id_estatus = await conn.fetchval(
        "SELECT id FROM tb_cat_estatus_oportunidades WHERE nombre = $1", estatus_nombre
    )
    assert id_estatus is not None, f"Estatus de oportunidad '{estatus_nombre}' no existe en catalogo"

    id_tipo_solicitud = await conn.fetchval(
        "SELECT id FROM tb_cat_tipos_solicitud WHERE codigo_interno = 'LEVANTAMIENTO'"
    )

    return await conn.fetchval(
        """
        INSERT INTO tb_oportunidades (
            id_oportunidad, op_id_estandar, cliente_nombre, creado_por_id,
            fecha_creacion, id_estatus_global, email_enviado, id_tipo_solicitud
        ) VALUES (gen_random_uuid(), $1, 'CLIENTE TEST', $2, now(), $3, true, $4)
        RETURNING id_oportunidad
        """,
        f"OP - TEST{uuid4().hex[:10]}",
        creado_por_id,
        id_estatus,
        id_tipo_solicitud,
    )


async def _crear_sitio(conn, id_oportunidad: UUID) -> UUID:
    return await conn.fetchval(
        """
        INSERT INTO tb_sitios_oportunidad (id_sitio, id_oportunidad, direccion, nombre_sitio)
        VALUES (gen_random_uuid(), $1, 'Direccion Test', 'Sitio Test')
        RETURNING id_sitio
        """,
        id_oportunidad,
    )


async def _crear_levantamiento(
    conn, *, id_oportunidad: UUID, id_sitio: UUID, solicitado_por_id: UUID, estatus_codigo: str = "pendiente"
) -> UUID:
    id_estatus = await conn.fetchval(
        "SELECT id FROM tb_cat_estatus_levantamiento WHERE codigo = $1", estatus_codigo
    )
    assert id_estatus is not None, f"Estatus de levantamiento '{estatus_codigo}' no existe en catalogo"

    now_mx = datetime.now(ZoneInfo("America/Mexico_City"))
    return await conn.fetchval(
        """
        INSERT INTO tb_levantamientos (
            id_levantamiento, id_sitio, id_oportunidad, solicitado_por_id,
            id_estatus_global, fecha_solicitud, created_at, updated_at, updated_by_id
        ) VALUES (gen_random_uuid(), $1, $2, $3, $4, $5, $5, $5, $3)
        RETURNING id_levantamiento
        """,
        id_sitio,
        id_oportunidad,
        solicitado_por_id,
        id_estatus,
        now_mx,
    )


async def _op_estatus_nombre(conn, id_oportunidad: UUID) -> str:
    return await conn.fetchval(
        """
        SELECT ce.nombre FROM tb_oportunidades o
        JOIN tb_cat_estatus_oportunidades ce ON ce.id = o.id_estatus_global
        WHERE o.id_oportunidad = $1
        """,
        id_oportunidad,
    )


async def _lev_estatus_codigo(conn, id_levantamiento: UUID) -> str:
    return await conn.fetchval(
        """
        SELECT cel.codigo FROM tb_levantamientos l
        JOIN tb_cat_estatus_levantamiento cel ON cel.id = l.id_estatus_global
        WHERE l.id_levantamiento = $1
        """,
        id_levantamiento,
    )


# ───────────────────────── cambiar_estado: sobre-propagacion multisitio ─────────────────────────


async def test_cambiar_estado_completado_en_multisitio_no_propaga_hasta_que_todos_terminan(real_conn):
    """Fix G-6/G-7: _propagar_estatus_op exige TODOS los levantamientos hermanos
    terminales antes de tocar la OP. Un solo sitio en 'completado' no debe mover
    la OP mientras el otro sitio siga 'pendiente'; solo al entregar formalmente
    el ultimo (con >=1 'entregado' entre los hermanos) la OP pasa a Entregado."""
    creador = await _crear_usuario(real_conn)
    admin = _admin_context(creador)
    id_op = await _crear_oportunidad(real_conn, creado_por_id=creador, estatus_nombre="Pendiente")
    sitio_1 = await _crear_sitio(real_conn, id_op)
    sitio_2 = await _crear_sitio(real_conn, id_op)
    lev_1 = await _crear_levantamiento(real_conn, id_oportunidad=id_op, id_sitio=sitio_1, solicitado_por_id=creador)
    lev_2 = await _crear_levantamiento(real_conn, id_oportunidad=id_op, id_sitio=sitio_2, solicitado_por_id=creador)

    id_completado = await real_conn.fetchval(
        "SELECT id FROM tb_cat_estatus_levantamiento WHERE codigo = 'completado'"
    )
    id_entregado = await real_conn.fetchval(
        "SELECT id FROM tb_cat_estatus_levantamiento WHERE codigo = 'entregado'"
    )

    service = LevantamientoService()
    await service.cambiar_estado(real_conn, lev_1, id_completado, admin)

    # Sitio 2 sigue pendiente -> no propaga todavia.
    assert await _op_estatus_nombre(real_conn, id_op) == "Pendiente"

    await service.cambiar_estado(real_conn, lev_2, id_entregado, admin)

    # Ambos terminales y al menos uno entregado -> ahora si propaga.
    assert await _op_estatus_nombre(real_conn, id_op) == "Entregado"


async def test_cambiar_estado_completado_respeta_op_ganada(real_conn):
    """Fix C-2: la guarda ahora protege explicitamente 'Ganada' (antes solo
    excluia es_estatus_final=true, y Ganada tiene ese flag en false). Completar
    el levantamiento de una OP ya ganada por Comercial no debe pisar esa decision."""
    creador = await _crear_usuario(real_conn)
    admin = _admin_context(creador)
    id_op = await _crear_oportunidad(real_conn, creado_por_id=creador, estatus_nombre="Ganada")
    sitio = await _crear_sitio(real_conn, id_op)
    lev = await _crear_levantamiento(real_conn, id_oportunidad=id_op, id_sitio=sitio, solicitado_por_id=creador)

    id_entregado = await real_conn.fetchval(
        "SELECT id FROM tb_cat_estatus_levantamiento WHERE codigo = 'entregado'"
    )

    service = LevantamientoService()
    await service.cambiar_estado(real_conn, lev, id_entregado, admin)

    assert await _op_estatus_nombre(real_conn, id_op) == "Ganada"


async def test_cambiar_estado_entregado_propaga_op_a_entregado(real_conn):
    """Comportamiento actual correcto (no cambia con el refactor): entregar el
    unico levantamiento de una OP pendiente si mueve la OP a 'Entregado'."""
    creador = await _crear_usuario(real_conn)
    admin = _admin_context(creador)
    id_op = await _crear_oportunidad(real_conn, creado_por_id=creador, estatus_nombre="Pendiente")
    sitio = await _crear_sitio(real_conn, id_op)
    lev = await _crear_levantamiento(real_conn, id_oportunidad=id_op, id_sitio=sitio, solicitado_por_id=creador)

    id_entregado = await real_conn.fetchval(
        "SELECT id FROM tb_cat_estatus_levantamiento WHERE codigo = 'entregado'"
    )

    service = LevantamientoService()
    await service.cambiar_estado(real_conn, lev, id_entregado, admin)

    assert await _op_estatus_nombre(real_conn, id_op) == "Entregado"


# ───────────────────────── cancelar_levantamiento: propagacion via motivo catalogado ─────────────────────────


async def test_cancelar_levantamiento_sin_motivo_catalogado_no_propaga(real_conn):
    """cancelar_levantamiento ahora invoca _propagar_estatus_op (Paso 1), pero el
    caso 3 (todos cancelados con motivo inviable) exige id_motivo_cancelacion
    poblado -- columna que el modal/endpoint (Paso 6, tarea aparte) todavia no
    escribe. Sin motivo catalogado, la propagacion queda inerte y la OP no se toca."""
    creador = await _crear_usuario(real_conn)
    admin = _admin_context(creador)
    id_op = await _crear_oportunidad(real_conn, creado_por_id=creador, estatus_nombre="Pendiente")
    sitio = await _crear_sitio(real_conn, id_op)
    lev = await _crear_levantamiento(real_conn, id_oportunidad=id_op, id_sitio=sitio, solicitado_por_id=creador)

    service = LevantamientoService()
    await service.cancelar_levantamiento(
        real_conn, lev, motivo="Motivo de prueba con longitud suficiente", user_context=admin
    )

    assert await _lev_estatus_codigo(real_conn, lev) == "cancelado"
    assert await _op_estatus_nombre(real_conn, id_op) == "Pendiente"


async def test_cancelar_levantamiento_con_motivo_inviable_propaga_op_a_cancelada(real_conn):
    """Caso 3 de _propagar_estatus_op: con id_motivo_cancelacion poblado y
    es_no_viable=true (columna sembrada en migracion 158), cancelar el unico
    levantamiento de la OP si la cierra como Cancelada con el motivo."""
    creador = await _crear_usuario(real_conn)
    admin = _admin_context(creador)
    id_op = await _crear_oportunidad(real_conn, creado_por_id=creador, estatus_nombre="Pendiente")
    sitio = await _crear_sitio(real_conn, id_op)
    lev = await _crear_levantamiento(real_conn, id_oportunidad=id_op, id_sitio=sitio, solicitado_por_id=creador)

    id_motivo_inviable = await real_conn.fetchval(
        "SELECT id FROM tb_cat_motivos_cierre WHERE es_no_viable = true AND aplicacion IN ('CANCELACION','AMBOS') LIMIT 1"
    )
    assert id_motivo_inviable is not None

    service = LevantamientoService()
    await service.cancelar_levantamiento(
        real_conn, lev, motivo="Motivo de prueba con longitud suficiente", user_context=admin,
        id_motivo_cancelacion=id_motivo_inviable,
    )

    assert await _op_estatus_nombre(real_conn, id_op) == "Cancelado"
    op_motivo = await real_conn.fetchval(
        "SELECT id_motivo_cierre FROM tb_oportunidades WHERE id_oportunidad = $1", id_op
    )
    assert op_motivo == id_motivo_inviable


# ───────────────────────── reactivar_levantamiento: transaccion atomica ─────────────────────────


async def test_reactivar_levantamiento_transaccion_atomica_revierte_si_falla_historial(
    real_conn, monkeypatch
):
    """Fix G-5: reactivar_levantamiento ahora envuelve UPDATE de estado + INSERT de
    historial + reversion de OP en una sola conn.transaction(). Si el historial
    falla, el UPDATE de estado tambien se revierte -- sin split state."""
    creador = await _crear_usuario(real_conn)
    admin = _admin_context(creador)
    id_op = await _crear_oportunidad(real_conn, creado_por_id=creador, estatus_nombre="Cancelado")
    sitio = await _crear_sitio(real_conn, id_op)
    lev = await _crear_levantamiento(
        real_conn, id_oportunidad=id_op, id_sitio=sitio, solicitado_por_id=creador, estatus_codigo="cancelado"
    )

    service = LevantamientoService()

    async def _historial_falla(*_args, **_kwargs):
        raise RuntimeError("Fallo simulado en registro de historial")

    monkeypatch.setattr(service, "_registrar_en_historial", _historial_falla)

    with pytest.raises(RuntimeError, match="Fallo simulado"):
        await service.reactivar_levantamiento(real_conn, lev, admin)

    # El UPDATE de estado se revirtio junto con el fallo: sin atomicidad quedaria en "pendiente".
    assert await _lev_estatus_codigo(real_conn, lev) == "cancelado"


# ───────────────────────── reactivar_levantamiento: reversion bidireccional de la OP ─────────────────────────


async def test_reactivar_levantamiento_revierte_op_cancelada_a_pendiente(real_conn):
    """Paso 4 del PLAN: si la OP sigue exactamente en 'Cancelado' (lo que la
    propagacion fijo), reactivar el levantamiento tambien revierte la OP a
    Pendiente y limpia id_motivo_cierre."""
    creador = await _crear_usuario(real_conn)
    admin = _admin_context(creador)
    id_op = await _crear_oportunidad(real_conn, creado_por_id=creador, estatus_nombre="Cancelado")
    id_motivo = await real_conn.fetchval("SELECT id FROM tb_cat_motivos_cierre LIMIT 1")
    await real_conn.execute(
        "UPDATE tb_oportunidades SET id_motivo_cierre = $1 WHERE id_oportunidad = $2", id_motivo, id_op
    )
    sitio = await _crear_sitio(real_conn, id_op)
    lev = await _crear_levantamiento(
        real_conn, id_oportunidad=id_op, id_sitio=sitio, solicitado_por_id=creador, estatus_codigo="cancelado"
    )

    service = LevantamientoService()
    await service.reactivar_levantamiento(real_conn, lev, admin)

    assert await _lev_estatus_codigo(real_conn, lev) == "pendiente"
    assert await _op_estatus_nombre(real_conn, id_op) == "Pendiente"
    op_motivo = await real_conn.fetchval(
        "SELECT id_motivo_cierre FROM tb_oportunidades WHERE id_oportunidad = $1", id_op
    )
    assert op_motivo is None


async def test_reactivar_levantamiento_no_revierte_op_ganada(real_conn):
    """Guarda C-2 espejo en la reversion: si Comercial ya movio la OP a Ganada
    (no esta en 'Cancelado'), reactivar el levantamiento no debe tocarla."""
    creador = await _crear_usuario(real_conn)
    admin = _admin_context(creador)
    id_op = await _crear_oportunidad(real_conn, creado_por_id=creador, estatus_nombre="Ganada")
    sitio = await _crear_sitio(real_conn, id_op)
    lev = await _crear_levantamiento(
        real_conn, id_oportunidad=id_op, id_sitio=sitio, solicitado_por_id=creador, estatus_codigo="cancelado"
    )

    service = LevantamientoService()
    await service.reactivar_levantamiento(real_conn, lev, admin)

    assert await _lev_estatus_codigo(real_conn, lev) == "pendiente"
    assert await _op_estatus_nombre(real_conn, id_op) == "Ganada"


# ───────────────────────── check_grupo_bloqueador: cerrar la OP sola no desbloquea ─────────────────────────


async def test_check_grupo_bloqueador_op_cerrada_no_desbloquea_si_lev_sigue_activo(real_conn):
    """Comportamiento actual (documentado en C-3 del PLAN, no cambia con el
    refactor): check_grupo_bloqueador es tiene_activo_op OR tiene_activo_lev --
    cerrar solo la OP no desbloquea el hilo si el levantamiento sigue no-terminal."""
    creador = await _crear_usuario(real_conn)
    id_op = await _crear_oportunidad(real_conn, creado_por_id=creador, estatus_nombre="Cancelado")
    sitio = await _crear_sitio(real_conn, id_op)
    await _crear_levantamiento(
        real_conn, id_oportunidad=id_op, id_sitio=sitio, solicitado_por_id=creador, estatus_codigo="pendiente"
    )

    service = ComercialService()
    bloqueador = await service.check_grupo_bloqueador(real_conn, id_op)

    assert bloqueador["tipo"] == "activo"
    assert bloqueador["lev"] is not None
