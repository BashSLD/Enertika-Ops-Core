"""
Integracion: easter egg de niveles de bolsa HE (Fase 8 del plan
_Planes_Activos/Planes_Anteriores_Ejecutados/2026-06-29-bolsa-horas-extra.md). Requiere BD real con la migracion
139 aplicada (tb_cat_he_niveles, tb_he_bolsa_movimientos). Cada test
corre dentro de una transaccion que se revierte al terminar.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
import pytest_asyncio

from modules.asistencia import db_service as db

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest_asyncio.fixture
async def usuario_id(real_conn):
    uid = await real_conn.fetchval(
        "SELECT id_usuario FROM tb_usuarios WHERE is_active = true LIMIT 1"
    )
    if not uid:
        pytest.skip("No hay usuarios activos en la BD")
    return uid


async def _credito_he(real_conn, usuario_id, *, horas, fecha_referencia, con_aprobacion=True):
    """Inserta un CREDITO de `horas` en la bolsa. Si con_aprobacion=True, crea
    tambien la asistencia y la aprobacion reales que exige el FK de
    aprobacion_id (solo asi cuenta para el nivel); si es False, el credito
    queda sin aprobacion_id (saldo inicial / ajuste manual, no cuenta)."""
    aprobacion_id = None
    if con_aprobacion:
        asistencia_id = uuid4()
        await real_conn.execute(
            """
            INSERT INTO tb_asistencia_diaria (
                id, usuario_id, fecha_laboral, minutos_trabajados, minutos_programados,
                minutos_extra, estado, horas_extra_estado
            ) VALUES ($1, $2, $3, 480, 480, $4, 'asistencia', 'aprobado')
            """,
            asistencia_id,
            usuario_id,
            fecha_referencia,
            horas * 60,
        )
        aprobacion_id = uuid4()
        await real_conn.execute(
            """
            INSERT INTO tb_horas_extra_aprobaciones (
                id, asistencia_id, aprobador_id, minutos_aprobados, comentario
            ) VALUES ($1, $2, $3, $4, 'Test aprobacion')
            """,
            aprobacion_id,
            asistencia_id,
            usuario_id,
            horas * 60,
        )
    await real_conn.execute(
        """
        INSERT INTO tb_he_bolsa_movimientos (
            id, usuario_id, tipo, minutos, concepto, fecha_referencia, aprobacion_id
        ) VALUES ($1, $2, 'CREDITO', $3, 'Test HE aprobada', $4, $5)
        """,
        uuid4(),
        usuario_id,
        horas * 60,
        fecha_referencia,
        aprobacion_id,
    )


async def test_nivel_sin_horas_no_participa(real_conn, usuario_id):
    nivel = await db.get_he_nivel_usuario(real_conn, usuario_id, 2026)
    assert nivel is None


async def test_nivel_justo_debajo_del_umbral_se_queda_en_nivel_anterior(real_conn, usuario_id):
    await _credito_he(real_conn, usuario_id, horas=48, fecha_referencia=date(2026, 3, 1))

    nivel = await db.get_he_nivel_usuario(real_conn, usuario_id, 2026)

    assert nivel["nivel"] == 1
    assert nivel["nombre"] == "Chispa"
    assert nivel["horas_actuales"] == 48
    assert nivel["horas_faltantes"] == 1
    assert nivel["es_maximo"] is False


async def test_nivel_justo_en_el_umbral_sube_de_nivel(real_conn, usuario_id):
    await _credito_he(real_conn, usuario_id, horas=49, fecha_referencia=date(2026, 3, 1))

    nivel = await db.get_he_nivel_usuario(real_conn, usuario_id, 2026)

    assert nivel["nivel"] == 2
    assert nivel["nombre"] == "Voltio"
    assert nivel["horas_actuales"] == 49
    assert nivel["horas_faltantes"] == 48


@pytest.mark.parametrize(
    "horas_totales, nivel_esperado, nombre_esperado",
    [
        (96, 2, "Voltio"),
        (97, 3, "Amperio"),
        (144, 3, "Amperio"),
        (145, 4, "Vatio"),
        (192, 4, "Vatio"),
        (193, 5, "Kilowatt"),
        (240, 5, "Kilowatt"),
    ],
)
async def test_nivel_en_cada_limite_de_umbral(
    real_conn, usuario_id, horas_totales, nivel_esperado, nombre_esperado
):
    await _credito_he(real_conn, usuario_id, horas=horas_totales, fecha_referencia=date(2026, 3, 1))

    nivel = await db.get_he_nivel_usuario(real_conn, usuario_id, 2026)

    assert nivel["nivel"] == nivel_esperado
    assert nivel["nombre"] == nombre_esperado


async def test_nivel_maximo_megawatt(real_conn, usuario_id):
    await _credito_he(real_conn, usuario_id, horas=241, fecha_referencia=date(2026, 3, 1))

    nivel = await db.get_he_nivel_usuario(real_conn, usuario_id, 2026)

    assert nivel["nivel"] == 6
    assert nivel["nombre"] == "Megawatt"
    assert nivel["horas_faltantes"] == 0
    assert nivel["es_maximo"] is True


async def test_nivel_ignora_creditos_sin_aprobacion_saldo_inicial_o_ajuste_manual(real_conn, usuario_id):
    await _credito_he(
        real_conn, usuario_id, horas=300, fecha_referencia=date(2026, 3, 1), con_aprobacion=False
    )

    nivel = await db.get_he_nivel_usuario(real_conn, usuario_id, 2026)

    assert nivel is None


async def test_nivel_reset_anual_diciembre_no_cuenta_para_anio_nuevo(real_conn, usuario_id):
    await _credito_he(real_conn, usuario_id, horas=200, fecha_referencia=date(2025, 12, 30))

    nivel_2025 = await db.get_he_nivel_usuario(real_conn, usuario_id, 2025)
    nivel_2026 = await db.get_he_nivel_usuario(real_conn, usuario_id, 2026)

    assert nivel_2025 is not None
    assert nivel_2025["nivel"] == 5
    assert nivel_2026 is None


async def test_niveles_equipo_excluye_usuarios_con_cero_horas(real_conn, usuario_id):
    otro_id = await real_conn.fetchval(
        "SELECT id_usuario FROM tb_usuarios WHERE is_active = true AND id_usuario <> $1 LIMIT 1",
        usuario_id,
    )
    if not otro_id:
        pytest.skip("Se requieren al menos 2 usuarios activos en la BD")

    await _credito_he(real_conn, usuario_id, horas=60, fecha_referencia=date(2026, 3, 1))

    niveles = await db.get_he_niveles_equipo(real_conn, [usuario_id, otro_id], 2026)

    ids = {row["usuario_id"] for row in niveles}
    assert usuario_id in ids
    assert otro_id not in ids
