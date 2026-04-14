-- 033_calculadora_cotizaciones_updated_at.sql
-- Agrega updated_at a tb_calculadora_cotizaciones para trazabilidad de ediciones

ALTER TABLE tb_calculadora_cotizaciones
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;
