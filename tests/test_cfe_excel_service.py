from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader
from openpyxl import load_workbook

from modules.shared.services.cfe import CfeXmlInput, generar_excel_cfe
from modules.shared.services.cfe.extractor import extraer_datos_xml
from modules.shared.services.cfe.profiles import obtener_perfil_cfe


CFE_REAL_DIR = Path("CFE")
CFE_REAL_GDMTO_XML = CFE_REAL_DIR / "JB-000090976983(3).xml"

CFE_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    Serie="GC" Folio="12345" Fecha="2025-02-28T10:30:00"
    SubTotal="4490.00" Total="5208.40" Moneda="MXN" MetodoPago="PUE" FormaPago="03">
  <cfdi:Emisor Rfc="CFE370814QI0" Nombre="COMISION FEDERAL DE ELECTRICIDAD"/>
  <cfdi:Receptor Rfc="AAA010101AAA" Nombre="CLIENTE PRUEBA" UsoCFDI="G03"/>
  <cfdi:Conceptos>
    <cfdi:Concepto ClaveUnidad="E48" Cantidad="1" Descripcion="Servicio de energia electrica" Importe="4490.00"/>
  </cfdi:Conceptos>
  <cfdi:Impuestos TotalImpuestosTrasladados="718.40"/>
  <cfdi:Complemento>
    <cfe:clsRegArchFact xmlns:cfe="https://www.cfe.mx/cfd/recibo">
      <TARIFA_REG>GDMTH</TARIFA_REG>
      <TARIFA>GDMTH</TARIFA>
      <RPU>123456789012</RPU>
      <FECDESDE>01 FEB 25</FECDESDE>
      <FECHASTA>28 FEB 25</FECHASTA>
      <FECLIMITE>15 MAR 25</FECLIMITE>
      <FECORTE>16 MAR 25</FECORTE>
      <NUMMED1>MED123</NUMMED1>
      <HILOS>3</HILOS>
      <CONSUMO_R>6000</CONSUMO_R>
      <CONSUMO3F>1000</CONSUMO3F>
      <CONSUMO2F>2000</CONSUMO2F>
      <CONSUMO1F>3000</CONSUMO1F>
      <DEMANDA>22</DEMANDA>
      <DEMANDA3P>10</DEMANDA3P>
      <DEMANDA2P>15</DEMANDA2P>
      <DEMANDA1P>20</DEMANDA1P>
      <KVARH>400</KVARH>
      <FacPot>95.5</FacPot>
      <MOTIVO_REG_1>EGB</MOTIVO_REG_1>
      <IMPTE_TOT_REG_1>100.00</IMPTE_TOT_REG_1>
      <MOTIVO_REG_2>EGI</MOTIVO_REG_2>
      <IMPTE_TOT_REG_2>200.00</IMPTE_TOT_REG_2>
      <MOTIVO_REG_3>EGP</MOTIVO_REG_3>
      <IMPTE_TOT_REG_3>300.00</IMPTE_TOT_REG_3>
      <MOTIVO_REG_4>ETB</MOTIVO_REG_4>
      <IMPTE_TOT_REG_4>400.00</IMPTE_TOT_REG_4>
      <MOTIVO_REG_5>ED1</MOTIVO_REG_5>
      <IMPTE_TOT_REG_5>500.00</IMPTE_TOT_REG_5>
      <MOTIVO_REG_6>EID</MOTIVO_REG_6>
      <IMPTE_TOT_REG_6>600.00</IMPTE_TOT_REG_6>
      <MOTIVO_REG_7>EMB</MOTIVO_REG_7>
      <IMPTE_TOT_REG_7>700.00</IMPTE_TOT_REG_7>
      <MOTIVO_REG_8>ES1</MOTIVO_REG_8>
      <IMPTE_TOT_REG_8>800.00</IMPTE_TOT_REG_8>
      <MOTIVO_REG_9>ECB</MOTIVO_REG_9>
      <IMPTE_TOT_REG_9>900.00</IMPTE_TOT_REG_9>
      <Conceptos>
        <Concepto1>2% Baja Tension((3))</Concepto1>
        <Concepto2>Bonificacion Factor de Potencia((3))</Concepto2>
        <Concepto3>Subtotal</Concepto3>
      </Conceptos>
      <Importes>
        <Importe1>20.00</Importe1>
        <Importe2>-30.00</Importe2>
        <Importe3>4490.00</Importe3>
      </Importes>
    </cfe:clsRegArchFact>
  </cfdi:Complemento>
