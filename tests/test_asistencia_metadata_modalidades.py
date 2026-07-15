from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from uuid import UUID, uuid4

import pytest

from modules.asistencia import db_service as asistencia_db
from modules.asistencia import service as asistencia_service
from modules.perfil import router as perfil_router
from modules.rrhh import router as rrhh_router


class _FakeConn:
    def __init__(self) -> None:
        self.query = ""
        self.args = ()

    async def fetch(self, query: str, *args):
        self.query = query
        self.args = args
        return []


def _row(
    usuario_id: UUID,
    *,
    estado: str = "asistencia",
    tiene_checada: bool = True,
    minutos_programados: int = 480,
) -> dict:
    return {
        "usuario_id": usuario_id,
        "fecha_laboral": date(2026, 7, 15),
        "primera_entrada": datetime(2026, 7, 15, 14, tzinfo=timezone.utc) if tiene_checada else None,
        "ultima_salida": None,
        "minutos_programados": minutos_programados,
        "estado": estado,
    }


@pytest.mark.asyncio
async def test_query_modalidades_metadata_es_batch_y_parametrizada():
    conn = _FakeConn()
    usuario_id = uuid4()

    result = await asistencia_db.get_modalidades_metadata_en_rango(
        conn,
        usuario_ids=[usuario_id],
        fecha_inicio=date(2026, 7, 1),
        fecha_fin=date(2026, 7, 31),
    )

    assert result == []
    assert "generate_series" in conn.query
    assert "sa.estado = 'aprobado'" in conn.query
    assert "COALESCE(sa.es_migracion, false) = false" in conn.query
    assert "ta.slug = ANY($4::text[])" in conn.query
    assert isinstance(conn.args[3], list)
    assert set(conn.args[3]) == {
        "home_office",
        "permiso_llegar_tarde",
        "permiso_salir_temprano",
    }


@pytest.mark.asyncio
async def test_anexar_modalidad_metadata_muestra_modalidad_valida(monkeypatch):
    usuario_id = uuid4()

    async def fake_get_modalidades(_conn, **kwargs):
        assert kwargs["usuario_ids"] == [usuario_id]
        return [{
            "usuario_id": usuario_id,
            "fecha_laboral": date(2026, 7, 15),
            "tipo_slug": "home_office",
            "tipo_nombre": "Home Office",
            "tipo_abreviatura": "HO",
            "solicitud_id": uuid4(),
        }]

    monkeypatch.setattr(asistencia_service.db, "get_modalidades_metadata_en_rango", fake_get_modalidades)
    rows = await asistencia_service.anexar_modalidad_metadata_asistencia(None, [_row(usuario_id)])

    assert rows[0]["modalidad_metadata"]["slug"] == "home_office"
    assert rows[0]["modalidad_metadata"]["abreviatura"] == "HO"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("estado", "tiene_checada", "minutos_programados"),
    [
        ("sin_registro", False, 480),
        ("descanso", True, 0),
        ("feriado", True, 0),
        ("vacaciones", True, 480),
        ("checada_en_ausencia", True, 480),
        ("asistencia", False, 480),
        ("asistencia", True, 0),
    ],
)
async def test_anexar_modalidad_metadata_excluye_estados_no_permitidos(
    monkeypatch, estado, tiene_checada, minutos_programados
):
    usuario_id = uuid4()

    async def fake_get_modalidades(_conn, **_kwargs):
        return [{
            "usuario_id": usuario_id,
            "fecha_laboral": date(2026, 7, 15),
            "tipo_slug": "home_office",
            "tipo_nombre": "Home Office",
            "tipo_abreviatura": "HO",
            "solicitud_id": uuid4(),
        }]

    monkeypatch.setattr(asistencia_service.db, "get_modalidades_metadata_en_rango", fake_get_modalidades)
    rows = await asistencia_service.anexar_modalidad_metadata_asistencia(
        None,
        [_row(
            usuario_id,
            estado=estado,
            tiene_checada=tiene_checada,
            minutos_programados=minutos_programados,
        )],
    )

    assert rows[0]["modalidad_metadata"] is None


