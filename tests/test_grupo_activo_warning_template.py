"""
Fix del rótulo de bloqueo duplicado en templates/comercial/modals/grupo_activo_warning.html
(_Planes_Activos/2026-07-23-propagacion-estatus-levantamientos-PLAN.md, Paso 12).

Antes: una OP tipo LEVANTAMIENTO no-final disparaba a la vez tiene_activo_op (bloque
"sim", mal-rotulado "Simulación en proceso") y tiene_activo_lev (bloque "lev",
correcto) -> dos tarjetas para el mismo bloqueo.
"""
from jinja2 import Environment, FileSystemLoader

_env = Environment(loader=FileSystemLoader("templates"))
_tpl = _env.get_template("comercial/modals/grupo_activo_warning.html")


def test_bloqueador_levantamiento_con_lev_activo_colapsa_en_una_tarjeta():
    html = _tpl.render(
        sim={"op_id": "OP-1", "tipo_solicitud": "Levantamiento", "estado": "Pendiente", "es_borrador": False},
        lev={"op_id": "OP-1", "estado": "Pendiente"},
    )
    assert html.count("bg-purple-50") == 1
    assert "El proceso de levantamiento aún no concluye" in html
    assert "Simulación en proceso" not in html


def test_bloqueador_levantamiento_sin_lev_activo_usa_estado_de_sim():
    """Caso frecuente: todos los levantamientos ya terminales (ej. Completado) pero
    la propagacion aun no cerro la OP -- tiene_activo_op=true, tiene_activo_lev=false."""
    html = _tpl.render(
        sim={"op_id": "OP-2", "tipo_solicitud": "Levantamiento", "estado": "Completado", "es_borrador": False},
        lev=None,
    )
    assert html.count("bg-purple-50") == 1
    assert "El proceso de levantamiento aún no concluye" in html
    assert "Completado" in html


def test_bloqueador_no_levantamiento_mantiene_tarjeta_azul_sin_cambios():
    html = _tpl.render(
        sim={"op_id": "OP-3", "tipo_solicitud": "Oferta Final", "estado": "En Proceso", "es_borrador": False},
        lev=None,
    )
    assert "Simulación en proceso" in html
    assert "bg-purple-50" not in html


def test_bloqueador_solo_lev_de_otra_op_no_se_toca():
    """sim y lev pueden referir a OPs distintas del mismo grupo (raro, pero valido) --
    en ese caso ambas tarjetas deben seguir apareciendo por separado."""
    html = _tpl.render(
        sim={"op_id": "OP-4", "tipo_solicitud": "Oferta Final", "estado": "En Proceso", "es_borrador": False},
        lev={"op_id": "OP-5", "estado": "Pendiente"},
    )
    assert "Simulación en proceso" in html
    assert "Levantamiento activo" in html
    assert html.count("bg-purple-50") == 1
    assert html.count("bg-blue-50") == 1


def test_bloqueador_sim_levantamiento_y_lev_de_otra_op_no_colapsan():
    """sim.tipo_solicitud == 'Levantamiento' pero lev.op_id es de una OP DISTINTA
    (dos OPs tipo Levantamiento bloqueando el mismo grupo): el rotulo de sim se
    corrige igual (no "Simulación en proceso"), pero NO colapsan en una sola
    tarjeta -- eso le atribuiria el estado de OP-7 a OP-6 y ocultaria OP-7."""
    html = _tpl.render(
        sim={"op_id": "OP-6", "tipo_solicitud": "Levantamiento", "estado": "Pendiente", "es_borrador": False},
        lev={"op_id": "OP-7", "estado": "Agendado"},
    )
    assert "OP-6" in html
    assert "OP-7" in html
    assert "El proceso de levantamiento aún no concluye" in html
    assert "Levantamiento activo" in html
    assert "Simulación en proceso" not in html
    assert html.count("bg-purple-50") == 2
    # OP-6 (sim) debe mostrar su propio estado (Pendiente), no el de OP-7 (Agendado).
    assert "Pendiente" in html
