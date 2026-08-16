"""
Fase 5 (_Planes_Activos/2026-08-14-actualizacion-precios-compras-bom.md): cobertura
nueva para las Fases 2-4 -- ninguna tenia tests antes de este archivo.

- Query "Actualizacion de precios" (Fase 2) vs get_proyectos_con_bom (Fase 2, nunca
  testeada tampoco): "Activos" excluye BORRADOR, la nueva SI lo incluye.
- CAS a nivel de item de actualizar_precios_items_compras_cas_batch (Fase 3): dos
  conexiones reales compitiendo por el mismo lock_version, solo una gana; una
  obsoleta se rechaza.
- MaterialsService.crear_interno (Fase 4, sin cobertura hoy): alta + que la busqueda
  de homologacion (buscar_internos_similares) encuentre el material recien creado.
"""
import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest

from core.bom.db_service import BomDBService
from core.bom.service import BomService
from modules.compras.db_service import ComprasDBService
from core.materials.service import MaterialsService


async def _bom_borrador_con_item_sin_costo(conn):
    """Reusa una fila real de DEV (mismo patron que _bom_cabeza_trabajo_activo en
    tests/test_bom_htmx_cas_router.py) -- no se construye desde cero por las mismas
    razones documentadas ahi (tb_proyectos_gate exige id_oportunidad NOT NULL)."""
    row = await conn.fetchrow("""
        SELECT b.id_bom, i.id_item, i.lock_version AS item_lock_version,
               i.precio_unitario, i.moneda
        FROM tb_bom b
        JOIN tb_bom_paquetes p ON p.id_paquete = b.id_paquete
        JOIN tb_bom_items i ON i.id_bom = b.id_bom
        WHERE p.cabeza_trabajo_id = b.id_bom AND p.estado_paquete = 'ACTIVO'
          AND b.estatus = 'BORRADOR'
          AND i.activo = TRUE
          AND COALESCE(i.tipo_origen_item, 'BASE') = 'BASE'
          AND (i.precio_unitario IS NULL OR i.precio_unitario <= 0)
        LIMIT 1
    """)
    if row is None:
        pytest.skip("No hay un BOM en BORRADOR con items sin costo real en DEV")
    return row


async def _bom_borrador_item_manual_sin_costo(conn):
    """Item BASE sin costo Y sin material vinculado -- entrada manual real de DEV,
    el caso que 6.1 (doc 42) resuelve."""
    row = await conn.fetchrow("""
        SELECT b.id_bom, i.id_item, i.lock_version AS item_lock_version,
               i.precio_unitario, i.moneda, i.descripcion
        FROM tb_bom b
        JOIN tb_bom_paquetes p ON p.id_paquete = b.id_paquete
        JOIN tb_bom_items i ON i.id_bom = b.id_bom
        WHERE p.cabeza_trabajo_id = b.id_bom AND p.estado_paquete = 'ACTIVO'
          AND b.estatus = 'BORRADOR'
          AND i.activo = TRUE
          AND COALESCE(i.tipo_origen_item, 'BASE') = 'BASE'
          AND (i.precio_unitario IS NULL OR i.precio_unitario <= 0)
          AND i.id_material_interno IS NULL
        LIMIT 1
    """)
    if row is None:
        pytest.skip("No hay un item de entrada manual sin costo real en DEV")
    return row


async def _usuario_id(conn):
    row = await conn.fetchval(
        "SELECT id_usuario FROM tb_usuarios WHERE is_active = true LIMIT 1"
    )
    if row is None:
        pytest.skip("No hay un usuario activo real en DEV")
    return row


