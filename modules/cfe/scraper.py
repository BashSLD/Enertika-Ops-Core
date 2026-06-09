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
from typing import Optional

from playwright.async_api import async_playwright, Page, BrowserContext

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

_MESES_ABREV = {
    "01": "ENE", "02": "FEB", "03": "MAR", "04": "ABR",
    "05": "MAY", "06": "JUN", "07": "JUL", "08": "AGO",
    "09": "SEP", "10": "OCT", "11": "NOV", "12": "DIC",
}


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


def _pick_browser() -> Optional[str]:
    for p in _BROWSER_PATHS:
        if Path(p).exists():
            return p
    return None  # Playwright usará su propio Chromium gestionado


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


def _periodo_from_filename(name: str) -> str:
    m = re.search(r"(\d{4})[-_]?(\d{2})", name)
    return f"{m.group(1)}-{m.group(2)}" if m else ""


def _periodo_from_xml(content: bytes) -> str:
    text = content.decode("utf-8", errors="replace")
    m = re.search(r"OCR_AAAAMM[>\s=\"]+(\d{6})", text, re.I)
    if m:
        raw = m.group(1)
        return f"{raw[:4]}-{raw[4:6]}"
    m = re.search(r"OCR_AAMM[>\s=\"]+(\d{4})", text, re.I)
    if m:
        raw = m.group(1)
        return f"20{raw[:2]}-{raw[2:4]}"
    return ""


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


async def _ensure_service_miespacio(page: Page, cfg: CfeScraperConfig, total_sin_dec: str) -> None:
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


async def _download_period_pdf(page: Page, cfg: CfeScraperConfig, periodo: str) -> tuple[bytes, str]:
    digits = re.sub(r"\D", "", cfg.numero_servicio)

    await page.goto(CFE_MIESPACIO_DEFAULT_URL, wait_until="domcontentloaded", timeout=cfg.timeout_ms)
    await page.wait_for_timeout(2000)

    await page.evaluate(
        f"""() => {{
            const sel = document.querySelector('#ctl00_MainContent_ddlServicios');
            if (!sel) return;
            const opt = [...sel.options].find(o => (o.value+' '+o.text).replace(/\\D/g,'').includes('{digits}'));
            if (opt && sel.value !== opt.value) {{
                sel.value = opt.value;
                sel.dispatchEvent(new Event('change', {{bubbles:true}}));
            }}
        }}"""
    )
    await page.wait_for_timeout(2000)

    candidates = await page.evaluate(
        """() => {
            const rows = [...document.querySelectorAll('#ctl00_MainContent_GVHistorial tr')].slice(1);
            return rows.map((r,i) => {
                const link = r.querySelector('a[id$="DescargaPDF"],a[href*="DescargaPDF"]');
                const text = r.innerText?.replace(/\s+/g,' ').trim()||'';
                const pm = text.match(/\b(ENE|FEB|MAR|ABR|MAY|JUN|JUL|AGO|SEP|OCT|NOV|DIC)\s+\d{4}\b/i);
                return {index:i, id:link?.id||'', href:link?.href||'', periodText: pm?pm[0].toUpperCase():''};
            }).filter(c => c.id || c.href);
        }"""
    )

    if not candidates:
        raise ValueError(
            f"No hay PDFs en el historial de MiEspacio para el servicio {cfg.numero_servicio}. "
            "Verifica que el servicio esté registrado correctamente."
        )

    target = ""
    if len(periodo) == 7:
        year, month = periodo.split("-")
        target = f"{_MESES_ABREV.get(month, '')} {year}"

    candidate = next((c for c in candidates if target and target in c["periodText"]), candidates[0])

    loc_id = candidate["id"].replace("$", r"\$") if candidate["id"] else ""
    locator = page.locator(f"#{loc_id}") if loc_id else page.locator(f'a[href="{candidate["href"]}"]')

    if not await locator.count():
        raise ValueError("No se pudo localizar el enlace PDF en la página de MiEspacio.")

    dl_promise = page.wait_for_event("download", timeout=cfg.timeout_ms)
    await locator.first.click(timeout=cfg.timeout_ms)
    download = await dl_promise

    tmp_path = await download.path()
    if not tmp_path:
        raise ValueError("La descarga del PDF no se completó. Intenta nuevamente.")

    content = Path(tmp_path).read_bytes()
    return content, download.suggested_filename or f"{cfg.numero_servicio}-{periodo}.pdf"


