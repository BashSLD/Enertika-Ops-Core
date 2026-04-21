-- Agrega ID de incidencia opcional para plantas de O&M
ALTER TABLE public.tb_calculadora_plantas
    ADD COLUMN IF NOT EXISTS id_incidencia TEXT NULL;

CREATE INDEX IF NOT EXISTS idx_calc_plantas_id_incidencia
    ON public.tb_calculadora_plantas (id_incidencia)
    WHERE id_incidencia IS NOT NULL;
