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
    env.filters["time_mx"] = lambda value, fmt="%d/%m/%Y": ""

    for template_name in [
        "cfe/partials/modal_buscar_periodos.html",
        "cfe/partials/busqueda_periodos.html",
        "cfe/partials/busqueda_confirmada.html",
        "cfe/partials/historial_descargas.html",
        "cfe/partials/lista_servicios.html",
    ]:
        assert env.get_template(template_name)


def test_historial_cfe_xml_completo_sin_pdf_muestra_reintento_pdf():
    env = Environment(loader=FileSystemLoader("templates"))
    env.filters["time_mx"] = lambda value, fmt="%d/%m/%Y": "09/06/2026"

    html = env.get_template("cfe/partials/historial_descargas.html").render(
        servicio={"id": "servicio-1"},
        descargas=[
            {
                "id": "xml-1",
                "periodo": "2026-04",
                "tipo": "xml",
                "estatus": "completado",
                "descargado_en": "2026-06-09",
                "error_mensaje": None,
                "tipo_recibo": "GDMTO",
            }
        ],
        tiene_activo=False,
        user={"user_name": "QA"},
    )

    assert "Falta PDF" in html
    assert "Reintentar PDF" in html
    assert "GDMTO" in html


def test_resultado_busqueda_cfe_no_muestra_descartado_para_no_disponible():
    env = Environment(loader=FileSystemLoader("templates"))
    env.filters["time_mx"] = lambda value, fmt="%d/%m/%Y": ""

    html = env.get_template("cfe/partials/busqueda_confirmada.html").render(
        servicio={"id": "servicio-1"},
        descargas=[],
        tiene_activo=False,
        items=[
            {
                "periodo": "2026-04",
                "etiqueta_periodo": "Abr 2026",
                "decision": "descartado",
                "xml_estatus": "no_disponible",
                "pdf_estatus": "no_disponible",
                "ya_descargado_xml": False,
                "ya_descargado_pdf": False,
            },
            {
                "periodo": "2026-03",
                "etiqueta_periodo": "Mar 2026",
                "decision": "descartado",
                "xml_estatus": "descargado",
                "pdf_estatus": "no_disponible",
                "ya_descargado_xml": False,
                "ya_descargado_pdf": False,
            },
            {
                "periodo": "2026-02",
                "etiqueta_periodo": "Feb 2026",
                "decision": "no_aplica",
                "xml_estatus": "error",
                "pdf_estatus": "no_disponible",
                "ya_descargado_xml": False,
                "ya_descargado_pdf": False,
            },
        ],
        _toast={"type": "success", "message": "Listo"},
        user={"user_name": "QA"},
    )

    assert "Descartado" not in html
    assert "No disponible" in html
    assert "No seleccionado" in html
    assert "Con error" in html


def test_lista_servicios_cfe_muestra_trabajos_activos():
    env = Environment(loader=FileSystemLoader("templates"))
    env.filters["time_mx"] = lambda value, fmt="%d/%m/%Y": "09/06/2026"

    html = env.get_template("cfe/partials/lista_servicios.html").render(
        servicios=[
            {
                "id": "servicio-busqueda",
                "nombre": "SERVICIO BUSQUEDA",
                "alias": None,
                "numero_servicio": "100",
                "ultima_descarga": None,
                "total_descargas": 0,
                "tiene_pendiente": True,
                "descarga_activa": False,
                "busqueda_activa_id": "busqueda-1",
                "busqueda_activa_estatus": "descargando",
            },
            {
                "id": "servicio-descarga",
                "nombre": "SERVICIO DESCARGA",
                "alias": None,
                "numero_servicio": "200",
                "ultima_descarga": None,
                "total_descargas": 0,
                "tiene_pendiente": True,
                "descarga_activa": True,
                "busqueda_activa_id": None,
                "busqueda_activa_estatus": None,
            },
        ],
        estado_sesion={"sesion_activa": True},
        user={"user_name": "QA"},
    )

    assert "Búsqueda en curso" in html
    assert "Ver búsqueda" in html
    assert "/cfe/servicios/servicio-busqueda/modal-busqueda-activa" in html
    assert "Descarga en curso" in html
    assert 'hx-trigger="load, every 4s"' in html
