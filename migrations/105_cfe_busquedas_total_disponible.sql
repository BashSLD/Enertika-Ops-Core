-- migrations/105_cfe_busquedas_total_disponible.sql
-- Guarda cuantos recibos hay realmente disponibles en cada fuente (sin capar a
-- max_periodos) para informar al usuario en los resultados de la busqueda.

ALTER TABLE tb_cfe_busquedas
    ADD COLUMN IF NOT EXISTS total_disponible_publico INTEGER;

ALTER TABLE tb_cfe_busquedas
    ADD COLUMN IF NOT EXISTS total_disponible_miespacio INTEGER;

COMMENT ON COLUMN tb_cfe_busquedas.total_disponible_publico IS
    'Periodos disponibles en el portal publico CFE para el servicio (sin capar a max_periodos). NULL = no determinado.';
COMMENT ON COLUMN tb_cfe_busquedas.total_disponible_miespacio IS
    'Recibos disponibles en MiEspacio (Otras Facturas) para el servicio (sin capar). NULL = no determinado.';
