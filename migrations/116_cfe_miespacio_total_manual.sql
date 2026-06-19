-- Total ingresado manualmente por el usuario para el alta en MiEspacio.
-- Columna operacional separada del JSONB de diagnóstico.
ALTER TABLE tb_cfe_servicios
  ADD COLUMN IF NOT EXISTS miespacio_total_manual TEXT;
