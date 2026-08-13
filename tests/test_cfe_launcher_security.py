import base64
import hashlib
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from modules.cfe.launcher_security import (
    launcher_storage_filename,
    launcher_version_key,
    require_newer_launcher_version,
    validate_launcher_public_key,
    verify_launcher_manifest,
)
from modules.cfe.router import _puede_emitir_ticket_lanzador
from modules.cfe.service import CfeService, _es_dominio_cfe as _es_dominio_cfe_storage
from tools.cfe import renovar_sesion as launcher_module
from tools.cfe.renovar_sesion import (
    LOGIN_TIMEOUT_S,
    _asegurar_edge_abierto,
    _es_dominio_cfe,
    _leer_codigo_temporal,
    _mensaje_error_autorizacion,
    _storage_state_cfe,
    _validar_codigo_temporal,
    _validar_url_https,
)
from core.config import settings
from tools.cfe.sign_release import generate_keypair, sign_release


def _signed_release(content: bytes = b"trusted executable") -> tuple[bytes, str]:
    private_key = Ed25519PrivateKey.generate()
    public_key_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    payload = {
        "schema": 1,
        "filename": "RenovarSesionCFE.exe",
        "version": "2026.07.30",
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    manifest = {
        **payload,
        "signature": base64.b64encode(private_key.sign(canonical)).decode("ascii"),
    }
    return json.dumps(manifest).encode("utf-8"), public_key_pem


def test_valid_signed_manifest_is_accepted():
    content = b"trusted executable"
    manifest, public_key = _signed_release(content)

    release = verify_launcher_manifest(
        manifest,
        public_key_pem=public_key,
        actual_filename="RenovarSesionCFE.exe",
        actual_size=len(content),
        actual_sha256=hashlib.sha256(content).hexdigest(),
    )

    assert release["version"] == "2026.07.30"


def test_release_tool_manifest_is_accepted_by_backend(tmp_path, monkeypatch):
    monkeypatch.setenv("CFE_SIGNING_KEY_PASSWORD", "test-only-password")
    private_key_path = tmp_path / "private.pem"
    public_key_path = tmp_path / "public.pem"
    executable_path = tmp_path / "RenovarSesionCFE.exe"
    manifest_path = tmp_path / "RenovarSesionCFE.exe.manifest.json"
    executable_path.write_bytes(b"signed executable")

    generate_keypair(private_key_path, public_key_path)
    sign_release(
        executable_path,
        private_key_path,
        "2026.07.30",
        manifest_path,
    )

    verify_launcher_manifest(
        manifest_path.read_bytes(),
        public_key_pem=public_key_path.read_text(encoding="ascii"),
        actual_filename=executable_path.name,
        actual_size=executable_path.stat().st_size,
        actual_sha256=hashlib.sha256(executable_path.read_bytes()).hexdigest(),
    )


def test_tampered_executable_is_rejected():
    manifest, public_key = _signed_release()
    tampered = b"tainted executable"

    with pytest.raises(ValueError, match="SHA-256"):
        verify_launcher_manifest(
            manifest,
            public_key_pem=public_key,
            actual_filename="RenovarSesionCFE.exe",
            actual_size=len(tampered),
            actual_sha256=hashlib.sha256(tampered).hexdigest(),
        )


def test_tampered_manifest_signature_is_rejected():
    content = b"trusted executable"
    manifest_raw, public_key = _signed_release(content)
    manifest = json.loads(manifest_raw)
    manifest["version"] = "2026.07.31"

    with pytest.raises(ValueError, match="firma Ed25519"):
        verify_launcher_manifest(
            json.dumps(manifest).encode("utf-8"),
            public_key_pem=public_key,
            actual_filename="RenovarSesionCFE.exe",
            actual_size=len(content),
            actual_sha256=hashlib.sha256(content).hexdigest(),
        )


def test_non_ed25519_public_key_is_rejected():
    with pytest.raises(ValueError, match="PEM válido"):
        validate_launcher_public_key("not-a-public-key")


def test_launcher_versions_are_monotonic_and_storage_names_are_immutable():
    assert launcher_version_key("2026-07-30") == (2026, 7, 30, 0)
    assert launcher_version_key("2026.07.30.2") == (2026, 7, 30, 2)
    require_newer_launcher_version("2026.07.30.1", "2026-07-30")

    with pytest.raises(ValueError, match="posterior"):
        require_newer_launcher_version("2026.07.30", "2026-07-30")

    sha256_hex = "a" * 64
    assert launcher_storage_filename("2026.07.30.1", sha256_hex) == (
        "RenovarSesionCFE_2026.07.30.1_aaaaaaaaaaaa.exe"
    )


def test_launcher_version_rejects_invalid_calendar_dates():
    with pytest.raises(ValueError, match="fecha inválida"):
        launcher_version_key("2026.02.30")


def test_upload_grant_outlives_the_browser_login_window():
    assert settings.CFE_LAUNCHER_UPLOAD_GRANT_TTL_SECONDS >= LOGIN_TIMEOUT_S + 120


def test_launcher_masks_pasted_ticket(capsys):
    ticket = "a" * 43
    chars = iter([*ticket, "\r"])

    assert _leer_codigo_temporal(chars.__next__) == ticket

    output = capsys.readouterr().out
    assert ticket not in output
    assert output.endswith("*" * 43 + "\n")


def test_launcher_rejects_duplicated_ticket_before_using_it():
    with pytest.raises(RuntimeError, match="se recibieron 86"):
        _validar_codigo_temporal("a" * 86)

    assert _validar_codigo_temporal("a" * 43) == "a" * 43


def test_launcher_reports_when_edge_was_closed():
    class ClosedPage:
        @staticmethod
        def is_closed():
            return True

    with pytest.raises(RuntimeError, match="Edge se cerro"):
        _asegurar_edge_abierto(ClosedPage())


def test_launcher_explains_how_to_replace_invalid_ticket():
    message = _mensaje_error_autorizacion(403, "detalle que no debe mostrarse")

    assert "vuelve a abrirlo" in message
    assert "no reutilices" in message
    assert "detalle que no debe mostrarse" not in message


def test_launcher_preserves_non_auth_http_error_detail():
    message = _mensaje_error_autorizacion(503, "Redis no disponible")

    assert message == "No se pudo autorizar el lanzador (503): Redis no disponible"


def test_launcher_distinguishes_missing_edge(monkeypatch):
    class Chromium:
        @staticmethod
        def launch(**_kwargs):
            raise launcher_module.PlaywrightError("Edge no encontrado")

    class Playwright:
        chromium = Chromium()

    monkeypatch.setattr(launcher_module, "_EDGE_PATHS", [])

    with pytest.raises(RuntimeError, match="Edge no esta instalado"):
        launcher_module.lanzar_edge(Playwright())


def test_launcher_reports_installed_edge_control_failure(tmp_path, monkeypatch):
    edge_path = tmp_path / "msedge.exe"
    edge_path.write_bytes(b"")

    class Chromium:
        @staticmethod
        def launch(**_kwargs):
            raise launcher_module.PlaywrightError("Edge bloqueado")

    class Playwright:
        chromium = Chromium()

    monkeypatch.setattr(launcher_module, "_EDGE_PATHS", [str(edge_path)])

    with pytest.raises(RuntimeError, match="Edge esta instalado, pero"):
        launcher_module.lanzar_edge(Playwright())


def test_launcher_tries_every_installed_edge_path(tmp_path, monkeypatch):
    first_path = tmp_path / "first" / "msedge.exe"
    second_path = tmp_path / "second" / "msedge.exe"
    first_path.parent.mkdir()
    second_path.parent.mkdir()
    first_path.write_bytes(b"")
    second_path.write_bytes(b"")

    class Chromium:
        @staticmethod
        def launch(**kwargs):
            if kwargs.get("executable_path") == str(second_path):
                return "browser-abierto"
            raise launcher_module.PlaywrightError("ruta bloqueada")

    class Playwright:
        chromium = Chromium()

    monkeypatch.setattr(
        launcher_module,
        "_EDGE_PATHS",
        [str(first_path), str(second_path)],
    )

    assert launcher_module.lanzar_edge(Playwright()) == "browser-abierto"


def test_global_admin_or_module_editor_plus_can_receive_launcher_tickets():
    assert _puede_emitir_ticket_lanzador({"role": "ADMIN", "module_roles": {}})
    assert _puede_emitir_ticket_lanzador(
        {"role": "USER", "module_roles": {"oym": "admin"}}
    )
    assert _puede_emitir_ticket_lanzador(
        {"role": "MANAGER", "module_roles": {"simulacion": "editor"}}
    )
    assert _puede_emitir_ticket_lanzador(
        {"role": "USER", "module_roles": {"oym": "editor"}}
    )
    assert not _puede_emitir_ticket_lanzador(
        {"role": "USER", "module_roles": {"oym": "viewer"}}
    )
    assert not _puede_emitir_ticket_lanzador(
        {"role": "USER", "module_roles": {}}
    )


def test_storage_state_rejects_foreign_cookie_domain():
    state = json.dumps({
        "cookies": [{"name": "session", "value": "x", "domain": ".evil.example"}],
        "origins": [],
    })

    with pytest.raises(ValueError, match="dominio no permitido"):
        CfeService._validar_storage_state(state)


def test_storage_state_accepts_only_cfe_domains():
    state = json.dumps({
        "cookies": [{"name": "session", "value": "x", "domain": ".app.cfe.mx"}],
        "origins": [{"origin": "https://app.cfe.mx", "localStorage": []}],
    })

    CfeService._validar_storage_state(state)


def test_backend_storage_domain_filter_requires_dns_boundary():
    assert _es_dominio_cfe_storage("app.cfe.mx")
    assert _es_dominio_cfe_storage(".cfe.mx")
    assert not _es_dominio_cfe_storage("evilcfe.mx")
    assert not _es_dominio_cfe_storage("cfe.mx.evil.example")


def test_launcher_domain_filter_requires_dns_boundary():
    assert _es_dominio_cfe("app.cfe.mx")
    assert _es_dominio_cfe(".cfe.mx")
    assert not _es_dominio_cfe("evilcfe.mx")
    assert not _es_dominio_cfe("cfe.mx.evil.example")


def test_launcher_rejects_untrusted_or_insecure_api_urls():
    _validar_url_https("https://eco.enertika.mx/cfe/sesion/iniciar", "eco.enertika.mx")

    with pytest.raises(RuntimeError, match="URL no autorizada"):
        _validar_url_https("http://eco.enertika.mx/cfe/sesion/iniciar", "eco.enertika.mx")
    with pytest.raises(RuntimeError, match="URL no autorizada"):
        _validar_url_https("https://evil.example/cfe/sesion/iniciar", "eco.enertika.mx")


def test_launcher_filters_foreign_storage_entries():
    filtered = _storage_state_cfe({
        "cookies": [
            {"name": "allowed", "domain": ".app.cfe.mx"},
            {"name": "blocked", "domain": "evilcfe.mx"},
        ],
        "origins": [
            {"origin": "https://app.cfe.mx", "localStorage": []},
            {"origin": "https://evil.example", "localStorage": []},
        ],
    })

    assert [cookie["name"] for cookie in filtered["cookies"]] == ["allowed"]
    assert [origin["origin"] for origin in filtered["origins"]] == ["https://app.cfe.mx"]
