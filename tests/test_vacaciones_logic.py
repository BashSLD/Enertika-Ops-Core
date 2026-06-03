from datetime import date

import pytest
from dateutil.relativedelta import relativedelta

from modules.vacaciones.logic import (
    asignar_consumo_fifo,
    calcular_balance,
    calcular_progreso,
    calcular_semestre_liberado,
    hito_recordatorio_aprobacion,
    restar_dias_habiles,
)

HOY = date(2026, 5, 21)

CATALOGO_BASE = [{"antiguedad_anios": 1, "antiguedad_anios_fin": None, "dias_enertika": 12}]


def _periodo(num, fecha_aniversario, fecha_expiracion, dias_otorgados, es_proximo=False):
    return {
        "num_periodo": num,
        "periodo": str(fecha_aniversario.year),
        "fecha_aniversario": fecha_aniversario,
        "fecha_expiracion": fecha_expiracion,
        "dias_otorgados": dias_otorgados,
        "es_proximo": es_proximo,
    }


def _prorroga(num_periodo, fecha_aniversario_periodo, fecha_expiracion_prorroga, dias_prorrogados):
    return {
        "num_periodo": num_periodo,
        "fecha_aniversario_periodo": fecha_aniversario_periodo,
        "fecha_expiracion_prorroga": fecha_expiracion_prorroga,
        "dias_prorrogados": dias_prorrogados,
    }


def _balance_enriquecido(num, aniversario, exp_efectiva, dias_otorgados, dias_usados,
                          tiene_prorroga=False, dias_prorrogados=None):
    """Construye un período ya enriquecido (como sale de calcular_balance) para usar en FIFO."""
    restantes = dias_otorgados - dias_usados
    return {
        "num_periodo": num,
        "fecha_aniversario": aniversario,
        "fecha_expiracion": aniversario + relativedelta(months=18),
        "fecha_expiracion_efectiva": exp_efectiva,
        "dias_otorgados": dias_otorgados,
        "dias_usados": dias_usados,
        "dias_restantes": restantes,
        "tiene_prorroga": tiene_prorroga,
        "dias_prorrogados": dias_prorrogados,
        "dias_restantes_prorrogados": min(restantes, dias_prorrogados) if tiene_prorroga else None,
        "es_proximo": False,
        "expirado": False,
    }


# ─────────────────────────────────────────────
# calcular_balance con prórrogas
# ─────────────────────────────────────────────

class TestRecordatoriosAprobacionHabiles:
    def test_lunes_dispara_t2_jueves_y_t1_viernes(self):
        inicio = date(2026, 6, 8)  # lunes
        festivos = set()

        assert restar_dias_habiles(inicio, 2, festivos) == date(2026, 6, 4)
        assert restar_dias_habiles(inicio, 1, festivos) == date(2026, 6, 5)
        assert hito_recordatorio_aprobacion(inicio, date(2026, 6, 4), festivos) == "t2"
        assert hito_recordatorio_aprobacion(inicio, date(2026, 6, 5), festivos) == "t1"

    def test_no_dispara_en_fin_de_semana(self):
        inicio = date(2026, 6, 8)

        assert hito_recordatorio_aprobacion(inicio, date(2026, 6, 6), set()) is None
        assert hito_recordatorio_aprobacion(inicio, date(2026, 6, 7), set()) is None

    def test_festivo_mueve_hito_al_dia_habil_anterior(self):
        inicio = date(2026, 6, 8)
        festivos = {date(2026, 6, 5)}

        assert restar_dias_habiles(inicio, 1, festivos) == date(2026, 6, 4)
        assert hito_recordatorio_aprobacion(inicio, date(2026, 6, 4), festivos) == "t1"
        assert hito_recordatorio_aprobacion(inicio, date(2026, 6, 5), festivos) is None

    def test_no_dispara_si_la_solicitud_ya_inicio(self):
        inicio = date(2026, 6, 8)

        assert hito_recordatorio_aprobacion(inicio, inicio, set()) is None


