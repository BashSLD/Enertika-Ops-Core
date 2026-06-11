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
        "cfe/analisis.html",
        "cfe/partials/analisis_servicio.html",
        "cfe/partials/modal_buscar_periodos.html",
        "cfe/partials/busqueda_periodos.html",
        "cfe/partials/busqueda_confirmada.html",
        "cfe/partials/historial_descargas.html",
        "cfe/partials/lista_servicios.html",
    ]:
        assert env.get_template(template_name)


def test_analisis_cfe_sin_datos_renderiza_estado_vacio():
    env = Environment(loader=FileSystemLoader("templates"))

    html = env.get_template("cfe/partials/analisis_servicio.html").render(
        analisis={
            "servicio": {
                "id": "servicio-1",
                "nombre": "SERVICIO PRUEBA",
                "numero_servicio": "123",
                "alias": None,
            },
            "hay_datos": False,
            "mensaje": "No hay XMLs completados para analizar este servicio.",
        },
        user={"user_name": "QA"},
    )

    assert "Volver a servicios" in html
    assert "No hay XMLs completados" in html
    assert 'hx-get="/cfe/ui"' in html


def test_analisis_cfe_con_datos_renderiza_dashboard():
    env = Environment(loader=FileSystemLoader("templates"))
    analisis = {
        "servicio": {
            "id": "servicio-1",
            "nombre": "SERVICIO PRUEBA",
            "numero_servicio": "123",
            "alias": "Planta",
        },
        "hay_datos": True,
        "mensaje": "",
        "perfil_analisis": {
            "key": "GDMTH",
            "nombre": "GDMTH",
            "descripcion": "Analisis horario con base, intermedia y punta.",
        },
        "secciones": {"perfil_horario": True, "desglose": True, "historial_extendido": True},
        "ultimo": {
            "label": "Feb-25",
            "tarifa": "GDMTH",
            "total_facturado": 5208.4,
            "subtotal": 4490.0,
            "consumo": 6000.0,
            "costo_kwh": 0.868,
            "kwmax": 22.0,
            "fp": 95.5,
            "consumo_punta_pct": 50.0,
            "perfil_horario": [{"nombre": "Punta", "consumo": 3000.0, "costo": 300.0}],
            "componentes": [{"nombre": "Generacion P", "importe": 300.0}],
        },
        "total_periodos": 2,
        "periodos_comparables": 2,
        "baseline_periodos": 1,
        "kpis": [
            {"key": "total_facturado", "label": "Total facturado", "valor": 5208.4, "tipo": "dinero", "unidad": "MXN", "decimales": 0},
            {"key": "consumo", "label": "Consumo", "valor": 6000.0, "tipo": "numero", "unidad": "kWh", "decimales": 0},
        ],
        "metricas_grafica": [
            {"key": "consumo", "label": "Consumo", "unidad": "kWh", "decimales": 0},
            {"key": "total_facturado", "label": "Total facturado", "unidad": "MXN", "decimales": 0},
        ],
        "comparativos": [
            {
                "key": "consumo",
                "label": "Consumo",
                "unidad": "kWh",
                "decimales": 0,
                "actual": 6000.0,
                "anterior": {"disponible": True, "valor": 5000.0, "delta": 1000.0, "delta_pct": 20.0},
                "promedio_12": {"disponible": True, "valor": 5000.0, "delta": 1000.0, "delta_pct": 20.0, "periodos": 1},
                "anio_anterior": {"disponible": False, "valor": None, "delta": None, "delta_pct": None},
            }
        ],
        "alertas": [
            {"tipo": "warning", "titulo": "Consumo arriba del promedio", "detalle": "20.0% contra el promedio."}
        ],
        "calidad_datos": {
            "disponibles": ["Consumo", "Total facturado"],
            "faltantes": [],
            "limitaciones": [],
        },
        "variacion_historico": {
            "disponible": True,
            "diferencia_estimada": 100.0,
            "costo_esperado": 5308.4,
            "costo_kwh_baseline": 0.884,
            "consumo_baseline": 5000.0,
            "variacion_consumo": 1000.0,
        },
        "historial_extendido": {
            "disponible": True,
            "origen_label": "Feb-25",
            "items": [
                {
                    "mes": "FEB",
                    "consumo_kwh": 6000.0,
                    "demanda_kw": 22.0,
                    "factor_potencia_pct": 95.5,
                    "precio_medio_mxn": 0.86,
                }
            ],
        },
        "graficas": {
            "labels": ["Ene-25", "Feb-25"],
            "metricas": {
                "consumo": {"label": "Consumo", "unidad": "kWh", "decimales": 0, "data": [5000.0, 6000.0], "promedio": 5500.0},
                "total_facturado": {"label": "Total", "unidad": "MXN", "decimales": 0, "data": [4300.0, 5208.4], "promedio": 4754.2},
                "costo_kwh": {"label": "Costo/kWh", "unidad": "MXN/kWh", "decimales": 2, "data": [0.86, 0.868], "promedio": 0.864},
                "kwmax": {"label": "Demanda", "unidad": "kW", "decimales": 1, "data": [20.0, 22.0], "promedio": 21.0},
            },
            "perfil_horario": {"labels": ["Punta"], "consumo": [3000.0], "costo": [300.0]},
            "desglose": {"labels": ["Generacion P"], "data": [300.0]},
        },
    }

    html = env.get_template("cfe/partials/analisis_servicio.html").render(
        analisis=analisis,
        user={"user_name": "QA"},
    )

    assert "Total facturado" in html
    assert "Comparativo del último periodo" in html
    assert "cfe-analisis-main-chart" in html
    assert "Generacion P" in html


