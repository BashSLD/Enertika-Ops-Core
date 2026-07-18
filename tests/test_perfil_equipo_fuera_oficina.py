"""
Tests de integracion (BD real, rollback automatico) para el query agregado del
widget "Equipo fuera de oficina" (_Planes_Activos/PLAN_EQUIPO_FUERA_OFICINA.md,
seccion 4), en particular la matriz de resolucion de "responsable visible".
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID, uuid4

import pytest

from modules.perfil import db_service as perfil_db

RANGO_INICIO = date(2030, 1, 1)
RANGO_FIN = date(2030, 1, 31)


async def _usuario(conn, nombre: str, *, is_active: bool = True) -> UUID:
    row = await conn.fetchrow(
        "INSERT INTO tb_usuarios (email, nombre, is_active) "
        "VALUES ($1, $2, $3) RETURNING id_usuario",
        f"{uuid4()}@test.enertika.mx",
        nombre,
        is_active,
    )
    return row["id_usuario"]


async def _jefe(conn, empleado_id: UUID, jefe_id: UUID) -> None:
    await conn.execute(
        "INSERT INTO tb_empleados_jefes (empleado_id, jefe_id) VALUES ($1, $2)",
        empleado_id, jefe_id,
    )


async def _tipo_vacaciones_id(conn) -> UUID:
    return await conn.fetchval(
        "SELECT id FROM tb_cat_tipos_ausencia WHERE slug = 'vacaciones'"
    )


async def _solicitud_aprobada(
    conn, usuario_id: UUID, tipo_id: UUID, fecha_inicio: date, fecha_fin: date,
    *, estado: str = "aprobado",
) -> None:
    await conn.execute(
        """
        INSERT INTO tb_solicitudes_ausencia
            (usuario_id, tipo_ausencia_id, fecha_inicio, fecha_fin,
             dias_solicitados, fecha_presentarse, estado)
        VALUES ($1, $2, $3, $4, 1, $5, $6)
        """,
        usuario_id, tipo_id, fecha_inicio, fecha_fin, fecha_fin + timedelta(days=1), estado,
    )


async def _compensatorio_aprobado(conn, usuario_id: UUID, fecha_descanso: date) -> None:
    await conn.execute(
        """
        INSERT INTO tb_he_solicitudes_compensatorio
            (usuario_id, fecha_descanso, minutos_solicitados, motivo, estatus)
        VALUES ($1, $2, 120, 'motivo libre que no debe exponerse', 'aprobado')
        """,
        usuario_id, fecha_descanso,
    )


def _responsables_por_usuario(eventos: list[dict]) -> dict[UUID, list[str]]:
    return {e["usuario_id"]: e["responsables_nombres"] for e in eventos}


@pytest.mark.asyncio
async def test_un_jefe_activo(real_conn):
    tipo_id = await _tipo_vacaciones_id(real_conn)
    jefe = await _usuario(real_conn, "Jefe Unico")
    empleado = await _usuario(real_conn, "Empleado A")
    await _jefe(real_conn, empleado, jefe)
    await _solicitud_aprobada(real_conn, empleado, tipo_id, RANGO_INICIO, RANGO_INICIO)

    eventos = await perfil_db.get_equipo_fuera_oficina(real_conn, RANGO_INICIO, RANGO_FIN)
    mapa = _responsables_por_usuario(eventos)

    assert mapa[empleado] == ["Jefe Unico"]


@pytest.mark.asyncio
async def test_jefe_mas_cercano_en_jerarquia(real_conn):
    """A y B son ambos jefes directos del empleado; B reporta a A -> se conserva B
    (el mas cercano), se excluye A."""
    tipo_id = await _tipo_vacaciones_id(real_conn)
    jefe_a = await _usuario(real_conn, "Jefe A Lejano")
    jefe_b = await _usuario(real_conn, "Jefe B Cercano")
    empleado = await _usuario(real_conn, "Empleado B")
    await _jefe(real_conn, empleado, jefe_a)
    await _jefe(real_conn, empleado, jefe_b)
    await _jefe(real_conn, jefe_b, jefe_a)  # B reporta a A
    await _solicitud_aprobada(real_conn, empleado, tipo_id, RANGO_INICIO, RANGO_INICIO)

    eventos = await perfil_db.get_equipo_fuera_oficina(real_conn, RANGO_INICIO, RANGO_FIN)
    mapa = _responsables_por_usuario(eventos)

    assert mapa[empleado] == ["Jefe B Cercano"]


@pytest.mark.asyncio
async def test_jefes_paralelos_se_conservan_ambos(real_conn):
    tipo_id = await _tipo_vacaciones_id(real_conn)
    jefe_1 = await _usuario(real_conn, "Paralelo Uno")
    jefe_2 = await _usuario(real_conn, "Paralelo Dos")
    empleado = await _usuario(real_conn, "Empleado C")
    await _jefe(real_conn, empleado, jefe_1)
    await _jefe(real_conn, empleado, jefe_2)
    await _solicitud_aprobada(real_conn, empleado, tipo_id, RANGO_INICIO, RANGO_INICIO)

    eventos = await perfil_db.get_equipo_fuera_oficina(real_conn, RANGO_INICIO, RANGO_FIN)
    mapa = _responsables_por_usuario(eventos)

    assert mapa[empleado] == ["Paralelo Dos", "Paralelo Uno"]


@pytest.mark.asyncio
async def test_empate_de_nombres_orden_por_id(real_conn):
    tipo_id = await _tipo_vacaciones_id(real_conn)
    jefe_1 = await _usuario(real_conn, "Nombre Empatado")
    jefe_2 = await _usuario(real_conn, "Nombre Empatado")
    empleado = await _usuario(real_conn, "Empleado D")
    await _jefe(real_conn, empleado, jefe_1)
    await _jefe(real_conn, empleado, jefe_2)
    await _solicitud_aprobada(real_conn, empleado, tipo_id, RANGO_INICIO, RANGO_INICIO)

    eventos = await perfil_db.get_equipo_fuera_oficina(real_conn, RANGO_INICIO, RANGO_FIN)
    mapa = _responsables_por_usuario(eventos)

    assert mapa[empleado] == ["Nombre Empatado", "Nombre Empatado"]
    esperado_orden = sorted([jefe_1, jefe_2])
    ids_row = await real_conn.fetch(
        "SELECT jefe_id FROM tb_empleados_jefes WHERE empleado_id = $1 ORDER BY jefe_id",
        empleado,
    )
    assert [r["jefe_id"] for r in ids_row] == esperado_orden


@pytest.mark.asyncio
async def test_jefe_inactivo_no_es_candidato(real_conn):
    tipo_id = await _tipo_vacaciones_id(real_conn)
    jefe_inactivo = await _usuario(real_conn, "Jefe Inactivo", is_active=False)
    empleado = await _usuario(real_conn, "Empleado E")
    await _jefe(real_conn, empleado, jefe_inactivo)
    await _solicitud_aprobada(real_conn, empleado, tipo_id, RANGO_INICIO, RANGO_INICIO)

    eventos = await perfil_db.get_equipo_fuera_oficina(real_conn, RANGO_INICIO, RANGO_FIN)
    mapa = _responsables_por_usuario(eventos)

    assert mapa[empleado] == []


@pytest.mark.asyncio
async def test_ningun_jefe_asignado(real_conn):
    tipo_id = await _tipo_vacaciones_id(real_conn)
    empleado = await _usuario(real_conn, "Empleado F Sin Jefe")
    await _solicitud_aprobada(real_conn, empleado, tipo_id, RANGO_INICIO, RANGO_INICIO)

    eventos = await perfil_db.get_equipo_fuera_oficina(real_conn, RANGO_INICIO, RANGO_FIN)
    mapa = _responsables_por_usuario(eventos)

    assert mapa[empleado] == []


@pytest.mark.asyncio
async def test_autoreferencia_se_ignora(real_conn):
    tipo_id = await _tipo_vacaciones_id(real_conn)
    empleado = await _usuario(real_conn, "Empleado G Autoreferencia")
    await _jefe(real_conn, empleado, empleado)
    await _solicitud_aprobada(real_conn, empleado, tipo_id, RANGO_INICIO, RANGO_INICIO)

    eventos = await perfil_db.get_equipo_fuera_oficina(real_conn, RANGO_INICIO, RANGO_FIN)
    mapa = _responsables_por_usuario(eventos)

    assert mapa[empleado] == []


@pytest.mark.asyncio
async def test_ciclo_no_poda_candidatos(real_conn):
    """A y B son jefes directos del empleado; ademas A reporta a B y B reporta a A
    (ciclo). No debe recursionar infinitamente y no debe podar ningun candidato."""
    tipo_id = await _tipo_vacaciones_id(real_conn)
    jefe_a = await _usuario(real_conn, "Ciclo A")
    jefe_b = await _usuario(real_conn, "Ciclo B")
    empleado = await _usuario(real_conn, "Empleado H")
    await _jefe(real_conn, empleado, jefe_a)
    await _jefe(real_conn, empleado, jefe_b)
    await _jefe(real_conn, jefe_a, jefe_b)
    await _jefe(real_conn, jefe_b, jefe_a)
    await _solicitud_aprobada(real_conn, empleado, tipo_id, RANGO_INICIO, RANGO_INICIO)

    eventos = await perfil_db.get_equipo_fuera_oficina(real_conn, RANGO_INICIO, RANGO_FIN)
    mapa = _responsables_por_usuario(eventos)

    assert mapa[empleado] == ["Ciclo A", "Ciclo B"]


@pytest.mark.asyncio
async def test_compensatorio_incluido_con_texto_fijo_sin_motivo(real_conn):
    jefe = await _usuario(real_conn, "Jefe Compensatorio")
    empleado = await _usuario(real_conn, "Empleado I")
    await _jefe(real_conn, empleado, jefe)
    await _compensatorio_aprobado(real_conn, empleado, RANGO_INICIO)

    eventos = await perfil_db.get_equipo_fuera_oficina(real_conn, RANGO_INICIO, RANGO_FIN)
    evento = next(e for e in eventos if e["usuario_id"] == empleado)

    assert evento["origen"] == "compensatorio"
    assert evento["tipo_nombre"] == "Permiso con goce de sueldo"
    assert evento["fecha_inicio"] == RANGO_INICIO
    assert "motivo" not in evento
    assert evento["responsables_nombres"] == ["Jefe Compensatorio"]


@pytest.mark.asyncio
async def test_excluye_usuario_inactivo_pendiente_y_solapamiento_fuera_de_rango(real_conn):
    tipo_id = await _tipo_vacaciones_id(real_conn)

    # Usuario inactivo: no debe aparecer aunque tenga solicitud aprobada en rango.
    inactivo = await _usuario(real_conn, "Empleado Inactivo", is_active=False)
    await _solicitud_aprobada(real_conn, inactivo, tipo_id, RANGO_INICIO, RANGO_INICIO)

    # Solicitud pendiente (no aprobada): no debe aparecer.
    pendiente_usr = await _usuario(real_conn, "Empleado Pendiente")
    await _solicitud_aprobada(
        real_conn, pendiente_usr, tipo_id, RANGO_INICIO, RANGO_INICIO, estado="pendiente"
    )

    # Solicitud aprobada pero completamente fuera del rango consultado.
    fuera_rango_usr = await _usuario(real_conn, "Empleado Fuera De Rango")
    await _solicitud_aprobada(
        real_conn, fuera_rango_usr, tipo_id,
        RANGO_FIN + timedelta(days=10), RANGO_FIN + timedelta(days=11),
    )

    eventos = await perfil_db.get_equipo_fuera_oficina(real_conn, RANGO_INICIO, RANGO_FIN)
    usuarios_presentes = {e["usuario_id"] for e in eventos}

    assert inactivo not in usuarios_presentes
    assert pendiente_usr not in usuarios_presentes
    assert fuera_rango_usr not in usuarios_presentes