@pytest.mark.asyncio
async def test_anexar_modalidad_metadata_registra_duplicado_y_elije_primero(monkeypatch, caplog):
    usuario_id = uuid4()

    async def fake_get_modalidades(_conn, **_kwargs):
        return [
            {
                "usuario_id": usuario_id,
                "fecha_laboral": date(2026, 7, 15),
                "tipo_slug": "home_office",
                "tipo_nombre": "Home Office",
                "tipo_abreviatura": "HO",
                "solicitud_id": uuid4(),
            },
            {
                "usuario_id": usuario_id,
                "fecha_laboral": date(2026, 7, 15),
                "tipo_slug": "permiso_llegar_tarde",
                "tipo_nombre": "Permiso para llegar tarde",
                "tipo_abreviatura": "PLT",
                "solicitud_id": uuid4(),
            },
        ]

    monkeypatch.setattr(asistencia_service.db, "get_modalidades_metadata_en_rango", fake_get_modalidades)
    with caplog.at_level(logging.WARNING, logger="asistencia.service"):
        rows = await asistencia_service.anexar_modalidad_metadata_asistencia(None, [_row(usuario_id)])

    assert rows[0]["modalidad_metadata"]["slug"] == "home_office"
    assert "Modalidades de asistencia duplicadas" in caplog.text


@pytest.mark.asyncio
async def test_fetch_asistencia_enriquece_solo_filas_visibles(monkeypatch):
    usuario_id = uuid4()
    rows = [
        {
            **_row(usuario_id),
            "fecha_laboral": date(2026, 7, day),
            "id": uuid4(),
            "minutos_trabajados": 480,
            "minutos_extra": 0,
            "minutos_he_compensatorio": 0,
        }
        for day in range(1, 17)
    ]
    enriched_ids = []

    async def fake_get_mi_asistencia(*_args, **_kwargs):
        return rows

    async def fake_anexar(_conn, visibles):
        enriched_ids.extend(row["id"] for row in visibles)
        for row in visibles:
            row["modalidad_metadata"] = None
        return visibles

    monkeypatch.setattr(perfil_router.perfil_db, "get_mi_asistencia", fake_get_mi_asistencia)
    monkeypatch.setattr(perfil_router, "anexar_modalidad_metadata_asistencia", fake_anexar)

    result, tiene_mas = await perfil_router._fetch_asistencia(
        None,
        usuario_id,
        offset=0,
        fecha_minima=date(2026, 4, 1),
    )

    assert len(result) == 15
    assert tiene_mas is True
    assert enriched_ids == [row["id"] for row in rows[:15]]


@pytest.mark.asyncio
async def test_rrhh_normaliza_usuario_id_antes_de_enriquecer_modalidad(monkeypatch):
    usuario_id = uuid4()
    raw = {
        **_row(usuario_id),
        "id_usuario": usuario_id,
        "minutos_trabajados": 480,
        "minutos_extra": 0,
        "tipo_ausencia_nombre": None,
    }
    rows_enriquecidas = []

    async def fake_get_reporte(_conn, **_kwargs):
        return [raw]

    async def fake_anexar(_conn, rows):
        rows_enriquecidas.extend(rows)
        rows[0]["modalidad_metadata"] = {"abreviatura": "HO", "nombre": "Home Office"}
        return rows

    async def fake_get_unmapped(_conn, **_kwargs):
        return []

    async def fake_get_usuarios(_conn):
        return []

    async def fake_get_sucursales(_conn):
        return []

    monkeypatch.setattr(asistencia_db, "get_reporte_asistencia", fake_get_reporte)
    monkeypatch.setattr(asistencia_service, "anexar_modalidad_metadata_asistencia", fake_anexar)
    monkeypatch.setattr(asistencia_db, "get_unmapped_biotime_checks_summary", fake_get_unmapped)
    monkeypatch.setattr(rrhh_router.vac_db, "get_usuarios_activos_simples", fake_get_usuarios)
    monkeypatch.setattr(asistencia_db, "get_sucursales", fake_get_sucursales)
    monkeypatch.setattr(rrhh_router.templates, "TemplateResponse", lambda _request, _name, context: context)

    response = await rrhh_router.asistencia_panel(
        None,
        fecha_inicio=date(2026, 7, 15),
        fecha_fin=date(2026, 7, 15),
        usuario_id=[str(usuario_id)],
        conn=None,
        context={},
    )

    assert rows_enriquecidas[0]["usuario_id"] == usuario_id
    assert response["rows"][0]["modalidad_metadata"]["abreviatura"] == "HO"
