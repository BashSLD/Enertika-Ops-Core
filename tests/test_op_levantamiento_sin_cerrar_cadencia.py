"""
Cadencia del recordatorio de OP tipo LEVANTAMIENTO con todos sus levantamientos
cancelados sin cerrar (_Planes_Activos/2026-07-23-propagacion-estatus-levantamientos-PLAN.md,
Paso 8-M): primer aviso a 2 dias habiles desde la ultima transicion a terminal,
luego cada lunes habil (si el lunes es festivo, el siguiente dia habil).
"""
from datetime import date

from core.tasks import (
    _dia_cadencia_semanal_lev_cancelado,
    _primer_aviso_lev_cancelado_vencido,
    _recordatorio_lev_cancelado_vencido,
)


# ───────────────────────── primer aviso (2 dias habiles) ─────────────────────────


def test_primer_aviso_no_vencido_antes_de_2_dias_habiles():
    lunes = date(2026, 7, 6)  # lunes
    assert _primer_aviso_lev_cancelado_vencido(lunes, date(2026, 7, 7), set()) is False  # martes: 1 dia


def test_primer_aviso_vencido_exacto_a_2_dias_habiles():
    lunes = date(2026, 7, 6)
    assert _primer_aviso_lev_cancelado_vencido(lunes, date(2026, 7, 8), set()) is True  # miercoles: 2 dias


def test_primer_aviso_salta_fin_de_semana():
    viernes = date(2026, 7, 3)
    # sabado/domingo no cuentan: 2 dias habiles = lunes + martes
    assert _primer_aviso_lev_cancelado_vencido(viernes, date(2026, 7, 7), set()) is True  # martes


def test_primer_aviso_salta_festivo():
    lunes = date(2026, 7, 6)
    martes_festivo = date(2026, 7, 7)
    # martes es festivo (no cuenta): dia habil 1 = miercoles, dia habil 2 = jueves -> due=jueves
    assert _primer_aviso_lev_cancelado_vencido(lunes, date(2026, 7, 8), {martes_festivo}) is False  # miercoles
    assert _primer_aviso_lev_cancelado_vencido(lunes, date(2026, 7, 9), {martes_festivo}) is True  # jueves


# ───────────────────────── cadencia semanal (lunes habil) ─────────────────────────


def test_dia_cadencia_semanal_es_lunes_sin_festivos():
    martes = date(2026, 7, 7)
    assert _dia_cadencia_semanal_lev_cancelado(martes, set()) == date(2026, 7, 6)


def test_dia_cadencia_semanal_salta_lunes_festivo():
    lunes = date(2026, 7, 6)
    assert _dia_cadencia_semanal_lev_cancelado(date(2026, 7, 8), {lunes}) == date(2026, 7, 7)


# ───────────────────────── orquestacion completa ─────────────────────────


def test_recordatorio_vencido_usa_primer_aviso_sin_envio_previo():
    ultima_transicion = date(2026, 7, 6)  # lunes
    assert _recordatorio_lev_cancelado_vencido(ultima_transicion, None, date(2026, 7, 7), set()) is False
    assert _recordatorio_lev_cancelado_vencido(ultima_transicion, None, date(2026, 7, 8), set()) is True


def test_recordatorio_vencido_cadencia_semanal_con_envio_previo():
    from datetime import datetime

    ultima_transicion = date(2026, 6, 1)
    ultimo_envio = datetime(2026, 6, 29, 10, 0)  # lunes anterior
    hoy_no_lunes = date(2026, 7, 2)  # jueves
    hoy_lunes = date(2026, 7, 6)  # lunes siguiente

    assert _recordatorio_lev_cancelado_vencido(ultima_transicion, ultimo_envio, hoy_no_lunes, set()) is False
    assert _recordatorio_lev_cancelado_vencido(ultima_transicion, ultimo_envio, hoy_lunes, set()) is True


def test_recordatorio_no_se_duplica_mismo_dia_de_cadencia():
    from datetime import datetime

    ultima_transicion = date(2026, 6, 1)
    lunes = date(2026, 7, 6)
    ultimo_envio_mismo_lunes = datetime(2026, 7, 6, 9, 0)

    assert _recordatorio_lev_cancelado_vencido(ultima_transicion, ultimo_envio_mismo_lunes, lunes, set()) is False
