-- Migration 061: BOM versionado — trazabilidad entre versiones (Gap 10)
-- Agrega id_item_origen (FK a sí mismo) y bloqueado a tb_bom_items.
-- Permite rastrear qué item de v2 vino de qué item de v1.
-- Items FACTURADOS/PAGADOS se bloquean en nuevas versiones.
-- Idempotente: ADD COLUMN IF NOT EXISTS, DO $$ para FK.

ALTER TABLE tb_bom_items
    ADD COLUMN IF NOT EXISTS id_item_origen UUID;

ALTER TABLE tb_bom_items
    ADD COLUMN IF NOT EXISTS bloqueado BOOLEAN DEFAULT FALSE;

DO $$ BEGIN
    ALTER TABLE tb_bom_items
        ADD CONSTRAINT fk_bom_items_origen
        FOREIGN KEY (id_item_origen) REFERENCES tb_bom_items(id_item) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_bom_items_origen ON tb_bom_items(id_item_origen);
