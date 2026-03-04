-- ============================================================
-- Migration 006: Fecha ideal del solicitante en Levantamientos
-- Descripcion: Agrega columna fecha_ideal_solicitante (TIMESTAMPTZ)
--              a tb_levantamientos para registrar cuándo el área
--              solicitante requiere que se realice el levantamiento.
--              Se combina con la hora opcionalmente ingresada en
--              el Paso 3 del formulario de notificación.
-- ============================================================

ALTER TABLE tb_levantamientos
    ADD COLUMN IF NOT EXISTS fecha_ideal_solicitante TIMESTAMP WITH TIME ZONE;

COMMENT ON COLUMN tb_levantamientos.fecha_ideal_solicitante IS
    'Fecha (y hora opcional) que el solicitante indica como ideal para realizar el levantamiento. '
    'Se captura en el Paso 3 del formulario de notificación (campo fecha_ideal_usuario + hora_ideal_usuario).';
