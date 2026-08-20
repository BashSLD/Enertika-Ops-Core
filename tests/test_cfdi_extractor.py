"""
Tests para el extractor de XML CFDI (core/cfdi/extractor.py).
Pruebas puras de parseo — sin BD ni I/O de red.
"""
import pytest
from decimal import Decimal

from core.cfdi.extractor import (
    parse_cfdi_xml,
    validate_xml_content,
    _safe_decimal,
    _detect_tipo_factura,
)
from core.cfdi.schemas import (
    CfdiConcepto,
    CfdiRelacionado,
    TipoFactura,
)


CFDI_40_NORMAL = b"""<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
    Version="4.0" Fecha="2025-01-15T10:30:00" Total="11600.00" SubTotal="10000.00"
    Moneda="MXN" MetodoPago="PUE" FormaPago="03" TipoDeComprobante="I">
  <cfdi:Emisor Rfc="AAA010101AAA" Nombre="Proveedor Demo SA de CV" RegimenFiscal="601"/>
  <cfdi:Receptor Rfc="BBB020202BBB" Nombre="Receptor Test SA" DomicilioFiscalReceptor="06600"
    RegimenFiscalReceptor="601" UsoCFDI="G03"/>
  <cfdi:Conceptos>
    <cfdi:Concepto ClaveProdServ="43211501" Cantidad="10" ClaveUnidad="H87"
      Unidad="Pieza" Descripcion="Material electrico tipo A"
      ValorUnitario="1000.00" Importe="10000.00"/>
  </cfdi:Conceptos>
  <cfdi:Complemento>
    <tfd:TimbreFiscalDigital UUID="AAAAAAAA-1111-2222-3333-444444444444"
      FechaTimbrado="2025-01-15T10:35:00" SelloCFD="abc" SelloSAT="def"
      NoCertificadoSAT="00001" Version="1.1"/>
  </cfdi:Complemento>
</cfdi:Comprobante>
"""

CFDI_ANTICIPO = b"""<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
    Version="4.0" Fecha="2025-02-01T08:00:00" Total="50000.00" SubTotal="43103.45"
    Moneda="MXN" TipoDeComprobante="I">
  <cfdi:Emisor Rfc="CCC030303CCC" Nombre="Proveedor Anticipos" RegimenFiscal="601"/>
  <cfdi:Receptor Rfc="BBB020202BBB" Nombre="Receptor Test SA" DomicilioFiscalReceptor="06600"
    RegimenFiscalReceptor="601" UsoCFDI="G03"/>
  <cfdi:Conceptos>
    <cfdi:Concepto ClaveProdServ="84111506" Cantidad="1" ClaveUnidad="ACT"
      Descripcion="Anticipo de obra electrica"
      ValorUnitario="43103.45" Importe="43103.45"/>
  </cfdi:Conceptos>
  <cfdi:Complemento>
    <tfd:TimbreFiscalDigital UUID="BBBBBBBB-1111-2222-3333-444444444444"
      FechaTimbrado="2025-02-01T08:05:00" SelloCFD="abc" SelloSAT="def"
      NoCertificadoSAT="00001" Version="1.1"/>
  </cfdi:Complemento>
</cfdi:Comprobante>
"""

CFDI_NOTA_CREDITO = b"""<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
    Version="4.0" Fecha="2025-03-01T12:00:00" Total="5000.00" SubTotal="4310.34"
    Moneda="MXN" TipoDeComprobante="E">
  <cfdi:CfdiRelacionados TipoRelacion="01">
    <cfdi:CfdiRelacionado UUID="AAAAAAAA-1111-2222-3333-444444444444"/>
  </cfdi:CfdiRelacionados>
  <cfdi:Emisor Rfc="AAA010101AAA" Nombre="Proveedor Demo SA de CV" RegimenFiscal="601"/>
  <cfdi:Receptor Rfc="BBB020202BBB" Nombre="Receptor Test SA" DomicilioFiscalReceptor="06600"
    RegimenFiscalReceptor="601" UsoCFDI="G02"/>
  <cfdi:Conceptos>
    <cfdi:Concepto ClaveProdServ="43211501" Cantidad="5" ClaveUnidad="H87"
      Descripcion="Devolucion material electrico"
      ValorUnitario="862.07" Importe="4310.34"/>
  </cfdi:Conceptos>
  <cfdi:Complemento>
    <tfd:TimbreFiscalDigital UUID="CCCCCCCC-1111-2222-3333-444444444444"
      FechaTimbrado="2025-03-01T12:05:00" SelloCFD="abc" SelloSAT="def"
      NoCertificadoSAT="00001" Version="1.1"/>
  </cfdi:Complemento>
</cfdi:Comprobante>
"""