def test_analisis_cfe_gdmto_renderiza_metricas_dinamicas_sin_seccion_horaria():
    env = Environment(loader=FileSystemLoader("templates"))
    analisis = {
        "servicio": {
            "id": "servicio-1",
            "nombre": "SERVICIO GDMTO",
            "numero_servicio": "123",
            "alias": None,
        },
        "hay_datos": True,
        "mensaje": "",
        "perfil_analisis": {
            "key": "GDMTO",
            "nombre": "GDMTO",
            "descripcion": "Analisis ordinario sin inferir perfil horario.",
        },
        "secciones": {"perfil_horario": False, "desglose": True, "historial_extendido": True},
        "ultimo": {
            "label": "Mar-26",
            "tarifa": "GDMTO",
            "total_facturado": 5220.0,
            "subtotal": 4500.0,
            "consumo": 4500.0,
            "costo_kwh": 1.16,
            "kwmax": 28.0,
            "kw_cap": 30.0,
            "kw_dist": 31.0,
            "fp": 97.1,
            "perfil_horario": [],
            "componentes": [{"nombre": "Energia", "importe": 4200.24}],
        },
        "total_periodos": 2,
        "periodos_comparables": 2,
        "baseline_periodos": 1,
        "kpis": [
            {"key": "total_facturado", "label": "Total facturado", "valor": 5220.0, "tipo": "dinero", "unidad": "MXN", "decimales": 0},
            {"key": "kw_cap", "label": "KW CAP", "valor": 30.0, "tipo": "numero", "unidad": "kW", "decimales": 1},
            {"key": "kw_dist", "label": "kW DIST", "valor": 31.0, "tipo": "numero", "unidad": "kW", "decimales": 1},
        ],
        "metricas_grafica": [
            {"key": "consumo", "label": "Consumo", "unidad": "kWh", "decimales": 0},
            {"key": "kw_cap", "label": "KW CAP", "unidad": "kW", "decimales": 1},
        ],
        "comparativos": [],
        "alertas": [{"tipo": "success", "titulo": "Sin alertas relevantes", "detalle": "OK"}],
        "calidad_datos": {
            "disponibles": ["Consumo", "KW CAP", "kW DIST"],
            "faltantes": [],
            "limitaciones": ["GDMTO no se analiza con perfil horario base/intermedia/punta."],
        },
        "variacion_historico": {
            "disponible": True,
            "diferencia_estimada": 100.0,
            "costo_esperado": 5320.0,
            "costo_kwh_baseline": 1.18,
            "consumo_baseline": 4400.0,
            "variacion_consumo": 100.0,
        },
        "historial_extendido": {"disponible": False, "items": []},
        "graficas": {
            "labels": ["Feb-26", "Mar-26"],
            "metricas": {
                "consumo": {"label": "Consumo", "unidad": "kWh", "decimales": 0, "data": [4400.0, 4500.0], "promedio": 4450.0},
                "kw_cap": {"label": "KW CAP", "unidad": "kW", "decimales": 1, "data": [29.0, 30.0], "promedio": 29.5},
            },
            "perfil_horario": {"labels": [], "consumo": [], "costo": []},
            "desglose": {"labels": ["Energia"], "data": [4200.24]},
        },
    }

    html = env.get_template("cfe/partials/analisis_servicio.html").render(
        analisis=analisis,
        user={"user_name": "QA"},
    )

    assert "KW CAP" in html
    assert "kW DIST" in html
    assert "GDMTO no se analiza con perfil horario" in html
    assert ">Perfil horario</h2>" not in html
    assert "Diferencia estimada" in html
    assert "Ahorro estimado" not in html


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
                "total_descargas": 2,
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
    assert "/cfe/servicios/servicio-busqueda/analisis" in html
    assert "Análisis" in html
    assert "Descarga en curso" in html
    assert "/cfe/servicios/servicio-descarga/zip" in html
    assert "Descargar ZIP" in html
    assert 'hx-trigger="load, every 4s"' in html
