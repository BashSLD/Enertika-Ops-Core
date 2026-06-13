"""
Constantes para cálculo de scores y categorización de desempeño
"""

from datetime import date

# ============================================
# CORTE DE DATOS HISTÓRICOS (ECO)
# ============================================
FECHA_INICIO_KPI_TIEMPO = date(2026, 3, 1)
"""Fecha de puesta en marcha de ECO: desde aquí 'tiempo_elaboracion_horas' se registra
con hora real. Antes, los datos legacy quedaron sin tiempo o a las 00:00, por lo que el
promedio de elaboración no es representativo. Los reportes cuyo rango inicie antes de
esta fecha muestran una nota en lugar del Tiempo promedio de entrega."""

# ============================================
# UMBRALES DE CATEGORIZACIÓN
# ============================================
UMBRAL_MIN_ENTREGAS = 10
"""Mínimo de entregas para calcular score de desempeño"""

UMBRAL_RATIO_LICITACIONES = 0.10
"""Ratio mínimo de licitaciones para categoría "Alta Complejidad" (10% = 2× promedio global)"""

# ============================================
# PESOS PARA CÁLCULO DE SCORE
# ============================================
PESO_CUMPLIMIENTO_COMPROMISO = 0.50
"""Peso de cumplimiento con cliente en score base"""

PESO_CUMPLIMIENTO_INTERNO = 0.25
"""Peso de cumplimiento SLA interno en score base"""

PESO_VOLUMEN = 0.25
"""Peso de carga de trabajo (sitios entregados) en score base"""

# ============================================
# MULTIPLICADORES DE COMPLEJIDAD
# ============================================
MULTIPLICADOR_LICITACIONES = 0.20
"""Bonus máximo por ratio de licitaciones (hasta +20%)"""

MULTIPLICADOR_ACTUALIZACIONES = 0.10
"""Bonus máximo por ratio de actualizaciones (hasta +10%)"""

PENALIZACION_RETRABAJOS = -0.15
"""Penalización por ratio de retrabajos (hasta -15%)"""

# ============================================
# NORMALIZACIÓN
# ============================================
VOLUMEN_MAX_NORMALIZACION = 15
"""Piso mínimo de carga (sitios) para la normalización relativa al período"""

# ============================================
# CATEGORÍAS (sin emojis - esos van en frontend)
# ============================================
CATEGORIA_ALTA_COMPLEJIDAD = "alta_complejidad"
CATEGORIA_EFICIENCIA = "eficiencia"
CATEGORIA_EVALUACION = "evaluacion"

CATEGORIAS_DISPLAY = {
    CATEGORIA_ALTA_COMPLEJIDAD: {
        "nombre": "Líderes de Alta Complejidad",
        "descripcion": "≥10 entregas, ≥10% licitaciones"
    },
    CATEGORIA_EFICIENCIA: {
        "nombre": "Líderes de Eficiencia",
        "descripcion": "≥10 entregas, <10% licitaciones"
    },
    CATEGORIA_EVALUACION: {
        "nombre": "Colaboradores en Evaluación",
        "descripcion": "<10 entregas"
    }
}
