-- Migracion 043: evitar duplicidad de plantas vinculadas al mismo proyecto

CREATE UNIQUE INDEX IF NOT EXISTS idx_calculadora_plantas_id_proyecto_unique
ON public.tb_calculadora_plantas (id_proyecto)
WHERE id_proyecto IS NOT NULL;
