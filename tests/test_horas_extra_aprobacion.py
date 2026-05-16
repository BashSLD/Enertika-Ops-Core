from __future__ import annotations

import pytest

from modules.asistencia.service import validate_aprobacion


def test_validate_ok_completo():
    validate_aprobacion(60, 120, "Proyecto urgente")


def test_validate_exactamente_minimo():
    validate_aprobacion(30, 60, "Correcto")


def test_validate_exactamente_maximo():
    validate_aprobacion(120, 120, "Todo el tiempo extra")


def test_validate_comentario_vacio():
    with pytest.raises(ValueError, match="comentario"):
        validate_aprobacion(60, 120, "")


def test_validate_comentario_solo_espacios():
    with pytest.raises(ValueError, match="comentario"):
        validate_aprobacion(60, 120, "   ")


def test_validate_minutos_bajo_minimo():
    with pytest.raises(ValueError, match="30"):
        validate_aprobacion(29, 120, "texto")


def test_validate_cero_minutos():
    with pytest.raises(ValueError, match="30"):
        validate_aprobacion(0, 120, "texto")


def test_validate_minutos_exceden_extra():
    with pytest.raises(ValueError, match="No puede aprobar"):
        validate_aprobacion(121, 120, "texto")


def test_validate_exactamente_30_con_extra_menor():
    with pytest.raises(ValueError, match="No puede aprobar"):
        validate_aprobacion(30, 20, "texto")