class TestCalcularBalanceProrrogas:
    def test_vencido_sin_prorroga_sigue_expirado(self, monkeypatch):
        monkeypatch.setattr("core.timezone.today_mx", lambda: HOY)
        aniversario = date(2024, 1, 1)
        expiracion = date(2025, 7, 1)
        balance = calcular_balance([_periodo(1, aniversario, expiracion, 15)], [])
        assert balance[0]["expirado"] is True
        assert balance[0]["tiene_prorroga"] is False

    def test_vencido_con_prorroga_vigente_no_expirado(self, monkeypatch):
        monkeypatch.setattr("core.timezone.today_mx", lambda: HOY)
        aniversario = date(2024, 1, 1)
        expiracion = date(2025, 7, 1)
        prorroga_fecha = date(2026, 8, 1)
        periodos = [_periodo(1, aniversario, expiracion, 15)]
        prorrogas = [_prorroga(1, aniversario, prorroga_fecha, 10)]
        balance = calcular_balance(periodos, [], prorrogas=prorrogas)
        p = balance[0]
        assert p["expirado"] is False
        assert p["tiene_prorroga"] is True
        assert p["fecha_expiracion_original"] == expiracion
        assert p["fecha_expiracion_efectiva"] == prorroga_fecha

    def test_prorroga_vencida_no_aplica(self, monkeypatch):
        monkeypatch.setattr("core.timezone.today_mx", lambda: HOY)
        aniversario = date(2024, 1, 1)
        expiracion = date(2025, 7, 1)
        prorroga_fecha = date(2026, 3, 1)  # ya venció antes de HOY
        periodos = [_periodo(1, aniversario, expiracion, 15)]
        prorrogas = [_prorroga(1, aniversario, prorroga_fecha, 10)]
        balance = calcular_balance(periodos, [], prorrogas=prorrogas)
        assert balance[0]["expirado"] is True
        assert balance[0]["tiene_prorroga"] is False

    def test_dias_limitados_por_prorrogados(self, monkeypatch):
        monkeypatch.setattr("core.timezone.today_mx", lambda: HOY)
        aniversario = date(2024, 1, 1)
        expiracion = date(2025, 7, 1)
        prorroga_fecha = date(2026, 8, 1)
        periodos = [_periodo(1, aniversario, expiracion, 15)]
        prorrogas = [_prorroga(1, aniversario, prorroga_fecha, 6)]
        balance = calcular_balance(periodos, [], prorrogas=prorrogas)
        p = balance[0]
        assert p["dias_restantes"] == 15
        assert p["dias_prorrogados"] == 6
        assert p["dias_restantes_prorrogados"] == 6  # min(15, 6)

    def test_sin_prorrogas_comportamiento_identico(self, monkeypatch):
        monkeypatch.setattr("core.timezone.today_mx", lambda: HOY)
        aniversario = date(2025, 1, 1)
        expiracion = HOY + relativedelta(months=6)
        periodos = [_periodo(1, aniversario, expiracion, 15)]
        consumos = [{"num_periodo": 1, "dias_consumidos": 5}]
        b_sin = calcular_balance(periodos, consumos)
        b_none = calcular_balance(periodos, consumos, prorrogas=None)
        assert b_sin[0]["expirado"] == b_none[0]["expirado"]
        assert b_sin[0]["dias_restantes"] == b_none[0]["dias_restantes"]
        assert b_sin[0]["dias_para_expiracion"] == b_none[0]["dias_para_expiracion"]


# ─────────────────────────────────────────────
# asignar_consumo_fifo con prórrogas
# ─────────────────────────────────────────────

class TestFifoConProrrogas:
    def test_fifo_consume_prorroga_antes_que_periodo_posterior(self, monkeypatch):
        monkeypatch.setattr("core.timezone.today_mx", lambda: HOY)
        # P1 prorrogado vence en junio; P2 ordinario vence en julio
        p1 = _balance_enriquecido(
            1, date(2023, 1, 1), date(2026, 6, 1),
            dias_otorgados=15, dias_usados=10,
            tiene_prorroga=True, dias_prorrogados=5,
        )
        p2 = _balance_enriquecido(
            2, date(2024, 1, 1), date(2026, 7, 1),
            dias_otorgados=14, dias_usados=0,
        )
        resultado = asignar_consumo_fifo([p2, p1], 7)  # orden invertido para probar sort
        assert resultado[0]["num_periodo"] == 1
        assert resultado[0]["dias_consumir"] == 5  # limitado por dias_prorrogados
        assert resultado[1]["num_periodo"] == 2
        assert resultado[1]["dias_consumir"] == 2

    def test_fifo_no_excede_limite_prorrogado(self, monkeypatch):
        monkeypatch.setattr("core.timezone.today_mx", lambda: HOY)
        p1 = _balance_enriquecido(
            1, date(2023, 1, 1), date(2026, 8, 1),
            dias_otorgados=15, dias_usados=5,
            tiene_prorroga=True, dias_prorrogados=4,
        )
        resultado = asignar_consumo_fifo([p1], 10)
        assert resultado[0]["dias_consumir"] == 4  # no puede tomar más de 4


