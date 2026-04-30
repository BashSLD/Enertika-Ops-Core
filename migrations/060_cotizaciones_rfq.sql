-- Migration 060: Cotizaciones — RFQ + flujo simplificado (Gap 7)
-- Agrega es_rfq, rfq_origen_id, comentarios_revision a tb_bom_cotizaciones.
-- Permite crear RFQ (solicitudes sin precios) y cotizaciones con solo subtotal.
-- Idempotente: IF NOT EXISTS / DO $$ para constraints.

-- 1. Columnas nuevas en tb_bom_cotizaciones
ALTER TABLE tb_bom_cotizaciones
    ADD COLUMN IF NOT EXISTS es_rfq BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS rfq_origen_id UUID,
    ADD COLUMN IF NOT EXISTS comentarios_revision TEXT;

-- 2. FK para rfq_origen_id (referencia al RFQ del que deriva esta cotización)
DO $$ BEGIN
    ALTER TABLE tb_bom_cotizaciones
        ADD CONSTRAINT fk_cotizacion_rfq_origen
        FOREIGN KEY (rfq_origen_id) REFERENCES tb_bom_cotizaciones(id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- 3. Índice para búsquedas por RFQ origen
CREATE INDEX IF NOT EXISTS idx_cotizaciones_rfq_origen ON tb_bom_cotizaciones(rfq_origen_id);
