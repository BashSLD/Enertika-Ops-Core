-- Fase 4 doc 33: visibilidad de comprobantes BOM (Finanzas) en Compras via asignacion explicita

ALTER TABLE tb_comprobantes_pago
    ADD COLUMN IF NOT EXISTS asignado_compras_id UUID REFERENCES tb_usuarios(id_usuario);

CREATE INDEX IF NOT EXISTS idx_comprobantes_asignado_compras
    ON tb_comprobantes_pago(asignado_compras_id);
