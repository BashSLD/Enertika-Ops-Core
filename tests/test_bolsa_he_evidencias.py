"""
Tests unitarios de evidencias HE (Fase 3/4 del plan
_Planes_Activos/Planes_Anteriores_Ejecutados/2026-06-29-bolsa-horas-extra.md): validacion de MIME/tamano/cantidad
y cleanup best-effort en SharePoint si falla la transaccion DB. Mocks
sobre modules.asistencia.service - no requieren BD ni SharePoint reales.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import asyncpg
import pytest

from modules.asistencia import service as asistencia_service


class FakeConn:
    def transaction(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, *_args, **_kwargs):
        return None


class FakeUploadFile:
    def __init__(self, filename: str, content_type: str, content: bytes = b"contenido"):
        self.filename = filename
        self.content_type = content_type
        self._content = content

    async def seek(self, _offset):
        return None

    async def read(self):
        return self._content


def _fake_config(overrides: dict | None = None):
    overrides = overrides or {}

    async def fake_get_config(_conn, clave, default, tipo=str):
        if clave in overrides:
            return overrides[clave]
        return default

    return fake_get_config


def _fake_configs_bulk(overrides: dict | None = None):
    overrides = overrides or {}

    async def fake_get_configs_bulk(_conn, specs):
        return {
            clave: overrides.get(clave, default) for clave, (default, _tipo) in specs.items()
        }

    return fake_get_configs_bulk


def _patch_config(monkeypatch, overrides: dict | None = None):
    monkeypatch.setattr(asistencia_service.ConfigService, "get_global_config", _fake_config(overrides))
    monkeypatch.setattr(
        asistencia_service.ConfigService, "get_global_configs_bulk", _fake_configs_bulk(overrides)
    )


# ── _validate_he_evidencias: MIME/tamano/cantidad ──


@pytest.mark.asyncio
async def test_validate_he_evidencias_max_archivos_excedido(monkeypatch):
    _patch_config(monkeypatch)
    files = [FakeUploadFile(f"f{i}.pdf", "application/pdf") for i in range(4)]

    with pytest.raises(ValueError, match="hasta 3 archivos"):
        await asistencia_service._validate_he_evidencias(FakeConn(), files)


@pytest.mark.asyncio
async def test_validate_he_evidencias_mime_invalido(monkeypatch):
    _patch_config(monkeypatch)
    files = [FakeUploadFile("f.txt", "text/plain")]

    with pytest.raises(ValueError, match="PDF o imagenes"):
        await asistencia_service._validate_he_evidencias(FakeConn(), files)


@pytest.mark.asyncio
async def test_validate_he_evidencias_tamano_excedido(monkeypatch):
    _patch_config(monkeypatch, {"HE_EVIDENCIA_MAX_MB": 1})
    contenido_grande = b"x" * (2 * 1024 * 1024)
    files = [FakeUploadFile("f.pdf", "application/pdf", content=contenido_grande)]

    with pytest.raises(ValueError, match="maximo 1 MB"):
        await asistencia_service._validate_he_evidencias(FakeConn(), files)


@pytest.mark.asyncio
async def test_validate_he_evidencias_dentro_de_limites_ok(monkeypatch):
    _patch_config(monkeypatch)
    files = [FakeUploadFile("f.pdf", "application/pdf")]

    result = await asistencia_service._validate_he_evidencias(FakeConn(), files)

    assert [file for file, _size in result] == files
    assert [size for _file, size in result] == [len(f._content) for f in files]


# ── subir_evidencias_he_y_solicitar_svc: token de aplicacion y cleanup best-effort ──


@pytest.mark.asyncio
async def test_subir_evidencias_usa_token_de_aplicacion_no_delegado(monkeypatch, fake_sharepoint_he_evidencia):
    usuario_id = uuid4()
    asistencia_id = uuid4()

    async def fake_get_asistencia(_conn, _id):
        return {
            "usuario_id": usuario_id,
            "horas_extra_estado": "pendiente",
            "fecha_laboral": date(2026, 7, 1),
            "minutos_extra": 120,
        }

    async def fake_festivos(_conn, _inicio, _fin):
        return set()

    async def fake_solicitar(_conn, _asistencia_id, _usuario_id, _motivo):
        return True

    async def fake_insertar_evidencia(_conn, **_kwargs):
        return uuid4()

    _patch_config(monkeypatch, {"SHAREPOINT_BASE_FOLDER": "TestFolder"})
    monkeypatch.setattr(asistencia_service.db, "get_asistencia_para_aprobar", fake_get_asistencia)
    monkeypatch.setattr(asistencia_service.db, "get_festivos_range", fake_festivos)
    monkeypatch.setattr(asistencia_service.db, "solicitar_aprobacion_horas_extra", fake_solicitar)
    monkeypatch.setattr(asistencia_service.db, "insertar_he_evidencia", fake_insertar_evidencia)
    monkeypatch.setattr(asistencia_service, "_notificar_solicitud_horas_extra", lambda *a, **k: _noop())

    await asistencia_service.subir_evidencias_he_y_solicitar_svc(
        FakeConn(),
        asistencia_id=asistencia_id,
        usuario_id=usuario_id,
        motivo="Proyecto urgente",
        empleado_nombre="Empleado Test",
        evidencias=[FakeUploadFile("evidencia.pdf", "application/pdf")],
    )

    assert fake_sharepoint_he_evidencia["token_requested"] is True


async def _noop():
    return None


@pytest.mark.asyncio
async def test_subir_evidencias_cleanup_best_effort_si_falla_db(monkeypatch, fake_sharepoint_he_evidencia):
    usuario_id = uuid4()
    asistencia_id = uuid4()

    async def fake_get_asistencia(_conn, _id):
        return {
            "usuario_id": usuario_id,
            "horas_extra_estado": "pendiente",
            "fecha_laboral": date(2026, 7, 1),
            "minutos_extra": 120,
        }

    async def fake_festivos(_conn, _inicio, _fin):
        return set()

    async def fake_solicitar_falla(_conn, _asistencia_id, _usuario_id, _motivo):
        raise asyncpg.PostgresError("fallo simulado de BD")

    _patch_config(monkeypatch, {"SHAREPOINT_BASE_FOLDER": "TestFolder"})
    monkeypatch.setattr(asistencia_service.db, "get_asistencia_para_aprobar", fake_get_asistencia)
    monkeypatch.setattr(asistencia_service.db, "get_festivos_range", fake_festivos)
    monkeypatch.setattr(asistencia_service.db, "solicitar_aprobacion_horas_extra", fake_solicitar_falla)

    with pytest.raises(asyncpg.PostgresError):
        await asistencia_service.subir_evidencias_he_y_solicitar_svc(
            FakeConn(),
            asistencia_id=asistencia_id,
            usuario_id=usuario_id,
            motivo="Proyecto urgente",
            empleado_nombre="Empleado Test",
            evidencias=[FakeUploadFile("evidencia.pdf", "application/pdf")],
        )

    assert fake_sharepoint_he_evidencia["eliminados"] == fake_sharepoint_he_evidencia["subidos"]
    assert len(fake_sharepoint_he_evidencia["subidos"]) == 1
