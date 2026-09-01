"""
Tests del indicador de pendientes de BOM en proyectos/ui
(_Planes_Activos/2026-08-31-plan-indicador-pendientes-proyectos-ui.md, puntos 3 y 6):
- GET /proyectos/ui y GET /proyectos/partials/proyectos deben calcular el mismo
  conteo para el mismo proyecto (riesgo: aparece en la carga inicial y
  desaparece al filtrar/refrescar via HTMX).
- Un error de BD en el batch-fetch no debe tumbar la pagina ni mostrar el
  indicador con datos falsos: 200, sin indicador, error logueado.
"""
from datetime import datetime
from uuid import uuid4

import asyncpg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.proyectos.router import router
from modules.proyectos.service import ProyectosService, get_service
from core.bom.service import get_bom_service
from core.database import get_db_connection
from core.security import get_current_user_context


class FakeBomService:
    def __init__(self, conteos=None, lanzar_error=False):
        self.conteos = conteos or {}
        self.lanzar_error = lanzar_error
        self.calls = []

    async def get_conteo_pendientes_por_proyecto(self, conn, proyecto_ids):
        self.calls.append(list(proyecto_ids))
        if self.lanzar_error:
            raise asyncpg.PostgresError("fallo simulado de BD")
        return self.conteos


def _fake_proyectos_service(proyectos):
    service = ProyectosService()

    async def _get_proyectos(conn, area_filter=None, status_filter=None, q=None, limit=50):
        return [dict(p) for p in proyectos]

    async def _get_kpis(conn):
        return {"total_proyectos": len(proyectos), "por_area": {}}

    service.get_proyectos = _get_proyectos
    service.get_kpis = _get_kpis
    return service


def _admin_context():
    return {
        "email": "admin@example.com",
        "user_name": "Test Admin",
        "role": "ADMIN",
        "rol_organizacional": None,
        "module_roles": {"proyectos": "admin"},
        "user_db_id": uuid4(),
    }


def _module_context(*module_slugs):
    return {
        "email": "user@example.com",
        "user_name": "Test User",
        "role": "USER",
        "rol_organizacional": None,
        "module_roles": {"proyectos": "viewer", **{slug: "viewer" for slug in module_slugs}},
        "user_db_id": uuid4(),
    }


def _build_client(service, bom_service, context):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user_context] = lambda: context
    app.dependency_overrides[get_db_connection] = lambda: object()
    app.dependency_overrides[get_service] = lambda: service
    app.dependency_overrides[get_bom_service] = lambda: bom_service
    return TestClient(app)


def test_conteo_pendientes_simetrico_entre_ui_y_partial():
    proyecto_id = uuid4()
    proyectos = [{
        "id_proyecto": proyecto_id, "nombre_proyecto": "Proyecto Test",
        "nombre_corto": "Test", "proyecto_id_estandar": "MX-1-FV",
        "area_actual": "CONSTRUCCION", "cliente_nombre": "Cliente Test",
        "sharepoint_url": None, "created_at": datetime.now(), "dias_en_area": 0,
    }]
    bom_service = FakeBomService(
        conteos={proyecto_id: {"compras_obra": 2, "cotizaciones_direccion": 1}}
    )
    service = _fake_proyectos_service(proyectos)
    client = _build_client(service, bom_service, _admin_context())

    resp_ui = client.get("/proyectos/ui")
    resp_partial = client.get("/proyectos/partials/proyectos")

    assert resp_ui.status_code == 200
    assert resp_partial.status_code == 200
    assert bom_service.calls == [[proyecto_id], [proyecto_id]]
    marcador = 'text-[10px] font-bold">3<'
    assert marcador in resp_ui.text
    assert marcador in resp_partial.text


def test_error_bd_en_conteo_no_tumba_la_pagina_ni_muestra_indicador(caplog):
    proyecto_id = uuid4()
    proyectos = [{
        "id_proyecto": proyecto_id, "nombre_proyecto": "Proyecto Test",
        "nombre_corto": "Test", "proyecto_id_estandar": "MX-1-FV",
        "area_actual": "CONSTRUCCION", "cliente_nombre": "Cliente Test",
        "sharepoint_url": None, "created_at": datetime.now(), "dias_en_area": 0,
    }]
    bom_service = FakeBomService(lanzar_error=True)
    service = _fake_proyectos_service(proyectos)
    client = _build_client(service, bom_service, _admin_context())

    with caplog.at_level("ERROR"):
        response = client.get("/proyectos/ui")

    assert response.status_code == 200
    assert 'text-[10px] font-bold"' not in response.text
    assert any("pendientes" in r.message.lower() for r in caplog.records)


def test_ingenieria_no_ve_el_indicador():
    """Ingenieria tiene acceso de lectura a /bom/direccion/cotizaciones y al
    paquete de Compras (MODULOS_PAQUETE_COMPRAS) por ser quien origina el BOM,
    pero no participa en aprobar cotizaciones/autorizaciones -- ese indicador
    puntual usa el set mas estricto MODULOS_INDICADOR_PENDIENTES_PROYECTO, que
    la excluye a peticion del usuario 2026-09-02."""
    proyecto_id = uuid4()
    proyectos = [{
        "id_proyecto": proyecto_id, "nombre_proyecto": "Proyecto Test",
        "nombre_corto": "Test", "proyecto_id_estandar": "MX-1-FV",
        "area_actual": "CONSTRUCCION", "cliente_nombre": "Cliente Test",
        "sharepoint_url": None, "created_at": datetime.now(), "dias_en_area": 0,
    }]
    bom_service = FakeBomService(
        conteos={proyecto_id: {"compras_obra": 2, "cotizaciones_direccion": 1}}
    )
    service = _fake_proyectos_service(proyectos)
    client = _build_client(service, bom_service, _module_context("ingenieria"))

    response = client.get("/proyectos/ui")

    assert response.status_code == 200
    assert 'text-[10px] font-bold"' not in response.text
    assert bom_service.calls == []


def test_construccion_si_ve_el_indicador():
    proyecto_id = uuid4()
    proyectos = [{
        "id_proyecto": proyecto_id, "nombre_proyecto": "Proyecto Test",
        "nombre_corto": "Test", "proyecto_id_estandar": "MX-1-FV",
        "area_actual": "CONSTRUCCION", "cliente_nombre": "Cliente Test",
        "sharepoint_url": None, "created_at": datetime.now(), "dias_en_area": 0,
    }]
    bom_service = FakeBomService(
        conteos={proyecto_id: {"compras_obra": 2, "cotizaciones_direccion": 1}}
    )
    service = _fake_proyectos_service(proyectos)
    client = _build_client(service, bom_service, _module_context("construccion"))

    response = client.get("/proyectos/ui")

    assert response.status_code == 200
    assert 'text-[10px] font-bold">3<' in response.text
