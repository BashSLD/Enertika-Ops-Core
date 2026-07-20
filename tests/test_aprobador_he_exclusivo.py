"""
Tests del aprobador exclusivo de horas extra/compensatorio
(_Planes_Activos/PLAN_EXCEPCION_APROBADOR_HORAS_EXTRA.md, seccion 4.8).

Combina funciones puras (sin BD), tests unitarios con monkeypatch, y tests de
integracion con BD real (fixture `real_conn`, filas temporales revertidas por
rollback) para la logica de autorizacion en modules/asistencia/db_service.py.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from core.config import settings
from core.tasks_db_service import get_tasks_db_service
from modules.asistencia import db_service as asistencia_db
from modules.asistencia import service as asistencia_service
from modules.asistencia.service import (
    HEAutorizacionError,
    HEFallbackVacioError,
    aprobar_horas_extra_svc,
    get_equipo_visible_he,
    omitir_horas_extra_propio_svc,
    resolver_destinatarios_he_puro,
    verificar_fallback_aprobador_he_svc,
)
from modules.perfil.router import _resolve_initial_tab
from modules.rrhh.service import _resolver_id_aprobador_horas_extra

URL_PERFIL = f"{settings.APP_BASE_URL}/perfil/ui?tab=aprobaciones"
URL_RH = f"{settings.APP_BASE_URL}/rrhh/ui?tab=aprobaciones"
ESCALACION_CC = {"rh_config@enertika.mx"}
ESCALACION_CCO = {"admin_config@enertika.mx"}


# ───────────────────────── resolver_destinatarios_he_puro ─────────────────────────


def test_resolver_override_activo_con_email():
    resultado = resolver_destinatarios_he_puro(
        tiene_override=True,
        override_email="sarel@enertika.mx",
        jefe_emails=["miguel@enertika.mx"],
        tiene_director=False,
        aprobador_vac_email="miguel@enertika.mx",
        fallback_emails={"rh@enertika.mx"},
        escalacion_cc=ESCALACION_CC,
        escalacion_cco=ESCALACION_CCO,
    )
    assert resultado == {
        "to": {"sarel@enertika.mx"},
        "cc": set(),
        "bcc": set(),
        "url": URL_PERFIL,
        "label_boton": "Revisar en Aprobaciones",
    }


def test_resolver_override_activo_pero_aprobador_inactivo_usa_fallback():
    resultado = resolver_destinatarios_he_puro(
        tiene_override=True,
        override_email=None,
        jefe_emails=["miguel@enertika.mx"],
        tiene_director=False,
        aprobador_vac_email="miguel@enertika.mx",
        fallback_emails={"rh@enertika.mx", "admin@enertika.mx"},
    )
    assert resultado["to"] == {"rh@enertika.mx", "admin@enertika.mx"}
    assert resultado["cc"] == set()
    assert resultado["bcc"] == set()
    assert resultado["url"] == URL_RH
    assert resultado["label_boton"] == "Revisar en RRHH"


def test_resolver_override_inactivo_sin_fallback_to_vacio():
    resultado = resolver_destinatarios_he_puro(
        tiene_override=True,
        override_email=None,
        jefe_emails=[],
        tiene_director=False,
        aprobador_vac_email=None,
        fallback_emails=set(),
    )
    assert resultado["to"] == set()
    assert resultado["url"] == URL_RH


def test_resolver_regla_normal_con_director_usa_escalacion_cc_cco():
    resultado = resolver_destinatarios_he_puro(
        tiene_override=False,
        override_email=None,
        jefe_emails=["jefe1@enertika.mx", "jefe2@enertika.mx"],
        tiene_director=True,
        aprobador_vac_email="vac@enertika.mx",
        fallback_emails={"rh@enertika.mx"},
        escalacion_cc=ESCALACION_CC,
        escalacion_cco=ESCALACION_CCO,
    )
    assert resultado["to"] == {"jefe1@enertika.mx", "jefe2@enertika.mx", "vac@enertika.mx"}
    assert resultado["cc"] == ESCALACION_CC
    assert resultado["bcc"] == ESCALACION_CCO
    assert resultado["url"] == URL_PERFIL
    assert resultado["label_boton"] == "Revisar en Aprobaciones"


def test_resolver_regla_normal_con_director_sin_config_no_agrega_nada():
    """Si RH no configuro reglas CC/CCO en Admin para el evento de escalacion, no se
    agrega nadie -- el resolver ya no cae al fallback RH/ADMIN por rol como antes."""
    resultado = resolver_destinatarios_he_puro(
        tiene_override=False,
        override_email=None,
        jefe_emails=["jefe1@enertika.mx"],
        tiene_director=True,
        aprobador_vac_email="vac@enertika.mx",
        fallback_emails={"rh@enertika.mx"},
    )
    assert resultado["cc"] == set()
    assert resultado["bcc"] == set()


def test_resolver_regla_normal_sin_director_cc_vacio():
    resultado = resolver_destinatarios_he_puro(
        tiene_override=False,
        override_email=None,
        jefe_emails=["jefe1@enertika.mx"],
        tiene_director=False,
        aprobador_vac_email=None,
        fallback_emails={"rh@enertika.mx"},
        escalacion_cc=ESCALACION_CC,
        escalacion_cco=ESCALACION_CCO,
    )
    assert resultado["cc"] == set()
    assert resultado["bcc"] == set()


def test_resolver_regla_normal_sin_destinatarios_cae_a_fallback():
    resultado = resolver_destinatarios_he_puro(
        tiene_override=False,
        override_email=None,
        jefe_emails=None,
        tiene_director=False,
        aprobador_vac_email=None,
        fallback_emails={"rh@enertika.mx"},
    )
    assert resultado["to"] == {"rh@enertika.mx"}
    assert resultado["url"] == URL_RH
    assert resultado["label_boton"] == "Revisar en RRHH"


def test_resolver_director_sin_correo_no_agrega_cc():
    """Director en la jerarquia pero sin correo registrado (jefe_emails vacio pese a
    tiene_director=True): CC/CCO deben quedar vacios, ya que ningun correo de director
    llego a TO (el TO se llena solo via aprobador de vacaciones)."""
    resultado = resolver_destinatarios_he_puro(
        tiene_override=False,
        override_email=None,
        jefe_emails=[],
        tiene_director=True,
        aprobador_vac_email="vac@enertika.mx",
        fallback_emails={"rh@enertika.mx"},
        escalacion_cc=ESCALACION_CC,
        escalacion_cco=ESCALACION_CCO,
    )
    assert resultado["to"] == {"vac@enertika.mx"}
    assert resultado["cc"] == set()
    assert resultado["bcc"] == set()


def test_resolver_filtra_emails_nulos_en_lista_de_jefes():
    resultado = resolver_destinatarios_he_puro(
        tiene_override=False,
        override_email=None,
        jefe_emails=["jefe1@enertika.mx", None],
        tiene_director=False,
        aprobador_vac_email=None,
        fallback_emails=set(),
    )
    assert resultado["to"] == {"jefe1@enertika.mx"}


# ───────────────────────── _resolve_initial_tab (perfil) ─────────────────────────


def _resolve(tab, *, puede_ver_aprobaciones, puede_ver_equipo):
    return _resolve_initial_tab(
        tab,
        puede_ver_aprobaciones=puede_ver_aprobaciones,
        puede_ver_equipo=puede_ver_equipo,
        solicitud_id=None,
        origen="solicitudes",
        equipo_uid=None,
        solicitud_pendiente_id=None,
    )


def test_aprobador_exclusivo_sin_jerarquia_ve_aprobaciones_no_equipo():
    tab, endpoint = _resolve("aprobaciones", puede_ver_aprobaciones=True, puede_ver_equipo=False)
    assert tab == "aprobaciones"
    assert endpoint == "/vacaciones/aprobaciones"


def test_aprobador_exclusivo_sin_jerarquia_no_puede_abrir_equipo():
    tab, _ = _resolve("equipo", puede_ver_aprobaciones=True, puede_ver_equipo=False)
    assert tab == "asistencia"


def test_jefe_historico_sin_override_ve_ambas_pestanas():
    tab, _ = _resolve("equipo", puede_ver_aprobaciones=True, puede_ver_equipo=True)
    assert tab == "equipo"
    tab, _ = _resolve("aprobaciones", puede_ver_aprobaciones=True, puede_ver_equipo=True)
    assert tab == "aprobaciones"


def test_usuario_sin_ningun_permiso_cae_a_asistencia():
    tab, _ = _resolve("aprobaciones", puede_ver_aprobaciones=False, puede_ver_equipo=False)
    assert tab == "asistencia"


# ───────────────────────── get_equipo_visible_he (union) ─────────────────────────


@pytest.mark.asyncio
async def test_get_equipo_visible_he_une_consulta_y_autorizacion(monkeypatch):
    autorizable = uuid4()
    solo_consulta = uuid4()

    async def fake_autorizacion(_conn, _user_id, _ctx):
        return [autorizable]

    monkeypatch.setattr(
        asistencia_service, "get_equipo_ids_para_autorizacion_he", fake_autorizacion
    )

    visible, autorizable_set = await get_equipo_visible_he(
        None, uuid4(), {}, base_ids=[solo_consulta]
    )

    assert set(visible) == {autorizable, solo_consulta}
    assert autorizable_set == {autorizable}
    assert solo_consulta not in autorizable_set


@pytest.mark.asyncio
async def test_get_equipo_visible_he_aprobador_exclusivo_sin_base_ids(monkeypatch):
    autorizable = uuid4()

    async def fake_autorizacion(_conn, _user_id, _ctx):
        return [autorizable]

    monkeypatch.setattr(
        asistencia_service, "get_equipo_ids_para_autorizacion_he", fake_autorizacion
    )

    visible, autorizable_set = await get_equipo_visible_he(None, uuid4(), {})

    assert visible == [autorizable]
    assert autorizable_set == {autorizable}


# ───────────────────────── verificar_fallback_aprobador_he_svc ─────────────────────────


@pytest.mark.asyncio
async def test_verificar_fallback_sin_afectados_no_lanza(monkeypatch):
    async def fake_verificar(_conn, *, user_id, sera_fallback_despues):
        return {"afectados_count": 0, "tiene_fallback": True}

    monkeypatch.setattr(asistencia_service.db, "verificar_fallback_aprobador_he", fake_verificar)
    await verificar_fallback_aprobador_he_svc(None, user_id=uuid4(), sera_fallback_despues=False)


@pytest.mark.asyncio
async def test_verificar_fallback_con_afectados_y_fallback_disponible_no_lanza(monkeypatch):
    async def fake_verificar(_conn, *, user_id, sera_fallback_despues):
        return {"afectados_count": 2, "tiene_fallback": True}

    monkeypatch.setattr(asistencia_service.db, "verificar_fallback_aprobador_he", fake_verificar)
    await verificar_fallback_aprobador_he_svc(None, user_id=uuid4(), sera_fallback_despues=False)


@pytest.mark.asyncio
async def test_verificar_fallback_vacio_lanza_409(monkeypatch):
    async def fake_verificar(_conn, *, user_id, sera_fallback_despues):
        return {"afectados_count": 3, "tiene_fallback": False}

    monkeypatch.setattr(asistencia_service.db, "verificar_fallback_aprobador_he", fake_verificar)
    with pytest.raises(HEFallbackVacioError, match="3 empleado"):
        await verificar_fallback_aprobador_he_svc(None, user_id=uuid4(), sera_fallback_despues=False)


# ───────────────────────── DB real: autorizacion HE ─────────────────────────


async def _crear_usuario(conn, *, email: str | None, is_active: bool = True, rol_sistema: str = "USER") -> UUID:
    row = await conn.fetchrow(
        """
        INSERT INTO tb_usuarios (email, nombre, rol_sistema, is_active)
        VALUES ($1, $2, $3, $4)
        RETURNING id_usuario
        """,
        email,
        f"Test {uuid4().hex[:8]}",
        rol_sistema,
        is_active,
    )
    return row["id_usuario"]


async def _crear_empleado_datos(
    conn,
    usuario_id: UUID,
    *,
    id_aprobador_vacaciones: UUID | None = None,
    id_aprobador_horas_extra: UUID | None = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO tb_empleados_datos (usuario_id, id_aprobador_vacaciones, id_aprobador_horas_extra)
        VALUES ($1, $2, $3)
        """,
        usuario_id,
        id_aprobador_vacaciones,
        id_aprobador_horas_extra,
    )


