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

from modules.rrhh.service import _normalizar_dias_horario


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
