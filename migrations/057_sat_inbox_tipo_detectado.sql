-- Permite que el auto-match y el modal distingan CIERRE_ANTICIPO de facturas normales.
-- Registros existentes quedan con 'NORMAL' (comportamiento correcto por defecto).
ALTER TABLE tb_sat_inbox
ADD COLUMN IF NOT EXISTS tipo_detectado TEXT NOT NULL DEFAULT 'NORMAL';
