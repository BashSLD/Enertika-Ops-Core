-- Permite tipos de notificacion definidos por cada modulo productor.

ALTER TABLE public.tb_notificaciones
    DROP CONSTRAINT IF EXISTS chk_tipo_notificacion;

COMMENT ON COLUMN public.tb_notificaciones.tipo IS
    'Tipo informativo de notificacion definido por el modulo productor.';
