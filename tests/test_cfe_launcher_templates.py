from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape


def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader("templates"),
        autoescape=select_autoescape(("html",)),
    )


def test_admin_launcher_upload_requires_executable_and_manifest():
    template = _environment().get_template("admin/partials/cfe_lanzador.html")

    html = template.render(
        lanzador_version="2026.07.30",
        lanzador_sha256="a" * 64,
    )

    assert 'name="archivo"' in html
    assert 'name="manifiesto"' in html
    assert "SHA-256" in html


def test_admin_launcher_public_key_form_renders():
    template = _environment().get_template("admin/partials/cfe_lanzador_clave.html")

    html = template.render(public_key="-----BEGIN PUBLIC KEY-----")

    assert 'name="cfe_lanzador_public_key"' in html
    assert "Guardar clave pública" in html


def test_launcher_modal_marks_ticket_as_sensitive_and_one_time():
    template = _environment().get_template("cfe/partials/modal_renovar_sesion.html")
    estado = {
        "sesion_estado": "expirada",
        "renovacion_habilitada": True,
        "lanzador_disponible": True,
        "lanzador_version": "2026.07.30",
    }

    html = template.render(
        estado_sesion=estado,
        ticket="ticket-temporal",
        ticket_error="",
        renovacion_autorizada=True,
        ticket_ttl_minutos=10,
        modulo="oym",
        zona_activa="Zona 1",
    )

    assert 'hx-history="false"' in html
    assert "ticket-temporal" in html
    assert "de un solo uso" in html


def test_build_requires_explicit_unsigned_mode_and_always_signs_manifest():
    build_script = Path("tools/cfe/build_exe.bat").read_text(encoding="utf-8")

    assert 'if /I not "%CFE_ALLOW_UNSIGNED%"=="1"' in build_script
    assert "CFE_AUTHENTICODE_CERT_SHA1" in build_script
    assert "--collect-all playwright" in build_script
    assert "sign_release.py sign" in build_script
