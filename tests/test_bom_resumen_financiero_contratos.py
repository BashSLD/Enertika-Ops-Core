"""Contratos SQL y de snapshots para el resumen financiero multi-BOM.

La mayoria de las pruebas de este archivo usan CaptureConn (verifican la forma del
SQL generado, sin ejecutarlo) o Fake*DB (logica pura de servicio: prorrateo,
propagacion de None, seleccion de snapshot vs. vivo -- no tocan SQL). Eso es
correcto para lo que prueban. Lo que NUNCA se ejecuto contra Postgres real es el
SQL mas complejo del diff (CTEs anidados, JSONB_TO_RECORDSET, prorrateo ponderado
por grupo, locking CAS de ejecucion) -- la seccion final agrega pruebas con
real_conn que corren esas consultas contra datos legacy reales en DEV.
"""

from decimal import Decimal
from datetime import date
from uuid import uuid4

import pytest

from core.bom.db_service import BomDBService
from core.bom.service import BomService
from modules.finanzas.db_service import FinanzasDBService
from modules.finanzas.service import FinanzasService


class CaptureConn:
    def __init__(self, *, rows=None, row=None):
        self.rows = list(rows or [])
        self.row = row
        self.fetch_calls = []
        self.fetchrow_calls = []
        self.executemany_calls = []

    async def fetch(self, query, *args):
        self.fetch_calls.append((query, args))
        return self.rows

    async def fetchrow(self, query, *args):
        self.fetchrow_calls.append((query, args))
        return self.row

    async def executemany(self, query, args):
        self.executemany_calls.append((query, args))


@pytest.mark.asyncio
async def test_cotizacion_congela_grupos_efectivos_sin_fallback_ambiguo():
    conn = CaptureConn()

    await BomDBService().agregar_items_cotizacion(
        conn,
        uuid4(),
        uuid4(),
        [{
            "bom_item_id": uuid4(),
            "precio_unitario": Decimal("10"),
            "cantidad": Decimal("2"),
            "moneda": "MXN",
            "subtotal_linea": Decimal("20"),
        }],
    )

    sql = " ".join(conn.executemany_calls[0][0].split())
    assert "FROM tb_bom_item_grupos_operativos operativo" in sql
    assert "AND NOT EXISTS" in sql
    assert "CASE WHEN COUNT(*) = 1" in sql
    assert "grupos.distribucion_unica" in sql


@pytest.mark.asyncio
async def test_sql_resumen_usa_distribuciones_hechos_nc_y_pagos_parciales():
    conn = CaptureConn()

    await BomDBService().get_resumen_compra(conn, uuid4())

    sql = " ".join(conn.fetch_calls[0][0].split())
    assert "COALESCE(pago.tipo_cambio_usado, 1)" not in sql
    assert "pago.tipo_cambio_usado IS NOT NULL" in sql
    assert "tb_bom_item_grupo_asignaciones asignacion" in sql
    assert "asignacion.porcentaje AS peso_grupo" in sql
    assert "tb_bom_hecho_grupo_asignaciones hecho" in sql
    assert "hecho.importe_asignado" in sql
    assert "WHEN factura.es_nota_credito THEN -ABS(material.importe)" in sql
    assert "SUM(CASE WHEN pago.moneda = 'MXN' THEN pago.monto_pagado" in sql
    assert (
        "SUM(pago.importe * linea.subtotal_linea / total.subtotal "
        "* linea.peso_grupo)" in sql
    )
    assert "linea.grupo_distribucion_snapshot" in sql
    assert "JSONB_TO_RECORDSET" in sql
    assert "linea.subtotal_linea IS NULL" in sql
    assert "total.subtotal IS NULL" in sql
    assert "/ COUNT(" not in sql

    consolidado_conn = CaptureConn()
    await BomDBService().get_consolidado_lineas(
        consolidado_conn, uuid4(), "CURSO"
    )
    consolidado_sql = " ".join(consolidado_conn.fetch_calls[0][0].split())
    assert "facturas_grupo_filas AS" in consolidado_sql
    assert (
        "asignacion.importe_asignado - COALESCE(SUM(grupo.importe_asignado), 0)"
        in consolidado_sql
    )
    assert "asignacion.asignacion_grupo_completa = FALSE" in consolidado_sql


