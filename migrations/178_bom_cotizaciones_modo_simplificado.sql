-- Persiste si una cotizacion se creo en modo simplificado ("Capturar solo el
-- total") para poder restaurar ese modo al editarla, en vez de siempre abrir
-- el modal de edicion en modo detallado (precio por item).

ALTER TABLE tb_bom_cotizaciones
    ADD COLUMN IF NOT EXISTS modo_simplificado BOOLEAN NOT NULL DEFAULT FALSE;
