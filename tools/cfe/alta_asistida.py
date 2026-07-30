#!/usr/bin/env python3
"""
Lanzador local: Alta asistida de servicio en MiEspacio (debug del registro).

Corre en la PC del usuario (Windows). Abre Microsoft Edge en MiEspacio, el
usuario inicia sesion y resuelve el CAPTCHA, y luego la herramienta intenta dar
de alta un servicio en AgregarServicio.aspx probando uno o varios montos de
"Total a pagar (sin decimales)", CAPTURANDO la respuesta exacta de CFE en cada
intento (mensaje de error, URL resultante, screenshot, HTML).

Objetivo: confirmar la hipotesis H1 (CFE valida el total contra su registro y
rechaza el alta si no coincide) y, de paso, registrar el servicio con el monto
correcto. Ver CFE_DEBUG_REGISTRO_MIESPACIO.md.

SUPERVISADO: antes de cada "Guardar" la herramienta hace pausa y pide Enter, para
que nada se registre sin que lo veas. Corre desde la PC del usuario para evitar el
bloqueo de IP de datacenter (Railway/proxy).

Uso:
    python alta_asistida.py

Selectores reales (verificados en dom_dump_20260612_082015):
    #ctl00_MainContent_txtRpu            Numero de servicio
    #ctl00_MainContent_txtNombreServicio Nombre del servicio
    #ctl00_MainContent_txtTotalAPagar    Total a pagar (sin decimales)
    #ctl00_MainContent_txtNombreCorto    Nombre corto
    #ctl00_MainContent_btnGuardar        Boton Guardar (input submit)

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
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:
    print("ERROR: Playwright no esta instalado. Ejecuta: pip install -r requirements.txt")
    sys.exit(1)

BASE = "https://app.cfe.mx/Aplicaciones/CCFE/MiEspacio"
DEFAULT_URL = f"{BASE}/Default.aspx"
AGREGAR_URL = f"{BASE}/AgregarServicio.aspx"

SEL_RPU = "#ctl00_MainContent_txtRpu"
SEL_NOMBRE = "#ctl00_MainContent_txtNombreServicio"
SEL_TOTAL = "#ctl00_MainContent_txtTotalAPagar"
SEL_CORTO = "#ctl00_MainContent_txtNombreCorto"
SEL_GUARDAR = "#ctl00_MainContent_btnGuardar"

POLL_INTERVAL_S = 2
LOGIN_TIMEOUT_S = 600

_EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

# Captura amplia del estado post-submit: cualquier mensaje que CFE muestre.
_CAPTURA_JS = r"""
() => {
  const grab = sel => [...document.querySelectorAll(sel)]
    .map(e => (e.innerText || e.textContent || '').trim())
    .filter(Boolean);
  const main = document.querySelector('#ctl00_MainContent, #MainContent, form');
  return {
    url: location.href,
    title: document.title || '',
    main_text: (main?.innerText || '').trim().slice(0, 1500),
    validadores: grab('[id*=Validator],[id*=valid],.field-validation-error,span[style*=color]'),
    alertas: grab('.alert,[role=alert],.message,.error,.swal2-html-container,.modal-body,.toast'),
    total_value: document.querySelector('#ctl00_MainContent_txtTotalAPagar')?.value || '',
    sigue_en_alta: /AgregarServicio/i.test(location.href),
  };
}
"""


def cargar_edge(pw):
    try:
        return pw.chromium.launch(channel="msedge", headless=False)
    except PlaywrightError:
        for ruta in _EDGE_PATHS:
            if Path(ruta).exists():
                return pw.chromium.launch(executable_path=ruta, headless=False)
        raise RuntimeError(
            "No se encontro Microsoft Edge. Instalalo o ejecuta: playwright install msedge"
        )


def esta_logueado(page) -> bool:
    try:
        url = page.evaluate("() => location.href")
        if not re.search(r"Login\.aspx", url, re.I):
            return True
        body = page.evaluate("() => document.body?.innerText || ''")
        return not re.search(r"USUARIO:\s*|CONTRASEÑA:\s*", body, re.I)
    except PlaywrightError:
        return False


def esperar_login(page) -> bool:
    print("\nSe abrio Edge en MiEspacio.")
    print("  1) Inicia sesion y resuelve el CAPTCHA.")
    print("  2) NO cierres la ventana: el login se detecta automaticamente.\n")
    print("Esperando inicio de sesion...", end="", flush=True)
    inicio = time.monotonic()
    while True:
        if esta_logueado(page):
            print("\nLogin detectado.")
            return True
        if time.monotonic() - inicio > LOGIN_TIMEOUT_S:
            print("\n  Tiempo agotado esperando el login. Reintenta.")
            return False
        print(".", end="", flush=True)
        time.sleep(POLL_INTERVAL_S)


def intentar_alta(page, datos: dict, monto: str, out_dir: Path, n: int) -> dict:
    """Llena el form y (tras confirmacion) guarda. Devuelve la captura de la respuesta."""
    print(f"\n--- Intento #{n}  monto='{monto}' ---")
    page.goto(AGREGAR_URL, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(2000)

    try:
        page.fill(SEL_RPU, datos["numero"])
        page.fill(SEL_NOMBRE, datos["nombre"])
        page.fill(SEL_TOTAL, monto)
        page.fill(SEL_CORTO, datos["corto"])
    except (KeyError, PlaywrightError) as exc:
        print(f"  ERROR llenando el formulario: {exc}")
        return {"error_local": str(exc), "monto": monto}

    page.screenshot(path=str(out_dir / f"intento{n}_pre.png"))
    print(f"  Form lleno: RPU={datos['numero']} nombre={datos['nombre']} total={monto} corto={datos['corto']}")
    print(f"  Screenshot pre-guardar: intento{n}_pre.png")
    resp = input("  >> Presiona ENTER para GUARDAR (o escribe 's' para saltar este monto): ").strip().lower()
    if resp == "s":
        print("  Saltado (no se guardo).")
        return {"saltado": True, "monto": monto}

    try:
        page.click(SEL_GUARDAR)
    except PlaywrightError as exc:
        print(f"  ERROR al hacer click en Guardar: {exc}")
        return {"error_local": str(exc), "monto": monto}

    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
    except PlaywrightError:
        pass
    page.wait_for_timeout(2500)

    try:
        captura = page.evaluate(_CAPTURA_JS)
    except PlaywrightError as exc:
        captura = {"error_captura": str(exc)}
    captura["monto"] = monto
    captura["intento"] = n

    page.screenshot(path=str(out_dir / f"intento{n}_post.png"))
    try:
        (out_dir / f"intento{n}_post.html").write_text(page.content(), encoding="utf-8")
    except OSError:
        pass
    (out_dir / f"intento{n}_resultado.json").write_text(
        json.dumps(captura, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    sigue = captura.get("sigue_en_alta", True)
    print(f"  URL resultante: {captura.get('url', '?')}")
    if captura.get("validadores"):
        print(f"  Validadores CFE: {captura['validadores']}")
    if captura.get("alertas"):
        print(f"  Alertas/mensajes: {captura['alertas']}")
    print(f"  {'AUN en AgregarServicio (probable rechazo)' if sigue else 'NAVEGO fuera (probable EXITO)'}")
    print(f"  Capturas: intento{n}_post.png / intento{n}_post.html / intento{n}_resultado.json")
    return captura


def main() -> None:
    print("=" * 60)
    print("  Alta asistida de servicio en MiEspacio (debug H1 - total)")
    print("=" * 60)

    numero = input("\nNumero de servicio (RPU): ").strip()
    nombre = input("Nombre del servicio (en MAYUSCULAS, como CFE): ").strip().upper()
    corto = input("Nombre corto / alias: ").strip() or numero[:20]
    print("\nMontos a probar (sin decimales), separados por coma.")
    print("  Sugerencia: prueba primero un monto OBVIAMENTE incorrecto (ej. 1) para")
    print("  capturar el mensaje de error de CFE, y luego el(los) correcto(s).")
    montos_raw = input("Montos: ").strip()
    montos = [m.strip() for m in montos_raw.split(",") if m.strip()]
    if not numero or not nombre or not montos:
        print("Faltan datos (numero, nombre o montos). Abortado.")
        sys.exit(1)

    datos = {"numero": numero, "nombre": nombre, "corto": corto}
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(__file__).resolve().parent / f"alta_dump_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    resultados = []
    with sync_playwright() as pw:
        browser = cargar_edge(pw)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(DEFAULT_URL, wait_until="domcontentloaded", timeout=60_000)

        if not esperar_login(page):
            ctx.close()
            browser.close()
            sys.exit(1)

        for i, monto in enumerate(montos, start=1):
            captura = intentar_alta(page, datos, monto, out_dir, i)
            resultados.append(captura)
            if captura.get("saltado") or captura.get("error_local"):
                continue
            if not captura.get("sigue_en_alta", True):
                print("\nEl servicio parece haberse registrado (CFE navego fuera del alta).")
                print("Detengo los intentos para no duplicar.")
                break
            if i < len(montos):
                input("  >> ENTER para probar el siguiente monto... ")

        ctx.close()
        browser.close()

    (out_dir / "resumen.json").write_text(
        json.dumps(resultados, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nListo. Archivos en: {out_dir}")
    print("Pega 'resumen.json' (y las capturas de error si aplica) en el chat.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelado.")
        sys.exit(130)