@pytest.mark.asyncio
async def test_sql_resumen_facturacion_parcial_conserva_hechos_y_solo_suma_residual():
    conn = CaptureConn()

    await BomDBService().get_resumen_compra(conn, uuid4())

    sql = " ".join(conn.fetch_calls[0][0].split())
    residual = (
        "asignacion.importe_asignado "
        "- COALESCE(SUM(hecho.importe_asignado), 0)"
    )
    assert "hecho.importe_asignado, hecho.moneda" in sql
    assert "asignacion.asignacion_grupo_completa = TRUE" not in sql
    assert "asignacion.asignacion_grupo_completa = FALSE" in sql
    assert residual in sql
    assert f"HAVING ABS( {residual} ) > 0.000001" in sql
    assert f"{residual}, asignacion.moneda" in sql


@pytest.mark.asyncio
async def test_sql_ejecucion_exige_lock_cero_para_insert_inicial():
    conn = CaptureConn(row=None)

    await BomDBService().upsert_item_ejecucion(
        conn,
        uuid4(),
        lock_version_esperado=4,
        estatus_ejecucion="PAGADO",
    )

    sql = " ".join(conn.fetchrow_calls[0][0].split())
    assert "WHERE $4 = 0 OR EXISTS" in sql
    assert "WHERE tb_bom_item_ejecucion.lock_version = $4" in sql


@pytest.mark.asyncio
async def test_locks_bom_respetan_orden_paquete_antes_de_version():
    db = BomDBService()
    conn = CaptureConn(row=None)

    await db.get_bom_for_update(conn, uuid4())
    await db.incrementar_lock_bom_cas(conn, uuid4(), 3, "BORRADOR")
    await db.update_bom_estatus_cas(
        conn, uuid4(), "BORRADOR", 3, "EN_REVISION_ING"
    )

    lock_sql = " ".join(conn.fetchrow_calls[0][0].split())
    incrementar_sql = " ".join(conn.fetchrow_calls[1][0].split())
    transicion_sql = " ".join(conn.fetchrow_calls[2][0].split())
    assert "WITH paquete AS MATERIALIZED" in lock_sql
    assert lock_sql.index("FOR UPDATE OF p") < lock_sql.index("FOR UPDATE OF b")
    for sql in (incrementar_sql, transicion_sql):
        assert "WITH paquete AS MATERIALIZED" in sql
        assert "p.cabeza_trabajo_id = $1" in sql
        assert "FOR UPDATE OF p" in sql
        assert "FROM paquete" in sql


@pytest.mark.asyncio
async def test_kpis_finanzas_no_duplica_autorizaciones_y_usa_fecha_mexico():
    conn = CaptureConn(row={
        "pendientes_pago": 1,
        "pagados_30d": 2,
        "monto_pagado_mes_mxn": Decimal("10"),
    })

    await FinanzasDBService().get_kpis(conn)

    sql = " ".join(conn.fetchrow_calls[0][0].split())
    assert "COUNT(DISTINCT a.id) FILTER" in sql
    assert "NOW() AT TIME ZONE 'America/Mexico_City'" in sql
    assert "CURRENT_DATE" not in sql


