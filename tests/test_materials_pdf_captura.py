import pytest
from jinja2 import Environment, FileSystemLoader
from pydantic import ValidationError

from core.materials.router import router
from core.materials.schemas import MaterialPdfAsignacion


def test_router_expone_endpoints_pdf_captura():
    paths = {route.path for route in router.routes}

    assert "/materials/internos/pdf-captura/extraer" in paths
    assert "/materials/internos/pdf-captura/guardar" in paths


def test_templates_pdf_captura_compilan():
    env = Environment(loader=FileSystemLoader("templates"))

    env.get_template("materials/partials/internos_content.html")
    env.get_template("materials/partials/similar_internos_results.html")
    env.get_template("materials/partials/_form_interno.html")


def test_material_pdf_asignacion_moneda_valida():
    asignacion = MaterialPdfAsignacion(
        id_material="11111111-1111-1111-1111-111111111111",
        precio="123.45",
        moneda="usd",
    )
    assert asignacion.moneda == "USD"


def test_material_pdf_asignacion_moneda_invalida_rechazada():
    with pytest.raises(ValidationError):
        MaterialPdfAsignacion(
            id_material="11111111-1111-1111-1111-111111111111",
            precio="123.45",
            moneda="EUR",
        )


def test_material_pdf_asignacion_precio_negativo_rechazado():
    with pytest.raises(ValidationError):
        MaterialPdfAsignacion(
            id_material="11111111-1111-1111-1111-111111111111",
            precio="-1",
            moneda="MXN",
        )
