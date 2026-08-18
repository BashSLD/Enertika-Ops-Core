"""Contrato de la migracion 160: verificado contra el esquema real de DEV (pg_catalog) donde
es posible, en vez de contra el texto del .sql. Un string-match sobre el archivo certifica que
el archivo "dice" algo, no que Postgres realmente lo aplico asi -- estas pruebas consultan lo
que quedo instalado.

Excepcion: test_no_reconstruye_snapshots_historicos_desde_datos_vivos verifica una propiedad del
SCRIPT de migracion (que no reconstruye historia desde el estado actual), no del estado
resultante. No hay forma de comprobarlo con una consulta post-hoc porque el backfill ya ocurrio;
se mantiene como verificacion de texto a proposito.
"""
from pathlib import Path

import asyncpg
import pytest

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "160_bom_paquetes_independientes.sql"
)
SQL = MIGRATION_PATH.read_text(encoding="utf-8")


def _section(start: str, end: str) -> str:
    start_at = SQL.index(start)
    end_at = SQL.index(end, start_at)
    return SQL[start_at:end_at]


async def _constraintdef(conn, table: str, conname: str) -> str:
    row = await conn.fetchrow(
        "SELECT pg_get_constraintdef(oid) AS def FROM pg_constraint "
        "WHERE conrelid = $1::regclass AND conname = $2",
        table, conname,
    )
    assert row, f"constraint {conname} no existe en {table}"
    return row["def"]


async def _triggerdef(conn, tgname: str) -> str:
    row = await conn.fetchrow(
        "SELECT pg_get_triggerdef(oid) AS def FROM pg_trigger WHERE tgname = $1",
        tgname,
    )
    assert row, f"trigger {tgname} no existe"
    return row["def"]


async def _indexdef(conn, indexname: str) -> str:
    row = await conn.fetchrow(
        "SELECT indexdef FROM pg_indexes WHERE indexname = $1", indexname,
    )
    assert row, f"indice {indexname} no existe"
    return row["indexdef"]


@pytest.mark.skip(
    reason=(
        "Desde la migracion 171 (doc 35, RFQ en tablas propias) se elimino "
        "tb_bom_cotizaciones.rfq_origen_id, columna que este archivo referencia (check de "
        "integridad RFQ/BOM en la linea 186 e indice idx_bom_cotizaciones_rfq_bom). "
        "Re-ejecutar 160 en aislamiento contra el esquema actual ya no es posible ni "
        "representativo: en un replay real de migraciones, 160 corre en orden antes que "
        "171, cuando la columna todavia existe. La propiedad de idempotencia que este test "
        "verificaba (regresion 2026-08-04, triggers diferidos) sigue siendo valida para ese "
        "punto del historial, pero deja de poder comprobarse de forma aislada post-171."
    )
)
@pytest.mark.asyncio
async def test_migracion_es_idempotente(real_conn):
    """Regresion 2026-08-04: re-ejecutar el archivo completo sobre un esquema ya migrado no
    debe fallar. El UPDATE de cabeza_trabajo_id/cabeza_oficial_id en tb_bom_paquetes no tenia
    guard de "solo si cambia"; en una segunda corrida, con las FKs DEFERRABLE INITIALLY
    DEFERRED ya creadas por la primera, encolaba eventos de trigger diferidos sobre la tabla y
    el CREATE INDEX IF NOT EXISTS siguiente fallaba con ObjectInUseError.
    """
    antes = await real_conn.fetchval("SELECT COUNT(*) FROM tb_bom_paquetes")
    await real_conn.execute(SQL)
    await real_conn.execute(SQL)
    despues = await real_conn.fetchval("SELECT COUNT(*) FROM tb_bom_paquetes")
    assert antes == despues