async def _crear_jefe(conn, empleado_id: UUID, jefe_id: UUID) -> None:
    await conn.execute(
        "INSERT INTO tb_empleados_jefes (empleado_id, jefe_id) VALUES ($1, $2)",
        empleado_id,
        jefe_id,
    )


def _email() -> str:
    return f"test-{uuid4().hex}@test.local"


async def _crear_asistencia_diaria(
    conn, usuario_id: UUID, *, horas_extra_estado: str = "pendiente", minutos_extra: int = 90
) -> UUID:
    return await conn.fetchval(
        """
        INSERT INTO tb_asistencia_diaria (
            usuario_id, fecha_laboral, primera_entrada, ultima_salida,
            minutos_trabajados, minutos_programados, minutos_extra, estado,
            tiene_vacaciones, horas_extra_estado, motivo_solicitud,
            calculated_at, created_at, updated_at
        )
        VALUES ($1, CURRENT_DATE, now(), now(), 600, 480, $2, 'asistencia',
                false, $3, 'test retiro propio', now(), now(), now())
        RETURNING id
        """,
        usuario_id,
        minutos_extra,
        horas_extra_estado,
    )


@pytest.mark.asyncio
async def test_get_empleados_para_autorizacion_he_override_excluye_jefe_historico(real_conn):
    jefe = await _crear_usuario(real_conn, email=_email())
    aprobador_exclusivo = await _crear_usuario(real_conn, email=_email())
    empleado = await _crear_usuario(real_conn, email=_email())
    await _crear_empleado_datos(real_conn, empleado, id_aprobador_horas_extra=aprobador_exclusivo)
    await _crear_jefe(real_conn, empleado, jefe)

    ids_exclusivo = await asistencia_db.get_empleados_para_autorizacion_he(real_conn, aprobador_exclusivo)
    ids_jefe = await asistencia_db.get_empleados_para_autorizacion_he(real_conn, jefe)

    assert empleado in ids_exclusivo
    assert empleado not in ids_jefe


