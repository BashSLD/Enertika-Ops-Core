"""
Regresion: get_he_evidencias_for_aprobador (modules/asistencia/db_service.py)
fallaba/dejaba sin parsear la columna jsonb `metadata`, porque asyncpg la
devuelve como str sin un codec configurado - .get("id_asistencia") sobre un
str truena. Reportado en logs de RRHH > Aprobaciones (GET /vacaciones/aprobaciones 500).
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from modules.asistencia import db_service as db

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def _insertar_evidencia(real_conn, *, asistencia_id, usuario_id):
    doc_id = uuid4()
    await real_conn.execute(
        """
        INSERT INTO tb_documentos_attachments (
            id_documento, nombre_archivo, origen_slug, activo, metadata
        ) VALUES ($1, $2, 'he_evidencia', true, $3::jsonb)
        """,
        doc_id,
        "evidencia.pdf",
        json.dumps({"id_asistencia": str(asistencia_id), "usuario_id": str(usuario_id)}),
    )
    return doc_id


async def test_get_he_evidencias_for_aprobador_parsea_metadata_string(real_conn):
    usuario_id = uuid4()
    asistencia_id = uuid4()
    doc_id = await _insertar_evidencia(real_conn, asistencia_id=asistencia_id, usuario_id=usuario_id)

    grouped = await db.get_he_evidencias_for_aprobador(real_conn, [asistencia_id])

    assert str(asistencia_id) in grouped
    ids = {row["id_documento"] for row in grouped[str(asistencia_id)]}
    assert doc_id in ids


async def test_get_he_evidencias_for_aprobador_sin_coincidencias_no_truena(real_conn):
    grouped = await db.get_he_evidencias_for_aprobador(real_conn, [uuid4()])

    assert grouped == {}
