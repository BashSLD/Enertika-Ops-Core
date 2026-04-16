-- Migracion 045: Hardening de indice de duplicados en comprobantes
-- Cubre entornos donde el objeto previo exista como constraint o como index.

ALTER TABLE tb_comprobantes_pago
    DROP CONSTRAINT IF EXISTS uq_comprobante_duplicado;

DROP INDEX IF EXISTS uq_comprobante_duplicado;

CREATE UNIQUE INDEX IF NOT EXISTS uq_comprobante_duplicado_no_bom
    ON tb_comprobantes_pago (fecha_pago, beneficiario_orig, monto)
    WHERE id_bom_pago IS NULL;
