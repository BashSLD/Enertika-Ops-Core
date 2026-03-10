-- Migración 014: Agrega columna notificacion_ganada_at en tb_oportunidades
-- Registra cuándo se envió la última notificación de "Oportunidad Ganada"

ALTER TABLE tb_oportunidades
    ADD COLUMN IF NOT EXISTS notificacion_ganada_at TIMESTAMPTZ NULL;
