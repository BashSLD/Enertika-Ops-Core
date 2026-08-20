"""
Cobertura directa de `core.cfdi.service.validar_datos_fiscales_receptor` (0% de
cobertura directa antes del refactor a core/cfdi/ -- solo se ejercitaba
indirectamente via RFC con los demas campos en None, ver
tests/test_compras_rfc_receptor.py). Cubre las 5 reglas completas, el caso
PENDIENTE_CONFIGURAR centralizado, y los toggles exigir_uso_cfdi/exigir_forma_pago.
"""

from decimal import Decimal

import pytest

from core.cfdi.schemas import CfdiData
from core.cfdi.service import validar_datos_fiscales_receptor


EMPRESA = {
    "rfc": "ENE010101AAA",
    "razon_social": "ENERTIKA MEXICO",
    "codigo_postal": "11560",
    "regimen_fiscal": "601",
}


def _cfdi(**overrides) -> CfdiData:
    base = dict(
        archivo="factura.xml",
        uuid="AAAAAAAA-1111-2222-3333-444444444444",
        fecha="2026-01-01",
        total=Decimal("1000"),
        emisor_rfc="PPP010101PPP",
        emisor_nombre="Proveedor",
        receptor_rfc="ENE010101AAA",
        receptor_nombre="ENERTIKA MEXICO",
        receptor_cp="11560",
        receptor_regimen_fiscal="601",
        uso_cfdi="G03",
        metodo_pago="PUE",
        forma_pago="03",
        tipo_comprobante="I",
    )
    base.update(overrides)
    return CfdiData(**base)


class TestReglasIndividuales:

    def test_cfdi_valido_sin_errores(self):
        assert validar_datos_fiscales_receptor(_cfdi(), EMPRESA) == []

    def test_rfc_receptor_distinto(self):
        errores = validar_datos_fiscales_receptor(_cfdi(receptor_rfc="ZZZ999999ZZZ"), EMPRESA)
        assert [codigo for codigo, _ in errores] == ["RFC_RECEPTOR"]

    def test_razon_social_distinta(self):
        errores = validar_datos_fiscales_receptor(_cfdi(receptor_nombre="OTRA EMPRESA SA"), EMPRESA)
        assert [codigo for codigo, _ in errores] == ["RAZON_SOCIAL_RECEPTOR"]

    def test_cp_distinto(self):
        errores = validar_datos_fiscales_receptor(_cfdi(receptor_cp="99999"), EMPRESA)
        assert [codigo for codigo, _ in errores] == ["CP_RECEPTOR"]

    def test_regimen_fiscal_distinto(self):
        errores = validar_datos_fiscales_receptor(_cfdi(receptor_regimen_fiscal="612"), EMPRESA)
        assert [codigo for codigo, _ in errores] == ["REGIMEN_RECEPTOR"]

    def test_uso_cfdi_distinto_de_g03(self):
        errores = validar_datos_fiscales_receptor(_cfdi(uso_cfdi="G01"), EMPRESA)
        assert [codigo for codigo, _ in errores] == ["USO_CFDI"]

    def test_uso_cfdi_no_se_valida_en_tipo_pago(self):
        # Tipo P siempre trae UsoCFDI=CP01 por regla SAT -- no debe compararse contra G03.
        errores = validar_datos_fiscales_receptor(
            _cfdi(uso_cfdi="CP01", tipo_comprobante="P"), EMPRESA
        )
        assert errores == []

    def test_forma_pago_distinta_con_pue(self):
        errores = validar_datos_fiscales_receptor(
            _cfdi(metodo_pago="PUE", forma_pago="99"), EMPRESA
        )
        assert [codigo for codigo, _ in errores] == ["FORMA_PAGO"]

    def test_forma_pago_no_se_valida_con_ppd(self):
        # Con PPD, FormaPago=99 es correcto -- la transferencia real llega con el
        # complemento de pago despues.
        errores = validar_datos_fiscales_receptor(
            _cfdi(metodo_pago="PPD", forma_pago="99"), EMPRESA
        )
        assert errores == []

    def test_multiples_errores_simultaneos(self):
        errores = validar_datos_fiscales_receptor(
            _cfdi(receptor_rfc="ZZZ999999ZZZ", receptor_cp="99999"), EMPRESA
        )
        codigos = {codigo for codigo, _ in errores}
        assert codigos == {"RFC_RECEPTOR", "CP_RECEPTOR"}


class TestPendienteConfigurar:

    def test_empresa_none_no_evalua_nada(self):
        assert validar_datos_fiscales_receptor(_cfdi(receptor_rfc="ZZZ999999ZZZ"), None) == []

    def test_rfc_pendiente_configurar_no_evalua_nada(self):
        errores = validar_datos_fiscales_receptor(
            _cfdi(receptor_rfc="ZZZ999999ZZZ"), {"rfc": "PENDIENTE_CONFIGURAR"}
        )
        assert errores == []


class TestTogglesExtension:
    """exigir_uso_cfdi/exigir_forma_pago: default True preserva el comportamiento
    actual de Compras/Finanzas; False es el punto de extension documentado para
    un futuro consumidor con reglas propias (ej. Construccion) -- sin implementar
    todavia, ver decision 2 del plan."""

    def test_exigir_uso_cfdi_false_ignora_mismatch(self):
        errores = validar_datos_fiscales_receptor(
            _cfdi(uso_cfdi="G01"), EMPRESA, exigir_uso_cfdi=False
        )
        assert errores == []

    def test_exigir_forma_pago_false_ignora_mismatch(self):
        errores = validar_datos_fiscales_receptor(
            _cfdi(metodo_pago="PUE", forma_pago="99"), EMPRESA, exigir_forma_pago=False
        )
        assert errores == []
