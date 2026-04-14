-- Migración 037: Años contratados en cotizaciones de póliza
-- Se captura al momento de marcar la cotización como ACEPTADA

ALTER TABLE tb_calculadora_cotizaciones
    ADD COLUMN IF NOT EXISTS anios_contratados INTEGER;
