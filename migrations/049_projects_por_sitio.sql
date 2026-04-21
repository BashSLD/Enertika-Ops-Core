-- Migracion 049: Proyectos por sitio (1 sitio ganado = 1 proyecto)

-- 1) Extender modelo de proyectos con referencia a sitio
ALTER TABLE public.tb_proyectos_gate
    ADD COLUMN IF NOT EXISTS id_sitio UUID;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'tb_proyectos_gate_id_sitio_fkey'
    ) THEN
        ALTER TABLE public.tb_proyectos_gate
            ADD CONSTRAINT tb_proyectos_gate_id_sitio_fkey
            FOREIGN KEY (id_sitio)
            REFERENCES public.tb_sitios_oportunidad(id_sitio);
    END IF;
END $$;

-- 2) Backfill id_sitio para proyectos existentes
-- Prioridad:
--   a) primer sitio en estatus Ganada
--   b) si no hay, primer sitio por fecha_carga ASC
WITH ganada AS (
    SELECT id
    FROM public.tb_cat_estatus_oportunidades
    WHERE lower(nombre) = 'ganada'
    ORDER BY id
    LIMIT 1
)
UPDATE public.tb_proyectos_gate p
SET id_sitio = (
    SELECT s.id_sitio
    FROM public.tb_sitios_oportunidad s
    LEFT JOIN ganada g ON TRUE
    WHERE s.id_oportunidad = p.id_oportunidad
    ORDER BY
        CASE WHEN g.id IS NOT NULL AND s.id_estatus_global = g.id THEN 0 ELSE 1 END,
        s.fecha_carga ASC,
        s.id_sitio ASC
    LIMIT 1
)
WHERE p.id_sitio IS NULL;

-- 3) Cambiar unicidad: de oportunidad -> sitio
ALTER TABLE public.tb_proyectos_gate
    DROP CONSTRAINT IF EXISTS tb_proyectos_id_oportunidad_key;

DROP INDEX IF EXISTS public.tb_proyectos_id_oportunidad_key;

CREATE UNIQUE INDEX IF NOT EXISTS uq_proyectos_gate_id_sitio
    ON public.tb_proyectos_gate (id_sitio)
    WHERE id_sitio IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_proyectos_gate_id_sitio
    ON public.tb_proyectos_gate (id_sitio);
