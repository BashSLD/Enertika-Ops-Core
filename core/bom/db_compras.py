"""
BOM – Compras: cotizaciones, autorizaciones Fase D, trazabilidad, tipo de
cambio, resumen de compra y RFQ. Mixin incluido en BomDBService.
"""

import json
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4
from typing import Optional, List


class BomComprasDBMixin:
    """Cotizaciones, autorizaciones Fase D, conciliacion, resumen de compra y RFQ."""

    # ─── COTIZACIONES ────────────────────────────────────────

    async def crear_cotizacion(
        self, conn, bom_id: UUID, proveedor_id: Optional[UUID],
        nombre_proveedor: Optional[str], moneda: str,
        subtotal, iva, total, notas: Optional[str], creado_por: UUID,
        rfq_id: Optional[UUID] = None,
        modo_simplificado: bool = False,
        folio_proveedor: Optional[str] = None,
    ) -> dict:
        row = await conn.fetchrow("""
            INSERT INTO tb_bom_cotizaciones
                (bom_id, proveedor_id, nombre_proveedor, moneda,
                 subtotal, iva, total, notas, creado_por, rfq_id, modo_simplificado,
                 folio_proveedor)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
            RETURNING *
        """, bom_id, proveedor_id, nombre_proveedor, moneda,
            subtotal, iva, total, notas, creado_por, rfq_id, modo_simplificado,
            folio_proveedor)
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
            FROM (
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
                   ap.motivo_standby AS aprobacion_motivo_standby,
                   ap.fecha_recordatorio AS aprobacion_fecha_recordatorio,
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
                ap.motivo_standby, ap.fecha_recordatorio,
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
                   bi.id_material_interno,
                   cat.nombre AS categoria_nombre
            FROM tb_bom_cotizacion_items ci
            JOIN tb_bom_items bi ON bi.id_item = ci.bom_item_id
            LEFT JOIN tb_cat_categorias_compra cat ON cat.id = bi.id_categoria
            WHERE ci.cotizacion_id = $1
            ORDER BY bi.orden ASC
        """, cotizacion_id)
        return [dict(r) for r in rows]

    async def guardar_historial_cotizacion(
        self, conn, id_proveedor: UUID,
        fecha: date, user_id: UUID, items: List[dict],
        tc_usd: Optional[Decimal],
    ) -> None:
        """Bitacora de precios en tb_materiales_historial (origen='COTIZACION'),
        mismo rol que el historial que ya alimenta el flujo XML pero atado
        directo al bom_item (sin ambiguedad de descripcion de proveedor).

        uuid_factura/numero_linea_cfdi son sinteticos (no hay CFDI real todavia
        para una cotizacion). uuid_factura se genera nuevo en cada llamada (NO se
        deriva de cotizacion_id): una cotizacion rechazada vuelve a RECIBIDA
        (_liberar_cotizacion_rechazada) y puede volver a adjudicarse, lo que
        repetiria el mismo par (uuid_factura, numero_linea_cfdi) contra el
        indice unico uq_materiales_factura_numero_linea si se reusara el id.
        tc_usd: tipo de cambio ya resuelto para el proyecto, solo se persiste en
        items cuya moneda es USD -- congela el TC del dia de adjudicacion para
        que get_items() lo use igual que ya hace con el TC del XML de factura
        (core/bom/db_service.py::get_tc_from_linked_materials).
        """
        uuid_factura = uuid4()
        # precio_unitario/subtotal_linea siempre vienen juntos: _calcular_items_cotizacion
        # solo persiste subtotal_linea cuando precio_unitario > 0 (core/bom/compras_service.py).
        validos = [it for it in items if it.get('precio_unitario') and it.get('cantidad')]
        rows = [
            (
                uuid_factura, id_proveedor, idx,
                it.get('descripcion') or 'Item sin descripcion',
                Decimal(str(it['cantidad'])), Decimal(str(it['precio_unitario'])),
                Decimal(str(it['subtotal_linea'])),
                it.get('unidad_medida'), it.get('id_categoria'),
                fecha, tc_usd if it.get('moneda') == 'USD' else None,
                user_id, it['bom_item_id'],
            )
            for idx, it in enumerate(validos, start=1)
        ]
        if not rows:
            return
        await conn.executemany("""
            INSERT INTO tb_materiales_historial (
                uuid_factura, id_proveedor, numero_linea_cfdi,
                descripcion_proveedor, cantidad, precio_unitario, importe,
                unidad, id_categoria, fecha_factura, tipo_cambio_xml,
                created_by_id, id_bom_item, origen
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,'COTIZACION')
        """, rows)

    async def get_items_by_cotizacion_ids(self, conn, cotizacion_ids: list) -> List[dict]:
        rows = await conn.fetch("""
            SELECT ci.*, ci.bom_item_id AS id_item,
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

    async def actualizar_cotizacion(
        self, conn, cotizacion_id: UUID, proveedor_id: Optional[UUID],
        nombre_proveedor: Optional[str], moneda: str,
        subtotal, iva, total, notas: Optional[str],
        lock_version_esperado: int,
        modo_simplificado: bool = False,
        folio_proveedor: Optional[str] = None,
    ) -> Optional[dict]:
        row = await conn.fetchrow("""
            UPDATE tb_bom_cotizaciones
            SET proveedor_id = $2, nombre_proveedor = $3, moneda = $4,
                subtotal = $5, iva = $6, total = $7, notas = $8,
                modo_simplificado = $10, folio_proveedor = $11,
                actualizado_en = NOW(), lock_version = lock_version + 1
            WHERE id = $1 AND estatus IN ('BORRADOR', 'RECIBIDA') AND lock_version = $9
            RETURNING *
        """, cotizacion_id, proveedor_id, nombre_proveedor, moneda,
            subtotal, iva, total, notas, lock_version_esperado, modo_simplificado,
            folio_proveedor)
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

    async def ajustar_cantidad_cubierta_items(
        self, conn, ajustes: List[tuple],
    ) -> List[dict]:
        """Incrementa/decrementa cantidad_cubierta por item y deriva estatus_compra.

        `ajustes`: lista de (bom_item_id, delta) -- delta positivo al adjudicar
        una cotizacion, negativo al liberarla. El CHECK
        tb_bom_items_cantidad_cubierta_check (0 <= cantidad_cubierta <= cantidad,
        migracion 183) es la ultima linea de defensa contra un delta mal
        calculado: si el resultado se sale de rango, el UPDATE falla completo.
        """
        if not ajustes:
            return []
        ids = [a[0] for a in ajustes]
        deltas = [a[1] for a in ajustes]
        rows = await conn.fetch("""
            UPDATE tb_bom_items bi
            SET cantidad_cubierta = bi.cantidad_cubierta + d.delta,
                estatus_compra = CASE
                    WHEN bi.cantidad_cubierta + d.delta <= 0 THEN 'SIN_COTIZAR'
                    WHEN bi.cantidad_cubierta + d.delta >= bi.cantidad THEN 'COTIZADO'
                    ELSE 'PARCIALMENTE_COTIZADO'
                END,
                lock_version = bi.lock_version + 1,
                updated_at = NOW()
            FROM UNNEST($1::uuid[], $2::numeric[]) AS d(bom_item_id, delta)
            WHERE bi.id_item = d.bom_item_id
            RETURNING bi.id_item, bi.estatus_compra, bi.cantidad_cubierta, bi.cantidad
        """, ids, deltas)
        return [dict(r) for r in rows]

    async def autorizar_items_cotizacion_por_cobertura(
        self, conn, bom_item_ids: List[UUID],
    ) -> List[dict]:
        """Promueve a AUTORIZADO solo los items totalmente cubiertos (cantidad_cubierta
        >= cantidad); el remanente sin cubrir por ninguna cotizacion se queda en su
        estatus_compra actual (PARCIALMENTE_COTIZADO) para seguir siendo elegible a
        una nueva cotizacion -- antes, avanzar Fase D marcaba AUTORIZADO al lote
        completo de la cotizacion sin mirar cobertura, bloqueando el remanente para
        siempre (item_disponible_cotizacion lo excluye una vez en ese estatus)."""
        rows = await conn.fetch("""
            UPDATE tb_bom_items
            SET estatus_compra = 'AUTORIZADO',
                lock_version = lock_version + 1,
                updated_at = NOW()
            WHERE id_item = ANY($1::uuid[])
              AND cantidad_cubierta >= cantidad
            RETURNING id_item, estatus_compra
        """, bom_item_ids)
        return [dict(r) for r in rows]

    async def get_items_con_cotizacion_activa(
        self, conn, item_ids: List[UUID], excluir_cotizacion_id: Optional[UUID] = None,
    ) -> List[UUID]:
        """IDs de items que ya estan en otra cotizacion BORRADOR/RECIBIDA -- para
        bloquear una 2a cotizacion activa compitiendo por el mismo remanente
        parcial (decision de negocio 2026-08-27, plan seccion 3)."""
        rows = await conn.fetch("""
            SELECT DISTINCT ci.bom_item_id
            FROM tb_bom_cotizacion_items ci
            JOIN tb_bom_cotizaciones c ON c.id = ci.cotizacion_id
            WHERE ci.bom_item_id = ANY($1::uuid[])
              AND c.estatus IN ('BORRADOR', 'RECIBIDA')
              AND ($2::uuid IS NULL OR c.id != $2)
        """, item_ids, excluir_cotizacion_id)
        return [r['bom_item_id'] for r in rows]

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
                   c.pdf_url,
                   c.folio_proveedor,
                   r.nombre AS rfq_nombre,
                   u1.nombre AS aprobador_obra_nombre,
                   u2.nombre AS aprobador_direccion_nombre,
                   u3.nombre AS aprobador_finanzas_nombre,
                   u4.nombre AS rechazado_por_nombre
            FROM tb_bom_autorizaciones a
            JOIN tb_bom_cotizaciones c ON c.id = a.cotizacion_id
            LEFT JOIN tb_bom_rfq r ON r.id = c.rfq_id
            LEFT JOIN tb_usuarios u1 ON u1.id_usuario = a.aprobador_obra_id
            LEFT JOIN tb_usuarios u2 ON u2.id_usuario = a.aprobador_direccion_id
            LEFT JOIN tb_usuarios u3 ON u3.id_usuario = a.aprobador_finanzas_id
            LEFT JOIN tb_usuarios u4 ON u4.id_usuario = a.rechazado_por
            WHERE a.bom_id = $1
            ORDER BY a.creado_en DESC
        """, bom_id)
        return [dict(r) for r in rows]

    async def get_bom_ids_con_autorizacion_pendiente(
        self, conn, bom_ids: List[UUID],
    ) -> set:
        """Batch: subconjunto de bom_ids con al menos una autorizacion PENDIENTE
        (paso Obra). Usado para decidir visibilidad del boton "Autorizar compra"
        en el hub de paquetes sin N+1 (una query para todo el proyecto)."""
        if not bom_ids:
            return set()
        rows = await conn.fetch(
            """
            SELECT DISTINCT bom_id
            FROM tb_bom_autorizaciones
            WHERE estatus = 'PENDIENTE' AND bom_id = ANY($1::uuid[])
            """,
            bom_ids,
        )
        return {r["bom_id"] for r in rows}

    async def get_autorizaciones_pendientes_por_coordinador(
        self, conn, representados: List[UUID], rol_organizacional: Optional[str],
    ) -> List[dict]:
        """Autorizaciones PENDIENTE (paso Obra) de cualquier BOM cuyo coordinador
        de obra sea alguno de los `representados` (titular o suplente activo), o
        -- si el paquete no tiene coordinador asignado -- el usuario tenga el rol
        organizacional jefe_construccion. Mismo predicado que
        BomService.es_coordinador_obra() (service.py), duplicado aqui en SQL a
        proposito: es un filtro cross-BOM (`b.coordinador_obra = ANY($1)`) sobre
        potencialmente muchos paquetes a la vez; resolverlo trayendo candidatos a
        Python y filtrando en memoria implicaria un N+1 o una query igual de
        grande. Si esta regla cambia, actualizar ambos lugares.
        Cross-BOM en una sola query para alimentar el popup de pendientes al
        entrar a la app (PLAN_popup_pendientes_autorizacion_obra.md §2)."""
        rows = await conn.fetch("""
            SELECT a.*,
                   c.nombre_proveedor,
                   c.pdf_url,
                   c.folio_proveedor,
                   r.nombre AS rfq_nombre,
                   b.id_paquete,
                   paq.codigo AS paquete_codigo,
                   paq.nombre AS paquete_nombre,
                   o.nombre_proyecto AS proyecto_nombre,
                   p.proyecto_id_estandar
            FROM tb_bom_autorizaciones a
            JOIN tb_bom_cotizaciones c ON c.id = a.cotizacion_id
            JOIN tb_bom b ON b.id_bom = a.bom_id
            JOIN tb_bom_paquetes paq ON paq.id_paquete = b.id_paquete
            LEFT JOIN tb_bom_rfq r ON r.id = c.rfq_id
            LEFT JOIN tb_proyectos_gate p ON p.id_proyecto = b.id_proyecto
            LEFT JOIN tb_oportunidades o ON o.id_oportunidad = p.id_oportunidad
            WHERE a.estatus = 'PENDIENTE'
              AND (
                  b.coordinador_obra = ANY($1::uuid[])
                  OR (b.coordinador_obra IS NULL AND $2 = 'jefe_construccion')
              )
            ORDER BY a.creado_en ASC
            LIMIT 20
        """, representados, rol_organizacional)
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
        """Aprobacion activa (pendiente, en standby, o aprobada) de una cotizacion;
        maximo una por indice unico parcial uq_bom_cot_aprob_activa (migracion 184)."""
        row = await conn.fetchrow("""
            SELECT ap.*
            FROM tb_bom_cotizacion_aprobaciones ap
            WHERE ap.cotizacion_id = $1
              AND ap.estatus IN (
                  'PENDIENTE_DIRECCION', 'APROBADA',
                  'EN_STANDBY', 'PENDIENTE_VIGENCIA_COMPRAS'
              )
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

    # ─── STANDBY DE DIRECCION Y VIGENCIA (COMPRAS) ──────────

    async def poner_en_standby_db(
        self, conn, aprobacion_id: UUID, motivo_standby: str,
        fecha_recordatorio: date, lock_version_esperado: int,
    ) -> Optional[dict]:
        """PENDIENTE_DIRECCION -> EN_STANDBY. Resetea recordatorio_enviado_at para
        que el worker vuelva a considerar esta fila elegible."""
        row = await conn.fetchrow("""
            UPDATE tb_bom_cotizacion_aprobaciones
            SET estatus = 'EN_STANDBY',
                motivo_standby = $2,
                fecha_recordatorio = $3,
                recordatorio_enviado_at = NULL,
                updated_at = NOW(),
                lock_version = lock_version + 1
            WHERE id = $1 AND estatus = 'PENDIENTE_DIRECCION'
              AND lock_version = $4
            RETURNING *
        """, aprobacion_id, motivo_standby, fecha_recordatorio, lock_version_esperado)
        return dict(row) if row else None

    async def reprogramar_standby_db(
        self, conn, aprobacion_id: UUID, motivo_standby: str,
        fecha_recordatorio: date, lock_version_esperado: int,
    ) -> Optional[dict]:
        """EN_STANDBY -> EN_STANDBY con nuevo motivo/fecha; resetea el dedupe del worker."""
        row = await conn.fetchrow("""
            UPDATE tb_bom_cotizacion_aprobaciones
            SET motivo_standby = $2,
                fecha_recordatorio = $3,
                recordatorio_enviado_at = NULL,
                updated_at = NOW(),
                lock_version = lock_version + 1
            WHERE id = $1 AND estatus = 'EN_STANDBY'
              AND lock_version = $4
            RETURNING *
        """, aprobacion_id, motivo_standby, fecha_recordatorio, lock_version_esperado)
        return dict(row) if row else None

    async def reclamar_standbys_vencidos_db(
        self, conn, hoy: date, limite: int = 50,
    ) -> List[dict]:
        """Reclama con FOR UPDATE SKIP LOCKED las aprobaciones EN_STANDBY cuyo
        recordatorio ya vencio y aun no fue enviado (dedupe por
        recordatorio_enviado_at), y las transiciona a PENDIENTE_VIGENCIA_COMPRAS
        marcando el envio en la misma sentencia -- un tick concurrente nunca
        vuelve a tomar la misma fila (patron de core/bom/outbox_worker.py)."""
        rows = await conn.fetch("""
            WITH candidatas AS (
                SELECT id, bom_id
                FROM tb_bom_cotizacion_aprobaciones
                WHERE estatus = 'EN_STANDBY'
                  AND fecha_recordatorio <= $1
                  AND recordatorio_enviado_at IS NULL
                ORDER BY fecha_recordatorio, id
                FOR UPDATE SKIP LOCKED
                LIMIT $2
            )
            UPDATE tb_bom_cotizacion_aprobaciones ap
            SET estatus = 'PENDIENTE_VIGENCIA_COMPRAS',
                recordatorio_enviado_at = NOW(),
                updated_at = NOW(),
                lock_version = lock_version + 1
            FROM candidatas
            JOIN tb_bom b ON b.id_bom = candidatas.bom_id
            WHERE ap.id = candidatas.id
            RETURNING ap.*, b.id_paquete
        """, hoy, limite)
        return [dict(r) for r in rows]

    async def confirmar_vigencia_reactiva_direccion_db(
        self, conn, aprobacion_id: UUID, lock_version_esperado: int,
    ) -> Optional[dict]:
        """PENDIENTE_VIGENCIA_COMPRAS -> PENDIENTE_DIRECCION (vigente): limpia el
        rastro de standby resuelto y regresa la cotizacion a la cola de Direccion."""
        row = await conn.fetchrow("""
            UPDATE tb_bom_cotizacion_aprobaciones
            SET estatus = 'PENDIENTE_DIRECCION',
                motivo_standby = NULL,
                fecha_recordatorio = NULL,
                recordatorio_enviado_at = NULL,
                updated_at = NOW(),
                lock_version = lock_version + 1
            WHERE id = $1 AND estatus = 'PENDIENTE_VIGENCIA_COMPRAS'
              AND lock_version = $2
            RETURNING *
        """, aprobacion_id, lock_version_esperado)
        return dict(row) if row else None

    async def rechazar_cotizacion_aprobacion_vigencia_db(
        self, conn, aprobacion_id: UUID, user_id: UUID, motivo: str,
        lock_version_esperado: int,
    ) -> Optional[dict]:
        """PENDIENTE_VIGENCIA_COMPRAS -> RECHAZADA: camino "no vigente" desde la
        reactivacion (Punto B). Espejo de rechazar_cotizacion_aprobacion_db con
        estado-origen distinto (Gap #9: CAS literal, no parametrizado)."""
        row = await conn.fetchrow("""
            UPDATE tb_bom_cotizacion_aprobaciones
            SET estatus = 'RECHAZADA',
                rechazado_por = $2,
                rechazado_en = NOW(),
                motivo_rechazo = $3,
                updated_at = NOW(),
                lock_version = lock_version + 1
            WHERE id = $1 AND estatus = 'PENDIENTE_VIGENCIA_COMPRAS'
              AND lock_version = $4
            RETURNING *
        """, aprobacion_id, user_id, motivo, lock_version_esperado)
        return dict(row) if row else None

    async def actualizar_total_pdf_cotizacion_vigencia(
        self, conn, cotizacion_id: UUID, nuevo_total, nuevo_pdf_url: Optional[str],
        lock_version_esperado: int,
    ) -> Optional[dict]:
        """Actualiza solo el total agregado (y opcionalmente el PDF) de una
        cotizacion SELECCIONADA sin tocarle estatus -- decision de alcance
        2026-08-28: no reabre el detalle por item (bulk_replace_cotizacion_items).
        No reutiliza actualizar_cotizacion/actualizar_pdf_cotizacion: ambas exigen
        estatus IN ('BORRADOR','RECIBIDA') y la segunda ademas fuerza
        estatus='RECIBIDA' como efecto secundario."""
        row = await conn.fetchrow("""
            UPDATE tb_bom_cotizaciones
            SET total = $2,
                pdf_url = COALESCE($3, pdf_url),
                actualizado_en = NOW(),
                lock_version = lock_version + 1
            WHERE id = $1 AND estatus = 'SELECCIONADA' AND lock_version = $4
            RETURNING *
        """, cotizacion_id, nuevo_total, nuevo_pdf_url, lock_version_esperado)
        return dict(row) if row else None

    async def sincronizar_monto_autorizacion_db(
        self, conn, autorizacion_id: UUID, monto_total, lock_version_esperado: int,
    ) -> Optional[dict]:
        """Sincroniza tb_bom_autorizaciones.monto_total tras una actualizacion de
        vigencia, en la misma transaccion que actualizar_total_pdf_cotizacion_vigencia.
        Sin este paso, el CONSTRAINT TRIGGER DEFERRED fn_bom_validar_documento_cotizacion
        (migraciones 160/177) revienta con RAISE EXCEPTION en cualquier UPDATE futuro
        no relacionado de tb_bom_autorizaciones, al comparar contra el total ya
        desincronizado (Gap #7)."""
        row = await conn.fetchrow("""
            UPDATE tb_bom_autorizaciones
            SET monto_total = $2,
                lock_version = lock_version + 1
            WHERE id = $1 AND lock_version = $3
            RETURNING *
        """, autorizacion_id, monto_total, lock_version_esperado)
        return dict(row) if row else None

    async def get_paquete_tiene_standby_activo(self, conn, id_paquete: UUID) -> bool:
        """True si el paquete tiene alguna cotizacion con aprobacion en
        EN_STANDBY/PENDIENTE_VIGENCIA_COMPRAS -- guard de cambiar_estado_paquete
        (Gap #11)."""
        existe = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1
                FROM tb_bom_cotizacion_aprobaciones ap
                JOIN tb_bom b ON b.id_bom = ap.bom_id
                WHERE b.id_paquete = $1
                  AND ap.estatus IN ('EN_STANDBY', 'PENDIENTE_VIGENCIA_COMPRAS')
            )
        """, id_paquete)
        return bool(existe)

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

    async def get_rfq_nombres_similares(self, conn, patron_base: str) -> list:
        """Nombres de RFQ (de cualquier proyecto) iguales a patron_base o con sufijo
        '-N' -- usado para autogenerar un nombre unico cuando no se captura uno."""
        rows = await conn.fetch(
            "SELECT nombre FROM tb_bom_rfq WHERE nombre = $1 OR nombre LIKE $2",
            patron_base, patron_base + '-%',
        )
        return [r['nombre'] for r in rows]

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

    async def rfq_tiene_pago_asignado(self, conn, rfq_id: UUID) -> bool:
        """True si alguna cotizacion de este RFQ ya tiene un pago registrado
        (tb_bom_rfq -> tb_bom_cotizaciones.rfq_id -> tb_bom_autorizaciones.cotizacion_id
        -> tb_bom_pagos.autorizacion_id). Los pagos se concilian por el nombre del RFQ,
        asi que una vez que existe un pago el nombre ya no debe poder cambiarse."""
        exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1
                FROM tb_bom_pagos pg
                JOIN tb_bom_autorizaciones a ON a.id = pg.autorizacion_id
                JOIN tb_bom_cotizaciones c ON c.id = a.cotizacion_id
                WHERE c.rfq_id = $1
            )
        """, rfq_id)
        return bool(exists)

    async def renombrar_rfq(self, conn, rfq_id: UUID, nombre: str, lock_version_esperado: int) -> Optional[dict]:
        """NOT EXISTS pliega el chequeo de pago-asignado en la misma UPDATE en
        vez de una query aparte antes: en el caso comun (sin pago) esto ahorra
        un roundtrip; el caller solo vuelve a consultar rfq_tiene_pago_asignado
        si esta UPDATE no afecto ninguna fila, para dar el mensaje especifico."""
        row = await conn.fetchrow("""
            UPDATE tb_bom_rfq SET nombre = $1, lock_version = lock_version + 1, updated_at = NOW()
            WHERE id = $2 AND lock_version = $3
              AND NOT EXISTS (
                  SELECT 1
                  FROM tb_bom_pagos pg
                  JOIN tb_bom_autorizaciones a ON a.id = pg.autorizacion_id
                  JOIN tb_bom_cotizaciones c ON c.id = a.cotizacion_id
                  WHERE c.rfq_id = tb_bom_rfq.id
              )
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

    async def actualizar_unidad_item_rfq(
        self, conn, rfq_id: UUID, bom_item_id: UUID, unidad_override: Optional[str],
    ) -> int:
        result = await conn.execute(
            "UPDATE tb_bom_rfq_items SET unidad_override = $3 WHERE rfq_id = $1 AND bom_item_id = $2",
            rfq_id, bom_item_id, unidad_override,
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
        """RFQs (tb_bom_rfq) de un BOM, con conteo de items y si ya tiene un
        pago asignado (calculado aqui via EXISTS para no repetir un roundtrip
        de rfq_tiene_pago_asignado por cada RFQ en la comparativa)."""
        rows = await conn.fetch("""
            SELECT r.*, r.created_at AS creado_en, u.nombre AS creado_por_nombre,
                   COUNT(ri.id) AS total_items_cotizacion,
                   EXISTS (
                       SELECT 1
                       FROM tb_bom_pagos pg
                       JOIN tb_bom_autorizaciones a ON a.id = pg.autorizacion_id
                       JOIN tb_bom_cotizaciones c ON c.id = a.cotizacion_id
                       WHERE c.rfq_id = r.id
                   ) AS tiene_pago_asignado
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
                FROM (
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