</cfdi:Comprobante>
"""

NON_CFE_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
    Version="4.0" Fecha="2025-03-01T12:00:00" Total="100.00"
    SubTotal="86.21" Moneda="MXN" TipoDeComprobante="I">
  <cfdi:Emisor Rfc="AAA010101AAA" Nombre="Proveedor No CFE"/>
  <cfdi:Receptor Rfc="BBB020202BBB" Nombre="Cliente"/>
  <cfdi:Conceptos>
    <cfdi:Concepto Descripcion="Servicio no CFE" Cantidad="1" ValorUnitario="86.21" Importe="86.21"/>
  </cfdi:Conceptos>
  <cfdi:Complemento>
    <tfd:TimbreFiscalDigital UUID="AAAAAAAA-1111-2222-3333-444444444444" Version="1.1"/>
  </cfdi:Complemento>
</cfdi:Comprobante>
"""


CFE_GDMTO_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    Serie="GC" Folio="67890" Fecha="2026-03-31T10:30:00"
    SubTotal="4500.00" Total="5220.00" Moneda="MXN" MetodoPago="PUE" FormaPago="03">
  <cfdi:Emisor Rfc="CFE370814QI0" Nombre="COMISION FEDERAL DE ELECTRICIDAD"/>
  <cfdi:Receptor Rfc="AAA010101AAA" Nombre="CLIENTE PRUEBA" UsoCFDI="G03"/>
  <cfdi:Conceptos>
    <cfdi:Concepto ClaveUnidad="E48" Cantidad="1" Descripcion="Servicio de energia electrica" Importe="4500.00"/>
  </cfdi:Conceptos>
  <cfdi:Impuestos TotalImpuestosTrasladados="720.00"/>
  <cfdi:Complemento>
    <cfe:clsRegArchFact xmlns:cfe="https://www.cfe.mx/cfd/recibo">
      <TARIFA_REG>GDMTO</TARIFA_REG>
      <TARIFA>GDMTO</TARIFA>
      <RPU>226160800958</RPU>
      <FECDESDE>01 MAR 26</FECDESDE>
      <FECHASTA>31 MAR 26</FECHASTA>
      <FECLIMITE>15 ABR 26</FECLIMITE>
      <FECORTE>16 ABR 26</FECORTE>
      <NUMMED1>MED456</NUMMED1>
      <HILOS>3</HILOS>
      <CONSUMO_R>4500</CONSUMO_R>
      <DEMANDA>28</DEMANDA>
      <DEMANDA_CAPACIDAD>30</DEMANDA_CAPACIDAD>
      <DEMANDA_DISTRIBUCION>31</DEMANDA_DISTRIBUCION>
      <FacPot>97.1</FacPot>
      <MESR01>MAR</MESR01>
      <CONSUMOR01>4500</CONSUMOR01>
      <DEMANDAR01>28</DEMANDAR01>
      <FACPOTR01>97.1</FACPOTR01>
      <FACARR01>42.5</FACARR01>
      <PMVR01>3.14</PMVR01>
      <MESR02>FEB</MESR02>
      <CONSUMOR02>4100</CONSUMOR02>
      <DEMANDAR02>26</DEMANDAR02>
      <FACPOTR02>96.8</FACPOTR02>
      <FACARR02>41.2</FACARR02>
      <PMVR02>3.01</PMVR02>
      <MOTIVO_REG_1>ES1</MOTIVO_REG_1>
      <IMPTE_TOT_REG_1>100.00</IMPTE_TOT_REG_1>
      <MOTIVO_REG_2>ED1</MOTIVO_REG_2>
      <IMPTE_TOT_REG_2>200.00</IMPTE_TOT_REG_2>
      <MOTIVO_REG_3>ETB</MOTIVO_REG_3>
      <IMPTE_TOT_REG_3>300.00</IMPTE_TOT_REG_3>
      <MOTIVO_REG_4>ECB</MOTIVO_REG_4>
      <IMPTE_TOT_REG_4>40.00</IMPTE_TOT_REG_4>
      <MOTIVO_REG_5>EID</MOTIVO_REG_5>
      <IMPTE_TOT_REG_5>50.00</IMPTE_TOT_REG_5>
      <MOTIVO_REG_6>EMB</MOTIVO_REG_6>
      <IMPTE_TOT_REG_6>60.00</IMPTE_TOT_REG_6>
      <MOTIVO_REG_7>EG1</MOTIVO_REG_7>
      <IMPTE_TOT_REG_7>4200.24</IMPTE_TOT_REG_7>
      <MOTIVO_REG_8>X08</MOTIVO_REG_8>
      <IMPTE_TOT_REG_8>8.00</IMPTE_TOT_REG_8>
      <MOTIVO_REG_9>X09</MOTIVO_REG_9>
      <IMPTE_TOT_REG_9>9.00</IMPTE_TOT_REG_9>
      <MOTIVO_REG_10>X10</MOTIVO_REG_10>
      <IMPTE_TOT_REG_10>10.00</IMPTE_TOT_REG_10>
      <MOTIVO_REG_11>X11</MOTIVO_REG_11>
      <IMPTE_TOT_REG_11>11.00</IMPTE_TOT_REG_11>
      <MOTIVO_REG_12>X12</MOTIVO_REG_12>
      <IMPTE_TOT_REG_12>12.00</IMPTE_TOT_REG_12>
      <MOTIVO_REG_13>X13</MOTIVO_REG_13>
      <IMPTE_TOT_REG_13>13.00</IMPTE_TOT_REG_13>
      <MOTIVO_REG_14>X14</MOTIVO_REG_14>
      <IMPTE_TOT_REG_14>14.00</IMPTE_TOT_REG_14>
      <MOTIVO_REG_15>X15</MOTIVO_REG_15>
      <IMPTE_TOT_REG_15>15.00</IMPTE_TOT_REG_15>
      <MOTIVO_REG_16>X16</MOTIVO_REG_16>
      <IMPTE_TOT_REG_16>16.00</IMPTE_TOT_REG_16>
      <MOTIVO_REG_17>X17</MOTIVO_REG_17>
      <IMPTE_TOT_REG_17>17.00</IMPTE_TOT_REG_17>
      <MOTIVO_REG_18>X18</MOTIVO_REG_18>
      <IMPTE_TOT_REG_18>18.00</IMPTE_TOT_REG_18>
      <MOTIVO_REG_19>X19</MOTIVO_REG_19>
      <IMPTE_TOT_REG_19>19.00</IMPTE_TOT_REG_19>
      <MOTIVO_REG_20>ET1</MOTIVO_REG_20>
      <IMPTE_TOT_REG_20>700.00</IMPTE_TOT_REG_20>
      <Conceptos>
        <Concepto1>Subtotal</Concepto1>
        <Concepto2>2% Baja Tension((3))</Concepto2>
        <Concepto3>Bonificacion Factor de Potencia((3))</Concepto3>
        <Concepto4>Cargo 4</Concepto4>
        <Concepto5>Cargo 5</Concepto5>
        <Concepto6>Cargo 6</Concepto6>
        <Concepto7>Cargo 7</Concepto7>
        <Concepto8>Cargo 8</Concepto8>
        <Concepto9>Cargo 9</Concepto9>
        <Concepto10>Cargo 10</Concepto10>
        <Concepto11>Cargo 11</Concepto11>
        <Concepto12>Cargo 12</Concepto12>
        <Concepto13>Cargo 13</Concepto13>
        <Concepto14>Cargo 14</Concepto14>
        <Concepto15>Cargo 15</Concepto15>
        <Concepto16>Cargo 16</Concepto16>
        <Concepto17>Cargo 17</Concepto17>
        <Concepto18>Cargo 18</Concepto18>
        <Concepto19>Cargo 19</Concepto19>
        <Concepto20>Cargo dinamico</Concepto20>
      </Conceptos>
      <Importes>
        <Importe1>4500.00</Importe1>
        <Importe2>20.00</Importe2>
        <Importe3>-10.00</Importe3>
        <Importe4>4.00</Importe4>
        <Importe5>5.00</Importe5>
        <Importe6>6.00</Importe6>
        <Importe7>7.00</Importe7>
        <Importe8>8.00</Importe8>
        <Importe9>9.00</Importe9>
        <Importe10>10.00</Importe10>
        <Importe11>11.00</Importe11>
        <Importe12>12.00</Importe12>
        <Importe13>13.00</Importe13>
        <Importe14>14.00</Importe14>
        <Importe15>15.00</Importe15>
        <Importe16>16.00</Importe16>
        <Importe17>17.00</Importe17>
        <Importe18>18.00</Importe18>
        <Importe19>19.00</Importe19>
        <Importe20>20.00</Importe20>
      </Importes>
    </cfe:clsRegArchFact>
  </cfdi:Complemento>