@pytest.mark.asyncio
async def test_get_empleados_para_autorizacion_he_null_conserva_regla_normal(real_conn):
    jefe = await _crear_usuario(real_conn, email=_email())
    empleado = await _crear_usuario(real_conn, email=_email())
    await _crear_empleado_datos(real_conn, empleado, id_aprobador_horas_extra=None)
    await _crear_jefe(real_conn, empleado, jefe)

    ids_jefe = await asistencia_db.get_empleados_para_autorizacion_he(real_conn, jefe)

    assert empleado in ids_jefe


@pytest.mark.asyncio
async def test_get_empleados_para_autorizacion_he_aprobador_vacaciones_sin_override(real_conn):
    aprobador_vac = await _crear_usuario(real_conn, email=_email())
    empleado = await _crear_usuario(real_conn, email=_email())
    await _crear_empleado_datos(real_conn, empleado, id_aprobador_vacaciones=aprobador_vac)

    ids = await asistencia_db.get_empleados_para_autorizacion_he(real_conn, aprobador_vac)

    assert empleado in ids


@pytest.mark.asyncio
async def test_puede_autorizar_he_niega_autoaprobacion(real_conn):
    usuario = await _crear_usuario(real_conn, email=_email())
    assert await asistencia_db.puede_autorizar_he(real_conn, usuario, usuario) is False


@pytest.mark.asyncio
async def test_puede_autorizar_he_admin_global_bypass(real_conn):
    admin = await _crear_usuario(real_conn, email=_email(), rol_sistema="ADMIN")
    empleado = await _crear_usuario(real_conn, email=_email())
    await _crear_empleado_datos(real_conn, empleado)

    assert await asistencia_db.puede_autorizar_he(real_conn, empleado, admin) is True


@pytest.mark.asyncio
async def test_puede_autorizar_he_rh_editor_bypass(real_conn):
    rh_editor = await _crear_usuario(real_conn, email=_email())
    empleado = await _crear_usuario(real_conn, email=_email())
    await _crear_empleado_datos(real_conn, empleado)
    await real_conn.execute(
        "INSERT INTO tb_permisos_modulos (id, usuario_id, modulo_slug, rol_modulo) VALUES (gen_random_uuid(), $1, 'rrhh', 'editor')",
        rh_editor,
    )

    assert await asistencia_db.puede_autorizar_he(real_conn, empleado, rh_editor) is True


@pytest.mark.asyncio
async def test_puede_autorizar_he_override_activo_permite_solo_al_exclusivo(real_conn):
    jefe = await _crear_usuario(real_conn, email=_email())
    aprobador_exclusivo = await _crear_usuario(real_conn, email=_email())
    empleado = await _crear_usuario(real_conn, email=_email())
    await _crear_empleado_datos(real_conn, empleado, id_aprobador_horas_extra=aprobador_exclusivo)
    await _crear_jefe(real_conn, empleado, jefe)

    assert await asistencia_db.puede_autorizar_he(real_conn, empleado, aprobador_exclusivo) is True
    assert await asistencia_db.puede_autorizar_he(real_conn, empleado, jefe) is False