class TestParseCfdiXml:

    def test_parse_cfdi_normal(self):
        result = parse_cfdi_xml(CFDI_40_NORMAL, "factura_normal.xml")

        assert result.uuid == "AAAAAAAA-1111-2222-3333-444444444444"
        assert result.emisor_rfc == "AAA010101AAA"
        assert result.emisor_nombre == "Proveedor Demo SA de CV"
        assert result.receptor_rfc == "BBB020202BBB"
        assert result.total == Decimal("11600.00")
        assert result.moneda == "MXN"
        assert result.tipo_factura == TipoFactura.NORMAL
        assert len(result.conceptos) == 1
        assert result.conceptos[0].descripcion == "Material electrico tipo A"
        assert result.conceptos[0].clave_prod_serv == "43211501"

    def test_parse_cfdi_anticipo(self):
        result = parse_cfdi_xml(CFDI_ANTICIPO, "anticipo.xml")

        assert result.uuid == "BBBBBBBB-1111-2222-3333-444444444444"
        assert result.tipo_factura == TipoFactura.ANTICIPO
        assert result.total == Decimal("50000.00")
        assert result.conceptos[0].clave_prod_serv == "84111506"

    def test_parse_cfdi_nota_credito(self):
        result = parse_cfdi_xml(CFDI_NOTA_CREDITO, "nota_credito.xml")

        assert result.uuid == "CCCCCCCC-1111-2222-3333-444444444444"
        assert result.tipo_factura == TipoFactura.NOTA_CREDITO
        assert result.tipo_comprobante == "E"
        assert len(result.relacionados) == 1
        assert result.relacionados[0].tipo_relacion == "01"

    def test_parse_xml_malformado_raises(self):
        with pytest.raises(ValueError, match="XML mal formado"):
            parse_cfdi_xml(b"<broken>not closed", "bad.xml")

    def test_parse_xml_sin_uuid_raises(self):
        xml_sin_timbre = b"""<?xml version="1.0" encoding="UTF-8"?>
        <cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
            Total="100" Fecha="2025-01-01">
          <cfdi:Emisor Rfc="AAA010101AAA" Nombre="Test"/>
          <cfdi:Receptor Rfc="BBB020202BBB" Nombre="Test2"/>
          <cfdi:Conceptos>
            <cfdi:Concepto Descripcion="Item" Cantidad="1" ValorUnitario="100" Importe="100"/>
          </cfdi:Conceptos>
        </cfdi:Comprobante>
        """
        with pytest.raises(ValueError, match="UUID"):
            parse_cfdi_xml(xml_sin_timbre, "sin_uuid.xml")

    def test_parse_xml_excede_tamano_raises(self):
        huge = b"x" * (10 * 1024 * 1024 + 1)
        with pytest.raises(ValueError, match="limite"):
            parse_cfdi_xml(huge, "huge.xml")



class TestHelpers:

    def test_safe_decimal_valid(self):
        assert _safe_decimal("123.45") == Decimal("123.45")

    def test_safe_decimal_none(self):
        assert _safe_decimal(None) is None

    def test_safe_decimal_invalid(self):
        assert _safe_decimal("not_a_number", Decimal("0")) == Decimal("0")

    def test_validate_xml_content_valid(self):
        assert validate_xml_content(CFDI_40_NORMAL, "test.xml") is None

    def test_validate_xml_content_too_small(self):
        assert validate_xml_content(b"<xml/>", "tiny.xml") is not None

    def test_validate_xml_content_not_cfdi(self):
        non_cfdi = b"<root>" + b"x" * 200 + b"</root>"
        assert validate_xml_content(non_cfdi, "not_cfdi.xml") is not None


class TestDetectTipoFactura:

    def test_normal_sin_relaciones(self):
        result = _detect_tipo_factura([], [], "I")
        assert result == TipoFactura.NORMAL

    def test_anticipo_por_clave_sat(self):
        concepto = CfdiConcepto(
            descripcion="Anticipo de proyecto",
            cantidad=Decimal("1"),
            valor_unitario=Decimal("1000"),
            importe=Decimal("1000"),
            clave_prod_serv="84111506",
        )
        result = _detect_tipo_factura([concepto], [], "I")
        assert result == TipoFactura.ANTICIPO

    def test_nota_credito_tipo_e_relacion_01(self):
        rel = CfdiRelacionado(uuid="AAA-BBB", tipo_relacion="01")
        result = _detect_tipo_factura([], [rel], "E")
        assert result == TipoFactura.NOTA_CREDITO

    def test_cierre_anticipo_relacion_07(self):
        rel = CfdiRelacionado(uuid="AAA-BBB", tipo_relacion="07")
        result = _detect_tipo_factura([], [rel], "I")
        assert result == TipoFactura.CIERRE_ANTICIPO

    def test_cierre_anticipo_por_descripcion_sin_relacion_07(self):
        concepto = CfdiConcepto(
            descripcion="Cierre de anticipo de proyecto",
            cantidad=Decimal("1"),
            valor_unitario=Decimal("1000"),
            importe=Decimal("1000"),
            clave_prod_serv="72151500",
        )
        result = _detect_tipo_factura([concepto], [], "I")
        assert result == TipoFactura.CIERRE_ANTICIPO
