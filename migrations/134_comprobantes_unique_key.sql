-- Migracion 134: unique key para comprobantes de compras.
-- Previene duplicados concurrentes del mismo comprobante sin afectar comprobantes BOM.

CREATE UNIQUE INDEX IF NOT EXISTS uq_comprobante_duplicado_no_bom
    ON public.tb_comprobantes_pago (fecha_pago, beneficiario_orig, monto)
    WHERE id_bom_pago IS NULL;
