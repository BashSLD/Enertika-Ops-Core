"""
Test del dashboard de Direccion (Fase 3 del plan
_Planes_Activos/2026-06-29-aprobaciones-cotizaciones-post-bom.md, seccion ## 16): el service delega
los filtros de estatus/proyecto/proveedor tal cual al metodo de BD, sin logica adicional (la fuente
de verdad de la query vive en core/bom/db_compras.py, ya cubierta por /auditar-sql diff).
"""

from uuid import uuid4

import pytest

from core.bom.service import BomService


class FakeDB:
    def __init__(self):
        self.calls = []

    async def get_cotizacion_aprobaciones_direccion(self, conn, estatus=None, id_proyecto=None,
                                                      nombre_proveedor=None):
        self.calls.append({
            "estatus": estatus, "id_proyecto": id_proyecto, "nombre_proveedor": nombre_proveedor,
        })
        return [{"aprobacion_id": uuid4(), "aprobacion_estatus": estatus or "PENDIENTE_DIRECCION"}]


@pytest.mark.asyncio
async def test_delega_filtros_tal_cual_al_db_service():
    svc = BomService()
    svc.db = FakeDB()

    resultado = await svc.get_cotizacion_aprobaciones_direccion(
        object(), estatus="APROBADA", id_proyecto=uuid4(), nombre_proveedor="Acme",
    )

    assert len(resultado) == 1
    assert svc.db.calls[0]["estatus"] == "APROBADA"
    assert svc.db.calls[0]["nombre_proveedor"] == "Acme"


@pytest.mark.asyncio
async def test_estatus_vacio_no_filtra():
    svc = BomService()
    svc.db = FakeDB()

    await svc.get_cotizacion_aprobaciones_direccion(object())

    assert svc.db.calls[0] == {"estatus": None, "id_proyecto": None, "nombre_proveedor": None}
