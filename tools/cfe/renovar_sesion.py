#!/usr/bin/env python3
"""
Lanzador local: Renovar sesion CFE MiEspacio.

Corre en la PC del usuario (Windows). Abre Microsoft Edge en la pagina de
MiEspacio, el usuario inicia sesion y resuelve el CAPTCHA, y el script captura
la sesion (storage_state de Playwright) y la sube SOLO al app via un endpoint
protegido por token compartido. No depende del administrador.

Uso:
    python renovar_sesion.py

Cada ejecucion pide un codigo temporal, individual y de un solo uso generado
desde el modal autenticado de Enertika Ops Core. No guarda secretos en disco.

Requisitos: ver requirements.txt y README.md (Playwright + navegador Edge).
"""
from __future__ import annotations

import getpass
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:
    print("ERROR: Playwright no esta instalado. Ejecuta: pip install -r requirements.txt")
    sys.exit(1)

MIESPACIO_URL = "https://app.cfe.mx/Aplicaciones/CCFE/MiEspacio/Default.aspx"
APP_BASE_URL = "https://eco.enertika.mx"
_APP_HOST = "eco.enertika.mx"
_CFE_HOST = "app.cfe.mx"
POLL_INTERVAL_S = 2
LOGIN_TIMEOUT_S = 600  # 10 min para resolver el CAPTCHA con calma

_EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_HTTPS_OPENER = urllib.request.build_opener(_NoRedirectHandler())


def _validar_url_https(url: str, expected_host: str) -> None:
    parsed = urlparse(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise RuntimeError(f"Se rechazo una URL no autorizada: {url}") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname != expected_host
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
    ):
        raise RuntimeError(f"Se rechazo una URL no autorizada: {url}")


