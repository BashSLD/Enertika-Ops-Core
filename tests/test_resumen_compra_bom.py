import pytest

from core.bom.service import BomService


class FakeResumenDB:
    async def get_resumen_compra(self, conn, id_bom):
        return [
            {
                "grupo_codigo": "DC",
                "grupo_nombre": "Corriente Directa",
                "grupo_orden": 2,
                "categoria_id": 11,
                "categoria_nombre": "Panel",
                "presupuesto_mxn": 1000,
                "compra_real_mxn": 900,
                "facturado_confirmado_mxn": 700,
                "facturado_sugerido_mxn": 100,
                "pagado_mxn": 500,
                "compra_real_base_mxn": 900,
                "reemplazos_mxn": 0,
                "fuera_scope_mxn": 0,
                "no_adquirido_mxn": 0,
                "valores_pendientes": 0,
                "grupos_pendientes": 0,
            },
            {
                "grupo_codigo": "AC",
                "grupo_nombre": "Corriente Alterna",
                "grupo_orden": 1,
                "categoria_id": 14,
                "categoria_nombre": "Transformador",
                "presupuesto_mxn": 200,
                "compra_real_mxn": 250,
                "facturado_confirmado_mxn": 0,
                "facturado_sugerido_mxn": 50,
                "pagado_mxn": 0,
                "compra_real_base_mxn": 250,
                "reemplazos_mxn": 0,
                "fuera_scope_mxn": 0,
                "no_adquirido_mxn": 0,
                "valores_pendientes": 0,
                "grupos_pendientes": 0,
            },
        ]

    async def get_divisores_bom(self, conn, id_bom):
        return {"modulos_fv": 10, "kwp": 5}


class FakeResumenDesconocidoDB:
    async def get_resumen_compra(self, conn, id_bom):
        return [{
            "grupo_codigo": "PENDIENTE_DISTRIBUCION",
            "grupo_nombre": "Pendiente de distribucion",
            "grupo_orden": 998,
            "categoria_id": 11,
            "categoria_nombre": "Panel",
            "presupuesto_mxn": None,
            "compra_real_mxn": None,
            "compra_real_base_mxn": None,
            "reemplazos_mxn": 0,
            "fuera_scope_mxn": 0,
            "no_adquirido_mxn": 0,
            "facturado_confirmado_mxn": None,
            "facturado_sugerido_mxn": 0,
            "pagado_mxn": None,
            "valores_pendientes": 3,
            "grupos_pendientes": 1,
        }]

    async def get_divisores_bom(self, conn, id_bom):
        return {"modulos_fv": 10, "kwp": 5}


@pytest.mark.asyncio
async def test_resumen_compra_rollup_separa_confirmado_y_sugerido():
    svc = BomService()
    svc.db = FakeResumenDB()

    resumen = await svc.get_resumen_compra(None, "bom-id")

    assert [s["codigo"] for s in resumen["secciones"]] == ["AC", "DC"]
    assert resumen["totales"]["presupuesto"] == 1200
    assert resumen["totales"]["real"] == 1150
    assert resumen["totales"]["dif_real"] == 50
    assert resumen["totales"]["facturado"] == 700
    assert resumen["totales"]["facturado_sugerido"] == 150
    assert resumen["totales"]["pagado"] == 500
    assert resumen["totales"]["reemplazos"] == 0
    assert resumen["totales"]["fuera_scope"] == 0
    assert resumen["totales"]["no_adquirido"] == 0
    assert resumen["metricas"]["facturado_por_modulo"] == 70
    assert resumen["metricas"]["sugerido_por_kwp"] == 30
    assert resumen["reconciliacion_completa"] is True


@pytest.mark.asyncio
async def test_resumen_con_desconocidos_y_grupo_pendiente_no_convierte_a_cero():
    svc = BomService()
    svc.db = FakeResumenDesconocidoDB()

    resumen = await svc.get_resumen_compra(None, "bom-id")

    categoria = resumen["secciones"][0]["categorias"][0]
    assert categoria["presupuesto"] is None
    assert categoria["real"] is None
    assert categoria["facturado"] is None
    assert categoria["pagado"] is None
    assert categoria["reemplazos"] == 0
    assert categoria["grupos_pendientes"] == 1
    assert resumen["totales"]["presupuesto"] is None
    assert resumen["totales"]["dif_facturado"] is None
    assert resumen["metricas"]["presup_por_modulo"] is None
    assert resumen["totales"]["valores_pendientes"] == 3
    assert resumen["totales"]["grupos_pendientes"] == 1
    assert resumen["reconciliacion_completa"] is False


@pytest.mark.asyncio
async def test_set_item_grupos_rechaza_lista_vacia():
    svc = BomService()

    with pytest.raises(ValueError, match="Selecciona al menos un grupo BOM"):
        await svc.set_item_grupos(None, "item-id", "user-id", [])