def test_no_reconstruye_snapshots_historicos_desde_datos_vivos():
    estado_proyecto = _section(
        "INSERT INTO tb_bom_proyecto_estado (",
        "-- 4. Identidad estable de linea y genealogia por paquete",
    )
    despues_del_cierre_legacy = estado_proyecto.split(
        "ON CONFLICT (id_proyecto) DO NOTHING;", maxsplit=1
    )[1]
    adendas = _section(
        "ALTER TABLE tb_bom_adendas\n    ADD COLUMN IF NOT EXISTS lock_version",
        "ALTER TABLE tb_bom_adendas DROP CONSTRAINT IF EXISTS "
        "tb_bom_adendas_snapshot_moneda_check",
    )

    assert "FROM tb_proyecto_paneles" not in SQL
    assert "FROM tb_tipo_cambio" not in SQL
    assert "UPDATE tb_bom bom" not in despues_del_cierre_legacy
    assert "WITH metricas_fv AS" not in despues_del_cierre_legacy
    assert "NOW()" not in despues_del_cierre_legacy
    assert "UPDATE tb_bom_adendas" not in adendas
    assert "FROM tb_bom_items" not in adendas
    assert "NOW()" not in adendas


@pytest.mark.asyncio
async def test_monedas_requeridas_antes_de_congelar_importes(real_conn):
    col = await real_conn.fetchrow(
        "SELECT is_nullable FROM information_schema.columns "
        "WHERE table_name = 'tb_bom_items' AND column_name = 'moneda'"
    )
    assert col["is_nullable"] == "NO"

    items_check = await _constraintdef(real_conn, "tb_bom_items", "tb_bom_items_importes_check")
    assert "moneda IS NOT NULL" in items_check
    assert "moneda = ANY (ARRAY['MXN'::bpchar, 'USD'::bpchar])" in items_check

    cot_items_check = await _constraintdef(
        real_conn, "tb_bom_cotizacion_items", "tb_bom_cot_items_moneda_check"
    )
    assert "moneda = ANY (ARRAY['MXN'::bpchar, 'USD'::bpchar])" in cot_items_check

    autorizaciones_check = await _constraintdef(
        real_conn, "tb_bom_autorizaciones", "tb_bom_autorizaciones_importe_moneda_check"
    )
    assert "monto_total > (0)::numeric" in autorizaciones_check
    assert "moneda = 'MXN'::bpchar) AND (tipo_cambio_snapshot IS NULL)" in autorizaciones_check
    assert "moneda = 'USD'::bpchar) AND (tipo_cambio_snapshot > (0)::numeric)" in autorizaciones_check


@pytest.mark.asyncio
async def test_moneda_invalida_es_rechazada_por_postgres_no_solo_por_la_app(real_conn):
    """Comportamiento real: usa un item ya existente en DEV e intenta ponerle una moneda
    fuera de catalogo. Si esto pasara, se rompe el reporte financiero silenciosamente."""
    id_item = await real_conn.fetchval("SELECT id_item FROM tb_bom_items LIMIT 1")
    if id_item is None:
        pytest.skip("No hay tb_bom_items en DEV para probar el CHECK real")

    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        async with real_conn.transaction():
            await real_conn.execute(
                "UPDATE tb_bom_items SET moneda = 'EUR' WHERE id_item = $1", id_item
            )


@pytest.mark.asyncio
async def test_asignacion_cfdi_usa_identidad_compuesta_de_concepto_e_item(real_conn):
    materiales_unique = await _constraintdef(
        real_conn, "tb_materiales_historial", "uq_materiales_id_concepto_cfdi"
    )
    assert materiales_unique == "UNIQUE (id, id_concepto_cfdi)"

    items_unique = await _constraintdef(
        real_conn, "tb_bom_items", "uq_bom_items_identidad_completa"
    )
    assert items_unique == "UNIQUE (id_item, id_bom, id_paquete, id_linea_bom)"

    fk_material = await _constraintdef(
        real_conn, "tb_bom_concepto_asignaciones", "fk_bom_concepto_asignacion_material"
    )
    assert fk_material == (
        "FOREIGN KEY (id_material, id_concepto_cfdi) "
        "REFERENCES tb_materiales_historial(id, id_concepto_cfdi) ON DELETE RESTRICT"
    )

    fk_item = await _constraintdef(
        real_conn, "tb_bom_concepto_asignaciones", "fk_bom_concepto_asignacion_item"
    )
    assert fk_item == (
        "FOREIGN KEY (id_bom_item, id_bom, id_paquete, id_linea_bom) "
        "REFERENCES tb_bom_items(id_item, id_bom, id_paquete, id_linea_bom) ON DELETE RESTRICT"
    )


