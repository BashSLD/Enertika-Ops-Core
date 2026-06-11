# modules/cfe/scraper.py
"""
Scraper CFE: portal público (XML) + MiEspacio (PDF).
Porto de ScrapingCoco/cfe-recibo-scraper.js + cfe-miespacio-workflow.js.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Page

try:
    from playwright.async_api import Error as PlaywrightError
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError
    _PLAYWRIGHT_ERRORS = (PlaywrightError, PlaywrightTimeoutError)
    _SCRAPER_TIMEOUT_ERRORS = (asyncio.TimeoutError, PlaywrightTimeoutError)
except ModuleNotFoundError:
    _PLAYWRIGHT_ERRORS = ()
    _SCRAPER_TIMEOUT_ERRORS = (asyncio.TimeoutError,)

_SCRAPER_ERRORS = (ValueError, RuntimeError, OSError, asyncio.TimeoutError) + _PLAYWRIGHT_ERRORS

from modules.shared.services.cfe.extractor import extraer_datos_xml

logger = logging.getLogger("CfeScraper")

CFE_PUBLIC_URL = "https://app.cfe.mx/Aplicaciones/CCFE/ReciboDeLuzGMX/Consulta"
CFE_MIESPACIO_ADD_URL = "https://app.cfe.mx/Aplicaciones/CCFE/MiEspacio/AgregarServicio.aspx"
CFE_MIESPACIO_DEFAULT_URL = "https://app.cfe.mx/Aplicaciones/CCFE/MiEspacio/Default.aspx"

_BROWSER_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
]

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

# Politeness anti-Imperva: pausa entre descargas de periodos consecutivos en
# MiEspacio (analisis web scraping §8/§10). Evita el challenge de Incapsula en
# historicos largos.
_DELAY_ENTRE_PERIODOS_MS = 1200

_MESES_ABREV = {
    "01": "ENE", "02": "FEB", "03": "MAR", "04": "ABR",
    "05": "MAY", "06": "JUN", "07": "JUL", "08": "AGO",
    "09": "SEP", "10": "OCT", "11": "NOV", "12": "DIC",
}

_MESES_CFE = {
    "ENE": "01", "ENERO": "01",
    "FEB": "02", "FEBRERO": "02",
    "MAR": "03", "MARZO": "03",
    "ABR": "04", "ABRIL": "04",
    "MAY": "05", "MAYO": "05",
    "JUN": "06", "JUNIO": "06",
    "JUL": "07", "JULIO": "07",
    "AGO": "08", "AGOSTO": "08",
    "SEP": "09", "SEPT": "09", "SEPTIEMBRE": "09",
    "OCT": "10", "OCTUBRE": "10",
    "NOV": "11", "NOVIEMBRE": "11",
    "DIC": "12", "DICIEMBRE": "12",
}
_MESES_PUBLIC_RE = re.compile(
    r"\b(" + "|".join(sorted(_MESES_CFE, key=len, reverse=True)) + r")\s+(20\d{2})\b",
    re.I,
)


@dataclass
class CfeScraperConfig:
    nombre: str
    numero_servicio: str
    lada: str
    telefono: str
    email: str
    alias: str
    mi_user: str
    mi_pass: str
    session_json: Optional[str] = None
    timeout_ms: int = 60_000


@dataclass
class DescargaResult:
    xml_content: Optional[bytes] = None
    xml_filename: str = ""
    pdf_content: Optional[bytes] = None
    pdf_filename: str = ""
    periodo: str = ""
    session_json_nuevo: Optional[str] = None
    error: Optional[str] = None
    pdf_error: Optional[str] = None


@dataclass
class DescargaPeriodoPublicoResult:
    periodo: str
    etiqueta: str = ""
    xml_content: Optional[bytes] = None
    xml_filename: str = ""
    pdf_content: Optional[bytes] = None
    pdf_filename: str = ""
    xml_error: Optional[str] = None
    pdf_error: Optional[str] = None


@dataclass
class ResultadoBusquedaPeriodos:
    periodos: list[DescargaPeriodoPublicoResult]
    advertencia: Optional[str] = None


def _advertencia_discrepancia(*, publico: int, miespacio: int) -> Optional[str]:
    """Avisa si el conteo de periodos difiere entre portal publico y MiEspacio.
    miespacio == -1 significa que no se pudo abrir/contar MiEspacio: sin aviso."""
    if miespacio < 0 or publico == miespacio:
        return None
    return (
        f"El portal publico mostro {publico} periodos y MiEspacio {miespacio}. "
        "Pueden faltar archivos en alguno de los dos."
    )


class MiEspacioServiceNotFound(ValueError):
    pass


_cached_browser_path: Optional[str] = None


def _pick_browser() -> Optional[str]:
    global _cached_browser_path
    if _cached_browser_path is None:
        for p in _BROWSER_PATHS:
            if Path(p).exists():
                _cached_browser_path = p
                break
    return _cached_browser_path


async def _detect_block(page: Page) -> Optional[str]:
    try:
        info = await page.evaluate(
            "() => ({ url: location.href, title: document.title || '', "
            "text: (document.body?.innerText || '').slice(0, 2000) })"
        )
    except Exception:
        return None
    haystack = f"{info['url']}\n{info['title']}\n{info['text']}"
    if re.search(r"imperva|incapsula|incident id|request unsuccessful", haystack, re.I):
        return "Portal CFE bloqueado por protección Imperva/Incapsula. Intenta en unos minutos."
    if re.search(r"access denied|request blocked", haystack, re.I):
        return "Acceso denegado por el portal CFE. Intenta en unos minutos."
    if re.search(r"por el momento no se encuentra disponible", haystack, re.I):
        return "Portal CFE MiEspacio no disponible temporalmente (sesión posiblemente inactiva). Renueva la sesión en Recibos CFE."
    # Página casi vacía después de una navegación: bloqueo silencioso por IP de datacenter.
    body_html_len = len(await page.evaluate("() => document.body?.innerHTML || ''"))
    if body_html_len < 600 and not info["title"]:
        return (
            "Portal CFE devolvió página vacía. "
            "Probable bloqueo por IP de servidor (Railway). "
            "El portal público CFE requiere IP residencial o corporativa."
        )
    return None


async def _is_logged_in(page: Page) -> bool:
    if re.search(r"Login\.aspx", page.url, re.I):
        return False
    body = await page.evaluate("() => document.body?.innerText || ''")
    return not re.search(r"USUARIO:\s*|CONTRASEÑA:\s*|CAPTCHA", body, re.I)


async def _fill_public_form(page: Page, cfg: CfeScraperConfig) -> None:
    await page.wait_for_selector(
        "#MainContent_txtNombre", state="visible", timeout=cfg.timeout_ms
    )
    await page.evaluate(
        """(v) => {
            const set = (sel, val) => {
                const el = document.querySelector(sel);
                if (!el) throw new Error('No existe: ' + sel);
                el.value = val || '';
                el.dispatchEvent(new Event('input', {bubbles: true}));
            };
            set('#MainContent_txtNombre', v.nombre);
            set('#MainContent_txtRPU', v.servicio);
            set('#MainContent_tbLada', v.lada);
            set('#MainContent_txtTel', v.telefono);
            set('#MainContent_txtCel', '');
            set('#MainContent_txtCorreoElectronico', v.email);
        }""",
        {
            "nombre": cfg.nombre,
            "servicio": cfg.numero_servicio,
            "lada": cfg.lada,
            "telefono": cfg.telefono,
            "email": cfg.email,
        },
    )


def _periodo_valido(year: str, month: str) -> str:
    try:
        year_int = int(year)
        month_int = int(month)
    except ValueError:
        return ""
    if 2000 <= year_int <= 2100 and 1 <= month_int <= 12:
        return f"{year_int:04d}-{month_int:02d}"
    return ""


def _periodo_from_filename(name: str) -> str:
    for m in re.finditer(r"(\d{4})[-_]?(\d{2})", name):
        periodo = _periodo_valido(m.group(1), m.group(2))
        if periodo:
            return periodo
    return ""


def _periodo_from_fecha_cfe(value: str) -> str:
    m = re.search(
        r"\b\d{1,2}\s+(ENE|FEB|MAR|ABR|MAY|JUN|JUL|AGO|SEP|OCT|NOV|DIC)\s+(\d{2,4})\b",
        value,
        re.I,
    )
    if not m:
        return ""
    month = _MESES_CFE.get(m.group(1).upper(), "")
    year = m.group(2)
    if len(year) == 2:
        year = f"20{year}"
    return _periodo_valido(year, month)


def _periodo_from_public_text(value: str) -> str:
    m = _MESES_PUBLIC_RE.search(value or "")
    if not m:
        return ""
    month = _MESES_CFE.get(m.group(1).upper(), "")
    return _periodo_valido(m.group(2), month)


def _periodo_public_label(periodo: str) -> str:
    if len(periodo) != 7:
        return periodo
    year, month = periodo.split("-")
    return f"{_MESES_ABREV.get(month, month).title()} {year}"


def _periodo_from_xml(content: bytes) -> str:
    text = content.decode("utf-8", errors="replace")
    m = re.search(r"OCR_AAAAMM[>\s=\"]+(\d{6})", text, re.I)
    if m:
        raw = m.group(1)
        periodo = _periodo_valido(raw[:4], raw[4:6])
        if periodo:
            return periodo
    m = re.search(r"OCR_AAMM[>\s=\"]+(\d{4})", text, re.I)
    if m:
        raw = m.group(1)
        periodo = _periodo_valido(f"20{raw[:2]}", raw[2:4])
        if periodo:
            return periodo
    m = re.search(
        r"<(?:\w+:)?FECHASTA(?:\s[^>]*)?>(.*?)</(?:\w+:)?FECHASTA>",
        text,
        re.I | re.S,
    )
    if m:
        return _periodo_from_fecha_cfe(m.group(1))
    return ""


def _looks_like_xml_download(name: str, content: bytes) -> bool:
    header = content[:500].decode("utf-8", errors="ignore").lower()
    return name.lower().endswith(".xml") or "<cfdi:" in header or "<comprobante" in header


async def _save_xml_download(download) -> tuple[bytes, str] | None:
    tmp = await download.path()
    if not tmp:
        return None
    content = Path(tmp).read_bytes()
    filename = download.suggested_filename or "recibo.xml"
    if not _looks_like_xml_download(filename, content):
        logger.info("Descarga ignorada por no parecer XML: %s", filename)
        return None
    return content, filename


async def _collect_download_candidates(page: Page) -> list[dict]:
    return await page.evaluate(
        """() => Array.from(document.querySelectorAll('a, input, button'))
            .map((el, index) => ({
                index,
                tag: el.tagName.toLowerCase(),
                type: el.getAttribute('type') || '',
                id: el.id || '',
                name: el.getAttribute('name') || '',
                text: (el.innerText || el.getAttribute('value') || '').trim(),
                href: el.href || '',
            }))
            .filter(el => (el.type || '').toLowerCase() !== 'hidden')
            .filter(el => {
                const haystack = `${el.id} ${el.name} ${el.href} ${el.text}`;
                return /(pdf|xml|descarg|imprim)/i.test(haystack);
            })"""
    )


async def _try_xml_candidate_download(page: Page, candidates: list[dict], timeout_ms: int) -> tuple[bytes, str] | None:
    xml_candidates = [
        c for c in candidates
        if re.search(r"xml", f"{c.get('id','')} {c.get('name','')} {c.get('href','')} {c.get('text','')}", re.I)
    ]
    for candidate in xml_candidates[:5]:
        try:
            logger.info(
                "Probando candidato XML CFE index=%s id=%s name=%s text=%s",
                candidate.get("index"),
                candidate.get("id"),
                candidate.get("name"),
                candidate.get("text"),
            )
            async with page.expect_download(timeout=timeout_ms) as download_info:
                clicked = await page.evaluate(
                    """(index) => {
                        const controls = Array.from(document.querySelectorAll('a, input, button'));
                        const el = controls[index];
                        if (!el) return false;
                        el.click();
                        return true;
                    }""",
                    candidate["index"],
                )
                if not clicked:
                    continue
            download = await download_info.value
            result = await _save_xml_download(download)
            if result:
                return result
        except Exception as exc:
            logger.info(
                "Candidato XML CFE no produjo descarga index=%s error=%s",
                candidate.get("index"),
                exc,
            )
    return None


_PAGE_SNAPSHOT_JS = """() => ({
    url: location.href,
    title: document.title || '',
    lines: (document.body?.innerText || '')
        .split(/\\r?\\n/)
        .map(line => line.trim())
        .filter(Boolean)
        .slice(0, 12),
})"""


async def _page_snapshot(page: Page) -> dict:
    try:
        return await page.evaluate(_PAGE_SNAPSHOT_JS)
    except Exception:
        return {"url": "", "title": "", "lines": []}


async def _public_portal_diagnostic(page: Page, candidates: list[dict]) -> str:
    snapshot = await _page_snapshot(page)

    details = [
        "No se descargó el XML del portal público CFE.",
        f"URL final: {snapshot.get('url') or 'N/D'}",
    ]
    if snapshot.get("title"):
        details.append(f"Título: {snapshot['title']}")
    if snapshot.get("lines"):
        details.append("Texto visible: " + " | ".join(snapshot["lines"][:8]))
    if candidates:
        sample = [
            " / ".join(filter(None, [c.get("id"), c.get("name"), c.get("text"), c.get("href")]))[:120]
            for c in candidates[:8]
        ]
        details.append("Candidatos de descarga: " + " ; ".join(sample))
    else:
        details.append("No se encontraron candidatos de descarga XML/PDF en la página.")
    return " ".join(details)


async def _wait_for_public_rows(page: Page, timeout_ms: int) -> list[dict]:
    """
    Espera a que el historial publico termine de renderizar filas con periodo.
    Tras el login el portal tarda unos segundos en pintar la tabla; leerla antes
    devuelve cero filas y provoca descargas fallidas. Si detecta bloqueo, corta.
    """
    interval = 700
    elapsed = 0
    rows: list[dict] = []
    while elapsed < timeout_ms:
        rows = await _collect_public_period_rows(page)
        if rows:
            return rows
        block_msg = await _detect_block(page)
        if block_msg:
            raise ValueError(block_msg)
        await page.wait_for_timeout(interval)
        elapsed += interval
    return await _collect_public_period_rows(page)


async def _wait_for_otras_facturas_rows(page: Page, timeout_ms: int) -> list[dict]:
    """Espera a que gvFacturasUsuario tenga filas; el portal puede renderizar el grid vacio antes de poblarlo via PostBack."""
    interval = 700
    elapsed = 0
    while elapsed < timeout_ms:
        rows = await _collect_otras_facturas(page)
        if rows:
            return rows
        block_msg = await _detect_block(page)
        if block_msg:
            raise ValueError(block_msg)
        await page.wait_for_timeout(interval)
        elapsed += interval
    return await _collect_otras_facturas(page)


async def _open_public_history(page: Page, cfg: CfeScraperConfig) -> list[dict]:
    await page.goto(CFE_PUBLIC_URL, wait_until="networkidle", timeout=cfg.timeout_ms)

    block_msg = await _detect_block(page)
    if block_msg:
        raise ValueError(block_msg)

    await _fill_public_form(page, cfg)
    await page.click("#MainContent_btnContinuar", timeout=cfg.timeout_ms)
    try:
        await page.wait_for_load_state("networkidle", timeout=15_000)
    except _SCRAPER_TIMEOUT_ERRORS:
        pass

    rows = await _wait_for_public_rows(page, 15_000)

    block_msg = await _detect_block(page)
    if block_msg:
        raise ValueError(block_msg)
    return rows


async def _collect_public_period_rows(page: Page) -> list[dict]:
    raw_rows = await page.evaluate(
        """() => {
            const controls = Array.from(document.querySelectorAll('a, input, button'));
            const rowNodes = Array.from(document.querySelectorAll('tr'));
            const fallbackNodes = rowNodes.length
                ? []
                : Array.from(document.querySelectorAll('li, div'))
                    .filter(el => (el.innerText || '').length < 500);
            const nodes = rowNodes.length ? rowNodes : fallbackNodes;
            return nodes.map((row, rowIndex) => {
                const text = (row.innerText || row.textContent || '')
                    .replace(/\\s+/g, ' ')
                    .trim();
                const rowControls = controls.map((el, index) => {
                    if (!row.contains(el)) return null;
                    const type = el.getAttribute('type') || '';
                    if ((type || '').toLowerCase() === 'hidden') return null;
                    return {
                        index,
                        tag: el.tagName.toLowerCase(),
                        type,
                        id: el.id || '',
                        name: el.getAttribute('name') || '',
                        text: (el.innerText || el.getAttribute('value') || '').replace(/\\s+/g, ' ').trim(),
                        href: el.href || '',
                    };
                }).filter(Boolean);
                return {rowIndex, text, controls: rowControls};
            }).filter(row => row.text && row.controls.length);
        }"""
    )

    rows_by_period: dict[str, dict] = {}
    for row in raw_rows:
        periodo = _periodo_from_public_text(row.get("text", ""))
        if not periodo:
            continue
        controls = [
            c for c in row.get("controls", [])
            if re.search(r"(xml|factura|pdf|descarg)", f"{c.get('id','')} {c.get('name','')} {c.get('text','')} {c.get('href','')}", re.I)
        ]
        if not controls:
            continue
        row["periodo"] = periodo
        row["etiqueta"] = _periodo_public_label(periodo)
        row["controls"] = controls
        current = rows_by_period.get(periodo)
        score = _public_row_score(row)
        if not current or score > _public_row_score(current):
            rows_by_period[periodo] = row

    return sorted(rows_by_period.values(), key=lambda item: item["periodo"], reverse=True)


def _public_row_score(row: dict) -> int:
    controls_text = " ".join(
        f"{c.get('id','')} {c.get('name','')} {c.get('text','')} {c.get('href','')}"
        for c in row.get("controls", [])
    )
    has_xml = bool(re.search(r"(xml|factura)", controls_text, re.I))
    has_pdf = bool(re.search(r"pdf", controls_text, re.I))
    return (10 if has_xml else 0) + (10 if has_pdf else 0) - min(len(row.get("text", "")), 1000) // 100


def _public_artifact_control(row: dict, tipo: str) -> Optional[dict]:
    if tipo == "xml":
        pattern = r"(xml|factura)"
    else:
        pattern = r"pdf"
    for control in row.get("controls", []):
        haystack = f"{control.get('id','')} {control.get('name','')} {control.get('text','')} {control.get('href','')}"
        if re.search(pattern, haystack, re.I):
            return control
    return None


async def _find_public_period_row(page: Page, periodo: str) -> dict:
    rows = await _collect_public_period_rows(page)
    row = next((item for item in rows if item["periodo"] == periodo), None)
    if not row:
        raise ValueError(f"No se encontro el periodo {periodo} en el portal publico CFE.")
    return row


async def _public_history_diagnostic(page: Page, rows: list[dict]) -> str:
    snapshot = await _page_snapshot(page)
    sample = " ; ".join(
        f"{r.get('periodo', 'N/D')} {r.get('text', '')[:120]}"
        for r in rows[:8]
    ) or "N/D"
    return (
        "No se pudo descargar desde el historial del portal publico CFE. "
        f"URL final: {snapshot.get('url') or 'N/D'}. "
        f"Texto visible: {' | '.join(snapshot.get('lines', [])[:6])}. "
        f"Periodos detectados: {sample}"
    )


def _looks_like_pdf_download(name: str, content: bytes) -> bool:
    return name.lower().endswith(".pdf") or content[:4] == b"%PDF"


async def _download_public_artifact(
    page: Page,
    cfg: CfeScraperConfig,
    periodo: str,
    tipo: str,
) -> tuple[bytes, str]:
    row = await _find_public_period_row(page, periodo)
    control = _public_artifact_control(row, tipo)
    if not control:
        raise ValueError(f"No hay enlace {tipo.upper()} para el periodo {periodo}.")

    captured: list[tuple[bytes, str]] = []
    pending_resps: list = []

    def _capture_artifact(resp):
        ct = resp.headers.get("content-type", "")
        cd = resp.headers.get("content-disposition", "")
        url = resp.url
        if "cfe.mx" not in url:
            return
        if tipo == "xml":
            looks_match = (
                "xml" in ct.lower()
                or ".xml" in cd.lower()
                or re.search(r"\.xml(?:\?|$)", url, re.I)
            ) and "svg" not in ct.lower()
        else:
            looks_match = (
                "pdf" in ct.lower()
                or ".pdf" in cd.lower()
                or re.search(r"\.pdf(?:\?|$)", url, re.I)
            )
        if looks_match:
            pending_resps.append(resp)

    page.on("response", _capture_artifact)
    download_task = asyncio.create_task(page.wait_for_event("download", timeout=cfg.timeout_ms))
    try:
        logger.info(
            "Descargando %s portal publico CFE servicio=%s periodo=%s candidato=%s texto=%s",
            tipo.upper(),
            cfg.numero_servicio,
            periodo,
            control.get("id") or control.get("name") or control.get("href") or control.get("index"),
            control.get("text", "")[:80],
        )
        clicked = await page.evaluate(
            """(index) => {
                const controls = Array.from(document.querySelectorAll('a, input, button'));
                const el = controls[index];
                if (!el) return false;
                el.click();
                return true;
            }""",
            control["index"],
        )
        if not clicked:
            raise ValueError(f"No se pudo hacer click en el enlace {tipo.upper()} del periodo {periodo}.")

        done, pending = await asyncio.wait(
            {download_task},
            timeout=cfg.timeout_ms / 1000,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()

        for task in done:
            try:
                download = task.result()
            except _SCRAPER_ERRORS:
                continue
            if tipo == "xml":
                saved = await _save_xml_download(download)
                if saved:
                    return saved
            else:
                saved = await _read_download(download)
                if saved and _looks_like_pdf_download(saved[1], saved[0]):
                    return saved

        try:
            await page.wait_for_load_state("networkidle", timeout=10_000)
        except _SCRAPER_ERRORS:
            pass
        await page.wait_for_timeout(1000)

        # await resp.body() here, outside the callback, so it completes before we check
        for resp in pending_resps:
            try:
                body = await resp.body()
            except _SCRAPER_ERRORS:
                continue
            url = resp.url
            filename = url.split("/")[-1].split("?")[0] or f"{cfg.numero_servicio}-{periodo}.{tipo}"
            if tipo == "xml" and _looks_like_xml_download(filename, body):
                captured.append((body, filename))
            elif tipo == "pdf" and _looks_like_pdf_download(filename, body):
                captured.append((body, filename))

        if captured:
            return captured[0]
        raise ValueError(await _public_history_diagnostic(page, [row]))
    finally:
        if not download_task.done():
            download_task.cancel()
        try:
            page.remove_listener("response", _capture_artifact)
        except _SCRAPER_ERRORS:
            pass


async def _descargar_artefacto_con_reintento(
    page: Page,
    cfg: CfeScraperConfig,
    periodo: str,
    tipo: str,
) -> tuple[Optional[bytes], str, Optional[str]]:
    """Descarga un artefacto del portal publico con un reintento. Devuelve
    (contenido, nombre, error); error es None si se descargo correctamente."""
    last_error = ""
    for intento in range(2):
        try:
            content, filename = await _download_public_artifact(page, cfg, periodo, tipo)
            return content, filename, None
        except _SCRAPER_ERRORS as exc:
            last_error = str(exc)
            if intento == 0:
                logger.info(
                    "Reintentando %s publico CFE servicio=%s periodo=%s",
                    tipo.upper(), cfg.numero_servicio, periodo,
                )
                await page.wait_for_timeout(1200)
    logger.warning(
        "No se pudo descargar %s publico CFE servicio=%s periodo=%s error=%s",
        tipo.upper(), cfg.numero_servicio, periodo, last_error,
    )
    return None, "", last_error


def _total_recibo_sin_decimales(xml_content: Optional[bytes], xml_filename: str) -> str:
    """Total a pagar (entero, como string) de un XML CFE; '0' si no se puede leer.
    Se usa para registrar el servicio en MiEspacio cuando aun no existe."""
    if not xml_content:
        return "0"
    try:
        receipt = extraer_datos_xml(xml_content, xml_filename or "recibo.xml")
        total_val = receipt.get("cfdi", {}).get("total", 0)
        if total_val:
            return str(round(float(total_val)))
    except (ValueError, KeyError, TypeError):
        pass
    return "0"


# ── MiEspacio · Otras Facturas (XML + PDF por periodo y serie) ──────────────────
# Selectores verificados contra el portal: tabla gvFacturasUsuario, links
# lnkDescargaPDF / lnkDescargaXML, columna Serie. Una fila por (serie, periodo);
# solo el recibo real trae PDF y XML (las complementarias traen solo XML).

async def _abrir_otras_facturas(page: Page, cfg: CfeScraperConfig) -> list[dict]:
    """Desde el historial de un servicio ya seleccionado, abre 'Otras facturas' y espera a que la grilla tenga datos."""
    link = page.locator('a[id$="hplMasFacturaciones"]').first
    if not await link.count():
        raise ValueError("No se encontro el enlace 'Otras facturas' en MiEspacio.")
    await link.click(timeout=cfg.timeout_ms)
    try:
        await page.wait_for_selector("#ctl00_MainContent_gvFacturasUsuario", timeout=15_000)
    except _SCRAPER_TIMEOUT_ERRORS:
        pass
    return await _wait_for_otras_facturas_rows(page, 10_000)


async def _collect_otras_facturas(page: Page) -> list[dict]:
    return await page.evaluate(
        """() => {
            const rows = [...document.querySelectorAll('#ctl00_MainContent_gvFacturasUsuario tr')].slice(1);
            return rows.map(r => {
                const tds = [...r.querySelectorAll('td')].map(c => (c.innerText || '').trim());
                const pdf = r.querySelector('a[id$="lnkDescargaPDF"]');
                const xml = r.querySelector('a[id$="lnkDescargaXML"]');
                return {
                    serie: tds[0] || '',
                    folio: tds[1] || '',
                    anio_mes: tds[2] || '',
                    pdf_id: pdf ? pdf.id : '',
                    xml_id: xml ? xml.id : '',
                };
            }).filter(r => r.anio_mes);
        }"""
    )


async def _otras_facturas_tiene_pager(page: Page) -> bool:
    """Detecta si gvFacturasUsuario tiene paginacion (footer con PostBack Page$N).
    Si la hay, solo se leyo la primera pagina (analisis web scraping §14.2). Hoy
    no iteramos paginas; logueamos para confirmar con datos reales si hace falta."""
    try:
        return await page.evaluate(
            """() => {
                const grid = document.querySelector('#ctl00_MainContent_gvFacturasUsuario');
                if (!grid) return false;
                return [...grid.querySelectorAll('a')].some(a =>
                    /Page\\$/i.test(a.getAttribute('href') || '') ||
                    /Page\\$/i.test(a.getAttribute('name') || ''));
            }"""
        )
    except Exception:
        return False


def _otras_facturas_por_periodo(rows: list[dict]) -> list[dict]:
    """Filas de OtrasFacturas que tienen PDF y XML (el recibo real), una por
    periodo (folio mas reciente), de mas reciente a mas antiguo. Las series solo
    con XML (complementarias) se descartan."""
    por_periodo: dict[str, dict] = {}
    ocr_por_periodo: dict[str, list[str]] = {}
    for row in rows:
        if not (row.get("pdf_id") and row.get("xml_id")):
            continue
        periodo = _periodo_from_public_text(row.get("anio_mes", ""))
        if not periodo:
            continue
        ocr_por_periodo.setdefault(periodo, []).append(row.get("folio", ""))
        enriquecido = {**row, "periodo": periodo, "etiqueta": _periodo_public_label(periodo)}
        actual = por_periodo.get(periodo)
        # Folios CFE son numericos zero-padded de igual longitud -> el mayor (mas
        # reciente) gana con comparacion de string.
        if actual is None or enriquecido["folio"] > actual["folio"]:
            por_periodo[periodo] = enriquecido
    # Telemetria: si un periodo trae mas de un recibo OCR (PDF+XML), hoy solo se
    # conserva el folio mayor (analisis web scraping §7.6/§14.1). Logueamos para
    # decidir con datos reales si algun dia hace falta indexar por folio.
    for periodo, folios in ocr_por_periodo.items():
        if len(folios) > 1:
            conservado = por_periodo[periodo]["folio"]
            omitidos = [f for f in folios if f != conservado]
            logger.warning(
                "Periodo %s tiene %d recibos OCR; se conserva folio=%s, se omiten=%s",
                periodo, len(folios), conservado, omitidos,
            )
    return sorted(por_periodo.values(), key=lambda r: r["periodo"], reverse=True)


async def _descargar_otras_factura(
    page: Page, cfg: CfeScraperConfig, row: dict, tipo: str
) -> tuple[bytes, str]:
    link_id = row["pdf_id"] if tipo == "pdf" else row["xml_id"]
    if not link_id:
        raise ValueError(f"La fila de OtrasFacturas no tiene enlace {tipo.upper()}.")
    locator = page.locator(f"#{link_id}")
    if not await locator.count():
        raise ValueError(f"No se localizo el enlace {tipo.upper()} en OtrasFacturas.")

    if tipo == "xml":
        dl_promise = page.wait_for_event("download", timeout=cfg.timeout_ms)
        await locator.first.click(timeout=cfg.timeout_ms)
        download = await dl_promise
        saved = await _save_xml_download(download)
        if not saved:
            raise ValueError("La descarga XML de OtrasFacturas no parece un XML valido.")
        return saved

    # PDF: el portal puede disparar un download directo o abrir un popup/visor.
    # Se escuchan ambos eventos en paralelo, igual que en _download_pdf_candidate.
    pdf_responses: list[tuple[bytes, str]] = []

    async def _capture_pdf(resp):
        ct = resp.headers.get("content-type", "")
        cd = resp.headers.get("content-disposition", "")
        url = resp.url
        looks_pdf = (
            "application/pdf" in ct.lower()
            or ".pdf" in cd.lower()
            or re.search(r"\.pdf(?:\?|$)", url, re.I)
        )
        if looks_pdf and "cfe.mx" in url:
            try:
                body = await resp.body()
                if body and body[:4] == b"%PDF":
                    name = url.split("/")[-1].split("?")[0] or f"{cfg.numero_servicio}.pdf"
                    pdf_responses.append((body, name))
            except Exception:
                pass

    page.on("response", _capture_pdf)
    download_task = asyncio.create_task(page.wait_for_event("download", timeout=cfg.timeout_ms))
    popup_task = asyncio.create_task(page.wait_for_event("popup", timeout=cfg.timeout_ms))
    try:
        await locator.first.click(timeout=cfg.timeout_ms)
        done, pending = await asyncio.wait(
            {download_task, popup_task},
            timeout=cfg.timeout_ms / 1000,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        for task in done:
            try:
                event_value = task.result()
            except Exception:
                continue
            if hasattr(event_value, "suggested_filename"):
                saved = await _read_download(event_value)
                if saved and _looks_like_pdf_download(saved[1], saved[0]):
                    return saved
            if hasattr(event_value, "url"):
                event_value.on("response", _capture_pdf)
                try:
                    await event_value.wait_for_load_state("domcontentloaded", timeout=10_000)
                except Exception:
                    pass
                logger.info("PDF OtrasFacturas abrio popup url=%s", event_value.url)
    except Exception as exc:
        for task in (download_task, popup_task):
            if not task.done():
                task.cancel()
        if pdf_responses:
            return pdf_responses[0]
        raise ValueError(f"No se pudo descargar PDF de OtrasFacturas. Detalle: {exc}") from exc
    finally:
        page.remove_listener("response", _capture_pdf)

    await page.wait_for_timeout(1500)
    if pdf_responses:
        return pdf_responses[0]
    raise ValueError("La descarga PDF de OtrasFacturas no se completo (sin download ni respuesta valida).")


async def _descargar_otras_factura_reintento(
    page: Page, cfg: CfeScraperConfig, row: dict, tipo: str
) -> tuple[bytes, str]:
    last_error: Optional[Exception] = None
    for intento in range(2):
        try:
            return await _descargar_otras_factura(page, cfg, row, tipo)
        except _SCRAPER_ERRORS as exc:
            last_error = exc
            if intento == 0:
                await page.wait_for_timeout(1200)
    raise ValueError(
        str(last_error) if last_error else f"No se pudo descargar {tipo.upper()} de OtrasFacturas."
    )


async def _setup_miespacio_page(browser, cfg: CfeScraperConfig) -> tuple:
    """Crea contexto + pagina MiEspacio con sesion guardada (si existe) y navega al home."""
    ctx_opts: dict = {"accept_downloads": True, "ignore_https_errors": True, "user_agent": _USER_AGENT}
    if cfg.session_json:
        try:
            ctx_opts["storage_state"] = json.loads(cfg.session_json)
        except (ValueError, TypeError):
            logger.warning("Session JSON invalido, ignorando sesion guardada")
    mi_ctx = await browser.new_context(**ctx_opts)
    mi_page = await mi_ctx.new_page()
    mi_page.set_default_timeout(cfg.timeout_ms)
    await mi_page.goto(CFE_MIESPACIO_ADD_URL, wait_until="domcontentloaded", timeout=cfg.timeout_ms)
    await mi_page.wait_for_timeout(2000)
    return mi_ctx, mi_page


async def _fase_miespacio_otras(
    browser,
    cfg: CfeScraperConfig,
    total_sin_dec: str,
    max_periodos: int,
    por_periodo: dict[str, DescargaPeriodoPublicoResult],
) -> int:
    """Abre MiEspacio con la sesion guardada, registra el servicio si hace falta y
    baja XML + PDF de cada periodo desde OtrasFacturas. Devuelve el numero de
    periodos con recibo real en MiEspacio (-1 si la sesion no esta activa)."""
    mi_ctx, mi_page = await _setup_miespacio_page(browser, cfg)
    try:

        block_msg = await _detect_block(mi_page)
        if block_msg:
            for res in por_periodo.values():
                if not res.pdf_content:
                    res.pdf_error = block_msg
            return -1

        if not await _is_logged_in(mi_page):
            for res in por_periodo.values():
                if not res.pdf_content:
                    res.pdf_error = (
                        "La sesión CFE MiEspacio expiró o no existe. "
                        "Un administrador debe renovar la sesión en Admin > Configuración Global > Recibos CFE."
                    )
            return -1

        try:
            await _select_service_miespacio(mi_page, cfg)
        except MiEspacioServiceNotFound:
            await _ensure_service_miespacio(mi_page, cfg, total_sin_dec)

        rows_raw = await _abrir_otras_facturas(mi_page, cfg)
        if await _otras_facturas_tiene_pager(mi_page):
            logger.warning(
                "OtrasFacturas tiene paginacion; solo se leyo la primera pagina servicio=%s",
                cfg.numero_servicio,
            )
        facturas = _otras_facturas_por_periodo(rows_raw)

        objetivo = facturas[:max_periodos]
        for indice, row in enumerate(objetivo):
            periodo = row["periodo"]
            res = por_periodo.get(periodo) or DescargaPeriodoPublicoResult(
                periodo=periodo, etiqueta=row["etiqueta"],
            )
            for tipo in ("xml", "pdf"):
                try:
                    content, nombre = await _descargar_otras_factura_reintento(mi_page, cfg, row, tipo)
                    setattr(res, f"{tipo}_content", content)
                    setattr(res, f"{tipo}_filename", nombre)
                    setattr(res, f"{tipo}_error", None)
                except _SCRAPER_ERRORS as exc:
                    logger.warning(
                        "No se pudo descargar %s MiEspacio servicio=%s periodo=%s error=%s",
                        tipo.upper(), cfg.numero_servicio, periodo, exc,
                    )
                    setattr(res, f"{tipo}_error", str(exc))
            por_periodo[periodo] = res
            # Pausa anti-Imperva entre periodos, salvo tras el ultimo.
            if indice < len(objetivo) - 1:
                await mi_page.wait_for_timeout(_DELAY_ENTRE_PERIODOS_MS)

        # Conteo capeado a max_periodos para comparar contra el publico en la
        # misma ventana (si no, un historial largo dispara falsa discrepancia).
        return len(objetivo)
    finally:
        try:
            await mi_ctx.close()
        except _SCRAPER_ERRORS:
            pass


async def _fallback_xml_publico(
    pub_page: Page,
    cfg: CfeScraperConfig,
    por_periodo: dict[str, DescargaPeriodoPublicoResult],
    pub_rows: dict[str, dict],
) -> None:
    """Para periodos detectados en publico que aun no tienen XML (no estaban en
    MiEspacio o fallo su descarga), intenta el XML del portal publico. Todo
    periodo detectado queda representado aunque falle (no desaparece de la tabla);
    si el portal bloquea, los restantes se anotan con el motivo."""
    pendientes = sorted(
        (
            periodo for periodo in pub_rows
            if not (por_periodo.get(periodo) and por_periodo[periodo].xml_content)
        ),
        reverse=True,
    )
    bloqueo: Optional[str] = None
    for indice, periodo in enumerate(pendientes):
        res = por_periodo.get(periodo)
        if res is None:
            res = DescargaPeriodoPublicoResult(
                periodo=periodo,
                etiqueta=pub_rows[periodo].get("etiqueta") or _periodo_public_label(periodo),
            )
            res.pdf_error = "No disponible en MiEspacio."
            por_periodo[periodo] = res

        if bloqueo is None and indice:
            await pub_page.wait_for_timeout(800)
            bloqueo = await _detect_block(pub_page)

        if bloqueo:
            if not res.xml_error:
                res.xml_error = bloqueo
            continue

        content, name, err = await _descargar_artefacto_con_reintento(pub_page, cfg, periodo, "xml")
        if content:
            res.xml_content, res.xml_filename, res.xml_error = content, name, None
        elif not res.xml_error:
            res.xml_error = err


async def descargar_periodos_busqueda(
    cfg: CfeScraperConfig,
    max_periodos: int,
) -> ResultadoBusquedaPeriodos:
    """
    Busqueda de periodos CFE: MiEspacio (Otras Facturas) es la fuente principal de
    XML + PDF. El portal publico se usa para detectar/contar periodos, obtener el
    total del ultimo recibo (registro del servicio en MiEspacio si no existe) y
    como fallback de XML. Devuelve los periodos + advertencia de discrepancia de
    conteo publico vs MiEspacio.
    """
    try:
        from playwright.async_api import async_playwright
    except ModuleNotFoundError as exc:
        if exc.name != "playwright":
            raise
        raise ValueError(
            "Playwright no esta instalado en el entorno. "
            "Reconstruye la imagen Docker para instalar dependencias CFE."
        ) from exc

    browser_path = _pick_browser()
    launch_kwargs: dict = {
        "headless": True,
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
        ],
    }
    if browser_path:
        launch_kwargs["executable_path"] = browser_path

    max_periodos = max(1, min(int(max_periodos or 12), 60))
    por_periodo: dict[str, DescargaPeriodoPublicoResult] = {}
    publico_count = 0
    miespacio_count = -1

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(**launch_kwargs)
        try:
            pub_ctx = await browser.new_context(
                accept_downloads=True, ignore_https_errors=True, user_agent=_USER_AGENT,
            )
            try:
                pub_page = await pub_ctx.new_page()
                pub_page.set_default_timeout(cfg.timeout_ms)

                # ── FASE 1: portal publico (deteccion + XML del ultimo periodo) ──
                rows = await _open_public_history(pub_page, cfg)
                if not rows:
                    try:
                        body_len = await pub_page.evaluate("() => (document.body?.innerHTML || '').length")
                        page_title = await pub_page.title()
                        logger.warning(
                            "[CFE] Portal sin filas servicio=%s url=%s title=%r body_len=%s",
                            cfg.numero_servicio, pub_page.url, page_title, body_len,
                        )
                    except Exception:
                        pass
                    raise ValueError(await _public_history_diagnostic(pub_page, rows))

                objetivo = rows[:max_periodos]
                publico_count = len(objetivo)
                pub_rows = {row["periodo"]: row for row in objetivo}

                # El XML del periodo mas reciente da el total para registrar el
                # servicio en MiEspacio (si no existe) y siembra el fallback.
                nperiodo = objetivo[0]["periodo"]
                nx_content, nx_name, nx_err = await _descargar_artefacto_con_reintento(
                    pub_page, cfg, nperiodo, "xml"
                )
                seed = DescargaPeriodoPublicoResult(
                    periodo=nperiodo,
                    etiqueta=objetivo[0].get("etiqueta") or _periodo_public_label(nperiodo),
                )
                seed.xml_content, seed.xml_filename, seed.xml_error = nx_content, nx_name, nx_err
                por_periodo[nperiodo] = seed
                total_sin_dec = _total_recibo_sin_decimales(nx_content, nx_name)

                # ── FASE 2: MiEspacio · Otras Facturas (XML + PDF) ───────────────
                if cfg.mi_user and cfg.mi_pass:
                    try:
                        miespacio_count = await _fase_miespacio_otras(
                            browser, cfg, total_sin_dec, max_periodos, por_periodo,
                        )
                    except _SCRAPER_ERRORS as exc:
                        logger.warning(
                            "Fase MiEspacio fallo servicio=%s: %s", cfg.numero_servicio, exc
                        )
                        for res in por_periodo.values():
                            if not res.pdf_content and not res.pdf_error:
                                res.pdf_error = f"No se pudo usar MiEspacio: {exc}"

                # ── FASE 3: fallback de XML publico para periodos sin XML ────────
                await _fallback_xml_publico(pub_page, cfg, por_periodo, pub_rows)
            finally:
                try:
                    await pub_ctx.close()
                except _SCRAPER_ERRORS:
                    pass
        finally:
            try:
                await browser.close()
            except _SCRAPER_ERRORS:
                pass

    periodos = sorted(por_periodo.values(), key=lambda r: r.periodo, reverse=True)
    advertencia = _advertencia_discrepancia(publico=publico_count, miespacio=miespacio_count)
    return ResultadoBusquedaPeriodos(periodos=periodos, advertencia=advertencia)


async def _fill_first_matching(page: Page, labels: list[str], value: str) -> None:
    filled = await page.evaluate(
        """({labels, value}) => {
            const norm = t => String(t||'').normalize('NFD').replace(/[̀-ͯ]/g,'').toLowerCase();
            const nl = labels.map(norm);
            const inputs = [...document.querySelectorAll('input,textarea')]
                .filter(e => !['hidden','submit','button','image','checkbox','radio']
                    .includes((e.getAttribute('type')||'text').toLowerCase()));
            const best = inputs.map(inp => {
                const hay = norm([inp.id, inp.name||'', inp.placeholder||'',
                    inp.closest('tr,.form-group,div')?.innerText||''].join(' '));
                const score = nl.reduce((s,l) => hay.includes(l) ? s+l.length : s, 0);
                return {inp, score};
            }).filter(x => x.score > 0).sort((a,b) => b.score-a.score)[0];
            if (!best) return false;
            best.inp.value = value;
            best.inp.dispatchEvent(new Event('input', {bubbles:true}));
            best.inp.dispatchEvent(new Event('change', {bubbles:true}));
            return true;
        }""",
        {"labels": labels, "value": value},
    )
    if not filled:
        raise ValueError(f"No se encontró campo para: {' / '.join(labels)}")


async def _click_first_matching(page: Page, labels: list[str]) -> None:
    clicked = await page.evaluate(
        """(labels) => {
            const norm = t => String(t||'').normalize('NFD').replace(/[̀-ͯ]/g,'').toLowerCase();
            const nl = labels.map(norm);
            for (const el of document.querySelectorAll('button,input,a')) {
                if (['hidden','image'].includes((el.type||'').toLowerCase())) continue;
                const hay = norm([el.id, el.name||'', el.value||'', el.innerText||''].join(' '));
                if (nl.some(l => hay.includes(l))) { el.click(); return true; }
            }
            return false;
        }""",
        labels,
    )
    if not clicked:
        raise ValueError(f"No se encontró botón para: {' / '.join(labels)}")


async def _ensure_service_miespacio_legacy(page: Page, cfg: CfeScraperConfig, total_sin_dec: str) -> None:
    digits = re.sub(r"\D", "", cfg.numero_servicio)
    await page.goto(CFE_MIESPACIO_DEFAULT_URL, wait_until="domcontentloaded", timeout=cfg.timeout_ms)
    await page.wait_for_timeout(1500)

    exists = await page.evaluate(
        f"""() => {{
            const d = '{digits}';
            const sel = document.querySelector('#ctl00_MainContent_ddlServicios');
            const opts = sel ? [...sel.options] : [];
            return opts.some(o => (o.value+' '+o.text).replace(/\\D/g,'').includes(d))
                || (document.body?.innerText||'').replace(/\\D/g,'').includes(d);
        }}"""
    )
    if exists:
        logger.info(f"Servicio {cfg.numero_servicio} ya registrado en MiEspacio")
        return

    logger.info(f"Registrando servicio {cfg.numero_servicio} en MiEspacio...")
    await page.goto(CFE_MIESPACIO_ADD_URL, wait_until="domcontentloaded", timeout=cfg.timeout_ms)
    await page.wait_for_timeout(2000)

    await _fill_first_matching(page, ["numero de servicio", "número de servicio", "rpu"], cfg.numero_servicio)
    await _fill_first_matching(page, ["nombre del servicio", "nombre servicio"], cfg.nombre)
    await _fill_first_matching(page, ["total a pagar", "sin decimales", "total"], total_sin_dec)
    await _fill_first_matching(page, ["nombre corto", "alias", "corto"], cfg.alias or cfg.numero_servicio[:20])
    await _click_first_matching(page, ["guardar", "agregar", "aceptar"])

    await page.wait_for_load_state("domcontentloaded", timeout=10000)
    await page.wait_for_timeout(3000)



async def _select_service_miespacio(page: Page, cfg: CfeScraperConfig) -> dict:
    digits = re.sub(r"\D", "", cfg.numero_servicio)
    await page.goto(CFE_MIESPACIO_DEFAULT_URL, wait_until="domcontentloaded", timeout=cfg.timeout_ms)
    await page.wait_for_timeout(2000)

    if not await _is_logged_in(page):
        raise ValueError("No hay sesión activa al abrir MiEspacio.")

    service = await page.evaluate(
        """(digits) => {
            const digitsOnly = value => String(value || '').replace(/\\D/g, '');
            const sel = document.querySelector('#ctl00_MainContent_ddlServicios');
            const options = sel ? [...sel.options].map(o => ({
                value: o.value || '',
                text: (o.text || '').trim(),
                selected: o.selected,
                digits: digitsOnly(`${o.value} ${o.text}`),
            })) : [];
            const match = options.find(o => o.digits.includes(digits));
            return {
                exists: Boolean(match),
                bodyHasService: digitsOnly(document.body?.innerText || '').includes(digits),
                value: match?.value || '',
                text: match?.text || '',
                selectedValue: sel?.value || '',
                optionsCount: options.length,
                options: options.slice(0, 12),
            };
        }""",
        digits,
    )

    if not service["exists"] and not service["bodyHasService"]:
        raise MiEspacioServiceNotFound(f"Servicio {cfg.numero_servicio} no registrado en MiEspacio.")

    logger.info(
        "MiEspacio servicio=%s opciones=%s seleccionado=%s match=%s texto=%s body=%s",
        cfg.numero_servicio,
        service["optionsCount"],
        service["selectedValue"],
        service["value"] or "N/D",
        service["text"] or "N/D",
        service["bodyHasService"],
    )

    if service["value"] and service["selectedValue"] != service["value"]:
        nav_task = asyncio.create_task(page.wait_for_event("framenavigated", timeout=10_000))
        try:
            await page.select_option("#ctl00_MainContent_ddlServicios", service["value"])
            try:
                await nav_task
            except Exception:
                pass
        finally:
            if not nav_task.done():
                nav_task.cancel()
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=10_000)
        except Exception:
            pass
        await page.wait_for_timeout(2000)

    try:
        await page.wait_for_selector("#ctl00_MainContent_GVHistorial", timeout=10_000)
    except Exception:
        logger.info("MiEspacio historial no visible tras seleccionar servicio=%s", cfg.numero_servicio)

    return service


async def _ensure_service_miespacio(page: Page, cfg: CfeScraperConfig, total_sin_dec: str) -> None:
    try:
        await _select_service_miespacio(page, cfg)
        logger.info(f"Servicio {cfg.numero_servicio} ya registrado en MiEspacio")
        return
    except MiEspacioServiceNotFound:
        pass

    logger.info(f"Registrando servicio {cfg.numero_servicio} en MiEspacio...")
    await page.goto(CFE_MIESPACIO_ADD_URL, wait_until="domcontentloaded", timeout=cfg.timeout_ms)
    await page.wait_for_timeout(2000)

    await _fill_first_matching(page, ["numero de servicio", "número de servicio", "rpu"], cfg.numero_servicio)
    await _fill_first_matching(page, ["nombre del servicio", "nombre servicio"], cfg.nombre)
    await _fill_first_matching(page, ["total a pagar", "sin decimales", "total"], total_sin_dec)
    await _fill_first_matching(page, ["nombre corto", "alias", "corto"], cfg.alias or cfg.numero_servicio[:20])
    await _click_first_matching(page, ["guardar", "agregar", "aceptar"])

    try:
        await page.wait_for_load_state("domcontentloaded", timeout=10_000)
    except Exception:
        pass
    await page.wait_for_timeout(3000)
    try:
        await _select_service_miespacio(page, cfg)
    except MiEspacioServiceNotFound:
        logger.warning(
            "Servicio %s registrado en MiEspacio pero aun no visible (propagacion pendiente)",
            cfg.numero_servicio,
        )



async def _read_download(download) -> tuple[bytes, str] | None:
    tmp_path = await download.path()
    if not tmp_path:
        return None
    return Path(tmp_path).read_bytes(), download.suggested_filename or "recibo.pdf"



async def descargar_pdf_periodo(cfg: CfeScraperConfig, periodo: str) -> DescargaResult:
    """Descarga solo el PDF desde MiEspacio para un periodo ya conocido."""
    result = DescargaResult(periodo=periodo)
    try:
        from playwright.async_api import async_playwright
    except ModuleNotFoundError as exc:
        if exc.name != "playwright":
            raise
        result.error = (
            "Playwright no esta instalado en el entorno. "
            "Reconstruye la imagen Docker para instalar dependencias CFE."
        )
        logger.error(result.error)
        return result

    if not cfg.mi_user or not cfg.mi_pass:
        result.pdf_error = (
            "Faltan credenciales CFE MiEspacio. "
            "Configúralas en Admin > Configuración Global > Recibos CFE."
        )
        return result

    browser_path = _pick_browser()
    launch_kwargs: dict = {
        "headless": True,
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
        ],
    }
    if browser_path:
        launch_kwargs["executable_path"] = browser_path

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(**launch_kwargs)
            try:
                mi_ctx, mi_page = await _setup_miespacio_page(browser, cfg)
                try:
                    block_msg = await _detect_block(mi_page)
                    if block_msg:
                        result.pdf_error = block_msg
                        return result

                    if not await _is_logged_in(mi_page):
                        result.pdf_error = (
                            "La sesión CFE MiEspacio expiró o no existe. "
                            "Un administrador debe renovar la sesión en Admin > Configuración Global > Recibos CFE."
                        )
                        return result

                    await _select_service_miespacio(mi_page, cfg)

                    try:
                        rows_raw = await _abrir_otras_facturas(mi_page, cfg)
                        rows_by_periodo = {r["periodo"]: r for r in _otras_facturas_por_periodo(rows_raw)}
                        row = rows_by_periodo.get(periodo)
                        if not row:
                            raise ValueError(
                                f"Periodo {periodo} no encontrado en Otras Facturas de MiEspacio "
                                f"para el servicio {cfg.numero_servicio}."
                            )
                        result.pdf_content, result.pdf_filename = await _descargar_otras_factura_reintento(
                            mi_page, cfg, row, "pdf"
                        )
                    except Exception as exc:
                        logger.warning(
                            "No se pudo descargar PDF CFE servicio=%s periodo=%s error=%s",
                            cfg.numero_servicio,
                            periodo,
                            exc,
                        )
                        result.pdf_error = f"No se pudo descargar el PDF de MiEspacio: {exc}"

                    state = await mi_ctx.storage_state()
                    result.session_json_nuevo = json.dumps(state)
                finally:
                    try:
                        await mi_ctx.close()
                    except Exception:
                        pass
            finally:
                try:
                    await browser.close()
                except Exception:
                    pass
    except ValueError as exc:
        result.pdf_error = str(exc)
    except Exception as exc:
        logger.exception(f"Error inesperado descargando PDF CFE para {cfg.numero_servicio}")
        result.pdf_error = f"Error inesperado descargando PDF: {exc}"

    return result


async def descargar_recibo(cfg: CfeScraperConfig) -> DescargaResult:
    """
    Orquesta descarga completa: XML portal público + PDF MiEspacio.
    Los errores del XML se retornan en DescargaResult.error. Si el XML se
    descarga y falla MiEspacio, el detalle queda en DescargaResult.pdf_error.
    """
    result = DescargaResult()
    try:
        from playwright.async_api import async_playwright
    except ModuleNotFoundError as exc:
        if exc.name != "playwright":
            raise
        result.error = (
            "Playwright no esta instalado en el entorno. "
            "Reconstruye la imagen Docker para instalar dependencias CFE."
        )
        logger.error(result.error)
        return result

    browser_path = _pick_browser()
    launch_kwargs: dict = {
        "headless": True,
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
        ],
    }
    if browser_path:
        launch_kwargs["executable_path"] = browser_path

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(**launch_kwargs)
            try:
                # ── PASO 1: XML desde portal público ──────────────────
                xml_captured: list[bytes] = []
                xml_names: list[str] = []

                pub_ctx = await browser.new_context(
                    accept_downloads=True, ignore_https_errors=True, user_agent=_USER_AGENT
                )
                pub_page = await pub_ctx.new_page()
                pub_page.set_default_timeout(cfg.timeout_ms)

                async def _capture_xml(resp):
                    ct = resp.headers.get("content-type", "")
                    cd = resp.headers.get("content-disposition", "")
                    url = resp.url
                    looks_xml = (
                        ("xml" in ct or ".xml" in cd.lower() or re.search(r"\.xml(?:\?|$)", url, re.I))
                        and "svg" not in ct
                    )
                    if looks_xml and "cfe.mx" in url:
                        try:
                            body = await resp.body()
                            if body and _looks_like_xml_download(url.split("/")[-1].split("?")[0], body):
                                xml_captured.append(body)
                                xml_names.append(url.split("/")[-1].split("?")[0] or "recibo.xml")
                        except Exception:
                            pass

                pub_page.on("response", _capture_xml)
                await pub_page.goto(CFE_PUBLIC_URL, wait_until="networkidle", timeout=cfg.timeout_ms)

                block_msg = await _detect_block(pub_page)
                if block_msg:
                    result.error = block_msg
                    return result

                await _fill_public_form(pub_page, cfg)

                try:
                    dl_task = asyncio.create_task(pub_page.wait_for_event("download", timeout=25_000))
                    await pub_page.click("#MainContent_btnContinuar", timeout=cfg.timeout_ms)
                    done, pending = await asyncio.wait({dl_task}, timeout=25)
                    for task in pending:
                        task.cancel()
                    maybe_download = None
                    for task in done:
                        try:
                            maybe_download = task.result()
                        except Exception:
                            pass
                    if maybe_download:
                        xml_download = await _save_xml_download(maybe_download)
                        if xml_download:
                            result.xml_content, result.xml_filename = xml_download
                except Exception as exc:
                    logger.info("Descarga directa XML CFE no disponible: %s", exc)

                try:
                    await pub_page.wait_for_load_state("networkidle", timeout=10_000)
                except Exception:
                    pass
                await pub_page.wait_for_timeout(3000)

                candidates = await _collect_download_candidates(pub_page)

                if not result.xml_content and xml_captured:
                    result.xml_content = xml_captured[0]
                    result.xml_filename = xml_names[0] if xml_names else "recibo.xml"

                if not result.xml_content and candidates:
                    xml_download = await _try_xml_candidate_download(pub_page, candidates, cfg.timeout_ms)
                    if xml_download:
                        result.xml_content, result.xml_filename = xml_download

                diagnostic = None
                if not result.xml_content:
                    diagnostic = await _public_portal_diagnostic(pub_page, candidates)

                await pub_ctx.close()

                if not result.xml_content:
                    result.error = diagnostic or "No se descargó el XML del portal público CFE."
                    return result

                result.periodo = (
                    _periodo_from_filename(result.xml_filename)
                    or _periodo_from_xml(result.xml_content)
                    or "desconocido"
                )

                # ── PASO 2: PDF desde MiEspacio ───────────────────────
                if not cfg.mi_user or not cfg.mi_pass:
                    result.pdf_error = (
                        "Se descargó el XML pero faltan credenciales CFE MiEspacio. "
                        "Configúralas en Admin > Configuración Global > Recibos CFE."
                    )
                    return result

                mi_ctx, mi_page = await _setup_miespacio_page(browser, cfg)
                try:
                    block_msg = await _detect_block(mi_page)
                    if block_msg:
                        result.pdf_error = block_msg
                        return result

                    if not await _is_logged_in(mi_page):
                        result.pdf_error = (
                            "La sesión CFE MiEspacio expiró o no existe. "
                            "Un administrador debe renovar la sesión en Admin > Configuración Global > Recibos CFE."
                        )
                        return result

                    total_sin_dec = _total_recibo_sin_decimales(result.xml_content, result.xml_filename)
                    await _ensure_service_miespacio(mi_page, cfg, total_sin_dec)

                    try:
                        rows_raw = await _abrir_otras_facturas(mi_page, cfg)
                        rows_by_periodo = {r["periodo"]: r for r in _otras_facturas_por_periodo(rows_raw)}
                        row = rows_by_periodo.get(result.periodo)
                        if not row:
                            raise ValueError(
                                f"Periodo {result.periodo} no encontrado en Otras Facturas de MiEspacio "
                                f"para el servicio {cfg.numero_servicio}."
                            )
                        result.pdf_content, result.pdf_filename = await _descargar_otras_factura_reintento(
                            mi_page, cfg, row, "pdf"
                        )
                    except Exception as exc:
                        logger.warning(
                            "No se pudo descargar PDF CFE servicio=%s periodo=%s error=%s",
                            cfg.numero_servicio,
                            result.periodo,
                            exc,
                        )
                        result.pdf_error = f"No se pudo descargar el PDF de MiEspacio: {exc}"

                    state = await mi_ctx.storage_state()
                    result.session_json_nuevo = json.dumps(state)
                finally:
                    try:
                        await mi_ctx.close()
                    except Exception:
                        pass

            finally:
                try:
                    await browser.close()
                except Exception:
                    pass

    except ValueError as exc:
        if result.xml_content:
            result.pdf_error = str(exc)
        else:
            result.error = str(exc)
    except Exception as exc:
        logger.exception(f"Error inesperado en scraper CFE para {cfg.numero_servicio}")
        if result.xml_content:
            result.pdf_error = f"Error inesperado descargando PDF: {exc}"
        else:
            result.error = f"Error inesperado: {exc}"

    return result
