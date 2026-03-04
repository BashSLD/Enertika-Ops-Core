-- 008: Add individual visit date per levantamiento in visita de campo

ALTER TABLE tb_visita_campo_levantamientos
    ADD COLUMN IF NOT EXISTS fecha_visita TIMESTAMPTZ;
