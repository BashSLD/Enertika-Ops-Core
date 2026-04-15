-- Migración 038: Descuentos por año independientes en tb_calculadora_cotizaciones
-- Agrega tres columnas de porcentaje de descuento, una por opción de contrato.
-- Las columnas antiguas (descuento_pct, descuento_anios) se mantienen para
-- compatibilidad con cotizaciones existentes.

ALTER TABLE tb_calculadora_cotizaciones
    ADD COLUMN IF NOT EXISTS descuento_pct_1 NUMERIC(5,4) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS descuento_pct_3 NUMERIC(5,4) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS descuento_pct_5 NUMERIC(5,4) DEFAULT NULL;

COMMENT ON COLUMN tb_calculadora_cotizaciones.descuento_pct_1 IS 'Descuento para contrato de 1 año (0.1000 = 10%)';
COMMENT ON COLUMN tb_calculadora_cotizaciones.descuento_pct_3 IS 'Descuento para contrato de 3 años (0.1000 = 10%)';
COMMENT ON COLUMN tb_calculadora_cotizaciones.descuento_pct_5 IS 'Descuento para contrato de 5 años (0.1000 = 10%)';
