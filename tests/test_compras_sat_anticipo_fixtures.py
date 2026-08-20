from pathlib import Path
from decimal import Decimal

import pytest

from core.cfdi.extractor import parse_cfdi_xml


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "compras_sat_anticipo"


@pytest.mark.parametrize(
    ("filename", "expected_tipo", "expected_uuid", "expected_total"),
    [
        (
            "05_anticipo.xml",
            "ANTICIPO",
            "10000005-0000-4000-8000-000000000005",
            "11600.00",
        ),
        (
            "06_cierre_anticipo_relacion_07.xml",
            "CIERRE_ANTICIPO",
            "10000006-0000-4000-8000-000000000006",
            "11600.00",
        ),
        (
            "07_cierre_anticipo_sin_07.xml",
            "CIERRE_ANTICIPO",
            "10000007-0000-4000-8000-000000000007",
            "11600.00",
        ),
        (
            "08_cierre_anticipo_sin_07_pendiente.xml",
            "CIERRE_ANTICIPO",
            "10000008-0000-4000-8000-000000000008",
            "5800.00",
        ),
    ],
)
def test_compras_sat_anticipo_fixture_parsea_como_esperado(
    filename,
    expected_tipo,
    expected_uuid,
    expected_total,
):
    cfdi = parse_cfdi_xml((FIXTURE_DIR / filename).read_bytes(), filename)

    assert cfdi.uuid == expected_uuid
    assert cfdi.tipo_factura.value == expected_tipo
    assert cfdi.total == Decimal(expected_total)
