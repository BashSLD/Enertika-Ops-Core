-- Migración 036: Campos de renovación y vigencia para calculadora de pólizas
-- Ejecutar ANTES de desplegar el código que depende de estos campos

-- 1. Planta: indicar si fue instalada por Enertika o es de terceros
ALTER TABLE tb_calculadora_plantas
    ADD COLUMN IF NOT EXISTS es_externa BOOLEAN NOT NULL DEFAULT FALSE;

-- 2. Cotización: fechas de vigencia de la póliza (inicio/fin del contrato)
ALTER TABLE tb_calculadora_cotizaciones
    ADD COLUMN IF NOT EXISTS fecha_inicio_poliza DATE,
    ADD COLUMN IF NOT EXISTS fecha_fin_poliza DATE;

-- 3. Cotización: trazabilidad de renovación
--    poliza_anterior_id -> referencia a la cotización previa (si está en el sistema)
--    fecha_fin_poliza_anterior -> vencimiento manual de la póliza previa (para pólizas pre-sistema)
ALTER TABLE tb_calculadora_cotizaciones
    ADD COLUMN IF NOT EXISTS poliza_anterior_id UUID REFERENCES tb_calculadora_cotizaciones(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS fecha_fin_poliza_anterior DATE;

-- Índice para búsquedas de renovaciones encadenadas
CREATE INDEX IF NOT EXISTS idx_cotizaciones_anterior
    ON tb_calculadora_cotizaciones(poliza_anterior_id)
    WHERE poliza_anterior_id IS NOT NULL;
