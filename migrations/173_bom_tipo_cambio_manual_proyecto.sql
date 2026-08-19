-- Plan: TC (tipo de cambio) manual a nivel proyecto en BOM.
-- El CEO (director/ADMIN) puede fijar un TC manual que sustituye Banxico/promedio en las
-- vistas "en curso" y, si esta vigente, se usa para congelar tipo_cambio_aprobacion al
-- aprobar. No toca autorizado/facturado/pagado (fuentes transaccionales propias).

ALTER TABLE tb_bom_proyecto_estado
    ADD COLUMN IF NOT EXISTS tipo_cambio_manual NUMERIC(10, 4);
ALTER TABLE tb_bom_proyecto_estado
    ADD COLUMN IF NOT EXISTS tipo_cambio_manual_fijado_por UUID REFERENCES tb_usuarios(id_usuario);
ALTER TABLE tb_bom_proyecto_estado
    ADD COLUMN IF NOT EXISTS tipo_cambio_manual_fijado_en TIMESTAMPTZ;

ALTER TABLE tb_bom_proyecto_estado
    DROP CONSTRAINT IF EXISTS tb_bom_proyecto_estado_tipo_cambio_manual_check;
ALTER TABLE tb_bom_proyecto_estado
    ADD CONSTRAINT tb_bom_proyecto_estado_tipo_cambio_manual_check
    CHECK (tipo_cambio_manual IS NULL OR tipo_cambio_manual > 0);
