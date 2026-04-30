-- Migration 058: Link tb_materiales_historial → tb_bom_items + ampliar estatus_compra
-- Agrega id_bom_item para trazabilidad bidireccional BOM↔Compras.
-- Expande CHECK de estatus_compra para incluir PAGADO y FACTURADO.
-- Idempotente: IF NOT EXISTS / DROP IF EXISTS para constraints.

-- 1. Columna id_bom_item en tb_materiales_historial (link al item del BOM)
ALTER TABLE tb_materiales_historial
    ADD COLUMN IF NOT EXISTS id_bom_item UUID;

ALTER TABLE tb_materiales_historial
    DROP CONSTRAINT IF EXISTS fk_materiales_bom_item;
ALTER TABLE tb_materiales_historial
    ADD CONSTRAINT fk_materiales_bom_item
    FOREIGN KEY (id_bom_item) REFERENCES tb_bom_items(id_item) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_materiales_bom_item
    ON tb_materiales_historial(id_bom_item);

-- 2. Ampliar CHECK de estatus_compra en tb_bom_items
ALTER TABLE tb_bom_items DROP CONSTRAINT IF EXISTS tb_bom_items_estatus_compra_check;
ALTER TABLE tb_bom_items ADD CONSTRAINT tb_bom_items_estatus_compra_check
    CHECK (estatus_compra IN ('SIN_COTIZAR', 'COTIZADO', 'AUTORIZADO', 'PAGADO', 'FACTURADO'));