async def _bom_activo_para_compras(conn):
    row = await conn.fetchrow("""
        SELECT b.id_bom
        FROM tb_bom b
        JOIN tb_bom_paquetes p ON p.id_paquete = b.id_paquete
        WHERE p.cabeza_trabajo_id = b.id_bom AND p.estado_paquete = 'ACTIVO'
          AND b.estatus IN ('APROBADO_CONST', 'EN_REVISION_FINAL', 'APROBADO_FINAL')
        LIMIT 1
    """)
    if row is None:
        pytest.skip("No hay un BOM APROBADO_CONST+ real en DEV")
    return row


# ─────────────────────────────────────────────────────────────────────────────
# Fase 2: query "Actualizacion de precios" vs get_proyectos_con_bom ("Activos")
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_activos_excluye_borrador_y_pendientes_lo_incluye(real_conn):
    borrador = await _bom_borrador_con_item_sin_costo(real_conn)
    activo = await _bom_activo_para_compras(real_conn)

    db = ComprasDBService()
    activos = await db.get_proyectos_con_bom(real_conn)
    pendientes = await db.get_proyectos_bom_pendientes_precio(real_conn)

    ids_activos = {p["id_bom"] for p in activos}
    ids_pendientes = {p["id_bom"] for p in pendientes}

    assert activo["id_bom"] in ids_activos
    assert activo["id_bom"] not in ids_pendientes
    assert borrador["id_bom"] in ids_pendientes
    assert borrador["id_bom"] not in ids_activos