@pytest.mark.asyncio
async def test_puede_autorizar_he_sin_override_permite_jefe_directo(real_conn):
    jefe = await _crear_usuario(real_conn, email=_email())
    empleado = await _crear_usuario(real_conn, email=_email())
    await _crear_empleado_datos(real_conn, empleado)
    await _crear_jefe(real_conn, empleado, jefe)

    assert await asistencia_db.puede_autorizar_he(real_conn, empleado, jefe) is True


@pytest.mark.asyncio
async def test_puede_autorizar_he_actor_inactivo_no_autoriza(real_conn):
    aprobador_exclusivo = await _crear_usuario(real_conn, email=_email(), is_active=False)
    empleado = await _crear_usuario(real_conn, email=_email())
    await _crear_empleado_datos(real_conn, empleado, id_aprobador_horas_extra=aprobador_exclusivo)

    assert await asistencia_db.puede_autorizar_he(real_conn, empleado, aprobador_exclusivo) is False


@pytest.mark.asyncio
async def test_puede_autorizar_he_extrano_sin_relacion_no_autoriza(real_conn):
    extrano = await _crear_usuario(real_conn, email=_email())
    empleado = await _crear_usuario(real_conn, email=_email())
    await _crear_empleado_datos(real_conn, empleado)

    assert await asistencia_db.puede_autorizar_he(real_conn, empleado, extrano) is False


# ───────────────────────── consistencia entre las 3 implementaciones de precedencia ─────────────────────────
# Regression guard para la triplicacion documentada en get_empleados_para_autorizacion_he /
# puede_autorizar_he / resolver_destinatarios_he_puro (ver notas "ATENCION" en esos docstrings):
# si alguna cambia la regla de precedencia (exclusivo > jefe/aprobador de vacaciones) sin
# replicarla en las otras, estos tests deben fallar.


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "con_override,con_jefe,con_aprobador_vac",
    [
        (True, True, True),
        (True, False, False),
        (False, True, False),
        (False, False, True),
        (False, True, True),
    ],
)
async def test_consistencia_precedencia_he_get_empleados_vs_puede_autorizar(
    real_conn, con_override, con_jefe, con_aprobador_vac
):
    empleado = await _crear_usuario(real_conn, email=_email())
    override = await _crear_usuario(real_conn, email=_email()) if con_override else None
    jefe = await _crear_usuario(real_conn, email=_email()) if con_jefe else None
    aprobador_vac = await _crear_usuario(real_conn, email=_email()) if con_aprobador_vac else None

    await _crear_empleado_datos(
        real_conn,
        empleado,
        id_aprobador_vacaciones=aprobador_vac,
        id_aprobador_horas_extra=override,
    )
    if jefe:
        await _crear_jefe(real_conn, empleado, jefe)

    candidatos_y_esperado = []
    if override:
        candidatos_y_esperado.append((override, True))
    if jefe:
        candidatos_y_esperado.append((jefe, not con_override))
    if aprobador_vac:
        candidatos_y_esperado.append((aprobador_vac, not con_override))

    for candidato, deberia_autorizar in candidatos_y_esperado:
        en_lista = empleado in await asistencia_db.get_empleados_para_autorizacion_he(real_conn, candidato)
        puede = await asistencia_db.puede_autorizar_he(real_conn, empleado, candidato)
        assert en_lista == deberia_autorizar, (
            f"get_empleados_para_autorizacion_he desincronizada de puede_autorizar_he "
            f"para candidato={candidato}, override={con_override}, jefe={con_jefe}"
        )
        assert puede == deberia_autorizar
        assert en_lista == puede


@pytest.mark.asyncio
@pytest.mark.parametrize("con_override", [True, False])
async def test_consistencia_precedencia_he_tiene_override_flag(real_conn, con_override):
    empleado = await _crear_usuario(real_conn, email=_email())
    override = await _crear_usuario(real_conn, email=_email()) if con_override else None
    await _crear_empleado_datos(real_conn, empleado, id_aprobador_horas_extra=override)

    datos = await asistencia_db.get_datos_resolucion_notificacion_he(real_conn, empleado)
    assert datos["tiene_override"] is con_override

    # Mismo discriminador que get_empleados_para_autorizacion_he/puede_autorizar_he usan
    # para decidir si la rama jefe/aprobador_vacaciones aplica (id_aprobador_horas_extra IS NULL).
    tiene_override_en_db = await real_conn.fetchval(
        "SELECT id_aprobador_horas_extra IS NOT NULL FROM tb_empleados_datos WHERE usuario_id = $1",
        empleado,
    )
    assert datos["tiene_override"] == tiene_override_en_db


# ───────────────────────── reasignacion concurrente (2 conexiones) ─────────────────────────