class FakeTransactionConn:
    def transaction(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeFinanzasPagoDB:
    def __init__(self, autorizacion):
        self.autorizacion = autorizacion
        self.comprobantes = []

    async def get_autorizacion_para_pago_for_update(self, conn, autorizacion_id):
        return self.autorizacion

    async def get_pago_por_clave_idempotencia(self, conn, clave):
        return None

    async def crear_pago_db(self, conn, **campos):
        return {"id": uuid4(), **campos}

    async def actualizar_estatus_autorizacion(
        self, conn, autorizacion_id, estatus, lock_version, nuevo_estatus,
    ):
        return {"id": autorizacion_id, "estatus": nuevo_estatus}

    async def crear_comprobante_bom(self, conn, **campos):
        self.comprobantes.append(campos)


@pytest.mark.asyncio
async def test_pago_completo_actualiza_ejecucion_con_lock_exacto(monkeypatch):
    autorizacion_id = uuid4()
    cotizacion_id = uuid4()
    item_id = uuid4()
    usuario_id = uuid4()
    aut = {
        "id": autorizacion_id,
        "estatus": "AUTORIZADO_FINANZAS",
        "lock_version": 3,
        "moneda": "MXN",
        "monto_total": Decimal("100"),
        "monto_pagado_acumulado": Decimal("0"),
        "cotizacion_id": cotizacion_id,
        "proyecto_id": uuid4(),
        "id_paquete": uuid4(),
        "bom_id": uuid4(),
        "bom_version": 2,
        "paquete_codigo": "P-01",
        "nombre_proveedor": "Proveedor",
        "proveedor_id": uuid4(),
    }
    bom_calls = {"estatus": [], "ejecucion": [], "outbox": []}

    class FakeBomDB:
        async def get_items_cotizacion(self, conn, id_cotizacion):
            return [{"bom_item_id": item_id}]

        async def lock_items_context_by_ids(self, conn, item_ids):
            return [{
                "id_item": item_id,
                "estatus_compra": "AUTORIZADO",
                "ejecucion_lock_version": 7,
            }]

        async def actualizar_estatus_compra_items(self, conn, item_ids, estatus):
            bom_calls["estatus"].append((item_ids, estatus))

        async def upsert_item_ejecucion(
            self, conn, id_item, updated_by=None,
            lock_version_esperado=None, **campos,
        ):
            bom_calls["ejecucion"].append(
                (id_item, updated_by, lock_version_esperado, campos)
            )
            return {"id_item": id_item, "lock_version": 8}

        async def registrar_evento_outbox(self, conn, *args, **kwargs):
            bom_calls["outbox"].append((args, kwargs))

    monkeypatch.setattr("modules.finanzas.service.BomDBService", FakeBomDB)
    svc = FinanzasService(FakeFinanzasPagoDB(aut))

    resultado = await svc.registrar_pago(
        FakeTransactionConn(),
        autorizacion_id,
        Decimal("100"),
        "MXN",
        None,
        date(2026, 8, 3),
        None,
        usuario_id,
        3,
        "pago-idempotente",
    )

    assert resultado["estatus_autorizacion"] == "PAGADO"
    assert bom_calls["estatus"] == [([item_id], "PAGADO")]
    assert bom_calls["ejecucion"] == [(
        item_id,
        usuario_id,
        7,
        {"estatus_ejecucion": "PAGADO"},
    )]
    assert len(bom_calls["outbox"]) == 1


@pytest.mark.asyncio
async def test_divisores_bom_lee_snapshots_exactos_sin_fallback_vivo():
    id_bom = uuid4()
    conn = CaptureConn(row={
        "kwp": Decimal("109.440000"),
        "modulos_fv": 171,
    })

    divisores = await BomDBService().get_divisores_bom(conn, id_bom)

    assert divisores == {"kwp": 109.44, "modulos_fv": 171.0}
    sql, args = conn.fetchrow_calls[0]
    assert "potencia_pico_kwp_snapshot AS kwp" in sql
    assert "modulos_fv_snapshot AS modulos_fv" in sql
    assert "tb_proyecto_paneles" not in sql
    assert "tb_cat_paneles_fv" not in sql
    assert args == (id_bom,)


@pytest.mark.asyncio
async def test_divisores_bom_propaga_snapshots_desconocidos_como_none():
    conn = CaptureConn(row={"kwp": None, "modulos_fv": None})

    divisores = await BomDBService().get_divisores_bom(conn, uuid4())

    assert divisores == {"kwp": None, "modulos_fv": None}


class FakeResumenNoneDB:
    async def get_resumen_compra(self, conn, id_bom):
        return [{
            "grupo_codigo": "DC",
            "grupo_nombre": "Corriente Directa",
            "grupo_orden": 1,
            "categoria_id": 11,
            "categoria_nombre": "Panel",
            "presupuesto_mxn": None,
            "compra_real_mxn": None,
            "compra_real_base_mxn": None,
            "reemplazos_mxn": None,
            "fuera_scope_mxn": None,
            "no_adquirido_mxn": None,
            "facturado_confirmado_mxn": None,
            "facturado_sugerido_mxn": None,
            "pagado_mxn": None,
            "valores_pendientes": 3,
            "grupos_pendientes": 1,
        }]

    async def get_divisores_bom(self, conn, id_bom):
        return {"modulos_fv": None, "kwp": None}


@pytest.mark.asyncio
async def test_service_propaga_montos_y_divisores_none():
    svc = BomService()
    svc.db = FakeResumenNoneDB()

    resumen = await svc.get_resumen_compra(None, uuid4())

    categoria = resumen["secciones"][0]["categorias"][0]
    campos_none = (
        "presupuesto",
        "real",
        "real_base",
        "reemplazos",
        "fuera_scope",
        "no_adquirido",
        "facturado",
        "facturado_sugerido",
        "pagado",
        "dif_real",
        "dif_facturado",
        "dif_pagado",
    )
    assert all(categoria[campo] is None for campo in campos_none)
    assert resumen["totales"]["presupuesto"] is None
    assert resumen["totales"]["pagado"] is None
    assert resumen["metricas"]["modulos_fv"] is None
    assert resumen["metricas"]["kwp"] is None
    assert resumen["metricas"]["presup_por_modulo"] is None
    assert resumen["metricas"]["presup_por_kwp"] is None
    assert resumen["reconciliacion_completa"] is False


class FakeConsolidadoOficialDB:
    def __init__(self, lineas=None):
        self.consulto_metricas_vivas = False
        self.lineas = list(lineas or [])

    async def get_proyecto_info(self, conn, id_proyecto):
        return {"id_proyecto": id_proyecto}

    async def get_consolidado_paquetes(self, conn, id_proyecto, modo):
        assert modo == "OFICIAL"
        return [{
            "presupuesto_mxn": Decimal("109440"),
            "presupuesto_usd": Decimal("0"),
            "presupuesto_total_mxn": Decimal("109440"),
            "cotizado_mxn": Decimal("0"),
            "cotizado_usd": Decimal("0"),
            "autorizado_mxn": Decimal("0"),
            "autorizado_usd": Decimal("0"),
            "autorizado_total_mxn": Decimal("0"),
            "facturado_mxn": Decimal("0"),
            "facturado_usd": Decimal("0"),
            "facturado_total_mxn": Decimal("0"),
            "pagado_mxn": Decimal("0"),
            "pagado_usd": Decimal("0"),
            "pagado_total_mxn": Decimal("0"),
        }]

    async def get_consolidado_lineas(self, conn, id_proyecto, modo):
        return self.lineas

    async def listar_paquetes_proyecto(self, conn, id_proyecto):
        return []

    async def get_estado_proyecto(self, conn, id_proyecto):
        return {"captura_cerrada": True}

    async def get_tipo_cambio_vigente(self, conn):
        return {"tasa_mxn": Decimal("99")}

    async def get_divisor_oficial_consolidado(self, conn, id_proyecto):
        return {
            "modulos_fv_snapshot": 171,
            "potencia_pico_kwp_snapshot": Decimal("109.440000"),
            "captura_cerrada": True,
        }

    async def get_metricas_paneles_proyecto(self, conn, id_proyecto):
        self.consulto_metricas_vivas = True
        return {"modulos_fv": 999, "potencia_pico_kwp": Decimal("999")}


@pytest.mark.asyncio
async def test_consolidado_oficial_usa_snapshot_y_no_paneles_vivos():
    db = FakeConsolidadoOficialDB()
    svc = BomService()
    svc.db = db

    consolidado = await svc.get_consolidado_proyecto(None, uuid4(), "OFICIAL")

    assert consolidado["divisor_fv"]["modulos_fv"] == 171
    assert consolidado["divisor_fv"]["potencia_pico_kwp"] == Decimal("109.440000")
    assert consolidado["totales"]["mxn_por_modulo"] == Decimal("640")
    assert consolidado["totales"]["mxn_por_kwp"] == Decimal("1000")
    assert db.consulto_metricas_vivas is False


@pytest.mark.asyncio
async def test_consolidado_prorratea_linea_multigrupo_sin_duplicar_importe():
    db = FakeConsolidadoOficialDB(lineas=[{
        "paquete_codigo": "AC-01",
        "grupos": ["AC", "DC"],
        "distribucion_grupos": {
            "AC": Decimal("0.60"),
            "DC": Decimal("0.40"),
        },
        "costo_estimado": Decimal("1000"),
        "moneda": "MXN",
        "facturado_por_grupo": {},
        "posible_solapamiento": False,
    }])
    svc = BomService()
    svc.db = db

    consolidado = await svc.get_consolidado_proyecto(None, uuid4(), "OFICIAL")

    grupos = {grupo["codigo"]: grupo for grupo in consolidado["desglose_grupos"]}
    assert grupos["AC"]["presupuesto_mxn"] == Decimal("600.00")
    assert grupos["DC"]["presupuesto_mxn"] == Decimal("400.00")
    assert sum(
        grupo["presupuesto_mxn"] for grupo in grupos.values()
    ) == Decimal("1000")


# ─────────────────────────────────────────────────────────────────────────────
# SQL real contra DEV (datos legacy existentes: 2 BOM, 20 items, 2 paquetes)
#
# Las pruebas de arriba con CaptureConn verifican la FORMA del SQL, nunca lo
# ejecutan. Estas corren el SQL real mas complejo del diff -- el que mas
# riesgo tiene de columnas/tipos/joins rotos tras la migracion 160 -- contra
# Postgres real, para atrapar justo la clase de bug que CaptureConn no puede
# ver (ya aparecio 3 veces en este mismo cierre: idempotencia de migracion,
# jsonb/dict, AmbiguousParameterError).
# ─────────────────────────────────────────────────────────────────────────────


async def _bom_legacy_con_items(conn):
    row = await conn.fetchrow(
        """
        SELECT b.id_bom, b.id_proyecto
        FROM tb_bom b
        JOIN tb_bom_items i ON i.id_bom = b.id_bom AND i.activo
        GROUP BY b.id_bom, b.id_proyecto
        LIMIT 1
        """
    )
    if row is None:
        pytest.skip("No hay un BOM legacy real con items en DEV")
    return row


@pytest.mark.asyncio
async def test_get_resumen_compra_ejecuta_contra_datos_legacy_reales(real_conn):
    fila = await _bom_legacy_con_items(real_conn)

    resumen = await BomDBService().get_resumen_compra(real_conn, fila["id_bom"])

    assert isinstance(resumen, list)
    if resumen:
        assert "grupo_codigo" in resumen[0]
        assert "presupuesto_mxn" in resumen[0]


@pytest.mark.asyncio
async def test_get_consolidado_lineas_ejecuta_contra_datos_legacy_reales(real_conn):
    fila = await _bom_legacy_con_items(real_conn)

    lineas = await BomDBService().get_consolidado_lineas(
        real_conn, fila["id_proyecto"], "CURSO"
    )

    assert isinstance(lineas, list)


@pytest.mark.asyncio
async def test_get_divisores_bom_ejecuta_contra_datos_legacy_reales(real_conn):
    fila = await _bom_legacy_con_items(real_conn)

    divisores = await BomDBService().get_divisores_bom(real_conn, fila["id_bom"])

    assert set(divisores) == {"kwp", "modulos_fv"}


@pytest.mark.asyncio
async def test_upsert_item_ejecucion_respeta_lock_contra_dato_legacy_real(real_conn):
    fila_bom = await _bom_legacy_con_items(real_conn)
    id_item = await real_conn.fetchval(
        "SELECT id_item FROM tb_bom_items WHERE id_bom = $1 AND activo LIMIT 1",
        fila_bom["id_bom"],
    )
    lock_actual = await real_conn.fetchval(
        "SELECT lock_version FROM tb_bom_item_ejecucion WHERE id_item = $1",
        id_item,
    )
    lock_esperado = lock_actual if lock_actual is not None else 0

    resultado = await BomDBService().upsert_item_ejecucion(
        real_conn, id_item,
        lock_version_esperado=lock_esperado,
        comentarios_operativos="prueba real_conn D7 (auto-rollback)",
    )

    assert resultado is not None
    assert resultado["comentarios_operativos"] == "prueba real_conn D7 (auto-rollback)"

    rechazado = await BomDBService().upsert_item_ejecucion(
        real_conn, id_item,
        lock_version_esperado=lock_esperado,
        comentarios_operativos="no debe aplicarse",
    )
    assert rechazado is None