async def descargar_recibo(cfg: CfeScraperConfig) -> DescargaResult:
    """
    Orquesta descarga completa: XML portal público + PDF MiEspacio.
    Todos los errores se capturan y retornan en DescargaResult.error para
    mostrarlos al usuario con contexto claro.
    """
    result = DescargaResult()
    browser_path = _pick_browser()
    launch_kwargs: dict = {
        "headless": True,
        "args": ["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-dev-shm-usage"],
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
                    if "xml" in ct and "cfe.mx" in resp.url and "svg" not in ct:
                        try:
                            body = await resp.body()
                            if body:
                                xml_captured.append(body)
                                xml_names.append(resp.url.split("/")[-1].split("?")[0] or "recibo.xml")
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
                    dl_promise = pub_page.wait_for_event("download", timeout=25_000)
                    await pub_page.click("#MainContent_btnContinuar", timeout=cfg.timeout_ms)
                    download = await asyncio.wait_for(asyncio.ensure_future(dl_promise), timeout=25)
                    tmp = await download.path()
                    if tmp:
                        result.xml_content = Path(tmp).read_bytes()
                        result.xml_filename = download.suggested_filename or "recibo.xml"
                except (asyncio.TimeoutError, Exception):
                    pass

                await pub_page.wait_for_load_state("networkidle", timeout=10_000)
                await pub_page.wait_for_timeout(2000)
                await pub_ctx.close()

                if not result.xml_content and xml_captured:
                    result.xml_content = xml_captured[0]
                    result.xml_filename = xml_names[0] if xml_names else "recibo.xml"

                if not result.xml_content:
                    result.error = (
                        "No se descargó el XML del portal público CFE. "
                        "Verifica que el número de servicio, nombre y datos de contacto sean correctos."
                    )
                    return result

                result.periodo = _periodo_from_filename(result.xml_filename) or _periodo_from_xml(result.xml_content)

                # ── PASO 2: PDF desde MiEspacio ───────────────────────
                if not cfg.mi_user or not cfg.mi_pass:
                    result.error = (
                        "Se descargó el XML pero faltan credenciales CFE MiEspacio. "
                        "Configúralas en Admin > Configuración Global > Recibos CFE."
                    )
                    return result

                ctx_opts: dict = {
                    "accept_downloads": True,
                    "ignore_https_errors": True,
                    "user_agent": _USER_AGENT,
                }
                if cfg.session_json:
                    try:
                        ctx_opts["storage_state"] = json.loads(cfg.session_json)
                    except (json.JSONDecodeError, Exception):
                        logger.warning("Session JSON inválido, ignorando sesión guardada")

                mi_ctx: BrowserContext = await browser.new_context(**ctx_opts)
                mi_page = await mi_ctx.new_page()
                mi_page.set_default_timeout(cfg.timeout_ms)

                await mi_page.goto(CFE_MIESPACIO_ADD_URL, wait_until="domcontentloaded", timeout=cfg.timeout_ms)
                await mi_page.wait_for_timeout(2000)

                if not await _is_logged_in(mi_page):
                    result.error = (
                        "La sesión CFE MiEspacio expiró o no existe. "
                        "Un administrador debe renovar la sesión en Admin > Configuración Global > Recibos CFE."
                    )
                    return result

                from modules.shared.services.cfe.extractor import extraer_datos_xml
                try:
                    receipt = extraer_datos_xml(result.xml_content, result.xml_filename)
                    total_val = receipt.get("cfdi", {}).get("total", 0)
                    total_sin_dec = str(round(float(total_val))) if total_val else "0"
                except (ValueError, KeyError, TypeError):
                    total_sin_dec = "0"

                await _ensure_service_miespacio(mi_page, cfg, total_sin_dec)

                result.pdf_content, result.pdf_filename = await _download_period_pdf(
                    mi_page, cfg, result.periodo
                )

                state = await mi_ctx.storage_state()
                result.session_json_nuevo = json.dumps(state)
                await mi_ctx.close()

            finally:
                await browser.close()

    except ValueError as exc:
        result.error = str(exc)
    except Exception as exc:
        logger.exception(f"Error inesperado en scraper CFE para {cfg.numero_servicio}")
        result.error = f"Error inesperado: {exc}"

    return result
