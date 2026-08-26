-- Folio/referencia que el proveedor asigna a su cotizacion, para conciliar despues contra la factura.

ALTER TABLE tb_bom_rfq ADD COLUMN IF NOT EXISTS folio_proveedor TEXT;
