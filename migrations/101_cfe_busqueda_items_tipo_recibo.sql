-- Guarda el tipo de recibo/tarifa CFE detectado del XML en cada item de busqueda,
-- para mostrarlo en los resultados antes de conservar (igual que tb_cfe_descargas.tipo_recibo).

ALTER TABLE tb_cfe_busqueda_items
ADD COLUMN IF NOT EXISTS tipo_recibo TEXT;

COMMENT ON COLUMN tb_cfe_busqueda_items.tipo_recibo IS
    'Tipo de recibo/tarifa detectado desde el XML CFE staged, por ejemplo GDMTO o GDMTH.';