@pytest.mark.asyncio
async def test_reasignacion_concurrente_bloquea_aprobador_anterior(two_real_conns):
    """Si RH reasigna el aprobador exclusivo mientras el aprobador anterior ya
    tenia la aprobacion en vuelo, quien gana la carrera del advisory lock
    (lock_he_usuario) decide: la reasignacion adquiere el lock primero, hace su
    UPDATE y comitea; el aprobador viejo se desbloquea despues, revalida en BD
    (no reusa una lista de UI) y debe recibir HEAutorizacionError -- sin crear
    credito de bolsa con datos obsoletos.
    """
    conn_a, conn_b = two_real_conns

    aprobador_viejo = await _crear_usuario(conn_a, email=_email())
    aprobador_nuevo = await _crear_usuario(conn_a, email=_email())
    empleado = await _crear_usuario(conn_a, email=_email())
    await _crear_empleado_datos(conn_a, empleado, id_aprobador_horas_extra=aprobador_viejo)

    asistencia_id = await conn_a.fetchval(
        """
        INSERT INTO tb_asistencia_diaria (
            usuario_id, fecha_laboral, primera_entrada, ultima_salida,
            minutos_trabajados, minutos_programados, minutos_extra, estado,
            tiene_vacaciones, horas_extra_estado, motivo_solicitud,
            calculated_at, created_at, updated_at
        )
        VALUES ($1, CURRENT_DATE, now(), now(), 600, 480, 90, 'asistencia',
                false, 'solicitado', 'test concurrencia reasignacion',
                now(), now(), now())
        RETURNING id
        """,
        empleado,
    )

    lock_adquirido = asyncio.Event()
    resultado: dict[str, Exception] = {}

    async def tarea_reasignacion():
        async with conn_b.transaction():
            await asistencia_db.lock_he_usuario(conn_b, empleado)
            lock_adquirido.set()
            await asyncio.sleep(0.3)
            await conn_b.execute(
                "UPDATE tb_empleados_datos SET id_aprobador_horas_extra = $1 WHERE usuario_id = $2",
                aprobador_nuevo,
                empleado,
            )

    async def tarea_aprobacion_vieja():
        await lock_adquirido.wait()
        try:
            await aprobar_horas_extra_svc(
                conn_a,
                asistencia_id=asistencia_id,
                aprobador_id=aprobador_viejo,
                minutos_aprobados=60,
                comentario="intento con aprobador ya reasignado",
            )
        except HEAutorizacionError as exc:
            resultado["error"] = exc

    try:
        await asyncio.gather(tarea_aprobacion_vieja(), tarea_reasignacion())

        assert isinstance(resultado.get("error"), HEAutorizacionError)

        estado_final = await conn_a.fetchval(
            "SELECT horas_extra_estado FROM tb_asistencia_diaria WHERE id = $1", asistencia_id
        )
        assert estado_final == "solicitado"

        aprobador_final = await conn_a.fetchval(
            "SELECT id_aprobador_horas_extra FROM tb_empleados_datos WHERE usuario_id = $1", empleado
        )
        assert aprobador_final == aprobador_nuevo
    finally:
        await conn_a.execute(
            "DELETE FROM tb_horas_extra_aprobaciones WHERE asistencia_id = $1", asistencia_id
        )
        await conn_a.execute("DELETE FROM tb_asistencia_diaria WHERE id = $1", asistencia_id)
        await conn_a.execute("DELETE FROM tb_empleados_datos WHERE usuario_id = $1", empleado)
        await conn_a.execute(
            "DELETE FROM tb_usuarios WHERE id_usuario = ANY($1::uuid[])",
            [empleado, aprobador_viejo, aprobador_nuevo],
        )


# ───────────────────────── retiro propio ─────────────────────────


@pytest.mark.asyncio
async def test_retiro_propio_omite_pendiente_sin_notificar(real_conn, monkeypatch):
    empleado = await _crear_usuario(real_conn, email=_email())
    asistencia_id = await _crear_asistencia_diaria(real_conn, empleado, horas_extra_estado="pendiente")
    llamado = {"veces": 0}

    async def fake_notificar(*_a, **_k):
        llamado["veces"] += 1

    monkeypatch.setattr(asistencia_service, "_notificar_retiro_horas_extra", fake_notificar)

    resultado = await omitir_horas_extra_propio_svc(
        real_conn, asistencia_id=asistencia_id, usuario_id=empleado
    )

    assert resultado["estado_anterior"] == "pendiente"
    estado = await real_conn.fetchval(
        "SELECT horas_extra_estado FROM tb_asistencia_diaria WHERE id = $1", asistencia_id
    )
    assert estado == "omitido"
    assert llamado["veces"] == 0


@pytest.mark.asyncio
async def test_retiro_propio_retira_solicitado_y_notifica(real_conn, monkeypatch):
    empleado = await _crear_usuario(real_conn, email=_email())
    asistencia_id = await _crear_asistencia_diaria(real_conn, empleado, horas_extra_estado="solicitado")
    capturado = {}

    async def fake_notificar(conn, *, usuario_id, row):
        capturado["usuario_id"] = usuario_id
        capturado["row"] = row

    monkeypatch.setattr(asistencia_service, "_notificar_retiro_horas_extra", fake_notificar)

    resultado = await omitir_horas_extra_propio_svc(
        real_conn, asistencia_id=asistencia_id, usuario_id=empleado
    )

    assert resultado["estado_anterior"] == "solicitado"
    estado = await real_conn.fetchval(
        "SELECT horas_extra_estado FROM tb_asistencia_diaria WHERE id = $1", asistencia_id
    )
    assert estado == "omitido"
    assert capturado["usuario_id"] == empleado


@pytest.mark.asyncio
async def test_retiro_propio_tercero_no_puede_retirar_ajeno(real_conn):
    empleado = await _crear_usuario(real_conn, email=_email())
    tercero = await _crear_usuario(real_conn, email=_email())
    asistencia_id = await _crear_asistencia_diaria(real_conn, empleado, horas_extra_estado="pendiente")

    with pytest.raises(ValueError, match="No tienes permiso"):
        await omitir_horas_extra_propio_svc(real_conn, asistencia_id=asistencia_id, usuario_id=tercero)

    estado = await real_conn.fetchval(
        "SELECT horas_extra_estado FROM tb_asistencia_diaria WHERE id = $1", asistencia_id
    )
    assert estado == "pendiente"


@pytest.mark.asyncio
async def test_retiro_propio_rechaza_estado_no_retirable(real_conn):
    empleado = await _crear_usuario(real_conn, email=_email())
    asistencia_id = await _crear_asistencia_diaria(real_conn, empleado, horas_extra_estado="aprobado")

    with pytest.raises(ValueError, match="pendientes o solicitados"):
        await omitir_horas_extra_propio_svc(real_conn, asistencia_id=asistencia_id, usuario_id=empleado)


