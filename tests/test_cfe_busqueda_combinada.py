from modules.cfe.scraper import (
    DescargaPeriodoPublicoResult,
    ResultadoBusquedaPeriodos,
    _advertencia_discrepancia,
    _otras_facturas_por_periodo,
)
from modules.shared.services.cfe.extractor import candidatos_total_a_pagar


def test_advertencia_discrepancia_avisa_cuando_difieren():
    assert _advertencia_discrepancia(publico=14, miespacio=12) == (
        "El portal publico mostro 14 periodos y MiEspacio 12. "
        "Pueden faltar archivos en alguno de los dos."
    )


def test_advertencia_discrepancia_none_cuando_coinciden():
    assert _advertencia_discrepancia(publico=12, miespacio=12) is None


def test_advertencia_discrepancia_none_si_miespacio_desconocido():
    # -1 = no se pudo abrir MiEspacio; no se avisa discrepancia
    assert _advertencia_discrepancia(publico=12, miespacio=-1) is None


def test_wrapper_resultado_guarda_periodos_y_advertencia():
    r = ResultadoBusquedaPeriodos(
        periodos=[DescargaPeriodoPublicoResult(periodo="2026-05")],
        advertencia="x",
    )
    assert r.periodos[0].periodo == "2026-05"
    assert r.advertencia == "x"


def _xml_con_totales(
    imptotal: str = "",
    imptotalxml: str = "",
    total_sin_ade: str = "",
) -> bytes:
    campos_total = "".join(
        f"<{campo}>{valor}</{campo}>"
        for campo, valor in (
            ("IMPTOTAL", imptotal),
            ("IMPTOTALXML", imptotalxml),
            ("TOTAL_SIN_ADE", total_sin_ade),
        )
        if valor
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" '
        'Folio="1" Total="2345.90" SubTotal="2345.90">'
        "<Complemento><clsRegArchFact><TARIFA_REG>GDMTO</TARIFA_REG>"
        f"<RPU>123</RPU>{campos_total}</clsRegArchFact></Complemento>"
        "</cfdi:Comprobante>"
    ).encode("utf-8")


def test_candidatos_total_a_pagar_prioriza_y_deduplica():
    xml = _xml_con_totales(
        imptotal="2345.90",
        imptotalxml="2345",
        total_sin_ade="1000.50",
    )

    assert candidatos_total_a_pagar(xml, "recibo.xml") == ["2345", "1000"]


def test_candidatos_total_a_pagar_vacio_si_no_hay_campos():
    assert candidatos_total_a_pagar(_xml_con_totales(), "recibo.xml") == []


def test_otras_facturas_por_periodo_solo_filas_con_pdf_y_xml():
    rows = [
        # PA mayo: recibo real (PDF+XML) -> se queda
        {"serie": "PA", "folio": "000001", "anio_mes": "MAY 2026", "pdf_id": "p_may", "xml_id": "x_may"},
        # PZ mayo: complementaria solo XML -> se descarta
        {"serie": "PZ", "folio": "000002", "anio_mes": "MAY 2026", "pdf_id": "", "xml_id": "x_pz"},
        # GI abril: recibo real
        {"serie": "GI", "folio": "000003", "anio_mes": "ABR 2026", "pdf_id": "p_abr", "xml_id": "x_abr"},
        # fila sin periodo reconocible -> se ignora
        {"serie": "GI", "folio": "000004", "anio_mes": "", "pdf_id": "p_x", "xml_id": "x_x"},
    ]
    out = _otras_facturas_por_periodo(rows)
    assert [r["periodo"] for r in out] == ["2026-05", "2026-04"]  # orden desc
    assert out[0]["pdf_id"] == "p_may" and out[0]["xml_id"] == "x_may"
    assert out[0]["etiqueta"] == "May 2026"


def test_otras_facturas_por_periodo_dedup_por_folio_mas_reciente():
    rows = [
        {"serie": "PA", "folio": "000010", "anio_mes": "MAY 2026", "pdf_id": "p1", "xml_id": "x1"},
        {"serie": "PA", "folio": "000020", "anio_mes": "MAY 2026", "pdf_id": "p2", "xml_id": "x2"},
    ]
    out = _otras_facturas_por_periodo(rows)
    assert len(out) == 1
    assert out[0]["folio"] == "000020"  # folio mas alto gana
