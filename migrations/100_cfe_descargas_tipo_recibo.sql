-- Agrega el tipo de recibo/tarifa CFE detectado desde XML para mostrarlo en el historial.

ALTER TABLE tb_cfe_descargas
ADD COLUMN IF NOT EXISTS tipo_recibo TEXT;

COMMENT ON COLUMN tb_cfe_descargas.tipo_recibo IS
    'Tipo de recibo/tarifa detectado desde el XML CFE, por ejemplo GDMTO o GDMTH.';