@pytest.mark.asyncio
async def test_notificar_retiro_horas_extra_incluye_escalacion_cc_y_bcc(real_conn, monkeypatch):
    """Regression: _notificar_retiro_horas_extra unia solo to|cc antes de que
    resolver_destinatarios_he_puro separara la escalacion a director en cc/bcc -- el
    CCO (ADMIN) quedaba fuera del aviso de retiro. Debe incluir las tres."""
    from core.timezone import today_mx

    jefe_email = _email()
    jefe = await _crear_usuario(real_conn, email=jefe_email)
    await real_conn.execute(
        "UPDATE tb_usuarios SET rol_organizacional = 'director' WHERE id_usuario = $1", jefe
    )
    empleado = await _crear_usuario(real_conn, email=_email())
    await _crear_empleado_datos(real_conn, empleado)
    await _crear_jefe(real_conn, empleado, jefe)

    cc_email = _email()
    bcc_email = _email()
    await real_conn.execute(
        """
        INSERT INTO tb_config_emails (modulo, trigger_field, trigger_value, email_to_add, type)
        VALUES ('ASISTENCIA', 'EVENTO', 'HORAS_EXTRA_ESCALACION_DIRECTOR', $1, 'CC'),
               ('ASISTENCIA', 'EVENTO', 'HORAS_EXTRA_ESCALACION_DIRECTOR', $2, 'CCO')
        """,
        cc_email,
        bcc_email,
    )

    capturado = {}

    async def fake_notify(self, conn, *, empleado_nombre, fecha_laboral, extra_fmt, destinatarios):
        capturado["destinatarios"] = destinatarios
        return True

    monkeypatch.setattr(
        "core.workflow.notification_service.NotificationService.notify_he_solicitud_retirada",
        fake_notify,
    )

    row = {"empleado_nombre": "Empleado Test", "fecha_laboral": today_mx(), "minutos_extra": 90}
    await asistencia_service._notificar_retiro_horas_extra(real_conn, usuario_id=empleado, row=row)

    # >= (no ==): la BD de pruebas puede tener otras filas CC/CCO preexistentes para el
    # mismo evento (p.ej. la semilla de la migracion 154) que tambien deben incluirse --
    # el punto de este test es que jefe_email (to), cc_email y bcc_email SI llegan, no que
    # sean los unicos.
    assert capturado["destinatarios"] >= {jefe_email, cc_email, bcc_email}


# ───────────────────────── validacion formulario RH ─────────────────────────


@pytest.mark.asyncio
async def test_resolver_aprobador_he_regla_normal_devuelve_none(real_conn):
    empleado = await _crear_usuario(real_conn, email=_email())

    resultado = await _resolver_id_aprobador_horas_extra(
        real_conn, usuario_id=empleado, existing=None, accion="regla_normal", candidato_id=uuid4()
    )

    assert resultado is None


@pytest.mark.asyncio
async def test_resolver_aprobador_he_conservar_inactivo_sin_actual_falla(real_conn):
    empleado = await _crear_usuario(real_conn, email=_email())

    with pytest.raises(ValueError, match="No hay un aprobador exclusivo"):
        await _resolver_id_aprobador_horas_extra(
            real_conn, usuario_id=empleado, existing=None, accion="conservar_inactivo", candidato_id=None
        )


@pytest.mark.asyncio
async def test_resolver_aprobador_he_conservar_inactivo_actual_reactivado_falla(real_conn):
    empleado = await _crear_usuario(real_conn, email=_email())
    aprobador = await _crear_usuario(real_conn, email=_email(), is_active=True)

    with pytest.raises(ValueError, match="ya no esta inactivo"):
        await _resolver_id_aprobador_horas_extra(
            real_conn,
            usuario_id=empleado,
            existing={"id_aprobador_horas_extra": aprobador},
            accion="conservar_inactivo",
            candidato_id=None,
        )


@pytest.mark.asyncio
async def test_resolver_aprobador_he_conservar_inactivo_ok(real_conn):
    empleado = await _crear_usuario(real_conn, email=_email())
    aprobador = await _crear_usuario(real_conn, email=_email(), is_active=False)

    resultado = await _resolver_id_aprobador_horas_extra(
        real_conn,
        usuario_id=empleado,
        existing={"id_aprobador_horas_extra": aprobador},
        accion="conservar_inactivo",
        candidato_id=None,
    )

    assert resultado == aprobador


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "modo_candidato,match",
    [
        ("ninguno", "Selecciona un usuario"),
        ("propio", "no puede ser el mismo empleado"),
        ("inactivo", "activo con correo"),
        ("sin_correo", "activo con correo"),
    ],
)
async def test_resolver_aprobador_he_asignar_candidato_invalido_falla(real_conn, modo_candidato, match):
    empleado = await _crear_usuario(real_conn, email=_email())
    if modo_candidato == "ninguno":
        candidato_id = None
    elif modo_candidato == "propio":
        candidato_id = empleado
    elif modo_candidato == "inactivo":
        candidato_id = await _crear_usuario(real_conn, email=_email(), is_active=False)
    else:
        candidato_id = await _crear_usuario(real_conn, email="")

    with pytest.raises(ValueError, match=match):
        await _resolver_id_aprobador_horas_extra(
            real_conn, usuario_id=empleado, existing=None, accion="asignar", candidato_id=candidato_id
        )


@pytest.mark.asyncio
async def test_resolver_aprobador_he_asignar_ok(real_conn):
    empleado = await _crear_usuario(real_conn, email=_email())
    candidato = await _crear_usuario(real_conn, email=_email())

    resultado = await _resolver_id_aprobador_horas_extra(
        real_conn, usuario_id=empleado, existing=None, accion="asignar", candidato_id=candidato
    )

    assert resultado == candidato