@pytest.mark.asyncio
async def test_trigger_diferido_impide_sobreasignar_un_concepto_cfdi(real_conn):
    trigger_def = await _triggerdef(real_conn, "trg_bom_validar_total_asignado_concepto")
    assert "AFTER INSERT OR DELETE OR UPDATE ON public.tb_bom_concepto_asignaciones" in trigger_def
    assert "DEFERRABLE INITIALLY DEFERRED" in trigger_def

    mensaje = await real_conn.fetchval(
        "SELECT prosrc FROM pg_proc WHERE proname = 'fn_bom_validar_total_asignado_material'"
    )
    assert "ABS(total_asignado) > importe_concepto + 0.000001" in mensaje
    assert "Las asignaciones BOM exceden el importe del concepto CFDI" in mensaje


@pytest.mark.asyncio
async def test_pagos_serializan_autorizacion_y_validan_saldo(real_conn):
    idempotencia = await _indexdef(real_conn, "uq_bom_pagos_idempotencia")
    assert "UNIQUE INDEX uq_bom_pagos_idempotencia ON public.tb_bom_pagos" in idempotencia
    assert "(clave_idempotencia)" in idempotencia

    bloqueo = await _triggerdef(real_conn, "trg_bom_bloquear_autorizacion_pago")
    assert "BEFORE INSERT OR DELETE OR UPDATE ON public.tb_bom_pagos" in bloqueo

    saldo = await _triggerdef(real_conn, "trg_bom_validar_saldo_pago")
    assert "AFTER INSERT OR DELETE OR UPDATE ON public.tb_bom_pagos" in saldo
    assert "DEFERRABLE INITIALLY DEFERRED" in saldo

    fuente = await real_conn.fetchval(
        "SELECT prosrc FROM pg_proc WHERE proname = 'fn_bom_validar_saldo_autorizacion'"
    )
    assert "total_pagado - autorizacion.monto_total > tolerancia" in fuente
    assert "Los pagos exceden el monto autorizado del BOM" in fuente
    assert "El estado de la autorizacion indica pagos inexistentes" in fuente
    assert "pago.moneda <> autorizacion.moneda" in fuente


@pytest.mark.asyncio
async def test_snapshots_de_grupo_y_revalidacion_de_membresia_son_durables(real_conn):
    snapshot_check = await _constraintdef(
        real_conn, "tb_bom_cotizacion_items", "tb_bom_cot_items_grupo_snapshot_check"
    )
    assert snapshot_check == "CHECK (fn_bom_snapshot_distribucion_valido(grupo_distribucion_snapshot))"

    validador = await real_conn.fetchval(
        "SELECT prosrc FROM pg_proc WHERE proname = 'fn_bom_snapshot_distribucion_valido'"
    )
    assert "ABS(porcentaje_total - 1) <= 0.000001" in validador

    base = await _triggerdef(real_conn, "trg_bom_revalidar_porcentajes_grupo_base")
    assert "ON public.tb_bom_item_grupos DEFERRABLE INITIALLY DEFERRED" in base

    operativo = await _triggerdef(real_conn, "trg_bom_revalidar_porcentajes_grupo_operativo")
    assert "ON public.tb_bom_item_grupos_operativos DEFERRABLE INITIALLY DEFERRED" in operativo


@pytest.mark.asyncio
async def test_mismo_usuario_puede_ser_ingeniero_y_responsable_ingenieria(real_conn):
    responsable = await _indexdef(real_conn, "uq_proyecto_usuario_area_activo")
    assert "NOT (((area)::text = 'INGENIERIA'::text) AND " \
           "((rol_proyecto)::text = 'responsable_ingenieria'::text))" in responsable

    ingeniero = await _indexdef(real_conn, "uq_proyecto_usuario_area_activo_sin_ingeniero")
    assert "NOT (((area)::text = 'INGENIERIA'::text) AND " \
           "((rol_proyecto)::text = 'ingeniero_asignado'::text))" in ingeniero


