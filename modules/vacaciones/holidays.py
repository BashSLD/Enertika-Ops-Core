from __future__ import annotations

from datetime import date, timedelta


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    current = date(year, month, 1)
    while current.weekday() != weekday:
        current += timedelta(days=1)
    return current + timedelta(days=7 * (n - 1))


def generar_feriados_mexico(anio: int) -> list[dict]:
    """Festivos oficiales base en México para generar el catálogo anual."""
    feriados = [
        {
            "fecha": date(anio, 1, 1),
            "descripcion": "Año Nuevo",
            "es_oficial": True,
        },
        {
            "fecha": _nth_weekday(anio, 2, 0, 1),
            "descripcion": "Día de la Constitución",
            "es_oficial": True,
        },
        {
            "fecha": _nth_weekday(anio, 3, 0, 3),
            "descripcion": "Natalicio de Benito Juárez",
            "es_oficial": True,
        },
        {
            "fecha": date(anio, 5, 1),
            "descripcion": "Día del Trabajo",
            "es_oficial": True,
        },
        {
            "fecha": date(anio, 9, 16),
            "descripcion": "Día de la Independencia",
            "es_oficial": True,
        },
        {
            "fecha": _nth_weekday(anio, 11, 0, 3),
            "descripcion": "Revolución Mexicana",
            "es_oficial": True,
        },
        {
            "fecha": date(anio, 12, 25),
            "descripcion": "Navidad",
            "es_oficial": True,
        },
    ]

    if (anio - 2024) % 6 == 0:
        feriados.append({
            "fecha": date(anio, 10, 1),
            "descripcion": "Transmisión del Poder Ejecutivo Federal",
            "es_oficial": True,
        })

    return sorted(feriados, key=lambda item: item["fecha"])
