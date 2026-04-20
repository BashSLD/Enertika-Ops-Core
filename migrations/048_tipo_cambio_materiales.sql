-- Migración 048: tipo de cambio por ítem en historial de materiales
-- Permite calcular costo real en MXN de cada material según el TC de la factura XML

ALTER TABLE tb_materiales_historial
    ADD COLUMN IF NOT EXISTS tipo_cambio_xml NUMERIC(15,6);
