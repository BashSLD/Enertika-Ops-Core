# core/cfdi/db_service.py
"""Acceso a datos compartido del dominio CFDI: datos fiscales y de contacto de la
empresa (tb_config_empresa, incluye correos operativos como el de RFQ) y auditoria
de errores fiscales (tb_cfdi_errores_fiscales). Recibe conn como parametro (patron del proyecto)."""

from typing import Optional
from uuid import UUID, uuid4
import logging

logger = logging.getLogger("Cfdi.DBService")


class CfdiDBService:

    async def get_config_empresa(self, conn) -> Optional[dict]:
        """Datos fiscales de Enertika (tb_config_empresa) para validar el RFC receptor del XML."""
        row = await conn.fetchrow("SELECT * FROM tb_config_empresa WHERE id = 1")
        return dict(row) if row else None

    async def update_config_empresa(
        self, conn, razon_social: str, rfc: str,
        codigo_postal: Optional[str], regimen_fiscal: Optional[str],
        direccion: Optional[str], telefono: Optional[str], email_contacto: Optional[str],
        email_rfq: Optional[str],
    ) -> dict:
        """Actualiza los datos fiscales de Enertika (Admin > Empresa)."""
        row = await conn.fetchrow("""
            UPDATE tb_config_empresa
            SET razon_social = $1, rfc = $2, codigo_postal = $3, regimen_fiscal = $4,
                direccion = $5, telefono = $6, email_contacto = $7, email_rfq = $8, updated_at = NOW()
            WHERE id = 1
            RETURNING *
        """, razon_social, rfc, codigo_postal, regimen_fiscal, direccion, telefono, email_contacto, email_rfq)
        return dict(row)

    async def insert_error_fiscal(
        self, conn, *, archivo: str, uuid_factura: Optional[str],
        emisor_rfc: Optional[str], emisor_nombre: Optional[str],
        tipo_error: str, detalle: str, modulo_slug: str, canal: str,
        uploaded_by_id: Optional[UUID],
    ) -> UUID:
        """Registra en tb_cfdi_errores_fiscales un XML que fallo la validacion fiscal del receptor."""
        error_id = uuid4()
        await conn.execute("""
            INSERT INTO tb_cfdi_errores_fiscales (
                id, archivo, uuid_factura, emisor_rfc, emisor_nombre,
                tipo_error, detalle, modulo_slug, canal, uploaded_by_id
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        """, error_id, archivo, uuid_factura, emisor_rfc, emisor_nombre,
             tipo_error, detalle, modulo_slug, canal, uploaded_by_id)
        return error_id

    async def get_errores_fiscales_paginado(
        self, conn, modulo_slug: str, page: int = 1, per_page: int = 50
    ) -> tuple[list[dict], int]:
        """Lista paginada de tb_cfdi_errores_fiscales para un modulo, para su pantalla
        propia de auditoria (ej. 'Facturas con Errores' de Compras)."""
        offset = (page - 1) * per_page
        rows = await conn.fetch("""
            SELECT e.*, u.nombre AS uploaded_by_nombre, COUNT(*) OVER() AS total_count
            FROM tb_cfdi_errores_fiscales e
            LEFT JOIN tb_usuarios u ON u.id_usuario = e.uploaded_by_id
            WHERE e.modulo_slug = $1
            ORDER BY e.created_at DESC
            LIMIT $2 OFFSET $3
        """, modulo_slug, per_page, offset)
        if not rows and offset > 0:
            # COUNT(*) OVER() viaja en las filas devueltas; si el offset deja la pagina vacia
            # no hay fila de la cual leer el total real, por eso se recalcula aparte.
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM tb_cfdi_errores_fiscales WHERE modulo_slug = $1", modulo_slug
            )
            return [], total
        total = rows[0]["total_count"] if rows else 0
        return [dict(r) for r in rows], total


def get_cfdi_db_service():
    return CfdiDBService()