@pytest.mark.asyncio
async def test_resolver_aprobador_he_accion_invalida_falla(real_conn):
    empleado = await _crear_usuario(real_conn, email=_email())

    with pytest.raises(ValueError, match="Accion .* invalida"):
        await _resolver_id_aprobador_horas_extra(
            real_conn, usuario_id=empleado, existing=None, accion="modo_inventado", candidato_id=None
        )


# ───────────────────────── admin concurrente vs aprobacion en vuelo (2 conexiones) ─────────────────────────


@pytest.mark.asyncio
async def test_revocar_rh_editor_concurrente_bloquea_aprobacion_en_vuelo(two_real_conns):
    """Un admin que revoca el rol RH-editor de un actor mientras ese actor tiene una
    aprobacion HE de tercero en vuelo debe serializar contra ella via lock_he_actor
    (agregado en _lock_y_guardar_fallback_he): la aprobacion no debe poder completarse
    con un permiso ya retirado.
    """
    from modules.admin.service import _lock_y_guardar_fallback_he

    conn_a, conn_b = two_real_conns

    actor_rh_editor = await _crear_usuario(conn_a, email=_email())
    empleado = await _crear_usuario(conn_a, email=_email())
    await _crear_empleado_datos(conn_a, empleado)
    await conn_a.execute(
        "INSERT INTO tb_permisos_modulos (id, usuario_id, modulo_slug, rol_modulo) VALUES (gen_random_uuid(), $1, 'rrhh', 'editor')",
        actor_rh_editor,
    )

    asistencia_id = await _crear_asistencia_diaria(conn_a, empleado, horas_extra_estado="solicitado")

    lock_adquirido = asyncio.Event()
    resultado: dict[str, Exception] = {}

    async def _sera_fallback_false():
        return False

    async def tarea_revocacion():
        async with conn_b.transaction():
            await _lock_y_guardar_fallback_he(
                conn_b, user_id=actor_rh_editor, calcular_sera_fallback_despues=_sera_fallback_false
            )
            lock_adquirido.set()
            await asyncio.sleep(0.3)
            await conn_b.execute(
                "DELETE FROM tb_permisos_modulos WHERE usuario_id = $1 AND modulo_slug = 'rrhh'",
                actor_rh_editor,
            )

    async def tarea_aprobacion():
        await lock_adquirido.wait()
        try:
            await aprobar_horas_extra_svc(
                conn_a,
                asistencia_id=asistencia_id,
                aprobador_id=actor_rh_editor,
                minutos_aprobados=60,
                comentario="intento con bypass RH ya revocado",
            )
        except HEAutorizacionError as exc:
            resultado["error"] = exc

    try:
        await asyncio.gather(tarea_aprobacion(), tarea_revocacion())

        assert isinstance(resultado.get("error"), HEAutorizacionError)

        estado_final = await conn_a.fetchval(
            "SELECT horas_extra_estado FROM tb_asistencia_diaria WHERE id = $1", asistencia_id
        )
        assert estado_final == "solicitado"

        sigue_editor = await conn_a.fetchval(
            "SELECT EXISTS(SELECT 1 FROM tb_permisos_modulos WHERE usuario_id = $1 AND modulo_slug = 'rrhh')",
            actor_rh_editor,
        )
        assert sigue_editor is False
    finally:
        await conn_a.execute(
            "DELETE FROM tb_horas_extra_aprobaciones WHERE asistencia_id = $1", asistencia_id
        )
        await conn_a.execute("DELETE FROM tb_asistencia_diaria WHERE id = $1", asistencia_id)
        await conn_a.execute(
            "DELETE FROM tb_permisos_modulos WHERE usuario_id = $1", actor_rh_editor
        )
        await conn_a.execute("DELETE FROM tb_empleados_datos WHERE usuario_id = $1", empleado)
        await conn_a.execute(
            "DELETE FROM tb_usuarios WHERE id_usuario = ANY($1::uuid[])",
            [empleado, actor_rh_editor],
        )


# ───────────────────────── ruteo de recordatorios del worker (BD real) ─────────────────────────


@pytest.mark.asyncio
async def test_recordatorios_he_query_resuelve_override_activo(real_conn):
    aprobador_exclusivo = await _crear_usuario(real_conn, email=_email())
    jefe_historico = await _crear_usuario(real_conn, email=_email())
    empleado = await _crear_usuario(real_conn, email=_email())
    await _crear_empleado_datos(real_conn, empleado, id_aprobador_horas_extra=aprobador_exclusivo)
    await _crear_jefe(real_conn, empleado, jefe_historico)

    asistencia_id = await real_conn.fetchval(
        """
        INSERT INTO tb_asistencia_diaria (
            usuario_id, fecha_laboral, primera_entrada, ultima_salida,
            minutos_trabajados, minutos_programados, minutos_extra, estado,
            tiene_vacaciones, horas_extra_estado, motivo_solicitud,
            horas_extra_solicitada_at, horas_extra_recordatorios_enviados,
            calculated_at, created_at, updated_at
        )
        VALUES ($1, CURRENT_DATE, now(), now(), 600, 480, 90, 'asistencia',
                false, 'solicitado', 'test ruteo recordatorio', $2, 0,
                now(), now(), now())
        RETURNING id
        """,
        empleado,
        datetime.now(timezone.utc) - timedelta(hours=25),
    )

    svc = get_tasks_db_service()
    rows = await svc.get_horas_extra_recordatorios_pendientes(
        real_conn, primer_delay_horas=24, intervalo_horas=48, max_recordatorios=3
    )
    row = next((r for r in rows if r["id"] == asistencia_id), None)

    assert row is not None
    assert row["tiene_override"] is True
    assert row["override_email"] is not None
    aprobador_email = await real_conn.fetchval(
        "SELECT email FROM tb_usuarios WHERE id_usuario = $1", aprobador_exclusivo
    )
    assert row["override_email"] == aprobador_email
    assert jefe_historico != aprobador_exclusivo


