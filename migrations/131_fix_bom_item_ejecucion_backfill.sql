-- Corrige el backfill inicial: el costo real solo debe venir de cotizaciones
-- seleccionadas o autorizadas, no de respuestas RFQ recibidas sin seleccionar.

WITH cotizacion_real AS (
    SELECT
        ci.bom_item_id,
        c.proveedor_id,
        ci.precio_unitario,
        COALESCE(ci.moneda, c.moneda) AS moneda,
        CASE
            WHEN EXISTS (
                SELECT 1
                FROM tb_bom_autorizaciones a
                WHERE a.cotizacion_id = c.id
                  AND a.estatus IN (
                      'AUTORIZADO_OBRA',
                      'AUTORIZADO_DIRECCION',
                      'AUTORIZADO_FINANZAS'
                  )
            )
                THEN 'AUTORIZADO'
            ELSE 'COTIZADO'
        END AS estatus_ejecucion,
        ROW_NUMBER() OVER (
            PARTITION BY ci.bom_item_id
            ORDER BY COALESCE(c.actualizado_en, c.creado_en) DESC
        ) AS rn
    FROM tb_bom_cotizacion_items ci
    JOIN tb_bom_cotizaciones c ON c.id = ci.cotizacion_id
    WHERE ci.precio_unitario IS NOT NULL
      AND (
          c.estatus = 'SELECCIONADA'
          OR EXISTS (
              SELECT 1
              FROM tb_bom_autorizaciones a
              WHERE a.cotizacion_id = c.id
                AND a.estatus IN (
                    'AUTORIZADO_OBRA',
                    'AUTORIZADO_DIRECCION',
                    'AUTORIZADO_FINANZAS'
                )
          )
      )
),
cotizacion_real_ranked AS (
    SELECT *
    FROM cotizacion_real
    WHERE rn = 1
)
UPDATE tb_bom_item_ejecucion e
SET precio_real = cr.precio_unitario,
    moneda_real = cr.moneda,
    id_proveedor_real = cr.proveedor_id,
    estatus_ejecucion = cr.estatus_ejecucion,
    updated_at = NOW()
FROM cotizacion_real_ranked cr
WHERE e.id_item = cr.bom_item_id
  AND (
      e.precio_real IS DISTINCT FROM cr.precio_unitario
      OR e.moneda_real IS DISTINCT FROM cr.moneda
      OR e.id_proveedor_real IS DISTINCT FROM cr.proveedor_id
      OR e.estatus_ejecucion IS DISTINCT FROM cr.estatus_ejecucion
  );

WITH items_sin_cotizacion_real AS (
    SELECT
        e.id_item,
        i.id_proveedor,
        CASE
            WHEN COALESCE(i.cantidad_recibida, 0) >= i.cantidad AND i.cantidad > 0
                THEN 'RECIBIDO_TOTAL'
            WHEN COALESCE(i.cantidad_recibida, 0) > 0
                THEN 'RECIBIDO_PARCIAL'
            WHEN i.estatus_compra IN ('COTIZADO', 'AUTORIZADO', 'FACTURADO', 'PAGADO')
                THEN i.estatus_compra
            ELSE 'PENDIENTE'
        END AS estatus_base
    FROM tb_bom_item_ejecucion e
    JOIN tb_bom_items i ON i.id_item = e.id_item
    WHERE e.updated_by IS NULL
      AND NOT EXISTS (
          SELECT 1
          FROM tb_bom_cotizacion_items ci
          JOIN tb_bom_cotizaciones c ON c.id = ci.cotizacion_id
          WHERE ci.bom_item_id = e.id_item
            AND ci.precio_unitario IS NOT NULL
            AND (
                c.estatus = 'SELECCIONADA'
                OR EXISTS (
                    SELECT 1
                    FROM tb_bom_autorizaciones a
                    WHERE a.cotizacion_id = c.id
                      AND a.estatus IN (
                          'AUTORIZADO_OBRA',
                          'AUTORIZADO_DIRECCION',
                          'AUTORIZADO_FINANZAS'
                      )
                )
            )
      )
)
UPDATE tb_bom_item_ejecucion e
SET precio_real = NULL,
    moneda_real = NULL,
    id_proveedor_real = iscr.id_proveedor,
    estatus_ejecucion = iscr.estatus_base,
    updated_at = NOW()
FROM items_sin_cotizacion_real iscr
WHERE e.id_item = iscr.id_item
  AND (
      e.precio_real IS NOT NULL
      OR e.moneda_real IS NOT NULL
      OR e.id_proveedor_real IS DISTINCT FROM iscr.id_proveedor
      OR e.estatus_ejecucion IS DISTINCT FROM iscr.estatus_base
  );
