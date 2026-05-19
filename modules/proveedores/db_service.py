"""Queries SQL compartidas para proveedores y expediente documental."""

from datetime import timedelta
from typing import Optional
from uuid import UUID, uuid4

from core.timezone import today_mx
from .constants import DIAS_PROXIMO_VENCIMIENTO


class ProveedoresDBService:
    """Capa de datos compartida para proveedores."""

    async def get_documentos_proveedor(self, conn, id_proveedor: UUID) -> list[dict]:
        rows = await conn.fetch(
            """
            SELECT d.*, u.nombre AS subido_por_nombre
            FROM tb_proveedor_documentos d
            LEFT JOIN tb_usuarios u ON u.id_usuario = d.subido_por
            WHERE d.id_proveedor = $1
            ORDER BY
                CASE
                    WHEN COALESCE(d.estatus, CASE WHEN d.vigente THEN 'vigente' ELSE 'historico' END) = 'vigente' THEN 0
                    WHEN COALESCE(d.estatus, CASE WHEN d.vigente THEN 'vigente' ELSE 'historico' END) = 'historico' THEN 1
                    ELSE 2
                END,
                d.tipo_documento ASC,
                COALESCE(d.version, 1) DESC
            """,
            id_proveedor,
        )
        return [dict(r) for r in rows]

    async def get_documento_archivo(
        self,
        conn,
        id_proveedor: UUID,
        doc_id: UUID,
    ) -> Optional[dict]:
        row = await conn.fetchrow(
            """
            SELECT
                d.*,
                p.rfc,
                p.razon_social,
                p.nombre_comercial
            FROM tb_proveedor_documentos d
            JOIN tb_proveedores p ON p.id_proveedor = d.id_proveedor
            WHERE d.id_proveedor = $1
              AND d.id = $2
              AND COALESCE(d.estatus, CASE WHEN d.vigente THEN 'vigente' ELSE 'historico' END) != 'eliminado'
            """,
            id_proveedor,
            doc_id,
        )
        return dict(row) if row else None

    async def get_documentos_vigentes_proveedor(
        self,
        conn,
        id_proveedor: UUID,
    ) -> list[dict]:
        rows = await conn.fetch(
            """
            SELECT
                d.*,
                p.rfc,
                p.razon_social,
                p.nombre_comercial
            FROM tb_proveedor_documentos d
            JOIN tb_proveedores p ON p.id_proveedor = d.id_proveedor
            WHERE d.id_proveedor = $1
              AND COALESCE(d.estatus, CASE WHEN d.vigente THEN 'vigente' ELSE 'historico' END) = 'vigente'
            ORDER BY d.tipo_documento ASC, COALESCE(d.periodo, '') DESC, COALESCE(d.version, 1) DESC
            """,
            id_proveedor,
        )
        return [dict(r) for r in rows]

    async def insert_documento_proveedor(
        self,
        conn,
        id_proveedor: UUID,
        tipo_documento: str,
        tipo_persona: str,
        sharepoint_url: str,
        fecha_vencimiento=None,
        fecha_documento=None,
        subido_por: Optional[UUID] = None,
        notas: Optional[str] = None,
        id_documento_attachment: Optional[UUID] = None,
        nombre_archivo: Optional[str] = None,
        tipo_contenido: Optional[str] = None,
        tamano_bytes: Optional[int] = None,
        drive_item_id: Optional[str] = None,
        parent_drive_id: Optional[str] = None,
        folder_path: Optional[str] = None,
        periodo: Optional[str] = None,
        nombre_documento_personalizado: Optional[str] = None,
    ) -> dict:
        async with conn.transaction():
            estado = await conn.fetchrow(
                """
                SELECT
                    MAX(COALESCE(version, 1)) AS max_version,
                    (SELECT id FROM tb_proveedor_documentos
                     WHERE id_proveedor = $1
                       AND tipo_documento = $2
                       AND periodo IS NOT DISTINCT FROM $3
                       AND nombre_documento_personalizado IS NOT DISTINCT FROM $4
                       AND COALESCE(estatus, CASE WHEN vigente THEN 'vigente' ELSE 'historico' END) = 'vigente'
                     ORDER BY COALESCE(version, 1) DESC, created_at DESC
                     LIMIT 1
                    ) AS vigente_id
                FROM tb_proveedor_documentos
                WHERE id_proveedor = $1
                  AND tipo_documento = $2
                  AND periodo IS NOT DISTINCT FROM $3
                  AND nombre_documento_personalizado IS NOT DISTINCT FROM $4
                """,
                id_proveedor,
                tipo_documento,
                periodo,
                nombre_documento_personalizado,
            )
            version = int(estado["max_version"] or 0) + 1
            vigente_id = estado["vigente_id"] if estado else None

            if vigente_id:
                await conn.execute(
                    """
                    UPDATE tb_proveedor_documentos
                    SET vigente = FALSE,
                        estatus = 'historico',
                        updated_at = NOW()
                    WHERE id = $1
                    """,
                    vigente_id,
                )

            row = await conn.fetchrow(
                """
                INSERT INTO tb_proveedor_documentos (
                    id_proveedor, tipo_documento, tipo_persona, sharepoint_url,
                    fecha_documento, fecha_vencimiento, vigente, subido_por, notas,
                    id_documento_attachment, nombre_archivo, tipo_contenido, tamano_bytes,
                    drive_item_id, parent_drive_id, folder_path, periodo,
                    nombre_documento_personalizado, version, reemplaza_a, estatus
                )
                VALUES (
                    $1,$2,$3,$4,$5,$6,TRUE,$7,$8,
                    $9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,'vigente'
                )
                RETURNING *
                """,
                id_proveedor,
                tipo_documento,
                tipo_persona,
                sharepoint_url,
                fecha_documento,
                fecha_vencimiento,
                subido_por,
                notas,
                id_documento_attachment,
                nombre_archivo,
                tipo_contenido,
                tamano_bytes,
                drive_item_id,
                parent_drive_id,
                folder_path,
                periodo,
                nombre_documento_personalizado,
                version,
                vigente_id,
            )
        return dict(row)

    async def delete_documento_proveedor(self, conn, doc_id: UUID) -> bool:
        result = await conn.execute(
            """
            DELETE FROM tb_proveedor_documentos WHERE id = $1
            """,
            doc_id,
        )
        return result.split()[-1] != "0"

    async def get_proveedores_con_estatus_docs(self, conn) -> list[dict]:
        """Proveedores activos con agregados documentales para Finanzas."""
        hoy = today_mx()
        proximo_hasta = hoy + timedelta(days=DIAS_PROXIMO_VENCIMIENTO)
        rows = await conn.fetch(
            """
            SELECT
                p.id_proveedor,
                p.nombre_comercial,
                p.razon_social,
                p.rfc,
                STRING_AGG(DISTINCT d.tipo_persona, ', ') FILTER (
                    WHERE COALESCE(d.estatus, CASE WHEN d.vigente THEN 'vigente' ELSE 'historico' END) = 'vigente'
                      AND d.tipo_persona IS NOT NULL
                ) AS tipos_persona_docs,
                COUNT(d.id) FILTER (
                    WHERE COALESCE(d.estatus, CASE WHEN d.vigente THEN 'vigente' ELSE 'historico' END) = 'vigente'
                ) AS docs_vigentes,
                COUNT(d.id) AS total_docs,
                COUNT(d.id) FILTER (
                    WHERE COALESCE(d.estatus, CASE WHEN d.vigente THEN 'vigente' ELSE 'historico' END) = 'vigente'
                      AND d.fecha_vencimiento IS NOT NULL
                      AND d.fecha_vencimiento <= $1
                ) AS docs_vencidos,
                COUNT(d.id) FILTER (
                    WHERE COALESCE(d.estatus, CASE WHEN d.vigente THEN 'vigente' ELSE 'historico' END) = 'vigente'
                      AND d.fecha_vencimiento IS NOT NULL
                      AND d.fecha_vencimiento > $1
                      AND d.fecha_vencimiento <= $2
                ) AS docs_proximos,
                MIN(d.fecha_vencimiento) FILTER (
                    WHERE COALESCE(d.estatus, CASE WHEN d.vigente THEN 'vigente' ELSE 'historico' END) = 'vigente'
                      AND d.fecha_vencimiento IS NOT NULL
                      AND d.fecha_vencimiento > $1
                ) AS prox_vencimiento
            FROM tb_proveedores p
            LEFT JOIN tb_proveedor_documentos d ON d.id_proveedor = p.id_proveedor
            WHERE p.activo = TRUE
            GROUP BY p.id_proveedor
            ORDER BY p.nombre_comercial ASC
            """,
            hoy,
            proximo_hasta,
        )
        return [dict(r) for r in rows]

    async def get_proveedores_lista(
        self,
        conn,
        busqueda: str = "",
        solo_activos: bool = False,
        page: int = 1,
        per_page: int = 50,
    ) -> list[dict]:
        """Lista paginada de proveedores con conteo de comprobantes vinculados."""
        busqueda = busqueda or ""
        rows = await conn.fetch(
            """
            SELECT
                p.id_proveedor,
                p.rfc,
                p.razon_social,
                p.nombre_comercial,
                p.activo,
                p.created_at,
                COUNT(DISTINCT c.id_comprobante) AS total_comprobantes
            FROM tb_proveedores p
            LEFT JOIN tb_comprobantes_pago c ON c.id_proveedor = p.id_proveedor
            WHERE (
                $1 = ''
                OR p.rfc ILIKE $2
                OR p.razon_social ILIKE $2
                OR p.nombre_comercial ILIKE $2
            )
              AND ($3 = FALSE OR p.activo = TRUE)
            GROUP BY p.id_proveedor, p.rfc, p.razon_social, p.nombre_comercial, p.activo, p.created_at
            ORDER BY p.razon_social
            LIMIT $4 OFFSET $5
            """,
            busqueda,
            f"%{busqueda}%",
            solo_activos,
            per_page,
            (page - 1) * per_page,
        )
        return [dict(r) for r in rows]

    async def count_proveedores(
        self,
        conn,
        busqueda: str = "",
        solo_activos: bool = False,
    ) -> int:
        """Cuenta total de proveedores para paginacion."""
        busqueda = busqueda or ""
        return await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM tb_proveedores
            WHERE (
                $1 = ''
                OR rfc ILIKE $2
                OR razon_social ILIKE $2
                OR nombre_comercial ILIKE $2
            )
              AND ($3 = FALSE OR activo = TRUE)
            """,
            busqueda,
            f"%{busqueda}%",
            solo_activos,
        )

    async def get_proveedor_detalle(self, conn, id_proveedor: UUID) -> Optional[dict]:
        """Obtiene un proveedor por ID con conteo de comprobantes."""
        row = await conn.fetchrow(
            """
            SELECT
                p.*,
                COUNT(DISTINCT c.id_comprobante) AS total_comprobantes
            FROM tb_proveedores p
            LEFT JOIN tb_comprobantes_pago c ON c.id_proveedor = p.id_proveedor
            WHERE p.id_proveedor = $1
            GROUP BY p.id_proveedor
            """,
            id_proveedor,
        )
        return dict(row) if row else None

    async def check_rfc_duplicado(
        self,
        conn,
        rfc: str,
        excluir_id: Optional[UUID] = None,
    ) -> bool:
        """Verifica si el RFC ya existe en otro proveedor."""
        return bool(
            await conn.fetchval(
                """
                SELECT 1
                FROM tb_proveedores
                WHERE rfc = $1
                  AND ($2::uuid IS NULL OR id_proveedor != $2)
                """,
                rfc,
                excluir_id,
            )
        )

    async def insert_proveedor(
        self,
        conn,
        rfc: str,
        razon_social: str,
        nombre_comercial: Optional[str],
    ) -> dict:
        """Crea un nuevo proveedor."""
        new_id = uuid4()
        row = await conn.fetchrow(
            """
            INSERT INTO tb_proveedores (id_proveedor, rfc, razon_social, nombre_comercial, activo, created_at, updated_at)
            VALUES ($1, $2, $3, $4, TRUE, NOW(), NOW())
            RETURNING *
            """,
            new_id,
            rfc.upper().strip(),
            razon_social.strip(),
            (nombre_comercial or "").strip() or None,
        )
        return dict(row)

    async def update_proveedor(
        self,
        conn,
        id_proveedor: UUID,
        rfc: str,
        razon_social: str,
        nombre_comercial: Optional[str],
    ) -> Optional[dict]:
        """Actualiza datos de un proveedor."""
        row = await conn.fetchrow(
            """
            UPDATE tb_proveedores
            SET rfc = $2, razon_social = $3, nombre_comercial = $4, updated_at = NOW()
            WHERE id_proveedor = $1
            RETURNING *
            """,
            id_proveedor,
            rfc.upper().strip(),
            razon_social.strip(),
            (nombre_comercial or "").strip() or None,
        )
        return dict(row) if row else None

    async def toggle_proveedor_activo(self, conn, id_proveedor: UUID) -> Optional[dict]:
        """Alterna el campo activo de un proveedor."""
        row = await conn.fetchrow(
            """
            UPDATE tb_proveedores
            SET activo = NOT activo, updated_at = NOW()
            WHERE id_proveedor = $1
            RETURNING *
            """,
            id_proveedor,
        )
        return dict(row) if row else None


def get_proveedores_db_service() -> ProveedoresDBService:
    return ProveedoresDBService()
