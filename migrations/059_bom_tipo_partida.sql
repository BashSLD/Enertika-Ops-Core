-- Migration 059: BOM tipo_partida — amplía alcance del BOM
-- Agrega tipo_partida a tb_bom_items: MATERIAL, MANO_OBRA, SERVICIO, LEGALIZACION, EQUIPO.
-- Idempotente: ADD COLUMN IF NOT EXISTS, DROP IF EXISTS para constraint.

ALTER TABLE tb_bom_items
    ADD COLUMN IF NOT EXISTS tipo_partida VARCHAR(30) DEFAULT 'MATERIAL';

ALTER TABLE tb_bom_items DROP CONSTRAINT IF EXISTS tb_bom_items_tipo_partida_check;
ALTER TABLE tb_bom_items ADD CONSTRAINT tb_bom_items_tipo_partida_check
    CHECK (tipo_partida IN ('MATERIAL', 'MANO_OBRA', 'SERVICIO', 'LEGALIZACION', 'EQUIPO'));
