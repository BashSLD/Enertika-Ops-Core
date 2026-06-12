#!/usr/bin/env python3
"""
Lanzador local: Volcar DOM de MiEspacio (debug del alta de servicios).

Corre en la PC del usuario (Windows). Abre Microsoft Edge en MiEspacio, el
usuario inicia sesion y resuelve el CAPTCHA, y el script captura el DOM real
(campos, botones, HTML) de las paginas relevantes para diagnosticar por que
falla el registro de un servicio nuevo. NO sube nada al app: guarda archivos
locales junto al script.

Corre desde la PC del usuario para evitar el bloqueo de IP de datacenter
(Railway/proxy) que afecta al scraper headless en produccion.

Uso:
    python volcar_dom.py

Genera, en una carpeta dom_dump_<timestamp>/ junto al script:
    - default.json / default.html              (Default.aspx — dropdown ddlServicios)
    - administrar_servicios.json / .html       (AdministrarServicios.aspx)
    - agregar_servicio.json / .html            (AgregarServicio.aspx — el critico)

Pega el contenido de agregar_servicio.json en el chat para fijar los selectores
reales del formulario de alta. Ver CFE_DEBUG_REGISTRO_MIESPACIO.md.

Requisitos: Playwright + navegador Edge (mismos que renovar_sesion.py).
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:
    print("ERROR: Playwright no esta instalado. Ejecuta: pip install -r requirements.txt")
    sys.exit(1)

BASE = "https://app.cfe.mx/Aplicaciones/CCFE/MiEspacio"
DEFAULT_URL = f"{BASE}/Default.aspx"
ADMINISTRAR_URL = f"{BASE}/AdministrarServicios.aspx"
AGREGAR_URL = f"{BASE}/AgregarServicio.aspx"

POLL_INTERVAL_S = 2
LOGIN_TIMEOUT_S = 600  # 10 min para resolver el CAPTCHA con calma

_EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

# Snippet de extraccion: identico criterio al que se documento para la consola.
# Lista campos (input/select/textarea) y botones/links relevantes con su id real.
_EXTRACT_JS = r"""
() => ({
  url: location.href,
  title: document.title || '',
  campos: [...document.querySelectorAll('input,select,textarea')].map(e => ({
    tag: e.tagName.toLowerCase(),
    type: (e.getAttribute('type') || '').toLowerCase(),
    id: e.id || '',
    name: e.name || '',
    placeholder: e.placeholder || '',
    value: (e.value || '').slice(0, 40),
    contexto: (e.closest('tr,.form-group,.form-row,div')?.innerText || '').trim().slice(0, 100),
    visible: !!(e.offsetParent),
    opciones: e.tagName.toLowerCase() === 'select'
      ? [...e.options].slice(0, 20).map(o => ({ value: o.value || '', text: (o.text || '').trim() }))
      : undefined,
  })),
  botones: [...document.querySelectorAll('button,input[type=submit],input[type=button],a')]
    .map(e => ({
      tag: e.tagName.toLowerCase(),
      type: (e.getAttribute('type') || '').toLowerCase(),
      id: e.id || '',
      name: e.name || '',
      value: e.value || '',
      text: (e.innerText || '').trim().slice(0, 50),
      href: e.getAttribute('href') || '',
      visible: !!(e.offsetParent),
    }))
    .filter(b => /guardar|agregar|aceptar|servicio|administrar|nuevo|recibo/i.test(
      b.id + b.name + b.value + b.text)),
  validadores: [...document.querySelectorAll('[id*=Validator],[id*=valid],.field-validation-error,span[style*=color]')]
    .map(e => ({ id: e.id || '', text: (e.innerText || '').trim().slice(0, 120) }))
    .filter(v => v.text),
})
"""


def cargar_edge(pw):
    """Intenta canal msedge; si falla usa executable_path de Edge instalado."""
    try:
        return pw.chromium.launch(channel="msedge", headless=False)
    except Exception:
        for ruta in _EDGE_PATHS:
            if Path(ruta).exists():
                return pw.chromium.launch(executable_path=ruta, headless=False)
        raise RuntimeError(
            "No se encontro Microsoft Edge. Instalalo o ejecuta: playwright install msedge"
        )


def esta_logueado(page) -> bool:
    """CFE puede loguear en-lugar (JS) sin cambiar la URL de Login.aspx."""
    try:
        url = page.evaluate("() => location.href")
        if not re.search(r"Login\.aspx", url, re.I):
            return True
        body = page.evaluate("() => document.body?.innerText || ''")
        return not re.search(r"USUARIO:\s*|CONTRASEÑA:\s*", body, re.I)
    except Exception:
        return False


def volcar_pagina(page, url: str, nombre: str, out_dir: Path) -> None:
    print(f"\n  -> {nombre}: {url}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    except Exception as exc:
        print(f"     AVISO: no se pudo navegar ({exc}). Se omite.")
        return
    page.wait_for_timeout(2500)

    try:
        data = page.evaluate(_EXTRACT_JS)
    except Exception as exc:
        print(f"     AVISO: no se pudo extraer el DOM ({exc}).")
        data = {"url": url, "error": str(exc)}

    try:
        html = page.content()
    except Exception:
        html = ""

    (out_dir / f"{nombre}.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if html:
        (out_dir / f"{nombre}.html").write_text(html, encoding="utf-8")

    n_campos = len(data.get("campos", [])) if isinstance(data, dict) else 0
    n_botones = len(data.get("botones", [])) if isinstance(data, dict) else 0
    print(f"     OK: {n_campos} campos, {n_botones} botones/links relevantes guardados.")


def main() -> None:
    print("=" * 60)
    print("  Volcar DOM de MiEspacio (debug alta de servicios)")
    print("=" * 60)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(__file__).resolve().parent / f"dom_dump_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = cargar_edge(pw)
        ctx = browser.new_context(ignore_https_errors=True)
        page = ctx.new_page()
        page.goto(DEFAULT_URL, wait_until="domcontentloaded", timeout=60_000)

        print("\nSe abrio Edge en MiEspacio.")
        print("  1) Inicia sesion y resuelve el CAPTCHA.")
        print("  2) NO cierres la ventana: el login se detecta automaticamente.\n")
        print("Esperando inicio de sesion...", end="", flush=True)

        inicio = time.monotonic()
        while True:
            if esta_logueado(page):
                break
            if time.monotonic() - inicio > LOGIN_TIMEOUT_S:
                print("\n  Tiempo agotado esperando el login. Reintenta.")
                ctx.close()
                browser.close()
                sys.exit(1)
            print(".", end="", flush=True)
            time.sleep(POLL_INTERVAL_S)

        print("\nLogin detectado. Volcando paginas...")
        volcar_pagina(page, DEFAULT_URL, "default", out_dir)
        volcar_pagina(page, ADMINISTRAR_URL, "administrar_servicios", out_dir)
        volcar_pagina(page, AGREGAR_URL, "agregar_servicio", out_dir)

        ctx.close()
        browser.close()

    print(f"\nListo. Archivos en: {out_dir}")
    print("Pega el contenido de 'agregar_servicio.json' en el chat para fijar los selectores.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelado.")
        sys.exit(130)
