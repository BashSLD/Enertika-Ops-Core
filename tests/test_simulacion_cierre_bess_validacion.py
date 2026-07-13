import sys
import types
from uuid import uuid4

import pytest
from fastapi import HTTPException


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

from modules.simulacion.schemas import SimulacionUpdate
from modules.simulacion.service import SimulacionService


STATUS_MAP = {"entregado": 10, "perdido": 11, "cancelado": 12}


def _user_context():
    return {
        "user_db_id": str(uuid4()),
        "role": "ADMIN",
        "module_roles": {"simulacion": "admin"},
    }


def _current_data(id_tecnologia, responsable_id, id_estatus_global_previo=None):
    return {
        "id_oportunidad": uuid4(),
        "id_tecnologia": id_tecnologia,
        "id_estatus_global": id_estatus_global_previo,
        "responsable_simulacion_id": responsable_id,
        "monto_cierre_usd": None,
        "id_interno_simulacion": None,
        "deadline_negociado": None,
    }


def _datos_entregado(responsable_id, potencia=None, bess=None):
    return SimulacionUpdate(
        id_estatus_global=STATUS_MAP["entregado"],
        responsable_simulacion_id=responsable_id,
        potencia_cierre_fv_kwp=potencia,
        capacidad_cierre_bess_kwh=bess,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("id_tecnologia", [2, 3])
async def test_entregado_bess_relacionado_sin_capacidad_rechaza(id_tecnologia):
    service = SimulacionService()
    user_context = _user_context()
    responsable_id = user_context["user_db_id"]
    current_data = _current_data(id_tecnologia, responsable_id)
    datos = _datos_entregado(responsable_id, potencia=10, bess=None)

    with pytest.raises(HTTPException) as exc_info:
        await service._resolve_update_permissions(
            None, current_data, datos, user_context, STATUS_MAP, total_sitios=1
        )

    assert exc_info.value.status_code == 400
    assert "BESS" in exc_info.value.detail


@pytest.mark.asyncio
async def test_entregado_hibrido_con_ambas_capacidades_pasa():
    service = SimulacionService()
    user_context = _user_context()
    responsable_id = user_context["user_db_id"]
    current_data = _current_data(3, responsable_id)
    datos = _datos_entregado(responsable_id, potencia=10, bess=25)

    result = await service._resolve_update_permissions(
        None, current_data, datos, user_context, STATUS_MAP, total_sitios=1
    )

    assert result.capacidad_cierre_bess_kwh == 25


@pytest.mark.asyncio
@pytest.mark.parametrize("id_tecnologia", [2, 3])
async def test_reguardar_ya_entregado_sin_bess_no_bloquea(id_tecnologia):
    """Registro histórico ya Entregado sin capacidad BESS: reguardar otro campo
    (ej. responsable) no debe fallar por un dato que nunca se capturó al cierre."""
    service = SimulacionService()
    user_context = _user_context()
    responsable_id = user_context["user_db_id"]
    current_data = _current_data(
        id_tecnologia, responsable_id, id_estatus_global_previo=STATUS_MAP["entregado"]
    )
    datos = _datos_entregado(responsable_id, potencia=10, bess=None)

    result = await service._resolve_update_permissions(
        None, current_data, datos, user_context, STATUS_MAP, total_sitios=1
    )

    assert result.capacidad_cierre_bess_kwh is None


@pytest.mark.asyncio
async def test_entregado_fv_puro_no_exige_bess():
    service = SimulacionService()
    user_context = _user_context()
    responsable_id = user_context["user_db_id"]
    current_data = _current_data(1, responsable_id)
    datos = _datos_entregado(responsable_id, potencia=10, bess=None)

    result = await service._resolve_update_permissions(
        None, current_data, datos, user_context, STATUS_MAP, total_sitios=1
    )

    assert result.capacidad_cierre_bess_kwh is None
