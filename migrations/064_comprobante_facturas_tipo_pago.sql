-- Agrega 'PAGO' (CFDI complemento de pago, TipoDeComprobante=P) al check constraint
-- de tb_comprobante_facturas. El tipo fue agregado al enum TipoFactura pero la
-- constraint de BD no se actualizó en su momento.

ALTER TABLE tb_comprobante_facturas
    DROP CONSTRAINT IF EXISTS tb_comprobante_facturas_tipo_check;

ALTER TABLE tb_comprobante_facturas
    ADD CONSTRAINT tb_comprobante_facturas_tipo_check
    CHECK (tipo = ANY (ARRAY[
        'NORMAL'::text,
        'ANTICIPO'::text,
        'CIERRE_ANTICIPO'::text,
        'NOTA_CREDITO'::text,
        'PAGO'::text
    ]));
