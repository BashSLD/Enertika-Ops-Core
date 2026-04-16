-- 041: Marca las cotizaciones creadas por importacion de Excel como legacy
-- Es_legacy = TRUE: montos en cero, no aparece en calculadora, solo sirve para
-- mantener la continuidad del ciclo (vigencia + renovacion desde OyM)

ALTER TABLE tb_calculadora_cotizaciones
    ADD COLUMN IF NOT EXISTS es_legacy BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_cotizaciones_es_legacy
    ON tb_calculadora_cotizaciones (es_legacy)
    WHERE es_legacy = TRUE;
