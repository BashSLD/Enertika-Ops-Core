-- Separa sugerencias del matcher BOM de la liga real que cuenta como facturado.

ALTER TABLE tb_materiales_historial
    ADD COLUMN IF NOT EXISTS id_bom_item_sugerido UUID;

ALTER TABLE tb_materiales_historial
    ADD COLUMN IF NOT EXISTS sugerencia_confianza VARCHAR(10);

ALTER TABLE tb_materiales_historial
    ADD COLUMN IF NOT EXISTS sugerencia_origen VARCHAR(20);

DO $$
BEGIN
    ALTER TABLE tb_materiales_historial
        ADD CONSTRAINT tb_materiales_historial_bom_item_sugerido_fkey
        FOREIGN KEY (id_bom_item_sugerido)
        REFERENCES tb_bom_items(id_item)
        ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_materiales_historial_bom_item_sugerido
    ON tb_materiales_historial (id_bom_item_sugerido);
