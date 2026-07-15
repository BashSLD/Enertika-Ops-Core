from datetime import time
import sys
import types

import pytest


def _install_redis_stub() -> None:
    redis_module = types.ModuleType("redis")
    redis_asyncio_module = types.ModuleType("redis.asyncio")
    redis_exceptions_module = types.ModuleType("redis.exceptions")

    class _Redis:
        pass

    class _RedisError(Exception):
        pass

    def _from_url(*_args, **_kwargs):
        return None

    redis_asyncio_module.Redis = _Redis
    redis_asyncio_module.from_url = _from_url
    redis_exceptions_module.RedisError = _RedisError
    redis_module.asyncio = redis_asyncio_module
    redis_module.exceptions = redis_exceptions_module
    sys.modules.setdefault("redis", redis_module)
    sys.modules.setdefault("redis.asyncio", redis_asyncio_module)
    sys.modules.setdefault("redis.exceptions", redis_exceptions_module)


_install_redis_stub()

from modules.asistencia.constants import HE_MINIMO_OPCIONES
from modules.rrhh.service import _coercer_he_minimo, _normalizar_dias_horario, guardar_config_asistencia


def _semana_base():
    return [
        {
            "dia_semana": dia,
            "es_laboral": dia < 5,
            "hora_entrada": "08:00" if dia < 5 else "",
            "hora_salida": "17:00" if dia < 5 else "",
            "descuento_comida_min": 60 if dia < 4 else 0,
            "cruza_medianoche": True,
        }
        for dia in range(7)
    ]


def _normalizar(dias, *, margen_entrada=120, margen_salida=360, comida_default=60):
    return _normalizar_dias_horario(
        dias,
        comida_default,
        margen_entrada_antes_min=margen_entrada,
        margen_salida_despues_min=margen_salida,
    )


def test_cruza_medianoche_se_calcula_automaticamente_para_horario_normal():
    dias = _normalizar(_semana_base())

    assert dias[0]["hora_entrada"] == time(8, 0)
    assert dias[0]["hora_salida"] == time(17, 0)
    assert dias[0]["cruza_medianoche"] is False
    assert dias[0]["descuento_comida_min"] == 60
    assert dias[0]["minutos_programados"] == 480


def test_cruza_medianoche_se_calcula_automaticamente_para_salida_menor():
    raw = _semana_base()
    raw[0]["hora_entrada"] = "22:00"
    raw[0]["hora_salida"] = "06:00"
    raw[1]["es_laboral"] = False

    dias = _normalizar(raw)

    assert dias[0]["cruza_medianoche"] is True
    assert dias[0]["minutos_programados"] == 420


def test_entrada_y_salida_iguales_es_invalido():
    raw = _semana_base()
    raw[0]["hora_entrada"] = "08:00"
    raw[0]["hora_salida"] = "08:00"

    with pytest.raises(ValueError, match="no pueden ser iguales"):
        _normalizar(raw)


def test_dia_no_laboral_limpia_horas_comida_y_cruce():
    raw = _semana_base()
    raw[5]["es_laboral"] = False
    raw[5]["hora_entrada"] = "08:00"
    raw[5]["hora_salida"] = "14:00"
    raw[5]["descuento_comida_min"] = 60
    raw[5]["cruza_medianoche"] = True

    dias = _normalizar(raw)

    assert dias[5]["hora_entrada"] is None
    assert dias[5]["hora_salida"] is None
    assert dias[5]["descuento_comida_min"] == 0
    assert dias[5]["cruza_medianoche"] is False
    assert dias[5]["minutos_programados"] == 0


def test_comida_por_dia_permite_viernes_sin_descuento():
    dias = _normalizar(_semana_base())

    assert dias[3]["descuento_comida_min"] == 60
    assert dias[3]["minutos_programados"] == 480
    assert dias[4]["descuento_comida_min"] == 0
    assert dias[4]["minutos_programados"] == 540


def test_traslape_de_ventanas_consecutivas_es_bloqueante():
    raw = _semana_base()

    with pytest.raises(ValueError, match="se cruza"):
        _normalizar(raw, margen_entrada=120, margen_salida=900)


@pytest.mark.asyncio
@pytest.mark.parametrize("valor", [1, 5, 9, 20, 45, 61, 480])
async def test_guardar_config_asistencia_rechaza_valores_fuera_del_catalogo(valor):
    with pytest.raises(ValueError, match="Minutos minimos invalidos"):
        await guardar_config_asistencia(conn=None, he_minimo_minutos=valor)


@pytest.mark.asyncio
@pytest.mark.parametrize("valor", HE_MINIMO_OPCIONES)
async def test_guardar_config_asistencia_acepta_valores_del_catalogo(monkeypatch, valor):
    guardado = {}

    async def fake_upsert(_conn, minutos):
        guardado["minutos"] = minutos

    import modules.rrhh.service as rrhh_service

    monkeypatch.setattr(rrhh_service.rrhh_db, "upsert_he_minimo_minutos", fake_upsert)

    await guardar_config_asistencia(conn=None, he_minimo_minutos=valor)

    assert guardado["minutos"] == valor


@pytest.mark.parametrize("valor", HE_MINIMO_OPCIONES)
def test_coercer_he_minimo_respeta_valores_del_catalogo(valor):
    assert _coercer_he_minimo(valor) == valor


@pytest.mark.parametrize(
    "valor,esperado",
    [
        (1, 10),
        (9, 10),
        (12, 10),
        (13, 15),
        (20, 15),
        (23, 30),
        (45, 30),
        (46, 60),
        (480, 60),
    ],
)
def test_coercer_he_minimo_ajusta_al_valor_mas_cercano(valor, esperado):
    assert _coercer_he_minimo(valor) == esperado
