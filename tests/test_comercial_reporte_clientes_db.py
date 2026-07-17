"""
Integracion: reportes_db_service de Comercial contra BD real.
Cada test opera dentro de una transaccion que se revierte al terminar (real_conn).

Cubre los escenarios de SQL a mano (UNION ALL, NOT EXISTS, agregacion legacy)
que los tests de reportes_service/reportes_excel_builder no ejercitan porque
mockean el DB service.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from modules.comercial import reportes_db_service as db

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def _usuario_id(conn):
    user_id = await conn.fetchval("SELECT id_usuario FROM tb_usuarios WHERE is_active = true LIMIT 1")
    if not user_id:
        pytest.skip("No hay usuarios activos en la BD")
    return user_id


async def _insertar_cliente(conn, nombre_fiscal: str):
    cliente_id = uuid4()
    await conn.execute(
        "INSERT INTO tb_clientes (id, nombre_fiscal) VALUES ($1, $2)",
        cliente_id, nombre_fiscal,
    )
    return cliente_id


async def _insertar_oportunidad(
    conn, *, usuario_id, cliente_id=None, cliente_nombre: str, id_estatus_global=None,
):
    op_id = uuid4()
    op_estandar = f"TEST-RCC-{uuid4().hex[:10].upper()}"
    await conn.execute(
        """
        INSERT INTO tb_oportunidades
            (id_oportunidad, op_id_estandar, cliente_nombre, creado_por_id,
             email_enviado, cliente_id, id_estatus_global)
        VALUES ($1, $2, $3, $4, true, $5, $6)
        """,
        op_id, op_estandar, cliente_nombre, usuario_id, cliente_id, id_estatus_global,
    )
    return op_id, op_estandar


async def _insertar_sitio(conn, *, id_oportunidad, direccion="Direccion de prueba", nombre_sitio=None):
    sitio_id = uuid4()
    await conn.execute(
        "INSERT INTO tb_sitios_oportunidad (id_sitio, id_oportunidad, direccion, nombre_sitio) "
        "VALUES ($1, $2, $3, $4)",
        sitio_id, id_oportunidad, direccion, nombre_sitio,
    )
    return sitio_id


async def _insertar_proyecto(
    conn, *, id_oportunidad, status_fase="CONSTRUCCION", area_actual="CONSTRUCCION",
    id_sitio=None, fecha_inicio_area=None,
):
    proyecto_id = uuid4()
    proyecto_estandar = f"TEST-RCC-PROY-{uuid4().hex[:10].upper()}"
    if fecha_inicio_area is not None:
        await conn.execute(
            """
            INSERT INTO tb_proyectos_gate
                (id_proyecto, id_oportunidad, proyecto_id_estandar, status_fase, area_actual,
                 id_sitio, fecha_inicio_area)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            proyecto_id, id_oportunidad, proyecto_estandar, status_fase, area_actual,
            id_sitio, fecha_inicio_area,
        )
    else:
        await conn.execute(
            """
            INSERT INTO tb_proyectos_gate
                (id_proyecto, id_oportunidad, proyecto_id_estandar, status_fase, area_actual, id_sitio)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            proyecto_id, id_oportunidad, proyecto_estandar, status_fase, area_actual, id_sitio,
        )
    return proyecto_id, proyecto_estandar


_SIN_FILTROS = dict(
    filtro_tipo_id=None, filtro_tecnologia_id=None, filtro_estatus_id=None,
    fecha_inicio_mx=None, fecha_fin_mx_exclusive=None,
)


# ---------------------------------------------------------------------------
# #4 - legacy no se fusiona con canonico de mismo nombre
# ---------------------------------------------------------------------------

async def test_resumen_no_fusiona_legacy_con_canonico_mismo_nombre(real_conn):
    usuario_id = await _usuario_id(real_conn)
    nombre = f"TEST RCC Acme Solar {uuid4().hex[:6]}"
    cliente_id = await _insertar_cliente(real_conn, nombre)
    await _insertar_oportunidad(real_conn, usuario_id=usuario_id, cliente_id=cliente_id, cliente_nombre=nombre)
    await _insertar_oportunidad(real_conn, usuario_id=usuario_id, cliente_id=None, cliente_nombre=nombre)

    filas = await db.obtener_resumen_clientes(real_conn, **_SIN_FILTROS)

    fila_canonica = next(f for f in filas if f["grupo_id"] == str(cliente_id))
    fila_legacy = next(f for f in filas if f["cliente_nombre"] == f"Registro histórico sin vincular — {nombre}")

    assert fila_canonica["cliente_nombre"] == nombre
    assert fila_canonica["total_solicitudes"] == 1
    assert fila_legacy["total_solicitudes"] == 1
    assert fila_canonica["grupo_id"] != fila_legacy["grupo_id"]


# ---------------------------------------------------------------------------
# #6 - catalogo nulo no pierde ni duplica la oportunidad
# ---------------------------------------------------------------------------

async def test_resumen_catalogo_nulo_no_pierde_ni_duplica(real_conn):
    usuario_id = await _usuario_id(real_conn)
    nombre = f"TEST RCC Sin Estatus {uuid4().hex[:6]}"
    cliente_id = await _insertar_cliente(real_conn, nombre)
    await _insertar_oportunidad(
        real_conn, usuario_id=usuario_id, cliente_id=cliente_id, cliente_nombre=nombre, id_estatus_global=None,
    )

    filas = await db.obtener_resumen_clientes(real_conn, **_SIN_FILTROS)
    fila = next(f for f in filas if f["grupo_id"] == str(cliente_id))

    assert fila["total_solicitudes"] == 1
    assert fila["desglose_estatus"] == "Sin estatus: 1"


# ---------------------------------------------------------------------------
# #7 - guarda anti-drift: el conteo de filas coincide con los datos reales
# ---------------------------------------------------------------------------

async def test_contar_filas_resumen_coincide_con_datos_reales(real_conn):
    usuario_id = await _usuario_id(real_conn)
    nombre = f"TEST RCC Conteo {uuid4().hex[:6]}"
    cliente_id = await _insertar_cliente(real_conn, nombre)
    await _insertar_oportunidad(real_conn, usuario_id=usuario_id, cliente_id=cliente_id, cliente_nombre=nombre)
    await _insertar_oportunidad(real_conn, usuario_id=usuario_id, cliente_id=None, cliente_nombre=f"{nombre} Legacy")

    filas = await db.obtener_resumen_clientes(real_conn, **_SIN_FILTROS)
    total = await db.contar_filas_resumen_general(real_conn, **_SIN_FILTROS)

    assert len(filas) == total


# ---------------------------------------------------------------------------
# #12 - proyecto cuyo id_sitio pertenece a OTRA oportunidad no se pierde
# ---------------------------------------------------------------------------

async def test_detalle_cliente_proyecto_con_sitio_de_otra_oportunidad(real_conn):
    usuario_id = await _usuario_id(real_conn)
    nombre = f"TEST RCC Sitio Ajeno {uuid4().hex[:6]}"
    cliente_id = await _insertar_cliente(real_conn, nombre)

    op_x, op_x_estandar = await _insertar_oportunidad(
        real_conn, usuario_id=usuario_id, cliente_id=cliente_id, cliente_nombre=nombre,
    )
    # op_y es de OTRO cliente/registro legacy; su unico proposito es prestar un sitio ajeno a op_x.
    op_y, _ = await _insertar_oportunidad(
        real_conn, usuario_id=usuario_id, cliente_id=None, cliente_nombre=f"{nombre} Ajena",
    )
    sitio_de_op_y = await _insertar_sitio(real_conn, id_oportunidad=op_y)

    # Proyecto de op_x pero con id_sitio de op_y: la FK lo permite (no hay constraint compuesta).
    _, proyecto_estandar = await _insertar_proyecto(
        real_conn, id_oportunidad=op_x, status_fase="CONSTRUCCION",
        area_actual="CONSTRUCCION", id_sitio=sitio_de_op_y,
    )

    filas = await db.obtener_detalle_por_cliente(
        real_conn, filtro_cliente_id=cliente_id, **_SIN_FILTROS,
    )

    assert len(filas) == 1
    assert filas[0]["folio"] == op_x_estandar
    assert filas[0]["proyecto_id_estandar"] == proyecto_estandar
    assert filas[0]["sitio_nombre"] == "N/A"
    assert filas[0]["fase_proyecto"] == "CONSTRUCCION"


# ---------------------------------------------------------------------------
# #15 - guarda anti-drift del modo enfocado (multisitio + proyecto sin sitio + N/A)
# ---------------------------------------------------------------------------

async def test_detalle_por_cliente_combina_ramas_multisitio_proyecto_y_na(real_conn):
    usuario_id = await _usuario_id(real_conn)
    nombre = f"TEST RCC Detalle {uuid4().hex[:6]}"
    cliente_id = await _insertar_cliente(real_conn, nombre)

    op_multisitio, _ = await _insertar_oportunidad(
        real_conn, usuario_id=usuario_id, cliente_id=cliente_id, cliente_nombre=nombre,
    )
    await _insertar_sitio(real_conn, id_oportunidad=op_multisitio, nombre_sitio="Sitio 1")
    await _insertar_sitio(real_conn, id_oportunidad=op_multisitio, nombre_sitio="Sitio 2")

    op_proyecto_sin_sitio, _ = await _insertar_oportunidad(
        real_conn, usuario_id=usuario_id, cliente_id=cliente_id, cliente_nombre=nombre,
    )
    await _insertar_proyecto(real_conn, id_oportunidad=op_proyecto_sin_sitio, id_sitio=None)

    await _insertar_oportunidad(real_conn, usuario_id=usuario_id, cliente_id=cliente_id, cliente_nombre=nombre)
    # tercera oportunidad sin sitio ni proyecto: cubre la rama N/A completa.

    filas = await db.obtener_detalle_por_cliente(real_conn, filtro_cliente_id=cliente_id, **_SIN_FILTROS)

    assert len(filas) == 4  # 2 sitios + 1 proyecto sin sitio + 1 fila N/A


# ---------------------------------------------------------------------------
# #1 - cliente canonico sin solicitudes sigue apareciendo en el resumen
# ---------------------------------------------------------------------------

async def test_resumen_incluye_cliente_canonico_sin_solicitudes(real_conn):
    nombre = f"TEST RCC Sin Solicitudes {uuid4().hex[:6]}"
    cliente_id = await _insertar_cliente(real_conn, nombre)

    filas = await db.obtener_resumen_clientes(real_conn, **_SIN_FILTROS)
    fila = next(f for f in filas if f["grupo_id"] == str(cliente_id))

    assert fila["cliente_nombre"] == nombre
    assert fila["total_solicitudes"] == 0
    assert fila["desglose_estatus"] == ""


# ---------------------------------------------------------------------------
# #2 - variantes de mayusculas/espacios del mismo nombre legacy se agrupan
# ---------------------------------------------------------------------------

async def test_resumen_agrupa_legacy_por_nombre_normalizado(real_conn):
    usuario_id = await _usuario_id(real_conn)
    base = f"TEST RCC Beta Corp {uuid4().hex[:6]}"
    variante_1 = base  # capitalizada
    variante_2 = f"  {base.lower()}  "  # mismo texto normalizado, minuscula y con espacios

    await _insertar_oportunidad(real_conn, usuario_id=usuario_id, cliente_id=None, cliente_nombre=variante_1)
    await _insertar_oportunidad(real_conn, usuario_id=usuario_id, cliente_id=None, cliente_nombre=variante_2)

    # La etiqueta ganadora depende del collation de la BD (no coincide con el orden
    # lexicografico de Python), asi que se le pregunta a Postgres con la misma
    # expresion que usa la query de produccion (_legacy_grupo_id_expr), en vez de asumirlo.
    etiqueta_esperada = await real_conn.fetchval(
        "SELECT MIN(NULLIF(btrim(x), '')) FROM (VALUES ($1), ($2)) AS t(x)",
        variante_1, variante_2,
    )

    filas = await db.obtener_resumen_clientes(real_conn, **_SIN_FILTROS)
    grupo_esperado = "legacy:" + base.lower()
    fila = next(f for f in filas if f["grupo_id"] == grupo_esperado)

    assert fila["total_solicitudes"] == 2
    assert fila["cliente_nombre"] == f"Registro histórico sin vincular — {etiqueta_esperada}"


# ---------------------------------------------------------------------------
# #3 - legacy sin nombre (vacio/blank) usa el fallback "Sin nombre"
# ---------------------------------------------------------------------------

async def test_resumen_legacy_sin_nombre_usa_fallback(real_conn):
    usuario_id = await _usuario_id(real_conn)

    antes = await db.obtener_resumen_clientes(real_conn, **_SIN_FILTROS)
    total_antes = next((f["total_solicitudes"] for f in antes if f["grupo_id"] == "legacy:sin_nombre"), 0)

    await _insertar_oportunidad(real_conn, usuario_id=usuario_id, cliente_id=None, cliente_nombre="   ")

    despues = await db.obtener_resumen_clientes(real_conn, **_SIN_FILTROS)
    fila = next(f for f in despues if f["grupo_id"] == "legacy:sin_nombre")

    assert fila["cliente_nombre"] == "Registro histórico sin vincular — Sin nombre"
    assert fila["total_solicitudes"] == total_antes + 1


# ---------------------------------------------------------------------------
# #5 - desglose de estatus agrupa y cuenta por nombre de estatus
# ---------------------------------------------------------------------------

async def test_resumen_desglose_estatus_agrupa_y_cuenta(real_conn):
    usuario_id = await _usuario_id(real_conn)
    nombre = f"TEST RCC Desglose {uuid4().hex[:6]}"
    cliente_id = await _insertar_cliente(real_conn, nombre)

    id_ganada = await real_conn.fetchval("SELECT id FROM tb_cat_estatus_oportunidades WHERE nombre = 'Ganada'")
    id_en_proceso = await real_conn.fetchval(
        "SELECT id FROM tb_cat_estatus_oportunidades WHERE nombre = 'En Proceso'"
    )
    assert id_ganada and id_en_proceso, "Catalogo de estatus incompleto en el entorno de pruebas"

    await _insertar_oportunidad(
        real_conn, usuario_id=usuario_id, cliente_id=cliente_id, cliente_nombre=nombre, id_estatus_global=id_ganada,
    )
    await _insertar_oportunidad(
        real_conn, usuario_id=usuario_id, cliente_id=cliente_id, cliente_nombre=nombre, id_estatus_global=id_ganada,
    )
    await _insertar_oportunidad(
        real_conn, usuario_id=usuario_id, cliente_id=cliente_id, cliente_nombre=nombre,
        id_estatus_global=id_en_proceso,
    )

    filas = await db.obtener_resumen_clientes(real_conn, **_SIN_FILTROS)
    fila = next(f for f in filas if f["grupo_id"] == str(cliente_id))

    assert fila["total_solicitudes"] == 3
    assert fila["desglose_estatus"] == "En Proceso: 1 | Ganada: 2"


# ---------------------------------------------------------------------------
# #8 - detalle general usa la fase del proyecto mas reciente
# ---------------------------------------------------------------------------

async def test_detalle_general_usa_fase_mas_reciente(real_conn):
    usuario_id = await _usuario_id(real_conn)
    nombre = f"TEST RCC Fase Reciente {uuid4().hex[:6]}"
    op_id, op_estandar = await _insertar_oportunidad(
        real_conn, usuario_id=usuario_id, cliente_id=None, cliente_nombre=nombre,
    )
    ahora = datetime.now(timezone.utc)
    await _insertar_proyecto(
        real_conn, id_oportunidad=op_id, area_actual="INGENIERIA", fecha_inicio_area=ahora - timedelta(days=10),
    )
    await _insertar_proyecto(
        real_conn, id_oportunidad=op_id, area_actual="CONSTRUCCION", fecha_inicio_area=ahora,
    )

    filas = await db.obtener_detalle_general(real_conn, **_SIN_FILTROS)
    fila = next(f for f in filas if f["folio"] == op_estandar)

    assert fila["fase_proyecto"] == "CONSTRUCCION"


# ---------------------------------------------------------------------------
# #9 - detalle general de una oportunidad sin proyecto es N/A
# ---------------------------------------------------------------------------

async def test_detalle_general_sin_proyecto_es_na(real_conn):
    usuario_id = await _usuario_id(real_conn)
    nombre = f"TEST RCC Sin Proyecto {uuid4().hex[:6]}"
    _, op_estandar = await _insertar_oportunidad(
        real_conn, usuario_id=usuario_id, cliente_id=None, cliente_nombre=nombre,
    )

    filas = await db.obtener_detalle_general(real_conn, **_SIN_FILTROS)
    fila = next(f for f in filas if f["folio"] == op_estandar)

    assert fila["fase_proyecto"] == "N/A"


# ---------------------------------------------------------------------------
# #10 - detalle por cliente: multisitio sin proyecto -> una fila por sitio
# ---------------------------------------------------------------------------

async def test_detalle_cliente_multisitio_sin_proyecto(real_conn):
    usuario_id = await _usuario_id(real_conn)
    nombre = f"TEST RCC Multisitio {uuid4().hex[:6]}"
    cliente_id = await _insertar_cliente(real_conn, nombre)
    op_id, _ = await _insertar_oportunidad(real_conn, usuario_id=usuario_id, cliente_id=cliente_id, cliente_nombre=nombre)
    await _insertar_sitio(real_conn, id_oportunidad=op_id, nombre_sitio="Sitio 1")
    await _insertar_sitio(real_conn, id_oportunidad=op_id, nombre_sitio="Sitio 2")

    filas = await db.obtener_detalle_por_cliente(real_conn, filtro_cliente_id=cliente_id, **_SIN_FILTROS)

    assert len(filas) == 2
    assert {f["sitio_nombre"] for f in filas} == {"Sitio 1", "Sitio 2"}
    assert all(f["proyecto_id_estandar"] == "N/A" and f["fase_proyecto"] == "N/A" for f in filas)


# ---------------------------------------------------------------------------
# #11 - detalle por cliente: proyecto sin sitio (id_sitio NULL) es su propia fila
# ---------------------------------------------------------------------------

async def test_detalle_cliente_proyecto_sin_sitio(real_conn):
    usuario_id = await _usuario_id(real_conn)
    nombre = f"TEST RCC Proyecto Sin Sitio {uuid4().hex[:6]}"
    cliente_id = await _insertar_cliente(real_conn, nombre)
    op_id, op_estandar = await _insertar_oportunidad(
        real_conn, usuario_id=usuario_id, cliente_id=cliente_id, cliente_nombre=nombre,
    )
    _, proyecto_estandar = await _insertar_proyecto(
        real_conn, id_oportunidad=op_id, area_actual="INGENIERIA", id_sitio=None,
    )

    filas = await db.obtener_detalle_por_cliente(real_conn, filtro_cliente_id=cliente_id, **_SIN_FILTROS)

    assert len(filas) == 1
    assert filas[0]["folio"] == op_estandar
    assert filas[0]["sitio_nombre"] == "N/A"
    assert filas[0]["proyecto_id_estandar"] == proyecto_estandar
    assert filas[0]["fase_proyecto"] == "INGENIERIA"


# ---------------------------------------------------------------------------
# #13 - detalle por cliente: oportunidad sin sitio ni proyecto es una fila N/A
# ---------------------------------------------------------------------------

async def test_detalle_cliente_sin_sitio_ni_proyecto(real_conn):
    usuario_id = await _usuario_id(real_conn)
    nombre = f"TEST RCC Nada {uuid4().hex[:6]}"
    cliente_id = await _insertar_cliente(real_conn, nombre)
    _, op_estandar = await _insertar_oportunidad(
        real_conn, usuario_id=usuario_id, cliente_id=cliente_id, cliente_nombre=nombre,
    )

    filas = await db.obtener_detalle_por_cliente(real_conn, filtro_cliente_id=cliente_id, **_SIN_FILTROS)

    assert len(filas) == 1
    assert filas[0]["folio"] == op_estandar
    assert filas[0]["sitio_nombre"] == "N/A"
    assert filas[0]["proyecto_id_estandar"] == "N/A"
    assert filas[0]["fase_proyecto"] == "N/A"


# ---------------------------------------------------------------------------
# #14 - detalle por cliente no mezcla filas de otro cliente
# ---------------------------------------------------------------------------

async def test_detalle_cliente_no_mezcla_otro_cliente(real_conn):
    usuario_id = await _usuario_id(real_conn)
    nombre_a = f"TEST RCC Cliente A {uuid4().hex[:6]}"
    nombre_b = f"TEST RCC Cliente B {uuid4().hex[:6]}"
    cliente_a = await _insertar_cliente(real_conn, nombre_a)
    cliente_b = await _insertar_cliente(real_conn, nombre_b)

    op_a, op_a_estandar = await _insertar_oportunidad(
        real_conn, usuario_id=usuario_id, cliente_id=cliente_a, cliente_nombre=nombre_a,
    )
    op_b, op_b_estandar = await _insertar_oportunidad(
        real_conn, usuario_id=usuario_id, cliente_id=cliente_b, cliente_nombre=nombre_b,
    )
    await _insertar_sitio(real_conn, id_oportunidad=op_a, nombre_sitio="Sitio A")
    await _insertar_sitio(real_conn, id_oportunidad=op_b, nombre_sitio="Sitio B")

    filas = await db.obtener_detalle_por_cliente(real_conn, filtro_cliente_id=cliente_a, **_SIN_FILTROS)

    assert len(filas) == 1
    assert filas[0]["folio"] == op_a_estandar
    assert all(f["folio"] != op_b_estandar for f in filas)
