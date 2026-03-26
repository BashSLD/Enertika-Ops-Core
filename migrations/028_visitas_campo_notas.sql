-- Migration 028: Agregar columna notas a tb_visitas_campo
-- Para el sub-módulo Visitas de Campo v2 (campo libre de texto por visita).

ALTER TABLE tb_visitas_campo
    ADD COLUMN IF NOT EXISTS notas TEXT;
