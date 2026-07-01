"""
BOM – Compras: cotizaciones, autorizaciones Fase D, trazabilidad, tipo de
cambio, resumen de compra y RFQ. Mixin incluido en BomDBService.
"""

from uuid import UUID
from typing import Optional, List


class BomComprasDBMixin:
    """Cotizaciones, autorizaciones Fase D, conciliacion, resumen de compra y RFQ."""

    # ─── COTIZACIONES ────────────────────────────────────────

    async def crear_cotizacion(
        self, conn, bom_id: UUID, proveedor_id: Optional[UUID],
        nombre_proveedor: Optional[str], moneda: str,
        subtotal, iva, total, notas: Optional[str], creado_por: UUID,
        es_rfq: bool = False, rfq_origen_id: Optional[UUID] = None
    ) -> dict:
        row = await conn.fetchrow("""
            INSERT INTO tb_bom_cotizaciones
                (bom_id, proveedor_id, nombre_proveedor, moneda,
                 subtotal, iva, total, notas, creado_por, es_rfq, rfq_origen_id)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
            RETURNING *
        """, bom_id, proveedor_id, nombre_proveedor, moneda,
            subtotal, iva, total, notas, creado_por, es_rfq, rfq_origen_id)
        return dict(row)

    async def agregar_items_cotizacion(self, conn, cotizacion_id: UUID, items: list) -> None:
        """Inserta ítems en tb_bom_cotizacion_items en lote."""
        await conn.executemany("""
            INSERT INTO tb_bom_cotizacion_items
                (cotizacion_id, bom_item_id, precio_unitario, cantidad, moneda, subtotal_linea)
            VALUES ($1,$2,$3,$4,$5,$6)
            ON CONFLICT (cotizacion_id, bom_item_id) DO NOTHING
        """, [
            (cotizacion_id,
             i['bom_item_id'], i['precio_unitario'], i['cantidad'],
             i.get('moneda', 'MXN'), i['subtotal_linea'])
            for i in items
        ])

    async def get_cotizaciones_by_bom(self, conn, bom_id: UUID) -> List[dict]:
        rows = await conn.fetch("""
            SELECT c.*,
                   u.nombre AS creado_por_nombre,
                   COUNT(ci.id) AS total_items_cotizacion
            FROM tb_bom_cotizaciones c
            LEFT JOIN tb_usuarios u ON u.id_usuario = c.creado_por
            LEFT JOIN tb_bom_cotizacion_items ci ON ci.cotizacion_id = c.id
            WHERE c.bom_id = $1
            GROUP BY c.id, u.nombre
            ORDER BY c.creado_en DESC
        """, bom_id)
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
        self, conn, cotizacion_id: UUID, estatus: str
    ) -> Optional[dict]:
        row = await conn.fetchrow("""
            UPDATE tb_bom_cotizaciones
            SET estatus = $2, actualizado_en = NOW()
            WHERE id = $1
            RETURNING *
        """, cotizacion_id, estatus)
        return dict(row) if row else None

    async def devolver_cotizacion_borrador(
        self, conn, cotizacion_id: UUID, motivo: str
    ) -> Optional[dict]:
        """Devuelve cotización a BORRADOR con comentarios_revision."""
        row = await conn.fetchrow("""
            UPDATE tb_bom_cotizaciones
            SET estatus = 'BORRADOR',
                comentarios_revision = $2,
                actualizado_en = NOW()
            WHERE id = $1
            RETURNING *
        """, cotizacion_id, motivo)
        return dict(row) if row else None

    async def actualizar_pdf_cotizacion(
        self, conn, cotizacion_id: UUID, pdf_url: str
    ) -> Optional[dict]:
        row = await conn.fetchrow("""
            UPDATE tb_bom_cotizaciones
            SET pdf_url = $2, estatus = 'RECIBIDA', actualizado_en = NOW()
            WHERE id = $1
            RETURNING *
        """, cotizacion_id, pdf_url)
        return dict(row) if row else None

    async def actualizar_estatus_compra_items(
        self, conn, bom_item_ids: List[UUID], estatus_compra: str
    ) -> None:
        """Actualiza estatus_compra legacy y el estatus operativo real en lote."""
        await conn.execute("""
            UPDATE tb_bom_items
            SET estatus_compra = $1, updated_at = NOW()
            WHERE id_item = ANY($2::uuid[])
        """, estatus_compra, bom_item_ids)
        await conn.execute("""
            INSERT INTO tb_bom_item_ejecucion (id_item, estatus_ejecucion)
            SELECT id_item,
                   CASE WHEN $1 = 'SIN_COTIZAR' THEN 'PENDIENTE' ELSE $1 END
            FROM tb_bom_items
            WHERE id_item = ANY($2::uuid[])
            ON CONFLICT (id_item) DO UPDATE
            SET estatus_ejecucion = EXCLUDED.estatus_ejecucion,
                updated_at = NOW()
        """, estatus_compra, bom_item_ids)

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

    async def get_tipo_cambio_vigente(self, conn) -> Optional[dict]:
        row = await conn.fetchrow("""
            SELECT tasa_mxn, fecha FROM tb_tipo_cambio
            ORDER BY fecha DESC LIMIT 1
        """)
        return dict(row) if row else None

    async def get_director(self, conn) -> Optional[dict]:
        """Obtiene el primer usuario con rol_organizacional = 'director'."""
        row = await conn.fetchrow("""
            SELECT id_usuario, nombre, email
            FROM tb_usuarios
            WHERE rol_organizacional = 'director' AND is_active = TRUE
            LIMIT 1
        """)
        return dict(row) if row else None

    async def update_autorizacion_paso_obra(
        self, conn, autorizacion_id: UUID, user_id: UUID, nota: Optional[str]
    ) -> dict:
        row = await conn.fetchrow("""
            UPDATE tb_bom_autorizaciones
            SET estatus = 'AUTORIZADO_OBRA',
                aprobador_obra_id = $2,
                fecha_aprobacion_obra = NOW(),
                nota_obra = $3
            WHERE id = $1
            RETURNING *
        """, autorizacion_id, user_id, nota)
        return dict(row)

    async def update_autorizacion_paso_direccion(
        self, conn, autorizacion_id: UUID, user_id: UUID, nota: Optional[str]
    ) -> dict:
        row = await conn.fetchrow("""
            UPDATE tb_bom_autorizaciones
            SET estatus = 'AUTORIZADO_DIRECCION',
                aprobador_direccion_id = $2,
                fecha_aprobacion_direccion = NOW(),
                nota_direccion = $3
            WHERE id = $1
            RETURNING *
        """, autorizacion_id, user_id, nota)
        return dict(row)

    async def update_autorizacion_paso_finanzas(
        self, conn, autorizacion_id: UUID, user_id: UUID, nota: Optional[str]
    ) -> dict:
        row = await conn.fetchrow("""
            UPDATE tb_bom_autorizaciones
            SET estatus = 'AUTORIZADO_FINANZAS',
                aprobador_finanzas_id = $2,
                fecha_aprobacion_finanzas = NOW(),
                nota_finanzas = $3
            WHERE id = $1
            RETURNING *
        """, autorizacion_id, user_id, nota)
        return dict(row)

    async def rechazar_autorizacion_db(
        self, conn, autorizacion_id: UUID, user_id: UUID,
        motivo: str, paso: str
    ) -> dict:
        row = await conn.fetchrow("""
            UPDATE tb_bom_autorizaciones
            SET estatus = 'RECHAZADO',
                rechazado_en_paso = $3,
                rechazado_por = $2,
                motivo_rechazo = $4,
                fecha_rechazo = NOW()
            WHERE id = $1
            RETURNING *
        """, autorizacion_id, user_id, paso, motivo)
        return dict(row)

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
                   (bi.cantidad * COALESCE(bi.precio_unitario, 0)) AS importe,
                   m.clave_prod_serv AS material_clave,
                   ci.precio_unitario AS coti_precio,
                   ci.cantidad AS coti_cantidad,
                   ci.subtotal_linea AS coti_subtotal
            FROM tb_bom_items bi
            JOIN tb_bom_cotizacion_items ci ON ci.bom_item_id = bi.id_item
            JOIN tb_bom_autorizaciones a ON a.cotizacion_id = ci.cotizacion_id
            LEFT JOIN tb_cat_categorias_compra c ON c.id = bi.id_categoria
            LEFT JOIN tb_cat_materiales m ON m.id = bi.id_material_ref
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
                   cp.uuid_factura
            FROM tb_materiales_historial mh
            JOIN tb_comprobantes_pago cp ON cp.id_comprobante = mh.id_comprobante
            JOIN tb_bom_pagos bp ON bp.id = cp.id_bom_pago
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
        self, conn, historial_id: UUID, id_bom_item: Optional[UUID]
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
                sugerencia_origen = NULL
            WHERE id = $1
            RETURNING id AS historial_id, id_bom_item
        """, historial_id, id_bom_item)
        return dict(row) if row else None

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

    async def update_items_estatus_compra(
        self, conn, item_ids: List[UUID], estatus_compra: str
    ) -> None:
        """Actualiza estatus_compra legacy y el estatus operativo real en lote."""
        await conn.execute("""
            UPDATE tb_bom_items
            SET estatus_compra = $1, updated_at = NOW()
            WHERE id_item = ANY($2::uuid[])
        """, estatus_compra, item_ids)
        await conn.execute("""
            INSERT INTO tb_bom_item_ejecucion (id_item, estatus_ejecucion)
            SELECT id_item,
                   CASE WHEN $1 = 'SIN_COTIZAR' THEN 'PENDIENTE' ELSE $1 END
            FROM tb_bom_items
            WHERE id_item = ANY($2::uuid[])
            ON CONFLICT (id_item) DO UPDATE
            SET estatus_ejecucion = EXCLUDED.estatus_ejecucion,
                updated_at = NOW()
        """, estatus_compra, item_ids)

    async def actualizar_estatus_compra_por_cotizacion(
        self, conn, cotizacion_id: UUID, nuevo_estatus: str,
        solo_si_estatus: Optional[str] = None
    ) -> int:
        """Actualiza estatus_compra de todos los items de una cotizacion.

        Si solo_si_estatus se especifica, solo actualiza items en ese estatus actual.
        Retorna cantidad de rows actualizadas.
        """
        if solo_si_estatus:
            result = await conn.execute("""
                WITH updated_items AS (
                    UPDATE tb_bom_items bi
                    SET estatus_compra = $1, updated_at = NOW()
                    FROM tb_bom_cotizacion_items ci
                    WHERE ci.cotizacion_id = $2
                      AND ci.bom_item_id = bi.id_item
                      AND bi.estatus_compra = $3
                    RETURNING bi.id_item
                )
                INSERT INTO tb_bom_item_ejecucion (id_item, estatus_ejecucion)
                SELECT id_item,
                       CASE WHEN $1 = 'SIN_COTIZAR' THEN 'PENDIENTE' ELSE $1 END
                FROM updated_items
                ON CONFLICT (id_item) DO UPDATE
                SET estatus_ejecucion = EXCLUDED.estatus_ejecucion,
                    updated_at = NOW()
            """, nuevo_estatus, cotizacion_id, solo_si_estatus)
        else:
            result = await conn.execute("""
                WITH updated_items AS (
                    UPDATE tb_bom_items bi
                    SET estatus_compra = $1, updated_at = NOW()
                    FROM tb_bom_cotizacion_items ci
                    WHERE ci.cotizacion_id = $2
                      AND ci.bom_item_id = bi.id_item
                    RETURNING bi.id_item
                )
                INSERT INTO tb_bom_item_ejecucion (id_item, estatus_ejecucion)
                SELECT id_item,
                       CASE WHEN $1 = 'SIN_COTIZAR' THEN 'PENDIENTE' ELSE $1 END
                FROM updated_items
                ON CONFLICT (id_item) DO UPDATE
                SET estatus_ejecucion = EXCLUDED.estatus_ejecucion,
                    updated_at = NOW()
            """, nuevo_estatus, cotizacion_id)
        return int(result.split()[-1]) if result else 0

    # ─── RESUMEN DE COMPRA (Presupuesto vs Facturado vs Pagado) ───

    async def get_resumen_compra(self, conn, id_bom: UUID) -> List[dict]:
        """Comparativo por grupo BOM y categoria: presupuesto, facturado y pagado.

        La seccion sale de tb_bom_item_grupos (AC/DC/CM/OC/TE). Si un item tiene
        multiples grupos, reparte su importe de forma equitativa. La columna
        seccion_bom de categorias solo queda como respaldo para historicos sin grupo.
        """
        rows = await conn.fetch("""
            WITH items_base AS (
                SELECT i.id_item, i.id_item_origen, i.id_categoria,
                       c.nombre AS categoria_nombre,
                       c.seccion_bom,
                       i.cantidad,
                       COALESCE(i.precio_unitario, 0) AS precio_unitario,
                       COALESCE(er.precio_real, 0) AS precio_real,
                       COALESCE(i.tipo_origen_item, 'BASE') AS tipo_origen_item,
                       COALESCE(er.estatus_ejecucion, 'PENDIENTE') AS estatus_ejecucion
                FROM tb_bom_items i
                LEFT JOIN tb_cat_categorias_compra c ON c.id = i.id_categoria
                LEFT JOIN tb_bom_item_ejecucion er ON er.id_item = i.id_item
                WHERE i.id_bom = $1 AND i.activo = TRUE
            ),
            grupos_base_raw AS (
                SELECT ig.id_item, g.id, g.codigo, g.nombre, g.orden
                FROM tb_bom_item_grupos ig
                JOIN tb_cat_grupos_bom g ON g.id = ig.id_grupo
                WHERE g.activo = TRUE
            ),
            grupos_operativos_raw AS (
                SELECT ig.id_item, g.id, g.codigo, g.nombre, g.orden
                FROM tb_bom_item_grupos_operativos ig
                JOIN tb_cat_grupos_bom g ON g.id = ig.id_grupo
                WHERE g.activo = TRUE
            ),
            item_grupos_base AS (
                SELECT ib.id_item,
                       ib.id_item_origen,
                       ib.id_categoria AS categoria_id,
                       COALESCE(ib.categoria_nombre, 'Sin categoria') AS categoria_nombre,
                       COALESCE(g.codigo, ib.seccion_bom, 'SIN_CLASIFICAR') AS grupo_codigo,
                       COALESCE(g.nombre, ib.seccion_bom, 'Sin clasificar') AS grupo_nombre,
                       COALESCE(g.orden, 999) AS grupo_orden,
                       CASE
                         WHEN COUNT(g.id) OVER (PARTITION BY ib.id_item) > 0
                         THEN 1.0 / COUNT(g.id) OVER (PARTITION BY ib.id_item)
                         ELSE 1.0
                       END AS peso_grupo,
                       ib.cantidad,
                       ib.precio_unitario,
                       ib.precio_real,
                       ib.tipo_origen_item,
                       ib.estatus_ejecucion
                FROM items_base ib
                LEFT JOIN grupos_base_raw g ON g.id_item = ib.id_item
            ),
            item_grupos_operativos AS (
                SELECT ib.id_item,
                       ib.id_item_origen,
                       ib.id_categoria AS categoria_id,
                       COALESCE(ib.categoria_nombre, 'Sin categoria') AS categoria_nombre,
                       COALESCE(go.codigo, gb.codigo, ib.seccion_bom, 'SIN_CLASIFICAR') AS grupo_codigo,
                       COALESCE(go.nombre, gb.nombre, ib.seccion_bom, 'Sin clasificar') AS grupo_nombre,
                       COALESCE(go.orden, gb.orden, 999) AS grupo_orden,
                       CASE
                         WHEN COUNT(COALESCE(go.id, gb.id)) OVER (PARTITION BY ib.id_item) > 0
                         THEN 1.0 / COUNT(COALESCE(go.id, gb.id)) OVER (PARTITION BY ib.id_item)
                         ELSE 1.0
                       END AS peso_grupo,
                       ib.cantidad,
                       ib.precio_unitario,
                       ib.precio_real,
                       ib.tipo_origen_item,
                       ib.estatus_ejecucion
                FROM items_base ib
                LEFT JOIN grupos_operativos_raw go ON go.id_item = ib.id_item
                LEFT JOIN grupos_base_raw gb
                    ON gb.id_item = ib.id_item
                   AND NOT EXISTS (
                       SELECT 1
                       FROM grupos_operativos_raw go_exists
                       WHERE go_exists.id_item = ib.id_item
                   )
            ),
            item_targets AS (
                SELECT id_item AS current_id, id_item AS target_id
                FROM items_base
                UNION ALL
                SELECT id_item AS current_id, id_item_origen AS target_id
                FROM items_base
                WHERE id_item_origen IS NOT NULL
            ),
            presupuesto AS (
                SELECT grupo_codigo, grupo_nombre, grupo_orden,
                       categoria_id, categoria_nombre,
                       SUM(
                           CASE WHEN tipo_origen_item = 'BASE'
                                THEN cantidad * precio_unitario * peso_grupo
                                ELSE 0 END
                       ) AS presupuesto_mxn
                FROM item_grupos_base
                GROUP BY grupo_codigo, grupo_nombre, grupo_orden, categoria_id, categoria_nombre
            ),
            compra_real AS (
                SELECT grupo_codigo, grupo_nombre, grupo_orden,
                       categoria_id, categoria_nombre,
                       SUM(cantidad * precio_real * peso_grupo) AS compra_real_mxn,
                       SUM(
                           CASE WHEN tipo_origen_item = 'BASE'
                                THEN cantidad * precio_real * peso_grupo
                                ELSE 0 END
                       ) AS compra_real_base_mxn,
                       SUM(
                           CASE WHEN tipo_origen_item = 'REEMPLAZO'
                                THEN cantidad * precio_real * peso_grupo
                                ELSE 0 END
                       ) AS reemplazos_mxn,
                       SUM(
                           CASE WHEN tipo_origen_item = 'FUERA_SCOPE'
                                THEN cantidad * precio_real * peso_grupo
                                ELSE 0 END
                       ) AS fuera_scope_mxn,
                       SUM(
                           CASE WHEN tipo_origen_item = 'BASE'
                                  AND estatus_ejecucion IN ('NO_ADQUIRIDO', 'REEMPLAZADO', 'CERRADO')
                                THEN cantidad * precio_unitario * peso_grupo
                                ELSE 0 END
                       ) AS no_adquirido_mxn
                FROM item_grupos_operativos
                GROUP BY grupo_codigo, grupo_nombre, grupo_orden, categoria_id, categoria_nombre
            ),
            facturado_confirmado AS (
                SELECT ig.grupo_codigo, ig.grupo_nombre, ig.grupo_orden,
                       ig.categoria_id, ig.categoria_nombre,
                       SUM(m.importe * COALESCE(m.tipo_cambio_xml, 1) * ig.peso_grupo) AS facturado_confirmado_mxn
                FROM item_grupos_operativos ig
                JOIN item_targets it ON it.current_id = ig.id_item
                JOIN tb_materiales_historial m ON m.id_bom_item = it.target_id
                GROUP BY ig.grupo_codigo, ig.grupo_nombre, ig.grupo_orden, ig.categoria_id, ig.categoria_nombre
            ),
            facturado_sugerido AS (
                SELECT ig.grupo_codigo, ig.grupo_nombre, ig.grupo_orden,
                       ig.categoria_id, ig.categoria_nombre,
                       SUM(m.importe * COALESCE(m.tipo_cambio_xml, 1) * ig.peso_grupo) AS facturado_sugerido_mxn
                FROM item_grupos_operativos ig
                JOIN item_targets it ON it.current_id = ig.id_item
                JOIN tb_materiales_historial m ON m.id_bom_item_sugerido = it.target_id
                WHERE m.id_bom_item IS NULL
                GROUP BY ig.grupo_codigo, ig.grupo_nombre, ig.grupo_orden, ig.categoria_id, ig.categoria_nombre
            ),
            coti_lineas AS (
                -- Una fila por linea de cotizacion (sin explotar por grupo): base del
                -- denominador de prorrateo para que items multi-grupo no lo inflen.
                SELECT a.id AS autorizacion_id, ci.subtotal_linea
                FROM tb_bom_autorizaciones a
                JOIN tb_bom_cotizacion_items ci ON ci.cotizacion_id = a.cotizacion_id
                JOIN items_base ib ON ib.id_item = ci.bom_item_id
                WHERE a.bom_id = $1
            ),
            coti_items AS (
                SELECT a.id AS autorizacion_id,
                       ci.subtotal_linea,
                       ig.grupo_codigo, ig.grupo_nombre, ig.grupo_orden,
                       ig.categoria_id, ig.categoria_nombre, ig.peso_grupo
                FROM tb_bom_autorizaciones a
                JOIN tb_bom_cotizacion_items ci ON ci.cotizacion_id = a.cotizacion_id
                JOIN item_grupos_operativos ig ON ig.id_item = ci.bom_item_id
                WHERE a.bom_id = $1
            ),
            pago_por_auth AS (
                SELECT p.autorizacion_id,
                       SUM(p.monto_pagado * COALESCE(p.tipo_cambio_usado, 1)) AS pagado_mxn
                FROM tb_bom_pagos p
                JOIN tb_bom_autorizaciones a ON a.id = p.autorizacion_id
                WHERE a.bom_id = $1
                GROUP BY p.autorizacion_id
            ),
            auth_totales AS (
                SELECT autorizacion_id,
                       NULLIF(SUM(subtotal_linea), 0) AS total_subtotal
                FROM coti_lineas
                GROUP BY autorizacion_id
            ),
            pagado AS (
                SELECT ci.grupo_codigo, ci.grupo_nombre, ci.grupo_orden,
                       ci.categoria_id, ci.categoria_nombre,
                       SUM(pa.pagado_mxn * (ci.subtotal_linea / at.total_subtotal) * ci.peso_grupo) AS pagado_mxn
                FROM coti_items ci
                JOIN pago_por_auth pa ON pa.autorizacion_id = ci.autorizacion_id
                JOIN auth_totales at ON at.autorizacion_id = ci.autorizacion_id
                WHERE at.total_subtotal IS NOT NULL
                GROUP BY ci.grupo_codigo, ci.grupo_nombre, ci.grupo_orden, ci.categoria_id, ci.categoria_nombre
            ),
            metricas AS (
                SELECT grupo_codigo, grupo_nombre, grupo_orden,
                       categoria_id, categoria_nombre,
                       presupuesto_mxn, 0::numeric AS facturado_confirmado_mxn,
                       0::numeric AS facturado_sugerido_mxn, 0::numeric AS pagado_mxn,
                       0::numeric AS compra_real_mxn,
                       0::numeric AS compra_real_base_mxn,
                       0::numeric AS reemplazos_mxn,
                       0::numeric AS fuera_scope_mxn,
                       0::numeric AS no_adquirido_mxn
                FROM presupuesto
                UNION ALL
                SELECT grupo_codigo, grupo_nombre, grupo_orden,
                       categoria_id, categoria_nombre,
                       0::numeric, 0::numeric, 0::numeric, 0::numeric,
                       compra_real_mxn, compra_real_base_mxn, reemplazos_mxn,
                       fuera_scope_mxn, no_adquirido_mxn
                FROM compra_real
                UNION ALL
                SELECT grupo_codigo, grupo_nombre, grupo_orden,
                       categoria_id, categoria_nombre,
                       0::numeric, facturado_confirmado_mxn, 0::numeric,
                       0::numeric, 0::numeric, 0::numeric, 0::numeric,
                       0::numeric, 0::numeric
                FROM facturado_confirmado
                UNION ALL
                SELECT grupo_codigo, grupo_nombre, grupo_orden,
                       categoria_id, categoria_nombre,
                       0::numeric, 0::numeric, facturado_sugerido_mxn,
                       0::numeric, 0::numeric, 0::numeric, 0::numeric,
                       0::numeric, 0::numeric
                FROM facturado_sugerido
                UNION ALL
                SELECT grupo_codigo, grupo_nombre, grupo_orden,
                       categoria_id, categoria_nombre,
                       0::numeric, 0::numeric, 0::numeric, pagado_mxn,
                       0::numeric, 0::numeric, 0::numeric, 0::numeric, 0::numeric
                FROM pagado
            )
            SELECT grupo_codigo,
                   grupo_nombre,
                   grupo_orden,
                   categoria_id,
                   categoria_nombre,
                   SUM(presupuesto_mxn) AS presupuesto_mxn,
                   SUM(facturado_confirmado_mxn) AS facturado_confirmado_mxn,
                   SUM(facturado_sugerido_mxn) AS facturado_sugerido_mxn,
                   SUM(pagado_mxn) AS pagado_mxn,
                   SUM(compra_real_mxn) AS compra_real_mxn,
                   SUM(compra_real_base_mxn) AS compra_real_base_mxn,
                   SUM(reemplazos_mxn) AS reemplazos_mxn,
                   SUM(fuera_scope_mxn) AS fuera_scope_mxn,
                   SUM(no_adquirido_mxn) AS no_adquirido_mxn
            FROM metricas
            GROUP BY grupo_codigo, grupo_nombre, grupo_orden, categoria_id, categoria_nombre
            HAVING SUM(presupuesto_mxn) <> 0
                OR SUM(facturado_confirmado_mxn) <> 0
                OR SUM(facturado_sugerido_mxn) <> 0
                OR SUM(pagado_mxn) <> 0
                OR SUM(compra_real_mxn) <> 0
                OR SUM(reemplazos_mxn) <> 0
                OR SUM(fuera_scope_mxn) <> 0
                OR SUM(no_adquirido_mxn) <> 0
            ORDER BY grupo_orden, grupo_codigo, categoria_nombre
        """, id_bom)
        return [dict(r) for r in rows]

    async def get_divisores_bom(self, conn, id_bom: UUID) -> dict:
        """Divisores para métricas normalizadas: kWp de cierre FV y módulos FV del BOM.

        - kwp: potencia de cierre FV de la oportunidad ligada al proyecto del BOM.
        - modulos_fv: suma de cantidades de items activos en la categoria Panel.
        """
        row = await conn.fetchrow("""
            SELECT
                (SELECT o.potencia_cierre_fv_kwp
                   FROM tb_bom b
                   JOIN tb_proyectos_gate g ON g.id_proyecto = b.id_proyecto
                   JOIN tb_oportunidades o ON o.id_oportunidad = g.id_oportunidad
                   WHERE b.id_bom = $1) AS kwp,
                (SELECT SUM(i.cantidad)
                   FROM tb_bom_items i
                   JOIN tb_cat_categorias_compra c ON c.id = i.id_categoria
                   WHERE i.id_bom = $1
                     AND i.activo = TRUE
                     AND COALESCE(i.tipo_origen_item, 'BASE') = 'BASE'
                     AND lower(c.nombre) = 'panel') AS modulos_fv
        """, id_bom)
        return {
            "kwp": float(row["kwp"]) if row and row["kwp"] is not None else None,
            "modulos_fv": float(row["modulos_fv"]) if row and row["modulos_fv"] is not None else None,
        }

    # ─── COMPARATIVA RFQ (Gap 7d) ───────────────────────────

    async def get_rfqs_by_bom(self, conn, id_bom: UUID) -> list:
        """RFQs activos de un BOM."""
        rows = await conn.fetch("""
            SELECT c.*, u.nombre AS creado_por_nombre
            FROM tb_bom_cotizaciones c
            LEFT JOIN tb_usuarios u ON u.id_usuario = c.creado_por
            WHERE c.bom_id = $1 AND c.es_rfq = TRUE
            ORDER BY c.creado_en DESC
        """, id_bom)
        return [dict(r) for r in rows]

    async def get_rfq_responses(self, conn, rfq_id: UUID) -> list:
        """Cotizaciones de proveedores que respondieron a un RFQ."""
        rows = await conn.fetch("""
            SELECT c.*, u.nombre AS creado_por_nombre
            FROM tb_bom_cotizaciones c
            LEFT JOIN tb_usuarios u ON u.id_usuario = c.creado_por
            WHERE c.rfq_origen_id = $1 AND c.es_rfq = FALSE
            ORDER BY c.creado_en DESC
        """, rfq_id)
        return [dict(r) for r in rows]

    async def bulk_replace_cotizacion_items(
        self, conn, cotizacion_id: UUID, items: list
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
                    (cotizacion_id, bom_item_id, precio_unitario, cantidad, moneda, subtotal_linea)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (cotizacion_id, bom_item_id) DO NOTHING
            """, [
                (cotizacion_id, i['bom_item_id'], i.get('precio_unitario'),
                 i.get('cantidad', 1), i.get('moneda', 'MXN'),
                 i.get('subtotal_linea', 0))
                for i in merged
            ])
