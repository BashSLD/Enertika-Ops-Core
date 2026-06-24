from jinja2 import Environment, FileSystemLoader

from core.materials.router import router


def test_router_expone_endpoints_actualizar_precios():
    paths = {route.path for route in router.routes}

    assert "/materials/internos/plantilla-precios" in paths
    assert "/materials/internos/actualizar-precios" in paths


def test_templates_actualizar_precios_compilan():
    env = Environment(loader=FileSystemLoader("templates"))

    env.get_template("materials/partials/actualizar_precios_resultado.html")
    env.get_template("materials/partials/internos_content.html")
