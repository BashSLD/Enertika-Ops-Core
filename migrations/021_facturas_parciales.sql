-- Migración 021: Soporte de facturas parciales y cierre de remanente
-- Fecha: 2026-03-17
--
-- Cambios:
-- 1. Agrega monto_facturado (acumulado de facturas vinculadas)
-- 2. Agrega campos de cierre de remanente (monto_remanente, motivo_cierre, cerrado_por_id, cerrado_at)
-- 3. Amplía constraint de estatus para incluir PARCIALMENTE_FACTURADO y CERRADO
-- 4. Backfill de monto_facturado para registros existentes
-- 5. Índice parcial para búsqueda de comprobantes con saldo pendiente

-- 1. Campos nuevos en tb_comprobantes_pago
ALTER TABLE tb_comprobantes_pago
    ADD COLUMN IF NOT EXISTS monto_facturado  NUMERIC(12,2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS monto_remanente  NUMERIC(12,2),
    ADD COLUMN IF NOT EXISTS motivo_cierre    TEXT,
    ADD COLUMN IF NOT EXISTS cerrado_por_id   UUID REFERENCES tb_usuarios(id_usuario),
    ADD COLUMN IF NOT EXISTS cerrado_at       TIMESTAMPTZ;

-- 2. Ampliar constraint de estatus
DO $$
BEGIN
    ALTER TABLE tb_comprobantes_pago
        DROP CONSTRAINT IF EXISTS tb_comprobantes_pago_estatus_check;
    ALTER TABLE tb_comprobantes_pago
        ADD CONSTRAINT tb_comprobantes_pago_estatus_check
        CHECK (estatus IN ('PENDIENTE', 'FACTURADO', 'ANTICIPO', 'PARCIALMENTE_FACTURADO', 'CERRADO'));
EXCEPTION WHEN others THEN
    NULL;
END $$;

-- 3. Backfill: sincronizar monto_facturado con lo que ya existe en tb_comprobante_facturas
UPDATE tb_comprobantes_pago cp
SET monto_facturado = COALESCE((
    SELECT SUM(cf.monto)
    FROM tb_comprobante_facturas cf
    WHERE cf.id_comprobante = cp.id_comprobante
), 0)
WHERE cp.estatus IN ('FACTURADO', 'ANTICIPO');

-- 4. Índice para búsqueda eficiente de comprobantes con saldo pendiente (PARCIAL_MATCH)
CREATE INDEX IF NOT EXISTS idx_comprobantes_parcial_proveedor
    ON tb_comprobantes_pago(id_proveedor, moneda, estatus)
    WHERE estatus IN ('PENDIENTE', 'PARCIALMENTE_FACTURADO');
