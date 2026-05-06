import pytest
from jinja2 import Environment, FileSystemLoader
from openpyxl import load_workbook

from modules.shared.services.cfe import CfeXmlInput, generar_excel_cfe
from modules.shared.services.cfe.extractor import extraer_datos_xml
from modules.shared.services.cfe.profiles import obtener_perfil_cfe


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


def test_extrae_datos_cfe_para_excel():
    datos = extraer_datos_xml(CFE_XML, "recibo.xml")

    importes = {linea["concepto"]: linea["importe"] for linea in datos["lineas_excel"]}
    assert datos["servicio"]["rpu"] == "123456789012"
    assert datos["periodo"]["mes_nombre"] == "Feb"
    assert importes["kWh base"] == 1000
    assert importes["Generación B"] == 100
    assert importes["Subtotal"] == 4490


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
