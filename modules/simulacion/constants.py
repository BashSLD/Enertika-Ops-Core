"""
Constantes para cálculo de scores y categorización de desempeño
"""

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

PESO_CUMPLIMIENTO_INTERNO = 0.35
"""Peso de cumplimiento SLA interno en score base"""

PESO_VOLUMEN = 0.15
"""Peso de volumen de entregas en score base"""

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
VOLUMEN_MAX_NORMALIZACION = 100
"""Volumen de entregas que representa 100% en normalización"""

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
