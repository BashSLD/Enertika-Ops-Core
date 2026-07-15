-- Columna zona explícita en tb_cfe_servicios (filtro conmutable OYM: Mi zona / Zona 1 / Zona 2 / Todas)
-- Backfill desde la zona del creador para servicios oym existentes; simulacion queda con zona = NULL.
ALTER TABLE tb_cfe_servicios
    ADD COLUMN IF NOT EXISTS zona TEXT;

UPDATE tb_cfe_servicios s
SET zona = z.zona
FROM tb_oym_zonas_usuarios z
WHERE z.usuario_id = s.creado_por
  AND s.zona IS NULL
  AND 'oym' = ANY(s.modulos);
