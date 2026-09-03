"""Reglas estaticas para templates y recursos frontend agregados."""

from __future__ import annotations

import re
from pathlib import Path

from devtools.models import AddedLine, ChangedFile, DiffSnapshot, Finding, Severity

_LOCAL_DATE_ISO_RE = re.compile(
    r"\.toISOString\(\)\.(?:"
    r"split\(\s*['\"]T['\"]\s*\)\s*\[\s*0\s*\]"
    r"|slice\(\s*0\s*,\s*10\s*\)"
    r"|substring\(\s*0\s*,\s*10\s*\)"
    r")"
)
_TOAST_TYPO_RE = re.compile(r"#toast-container\b")
_OVERLAY_ROOT_RE = re.compile(r"fixed\s+inset-0")
_OVERLAY_DIM_RE = re.compile(r"bg-opacity|backdrop-blur")
_HTMX_AJAX_RE = re.compile(r"htmx\.ajax\(")
_HTMX_AJAX_SOURCE_RE = re.compile(r"\bsource\s*[:,]")
_HTMX_AJAX_LOOKAHEAD_LINES = 6
_JS_ATTR_OPEN_RE = re.compile(
    r'(?<![\w:.-])(?:@[\w:.$-]+|x-on:[\w:.$-]+|on[a-z]+|hx-on::[\w-]+)="'
)
_JS_ATTR_LOOKAHEAD_LINES = 6


def check_frontend_rules(
    snapshot: DiffSnapshot, root: Path | None = None
) -> list[Finding]:
    findings: list[Finding] = []
    for changed_file in snapshot.files:
        if changed_file.suffix not in {".html", ".js"}:
            continue
        for line in changed_file.added_lines:
            if _LOCAL_DATE_ISO_RE.search(line.text):
                findings.append(
                    Finding(
                        code="TZ003",
                        severity=Severity.ERROR,
                        message=(
                            "No extraer fechas locales con toISOString(); usar toLocalISO."
                        ),
                        path=line.path,
                        line=line.number,
                    )
                )
            if _uses_ternary_tab_class(line.text):
                findings.append(
                    Finding(
                        code="HTMX001",
                        severity=Severity.ERROR,
                        message=(
                            "En tabs Alpine, :class debe usar notacion de objeto, no un "
                            "ternario de cadenas."
                        ),
                        path=line.path,
                        line=line.number,
                    )
                )
            if _TOAST_TYPO_RE.search(line.text):
                findings.append(
                    Finding(
                        code="HTMX002",
                        severity=Severity.ERROR,
                        message=(
                            "Typo de toast OOB: usar #global-toast-container, no "
                            "#toast-container; el ID incorrecto aborta todo el swap."
                        ),
                        path=line.path,
                        line=line.number,
                    )
                )
            if _uses_tojson_in_alpine_data(line.text):
                findings.append(
                    Finding(
                        code="ALPINE001",
                        severity=Severity.ERROR,
                        message=(
                            "No usar |tojson dentro de x-data; usar atributos data- con "
                            "comillas simples y JSON.parse($el.dataset.foo)."
                        ),
                        path=line.path,
                        line=line.number,
                    )
                )
            if _is_overlay_missing_stacking_layer(line.text):
                findings.append(
                    Finding(
                        code="UI001",
                        severity=Severity.WARNING,
                        message=(
                            "Backdrop raiz de modal (fixed inset-0 + bg-opacity/"
                            "backdrop-blur) sin clase modal-overlay-layer para stacking."
                        ),
                        path=line.path,
                        line=line.number,
                    )
                )
        for hit in _find_htmx_ajax_missing_source(changed_file, root):
            findings.append(
                Finding(
                    code="HTMX003",
                    severity=Severity.WARNING,
                    message=(
                        "htmx.ajax(...) sin 'source': si no se especifica, htmx usa "
                        "document.body como elemento emisor y le agrega la clase "
                        "htmx-request, activando CUALQUIER .htmx-indicator "
                        "descendiente (ej. #global-loading-overlay) sin haber sido "
                        "pedido. Agregar source apuntando a un elemento estable "
                        "(normalmente el mismo target, o $el/$event.target si no "
                        "hay target)."
                    ),
                    path=hit.path,
                    line=hit.number,
                )
            )
        for hit in _find_tojson_in_double_quoted_js_attr(changed_file, root):
            findings.append(
                Finding(
                    code="ALPINE002",
                    severity=Severity.ERROR,
                    message=(
                        "|tojson dentro de un atributo con comillas dobles (@click=\"...\", "
                        "onsubmit=\"...\", hx-on::...=\"...\"): tojson nunca escapa comillas "
                        "dobles, la primera '\"' de su salida cierra el atributo antes de "
                        "tiempo y rompe el HTML. Usar comillas simples en el atributo "
                        "(y comillas dobles para strings JS internos), o forceescape si "
                        "debe quedar en comillas dobles."
                    ),
                    path=hit.path,
                    line=hit.number,
                )
            )
    return findings


def _uses_ternary_tab_class(text: str) -> bool:
    return ":class=" in text and "?" in text and "tab" in text


def _uses_tojson_in_alpine_data(text: str) -> bool:
    return "x-data=" in text and "tojson" in text


