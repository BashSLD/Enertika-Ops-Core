-- Separa la linea base del BOM de la ejecucion real de compra y recepcion.

CREATE TABLE IF NOT EXISTS tb_bom_item_ejecucion (
    id_item UUID PRIMARY KEY REFERENCES tb_bom_items(id_item) ON DELETE CASCADE,
    id_proveedor_real UUID REFERENCES tb_proveedores(id_proveedor),
    precio_real NUMERIC(14,4),
    moneda_real VARCHAR(3),
    cantidad_recibida NUMERIC(14,4) NOT NULL DEFAULT 0,
    fecha_estimada_entrega DATE,
    fecha_llegada_real DATE,
    tipo_entrega VARCHAR(50),
    estatus_ejecucion VARCHAR(30) NOT NULL DEFAULT 'PENDIENTE',
    comentarios_operativos TEXT,
    updated_by UUID REFERENCES tb_usuarios(id_usuario),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT tb_bom_item_ejecucion_precio_real_check
        CHECK (precio_real IS NULL OR precio_real >= 0),
    CONSTRAINT tb_bom_item_ejecucion_cantidad_recibida_check
        CHECK (cantidad_recibida >= 0),
    CONSTRAINT tb_bom_item_ejecucion_moneda_real_check
        CHECK (moneda_real IS NULL OR moneda_real IN ('MXN', 'USD')),
    CONSTRAINT tb_bom_item_ejecucion_estatus_check
        CHECK (estatus_ejecucion IN (
            'PENDIENTE',
            'SIN_COTIZAR',
            'COTIZADO',
            'AUTORIZADO',
            'COMPRADO',
            'FACTURADO',
            'PAGADO',
            'RECIBIDO_PARCIAL',
            'RECIBIDO_TOTAL',
            'NO_ADQUIRIDO',
            'REEMPLAZADO',
            'CERRADO'
        ))
);

CREATE INDEX IF NOT EXISTS idx_bom_item_ejecucion_estatus
    ON tb_bom_item_ejecucion(estatus_ejecucion);

CREATE INDEX IF NOT EXISTS idx_bom_item_ejecucion_proveedor
    ON tb_bom_item_ejecucion(id_proveedor_real)
    WHERE id_proveedor_real IS NOT NULL;

INSERT INTO tb_bom_item_ejecucion (
    id_item,
    id_proveedor_real,
    cantidad_recibida,
    fecha_estimada_entrega,
    fecha_llegada_real,
    tipo_entrega,
    estatus_ejecucion,
    created_at,
    updated_at
)
SELECT
    i.id_item,
    i.id_proveedor,
    COALESCE(i.cantidad_recibida, 0),
    i.fecha_estimada_entrega,
    i.fecha_llegada_real,
    i.tipo_entrega,
    CASE
        WHEN COALESCE(i.cantidad_recibida, 0) >= i.cantidad AND i.cantidad > 0
            THEN 'RECIBIDO_TOTAL'
        WHEN COALESCE(i.cantidad_recibida, 0) > 0
            THEN 'RECIBIDO_PARCIAL'
        WHEN i.estatus_compra IN ('COTIZADO', 'AUTORIZADO', 'FACTURADO', 'PAGADO')
            THEN i.estatus_compra
        ELSE 'PENDIENTE'
    END,
    NOW(),
    NOW()
FROM tb_bom_items i
ON CONFLICT (id_item) DO NOTHING;

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
            WHEN c.estatus = 'SELECCIONADA'
                THEN 'COTIZADO'
            ELSE 'PENDIENTE'
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
)
UPDATE tb_bom_item_ejecucion e
SET precio_real = cr.precio_unitario,
    moneda_real = cr.moneda,
    id_proveedor_real = cr.proveedor_id,
    estatus_ejecucion = cr.estatus_ejecucion,
    updated_at = NOW()
FROM cotizacion_real cr
WHERE cr.rn = 1
  AND e.id_item = cr.bom_item_id
  AND (
      e.precio_real IS DISTINCT FROM cr.precio_unitario
      OR e.moneda_real IS DISTINCT FROM cr.moneda
      OR e.id_proveedor_real IS DISTINCT FROM cr.proveedor_id
      OR e.estatus_ejecucion IS DISTINCT FROM cr.estatus_ejecucion
  );
