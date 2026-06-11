-- Guarda un aviso no-bloqueante de la busqueda de periodos (p. ej. discrepancia
-- de conteo entre portal publico y MiEspacio) para mostrarlo en los resultados.

ALTER TABLE tb_cfe_busquedas
ADD COLUMN IF NOT EXISTS advertencia TEXT;

COMMENT ON COLUMN tb_cfe_busquedas.advertencia IS
    'Aviso no-bloqueante de la busqueda (ej. discrepancia de conteo publico vs MiEspacio).';
