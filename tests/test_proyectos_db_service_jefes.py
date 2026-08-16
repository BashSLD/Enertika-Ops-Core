"""
Test de integracion (BD real, DEV, rollback automatico via real_conn) para el
punto 6.6 (doc 37/41): confirma que la migracion 167 dejo pasar 'jefe_compras'
en el CHECK de tb_usuarios.rol_organizacional, y que get_jefes_organizacionales
ya incluye ese rol en su filtro.
"""
from uuid import uuid4

import pytest

from modules.proyectos.db_service import ProyectosDBService


@pytest.mark.asyncio
async def test_get_jefes_organizacionales_incluye_jefe_compras(real_conn):
    db = ProyectosDBService()
    id_usuario = uuid4()
    await real_conn.execute(
        """
        INSERT INTO tb_usuarios (id_usuario, email, nombre, rol_organizacional, is_active)
        VALUES ($1, $2, 'Jefe Compras Test', 'jefe_compras', TRUE)
        """,
        id_usuario,
        f"jefe-compras-test-{id_usuario}@example.com",
    )

    jefes = await db.get_jefes_organizacionales(real_conn)

    ids = {j["id_usuario"] for j in jefes}
    assert id_usuario in ids
