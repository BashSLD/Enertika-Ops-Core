"""
Test estructural: solo templates/base.html debe declarar id="main-content".

Un segundo id="main-content" en un template que extiende base.html (o en un
partial incluido dentro del bloque content) queda anidado dentro del
#main-content real del shell. Cuando ese template se sirve como respuesta a
un swap HTMX hacia #main-content, HTMX resuelve el selector al primer match
en el documento completo — el duplicado es simplemente ID invalido en el DOM,
sintoma de que el template fue escrito asumiendo que seria su propio shell.
Ver templates/simulacion/reportes/analisis_detallado.html (caso real corregido).
"""
import re
from pathlib import Path

TEMPLATES_DIR = Path(__file__).parents[1] / "templates"
MAIN_CONTENT_ID_RE = re.compile(r'id=["\']main-content["\']')


def test_only_base_html_declares_main_content_id():
    offenders = []
    for path in TEMPLATES_DIR.rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        if MAIN_CONTENT_ID_RE.search(text) and path.name != "base.html":
            offenders.append(str(path.relative_to(TEMPLATES_DIR)))

    assert offenders == [], (
        "Templates con id=\"main-content\" duplicado fuera de base.html: "
        f"{offenders}. Elimina el wrapper redundante (base.html ya envuelve "
        "{% block content %} en su propio #main-content)."
    )
