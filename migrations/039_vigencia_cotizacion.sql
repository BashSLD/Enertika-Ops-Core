-- Migración 039: vigencia_cotizacion_dias en cotizaciones + config global default
-- Idempotente

ALTER TABLE tb_calculadora_cotizaciones
    ADD COLUMN IF NOT EXISTS vigencia_cotizacion_dias INTEGER;

INSERT INTO tb_configuracion_global (clave, valor, descripcion, tipo_dato)
VALUES ('calc_poliza_vigencia_dias', '30', 'Vigencia default de propuesta de poliza OyM (dias)', 'int')
ON CONFLICT (clave) DO NOTHING;
