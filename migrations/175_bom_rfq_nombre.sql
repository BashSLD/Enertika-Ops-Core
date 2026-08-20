-- Nombre editable del RFQ (doc guia post-BOM 2026-08-19): Compras lo captura al crear
-- el RFQ, Finanzas lo usa para identificarlo en su vista de solo lectura.
ALTER TABLE tb_bom_rfq ADD COLUMN IF NOT EXISTS nombre TEXT;
