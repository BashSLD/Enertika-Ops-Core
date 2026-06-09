from modules.cfe.scraper import (
    _periodo_from_public_text,
    _periodo_public_label,
    _public_artifact_control,
    _public_row_score,
)
from jinja2 import Environment, FileSystemLoader


def test_periodo_from_public_text_normaliza_mes_anio():
    assert _periodo_from_public_text("may 2026 Descarga Pdf Descarga Xml Factura") == "2026-05"
    assert _periodo_from_public_text("abr 2025 Descarga Xml Factura") == "2025-04"
    assert _periodo_from_public_text("DICIEMBRE 2025") == "2025-12"


def test_periodo_public_label_formatea_periodo():
    assert _periodo_public_label("2026-05") == "May 2026"
    assert _periodo_public_label("2025-12") == "Dic 2025"


def test_public_artifact_control_prefiere_xml_y_pdf():
    row = {
        "text": "may 2026 Descarga Pdf Descarga Xml Factura",
        "controls": [
            {"id": "pdf_1", "name": "", "text": "Descarga Pdf", "href": "", "index": 1},
            {"id": "xml_1", "name": "", "text": "Descarga Xml Factura", "href": "", "index": 2},
        ],
    }

    assert _public_artifact_control(row, "pdf")["index"] == 1
    assert _public_artifact_control(row, "xml")["index"] == 2
    assert _public_row_score(row) > 0


def test_templates_busqueda_cfe_compilan():
    env = Environment(loader=FileSystemLoader("templates"))

    for template_name in [
        "cfe/partials/modal_buscar_periodos.html",
        "cfe/partials/busqueda_periodos.html",
        "cfe/partials/busqueda_confirmada.html",
    ]:
        assert env.get_template(template_name)
