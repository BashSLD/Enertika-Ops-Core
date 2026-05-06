from .schemas import CfeExcelColumn, CfeExcelProfile


COLUMNAS_CFE_ACTUAL = (
    CfeExcelColumn("mes", "Mes"),
    CfeExcelColumn("consumo", "Consumo"),
    CfeExcelColumn("consumo_base", "Consumo Base"),
    CfeExcelColumn("consumo_intermedio", "Consumo Intermedio"),
    CfeExcelColumn("consumo_punta", "Consumo Punta"),
    CfeExcelColumn("potencia_base", "Potencia Base"),
    CfeExcelColumn("potencia_intermedia", "Potencia Intermedia"),
    CfeExcelColumn("potencia_punta", "Potencia Punta"),
    CfeExcelColumn("dias", "Dias"),
    CfeExcelColumn("kw_cap", "KW CAP"),
    CfeExcelColumn("kw_dist", "kW DIST"),
    CfeExcelColumn("kwmax", "kWMax"),
    CfeExcelColumn("fp", "FP"),
    CfeExcelColumn("reactiva", "Reactiva"),
    CfeExcelColumn("coste_energia_base", "Coste Energía (Base )"),
    CfeExcelColumn("coste_energia_intermedia", "Coste Energía (Intermedia)"),
    CfeExcelColumn("coste_energia_punta", "Coste Energía (Punta)"),
    CfeExcelColumn("transmision", "Trasmisión"),
    CfeExcelColumn("coste_distribucion", "Coste Distribución"),
    CfeExcelColumn("coste_capacidad", "Coste Capacidad"),
    CfeExcelColumn("scnmem", "SCnMEM"),
    CfeExcelColumn("suministro", "Suministro"),
    CfeExcelColumn("cenace", "CENACE"),
    CfeExcelColumn("dos_por_ciento", "2%"),
    CfeExcelColumn("penalizacion_fp", "Penalización FP"),
    CfeExcelColumn("total", "TOTAL"),
    CfeExcelColumn("observaciones", "Observaciones"),
)

PERFILES_CFE = {
    "oym": CfeExcelProfile(
        slug="oym",
        nombre="O&M",
        columns=COLUMNAS_CFE_ACTUAL,
    ),
    "simulacion": CfeExcelProfile(
        slug="simulacion",
        nombre="Simulación",
        columns=COLUMNAS_CFE_ACTUAL,
    ),
}


def obtener_perfil_cfe(slug: str) -> CfeExcelProfile:
    try:
        return PERFILES_CFE[slug]
    except KeyError as exc:
        raise ValueError(f"Perfil de Excel CFE no soportado: {slug}") from exc
