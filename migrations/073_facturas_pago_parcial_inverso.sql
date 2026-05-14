-- Soporta aplicar una misma factura a varios comprobantes de pago.
-- El total del CFDI queda en monto; monto_aplicado representa cuanto cubre
-- este comprobante especifico.

ALTER TABLE tb_comprobante_facturas
ADD COLUMN IF NOT EXISTS monto_aplicado NUMERIC(14,2);

UPDATE tb_comprobante_facturas
SET monto_aplicado = COALESCE(monto_aplicado, monto, 0)
WHERE monto_aplicado IS NULL;

ALTER TABLE tb_comprobante_facturas
ALTER COLUMN monto_aplicado SET DEFAULT 0,
ALTER COLUMN monto_aplicado SET NOT NULL;

UPDATE tb_comprobantes_pago cp
SET monto_facturado = COALESCE((
    SELECT SUM(COALESCE(cf.monto_aplicado, cf.monto, 0))
    FROM tb_comprobante_facturas cf
    WHERE cf.id_comprobante = cp.id_comprobante
), 0)
WHERE EXISTS (
    SELECT 1
    FROM tb_comprobante_facturas cf
    WHERE cf.id_comprobante = cp.id_comprobante
);
