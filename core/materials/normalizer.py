import html
import re
import unicodedata


# Prefijo código entre corchetes al inicio: [BOTE10], [INV-GRO-20-220V]
_RE_PREFIX_CODE = re.compile(r'^\[[^\]]*\]\s*')

# Tags HTML
_RE_HTML_TAGS = re.compile(r'<[^>]+>')

# Noise comercial: todo desde el primer ** hasta el final (OFRECER, BOLSA, AP, etc.)
_RE_NOISE_STARS = re.compile(r'\s*\*{2,}.*', re.DOTALL)

# Dígito pegado a 2+ letras: 10AWG → 10 AWG  (no parte 3/4 ni 5A)
_RE_DIGIT_LETTER = re.compile(r'(\d)([A-Z]{2,})')

# Guión no entre dígitos: THHN-2 → THHN 2  (pero 3/8-16 intacto)
_RE_DASH_NON_NUMERIC = re.compile(r'(?<!\d)-(?!\d)')

# Punto suelto entre espacios (artefacto \n.\n del XML)
_RE_ISOLATED_DOT = re.compile(r'(?<= )\.(?= )')

_RE_WHITESPACE = re.compile(r'[\r\n\t]+')

# Espacios multiples -> uno solo. Publica: tambien la usa
# modules/compras/xml_extractor.py para higiene de formato en descripcion_proveedor
# (limpieza de escritura, no de matching -- no confundir con normalizar_descripcion).
RE_MULTI_SPACE = re.compile(r' {2,}')


def normalizar_descripcion(texto: str) -> str:
    """
    Normaliza descripción para almacenar en descripcion_norm (búsqueda fuzzy).
    Opera solo sobre tb_cat_materiales — nunca modifica descripcion_proveedor.
    """
    if not texto:
        return ""

    t = texto

    # 1. Unescape HTML entities (&reg; → ®, &amp; → &)
    t = html.unescape(t)

    # 2. Strip tags HTML (<br />, <b>, etc.)
    t = _RE_HTML_TAGS.sub(" ", t)

    # 3. Colapsar saltos de línea y artefactos \n.\n del XML
    t = _RE_WHITESPACE.sub(" ", t)

    # 4. Quitar prefijo código entre corchetes al inicio: [BOTE10]
    t = _RE_PREFIX_CODE.sub("", t)

    # 5. Quitar noise comercial desde el primer ** hasta el final
    t = _RE_NOISE_STARS.sub("", t)

    # 6. Strip y quitar caracteres basura al inicio (: y puntos sueltos)
    t = t.strip().lstrip(":. ")

    # 7. UPPER
    t = t.upper()

    # 8. Quitar acentos (NFKD) + eliminar caracteres combinantes
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))

    # 9. Quitar símbolos no-ASCII que no aportan al matching (®, ©, ™…)
    #    Se conserva ° (calibre eléctrico) y todo ASCII imprimible 0x20-0x7E
    t = re.sub(r'[^\x20-\x7E\xB0]', '', t)

    # 10. Homologar '' → " (dos comillas simples = pulgadas)
    t = t.replace("''", '"')

    # 11. Guión no numérico → espacio (THHN-2 → THHN 2, pero 3/8-16 intacto)
    t = _RE_DASH_NON_NUMERIC.sub(" ", t)

    # 12. Separar dígito pegado a letras: 10AWG → 10 AWG
    t = _RE_DIGIT_LETTER.sub(r"\1 \2", t)

    # 13. Quitar puntos sueltos entre espacios (artefacto \n.\n del XML)
    t = _RE_ISOLATED_DOT.sub(" ", t)

    # 14. Colapsar espacios múltiples
    t = RE_MULTI_SPACE.sub(" ", t).strip()

    return t


def normalizar_unidad(texto: str) -> str:
    """
    Normaliza texto crudo de unidad para comparar contra tb_cat_unidad_aliases.
    Resultado en UPPER sin acentos ni punto final.
    """
    if not texto:
        return ""

    t = texto.strip().upper()
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"\.$", "", t)   # PZA. → PZA
    t = re.sub(r"\s+", " ", t).strip()

    return t
