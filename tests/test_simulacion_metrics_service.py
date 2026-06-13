import sys
import types
from datetime import date
from uuid import uuid4

import pytest


redis_module = types.ModuleType("redis")
redis_asyncio_module = types.ModuleType("redis.asyncio")
redis_exceptions_module = types.ModuleType("redis.exceptions")


class RedisError(Exception):
    pass


class Redis:
    pass


redis_asyncio_module.Redis = Redis
redis_asyncio_module.from_url = lambda *args, **kwargs: None
redis_exceptions_module.RedisError = RedisError
redis_module.asyncio = redis_asyncio_module
redis_module.exceptions = redis_exceptions_module

sys.modules.setdefault("redis", redis_module)
sys.modules.setdefault("redis.asyncio", redis_asyncio_module)
sys.modules.setdefault("redis.exceptions", redis_exceptions_module)

from modules.simulacion.metrics_db_service import MetricsDBService


class FakeConn:
    def __init__(self, row):
        self.row = row
        self.query = None
        self.args = None

    async def fetchrow(self, query, *args):
        self.query = query
        self.args = args
        return self.row


async def fake_get_global_config(conn, clave, default, tipo=str):
    values = {
        "DESCONTAR_TIEMPO_REVISION_SLA": True,
        "UMBRAL_LAG_NOTIFICACION": 1440,
        "VENTANA_BLOQUE_REGISTRO_MIN": 2,
        "VENTANA_RAFAGA_USUARIO_MIN": 10,
        "UMBRAL_RAFAGA_USUARIO_OPS": 10,
    }
    return values.get(clave, default)


async def fake_get_global_configs_bulk(conn, specs):
    values = {
        "UMBRAL_LAG_NOTIFICACION": 1440,
        "VENTANA_BLOQUE_REGISTRO_MIN": 2,
        "VENTANA_RAFAGA_USUARIO_MIN": 10,
        "UMBRAL_RAFAGA_USUARIO_OPS": 10,
    }
    return {k: values.get(k, spec[0]) for k, spec in specs.items()}


@pytest.mark.asyncio
async def test_get_comparativo_sla_ajustado_calcula_resumen(monkeypatch):
    monkeypatch.setattr(
        "modules.simulacion.metrics_db_service.ConfigService.get_global_config",
        fake_get_global_config,
    )
    conn = FakeConn(
        {
            "total_oportunidades": 3,
            "dias_actuales_promedio": 5.5,
            "dias_ajustados_promedio": 4.0,
            "dias_revision_promedio": 1.5,
        }
    )
    user_id = uuid4()

    resultado = await MetricsDBService().get_comparativo_sla_ajustado(
        conn,
        date(2026, 1, 1),
        date(2026, 1, 31),
        user_id=user_id,
        tipo_solicitud_id=8,
    )

    assert resultado.total_oportunidades == 3
    assert resultado.tiempo_actual_promedio_dias == 5.5
    assert resultado.tiempo_ajustado_promedio_dias == 4.0
    assert resultado.tiempo_revision_descontado_dias == 1.5
    assert resultado.reduccion_promedio_dias == 1.5
    assert resultado.reduccion_pct == 27.3
    assert resultado.descuento_sla_activo is True
    assert conn.args == (date(2026, 1, 1), date(2026, 1, 31), user_id, 8)
    assert "o.responsable_simulacion_id = $3" in conn.query
    assert "o.id_tipo_solicitud = $4" in conn.query


@pytest.mark.asyncio
async def test_get_calidad_registro_calcula_resumen(monkeypatch):
    monkeypatch.setattr(
        "modules.simulacion.metrics_db_service.ConfigService.get_global_configs_bulk",
        fake_get_global_configs_bulk,
    )
    conn = FakeConn(
        {
            "total_transiciones": 10,
            "transiciones_a_tiempo": 7,
            "transiciones_tarde": 3,
            "transiciones_sin_usuario": 1,
            "lag_promedio_min": 180,
            "lag_p95_min": 1500,
            "oportunidades_en_bloque": 2,
            "rafagas_usuario": 1,
            "max_oportunidades_por_rafaga": 12,
        }
    )
    user_id = uuid4()

    resultado = await MetricsDBService().get_calidad_registro(
        conn,
        date(2026, 2, 1),
        date(2026, 2, 28),
        user_id=user_id,
        tipo_solicitud_id=4,
    )

    assert resultado.total_transiciones == 10
    assert resultado.pct_registrado_a_tiempo == 70.0
    assert resultado.lag_promedio_horas == 3.0
    assert resultado.lag_p95_horas == 25.0
    assert resultado.transiciones_tarde == 3
    assert resultado.oportunidades_en_bloque == 2
    assert resultado.rafagas_usuario == 1
    assert resultado.max_oportunidades_por_rafaga == 12
    assert resultado.transiciones_sin_usuario == 1
    assert resultado.umbral_lag_horas == 24.0
    assert resultado.ventana_bloque_min == 2
    assert resultado.ventana_rafaga_min == 10
    assert resultado.umbral_rafaga_usuario == 10
    assert conn.args == (date(2026, 2, 1), date(2026, 2, 28), 1440, 2, 10, 10, user_id, 4)
    assert "o.responsable_simulacion_id = $7" in conn.query
    assert "o.id_tipo_solicitud = $8" in conn.query
