"""
BOM – Compras: cotizaciones, autorizaciones Fase D, trazabilidad, tipo de
cambio, resumen de compra y RFQ. Mixin incluido en BomDBService.
"""

import json
from uuid import UUID
from typing import Optional, List


class BomComprasDBMixin:
    """Cotizaciones, autorizaciones Fase D, conciliacion, resumen de compra y RFQ."""

    # ─── COTIZACIONES ────────────────────────────────────────

    async def crear_cotizacion(
        self, conn, bom_id: UUID, proveedor_id: Optional[UUID],
        nombre_proveedor: Optional[str], moneda: str,
        subtotal, iva, total, notas: Optional[str], creado_por: UUID,
        rfq_id: Optional[UUID] = None,
    ) -> dict:
        row = await conn.fetchrow("""
            INSERT INTO tb_bom_cotizaciones
                (bom_id, proveedor_id, nombre_proveedor, moneda,
                 subtotal, iva, total, notas, creado_por, rfq_id)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            RETURNING *
        """, bom_id, proveedor_id, nombre_proveedor, moneda,
            subtotal, iva, total, notas, creado_por, rfq_id)
        return dict(row)

    async def agregar_items_cotizacion(
        self, conn, cotizacion_id: UUID, bom_id: UUID, items: list
    ) -> None:
        """Inserta ítems en tb_bom_cotizacion_items en lote."""
        await conn.executemany("""
            INSERT INTO tb_bom_cotizacion_items
                (cotizacion_id, bom_id, bom_item_id, precio_unitario, cantidad,
                 moneda, subtotal_linea, grupo_ids_snapshot,
                 grupo_distribucion_snapshot)
            SELECT $1,$2,$3,$4,$5,$6,$7,
                   grupos.ids,
                   COALESCE((
                       SELECT JSONB_AGG(JSONB_BUILD_OBJECT(
                           'id_grupo', d.id_grupo,
                           'codigo', d.grupo_codigo_snapshot,
                           'nombre', d.grupo_nombre_snapshot,
                           'porcentaje', d.porcentaje
                       ) ORDER BY d.id_grupo)
                       FROM tb_bom_item_grupo_asignaciones d
                       WHERE d.id_bom_item = $3
                       HAVING ABS(SUM(d.porcentaje) - 1) <= 0.000001
                   ), grupos.distribucion_unica, '[]'::JSONB)
            CROSS JOIN LATERAL (
                WITH efectivos AS (
                    SELECT operativo.id_grupo
                    FROM tb_bom_item_grupos_operativos operativo
                    WHERE operativo.id_item = $3
                    UNION ALL
                    SELECT base.id_grupo
                    FROM tb_bom_item_grupos base
                    WHERE base.id_item = $3
                      AND NOT EXISTS (
                          SELECT 1
                          FROM tb_bom_item_grupos_operativos operativo
                          WHERE operativo.id_item = $3
                      )
                )
                SELECT COALESCE(
                           ARRAY_AGG(efectivo.id_grupo ORDER BY efectivo.id_grupo),
                           ARRAY[]::INTEGER[]
                       ) AS ids,
                       CASE WHEN COUNT(*) = 1 THEN
                           JSONB_BUILD_ARRAY(JSONB_BUILD_OBJECT(
                               'id_grupo', MIN(efectivo.id_grupo),
                               'codigo', MIN(catalogo.codigo),
                               'nombre', MIN(catalogo.nombre),
                               'porcentaje', 1
                           ))
                       END AS distribucion_unica
                FROM efectivos efectivo
                JOIN tb_cat_grupos_bom catalogo
                  ON catalogo.id = efectivo.id_grupo
            ) grupos
            ON CONFLICT (cotizacion_id, bom_item_id) DO NOTHING
        """, [
            (cotizacion_id, bom_id,
             i['bom_item_id'], i['precio_unitario'], i['cantidad'],
             i.get('moneda', 'MXN'), i['subtotal_linea'])
            for i in items
        ])

    async def get_cotizaciones_by_bom(self, conn, bom_id: UUID) -> List[dict]:
        rows = await conn.fetch("""
            SELECT c.*,
                   u.nombre AS creado_por_nombre,
                   item_count.total AS total_items_cotizacion,
                   ap.id AS aprobacion_id,
                   ap.estatus AS aprobacion_estatus,
                   ap.lock_version AS aprobacion_lock_version,
                   ap.comentarios_solicitud,
                   ap.comentarios_direccion,
                   ap.motivo_rechazo AS aprobacion_motivo_rechazo,
                   a.id AS autorizacion_id,
                   a.estatus AS autorizacion_estatus,
                   a.lock_version AS autorizacion_lock_version
            FROM tb_bom_cotizaciones c
            LEFT JOIN tb_usuarios u ON u.id_usuario = c.creado_por
            LEFT JOIN LATERAL (
                SELECT COUNT(*) AS total
                FROM tb_bom_cotizacion_items ci
                WHERE ci.cotizacion_id = c.id
            ) item_count ON TRUE
            LEFT JOIN LATERAL (
                SELECT aprobacion.*
                FROM tb_bom_cotizacion_aprobaciones aprobacion
                WHERE aprobacion.cotizacion_id = c.id
                ORDER BY aprobacion.created_at DESC, aprobacion.id DESC
                LIMIT 1
            ) ap ON TRUE
            LEFT JOIN tb_bom_autorizaciones a ON a.cotizacion_id = c.id
            WHERE c.bom_id = $1
            ORDER BY c.creado_en DESC
        """, bom_id)
        return [dict(r) for r in rows]

    async def get_cotizacion_aprobaciones_direccion(
        self, conn, estatus: Optional[str] = None,
        id_proyecto: Optional[UUID] = None,
        nombre_proveedor: Optional[str] = None,
    ) -> List[dict]:
        """Aprobaciones de cotizacion post-BOM para el dashboard de Direccion (todos los proyectos)."""
        condiciones = []
        params = []
        if estatus:
            params.append(estatus)
            condiciones.append(f"ap.estatus = ${len(params)}")
        if id_proyecto:
            params.append(id_proyecto)
            condiciones.append(f"ap.proyecto_id = ${len(params)}")
        if nombre_proveedor:
            params.append(f"%{nombre_proveedor}%")
            condiciones.append(f"c.nombre_proveedor ILIKE ${len(params)}")
        where = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""

        rows = await conn.fetch(f"""
            SELECT
                ap.id AS aprobacion_id, ap.estatus AS aprobacion_estatus,
                ap.lock_version AS aprobacion_lock_version,
                ap.solicitado_en, ap.aprobado_en, ap.rechazado_en,
                ap.comentarios_solicitud, ap.comentarios_direccion, ap.motivo_rechazo,
                c.id AS cotizacion_id, c.lock_version AS cotizacion_lock_version,
                c.nombre_proveedor, c.total, c.moneda, c.pdf_url,
                b.id_bom, b.version AS bom_version,
                paquete.codigo AS paquete_codigo, paquete.nombre AS paquete_nombre,
                p.id_proyecto, p.proyecto_id_estandar, p.nombre_corto AS nombre_proyecto,
                cl.nombre_fiscal AS cliente_nombre,
                a.id AS autorizacion_id, a.estatus AS autorizacion_estatus,
                a.lock_version AS autorizacion_lock_version
            FROM tb_bom_cotizacion_aprobaciones ap
            JOIN tb_bom_cotizaciones c ON c.id = ap.cotizacion_id
            JOIN tb_bom b ON b.id_bom = ap.bom_id
            JOIN tb_bom_paquetes paquete ON paquete.id_paquete = b.id_paquete
            JOIN tb_proyectos_gate p ON p.id_proyecto = ap.proyecto_id
            LEFT JOIN tb_oportunidades op ON op.id_oportunidad = p.id_oportunidad
            LEFT JOIN tb_clientes cl ON cl.id = op.cliente_id
            LEFT JOIN tb_bom_autorizaciones a ON a.cotizacion_id = c.id
            {where}
            ORDER BY COALESCE(ap.aprobado_en, ap.rechazado_en, ap.solicitado_en) DESC
            LIMIT 200
        """, *params)
        return [dict(r) for r in rows]

    async def get_cotizacion_by_id(self, conn, cotizacion_id: UUID) -> Optional[dict]:
        row = await conn.fetchrow("""
            SELECT c.*,
                   u.nombre AS creado_por_nombre
            FROM tb_bom_cotizaciones c
            LEFT JOIN tb_usuarios u ON u.id_usuario = c.creado_por
            WHERE c.id = $1
        """, cotizacion_id)
        return dict(row) if row else None

    async def get_cotizacion_for_update(
        self, conn, cotizacion_id: UUID,
    ) -> Optional[dict]:
        row = await conn.fetchrow("""
            SELECT * FROM tb_bom_cotizaciones
            WHERE id = $1
            FOR UPDATE
        """, cotizacion_id)
        return dict(row) if row else None

    async def get_items_cotizacion(self, conn, cotizacion_id: UUID) -> List[dict]:
        rows = await conn.fetch("""
            SELECT ci.*,
                   bi.descripcion, bi.unidad_medida, bi.id_categoria,
                   cat.nombre AS categoria_nombre
            FROM tb_bom_cotizacion_items ci
            JOIN tb_bom_items bi ON bi.id_item = ci.bom_item_id
            LEFT JOIN tb_cat_categorias_compra cat ON cat.id = bi.id_categoria
            WHERE ci.cotizacion_id = $1
            ORDER BY bi.orden ASC
        """, cotizacion_id)
        return [dict(r) for r in rows]

    async def get_items_by_cotizacion_ids(self, conn, cotizacion_ids: list) -> List[dict]:
        rows = await conn.fetch("""
            SELECT ci.*,
                   bi.descripcion, bi.unidad_medida, bi.id_categoria,
                   cat.nombre AS categoria_nombre
            FROM tb_bom_cotizacion_items ci
            JOIN tb_bom_items bi ON bi.id_item = ci.bom_item_id
            LEFT JOIN tb_cat_categorias_compra cat ON cat.id = bi.id_categoria
            WHERE ci.cotizacion_id = ANY($1::uuid[])
            ORDER BY ci.cotizacion_id, bi.orden ASC
        """, cotizacion_ids)
        return [dict(r) for r in rows]

    async def actualizar_estatus_cotizacion(
        self, conn, cotizacion_id: UUID, estatus: str,
        estatus_esperado: str, lock_version_esperado: int,
    ) -> Optional[dict]:
        row = await conn.fetchrow("""
            UPDATE tb_bom_cotizaciones
            SET estatus = $2, actualizado_en = NOW(),
                lock_version = lock_version + 1
            WHERE id = $1 AND estatus = $3 AND lock_version = $4
            RETURNING *
        """, cotizacion_id, estatus, estatus_esperado, lock_version_esperado)
        return dict(row) if row else None

    async def incrementar_lock_cotizacion_cas(
        self, conn, cotizacion_id: UUID, estatus_esperado: str,
        lock_version_esperado: int,
    ) -> Optional[dict]:
        row = await conn.fetchrow("""
            UPDATE tb_bom_cotizaciones
            SET lock_version = lock_version + 1,
                actualizado_en = NOW()
            WHERE id = $1
              AND estatus = $2
              AND lock_version = $3
            RETURNING *
        """, cotizacion_id, estatus_esperado, lock_version_esperado)
        return dict(row) if row else None

    async def devolver_cotizacion_borrador(
        self, conn, cotizacion_id: UUID, motivo: str,
        estatus_esperado: str, lock_version_esperado: int,
    ) -> Optional[dict]:
        """Devuelve cotización a BORRADOR con comentarios_revision."""
        row = await conn.fetchrow("""
            UPDATE tb_bom_cotizaciones
            SET estatus = 'BORRADOR',
                comentarios_revision = $2,
                actualizado_en = NOW(),
                lock_version = lock_version + 1
            WHERE id = $1 AND estatus = $3 AND lock_version = $4
            RETURNING *
        """, cotizacion_id, motivo, estatus_esperado, lock_version_esperado)
        return dict(row) if row else None

    async def actualizar_pdf_cotizacion(
        self, conn, cotizacion_id: UUID, pdf_url: str,
        lock_version_esperado: int,
    ) -> Optional[dict]:
        row = await conn.fetchrow("""
            UPDATE tb_bom_cotizaciones
            SET pdf_url = $2, estatus = 'RECIBIDA', actualizado_en = NOW(),
                lock_version = lock_version + 1
            WHERE id = $1 AND estatus IN ('BORRADOR', 'RECIBIDA')
              AND lock_version = $3
            RETURNING *
        """, cotizacion_id, pdf_url, lock_version_esperado)
        return dict(row) if row else None

    async def eliminar_attachment_huerfano(self, conn, doc_id: UUID) -> None:
        """Borra un attachment recien subido a SharePoint cuando el CAS que lo
        iba a referenciar (actualizar_pdf_cotizacion) fallo por lock_version o
        estatus obsoletos. Evita que get_pdf_attachment_cotizacion lo sirva por
        error en el preview al ser el mas reciente sin estar realmente vigente."""
        await conn.execute("DELETE FROM tb_documentos_attachments WHERE id_documento = $1", doc_id)

    async def get_pdf_attachment_cotizacion(
        self, conn, cotizacion_id: UUID, doc_id: Optional[UUID] = None,
    ) -> Optional[dict]:
        """Un PDF de la cotizacion; sin doc_id devuelve el mas reciente."""
        if doc_id:
            row = await conn.fetchrow("""
                SELECT id_documento, nombre_archivo, url_sharepoint, drive_item_id,
                       parent_drive_id, tipo_contenido, tamano_bytes
                FROM tb_documentos_attachments
                WHERE id_bom_cotizacion = $1 AND id_documento = $2 AND activo = TRUE
            """, cotizacion_id, doc_id)
        else:
            row = await conn.fetchrow("""
                SELECT id_documento, nombre_archivo, url_sharepoint, drive_item_id,
                       parent_drive_id, tipo_contenido, tamano_bytes
                FROM tb_documentos_attachments
                WHERE id_bom_cotizacion = $1 AND activo = TRUE
                ORDER BY fecha_subida DESC
                LIMIT 1
            """, cotizacion_id)
        return dict(row) if row else None

    async def actualizar_estatus_compra_items(
        self, conn, bom_item_ids: List[UUID], estatus_compra: str
    ) -> int:
        """Actualiza el espejo legacy; ejecución se muta aparte con CAS exacto."""
        result = await conn.execute("""
            UPDATE tb_bom_items
            SET estatus_compra = $1,
                lock_version = lock_version + 1,
                updated_at = NOW()
            WHERE id_item = ANY($2::uuid[])
        """, estatus_compra, bom_item_ids)
        return int(result.split()[-1]) if result else 0

    async def get_proveedores_buscar(self, conn, q: str) -> List[dict]:
        rows = await conn.fetch("""
            SELECT id_proveedor, rfc, razon_social, nombre_comercial
            FROM tb_proveedores
            WHERE activo = TRUE
              AND (nombre_comercial ILIKE $1 OR razon_social ILIKE $1 OR rfc ILIKE $1)
            ORDER BY nombre_comercial
            LIMIT 15
        """, f"%{q}%")
        return [dict(r) for r in rows]

    # ─── AUTORIZACIONES (Fase D) ────────────────────────────

    async def crear_autorizacion(
        self, conn, cotizacion_id: UUID, bom_id: UUID, proyecto_id: UUID,
        monto_total, moneda: str, tipo_cambio_snapshot, creado_por: UUID
    ) -> dict:
        row = await conn.fetchrow("""
            INSERT INTO tb_bom_autorizaciones
                (cotizacion_id, bom_id, proyecto_id, monto_total, moneda,
                 tipo_cambio_snapshot, creado_por)
            VALUES ($1,$2,$3,$4,$5,$6,$7)
            RETURNING *
        """, cotizacion_id, bom_id, proyecto_id, monto_total, moneda,
            tipo_cambio_snapshot, creado_por)
        return dict(row)

    async def get_autorizacion_by_id(self, conn, autorizacion_id: UUID) -> Optional[dict]:
        row = await conn.fetchrow("""
            SELECT a.*,
                   c.nombre_proveedor,
                   u1.nombre AS aprobador_obra_nombre,
                   u2.nombre AS aprobador_direccion_nombre,
                   u3.nombre AS aprobador_finanzas_nombre,
                   u4.nombre AS rechazado_por_nombre
            FROM tb_bom_autorizaciones a
            JOIN tb_bom_cotizaciones c ON c.id = a.cotizacion_id
            LEFT JOIN tb_usuarios u1 ON u1.id_usuario = a.aprobador_obra_id
            LEFT JOIN tb_usuarios u2 ON u2.id_usuario = a.aprobador_direccion_id
            LEFT JOIN tb_usuarios u3 ON u3.id_usuario = a.aprobador_finanzas_id
            LEFT JOIN tb_usuarios u4 ON u4.id_usuario = a.rechazado_por
            WHERE a.id = $1
        """, autorizacion_id)
        return dict(row) if row else None

    async def get_autorizacion_for_update(
        self, conn, autorizacion_id: UUID,
    ) -> Optional[dict]:
        row = await conn.fetchrow("""
            SELECT a.*, c.nombre_proveedor
            FROM tb_bom_autorizaciones a
            JOIN tb_bom_cotizaciones c ON c.id = a.cotizacion_id
            WHERE a.id = $1
            FOR UPDATE OF a
        """, autorizacion_id)
        return dict(row) if row else None

    async def get_autorizacion_by_cotizacion(self, conn, cotizacion_id: UUID) -> Optional[dict]:
        row = await conn.fetchrow("""
            SELECT a.*,
                   c.nombre_proveedor,
                   u1.nombre AS aprobador_obra_nombre,
                   u2.nombre AS aprobador_direccion_nombre,
                   u3.nombre AS aprobador_finanzas_nombre,
                   u4.nombre AS rechazado_por_nombre
            FROM tb_bom_autorizaciones a
            JOIN tb_bom_cotizaciones c ON c.id = a.cotizacion_id
            LEFT JOIN tb_usuarios u1 ON u1.id_usuario = a.aprobador_obra_id
            LEFT JOIN tb_usuarios u2 ON u2.id_usuario = a.aprobador_direccion_id
            LEFT JOIN tb_usuarios u3 ON u3.id_usuario = a.aprobador_finanzas_id
            LEFT JOIN tb_usuarios u4 ON u4.id_usuario = a.rechazado_por
            WHERE a.cotizacion_id = $1
        """, cotizacion_id)
        return dict(row) if row else None

    async def get_autorizaciones_by_bom(self, conn, bom_id: UUID) -> List[dict]:
        rows = await conn.fetch("""
            SELECT a.*,
                   c.nombre_proveedor,
                   u1.nombre AS aprobador_obra_nombre,
                   u2.nombre AS aprobador_direccion_nombre,
                   u3.nombre AS aprobador_finanzas_nombre,
                   u4.nombre AS rechazado_por_nombre
            FROM tb_bom_autorizaciones a
            JOIN tb_bom_cotizaciones c ON c.id = a.cotizacion_id
            LEFT JOIN tb_usuarios u1 ON u1.id_usuario = a.aprobador_obra_id
            LEFT JOIN tb_usuarios u2 ON u2.id_usuario = a.aprobador_direccion_id
            LEFT JOIN tb_usuarios u3 ON u3.id_usuario = a.aprobador_finanzas_id
            LEFT JOIN tb_usuarios u4 ON u4.id_usuario = a.rechazado_por
            WHERE a.bom_id = $1
            ORDER BY a.creado_en DESC
        """, bom_id)
        return [dict(r) for r in rows]

    async def update_autorizacion_paso_obra(
        self, conn, autorizacion_id: UUID, user_id: UUID, nota: Optional[str],
        lock_version_esperado: int,
    ) -> Optional[dict]:
        row = await conn.fetchrow("""
            UPDATE tb_bom_autorizaciones
            SET estatus = 'AUTORIZADO_OBRA',
                aprobador_obra_id = $2,
                fecha_aprobacion_obra = NOW(),
                nota_obra = $3,
                lock_version = lock_version + 1
            WHERE id = $1 AND estatus = 'PENDIENTE' AND lock_version = $4
            RETURNING *
        """, autorizacion_id, user_id, nota, lock_version_esperado)
        return dict(row) if row else None

    async def update_autorizacion_paso_direccion(
        self, conn, autorizacion_id: UUID, user_id: UUID, nota: Optional[str],
        lock_version_esperado: int,
    ) -> Optional[dict]:
        row = await conn.fetchrow("""
            UPDATE tb_bom_autorizaciones
            SET estatus = 'AUTORIZADO_DIRECCION',
                aprobador_direccion_id = $2,
                fecha_aprobacion_direccion = NOW(),
                nota_direccion = $3,
                lock_version = lock_version + 1
            WHERE id = $1 AND estatus = 'AUTORIZADO_OBRA' AND lock_version = $4
            RETURNING *
        """, autorizacion_id, user_id, nota, lock_version_esperado)
        return dict(row) if row else None

    async def update_autorizacion_paso_finanzas(
        self, conn, autorizacion_id: UUID, user_id: UUID, nota: Optional[str],
        lock_version_esperado: int,
    ) -> Optional[dict]:
        row = await conn.fetchrow("""
            UPDATE tb_bom_autorizaciones
            SET estatus = 'AUTORIZADO_FINANZAS',
                aprobador_finanzas_id = $2,
                fecha_aprobacion_finanzas = NOW(),
                nota_finanzas = $3,
                lock_version = lock_version + 1
            WHERE id = $1 AND estatus = 'AUTORIZADO_DIRECCION' AND lock_version = $4
            RETURNING *
        """, autorizacion_id, user_id, nota, lock_version_esperado)
        return dict(row) if row else None

    async def rechazar_autorizacion_db(
        self, conn, autorizacion_id: UUID, user_id: UUID,
        motivo: str, paso: str, estatus_esperado: str,
        lock_version_esperado: int,
    ) -> Optional[dict]:
        row = await conn.fetchrow("""
            UPDATE tb_bom_autorizaciones
            SET estatus = 'RECHAZADO',
                rechazado_en_paso = $3,
                rechazado_por = $2,
                motivo_rechazo = $4,
                fecha_rechazo = NOW(),
                lock_version = lock_version + 1
            WHERE id = $1 AND estatus = $5 AND lock_version = $6
            RETURNING *
        """, autorizacion_id, user_id, paso, motivo, estatus_esperado,
             lock_version_esperado)
        return dict(row) if row else None

    async def reabrir_autorizacion_db(
        self, conn, autorizacion_id: UUID, monto_total, moneda: str,
        tipo_cambio_snapshot, creado_por: UUID, lock_version_esperado: int,
    ) -> Optional[dict]:
        """Reabre una autorización RECHAZADA a PENDIENTE al re-seleccionar la cotización (nuevo ciclo)."""
        row = await conn.fetchrow("""
            UPDATE tb_bom_autorizaciones
            SET estatus = 'PENDIENTE',
                monto_total = $2,
                moneda = $3,
                tipo_cambio_snapshot = $4,
                creado_por = $5,
                creado_en = NOW(),
                aprobador_obra_id = NULL,
                fecha_aprobacion_obra = NULL,
                nota_obra = NULL,
                aprobador_direccion_id = NULL,
                fecha_aprobacion_direccion = NULL,
                nota_direccion = NULL,
                aprobador_finanzas_id = NULL,
                fecha_aprobacion_finanzas = NULL,
                nota_finanzas = NULL,
                rechazado_en_paso = NULL,
                rechazado_por = NULL,
                motivo_rechazo = NULL,
                fecha_rechazo = NULL,
                lock_version = lock_version + 1
            WHERE id = $1 AND estatus = 'RECHAZADO' AND lock_version = $6
            RETURNING *
        """, autorizacion_id, monto_total, moneda, tipo_cambio_snapshot, creado_por,
             lock_version_esperado)
        return dict(row) if row else None

    # ─── APROBACIONES DE COTIZACION (post-BOM) ──────────────

    async def crear_cotizacion_aprobacion(
        self, conn, cotizacion_id: UUID, bom_id: UUID, proyecto_id: UUID,
        solicitado_por: UUID, comentarios_solicitud: Optional[str] = None,
        cotizacion_reemplazada_id: Optional[UUID] = None,
        aprobacion_reemplazada_id: Optional[UUID] = None,
    ) -> dict:
        row = await conn.fetchrow("""
            INSERT INTO tb_bom_cotizacion_aprobaciones
                (cotizacion_id, bom_id, proyecto_id, solicitado_por, comentarios_solicitud,
                 cotizacion_reemplazada_id, aprobacion_reemplazada_id)
            VALUES ($1,$2,$3,$4,$5,$6,$7)
            RETURNING *
        """, cotizacion_id, bom_id, proyecto_id, solicitado_por, comentarios_solicitud,
            cotizacion_reemplazada_id, aprobacion_reemplazada_id)
        return dict(row)

    async def marcar_cotizacion_aprobacion_reemplazada(
        self, conn, aprobacion_id: UUID, nuevo_estatus: str, motivo_reemplazo: str,
        lock_version_esperado: int,
    ) -> Optional[dict]:
        """Cierra una aprobacion APROBADA como REEMPLAZADA o CANCELADA_PROVEEDOR (## 7.4).

        No toca tb_bom_cotizaciones.estatus: su CHECK no admite un valor de
        reemplazo (BORRADOR|RECIBIDA|SELECCIONADA|RECHAZADA) y la cotizacion
        original se conserva intacta como evidencia historica.
        """
        row = await conn.fetchrow("""
            UPDATE tb_bom_cotizacion_aprobaciones
            SET estatus = $2,
                motivo_reemplazo = $3,
                updated_at = NOW(),
                lock_version = lock_version + 1
            WHERE id = $1 AND estatus = 'APROBADA' AND lock_version = $4
            RETURNING *
        """, aprobacion_id, nuevo_estatus, motivo_reemplazo, lock_version_esperado)
        return dict(row) if row else None

    async def get_cotizacion_aprobaciones_reemplazables(
        self, conn, bom_id: UUID,
    ) -> List[dict]:
        """Aprobaciones REEMPLAZADA de este BOM sin una cotizacion sucesora aun ligada.

        Alimenta el selector opcional de "esta cotizacion reemplaza a" en el
        formulario de solicitar aprobacion de Direccion.
        """
        rows = await conn.fetch("""
            SELECT ap.id, ap.cotizacion_id, ap.motivo_reemplazo, ap.updated_at,
                   c.nombre_proveedor
            FROM tb_bom_cotizacion_aprobaciones ap
            JOIN tb_bom_cotizaciones c ON c.id = ap.cotizacion_id
            WHERE ap.bom_id = $1
              AND ap.estatus = 'REEMPLAZADA'
              AND NOT EXISTS (
                  SELECT 1 FROM tb_bom_cotizacion_aprobaciones sucesora
                  WHERE sucesora.aprobacion_reemplazada_id = ap.id
              )
            ORDER BY ap.updated_at DESC
        """, bom_id)
        return [dict(r) for r in rows]

    async def get_cotizacion_aprobacion_activa(self, conn, cotizacion_id: UUID) -> Optional[dict]:
        """Aprobacion activa (pendiente o aprobada) de una cotizacion; maximo una por indice unico parcial."""
        row = await conn.fetchrow("""
            SELECT ap.*
            FROM tb_bom_cotizacion_aprobaciones ap
            WHERE ap.cotizacion_id = $1
              AND ap.estatus IN ('PENDIENTE_DIRECCION', 'APROBADA')
        """, cotizacion_id)
        return dict(row) if row else None

    async def get_cotizacion_aprobacion_for_update(
        self, conn, aprobacion_id: UUID,
    ) -> Optional[dict]:
        row = await conn.fetchrow("""
            SELECT * FROM tb_bom_cotizacion_aprobaciones
            WHERE id = $1
            FOR UPDATE
        """, aprobacion_id)
        return dict(row) if row else None

    async def aprobar_cotizacion_aprobacion_db(
        self, conn, aprobacion_id: UUID, user_id: UUID,
        comentarios: Optional[str], lock_version_esperado: int,
    ) -> Optional[dict]:
        row = await conn.fetchrow("""
            UPDATE tb_bom_cotizacion_aprobaciones
            SET estatus = 'APROBADA',
                aprobado_por = $2,
                aprobado_en = NOW(),
                comentarios_direccion = $3,
                updated_at = NOW(),
                lock_version = lock_version + 1
            WHERE id = $1 AND estatus = 'PENDIENTE_DIRECCION'
              AND lock_version = $4
            RETURNING *
        """, aprobacion_id, user_id, comentarios, lock_version_esperado)
        return dict(row) if row else None

    async def rechazar_cotizacion_aprobacion_db(
        self, conn, aprobacion_id: UUID, user_id: UUID, motivo: str,
        lock_version_esperado: int,
    ) -> Optional[dict]:
        row = await conn.fetchrow("""
            UPDATE tb_bom_cotizacion_aprobaciones
            SET estatus = 'RECHAZADA',
                rechazado_por = $2,
                rechazado_en = NOW(),
                motivo_rechazo = $3,
                updated_at = NOW(),
                lock_version = lock_version + 1
            WHERE id = $1 AND estatus = 'PENDIENTE_DIRECCION'
              AND lock_version = $4
            RETURNING *
        """, aprobacion_id, user_id, motivo, lock_version_esperado)
        return dict(row) if row else None

    # ─── TRAZABILIDAD BOM ↔ COMPRAS ─────────────────────────

    async def get_items_by_autorizacion(self, conn, autorizacion_id: UUID) -> List[dict]:
        """Obtiene los items BOM asociados a una autorizacion via cotizacion.

        Incluye la clave SAT del material interno (para match exacto por clave) y los
        montos de la linea de cotizacion (ancla declarada por Compras al cotizar), que
        alimentan el matcher por niveles de `match_conceptos_a_items`.
        """
        rows = await conn.fetch("""
            SELECT bi.*,
                   c.nombre AS categoria_nombre,
                   (bi.cantidad * bi.precio_unitario) AS importe,
                   m.clave_prod_serv AS material_clave,
                   ci.precio_unitario AS coti_precio,
                   ci.cantidad AS coti_cantidad,
                   ci.subtotal_linea AS coti_subtotal,
                   grupos.grupo_ids,
                   grupos.grupo_labels
            FROM tb_bom_items bi
            JOIN tb_bom_cotizacion_items ci ON ci.bom_item_id = bi.id_item
            JOIN tb_bom_autorizaciones a ON a.cotizacion_id = ci.cotizacion_id
            LEFT JOIN tb_cat_categorias_compra c ON c.id = bi.id_categoria
            LEFT JOIN tb_cat_materiales m ON m.id = bi.id_material_ref
            LEFT JOIN LATERAL (
                SELECT ARRAY_AGG(catalogo.id ORDER BY catalogo.orden, catalogo.id) AS grupo_ids,
                       ARRAY_AGG(
                           catalogo.codigo || ' - ' || catalogo.nombre
                           ORDER BY catalogo.orden, catalogo.id
                       ) AS grupo_labels
                FROM (
                    SELECT relacion.id_grupo
                    FROM tb_bom_item_grupos_operativos relacion
                    WHERE relacion.id_item = bi.id_item
                    UNION ALL
                    SELECT relacion.id_grupo
                    FROM tb_bom_item_grupos relacion
                    WHERE relacion.id_item = bi.id_item
                      AND NOT EXISTS (
                          SELECT 1 FROM tb_bom_item_grupos_operativos operativa
                          WHERE operativa.id_item = bi.id_item
                      )
                ) relacion
                JOIN tb_cat_grupos_bom catalogo ON catalogo.id = relacion.id_grupo
                WHERE catalogo.activo = TRUE
            ) grupos ON TRUE
            WHERE a.id = $1 AND bi.activo = TRUE
            ORDER BY bi.orden ASC
        """, autorizacion_id)
        return [dict(r) for r in rows]

    async def get_memoria_match_proveedor(
        self, conn, id_proveedor: UUID, claves: List[str]
    ) -> dict:
        """Memoria proveedor-producto derivada del historial (sin tabla dedicada).

        Para cada `clave_prod_serv` de la lista, devuelve el `id_material_ref` al que ese
        proveedor ya se ha ligado con mas frecuencia. Alimenta el nivel MEMORIA de
        `match_conceptos_a_items`.

        Gating (B3c): la memoria SOLO aprende de matches confiables -> confirmados por una
        persona (`match_origen = 'HUMANO'`) o de alta confianza (`match_confianza = 'ALTA'`,
        es decir clave SAT exacta / memoria previa / ancla de cotizacion). Las auto-asignaciones
        debiles (`BAJA`, fallback de texto) NO se aprenden, para no propagar un match erroneo.
        Ante empate de frecuencia, el `id_material_ref` respaldado por una confirmacion humana
        gana sobre el meramente sugerido.

        Returns: {clave_prod_serv: UUID(id_material_ref)}
        """
        if not claves:
            return {}
        rows = await conn.fetch("""
            SELECT DISTINCT ON (mh.clave_prod_serv)
                   mh.clave_prod_serv, bi.id_material_ref
            FROM tb_materiales_historial mh
            JOIN tb_bom_items bi ON bi.id_item = mh.id_bom_item
            WHERE mh.id_proveedor = $1 AND mh.clave_prod_serv = ANY($2)
              AND bi.id_material_ref IS NOT NULL
              AND (mh.match_origen = 'HUMANO' OR mh.match_confianza = 'ALTA')
            GROUP BY mh.clave_prod_serv, bi.id_material_ref
            ORDER BY mh.clave_prod_serv,
                     max(CASE WHEN mh.match_origen = 'HUMANO' THEN 1 ELSE 0 END) DESC,
                     count(*) DESC
        """, id_proveedor, claves)
        return {r['clave_prod_serv']: r['id_material_ref'] for r in rows}

    async def get_conceptos_conciliacion(self, conn, autorizacion_id: UUID) -> List[dict]:
        """Conceptos CFDI de las facturas de una autorizacion, con su match actual.

        Columna izquierda de la UI de conciliacion. Puente:
        tb_materiales_historial.id_comprobante -> tb_comprobantes_pago -> tb_bom_pagos
        -> autorizacion. Orden: sin asignar primero, luego BAJA, luego ALTA/HUMANO,
        para que lo que requiere atencion quede arriba.
        """
        rows = await conn.fetch("""
            SELECT mh.id AS historial_id,
                   mh.descripcion_proveedor, mh.clave_prod_serv, mh.cantidad,
                   mh.precio_unitario, mh.importe, mh.tipo_cambio_xml,
                   mh.id_bom_item, mh.match_confianza, mh.match_origen,
                   mh.id_bom_item_sugerido, mh.sugerencia_confianza, mh.sugerencia_origen,
                   mh.grupo_ids_snapshot,
                   mh.lock_version AS concepto_lock_version,
                   asignacion.id_asignacion AS concepto_asignacion_id,
                   asignacion.lock_version AS concepto_asignacion_lock_version,
                   asignacion.asignacion_grupo_completa,
                   grupo_asignado.id_grupo AS grupo_asignado_id,
                   cp.uuid_factura
            FROM tb_materiales_historial mh
            JOIN tb_comprobantes_pago cp ON cp.id_comprobante = mh.id_comprobante
            JOIN tb_bom_pagos bp ON bp.id = cp.id_bom_pago
            LEFT JOIN tb_bom_concepto_asignaciones asignacion
              ON asignacion.id_material = mh.id
             AND asignacion.id_bom_item = mh.id_bom_item
            LEFT JOIN LATERAL (
                SELECT MIN(hecho.id_grupo) AS id_grupo
                FROM tb_bom_hecho_grupo_asignaciones hecho
                WHERE hecho.id_asignacion_concepto = asignacion.id_asignacion
                HAVING COUNT(*) = 1
            ) grupo_asignado ON TRUE
            WHERE bp.autorizacion_id = $1
            ORDER BY
                CASE WHEN mh.id_bom_item IS NULL AND mh.id_bom_item_sugerido IS NULL THEN 0
                     WHEN mh.id_bom_item IS NULL AND mh.id_bom_item_sugerido IS NOT NULL THEN 1
                     WHEN mh.match_confianza = 'BAJA' THEN 1
                     ELSE 2 END,
                mh.descripcion_proveedor
        """, autorizacion_id)
        return [dict(r) for r in rows]

    async def confirmar_match_concepto(
        self, conn, historial_id: UUID, id_bom_item: Optional[UUID],
        id_bom_item_anterior: Optional[UUID],
        lock_version_esperado: int,
        id_grupo: Optional[int] = None,
    ) -> Optional[dict]:
        """Persiste (o limpia) el match concepto->item confirmado por un humano.

        id_bom_item set   -> match_confianza='ALTA', match_origen='HUMANO'.
        id_bom_item None  -> desasigna: id_bom_item, match_confianza, match_origen = NULL.
        Devuelve {historial_id, id_bom_item} o None si el concepto no existe.
        """
        row = await conn.fetchrow("""
            UPDATE tb_materiales_historial
            SET id_bom_item = $2,
                match_confianza = CASE WHEN $2::uuid IS NULL THEN NULL ELSE 'ALTA' END,
                match_origen    = CASE WHEN $2::uuid IS NULL THEN NULL ELSE 'HUMANO' END,
                id_bom_item_sugerido = NULL,
                sugerencia_confianza = NULL,
                sugerencia_origen = NULL,
                grupo_ids_snapshot = CASE
                    WHEN $2::uuid IS NULL THEN ARRAY[]::integer[]
                    ELSE COALESCE(
                        (SELECT ARRAY_AGG(g.id_grupo ORDER BY g.id_grupo)
                         FROM tb_bom_item_grupos_operativos g
                         WHERE g.id_item = $2),
                        (SELECT ARRAY_AGG(g.id_grupo ORDER BY g.id_grupo)
                         FROM tb_bom_item_grupos g
                         WHERE g.id_item = $2),
                        ARRAY[]::integer[]
                    )
                END,
                lock_version = lock_version + 1
            WHERE id = $1
              AND id_bom_item IS NOT DISTINCT FROM $3
              AND lock_version = $4
            RETURNING id AS historial_id, id_bom_item, grupo_ids_snapshot,
                      lock_version
        """, historial_id, id_bom_item, id_bom_item_anterior, lock_version_esperado)
        if not row:
            return None

        await conn.execute("""
            DELETE FROM tb_bom_hecho_grupo_asignaciones grupo
            USING tb_bom_concepto_asignaciones asignacion
            WHERE grupo.id_asignacion_concepto = asignacion.id_asignacion
              AND asignacion.id_material = $1
        """, historial_id)
        await conn.execute("""
            DELETE FROM tb_bom_concepto_asignaciones
            WHERE id_material = $1
        """, historial_id)
        if id_bom_item is None:
            return dict(row)

        asignacion = await conn.fetchrow("""
            INSERT INTO tb_bom_concepto_asignaciones (
                id_material, id_concepto_cfdi, id_paquete, id_bom, id_linea_bom,
                id_bom_item, importe_asignado, moneda, tipo_cfdi
            )
            SELECT material.id, material.id_concepto_cfdi, item.id_paquete,
                   item.id_bom, item.id_linea_bom, item.id_item,
                   CASE WHEN factura.tipo_cfdi = 'NOTA_CREDITO'
                        THEN -ABS(material.importe) ELSE ABS(material.importe) END,
                   factura.moneda, factura.tipo_cfdi
            FROM tb_materiales_historial material
            JOIN tb_bom_items item ON item.id_item = $2
            LEFT JOIN LATERAL (
                SELECT
                    CASE WHEN BOOL_OR(cf.tipo = 'NOTA_CREDITO')
                         THEN 'NOTA_CREDITO' ELSE 'NORMAL' END AS tipo_cfdi,
                    MAX(cf.moneda) AS moneda
                FROM tb_comprobante_facturas cf
                WHERE cf.uuid_factura = material.uuid_factura::text
            ) factura ON TRUE
            WHERE material.id = $1
            RETURNING *
        """, historial_id, id_bom_item)
        if asignacion:
            if id_grupo is not None:
                grupo = await conn.fetchrow("""
                    SELECT catalogo.id, catalogo.codigo, catalogo.nombre
                    FROM tb_cat_grupos_bom catalogo
                    WHERE catalogo.id = $1 AND catalogo.activo = TRUE
                """, id_grupo)
                if grupo:
                    await conn.execute("""
                        INSERT INTO tb_bom_hecho_grupo_asignaciones (
                            id_asignacion_concepto, id_grupo, grupo_codigo_snapshot,
                            grupo_nombre_snapshot, importe_asignado, moneda
                        ) VALUES ($1, $2, $3, $4, $5, $6)
                    """, asignacion["id_asignacion"], grupo["id"], grupo["codigo"],
                         grupo["nombre"], asignacion["importe_asignado"], asignacion["moneda"])
            else:
                await conn.execute("""
                    INSERT INTO tb_bom_hecho_grupo_asignaciones (
                        id_asignacion_concepto, id_grupo, grupo_codigo_snapshot,
                        grupo_nombre_snapshot, importe_asignado, moneda
                    )
                    SELECT $1, distribucion.id_grupo,
                           distribucion.grupo_codigo_snapshot,
                           distribucion.grupo_nombre_snapshot,
                           $2 * distribucion.porcentaje,
                           $3
                    FROM tb_bom_item_grupo_asignaciones distribucion
                    WHERE distribucion.id_bom_item = $4
                      AND ABS((
                          SELECT SUM(otra.porcentaje)
                          FROM tb_bom_item_grupo_asignaciones otra
                          WHERE otra.id_bom_item = $4
                      ) - 1) <= 0.000001
                """, asignacion["id_asignacion"], asignacion["importe_asignado"],
                     asignacion["moneda"], id_bom_item)
                tiene_distribucion = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT 1 FROM tb_bom_hecho_grupo_asignaciones
                        WHERE id_asignacion_concepto = $1
                    )
                """, asignacion["id_asignacion"])
                if not tiene_distribucion:
                    grupo = await conn.fetchrow("""
                        WITH grupos AS (
                            SELECT relacion.id_grupo
                            FROM tb_bom_item_grupos_operativos relacion
                            WHERE relacion.id_item = $1
                            UNION ALL
                            SELECT relacion.id_grupo
                            FROM tb_bom_item_grupos relacion
                            WHERE relacion.id_item = $1
                              AND NOT EXISTS (
                                  SELECT 1 FROM tb_bom_item_grupos_operativos operativa
                                  WHERE operativa.id_item = $1
                              )
                        )
                        SELECT catalogo.id, catalogo.codigo, catalogo.nombre
                        FROM grupos
                        JOIN tb_cat_grupos_bom catalogo
                          ON catalogo.id = grupos.id_grupo
                        WHERE catalogo.activo = TRUE
                          AND (SELECT COUNT(*) FROM grupos) = 1
                    """, id_bom_item)
                    if grupo:
                        await conn.execute("""
                            INSERT INTO tb_bom_hecho_grupo_asignaciones (
                                id_asignacion_concepto, id_grupo,
                                grupo_codigo_snapshot, grupo_nombre_snapshot,
                                importe_asignado, moneda
                            ) VALUES ($1, $2, $3, $4, $5, $6)
                        """, asignacion["id_asignacion"], grupo["id"], grupo["codigo"],
                             grupo["nombre"], asignacion["importe_asignado"], asignacion["moneda"])
            completa = await conn.fetchval("""
                SELECT COALESCE(
                    ABS(SUM(importe_asignado) - $2) <= 0.000001,
                    FALSE
                )
                FROM tb_bom_hecho_grupo_asignaciones
                WHERE id_asignacion_concepto = $1
            """, asignacion["id_asignacion"], asignacion["importe_asignado"])
            if completa:
                await conn.execute("""
                    UPDATE tb_bom_concepto_asignaciones
                    SET asignacion_grupo_completa = TRUE, updated_at = NOW()
                    WHERE id_asignacion = $1
                """, asignacion["id_asignacion"])
        return dict(row)

    async def get_autorizacion_by_bom_pago(self, conn, id_bom_pago: UUID) -> Optional[dict]:
        """Obtiene la autorizacion a partir del id_bom_pago."""
        row = await conn.fetchrow("""
            SELECT a.*, c.nombre_proveedor
            FROM tb_bom_autorizaciones a
            JOIN tb_bom_pagos bp ON bp.autorizacion_id = a.id
            JOIN tb_bom_cotizaciones c ON c.id = a.cotizacion_id
            WHERE bp.id = $1
        """, id_bom_pago)
        return dict(row) if row else None

    # ─── RESUMEN DE COMPRA (Presupuesto vs Facturado vs Pagado) ───

    async def get_resumen_compra(self, conn, id_bom: UUID) -> List[dict]:
        """Reconcilia costos por grupo sin repartir ni convertir datos desconocidos."""
        rows = await conn.fetch("""
            WITH items AS (
                SELECT item.id_item, item.id_categoria,
                       COALESCE(categoria.nombre, 'Sin categoria') AS categoria_nombre,
                       item.cantidad, item.precio_unitario,
                       item.moneda AS moneda_base,
                       COALESCE(adenda.tipo_cambio_aprobacion,
                                bom.tipo_cambio_aprobacion) AS tipo_cambio_base,
                       ejecucion.precio_real, ejecucion.moneda_real,
                       COALESCE(item.tipo_origen_item, 'BASE') AS tipo_origen_item,
                       COALESCE(ejecucion.estatus_ejecucion, 'PENDIENTE')
                           AS estatus_ejecucion
                FROM tb_bom_items item
                JOIN tb_bom bom ON bom.id_bom = item.id_bom
                LEFT JOIN tb_cat_categorias_compra categoria
                  ON categoria.id = item.id_categoria
                LEFT JOIN tb_bom_item_ejecucion ejecucion
                  ON ejecucion.id_item = item.id_item
                LEFT JOIN tb_bom_adendas adenda
                  ON adenda.id_adenda = item.creado_en_adenda
                 AND adenda.estatus = 'APROBADA'
                WHERE item.id_bom = $1 AND item.activo = TRUE
            ),
            distribuciones_validas AS (
                SELECT asignacion.id_bom_item
                FROM tb_bom_item_grupo_asignaciones asignacion
                JOIN items item ON item.id_item = asignacion.id_bom_item
                GROUP BY asignacion.id_bom_item
                HAVING ABS(SUM(asignacion.porcentaje) - 1) <= 0.000001
            ),
            grupos_actuales AS (
                SELECT relacion.id_item, relacion.id_grupo
                FROM tb_bom_item_grupos_operativos relacion
                JOIN items item ON item.id_item = relacion.id_item
                UNION ALL
                SELECT relacion.id_item, relacion.id_grupo
                FROM tb_bom_item_grupos relacion
                JOIN items item ON item.id_item = relacion.id_item
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM tb_bom_item_grupos_operativos operativa
                    WHERE operativa.id_item = relacion.id_item
                )
            ),
            grupos_unicos AS (
                SELECT id_item, MIN(id_grupo) AS id_grupo
                FROM grupos_actuales
                GROUP BY id_item
                HAVING COUNT(*) = 1
            ),
            item_grupos AS (
                SELECT item.*, asignacion.grupo_codigo_snapshot AS grupo_codigo,
                       asignacion.grupo_nombre_snapshot AS grupo_nombre,
                       COALESCE(catalogo.orden, 999) AS grupo_orden,
                       asignacion.porcentaje AS peso_grupo,
                       FALSE AS grupo_pendiente
                FROM items item
                JOIN distribuciones_validas valida
                  ON valida.id_bom_item = item.id_item
                JOIN tb_bom_item_grupo_asignaciones asignacion
                  ON asignacion.id_bom_item = item.id_item
                LEFT JOIN tb_cat_grupos_bom catalogo
                  ON catalogo.id = asignacion.id_grupo

                UNION ALL

                SELECT item.*, catalogo.codigo, catalogo.nombre,
                       catalogo.orden, 1::numeric, FALSE
                FROM items item
                JOIN grupos_unicos unico ON unico.id_item = item.id_item
                JOIN tb_cat_grupos_bom catalogo ON catalogo.id = unico.id_grupo
                WHERE NOT EXISTS (
                    SELECT 1 FROM distribuciones_validas valida
                    WHERE valida.id_bom_item = item.id_item
                )

                UNION ALL

                SELECT item.*, 'PENDIENTE_DISTRIBUCION',
                       'Pendiente de distribucion', 998, 1::numeric, TRUE
                FROM items item
                WHERE NOT EXISTS (
                    SELECT 1 FROM distribuciones_validas valida
                    WHERE valida.id_bom_item = item.id_item
                )
                  AND NOT EXISTS (
                    SELECT 1 FROM grupos_unicos unico
                    WHERE unico.id_item = item.id_item
                )
            ),
            costos AS (
                SELECT grupo_codigo, grupo_nombre, grupo_orden,
                       id_categoria AS categoria_id, categoria_nombre,
                       SUM(CASE
                           WHEN tipo_origen_item = 'BASE'
                            AND cantidad IS NOT NULL AND precio_unitario IS NOT NULL
                            AND moneda_base = 'MXN'
                               THEN cantidad * precio_unitario * peso_grupo
                           WHEN tipo_origen_item = 'BASE'
                            AND cantidad IS NOT NULL AND precio_unitario IS NOT NULL
                            AND moneda_base = 'USD' AND tipo_cambio_base IS NOT NULL
                               THEN cantidad * precio_unitario * tipo_cambio_base
                                    * peso_grupo
                           ELSE 0
                       END) AS presupuesto,
                       COUNT(*) FILTER (WHERE tipo_origen_item = 'BASE' AND (
                           cantidad IS NULL OR precio_unitario IS NULL
                           OR moneda_base IS NULL OR moneda_base NOT IN ('MXN', 'USD')
                           OR (moneda_base = 'USD' AND tipo_cambio_base IS NULL)
                       )) AS presupuesto_pendiente,
                       SUM(CASE WHEN precio_real IS NOT NULL AND moneda_real = 'MXN'
                           THEN cantidad * precio_real * peso_grupo ELSE 0 END) AS real,
                       COUNT(*) FILTER (WHERE estatus_ejecucion NOT IN (
                           'PENDIENTE', 'SIN_COTIZAR', 'NO_ADQUIRIDO',
                           'REEMPLAZADO', 'CERRADO'
                       ) AND (cantidad IS NULL OR precio_real IS NULL
                              OR moneda_real IS NULL OR moneda_real <> 'MXN'))
                           AS real_pendiente,
                       SUM(CASE WHEN tipo_origen_item = 'BASE'
                            AND precio_real IS NOT NULL AND moneda_real = 'MXN'
                           THEN cantidad * precio_real * peso_grupo ELSE 0 END)
                           AS real_base,
                       COUNT(*) FILTER (WHERE tipo_origen_item = 'BASE'
                         AND estatus_ejecucion NOT IN (
                             'PENDIENTE', 'SIN_COTIZAR', 'NO_ADQUIRIDO',
                             'REEMPLAZADO', 'CERRADO'
                         ) AND (cantidad IS NULL OR precio_real IS NULL
                                OR moneda_real IS NULL OR moneda_real <> 'MXN'))
                           AS real_base_pendiente,
                       SUM(CASE WHEN tipo_origen_item = 'REEMPLAZO'
                            AND precio_real IS NOT NULL AND moneda_real = 'MXN'
                           THEN cantidad * precio_real * peso_grupo ELSE 0 END)
                           AS reemplazos,
                       COUNT(*) FILTER (WHERE tipo_origen_item = 'REEMPLAZO'
                         AND estatus_ejecucion NOT IN ('PENDIENTE', 'SIN_COTIZAR')
                         AND (cantidad IS NULL OR precio_real IS NULL
                              OR moneda_real IS NULL OR moneda_real <> 'MXN'))
                           AS reemplazos_pendiente,
                       SUM(CASE WHEN tipo_origen_item = 'FUERA_SCOPE'
                            AND precio_real IS NOT NULL AND moneda_real = 'MXN'
                           THEN cantidad * precio_real * peso_grupo ELSE 0 END)
                           AS fuera_scope,
                       COUNT(*) FILTER (WHERE tipo_origen_item = 'FUERA_SCOPE'
                         AND estatus_ejecucion NOT IN ('PENDIENTE', 'SIN_COTIZAR')
                         AND (cantidad IS NULL OR precio_real IS NULL
                              OR moneda_real IS NULL OR moneda_real <> 'MXN'))
                           AS fuera_scope_pendiente,
                       SUM(CASE
                           WHEN tipo_origen_item = 'BASE'
                            AND estatus_ejecucion IN (
                                'NO_ADQUIRIDO', 'REEMPLAZADO', 'CERRADO'
                            ) AND cantidad IS NOT NULL AND precio_unitario IS NOT NULL
                            AND moneda_base = 'MXN'
                               THEN cantidad * precio_unitario * peso_grupo
                           WHEN tipo_origen_item = 'BASE'
                            AND estatus_ejecucion IN (
                                'NO_ADQUIRIDO', 'REEMPLAZADO', 'CERRADO'
                            ) AND cantidad IS NOT NULL AND precio_unitario IS NOT NULL
                            AND moneda_base = 'USD' AND tipo_cambio_base IS NOT NULL
                               THEN cantidad * precio_unitario * tipo_cambio_base
                                    * peso_grupo
                           ELSE 0
                       END) AS no_adquirido,
                       COUNT(*) FILTER (WHERE tipo_origen_item = 'BASE'
                         AND estatus_ejecucion IN (
                             'NO_ADQUIRIDO', 'REEMPLAZADO', 'CERRADO'
                         ) AND (cantidad IS NULL OR precio_unitario IS NULL
                                OR moneda_base IS NULL
                                OR moneda_base NOT IN ('MXN', 'USD')
                                OR (moneda_base = 'USD'
                                    AND tipo_cambio_base IS NULL)))
                           AS no_adquirido_pendiente,
                       COUNT(*) FILTER (WHERE grupo_pendiente) AS grupos_pendientes
                FROM item_grupos
                GROUP BY grupo_codigo, grupo_nombre, grupo_orden,
                         id_categoria, categoria_nombre
            ),
            facturas_filas AS (
                SELECT hecho.grupo_codigo_snapshot AS grupo_codigo,
                       hecho.grupo_nombre_snapshot AS grupo_nombre,
                       COALESCE(catalogo.orden, 999) AS grupo_orden,
                       item.id_categoria AS categoria_id,
                       COALESCE(categoria.nombre, 'Sin categoria') AS categoria_nombre,
                       hecho.importe_asignado, hecho.moneda,
                       material.tipo_cambio_xml, FALSE AS grupo_pendiente
                FROM tb_bom_concepto_asignaciones asignacion
                JOIN tb_bom_hecho_grupo_asignaciones hecho
                  ON hecho.id_asignacion_concepto = asignacion.id_asignacion
                JOIN tb_materiales_historial material
                  ON material.id = asignacion.id_material
                LEFT JOIN tb_bom_items item ON item.id_item = asignacion.id_bom_item
                LEFT JOIN tb_cat_categorias_compra categoria
                  ON categoria.id = item.id_categoria
                LEFT JOIN tb_cat_grupos_bom catalogo ON catalogo.id = hecho.id_grupo
                WHERE asignacion.id_bom = $1

                UNION ALL

                SELECT 'PENDIENTE_DISTRIBUCION', 'Pendiente de distribucion', 998,
                       item.id_categoria, COALESCE(categoria.nombre, 'Sin categoria'),
                       asignacion.importe_asignado
                           - COALESCE(SUM(hecho.importe_asignado), 0),
                       asignacion.moneda,
                       material.tipo_cambio_xml, TRUE
                FROM tb_bom_concepto_asignaciones asignacion
                JOIN tb_materiales_historial material
                  ON material.id = asignacion.id_material
                LEFT JOIN tb_bom_hecho_grupo_asignaciones hecho
                  ON hecho.id_asignacion_concepto = asignacion.id_asignacion
                LEFT JOIN tb_bom_items item ON item.id_item = asignacion.id_bom_item
                LEFT JOIN tb_cat_categorias_compra categoria
                  ON categoria.id = item.id_categoria
                WHERE asignacion.id_bom = $1
                  AND asignacion.asignacion_grupo_completa = FALSE
                GROUP BY asignacion.id_asignacion, asignacion.importe_asignado,
                         asignacion.moneda, material.tipo_cambio_xml,
                         item.id_categoria, categoria.nombre
                HAVING ABS(
                    asignacion.importe_asignado
                        - COALESCE(SUM(hecho.importe_asignado), 0)
                ) > 0.000001
            ),
            facturas AS (
                SELECT grupo_codigo, grupo_nombre, grupo_orden,
                       categoria_id, categoria_nombre,
                       SUM(CASE
                           WHEN moneda = 'MXN' THEN importe_asignado
                           WHEN moneda = 'USD' AND tipo_cambio_xml IS NOT NULL
                               THEN importe_asignado * tipo_cambio_xml
                           ELSE 0
                       END) AS importe,
                       COUNT(*) FILTER (WHERE moneda IS NULL
                         OR moneda NOT IN ('MXN', 'USD')
                         OR (moneda = 'USD' AND tipo_cambio_xml IS NULL)) AS pendientes,
                       COUNT(*) FILTER (WHERE grupo_pendiente) AS grupos_pendientes
                FROM facturas_filas
                GROUP BY grupo_codigo, grupo_nombre, grupo_orden,
                         categoria_id, categoria_nombre
            ),
            sugerencias_filas AS (
                SELECT grupos.grupo_codigo, grupos.grupo_nombre, grupos.grupo_orden,
                       grupos.id_categoria AS categoria_id,
                       grupos.categoria_nombre,
                       CASE WHEN factura.es_nota_credito
                            THEN -ABS(material.importe) ELSE ABS(material.importe) END
                           * grupos.peso_grupo AS importe_asignado,
                       factura.moneda, material.tipo_cambio_xml,
                       grupos.grupo_pendiente
                FROM tb_materiales_historial material
                JOIN item_grupos grupos
                  ON grupos.id_item = material.id_bom_item_sugerido
                LEFT JOIN LATERAL (
                    SELECT MAX(cf.moneda) AS moneda,
                           BOOL_OR(cf.tipo = 'NOTA_CREDITO') AS es_nota_credito
                    FROM tb_comprobante_facturas cf
                    WHERE cf.uuid_factura = material.uuid_factura::text
                ) factura ON TRUE
                WHERE material.id_bom_item IS NULL
            ),
            sugerencias AS (
                SELECT grupo_codigo, grupo_nombre, grupo_orden,
                       categoria_id, categoria_nombre,
                       SUM(CASE
                           WHEN moneda = 'MXN' THEN importe_asignado
                           WHEN moneda = 'USD' AND tipo_cambio_xml IS NOT NULL
                               THEN importe_asignado * tipo_cambio_xml
                           ELSE 0
                       END) AS importe,
                       COUNT(*) FILTER (WHERE moneda IS NULL
                         OR moneda NOT IN ('MXN', 'USD')
                         OR (moneda = 'USD' AND tipo_cambio_xml IS NULL)) AS pendientes,
                       COUNT(*) FILTER (WHERE grupo_pendiente) AS grupos_pendientes
                FROM sugerencias_filas
                GROUP BY grupo_codigo, grupo_nombre, grupo_orden,
                         categoria_id, categoria_nombre
            ),
            cotizacion_totales AS (
                SELECT autorizacion.id AS autorizacion_id,
                       CASE WHEN COUNT(*) FILTER (
                           WHERE linea.subtotal_linea IS NULL
                       ) > 0 OR COALESCE(SUM(linea.subtotal_linea), 0) = 0
                       THEN NULL ELSE SUM(linea.subtotal_linea) END AS subtotal
                FROM tb_bom_autorizaciones autorizacion
                JOIN tb_bom_cotizacion_items linea
                  ON linea.cotizacion_id = autorizacion.cotizacion_id
                WHERE autorizacion.bom_id = $1
                GROUP BY autorizacion.id
            ),
            pagos_autorizacion AS (
                SELECT pago.autorizacion_id,
                       SUM(CASE
                           WHEN pago.moneda = 'MXN' THEN pago.monto_pagado
                           WHEN pago.moneda = 'USD'
                            AND pago.tipo_cambio_usado IS NOT NULL
                               THEN pago.monto_pagado * pago.tipo_cambio_usado
                           ELSE 0
                       END) AS importe,
                       COUNT(*) FILTER (WHERE pago.moneda IS NULL
                         OR pago.moneda NOT IN ('MXN', 'USD')
                         OR (pago.moneda = 'USD'
                             AND pago.tipo_cambio_usado IS NULL)) AS pendientes
                FROM tb_bom_pagos pago
                JOIN tb_bom_autorizaciones autorizacion
                  ON autorizacion.id = pago.autorizacion_id
                WHERE autorizacion.bom_id = $1
                GROUP BY pago.autorizacion_id
            ),
            lineas_pago AS (
                SELECT linea.cotizacion_id, linea.subtotal_linea,
                       item.id_categoria AS categoria_id,
                       COALESCE(categoria.nombre, 'Sin categoria')
                           AS categoria_nombre,
                       snapshot.codigo AS grupo_codigo,
                       snapshot.nombre AS grupo_nombre,
                       COALESCE(catalogo.orden,
                                CASE WHEN snapshot.grupo_pendiente THEN 998 ELSE 999 END)
                           AS grupo_orden,
                       snapshot.porcentaje AS peso_grupo,
                       snapshot.grupo_pendiente
                FROM tb_bom_cotizacion_items linea
                JOIN tb_bom_items item ON item.id_item = linea.bom_item_id
                LEFT JOIN tb_cat_categorias_compra categoria
                  ON categoria.id = item.id_categoria
                CROSS JOIN LATERAL (
                    SELECT distribucion.id_grupo,
                           distribucion.codigo,
                           distribucion.nombre,
                           distribucion.porcentaje,
                           FALSE AS grupo_pendiente
                    FROM JSONB_TO_RECORDSET(COALESCE(
                        linea.grupo_distribucion_snapshot, '[]'::JSONB
                    )) AS distribucion(
                        id_grupo INTEGER,
                        codigo VARCHAR,
                        nombre VARCHAR,
                        porcentaje NUMERIC
                    )
                    UNION ALL
                    SELECT NULL, 'PENDIENTE_DISTRIBUCION',
                           'Pendiente de distribucion', 1::NUMERIC, TRUE
                    WHERE JSONB_ARRAY_LENGTH(COALESCE(
                        linea.grupo_distribucion_snapshot, '[]'::JSONB
                    )) = 0
                ) snapshot
                LEFT JOIN tb_cat_grupos_bom catalogo
                  ON catalogo.id = snapshot.id_grupo
            ),
            pagos_distribuidos AS (
                SELECT linea.grupo_codigo, linea.grupo_nombre, linea.grupo_orden,
                       linea.categoria_id, linea.categoria_nombre,
                       SUM(pago.importe * linea.subtotal_linea / total.subtotal
                           * linea.peso_grupo) AS importe,
                       SUM(pago.pendientes) AS pendientes,
                       COUNT(*) FILTER (WHERE linea.grupo_pendiente)
                           AS grupos_pendientes
                FROM tb_bom_autorizaciones autorizacion
                JOIN pagos_autorizacion pago
                  ON pago.autorizacion_id = autorizacion.id
                JOIN cotizacion_totales total
                  ON total.autorizacion_id = autorizacion.id
                JOIN lineas_pago linea
                  ON linea.cotizacion_id = autorizacion.cotizacion_id
                WHERE autorizacion.bom_id = $1 AND total.subtotal IS NOT NULL
                GROUP BY linea.grupo_codigo, linea.grupo_nombre,
                         linea.grupo_orden, linea.categoria_id,
                         linea.categoria_nombre
            ),
            pagos_pendientes AS (
                SELECT 'PENDIENTE_DISTRIBUCION' AS grupo_codigo,
                       'Pendiente de distribucion' AS grupo_nombre,
                       998 AS grupo_orden,
                       NULL::INTEGER AS categoria_id,
                       'Sin categoria' AS categoria_nombre,
                       0::NUMERIC AS importe,
                       SUM(pago.pendientes) + COUNT(*) AS pendientes,
                       COUNT(*) AS grupos_pendientes
                FROM tb_bom_autorizaciones autorizacion
                JOIN pagos_autorizacion pago
                  ON pago.autorizacion_id = autorizacion.id
                JOIN cotizacion_totales total
                  ON total.autorizacion_id = autorizacion.id
                WHERE autorizacion.bom_id = $1 AND total.subtotal IS NULL
                HAVING COUNT(*) > 0
            ),
            pagos AS (
                SELECT * FROM pagos_distribuidos
                UNION ALL
                SELECT * FROM pagos_pendientes
            ),
            metricas AS (
                SELECT grupo_codigo, grupo_nombre, grupo_orden,
                       categoria_id, categoria_nombre,
                       presupuesto, presupuesto_pendiente,
                       real, real_pendiente, real_base, real_base_pendiente,
                       reemplazos, reemplazos_pendiente,
                       fuera_scope, fuera_scope_pendiente,
                       no_adquirido, no_adquirido_pendiente,
                       0::numeric AS facturado, 0::bigint AS facturado_pendiente,
                       0::numeric AS sugerido, 0::bigint AS sugerido_pendiente,
                       0::numeric AS pagado, 0::bigint AS pagado_pendiente,
                       grupos_pendientes
                FROM costos
                UNION ALL
                SELECT grupo_codigo, grupo_nombre, grupo_orden,
                       categoria_id, categoria_nombre,
                       0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                       importe, pendientes, 0, 0, 0, 0, grupos_pendientes
                FROM facturas
                UNION ALL
                SELECT grupo_codigo, grupo_nombre, grupo_orden,
                       categoria_id, categoria_nombre,
                       0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                       0, 0, importe, pendientes, 0, 0, grupos_pendientes
                FROM sugerencias
                UNION ALL
                SELECT grupo_codigo, grupo_nombre, grupo_orden,
                       categoria_id, categoria_nombre,
                       0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                       0, 0, 0, 0, importe, pendientes, grupos_pendientes
                FROM pagos
            )
            SELECT grupo_codigo, grupo_nombre, grupo_orden,
                   categoria_id, categoria_nombre,
                   CASE WHEN SUM(presupuesto_pendiente) > 0 THEN NULL
                        ELSE SUM(presupuesto) END AS presupuesto_mxn,
                   CASE WHEN SUM(facturado_pendiente) > 0 THEN NULL
                        ELSE SUM(facturado) END AS facturado_confirmado_mxn,
                   CASE WHEN SUM(sugerido_pendiente) > 0 THEN NULL
                        ELSE SUM(sugerido) END AS facturado_sugerido_mxn,
                   CASE WHEN SUM(pagado_pendiente) > 0 THEN NULL
                        ELSE SUM(pagado) END AS pagado_mxn,
                   CASE WHEN SUM(real_pendiente) > 0 THEN NULL
                        ELSE SUM(real) END AS compra_real_mxn,
                   CASE WHEN SUM(real_base_pendiente) > 0 THEN NULL
                        ELSE SUM(real_base) END AS compra_real_base_mxn,
                   CASE WHEN SUM(reemplazos_pendiente) > 0 THEN NULL
                        ELSE SUM(reemplazos) END AS reemplazos_mxn,
                   CASE WHEN SUM(fuera_scope_pendiente) > 0 THEN NULL
                        ELSE SUM(fuera_scope) END AS fuera_scope_mxn,
                   CASE WHEN SUM(no_adquirido_pendiente) > 0 THEN NULL
                        ELSE SUM(no_adquirido) END AS no_adquirido_mxn,
                   SUM(presupuesto_pendiente + real_pendiente
                       + facturado_pendiente + sugerido_pendiente
                       + pagado_pendiente) AS valores_pendientes,
                   SUM(grupos_pendientes) AS grupos_pendientes
            FROM metricas
            GROUP BY grupo_codigo, grupo_nombre, grupo_orden,
                     categoria_id, categoria_nombre
            HAVING SUM(presupuesto + real + facturado + sugerido + pagado
                       + reemplazos + fuera_scope + no_adquirido) <> 0
                OR SUM(presupuesto_pendiente + real_pendiente
                       + facturado_pendiente + sugerido_pendiente
                       + pagado_pendiente + grupos_pendientes) > 0
            ORDER BY grupo_orden, grupo_codigo, categoria_nombre
        """, id_bom)
        return [dict(row) for row in rows]

    async def get_divisores_bom(self, conn, id_bom: UUID) -> dict:
        """Divisores FV congelados al aprobar la version oficial del paquete."""
        row = await conn.fetchrow("""
            SELECT potencia_pico_kwp_snapshot AS kwp,
                   modulos_fv_snapshot AS modulos_fv
            FROM tb_bom
            WHERE id_bom = $1
        """, id_bom)
        return {
            "kwp": float(row["kwp"]) if row and row["kwp"] is not None else None,
            "modulos_fv": float(row["modulos_fv"]) if row and row["modulos_fv"] is not None else None,
        }

    # ─── RFQ (doc 35) ────────────────────────────────────────

    async def crear_rfq(
        self, conn, bom_id: UUID, creado_por: UUID, notas: Optional[str],
        nombre: Optional[str] = None,
    ) -> dict:
        row = await conn.fetchrow("""
            INSERT INTO tb_bom_rfq (bom_id, creado_por, notas, nombre)
            VALUES ($1, $2, $3, $4)
            RETURNING *
        """, bom_id, creado_por, notas, nombre)
        return dict(row)

    async def renombrar_rfq(self, conn, rfq_id: UUID, nombre: str, lock_version_esperado: int) -> Optional[dict]:
        row = await conn.fetchrow("""
            UPDATE tb_bom_rfq SET nombre = $1, lock_version = lock_version + 1, updated_at = NOW()
            WHERE id = $2 AND lock_version = $3
            RETURNING *
        """, nombre, rfq_id, lock_version_esperado)
        return dict(row) if row else None

    async def agregar_items_rfq(self, conn, rfq_id: UUID, items: list) -> int:
        """items: lista de dicts {bom_item_id, cantidad, unidad_override}.

        Retorna cuantas filas se insertaron realmente (el ON CONFLICT hace
        no-op silencioso si el item ya estaba en el RFQ). Insert por lotes via
        unnest en vez de una vuelta a la BD por item.
        """
        if not items:
            return 0
        rows = await conn.fetch("""
            INSERT INTO tb_bom_rfq_items (rfq_id, bom_item_id, cantidad, unidad_override)
            SELECT $1, x.bom_item_id, x.cantidad, x.unidad_override
            FROM unnest($2::uuid[], $3::numeric[], $4::varchar[])
                AS x(bom_item_id, cantidad, unidad_override)
            ON CONFLICT (rfq_id, bom_item_id) DO NOTHING
            RETURNING id
        """,
            rfq_id,
            [i['bom_item_id'] for i in items],
            [i['cantidad'] for i in items],
            [i.get('unidad_override') for i in items],
        )
        return len(rows)

    async def get_rfq_by_id(self, conn, rfq_id: UUID) -> Optional[dict]:
        row = await conn.fetchrow("SELECT * FROM tb_bom_rfq WHERE id = $1", rfq_id)
        return dict(row) if row else None

    async def quitar_item_rfq(self, conn, rfq_id: UUID, bom_item_id: UUID) -> int:
        result = await conn.execute(
            "DELETE FROM tb_bom_rfq_items WHERE rfq_id = $1 AND bom_item_id = $2",
            rfq_id, bom_item_id,
        )
        return int(result.split()[-1]) if result else 0

    async def incrementar_lock_rfq(self, conn, rfq_id: UUID, lock_version_esperado: int) -> Optional[dict]:
        row = await conn.fetchrow("""
            UPDATE tb_bom_rfq SET lock_version = lock_version + 1, updated_at = NOW()
            WHERE id = $1 AND lock_version = $2
            RETURNING *
        """, rfq_id, lock_version_esperado)
        return dict(row) if row else None

    async def registrar_historial_rfq(
        self, conn, rfq_id: UUID, usuario_id: UUID, accion: str, detalle: Optional[dict] = None,
    ) -> None:
        await conn.execute("""
            INSERT INTO tb_bom_rfq_historial (rfq_id, usuario_id, accion, detalle)
            VALUES ($1, $2, $3, $4::jsonb)
        """, rfq_id, usuario_id, accion, json.dumps(detalle or {}))

    async def get_historial_rfq(self, conn, rfq_id: UUID) -> list:
        rows = await conn.fetch("""
            SELECT h.*, u.nombre AS usuario_nombre
            FROM tb_bom_rfq_historial h
            LEFT JOIN tb_usuarios u ON u.id_usuario = h.usuario_id
            WHERE h.rfq_id = $1
            ORDER BY h.fecha DESC
        """, rfq_id)
        return [dict(r) for r in rows]

    # ─── COMPARATIVA RFQ (Gap 7d) ───────────────────────────

    async def get_rfqs_by_bom(self, conn, id_bom: UUID) -> list:
        """RFQs (tb_bom_rfq) de un BOM, con conteo de items."""
        rows = await conn.fetch("""
            SELECT r.*, r.created_at AS creado_en, u.nombre AS creado_por_nombre,
                   COUNT(ri.id) AS total_items_cotizacion
            FROM tb_bom_rfq r
            LEFT JOIN tb_usuarios u ON u.id_usuario = r.creado_por
            LEFT JOIN tb_bom_rfq_items ri ON ri.rfq_id = r.id
            WHERE r.bom_id = $1
            GROUP BY r.id, u.nombre
            ORDER BY r.created_at DESC
        """, id_bom)
        return [dict(r) for r in rows]

    async def get_rfqs_cross_proyecto(self, conn) -> list:
        """RFQs de todos los proyectos, para la vista de solo lectura de Finanzas.

        LIMIT 200 se aplica antes de contar items (CTE + LATERAL) para no expandir
        tb_bom_rfq_items completa por cada fila de RFQ antes de agrupar.
        """
        rows = await conn.fetch("""
            WITH recientes AS (
                SELECT * FROM tb_bom_rfq ORDER BY created_at DESC LIMIT 200
            )
            SELECT r.id, r.nombre, r.created_at AS creado_en,
                   u.nombre AS creado_por_nombre,
                   COALESCE(ic.total_items, 0) AS total_items,
                   b.id_bom, b.version AS bom_version,
                   paquete.codigo AS paquete_codigo, paquete.nombre AS paquete_nombre,
                   p.proyecto_id_estandar, p.nombre_corto AS nombre_proyecto
            FROM recientes r
            JOIN tb_bom b ON b.id_bom = r.bom_id
            JOIN tb_bom_paquetes paquete ON paquete.id_paquete = b.id_paquete
            JOIN tb_proyectos_gate p ON p.id_proyecto = paquete.id_proyecto
            LEFT JOIN tb_usuarios u ON u.id_usuario = r.creado_por
            LEFT JOIN LATERAL (
                SELECT COUNT(*) AS total_items FROM tb_bom_rfq_items ri WHERE ri.rfq_id = r.id
            ) ic ON true
            ORDER BY r.created_at DESC
        """)
        return [dict(r) for r in rows]

    async def get_items_rfq(self, conn, rfq_id: UUID) -> list:
        """Items de un RFQ (tb_bom_rfq_items), con descripcion del item BOM."""
        rows = await conn.fetch("""
            SELECT ri.id, ri.bom_item_id, ri.cantidad, ri.unidad_override,
                   bi.descripcion, bi.unidad_medida, bi.precio_unitario
            FROM tb_bom_rfq_items ri
            JOIN tb_bom_items bi ON bi.id_item = ri.bom_item_id
            WHERE ri.rfq_id = $1
            ORDER BY bi.orden ASC
        """, rfq_id)
        return [dict(r) for r in rows]

    async def get_rfq_responses(self, conn, rfq_id: UUID) -> list:
        """Cotizaciones reales de proveedores que respondieron a un RFQ."""
        rows = await conn.fetch("""
            SELECT c.*, u.nombre AS creado_por_nombre
            FROM tb_bom_cotizaciones c
            LEFT JOIN tb_usuarios u ON u.id_usuario = c.creado_por
            WHERE c.rfq_id = $1
            ORDER BY c.creado_en DESC
        """, rfq_id)
        return [dict(r) for r in rows]

    async def bulk_replace_cotizacion_items(
        self, conn, cotizacion_id: UUID, bom_id: UUID, items: list
    ) -> None:
        """Reemplaza los items de una cotización preservando precios existentes.

        Si un item ya tenía precio y el nuevo payload no trae precio (None),
        se conserva el precio anterior para no destruir datos del proveedor.
        """
        existing = await conn.fetch("""
            SELECT bom_item_id, precio_unitario, cantidad, moneda, subtotal_linea
            FROM tb_bom_cotizacion_items WHERE cotizacion_id = $1
        """, cotizacion_id)
        existing_map = {str(r['bom_item_id']): dict(r) for r in existing}

        await conn.execute(
            "DELETE FROM tb_bom_cotizacion_items WHERE cotizacion_id = $1", cotizacion_id
        )
        if items:
            merged = []
            for item in items:
                item_id_str = str(item['bom_item_id'])
                if item_id_str in existing_map and item.get('precio_unitario') is None:
                    ex = existing_map[item_id_str]
                    merged.append({
                        **item,
                        'precio_unitario': ex['precio_unitario'],
                        'cantidad': ex['cantidad'],
                        'moneda': ex['moneda'],
                        'subtotal_linea': ex['subtotal_linea'],
                    })
                else:
                    merged.append(item)

            await conn.executemany("""
                INSERT INTO tb_bom_cotizacion_items
                    (cotizacion_id, bom_id, bom_item_id, precio_unitario, cantidad,
                     moneda, subtotal_linea, grupo_ids_snapshot,
                     grupo_distribucion_snapshot)
                SELECT $1, $2, $3, $4, $5, $6, $7,
                       grupos.ids,
                       COALESCE((
                           SELECT JSONB_AGG(JSONB_BUILD_OBJECT(
                               'id_grupo', d.id_grupo,
                               'codigo', d.grupo_codigo_snapshot,
                               'nombre', d.grupo_nombre_snapshot,
                               'porcentaje', d.porcentaje
                           ) ORDER BY d.id_grupo)
                           FROM tb_bom_item_grupo_asignaciones d
                           WHERE d.id_bom_item = $3
                           HAVING ABS(SUM(d.porcentaje) - 1) <= 0.000001
                       ), grupos.distribucion_unica, '[]'::JSONB)
                CROSS JOIN LATERAL (
                    WITH efectivos AS (
                        SELECT operativo.id_grupo
                        FROM tb_bom_item_grupos_operativos operativo
                        WHERE operativo.id_item = $3
                        UNION ALL
                        SELECT base.id_grupo
                        FROM tb_bom_item_grupos base
                        WHERE base.id_item = $3
                          AND NOT EXISTS (
                              SELECT 1
                              FROM tb_bom_item_grupos_operativos operativo
                              WHERE operativo.id_item = $3
                          )
                    )
                    SELECT COALESCE(
                               ARRAY_AGG(efectivo.id_grupo ORDER BY efectivo.id_grupo),
                               ARRAY[]::INTEGER[]
                           ) AS ids,
                           CASE WHEN COUNT(*) = 1 THEN
                               JSONB_BUILD_ARRAY(JSONB_BUILD_OBJECT(
                                   'id_grupo', MIN(efectivo.id_grupo),
                                   'codigo', MIN(catalogo.codigo),
                                   'nombre', MIN(catalogo.nombre),
                                   'porcentaje', 1
                               ))
                           END AS distribucion_unica
                    FROM efectivos efectivo
                    JOIN tb_cat_grupos_bom catalogo
                      ON catalogo.id = efectivo.id_grupo
                ) grupos
                ON CONFLICT (cotizacion_id, bom_item_id) DO NOTHING
            """, [
                (cotizacion_id, bom_id, i['bom_item_id'], i.get('precio_unitario'),
                 i.get('cantidad', 1), i['moneda'], i.get('subtotal_linea'))
                for i in merged
            ])