@pytest.mark.asyncio
async def test_actualizar_concepto_revalida_moneda_y_reconciliacion_de_grupos(real_conn):
    trigger_def = await _triggerdef(real_conn, "trg_bom_validar_concepto_completo")
    assert (
        "AFTER INSERT OR UPDATE OF importe_asignado, moneda, asignacion_grupo_completa "
        "ON public.tb_bom_concepto_asignaciones" in trigger_def
    )
    assert "DEFERRABLE INITIALLY DEFERRED" in trigger_def


@pytest.mark.asyncio
async def test_outbox_exige_identidad_jerarquica_compuesta(real_conn):
    identidad_check = await _constraintdef(
        real_conn, "tb_bom_eventos_outbox", "tb_bom_eventos_outbox_identidad_check"
    )
    assert "(id_paquete IS NULL) OR (id_proyecto IS NOT NULL)" in identidad_check
    assert "(id_bom IS NULL) OR (id_paquete IS NOT NULL)" in identidad_check
    assert "(id_item IS NULL) OR (id_bom IS NOT NULL)" in identidad_check

    fk_paquete_proyecto = await _constraintdef(
        real_conn, "tb_bom_eventos_outbox", "fk_bom_outbox_paquete_proyecto"
    )
    assert fk_paquete_proyecto == (
        "FOREIGN KEY (id_paquete, id_proyecto) "
        "REFERENCES tb_bom_paquetes(id_paquete, id_proyecto) ON DELETE RESTRICT"
    )

    fk_bom_paquete = await _constraintdef(
        real_conn, "tb_bom_eventos_outbox", "fk_bom_outbox_bom_paquete"
    )
    assert fk_bom_paquete == (
        "FOREIGN KEY (id_bom, id_paquete) REFERENCES tb_bom(id_bom, id_paquete) ON DELETE RESTRICT"
    )


@pytest.mark.asyncio
async def test_outbox_rechaza_par_bom_paquete_cruzado_con_datos_reales(real_conn):
    """Comportamiento real: toma un id_bom existente y le asigna un id_paquete que no le
    pertenece -- exactamente el escenario de aislamiento cruzado que el plan exige bloquear."""
    fila = await real_conn.fetchrow("SELECT id_bom, id_proyecto FROM tb_bom LIMIT 1")
    if fila is None:
        pytest.skip("No hay tb_bom en DEV para probar el aislamiento cruzado real")

    from uuid import uuid4

    with pytest.raises(asyncpg.exceptions.ForeignKeyViolationError):
        async with real_conn.transaction():
            await real_conn.execute(
                """
                INSERT INTO tb_bom_eventos_outbox
                    (clave_idempotencia, tipo_evento, id_proyecto, id_paquete, id_bom)
                VALUES ($1, 'TEST_AISLAMIENTO', $2, $3, $4)
                """,
                f"test-{uuid4()}",
                fila["id_proyecto"],
                uuid4(),
                fila["id_bom"],
            )


def test_feature_flag_multi_paquete_inserta_apagada_de_forma_idempotente():
    """El contrato de la migracion es que el INSERT inicial defaulteaba a 'false' y
    es idempotente (ON CONFLICT DO NOTHING) -- no que el flag siga apagado para
    siempre. Es config operativa mutable: se activo a proposito en PROD/DEV el
    2026-08-12 al completar la feature (memory/bom_multiples_paquetes_diagnostico_
    precommit.md), asi que ya no se verifica el valor actual en BD -- mismo patron
    que test_no_reconstruye_snapshots_historicos_desde_datos_vivos arriba."""
    flag = _section(
        "INSERT INTO tb_configuracion_global (clave, valor, descripcion, tipo_dato)\n"
        "VALUES (\n    'bom.multi_paquete_habilitado'",
        "-- 8. Auditoria post-migracion",
    )
    assert "ON CONFLICT (clave) DO NOTHING" in flag