# ─────────────────────────────────────────────
# calcular_semestre_liberado
# ─────────────────────────────────────────────

class TestCalcularSemestreLiberado:
    def test_antes_del_semestre_no_libera(self):
        resultado = calcular_semestre_liberado(date(2026, 1, 1), HOY, CATALOGO_BASE)
        assert resultado["semestre_activo"] is False
        assert resultado["dias_liberados"] == 0
        assert resultado["dias_a_liberar"] == 6  # proyección aunque no activo

    def test_despues_del_semestre_libera_dias(self):
        resultado = calcular_semestre_liberado(date(2025, 8, 1), HOY, CATALOGO_BASE)
        assert resultado["semestre_activo"] is True
        assert resultado["dias_liberados"] == 6  # floor(12 * 50/100)
        assert resultado["dias_a_liberar"] == 6

    def test_exactamente_en_fecha_semestre_activa(self):
        resultado = calcular_semestre_liberado(date(2025, 11, 21), HOY, CATALOGO_BASE)
        assert resultado["semestre_activo"] is True
        assert resultado["dias_liberados"] == 6
        assert resultado["dias_a_liberar"] == 6

    def test_porcentaje_liberacion_custom(self):
        resultado = calcular_semestre_liberado(date(2025, 8, 1), HOY, CATALOGO_BASE, porcentaje_liberacion=75)
        assert resultado["dias_liberados"] == 9  # floor(12 * 75/100)
        assert resultado["dias_a_liberar"] == 9

    def test_estructura_respuesta(self):
        resultado = calcular_semestre_liberado(date(2025, 8, 1), HOY, CATALOGO_BASE)
        assert set(resultado.keys()) == {
            "fecha_semestre", "dias_a_liberar", "dias_liberados", "semestre_activo",
            "dias_proximo_periodo", "meses_semestre", "semestre_pct",
        }


# ─────────────────────────────────────────────
# calcular_progreso — regresión
# ─────────────────────────────────────────────

class TestCalcularProgreso:
    def test_primer_año_mitad(self):
        resultado = calcular_progreso(date(2025, 11, 21), HOY, CATALOGO_BASE)
        assert resultado["numero_periodo_actual"] == 1
        assert resultado["dias_transcurridos"] == 181
        assert resultado["dias_proximo_periodo"] == 12
        assert resultado["porcentaje"] < 100.0
        assert resultado["fecha_ultimo_aniversario"] == date(2025, 11, 21)
        assert resultado["fecha_proximo_aniversario"] == date(2026, 11, 21)

    def test_exactamente_en_aniversario(self):
        resultado = calcular_progreso(date(2025, 5, 21), HOY, CATALOGO_BASE)
        assert resultado["numero_periodo_actual"] == 2
        assert resultado["dias_transcurridos"] == 0
        assert resultado["dias_proporcionales"] == 0.0
        assert resultado["porcentaje"] == 0.0
        assert resultado["fecha_ultimo_aniversario"] == date(2026, 5, 21)

    def test_porcentaje_no_supera_100(self):
        for fc in [date(2025, 1, 1), date(2024, 6, 15), date(2023, 5, 21)]:
            resultado = calcular_progreso(fc, HOY, CATALOGO_BASE)
            assert resultado["porcentaje"] <= 100.0

    def test_estructura_respuesta(self):
        resultado = calcular_progreso(date(2025, 11, 21), HOY, CATALOGO_BASE)
        assert set(resultado.keys()) == {
            "dias_transcurridos", "dias_totales_anio", "dias_proximo_periodo",
            "dias_proporcionales", "porcentaje",
            "fecha_ultimo_aniversario", "fecha_proximo_aniversario",
            "numero_periodo_actual",
        }