</cfdi:Comprobante>
"""


def _valor_en_fila(ws, header: str, row: int = 2):
    headers = [cell.value for cell in ws[1]]
    return ws.cell(row=row, column=headers.index(header) + 1).value


def test_extrae_datos_cfe_para_excel():
    datos = extraer_datos_xml(CFE_XML, "recibo.xml")

    importes = {linea["concepto"]: linea["importe"] for linea in datos["lineas_excel"]}
    assert datos["servicio"]["rpu"] == "123456789012"
    assert datos["periodo"]["mes_nombre"] == "Feb"
    assert importes["kWh base"] == 1000
    assert importes["Generación B"] == 100
    assert importes["Subtotal"] == 4490


def test_extrae_gdmto_demandas_historial_y_campos_dinamicos():
    datos = extraer_datos_xml(CFE_GDMTO_XML, "gdmto.xml")

    assert datos["servicio"]["tarifa"] == "GDMTO"
    assert datos["servicio"]["tarifa_reconocida"] is True
    assert datos["medicion"]["demanda_capacidad"] == 30
    assert datos["medicion"]["demanda_distribucion"] == 31
    assert datos["historial"] == [
        {
            "mes": "MAR",
            "consumo_kwh": 4500,
            "demanda_kw": 28,
            "factor_potencia_pct": 97.1,
            "factor_carga_pct": 42.5,
            "precio_medio_mxn": 3.14,
        },
        {
            "mes": "FEB",
            "consumo_kwh": 4100,
            "demanda_kw": 26,
            "factor_potencia_pct": 96.8,
            "factor_carga_pct": 41.2,
            "precio_medio_mxn": 3.01,
        },
    ]
    assert datos["componentes_tarifarios"][-1]["codigo"] == "ET1"
    importes = {linea["concepto"]: linea["importe"] for linea in datos["lineas_excel"]}
    assert importes["Generación I"] == 4200.24
    assert any(
        concepto["concepto"] == "Cargo dinamico"
        for concepto in datos["conceptos_importes"]
    )


def test_generar_excel_gdmto_usa_directos_na_e_historial():
    buffer = generar_excel_cfe(
        [CfeXmlInput(filename="gdmto.xml", content=CFE_GDMTO_XML)],
        perfil_slug="simulacion",
        modo_calculo="calculado",
    )
    wb = load_workbook(buffer, data_only=False)
    ws = wb.active

    assert ws.title == "226160800958"
    assert _valor_en_fila(ws, "Mes") == "Mar-26"
    assert _valor_en_fila(ws, "Consumo") == 4500
    assert _valor_en_fila(ws, "Consumo Base") == "N/A"
    assert _valor_en_fila(ws, "Potencia Base") == "N/A"
    assert _valor_en_fila(ws, "Reactiva") == "N/A"
    assert _valor_en_fila(ws, "KW CAP") == 30
    assert _valor_en_fila(ws, "kW DIST") == 31
    assert _valor_en_fila(ws, "Coste Energía (Intermedia)") == 4200.24

    hojas_historial = [name for name in wb.sheetnames if "Historial" in name]
    assert hojas_historial == ["226160800958 Historial"]
    historial = wb[hojas_historial[0]]
    assert [cell.value for cell in historial[1]] == [
        "Mes",
        "Consumo kWh",
        "Demanda kW",
        "Factor Potencia %",
        "Factor Carga %",
        "Precio Medio MXN",
    ]
    assert historial.max_row == 3
    assert historial["A2"].value == "MAR"
    assert historial["B2"].value == 4500


def test_generar_excel_gdmto_formulas_conserva_valores_directos():
    buffer = generar_excel_cfe(
        [CfeXmlInput(filename="gdmto.xml", content=CFE_GDMTO_XML)],
        perfil_slug="simulacion",
        modo_calculo="formulas",
    )
    wb = load_workbook(buffer, data_only=False)
    ws = wb.active

    assert _valor_en_fila(ws, "Consumo") == 4500
    assert _valor_en_fila(ws, "KW CAP") == 30
    assert _valor_en_fila(ws, "kW DIST") == 31


def test_gdmth_no_remapea_eg1_como_generacion_intermedia():
    xml = CFE_XML.replace(
        b"<MOTIVO_REG_2>EGI</MOTIVO_REG_2>",
        b"<MOTIVO_REG_2>EG1</MOTIVO_REG_2>",
    )
    datos = extraer_datos_xml(xml, "gdmth-eg1.xml")

    importes = {linea["concepto"]: linea["importe"] for linea in datos["lineas_excel"]}
    assert importes["Generacion"] == 200
    assert "Generación I" not in importes


@pytest.mark.skipif(
    not CFE_REAL_GDMTO_XML.exists(),
    reason="XML real GDMTO no disponible",
)
def test_xml_real_gdmto_eg1_alimenta_coste_energia_intermedia():
    content = CFE_REAL_GDMTO_XML.read_bytes()
    buffer = generar_excel_cfe(
        [CfeXmlInput(filename="JB-000090976983(3).xml", content=content)],
        perfil_slug="simulacion",
        modo_calculo="calculado",
    )
    wb = load_workbook(buffer, data_only=False)
    ws = wb.active

    assert _valor_en_fila(ws, "Coste Energía (Intermedia)") == 4200.24


def test_generar_excel_simulacion_calculado():
    buffer = generar_excel_cfe(
        [CfeXmlInput(filename="recibo.xml", content=CFE_XML)],
        perfil_slug="simulacion",
        modo_calculo="calculado",
    )
    wb = load_workbook(buffer, data_only=False)
    ws = wb.active
    headers = [cell.value for cell in ws[1]]

    assert headers[-1] == "Observaciones"
    assert headers == [column.header for column in obtener_perfil_cfe("simulacion").columns]
    assert ws["A2"].value == "Feb-25"
    assert ws["B2"].value == 6000
    assert ws["I2"].value == 28
    assert ws["J2"].value == 16
    assert ws["K2"].value == 16
    assert ws["Z2"].value == 4490
    assert "Tarifa: GDMTH" in ws["AA2"].value


def test_generar_excel_oym_mantiene_observaciones():
    buffer = generar_excel_cfe(
        [CfeXmlInput(filename="recibo.xml", content=CFE_XML)],
        perfil_slug="oym",
        modo_calculo="calculado",
    )
    wb = load_workbook(buffer, data_only=False)
    ws = wb.active
    headers = [cell.value for cell in ws[1]]

    assert headers[-1] == "Observaciones"
    assert "Tarifa: GDMTH" in ws.cell(row=2, column=len(headers)).value


def test_generar_excel_omite_xml_no_cfe_y_procesa_validos():
    buffer = generar_excel_cfe(
        [
            CfeXmlInput(filename="proveedor.xml", content=NON_CFE_XML),
            CfeXmlInput(filename="recibo.xml", content=CFE_XML),
        ],
        perfil_slug="simulacion",
        modo_calculo="calculado",
    )
    wb = load_workbook(buffer, data_only=False)

    assert "Validacion" in wb.sheetnames
    ws = wb.active
    assert ws.max_row == 2
    assert ws["A2"].value == "Feb-25"

    validacion = wb["Validacion"]
    assert validacion["A2"].value == "proveedor.xml"
    assert validacion["B2"].value == "Omitido"
    assert validacion["C2"].value == "No es un XML de recibo CFE"
    assert validacion["A3"].value == "recibo.xml"
    assert validacion["B3"].value == "Procesado"


def test_generar_excel_error_si_no_hay_xml_cfe():
    with pytest.raises(ValueError, match="No se encontraron XML de CFE válidos"):
        generar_excel_cfe(
            [CfeXmlInput(filename="proveedor.xml", content=NON_CFE_XML)],
            perfil_slug="simulacion",
            modo_calculo="calculado",
        )


def test_generar_excel_soporta_formulas_internas():
    buffer = generar_excel_cfe(
        [CfeXmlInput(filename="recibo.xml", content=CFE_XML)],
        perfil_slug="simulacion",
        modo_calculo="formulas",
    )
    wb = load_workbook(buffer, data_only=False)
    ws = wb.active

    assert ws["B2"].value == "=SUM(C2,D2,E2)"
    assert ws["J2"].value.startswith("=ROUNDUP(MIN(")
    assert ws["K2"].value.startswith("=ROUNDUP(MIN(MAX(")


def test_generar_excel_rechaza_modo_invalido():
    with pytest.raises(ValueError, match="Modo de Excel CFE no soportado"):
        generar_excel_cfe(
            [CfeXmlInput(filename="recibo.xml", content=CFE_XML)],
            perfil_slug="simulacion",
            modo_calculo="mixto",
        )


def test_modal_cfe_compila_con_contexto_de_modulo():
    env = Environment(loader=FileSystemLoader("templates"))
    template = env.get_template("shared/modals/cfe_upload_modal.html")

    html = template.render(
        module_slug="simulacion",
        module_label="Simulación",
        post_url="/simulacion/cfe/excel",
        accent="indigo",
    )

    assert "Recibos CFE - Simulación" in html
    assert "/simulacion/cfe/excel" in html
