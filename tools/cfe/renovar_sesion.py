#!/usr/bin/env python3
"""
Lanzador local: Renovar sesion CFE MiEspacio.

Corre en la PC del usuario (Windows). Abre Microsoft Edge en la pagina de
MiEspacio, el usuario inicia sesion y resuelve el CAPTCHA, y el script captura
la sesion (storage_state de Playwright) y la sube SOLO al app via un endpoint
protegido por token compartido. No depende del administrador.

Uso:
    python renovar_sesion.py

La primera vez pide la URL del app y el token (los guarda en cfe_config.json
junto al script para no volver a pedirlos).

Requisitos: ver requirements.txt y README.md (Playwright + navegador Edge).
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:
    print("ERROR: Playwright no esta instalado. Ejecuta: pip install -r requirements.txt")
    sys.exit(1)

MIESPACIO_URL = "https://app.cfe.mx/Aplicaciones/CCFE/MiEspacio/Default.aspx"
CONFIG_PATH = (
    Path(sys.executable).resolve().parent / "cfe_config.json"
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent / "cfe_config.json"
)
POLL_INTERVAL_S = 2
LOGIN_TIMEOUT_S = 600  # 10 min para resolver el CAPTCHA con calma

_EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


APP_BASE_URL = "https://eco.enertika.mx"


def cargar_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            print(f"Aviso: no se pudo leer {CONFIG_PATH.name}, se pedira de nuevo.")
    print(f"\nURL del app: {APP_BASE_URL}")
    print("Token: obtenlo en Admin > Configuracion Global > Recibos CFE")
    cfg = {
        "app_base_url": APP_BASE_URL,
        "token": input("Token de renovacion CFE: ").strip(),
    }
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        print(f"Configuracion guardada en {CONFIG_PATH.name}")
    except OSError as exc:
        print(f"Aviso: no se pudo guardar la configuracion: {exc}")
    return cfg


def esta_logueado(page) -> bool:
    """
    CFE puede hacer el login en-lugar (JS) sin cambiar la URL de Login.aspx.
    Se considera logueado cuando la URL ya no es Login.aspx O cuando los
    campos de usuario/contrasena desaparecieron del DOM.
    """
    try:
        url = page.evaluate("() => location.href")
        if not re.search(r"Login\.aspx", url, re.I):
            return True
        body = page.evaluate("() => document.body?.innerText || ''")
        return not re.search(r"USUARIO:\s*|CONTRASEÑA:\s*", body, re.I)
    except Exception:
        return False


def lanzar_edge(pw):
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


def subir_sesion(app_base_url: str, token: str, storage_state: dict) -> None:
    url = f"{app_base_url}/cfe/sesion/subir"
    body = json.dumps(storage_state).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "X-CFE-Token": token},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        print(f"\n  {data.get('mensaje', 'Sesion renovada.')}")
    except urllib.error.HTTPError as exc:
        detalle = exc.read().decode("utf-8", errors="replace")
        try:
            detalle = json.loads(detalle).get("error", detalle)
        except json.JSONDecodeError:
            pass
        print(f"\n  ERROR {exc.code}: {detalle}")
        sys.exit(1)
    except urllib.error.URLError as exc:
        print(f"\n  ERROR de conexion con el app: {exc.reason}")
        sys.exit(1)


def main() -> None:
    print("=" * 60)
    print("  Renovar sesion CFE MiEspacio")
    print("=" * 60)
    cfg = cargar_config()
    if not cfg.get("app_base_url") or not cfg.get("token"):
        print("Falta URL del app o token. Borra cfe_config.json y reintenta.")
        sys.exit(1)

    with sync_playwright() as pw:
        browser = lanzar_edge(pw)
        ctx = browser.new_context(ignore_https_errors=True)
        page = ctx.new_page()
        page.goto(MIESPACIO_URL, wait_until="domcontentloaded", timeout=60_000)

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

        print("\nLogin detectado. Capturando sesion...")
        storage_state = ctx.storage_state()
        ctx.close()
        browser.close()

    subir_sesion(cfg["app_base_url"], cfg["token"], storage_state)
    print("\nSesion renovada correctamente. Ya puedes cerrar esta ventana.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelado.")
        sys.exit(130)
