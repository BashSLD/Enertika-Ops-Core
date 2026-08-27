"""
Tests de la captura asistida por PDF en cotizaciones de proveedor (BOM/Compras):
extraccion de precios candidatos (core/bom/pdf_cotizacion_extractor.py, funciones
puras sin pdfplumber) y el gate de content-type/tamano en el service
(extraer_costos_pdf_cotizacion, core/bom/compras_service.py).
"""

import pytest

from core.bom.pdf_cotizacion_extractor import (
    _candidatos_de_texto,
    _detectar_moneda,
    _parse_precio,
)
from core.bom.service import BomService
import core.bom.compras_service as compras_service_module


def test_parse_precio_extrae_numero_con_centavos():
    assert _parse_precio("$1,234.56") == 1234.56
    assert _parse_precio("1234.56") == 1234.56


def test_parse_precio_none_si_no_hay_numero_con_centavos():
    assert _parse_precio("sin precio aqui") is None
    assert _parse_precio("") is None
    assert _parse_precio(None) is None


def test_detectar_moneda_usd():
    assert _detectar_moneda("Cotización en USD Dólares") == "USD"


def test_detectar_moneda_mxn():
    assert _detectar_moneda("Precio en MXN Pesos") == "MXN"


def test_detectar_moneda_none_si_no_hay_pista():
    assert _detectar_moneda("Sin moneda explícita") is None


def test_candidatos_de_texto_extrae_lineas_con_precio_al_final():
    paginas = ["Cable THHW 10AWG ..... $1,250.00\nSin precio esta linea\nConector MC4 $85.50"]
    candidatos = _candidatos_de_texto(paginas)
    assert candidatos == [
        {"texto": "Cable THHW 10AWG .....", "precio": 1250.00},
        {"texto": "Conector MC4", "precio": 85.50},
    ]


def test_candidatos_de_texto_ignora_linea_sin_texto_previo_al_precio():
    paginas = ["$100.00"]
    assert _candidatos_de_texto(paginas) == []


def test_candidatos_de_texto_respeta_tope_maximo():
    paginas = ["\n".join(f"Item {i} $10.00" for i in range(60))]
    candidatos = _candidatos_de_texto(paginas)
    assert len(candidatos) == 50


def test_candidatos_de_texto_excluye_lineas_de_total_iva_subtotal():
    paginas = [
        "Cable THHW 10AWG $1,250.00\n"
        "Subtotal $1,250.00\n"
        "IVA (16%) $200.00\n"
        "Total a pagar $1,450.00\n"
        "Conector MC4 $85.50"
    ]
    candidatos = _candidatos_de_texto(paginas)
    assert candidatos == [
        {"texto": "Cable THHW 10AWG", "precio": 1250.00},
        {"texto": "Conector MC4", "precio": 85.50},
    ]


class FakePdfFile:
    content_type = "application/pdf"
    filename = "cotizacion.pdf"

    def __init__(self, content: bytes = b"%PDF-1.4 fake"):
        self._content = content

    async def read(self):
        return self._content


@pytest.mark.asyncio
async def test_extraer_costos_rechaza_archivo_que_no_es_pdf():
    svc = BomService()

    class FakeHtmlFile:
        content_type = "text/html"

    with pytest.raises(ValueError, match="debe ser un PDF"):
        await svc.extraer_costos_pdf_cotizacion(FakeHtmlFile())


@pytest.mark.asyncio
async def test_extraer_costos_rechaza_archivo_que_excede_tamano_maximo(monkeypatch):
    svc = BomService()
    monkeypatch.setattr(compras_service_module.settings, "PDF_MAX_UPLOAD_SIZE_MB", 1)
    archivo_grande = FakePdfFile(content=b"0" * (2 * 1024 * 1024))

    with pytest.raises(ValueError, match="tamaño máximo"):
        await svc.extraer_costos_pdf_cotizacion(archivo_grande)


@pytest.mark.asyncio
async def test_extraer_costos_delega_al_extractor_con_los_bytes_leidos(monkeypatch):
    svc = BomService()
    llamadas = []

    def _fake_extraer(content, filename):
        llamadas.append((content, filename))
        return {"candidatos": [{"texto": "Item", "precio": 1.0}], "metodo": "texto", "moneda_detectada": None, "error": None}

    monkeypatch.setattr(compras_service_module, "extraer_costos_cotizacion", _fake_extraer)

    resultado = await svc.extraer_costos_pdf_cotizacion(FakePdfFile(content=b"contenido-pdf"))

    assert resultado["candidatos"] == [{"texto": "Item", "precio": 1.0}]
    assert llamadas == [(b"contenido-pdf", "cotizacion.pdf")]