@pytest.mark.asyncio
async def test_recordatorios_he_query_override_inactivo_no_expone_email(real_conn):
    aprobador_inactivo = await _crear_usuario(real_conn, email=_email(), is_active=False)
    empleado = await _crear_usuario(real_conn, email=_email())
    await _crear_empleado_datos(real_conn, empleado, id_aprobador_horas_extra=aprobador_inactivo)

    asistencia_id = await real_conn.fetchval(
        """
        INSERT INTO tb_asistencia_diaria (
            usuario_id, fecha_laboral, primera_entrada, ultima_salida,
            minutos_trabajados, minutos_programados, minutos_extra, estado,
            tiene_vacaciones, horas_extra_estado, motivo_solicitud,
            horas_extra_solicitada_at, horas_extra_recordatorios_enviados,
            calculated_at, created_at, updated_at
        )
        VALUES ($1, CURRENT_DATE, now(), now(), 600, 480, 90, 'asistencia',
                false, 'solicitado', 'test ruteo recordatorio inactivo', $2, 0,
                now(), now(), now())
        RETURNING id
        """,
        empleado,
        datetime.now(timezone.utc) - timedelta(hours=25),
    )

    svc = get_tasks_db_service()
    rows = await svc.get_horas_extra_recordatorios_pendientes(
        real_conn, primer_delay_horas=24, intervalo_horas=48, max_recordatorios=3
    )
    row = next((r for r in rows if r["id"] == asistencia_id), None)

    assert row is not None
    assert row["tiene_override"] is True
    assert row["override_email"] is None


# ───────────────────────── evidencia huerfana en transicion concurrente (2 conexiones) ─────────────────────────


class _FakeUploadFile:
    def __init__(self, filename: str, content_type: str, content: bytes = b"contenido"):
        self.filename = filename
        self.content_type = content_type
        self._content = content

    async def seek(self, _offset):
        return None

    async def read(self):
        return self._content


@pytest.mark.asyncio
async def test_subir_evidencia_no_deja_huerfano_si_pierde_la_carrera(
    two_real_conns, monkeypatch, fake_sharepoint_he_evidencia
):
    """Si otra conexion aprueba/cambia el estado justo mientras se sube evidencia, el
    lock_he_usuario + validacion de rowcount agregados en subir_evidencias_he_y_solicitar_svc
    deben detectar la carrera y limpiar el archivo ya subido a SharePoint -- sin dejarlo huerfano.
    """
    conn_a, conn_b = two_real_conns
    from modules.asistencia.service import subir_evidencias_he_y_solicitar_svc

    empleado = await _crear_usuario(conn_a, email=_email())
    await _crear_empleado_datos(conn_a, empleado)
    asistencia_id = await _crear_asistencia_diaria(conn_a, empleado, horas_extra_estado="pendiente")

    async def fake_get_config(_conn, clave, default, tipo=str):
        return {"SHAREPOINT_BASE_FOLDER": "TestFolder"}.get(clave, default)

    async def fake_get_configs_bulk(_conn, specs):
        overrides = {"HE_EVIDENCIA_MAX_ARCHIVOS": 3, "HE_EVIDENCIA_MAX_MB": 4}
        return {clave: overrides.get(clave, default) for clave, (default, _tipo) in specs.items()}

    monkeypatch.setattr(asistencia_service.ConfigService, "get_global_config", fake_get_config)
    monkeypatch.setattr(asistencia_service.ConfigService, "get_global_configs_bulk", fake_get_configs_bulk)

    lock_adquirido = asyncio.Event()
    resultado: dict[str, Exception] = {}

    async def tarea_aprobacion_gana_la_carrera():
        async with conn_b.transaction():
            await asistencia_db.lock_he_usuario(conn_b, empleado)
            lock_adquirido.set()
            await asyncio.sleep(0.3)
            await conn_b.execute(
                "UPDATE tb_asistencia_diaria SET horas_extra_estado = 'aprobado' WHERE id = $1",
                asistencia_id,
            )

    async def tarea_subir_evidencia():
        await lock_adquirido.wait()
        try:
            await subir_evidencias_he_y_solicitar_svc(
                conn_a,
                asistencia_id=asistencia_id,
                usuario_id=empleado,
                motivo="Intento con carrera perdida",
                empleado_nombre="Empleado Test",
                evidencias=[_FakeUploadFile("evidencia.pdf", "application/pdf")],
            )
        except ValueError as exc:
            resultado["error"] = exc

    try:
        await asyncio.gather(tarea_subir_evidencia(), tarea_aprobacion_gana_la_carrera())

        assert isinstance(resultado.get("error"), ValueError)
        assert len(fake_sharepoint_he_evidencia["subidos"]) == 1
        assert fake_sharepoint_he_evidencia["eliminados"] == fake_sharepoint_he_evidencia["subidos"]

        estado_final = await conn_a.fetchval(
            "SELECT horas_extra_estado FROM tb_asistencia_diaria WHERE id = $1", asistencia_id
        )
        assert estado_final == "aprobado"
        tiene_evidencia = await conn_a.fetchval(
            """
            SELECT EXISTS(
                SELECT 1 FROM tb_documentos_attachments
                WHERE origen_slug = 'he_evidencia' AND metadata->>'id_asistencia' = $1
            )
            """,
            str(asistencia_id),
        )
        assert tiene_evidencia is False
    finally:
        await conn_a.execute(
            "DELETE FROM tb_documentos_attachments WHERE origen_slug = 'he_evidencia' "
            "AND metadata->>'id_asistencia' = $1",
            str(asistencia_id),
        )
        await conn_a.execute("DELETE FROM tb_asistencia_diaria WHERE id = $1", asistencia_id)
        await conn_a.execute("DELETE FROM tb_empleados_datos WHERE usuario_id = $1", empleado)
        await conn_a.execute("DELETE FROM tb_usuarios WHERE id_usuario = $1", empleado)