@pytest.mark.asyncio
async def test_pendientes_precio_reporta_total_pendientes_mayor_a_cero(real_conn):
    borrador = await _bom_borrador_con_item_sin_costo(real_conn)

    db = ComprasDBService()
    pendientes = await db.get_proyectos_bom_pendientes_precio(real_conn)
    fila = next(p for p in pendientes if p["id_bom"] == borrador["id_bom"])

    assert fila["total_pendientes"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Fase 3: CAS a nivel de item (actualizar_precios_items_compras_cas_batch)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cas_item_concurrente_solo_deja_ganar_a_una_conexion(two_real_conns):
    """Dos conexiones reales compiten por el mismo lock_version_esperado del mismo
    item: solo una debe ganar (RETURNING no vacio), la otra debe perder (lista vacia) --
    no ambas, no ninguna, sin deadlock."""
    conn_a, conn_b = two_real_conns
    fila = await _bom_borrador_con_item_sin_costo(conn_a)
    id_item = fila["id_item"]
    lock_original = fila["item_lock_version"]

    db = BomDBService()
    try:
        resultado_a, resultado_b = await asyncio.gather(
            db.actualizar_precios_items_compras_cas_batch(
                conn_a, [(id_item, Decimal("100.00"), "MXN", lock_original, None)]
            ),
            db.actualizar_precios_items_compras_cas_batch(
                conn_b, [(id_item, Decimal("200.00"), "MXN", lock_original, None)]
            ),
        )

        ganadores = [r for r in (resultado_a, resultado_b) if r]
        perdedores = [r for r in (resultado_a, resultado_b) if not r]
        assert len(ganadores) == 1, "exactamente una conexion debe ganar la carrera del CAS"
        assert len(perdedores) == 1
    finally:
        await conn_a.execute(
            "UPDATE tb_bom_items SET precio_unitario = $1, moneda = $2, lock_version = $3 "
            "WHERE id_item = $4",
            fila["precio_unitario"], fila["moneda"], lock_original, id_item,
        )


@pytest.mark.asyncio
async def test_cas_item_rechaza_lock_version_obsoleto_tras_commit_ajeno(two_real_conns):
    """Escenario 'dos modales de Compras abiertos sobre el mismo item': el primero en
    guardar avanza lock_version; el segundo, con el lock_version viejo cargado, debe
    ser rechazado en vez de pisar el precio ya guardado."""
    conn_a, conn_b = two_real_conns
    fila = await _bom_borrador_con_item_sin_costo(conn_a)
    id_item = fila["id_item"]
    lock_original = fila["item_lock_version"]

    db = BomDBService()
    try:
        primero = await db.actualizar_precios_items_compras_cas_batch(
            conn_a, [(id_item, Decimal("150.00"), "MXN", lock_original, None)]
        )
        assert primero == [id_item]

        segundo = await db.actualizar_precios_items_compras_cas_batch(
            conn_b, [(id_item, Decimal("999.00"), "USD", lock_original, None)]
        )
        assert segundo == [], "el lock_version obsoleto debe ser rechazado, no aplicado"
    finally:
        await conn_a.execute(
            "UPDATE tb_bom_items SET precio_unitario = $1, moneda = $2, lock_version = $3 "
            "WHERE id_item = $4",
            fila["precio_unitario"], fila["moneda"], lock_original, id_item,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Fase 4: MaterialsService.crear_interno (sin cobertura hoy) + homologacion
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_crear_interno_y_homologacion_encuentra_el_material_creado(real_conn):
    """crear_interno no tenia ningun test; de paso valida el flujo que motiva la Fase
    4: tras dar de alta un material, buscar_internos_similares con una descripcion
    parecida debe encontrarlo (esa es la señal de homologacion que ve el usuario)."""
    marca_unica = f"TESTFASE4-{uuid4().hex[:8]}"
    service = MaterialsService()

    creado = await service.crear_interno(real_conn, {
        "descripcion_canonica": f"Abrazadera galvanizada {marca_unica}",
        "id_unidad_medida": None,
        "id_categoria": None,
        "clave_prod_serv": None,
        "precio_referencia": 12.50,
        "notas": None,
        "material": None, "tipo": None, "acabado": None,
        "marca": None, "adicional": None, "medida": None,
        "moneda": "MXN",
        "creado_por": None,
        "actualizado_por": None,
    })

    assert creado["descripcion_canonica"] == f"Abrazadera galvanizada {marca_unica}"

    similares = await service.buscar_internos_similares(
        real_conn, f"Abrazadera galvanizada {marca_unica}"
    )

    assert any(r["id"] == creado["id"] for r in similares)


# ─────────────────────────────────────────────────────────────────────────────
# Fase 6.1 (doc 42): crear/vincular material interno desde item de entrada manual
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_crear_catalogo_crea_material_y_lo_enlaza_al_item_manual(real_conn):
    """doc 42 (BOM 6.1): Compras marca 'crear_catalogo' sobre un item de entrada
    manual sin material vinculado -- debe crear tb_cat_materiales y enlazar
    id_material_interno del item en la MISMA pasada que confirma el precio."""
    fila = await _bom_borrador_item_manual_sin_costo(real_conn)
    id_item = fila["id_item"]
    user_id = await _usuario_id(real_conn)

    marca_unica = f"TEST6.1-{uuid4().hex[:8]}"
    descripcion_temporal = f"Material de prueba {marca_unica}"
    await real_conn.execute(
        "UPDATE tb_bom_items SET descripcion = $1 WHERE id_item = $2",
        descripcion_temporal, id_item,
    )

    service = BomService()
    resultado = await service.resolver_costos_pendientes_compras(
        real_conn, fila["id_bom"], user_id,
        [{
            "id_item": id_item, "precio_unitario": Decimal("55.00"), "moneda": "MXN",
            "lock_version": fila["item_lock_version"], "actualizar_catalogo": False,
            "crear_catalogo": True, "id_material_vinculado": None,
        }],
    )
    assert id_item in resultado["aplicados"], resultado["rechazados"]

    fila_post = await real_conn.fetchrow(
        "SELECT id_material_interno FROM tb_bom_items WHERE id_item = $1", id_item
    )
    assert fila_post["id_material_interno"] is not None

    material = await real_conn.fetchrow(
        "SELECT descripcion_canonica FROM tb_cat_materiales WHERE id = $1",
        fila_post["id_material_interno"],
    )
    assert material["descripcion_canonica"] == descripcion_temporal


@pytest.mark.asyncio
async def test_id_material_vinculado_enlaza_existente_sin_crear_uno_nuevo(real_conn):
    """Cuando Compras da clic en una sugerencia de homologacion (id_material_vinculado
    ya resuelto), el item debe enlazarse al material EXISTENTE -- no crear un
    duplicado, aunque crear_catalogo tambien venga en true (precedencia del
    vinculo sobre la creacion, ver resolver_costos_pendientes_compras)."""
    fila = await _bom_borrador_item_manual_sin_costo(real_conn)
    id_item = fila["id_item"]
    user_id = await _usuario_id(real_conn)

    material = await real_conn.fetchrow(
        "SELECT id FROM tb_cat_materiales WHERE activo = TRUE LIMIT 1"
    )
    if material is None:
        pytest.skip("No hay materiales activos en el catalogo interno de DEV")

    total_antes = await real_conn.fetchval("SELECT COUNT(*) FROM tb_cat_materiales")

    service = BomService()
    resultado = await service.resolver_costos_pendientes_compras(
        real_conn, fila["id_bom"], user_id,
        [{
            "id_item": id_item, "precio_unitario": Decimal("30.00"), "moneda": "MXN",
            "lock_version": fila["item_lock_version"], "actualizar_catalogo": False,
            "crear_catalogo": True, "id_material_vinculado": material["id"],
        }],
    )
    assert id_item in resultado["aplicados"], resultado["rechazados"]

    fila_post = await real_conn.fetchrow(
        "SELECT id_material_interno FROM tb_bom_items WHERE id_item = $1", id_item
    )
    assert fila_post["id_material_interno"] == material["id"]

    total_despues = await real_conn.fetchval("SELECT COUNT(*) FROM tb_cat_materiales")
    assert total_despues == total_antes


@pytest.mark.asyncio
async def test_crear_catalogo_rechaza_si_ya_existe_similar_en_catalogo(real_conn):
    """Anti-duplicado (threshold 0.9): si la homologacion encuentra un material casi
    identico, crear_catalogo debe rechazarse -- ni crea el material ni aplica el
    precio -- en vez de crear un duplicado silencioso."""
    fila = await _bom_borrador_item_manual_sin_costo(real_conn)
    id_item = fila["id_item"]
    user_id = await _usuario_id(real_conn)

    marca_unica = f"TEST6.1DUP-{uuid4().hex[:8]}"
    descripcion_temporal = f"Material duplicado de prueba {marca_unica}"
    materials_service = MaterialsService()
    await materials_service.crear_interno(real_conn, {
        "descripcion_canonica": descripcion_temporal,
        "id_unidad_medida": None, "id_categoria": None, "clave_prod_serv": None,
        "precio_referencia": None, "notas": None,
        "material": None, "tipo": None, "acabado": None,
        "marca": None, "adicional": None, "medida": None,
        "moneda": "MXN", "creado_por": None, "actualizado_por": None,
    })
    await real_conn.execute(
        "UPDATE tb_bom_items SET descripcion = $1 WHERE id_item = $2",
        descripcion_temporal, id_item,
    )

    service = BomService()
    resultado = await service.resolver_costos_pendientes_compras(
        real_conn, fila["id_bom"], user_id,
        [{
            "id_item": id_item, "precio_unitario": Decimal("55.00"), "moneda": "MXN",
            "lock_version": fila["item_lock_version"], "actualizar_catalogo": False,
            "crear_catalogo": True, "id_material_vinculado": None,
        }],
    )
    assert id_item not in resultado["aplicados"]
    assert any(r["id_item"] == id_item for r in resultado["rechazados"])

    fila_post = await real_conn.fetchrow(
        "SELECT id_material_interno, precio_unitario FROM tb_bom_items WHERE id_item = $1",
        id_item,
    )
    assert fila_post["id_material_interno"] is None
    assert fila_post["precio_unitario"] == fila["precio_unitario"]
