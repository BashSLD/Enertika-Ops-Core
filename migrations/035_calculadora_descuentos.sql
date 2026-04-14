-- Migración 035: Descuentos por cotización en calculadora de pólizas
-- Agrega campos para almacenar el porcentaje de descuento y los años donde aplica.
-- Ambos son opcionales (NULL = sin descuento).

ALTER TABLE tb_calculadora_cotizaciones
    ADD COLUMN IF NOT EXISTS descuento_pct   NUMERIC(5,4) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS descuento_anios SMALLINT[]   DEFAULT NULL;

COMMENT ON COLUMN tb_calculadora_cotizaciones.descuento_pct   IS 'Porcentaje de descuento aplicado (ej: 0.1000 = 10%). NULL = sin descuento.';
COMMENT ON COLUMN tb_calculadora_cotizaciones.descuento_anios IS 'Años de contrato donde aplica el descuento (ej: ARRAY[3,5]). NULL = sin descuento.';
