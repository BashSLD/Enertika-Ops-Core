from datetime import datetime, time as dt_time, timedelta
import json
from typing import List, Tuple

class SLACalculator:
    """
    Pure Logic Class for SLA and Date Calculations.
    Does not interact with DB. Receives configuration as arguments.
    """

    @staticmethod
    def parse_config(config: dict) -> Tuple[dt_time, List[int], int]:
        """Helper to parse configuration strings into Python objects."""
        # Hora de Corte
        hora_corte_str = config.get("HORA_CORTE_L_V", "17:30")
        try:
            h, m = map(int, hora_corte_str.split(":"))
            hora_corte = dt_time(h, m)
        except ValueError:
             hora_corte = dt_time(17, 30)

        # Días Fin de Semana
        dias_fin_semana_str = config.get("DIAS_FIN_SEMANA", "[5, 6]")
        try:
            dias_fin_semana = json.loads(dias_fin_semana_str)
        except json.JSONDecodeError:
            dias_fin_semana = [5, 6]

        # Días SLA
        try:
            dias_sla_str = config.get("DIAS_SLA_DEFAULT", "7")
            dias_sla = int(dias_sla_str)
        except ValueError:
            dias_sla = 7
            
        return hora_corte, dias_fin_semana, dias_sla

    @staticmethod
    def is_out_of_hours(fecha: datetime, hora_corte: dt_time, dias_fin_semana: List[int]) -> bool:
        """Determines if a date is outside business hours."""
        dia_semana = fecha.weekday()
        hora_actual = fecha.time()

        if dia_semana in dias_fin_semana:
            return True
        if hora_actual > hora_corte:
            return True
        return False

    @staticmethod
    def calculate_deadline(fecha: datetime, hora_corte: dt_time, dias_sla: int) -> datetime:
        """
        Calculates the deadline based on business rules.
        """
        # Datos de la Fecha Actual
        dia_semana = fecha.weekday() 
        hora_actual = fecha.time()
        
        # Reseteamos a 00:00:00 para sumar días completos
        fecha_base = fecha.replace(hour=0, minute=0, second=0, microsecond=0)
        
        dias_ajuste_inicio = 0

        # --- REGLAS DE NEGOCIO ---
        if dia_semana == 5:   # Sábado -> Lunes (+2)
            dias_ajuste_inicio = 2
        elif dia_semana == 6: # Domingo -> Lunes (+1)
            dias_ajuste_inicio = 1
        else:
            if hora_actual > hora_corte:
                if dia_semana == 4: # Viernes tarde -> Lunes (+3)
                    dias_ajuste_inicio = 3
                else:               # Lun-Jue tarde -> Día siguiente (+1)
                    dias_ajuste_inicio = 1
            else:
                dias_ajuste_inicio = 0

        # Fecha Inicio Real = Fecha Creación + Ajuste
        adjusted_start_date = fecha_base + timedelta(days=dias_ajuste_inicio)
        
        # Deadline = Fecha Inicio Real + SLA
        deadline_final = adjusted_start_date + timedelta(days=dias_sla)
        
        # Fijar hora de vencimiento al cierre de jornada
        deadline_final = deadline_final.replace(hour=hora_corte.hour, minute=hora_corte.minute)
        
        return deadline_final