def _leer_json_response(resp) -> dict:
    _validar_url_https(resp.geturl(), _APP_HOST)
    try:
        return json.loads(resp.read().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("El servidor devolvio una respuesta invalida.") from exc


def _es_dominio_cfe(domain: str) -> bool:
    normalized = (domain or "").strip().lstrip(".").lower()
    return normalized == "cfe.mx" or normalized.endswith(".cfe.mx")


def _detalle_http(exc: urllib.error.HTTPError) -> str:
    try:
        data = json.loads(exc.read().decode("utf-8", errors="replace"))
        return str(data.get("error") or data.get("detail") or exc.reason)
    except (json.JSONDecodeError, AttributeError):
        return str(exc.reason)


def esta_logueado(page) -> bool:
    """
    CFE puede hacer el login en-lugar (JS) sin cambiar la URL de Login.aspx.
    Se considera logueado solo cuando los campos de usuario/contrasena
    desaparecieron del DOM y existe al menos una cookie del dominio CFE.
    """
    try:
        url = page.evaluate("() => location.href")
        _validar_url_https(url, _CFE_HOST)
        login_fields = page.locator(
            "#ctl00_MainContent_txtUsuario, #ctl00_MainContent_txtPassword"
        )
        if any(
            login_fields.nth(index).is_visible()
            for index in range(login_fields.count())
        ):
            return False
        cookies = page.context.cookies([MIESPACIO_URL])
        return any(
            _es_dominio_cfe(cookie.get("domain") or "")
            for cookie in cookies
        )
    except (PlaywrightError, RuntimeError, TypeError):
        return False


def lanzar_edge(pw):
    """Intenta canal msedge; si falla usa executable_path de Edge instalado."""
    try:
        return pw.chromium.launch(channel="msedge", headless=False)
    except PlaywrightError:
        for ruta in _EDGE_PATHS:
            if Path(ruta).exists():
                return pw.chromium.launch(executable_path=ruta, headless=False)
        raise RuntimeError(
            "No se encontro Microsoft Edge. Instalalo o ejecuta: playwright install msedge"
        )


def iniciar_renovacion(ticket: str) -> dict:
    """Canjea el codigo temporal por credenciales y un grant de subida."""
    url = f"{APP_BASE_URL}/cfe/sesion/iniciar"
    _validar_url_https(url, _APP_HOST)
    req = urllib.request.Request(
        url,
        data=b"",
        method="POST",
        headers={"X-CFE-Ticket": ticket},
    )
    try:
        with _HTTPS_OPENER.open(req, timeout=15) as resp:
            data = _leer_json_response(resp)
        return {
            "usuario": data["usuario"],
            "password": data["password"],
            "upload_grant": data["upload_grant"],
        }
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"No se pudo autorizar el lanzador ({exc.code}): {_detalle_http(exc)}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"No se pudo conectar de forma segura con el app: {exc.reason}") from exc
    except KeyError as exc:
        raise RuntimeError("La respuesta de autorizacion esta incompleta.") from exc


def autocompletar_login(page, credenciales: dict) -> bool:
    """Rellena usuario/contrasena; el CAPTCHA y el boton Ingresar los resuelve la persona."""
    _validar_url_https(page.url, _CFE_HOST)
    try:
        page.fill("#ctl00_MainContent_txtUsuario", credenciales["usuario"])
        page.fill("#ctl00_MainContent_txtPassword", credenciales["password"])
        return True
    except (KeyError, PlaywrightError, TypeError) as exc:
        raise RuntimeError("No se pudo autocompletar el login seguro de CFE.") from exc


def _storage_state_cfe(storage_state: dict) -> dict:
    cookies = [
        cookie
        for cookie in storage_state.get("cookies", [])
        if _es_dominio_cfe(cookie.get("domain") or "")
    ]
    origins = []
    for origin in storage_state.get("origins", []):
        origin_url = str(origin.get("origin") or "")
        parsed = urlparse(origin_url)
        if parsed.scheme == "https" and (
            parsed.hostname == "cfe.mx" or (parsed.hostname or "").endswith(".cfe.mx")
        ):
            origins.append(origin)
    if not cookies:
        raise RuntimeError("No se encontraron cookies validas de CFE despues del login.")
    return {"cookies": cookies, "origins": origins}


def subir_sesion(upload_grant: str, storage_state: dict) -> None:
    url = f"{APP_BASE_URL}/cfe/sesion/subir"
    _validar_url_https(url, _APP_HOST)
    body = json.dumps(storage_state).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "X-CFE-Grant": upload_grant},
    )
    try:
        with _HTTPS_OPENER.open(req, timeout=30) as resp:
            data = _leer_json_response(resp)
        print(f"\n  {data.get('mensaje', 'Sesion renovada.')}")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"El app rechazo la sesion ({exc.code}): {_detalle_http(exc)}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"No se pudo conectar de forma segura con el app: {exc.reason}") from exc


def main() -> None:
    print("=" * 60)
    print("  Renovar sesion CFE MiEspacio")
    print("=" * 60)
    print(f"\nServidor autorizado: {APP_BASE_URL}")
    ticket = getpass.getpass("Codigo temporal mostrado en Enertika Ops Core: ").strip()
    if not ticket:
        raise RuntimeError("Falta el codigo temporal.")
    autorizacion = iniciar_renovacion(ticket)
    upload_grant = autorizacion.pop("upload_grant")

    with sync_playwright() as pw:
        browser = lanzar_edge(pw)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(MIESPACIO_URL, wait_until="domcontentloaded", timeout=60_000)
        _validar_url_https(page.url, _CFE_HOST)

        autocompletar_login(page, autorizacion)
        autorizacion.clear()

        print("\nSe abrio Edge en MiEspacio.")
        print("  1) Usuario y contrasena ya estan llenos. Solo resuelve el CAPTCHA y da clic en Ingresar.")
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
        _validar_url_https(page.url, _CFE_HOST)
        storage_state = _storage_state_cfe(ctx.storage_state())
        ctx.close()
        browser.close()

    subir_sesion(upload_grant, storage_state)
    print("\nSesion renovada correctamente. Ya puedes cerrar esta ventana.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelado.")
        sys.exit(130)
    except RuntimeError as exc:
        print(f"\nERROR: {exc}")
        sys.exit(1)