def _is_overlay_missing_stacking_layer(text: str) -> bool:
    return (
        bool(_OVERLAY_ROOT_RE.search(text))
        and bool(_OVERLAY_DIM_RE.search(text))
        and "modal-overlay-layer" not in text
    )


def _find_htmx_ajax_missing_source(
    changed_file: ChangedFile, root: Path | None
) -> list[AddedLine]:
    """Busca 'source' dentro de cada llamada htmx.ajax(...) tocada por el diff.

    Con `root` disponible, lee el archivo actual completo y balancea parentesis
    a partir de cada 'htmx.ajax(' para acotar la llamada exacta, sin limite
    artificial de lineas ni depender de que 'source' este entre las lineas
    agregadas del diff (con --unified=0 el diff no trae contexto, asi que una
    llamada modificada a medias podria tener su 'source' en una linea no
    tocada y quedar invisible para un heuristico basado solo en added_lines).
    Si el archivo no se puede leer (tests con ChangedFile sinteticos, root=None),
    cae al heuristico de ventana fija sobre added_lines."""
    hits: list[AddedLine] = []
    lines = changed_file.added_lines
    file_lines = _read_file_lines(root, changed_file.path) if root is not None else None

    for index, line in enumerate(lines):
        if not _HTMX_AJAX_RE.search(line.text):
            continue

        if file_lines is not None and 1 <= line.number <= len(file_lines):
            call_text = _extract_balanced_call(file_lines, line.number - 1)
            if call_text is not None:
                if not _HTMX_AJAX_SOURCE_RE.search(call_text):
                    hits.append(line)
                continue

        window = [line] + [
            candidate
            for candidate in lines[index + 1 : index + 1 + _HTMX_AJAX_LOOKAHEAD_LINES]
            if candidate.number - line.number <= _HTMX_AJAX_LOOKAHEAD_LINES
        ]
        if not any(_HTMX_AJAX_SOURCE_RE.search(candidate.text) for candidate in window):
            hits.append(line)
    return hits


def _find_tojson_in_double_quoted_js_attr(
    changed_file: ChangedFile, root: Path | None
) -> list[AddedLine]:
    """Busca `| tojson` dentro del valor de un atributo JS con comillas dobles.

    Igual que `_find_htmx_ajax_missing_source`: con `root` disponible, lee el
    archivo actual y extrae el valor exacto del atributo balanceando comillas
    a partir de donde abre (`@click="`, `onsubmit="`, `hx-on::evt="`, etc.),
    sin depender de que el atributo entero este en las lineas agregadas del
    diff. Sin `root` (tests con ChangedFile sinteticos), cae a una ventana
    fija sobre added_lines."""
    hits: list[AddedLine] = []
    lines = changed_file.added_lines
    file_lines = _read_file_lines(root, changed_file.path) if root is not None else None

    for index, line in enumerate(lines):
        if not _JS_ATTR_OPEN_RE.search(line.text):
            continue

        if file_lines is not None and 1 <= line.number <= len(file_lines):
            match = _JS_ATTR_OPEN_RE.search(file_lines[line.number - 1])
            if match is not None:
                value = _extract_double_quoted_value(
                    file_lines, line.number - 1, match.end()
                )
                if value is not None:
                    if "tojson" in value and "forceescape" not in value:
                        hits.append(line)
                    continue

        window = [line] + [
            candidate
            for candidate in lines[index + 1 : index + 1 + _JS_ATTR_LOOKAHEAD_LINES]
            if candidate.number - line.number <= _JS_ATTR_LOOKAHEAD_LINES
        ]
        joined = " ".join(candidate.text for candidate in window)
        if "tojson" in joined and "forceescape" not in joined:
            hits.append(line)
    return hits


def _extract_double_quoted_value(
    file_lines: list[str], start_index: int, start_col: int
) -> str | None:
    """Valor de un atributo `="..."` que empieza en file_lines[start_index]
    en la columna start_col (justo despues de la comilla de apertura), hasta
    la comilla doble de cierre (sin escape -- los atributos HTML no usan
    backslash-escape para comillas)."""
    collected: list[str] = []
    for offset, raw in enumerate(
        file_lines[start_index : start_index + _JS_ATTR_VALUE_MAX_LINES]
    ):
        text = raw[start_col:] if offset == 0 else raw
        closing = text.find('"')
        if closing != -1:
            collected.append(text[:closing])
            return "\n".join(collected)
        collected.append(text)
    return None


_JS_ATTR_VALUE_MAX_LINES = 200


def _read_file_lines(root: Path, relative_path: str) -> list[str] | None:
    try:
        return (root / relative_path).read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()
    except OSError:
        return None


_HTMX_AJAX_CALL_MAX_LINES = 200


def _extract_balanced_call(file_lines: list[str], start_index: int) -> str | None:
    """Texto de la llamada htmx.ajax(...) que empieza en file_lines[start_index],
    balanceando parentesis hasta encontrar el cierre correspondiente."""
    open_pos = file_lines[start_index].find("htmx.ajax(")
    if open_pos == -1:
        return None
    depth = 0
    collected: list[str] = []
    for offset, raw in enumerate(file_lines[start_index:start_index + _HTMX_AJAX_CALL_MAX_LINES]):
        text = raw[open_pos:] if offset == 0 else raw
        depth += text.count("(") - text.count(")")
        collected.append(text)
        if depth <= 0:
            return "\n".join(collected)
    return "\n".join(collected)
