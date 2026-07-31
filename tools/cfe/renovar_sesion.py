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
import re
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
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
_TICKET_RE = re.compile(r"[A-Za-z0-9_-]{43}")

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


def _leer_codigo_temporal(read_char: Callable[[], str] | None = None) -> str:
    """Lee el ticket sin exponerlo y confirma cada caracter con un asterisco."""
    prompt = "Codigo temporal mostrado en Enertika Ops Core (veras un * por caracter): "
    if read_char is None and sys.platform != "win32":
        return getpass.getpass(prompt).strip()
    if read_char is None:
        import msvcrt

        read_char = msvcrt.getwch

    print(prompt, end="", flush=True)
    chars: list[str] = []
    while True:
        char = read_char()
        if char in ("\r", "\n"):
            print()
            return "".join(chars).strip()
        if char == "\x03":
            raise KeyboardInterrupt
        if char == "\b":
            if chars:
                chars.pop()
                print("\b \b", end="", flush=True)
            continue
        if char in ("\x00", "\xe0"):
            read_char()
            continue
        if char.isprintable():
            chars.append(char)
            print("*", end="", flush=True)


def _validar_codigo_temporal(ticket: str) -> str:
    if not ticket:
        raise RuntimeError("No se recibio ningun codigo temporal.")
    if not _TICKET_RE.fullmatch(ticket):
        raise RuntimeError(
            "El codigo temporal debe tener 43 caracteres; "
            f"se recibieron {len(ticket)}. Copia un codigo nuevo una sola vez."
        )
    return ticket


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


def _asegurar_edge_abierto(page) -> None:
    try:
        cerrado = page.is_closed()
    except PlaywrightError as exc:
        raise RuntimeError(
            "Se perdio la conexion con Microsoft Edge. Genera un codigo nuevo y reintenta."
        ) from exc
    if cerrado:
        raise RuntimeError(
            "La ventana de Microsoft Edge se cerro antes de completar el login. "
            "Genera un codigo nuevo y reintenta."
        )


def lanzar_edge(pw):
    """Intenta canal msedge; si falla usa executable_path de Edge instalado."""
    try:
        return pw.chromium.launch(channel="msedge", headless=False)
    except PlaywrightError as exc:
        edge_paths = [ruta for ruta in _EDGE_PATHS if Path(ruta).exists()]
        if not edge_paths:
            raise RuntimeError(
                "Microsoft Edge no esta instalado en este equipo. Instalalo y reintenta."
            ) from exc
        last_error = exc
        for edge_path in edge_paths:
            try:
                return pw.chromium.launch(executable_path=edge_path, headless=False)
            except PlaywrightError as fallback_exc:
                last_error = fallback_exc
        detail = str(last_error).splitlines()[0]
        raise RuntimeError(
            "Microsoft Edge esta instalado, pero el lanzador no pudo controlarlo. "
            "Cierra todas las ventanas de Edge y reintenta con un codigo nuevo. "
            f"Detalle: {detail}"
        ) from last_error


def _mensaje_error_autorizacion(status_code: int, detail: str) -> str:
    if status_code == 403:
        return (
            "El codigo temporal ya no es valido. Cierra el modal de renovacion, "
            "vuelve a abrirlo y copia el codigo nuevo; no reutilices el anterior."
        )
    return f"No se pudo autorizar el lanzador ({status_code}): {detail}"


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
        raise RuntimeError(_mensaje_error_autorizacion(exc.code, _detalle_http(exc))) from exc
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
    ticket = _validar_codigo_temporal(_leer_codigo_temporal())
    print(f"Codigo recibido ({len(ticket)} caracteres). Validando con Enertika Ops Core...")
    autorizacion = iniciar_renovacion(ticket)
    upload_grant = autorizacion.pop("upload_grant")
    print("Codigo validado. Iniciando Microsoft Edge...")

    with sync_playwright() as pw:
        browser = lanzar_edge(pw)
        try:
            ctx = browser.new_context()
            try:
                page = ctx.new_page()
                try:
                    page.goto(MIESPACIO_URL, wait_until="domcontentloaded", timeout=60_000)
                except PlaywrightError as exc:
                    raise RuntimeError(
                        "Edge se abrio, pero no pudo cargar MiEspacio. "
                        "Verifica la conexion a Internet e intenta con un codigo nuevo."
                    ) from exc
                _validar_url_https(page.url, _CFE_HOST)

                try:
                    autocompletar_login(page, autorizacion)
                finally:
                    autorizacion.clear()

                print("\nSe abrio Edge en MiEspacio.")
                print("  1) Usuario y contrasena ya estan llenos. Solo resuelve el CAPTCHA y da clic en Ingresar.")
                print("  2) NO cierres la ventana: el login se detecta automaticamente.\n")
                print("Esperando inicio de sesion...", end="", flush=True)

                inicio = time.monotonic()
                while True:
                    _asegurar_edge_abierto(page)
                    if esta_logueado(page):
                        break
                    if time.monotonic() - inicio > LOGIN_TIMEOUT_S:
                        raise RuntimeError(
                            "Tiempo agotado esperando el login. Genera un codigo nuevo y reintenta."
                        )
                    print(".", end="", flush=True)
                    time.sleep(POLL_INTERVAL_S)

                print("\nLogin detectado. Capturando sesion...")
                _validar_url_https(page.url, _CFE_HOST)
                storage_state = _storage_state_cfe(ctx.storage_state())
            finally:
                try:
                    ctx.close()
                except PlaywrightError:
                    pass
        finally:
            try:
                browser.close()
            except PlaywrightError:
                pass

    subir_sesion(upload_grant, storage_state)
    print("\nSesion renovada correctamente. Ya puedes cerrar esta ventana.")


def _pausar_antes_de_cerrar() -> None:
    try:
        input("\nPresiona ENTER para cerrar esta ventana...")
    except (EOFError, OSError):
        pass


def _ejecutar() -> int:
    try:
        main()
        return 0
    except KeyboardInterrupt:
        print("\nCancelado.")
        return 130
    except RuntimeError as exc:
        print(f"\nERROR: {exc}")
        return 1
    except PlaywrightError as exc:
        detail = str(exc).splitlines()[0]
        print("\nERROR: No se pudo controlar Microsoft Edge con Playwright.")
        print(f"Detalle: {detail}")
        return 1
    except OSError as exc:
        print(f"\nERROR: Windows no pudo completar la operacion: {exc}")
        return 1


if __name__ == "__main__":
    exit_code = _ejecutar()
    _pausar_antes_de_cerrar()
    sys.exit(exit_code)
