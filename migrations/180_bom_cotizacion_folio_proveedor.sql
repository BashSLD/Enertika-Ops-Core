-- Mueve el folio/referencia del proveedor del RFQ a la cotizacion: cada proveedor que responde
-- tiene su propio folio (para conciliar despues contra su factura), no el RFQ en si.

ALTER TABLE tb_bom_cotizaciones ADD COLUMN IF NOT EXISTS folio_proveedor TEXT;

ALTER TABLE tb_bom_rfq DROP COLUMN IF EXISTS folio_proveedor;
