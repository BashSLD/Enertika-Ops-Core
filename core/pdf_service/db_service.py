from typing import Dict, Iterable, Optional


class PDFDBService:
    """Queries SQL puras usadas por el servicio de PDFs."""

    async def get_config_value(self, conn, key: str) -> Optional[str]:
        row = await conn.fetchrow(
            "SELECT valor FROM tb_configuracion_global WHERE clave = $1",
            key,
        )
        return row["valor"] if row else None

    async def get_config_values(self, conn, keys: Iterable[str]) -> Dict[str, str]:
        rows = await conn.fetch(
            """
            SELECT clave, valor
            FROM tb_configuracion_global
            WHERE clave = ANY($1::text[])
            """,
            list(keys),
        )
        return {row["clave"]: (row["valor"] or "").strip() for row in rows}


def get_pdf_db_service() -> PDFDBService:
    return PDFDBService()
