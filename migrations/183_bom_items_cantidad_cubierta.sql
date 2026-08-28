-- Migración 183: Soporte de cobertura parcial en cotización de ítems BOM
-- Fecha: 2026-08-28
--
-- Cambios:
-- 1. Agrega tb_bom_items.cantidad_cubierta (acumulado adjudicado entre cotizaciones)
-- 2. Backfill: items ya cerrados en compra quedan 100% cubiertos
-- 3. CHECK de rango para cantidad_cubierta
-- 4. Amplía constraint de estatus_compra (tb_bom_items) y estatus_ejecucion
--    (tb_bom_item_ejecucion) para incluir PARCIALMENTE_COTIZADO

-- 1. Campo nuevo en tb_bom_items
ALTER TABLE tb_bom_items
    ADD COLUMN IF NOT EXISTS cantidad_cubierta NUMERIC(14,4) NOT NULL DEFAULT 0;

-- 2. Backfill: items ya en un estatus terminal de compra ya estaban 100% cubiertos
UPDATE tb_bom_items
SET cantidad_cubierta = cantidad
WHERE estatus_compra IN ('COTIZADO', 'AUTORIZADO', 'PAGADO', 'FACTURADO');

-- 3. CHECK de rango: 0 <= cantidad_cubierta <= cantidad
DO $$
BEGIN
    ALTER TABLE tb_bom_items
        DROP CONSTRAINT IF EXISTS tb_bom_items_cantidad_cubierta_check;
    ALTER TABLE tb_bom_items
        ADD CONSTRAINT tb_bom_items_cantidad_cubierta_check
        CHECK (cantidad_cubierta >= 0 AND cantidad_cubierta <= cantidad);
EXCEPTION WHEN others THEN
    NULL;
END $$;

-- 4. Ampliar CHECK de estatus_compra en tb_bom_items
DO $$
BEGIN
    ALTER TABLE tb_bom_items
        DROP CONSTRAINT IF EXISTS tb_bom_items_estatus_compra_check;
    ALTER TABLE tb_bom_items
        ADD CONSTRAINT tb_bom_items_estatus_compra_check
        CHECK (estatus_compra IN (
            'SIN_COTIZAR', 'PARCIALMENTE_COTIZADO', 'COTIZADO',
            'AUTORIZADO', 'PAGADO', 'FACTURADO'
        ));
EXCEPTION WHEN others THEN
    NULL;
END $$;

-- 5. Ampliar CHECK de estatus_ejecucion en tb_bom_item_ejecucion (espejo 1:1)
DO $$
BEGIN
    ALTER TABLE tb_bom_item_ejecucion
        DROP CONSTRAINT IF EXISTS tb_bom_item_ejecucion_estatus_check;
    ALTER TABLE tb_bom_item_ejecucion
        ADD CONSTRAINT tb_bom_item_ejecucion_estatus_check
        CHECK (estatus_ejecucion IN (
            'PENDIENTE', 'SIN_COTIZAR', 'PARCIALMENTE_COTIZADO', 'COTIZADO',
            'AUTORIZADO', 'COMPRADO', 'FACTURADO', 'PAGADO',
            'RECIBIDO_PARCIAL', 'RECIBIDO_TOTAL', 'NO_ADQUIRIDO',
            'REEMPLAZADO', 'CERRADO'
        ));
EXCEPTION WHEN others THEN
    NULL;
END $$;
